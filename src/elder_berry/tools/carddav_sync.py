"""CardDAVSyncClient – CardDAV-Sync für Nextcloud Contacts.

Synchronisiert Kontakte zwischen dem lokalen ContactStore (SQLite) und
Nextcloud CardDAV. SQLite bleibt die primäre Datenquelle.

Sync-Richtungen:
    kontakte sync       → Pull (NC→lokal) + Push (lokal→NC)
    kontakte sync push  → Nur lokal→NC
    kontakte sync pull  → Nur NC→lokal

Credentials aus SecretStore (identisch mit Files + CalDAV):
    nextcloud_url, nextcloud_user, nextcloud_app_password
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.tools.contact_store import Contact, ContactStore

logger = logging.getLogger(__name__)

# DAV XML namespace
_DAV_NS = "DAV:"
_DAV = f"{{{_DAV_NS}}}"

_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<d:propfind xmlns:d="DAV:">'
    "<d:prop>"
    "<d:getetag/>"
    "<d:getcontenttype/>"
    "</d:prop>"
    "</d:propfind>"
)


# ── DTOs ───────────────────────────────────────────────────────────────


@dataclass
class SyncResult:
    """Ergebnis einer Sync-Operation."""

    pushed: int = 0
    pulled: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = []
        if self.pushed:
            parts.append(f"{self.pushed} gepusht")
        if self.pulled:
            parts.append(f"{self.pulled} gepullt")
        if self.conflicts:
            parts.append(f"{self.conflicts} Konflikte")
        if self.errors:
            parts.append(f"{len(self.errors)} Fehler")
        return ", ".join(parts) if parts else "keine Änderungen"


# ── Client ─────────────────────────────────────────────────────────────


class CardDAVSyncClient:
    """CardDAV-Sync-Client für Nextcloud Contacts."""

    def __init__(self, secret_store: SecretStore) -> None:
        self._url = secret_store.get_or_none("nextcloud_url")
        self._user = secret_store.get_or_none("nextcloud_user")
        self._password = secret_store.get_or_none("nextcloud_app_password")

    @property
    def _has_credentials(self) -> bool:
        return bool(self._url and self._user and self._password)

    @property
    def _carddav_base(self) -> str:
        """CardDAV base URL for the default addressbook."""
        url = (self._url or "").rstrip("/")
        return f"{url}/remote.php/dav/addressbooks/users/{self._user}/contacts/"

    @property
    def _auth(self) -> tuple[str, str]:
        return (self._user or "", self._password or "")

    def is_available(self) -> bool:
        """Prüft ob Credentials vorhanden und Server erreichbar."""
        if not self._has_credentials:
            return False
        try:
            resp = httpx.request(
                "PROPFIND",
                self._carddav_base,
                auth=self._auth,
                headers={
                    "Content-Type": "application/xml",
                    "Depth": "0",
                },
                content=_PROPFIND_BODY,
                timeout=10.0,
            )
            return resp.status_code in (200, 207)
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
        except Exception as exc:
            logger.warning("CardDAV availability check failed: %s", exc)
            return False

    # ── Push ───────────────────────────────────────────────────────────

    def push_contacts(self, contacts: list[Contact]) -> SyncResult:
        """Lokale Kontakte → Nextcloud (PUT vCards)."""
        result = SyncResult()
        if not contacts:
            return result
        if not self._has_credentials:
            result.errors.append("Keine Nextcloud-Credentials konfiguriert")
            return result

        for contact in contacts:
            uid = f"elderberry-contact-{contact.id}"
            try:
                vcard_str = self._contact_to_vcard(contact)
                url = f"{self._carddav_base}{uid}.vcf"
                resp = httpx.put(
                    url,
                    auth=self._auth,
                    headers={"Content-Type": "text/vcard; charset=utf-8"},
                    content=vcard_str.encode("utf-8"),
                    timeout=15.0,
                )
                if resp.status_code in (201, 204):
                    result.pushed += 1
                else:
                    result.errors.append(
                        f"PUT {contact.name}: HTTP {resp.status_code}"
                    )
            except Exception as exc:
                result.errors.append(f"PUT {contact.name}: {exc}")

        return result

    # ── Pull ───────────────────────────────────────────────────────────

    def pull_contacts(self, user_id: str) -> list[Contact]:
        """Nextcloud → lokale Contact-Objekte (PROPFIND + GET + Parse)."""
        if not self._has_credentials:
            return []

        # Schritt 1: Alle .vcf-Hrefs auflisten
        hrefs = self._list_vcf_hrefs()

        # Schritt 2: Jede vCard laden und parsen
        contacts = []
        for href in hrefs:
            try:
                url = self._href_to_url(href)
                resp = httpx.get(
                    url, auth=self._auth, timeout=15.0,
                )
                if resp.status_code != 200:
                    continue
                contact = self._vcard_to_contact(resp.text, user_id)
                if contact is not None:
                    contacts.append(contact)
            except Exception as exc:
                logger.warning("CardDAV GET %s fehlgeschlagen: %s", href, exc)

        return contacts

    # ── Sync (bidirektional) ───────────────────────────────────────────

    def sync(self, contact_store: ContactStore, user_id: str) -> SyncResult:
        """Bidirektionaler Sync: Pull + Merge + Push."""
        result = SyncResult()

        # Lokale und Remote-Kontakte laden
        local_contacts = contact_store.list_all(user_id, limit=1000)
        remote_contacts = self.pull_contacts(user_id)

        # Index aufbauen: Name (lowercase) → Contact
        local_by_name: dict[str, Contact] = {
            c.name.lower(): c for c in local_contacts
        }
        # UID-basiertes Matching: elderberry-contact-{id}
        local_by_uid: dict[str, Contact] = {
            f"elderberry-contact-{c.id}": c for c in local_contacts
        }

        remote_by_name: dict[str, Contact] = {}
        remote_uids: dict[str, Contact] = {}
        for rc in remote_contacts:
            remote_by_name[rc.name.lower()] = rc
            # UID aus notes extrahieren wenn vorhanden (vom Push gesetzt)
            # Remote-Kontakte haben id=0, aber ggf. eine UID im Feld
            remote_uids[rc.name.lower()] = rc

        # Kontakte die nur lokal existieren → Push
        to_push: list[Contact] = []
        for name_lower, local_c in local_by_name.items():
            if name_lower not in remote_by_name:
                to_push.append(local_c)

        # Kontakte die nur remote existieren → Pull (Add lokal)
        for name_lower, remote_c in remote_by_name.items():
            if name_lower not in local_by_name:
                contact_store.add(
                    user_id,
                    name=remote_c.name,
                    email=remote_c.email,
                    role=remote_c.role,
                    formality=remote_c.formality,
                    notes=remote_c.notes,
                    birthday=remote_c.birthday,
                    phone=remote_c.phone,
                )
                result.pulled += 1

        # Kontakte die auf beiden Seiten existieren → Vergleich
        for name_lower in local_by_name:
            if name_lower not in remote_by_name:
                continue
            local_c = local_by_name[name_lower]
            remote_c = remote_by_name[name_lower]

            # Vergleich: updated_at (lokal) vs. now (remote hat kein Timestamp)
            # Bei Gleichstand: lokal gewinnt (SQLite ist primär)
            # Einfache Heuristik: Wenn Felder sich unterscheiden,
            # lokal gewinnt (Push), da SQLite primäre Quelle ist
            if self._contacts_differ(local_c, remote_c):
                to_push.append(local_c)
                result.conflicts += 1

        # Push ausführen
        if to_push:
            push_result = self.push_contacts(to_push)
            result.pushed = push_result.pushed
            result.errors.extend(push_result.errors)

        return result

    # ── vCard-Konvertierung ────────────────────────────────────────────

    def _contact_to_vcard(self, contact: Contact) -> str:
        """Konvertiert Contact → vCard 3.0 String."""
        import vobject

        card = vobject.vCard()
        card.add("fn").value = contact.name
        card.add("uid").value = f"elderberry-contact-{contact.id}"
        card.add("rev").value = contact.updated_at.strftime("%Y%m%dT%H%M%SZ")

        if contact.email:
            card.add("email").value = contact.email

        if contact.phone:
            tel = card.add("tel")
            tel.value = contact.phone
            tel.type_param = "CELL"

        if contact.birthday:
            bday = card.add("bday")
            if contact.birthday.startswith("0000-"):
                # Jahr unbekannt → --MM-DD (vCard partial date)
                bday.value = "--" + contact.birthday[5:]
            else:
                bday.value = contact.birthday

        if contact.notes or contact.role:
            note_parts = []
            if contact.role:
                note_parts.append(f"Rolle: {contact.role}")
            if contact.notes:
                note_parts.append(contact.notes)
            card.add("note").value = "\n".join(note_parts)

        if contact.formality:
            card.add("x-elderberry-formality").value = contact.formality

        return card.serialize()

    def _vcard_to_contact(self, vcard_str: str, user_id: str) -> Contact | None:
        """Parst vCard-String → Contact (ohne DB-ID)."""
        import vobject
        from elder_berry.tools.contact_store import Contact

        try:
            card = vobject.readOne(vcard_str)
        except Exception as exc:
            logger.warning("vCard parse error: %s", exc)
            return None

        fn = str(getattr(card, "fn", None) and card.fn.value or "")
        if not fn:
            return None

        email = ""
        if hasattr(card, "email"):
            email = str(card.email.value)

        phone = ""
        if hasattr(card, "tel"):
            phone = str(card.tel.value)

        birthday = ""
        if hasattr(card, "bday"):
            bday_val = str(card.bday.value)
            if bday_val.startswith("--"):
                # Partial date → 0000-MM-DD
                birthday = "0000-" + bday_val[2:]
            else:
                birthday = bday_val[:10]  # YYYY-MM-DD

        role = ""
        notes = ""
        if hasattr(card, "note"):
            note_text = str(card.note.value)
            lines = note_text.split("\n")
            remaining = []
            for line in lines:
                if line.startswith("Rolle: "):
                    role = line[7:]
                else:
                    remaining.append(line)
            notes = "\n".join(remaining).strip()

        formality = "förmlich"
        for child in card.getChildren():
            if child.name.upper() == "X-ELDERBERRY-FORMALITY":
                formality = str(child.value)
                break

        now = datetime.now(timezone.utc)
        return Contact(
            id=0,
            user_id=user_id,
            name=fn,
            email=email,
            role=role,
            formality=formality,
            phone=phone,
            notes=notes,
            birthday=birthday,
            created_at=now,
            updated_at=now,
        )

    # ── Hilfsmethoden ──────────────────────────────────────────────────

    def _list_vcf_hrefs(self) -> list[str]:
        """PROPFIND auf CardDAV-URL → Liste von .vcf-Hrefs."""
        try:
            resp = httpx.request(
                "PROPFIND",
                self._carddav_base,
                auth=self._auth,
                headers={
                    "Content-Type": "application/xml",
                    "Depth": "1",
                },
                content=_PROPFIND_BODY,
                timeout=10.0,
            )
            if resp.status_code not in (200, 207):
                return []
        except Exception as exc:
            logger.warning("CardDAV PROPFIND fehlgeschlagen: %s", exc)
            return []

        hrefs = []
        try:
            root = ET.fromstring(resp.text)
            for response in root.findall(f"{_DAV}response"):
                href_el = response.find(f"{_DAV}href")
                if href_el is not None and href_el.text:
                    href = href_el.text
                    if href.endswith(".vcf"):
                        hrefs.append(href)
        except ET.ParseError as exc:
            logger.warning("CardDAV XML parse error: %s", exc)

        return hrefs

    def _href_to_url(self, href: str) -> str:
        """Konvertiert einen relativen href in eine absolute URL."""
        url = (self._url or "").rstrip("/")
        if href.startswith("http"):
            return href
        return f"{url}{href}"

    @staticmethod
    def _contacts_differ(local: Contact, remote: Contact) -> bool:
        """Prüft ob sich zwei Kontakte in den sync-relevanten Feldern unterscheiden."""
        return (
            local.email != remote.email
            or local.phone != remote.phone
            or local.role != remote.role
            or local.notes != remote.notes
            or local.birthday != remote.birthday
            or local.formality != remote.formality
        )
