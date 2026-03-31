"""CardDAVSyncClient – CardDAV-Sync für Nextcloud Contacts.

Synchronisiert Kontakte zwischen dem lokalen ContactStore (SQLite) und
Nextcloud CardDAV. Nextcloud ist die Datenquelle für alle vCard-Felder,
Elder-Berry ist die Quelle für eigene Metadaten (role, formality, notes).

Sync-Richtungen:
    kontakte sync       → Pull (NC→lokal) + Push (lokal→NC, nur EB-Felder)
    kontakte sync push  → Nur lokal→NC (EB-Felder in bestehende vCards)
    kontakte sync pull  → Nur NC→lokal
    kontakte sync reset → Alle lokal löschen + frischer Pull

Credentials aus SecretStore (identisch mit Files + CalDAV):
    nextcloud_url, nextcloud_user, nextcloud_app_password
"""
from __future__ import annotations

import json
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

# Elder-Berry-eigene Felder (werden aktiv nach NC gepusht)
_EB_FIELDS = {"role", "formality", "notes"}


# ── DTOs ───────────────────────────────────────────────────────────────


@dataclass
class SyncResult:
    """Ergebnis einer Sync-Operation."""

    pushed: int = 0
    pulled: int = 0
    updated: int = 0
    deleted: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = []
        if self.pushed:
            parts.append(f"{self.pushed} gepusht")
        if self.pulled:
            parts.append(f"{self.pulled} gepullt")
        if self.updated:
            parts.append(f"{self.updated} aktualisiert")
        if self.deleted:
            parts.append(f"{self.deleted} gelöscht")
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
        """Lokale Kontakte → Nextcloud.

        Für Kontakte MIT vcard_uid: bestehende vCard laden, EB-Felder
        einfügen, zurückschreiben (kein Duplikat!).
        Für Kontakte OHNE vcard_uid: neue vCard mit elderberry-UID anlegen.
        """
        result = SyncResult()
        if not contacts:
            return result
        if not self._has_credentials:
            result.errors.append("Keine Nextcloud-Credentials konfiguriert")
            return result

        for contact in contacts:
            try:
                if contact.vcard_uid:
                    # Bestehende NC-vCard aktualisieren
                    ok = self._update_existing_vcard(contact)
                else:
                    # Neue vCard anlegen
                    ok = self._create_new_vcard(contact)
                if ok:
                    result.pushed += 1
            except Exception as exc:
                result.errors.append(f"PUT {contact.name}: {exc}")

        return result

    def _create_new_vcard(self, contact: Contact) -> bool:
        """Erstellt eine neue vCard auf Nextcloud."""
        uid = f"elderberry-contact-{contact.id}"
        vcard_str = self._contact_to_vcard(contact, uid=uid)
        url = f"{self._carddav_base}{uid}.vcf"
        resp = httpx.put(
            url,
            auth=self._auth,
            headers={"Content-Type": "text/vcard; charset=utf-8"},
            content=vcard_str.encode("utf-8"),
            timeout=15.0,
        )
        if resp.status_code in (201, 204):
            return True
        logger.warning("PUT new vCard %s: HTTP %d", contact.name, resp.status_code)
        return False

    def _update_existing_vcard(self, contact: Contact) -> bool:
        """Lädt bestehende vCard, fügt EB-Felder ein, schreibt zurück."""
        # Finde die richtige vcf-URL anhand der UID
        href = self._find_vcard_href(contact.vcard_uid)
        if not href:
            logger.warning(
                "vCard für UID %s nicht gefunden, erstelle neue",
                contact.vcard_uid,
            )
            return self._create_new_vcard(contact)

        url = self._href_to_url(href)

        # vCard laden
        resp = httpx.get(url, auth=self._auth, timeout=15.0)
        if resp.status_code != 200:
            logger.warning("GET vCard %s: HTTP %d", href, resp.status_code)
            return False

        # EB-Felder in bestehende vCard einfügen
        updated_vcard = self._inject_eb_fields(resp.text, contact)

        # Zurückschreiben
        resp = httpx.put(
            url,
            auth=self._auth,
            headers={"Content-Type": "text/vcard; charset=utf-8"},
            content=updated_vcard.encode("utf-8"),
            timeout=15.0,
        )
        if resp.status_code in (200, 201, 204):
            return True
        logger.warning("PUT updated vCard %s: HTTP %d", href, resp.status_code)
        return False

    def _inject_eb_fields(self, vcard_str: str, contact: Contact) -> str:
        """Fügt Elder-Berry-Felder (NOTE, X-ELDERBERRY-*) in bestehende vCard ein."""
        import vobject

        try:
            card = vobject.readOne(vcard_str)
        except Exception:
            return vcard_str

        # NOTE: Rolle + Notizen
        note_parts = []
        if contact.role:
            note_parts.append(f"Rolle: {contact.role}")
        if contact.notes:
            note_parts.append(contact.notes)
        if note_parts:
            if hasattr(card, "note"):
                card.note.value = "\n".join(note_parts)
            else:
                card.add("note").value = "\n".join(note_parts)
        elif hasattr(card, "note"):
            card.remove(card.note)

        # X-ELDERBERRY-FORMALITY
        for child in list(card.getChildren()):
            if child.name.upper() == "X-ELDERBERRY-FORMALITY":
                card.remove(child)
        if contact.formality:
            card.add("x-elderberry-formality").value = contact.formality

        return card.serialize()

    # ── Pull ───────────────────────────────────────────────────────────

    def pull_contacts(self, user_id: str) -> list[dict]:
        """Nextcloud → lokale Contact-Daten (PROPFIND + GET + Parse).

        Returns:
            Liste von Dicts mit allen Contact-Feldern (kein Contact-Objekt,
            da die caller add_or_update_by_vcard_uid() verwenden).
        """
        if not self._has_credentials:
            return []

        hrefs = self._list_vcf_hrefs()
        contacts = []
        for href in hrefs:
            try:
                url = self._href_to_url(href)
                resp = httpx.get(
                    url, auth=self._auth, timeout=15.0,
                )
                if resp.status_code != 200:
                    continue
                data = self._vcard_to_dict(resp.text, user_id)
                if data is not None:
                    contacts.append(data)
            except Exception as exc:
                logger.warning("CardDAV GET %s fehlgeschlagen: %s", href, exc)

        return contacts

    def reset_and_pull(
        self, contact_store: ContactStore, user_id: str,
    ) -> SyncResult:
        """Löscht alle lokalen Kontakte und zieht frischen Stand von NC.

        Für Clean-Slate-Migration nach Schema-Änderung.
        """
        result = SyncResult()
        deleted = contact_store.delete_all(user_id)
        result.deleted = deleted
        logger.info("Reset: %d lokale Kontakte gelöscht", deleted)

        remote_data = self.pull_contacts(user_id)
        for data in remote_data:
            try:
                contact_store.add_or_update_by_vcard_uid(
                    user_id, vcard_uid=data.pop("vcard_uid", ""),
                    **data,
                )
                result.pulled += 1
            except Exception as exc:
                result.errors.append(f"Pull {data.get('name', '?')}: {exc}")

        return result

    # ── Sync (bidirektional) ───────────────────────────────────────────

    def sync(self, contact_store: ContactStore, user_id: str) -> SyncResult:
        """Bidirektionaler Sync: Pull NC→lokal, Push EB-Felder→NC.

        Sync-Strategie:
        - NC ist Quelle der Wahrheit für vCard-Felder
        - EB ist Quelle der Wahrheit für role, formality, notes
        - Pull: alle NC-Felder überschreiben lokale NC-Felder
        - Push: nur EB-Felder werden in bestehende NC-vCards eingefügt
        """
        result = SyncResult()

        # Phase 1: Pull (NC → lokal)
        remote_data = self.pull_contacts(user_id)
        remote_uids: set[str] = set()
        for data in remote_data:
            vcard_uid = data.pop("vcard_uid", "")
            if vcard_uid:
                remote_uids.add(vcard_uid)
            try:
                name = data.get("name", "")
                # Prüfe ob lokal vorhanden (per UID oder Name)
                existing = None
                if vcard_uid:
                    existing = contact_store.find_by_vcard_uid(
                        user_id, vcard_uid,
                    )
                if not existing and name:
                    existing = contact_store.find_by_name(user_id, name)

                if existing:
                    # NC-Felder aktualisieren, EB-Felder behalten
                    update_data = {k: v for k, v in data.items()
                                   if k not in _EB_FIELDS}
                    update_data["vcard_uid"] = vcard_uid
                    contact_store.update(existing.id, **update_data)
                    result.updated += 1
                else:
                    contact_store.add_or_update_by_vcard_uid(
                        user_id, vcard_uid=vcard_uid, **data,
                    )
                    result.pulled += 1
            except Exception as exc:
                result.errors.append(
                    f"Pull {data.get('name', '?')}: {exc}",
                )

        # Phase 2: Push EB-Felder (lokal → NC)
        local_contacts = contact_store.list_all(user_id, limit=1000)
        to_push = [
            c for c in local_contacts
            if c.vcard_uid and (c.role or c.notes or c.formality != "förmlich")
        ]
        if to_push:
            push_result = self.push_contacts(to_push)
            result.pushed = push_result.pushed
            result.errors.extend(push_result.errors)

        return result

    # ── vCard-Konvertierung ────────────────────────────────────────────

    @staticmethod
    def _contact_to_vcard(contact: Contact, uid: str = "") -> str:
        """Konvertiert Contact → vCard 3.0 String (für neue Kontakte)."""
        import vobject

        card = vobject.vCard()
        card.add("fn").value = contact.name
        card.add("uid").value = uid or f"elderberry-contact-{contact.id}"
        card.add("rev").value = contact.updated_at.strftime("%Y%m%dT%H%M%SZ")

        # Mehrere Emails
        for ei in contact.get_emails_list():
            em = card.add("email")
            em.value = ei.get("email", "")
            em.type_param = ei.get("type", "INTERNET").upper()

        # Mehrere Telefonnummern
        for pi in contact.get_phones_list():
            tel = card.add("tel")
            tel.value = pi.get("number", "")
            tel.type_param = pi.get("type", "CELL").upper()

        if contact.birthday:
            bday = card.add("bday")
            if contact.birthday.startswith("0000-"):
                bday.value = "--" + contact.birthday[5:]
            else:
                bday.value = contact.birthday

        if contact.address:
            adr = card.add("adr")
            adr.value = vobject.vcard.Address(street=contact.address)

        if contact.organization:
            card.add("org").value = [contact.organization]

        if contact.title:
            card.add("title").value = contact.title

        if contact.categories:
            cats = [c.strip() for c in contact.categories.split(",")]
            card.add("categories").value = cats

        if contact.nickname:
            card.add("nickname").value = contact.nickname

        if contact.anniversary:
            card.add("anniversary").value = contact.anniversary

        if contact.url:
            card.add("url").value = contact.url

        # EB-spezifische Felder
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

    @staticmethod
    def _vcard_to_dict(vcard_str: str, user_id: str) -> dict | None:
        """Parst vCard-String → Dict mit allen Contact-Feldern."""
        import vobject

        try:
            card = vobject.readOne(vcard_str)
        except Exception as exc:
            logger.warning("vCard parse error: %s", exc)
            return None

        fn = str(getattr(card, "fn", None) and card.fn.value or "")
        if not fn:
            return None

        # UID
        vcard_uid = ""
        if hasattr(card, "uid"):
            vcard_uid = str(card.uid.value)

        # Mehrere Emails → JSON
        emails = []
        for em in card.contents.get("email", []):
            email_type = "home"
            if hasattr(em, "params") and "TYPE" in em.params:
                email_type = em.params["TYPE"][0].lower()
            emails.append({"type": email_type, "email": str(em.value)})

        # Mehrere Telefonnummern → JSON
        phones = []
        for tel in card.contents.get("tel", []):
            phone_type = "cell"
            if hasattr(tel, "params") and "TYPE" in tel.params:
                # TYPE kann mehrere Werte haben (z.B. CELL,VOICE)
                types = [t.lower() for t in tel.params["TYPE"]]
                # Bevorzuge spezifische Typen
                for preferred in ("cell", "mobile", "home", "work"):
                    if preferred in types:
                        phone_type = preferred
                        break
                else:
                    phone_type = types[0] if types else "cell"
            phones.append({"type": phone_type, "number": str(tel.value)})

        # Birthday
        birthday = ""
        if hasattr(card, "bday"):
            bday_val = str(card.bday.value)
            if bday_val.startswith("--"):
                birthday = "0000-" + bday_val[2:]
            else:
                birthday = bday_val[:10]

        # Address (ADR → Freitext)
        address = ""
        if hasattr(card, "adr"):
            adr = card.adr.value
            parts = []
            if hasattr(adr, "street") and adr.street:
                parts.append(adr.street)
            code_city = []
            if hasattr(adr, "code") and adr.code:
                code_city.append(adr.code)
            if hasattr(adr, "city") and adr.city:
                code_city.append(adr.city)
            if code_city:
                parts.append(" ".join(code_city))
            if hasattr(adr, "region") and adr.region:
                parts.append(adr.region)
            if hasattr(adr, "country") and adr.country:
                parts.append(adr.country)
            address = ", ".join(p for p in parts if p)

        # Organization
        organization = ""
        if hasattr(card, "org"):
            org_val = card.org.value
            if isinstance(org_val, list):
                organization = " / ".join(str(o) for o in org_val if o)
            else:
                organization = str(org_val)

        # Title
        title = ""
        if hasattr(card, "title"):
            title = str(card.title.value)

        # Categories
        categories = ""
        if hasattr(card, "categories"):
            cat_val = card.categories.value
            if isinstance(cat_val, list):
                categories = ", ".join(str(c) for c in cat_val)
            else:
                categories = str(cat_val)

        # Nickname
        nickname = ""
        if hasattr(card, "nickname"):
            nickname = str(card.nickname.value)

        # Anniversary
        anniversary = ""
        for child in card.getChildren():
            if child.name.upper() == "ANNIVERSARY":
                anniversary = str(child.value)[:10]
                break
            if child.name.upper() == "X-ANNIVERSARY":
                anniversary = str(child.value)[:10]
                break

        # URL
        url = ""
        if hasattr(card, "url"):
            url = str(card.url.value)

        # NOTE → role + notes (EB-Felder)
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

        # Formality (EB-Feld)
        formality = "förmlich"
        for child in card.getChildren():
            if child.name.upper() == "X-ELDERBERRY-FORMALITY":
                formality = str(child.value)
                break

        return {
            "name": fn,
            "emails": json.dumps(emails) if emails else "[]",
            "phones": json.dumps(phones) if phones else "[]",
            "role": role,
            "formality": formality,
            "notes": notes,
            "birthday": birthday,
            "address": address,
            "organization": organization,
            "title": title,
            "categories": categories,
            "nickname": nickname,
            "anniversary": anniversary,
            "url": url,
            "vcard_uid": vcard_uid,
        }

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

    def _find_vcard_href(self, vcard_uid: str) -> str | None:
        """Sucht die .vcf-Href anhand der vCard-UID.

        Lädt alle hrefs und vergleicht mit der bekannten UID.
        Optimierung: UID ist oft der Dateiname.
        """
        # Schneller Versuch: UID als Dateiname
        # Nextcloud nutzt oft {UID}.vcf als Dateinamen
        hrefs = self._list_vcf_hrefs()
        for href in hrefs:
            filename = href.rsplit("/", 1)[-1].replace(".vcf", "")
            if filename == vcard_uid:
                return href

        # Langsamer Fallback: Jede vCard laden und UID vergleichen
        for href in hrefs:
            try:
                url = self._href_to_url(href)
                resp = httpx.get(url, auth=self._auth, timeout=10.0)
                if resp.status_code != 200:
                    continue
                if f"UID:{vcard_uid}" in resp.text:
                    return href
            except Exception:
                continue

        return None

    def _href_to_url(self, href: str) -> str:
        """Konvertiert einen relativen href in eine absolute URL."""
        url = (self._url or "").rstrip("/")
        if href.startswith("http"):
            return href
        return f"{url}{href}"
