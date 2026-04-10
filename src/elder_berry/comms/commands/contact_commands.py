"""ContactCommandHandler – Kontaktbuch-Commands.

Commands:
- kontakt: Name, Rolle, Email, Anrede       → Kontakt anlegen/aktualisieren
- kontakt ändern #ID: Feld=Wert             → Kontakt bearbeiten
- kontakt #ID Feld: Wert                    → Kontakt bearbeiten (LLM-Variante)
- wer ist <Name>?                           → Kontakt abrufen
- kontakte                                   → Alle Kontakte auflisten
- kontakte suche <Begriff>                   → Volltextsuche
- kontakt löschen #<ID>                      → Per ID löschen
- kontakt löschen <Name>                     → Per Name löschen
- kontakte sync [push|pull|reset]            → CardDAV-Sync
- wann hat <Name> geburtstag?               → Feld-Abfrage
- was ist die adresse von <Name>?           → Feld-Abfrage
- kontakte gruppe <Name>                     → Gruppen-Listing
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.tools.carddav_sync import CardDAVSyncClient
    from elder_berry.tools.contact_store import Contact, ContactStore

logger = logging.getLogger(__name__)

CONTACT_SYNC_PATTERN = re.compile(
    r"^kontakte?\s+sync(?:\s+(push|pull|reset))?\s*$",
    re.IGNORECASE,
)

CONTACT_ADD_PATTERN = re.compile(
    r"^(?:neuer?\s+)?kontakt[:\s]+(?!ändern\b|bearbeiten\b|update\b|löschen\b|lösche\b|suche?\b|sync\b)(.+)$",
    re.IGNORECASE,
)

CONTACT_ADD_NATURAL_PATTERN = re.compile(
    r"^(?:(?:füge|nimm|trag)\s+(.+?)\s+(?:in\s+(?:meine?\s+)?kontakte|als\s+kontakt)\s*(?:auf|hinzu|ein)?"
    r"|(?:speicher|merke?|notier)\s+(?:dir\s+)?(.+?)\s+als\s+kontakt"
    r"|(?:erstell|leg|mach)\s+(?:einen?\s+)?(?:neuen?\s+)?kontakt\s+(?:für\s+|von\s+)?(.+?))\s*$",
    re.IGNORECASE,
)

CONTACT_UPDATE_PATTERN = re.compile(
    r"kontakt\s+(?:(?:ändern|bearbeiten|update)\s+)?(?:"
    r"#?(\d+)[:\s]+"              # Branch 1: numerische ID (#118 oder 118)
    r"|#([\w]+)\s*:\s*"           # Branch 2: #Name gefolgt von : (#lisa:)
    r")(.+)",
    re.IGNORECASE,
)

CONTACT_WHO_PATTERN = re.compile(
    r"^wer\s+ist\s+(.+?)\??\s*$", re.IGNORECASE,
)

CONTACT_LOOKUP_PATTERN = re.compile(
    r"^(?:was\s+wei(?:ss|ß)t?\s+du\s+(?:zu|über)\s+(?:(?:meinen?|den|dem)\s+)?(?:kontakt\s+)?(.+?)"
    r"|(?:zeig|info|details)\s+(?:mir\s+)?(?:zu\s+|von\s+)?(?:kontakt\s+)?(.+?)"
    r"|kontakt\s+(?:info\s+)?(?:#(\d+)|(\S+.+?)))\??\s*$",
    re.IGNORECASE,
)

CONTACT_SEARCH_PATTERN = re.compile(
    r"^kontakte?\s+suche?\s+(.+)$", re.IGNORECASE,
)

CONTACT_DELETE_PATTERN = re.compile(
    r"^kontakte?\s+(?:löschen|lösche|entferne?)\s+(?:#(\d+)|(.+))$",
    re.IGNORECASE,
)

# Natürliche Feld-Abfragen
# Neu: "geburtstag von Max", "wann ist Annas geburtstag" (Genitiv-s)
CONTACT_FIELD_QUERY_PATTERN = re.compile(
    r"^(?:wann\s+hat\s+(.+?)\s+geburtstag"
    r"|wann\s+ist\s+(.+?)s?\s+geburtstag"
    r"|geburtstag\s+(?:von\s+)?(.+?)"
    r"|(?:was|wie)\s+ist\s+(?:die\s+)?(?:adresse|anschrift)\s+von\s+(.+?)"
    r"|(?:was|wie)\s+ist\s+(?:die\s+)?(?:telefonnummer|nummer|handynummer)\s+von\s+(.+?)"
    r"|(?:was|wie)\s+ist\s+(?:die\s+)?(?:email|e-mail|mailadresse)\s+von\s+(.+?)"
    r"|(?:was|wie)\s+ist\s+(?:die\s+)?(?:adresse|anschrift)\s+von\s+(.+?)"
    r"|in\s+welcher\s+gruppe\s+ist\s+(.+?)"
    r"|wo\s+(?:arbeitet|wohnt)\s+(.+?))\??\s*$",
    re.IGNORECASE,
)

# Gruppen-Abfrage
CONTACT_GROUP_PATTERN = re.compile(
    r"^kontakte?\s+(?:gruppe|kategorie|group)\s+(.+)$",
    re.IGNORECASE,
)

_FORMALITY_FOERMLICH = {"förmlich", "formell", "sie", "höflich", "distanziert"}
_FORMALITY_LOCKER = {"locker", "informell", "du", "persönlich", "freundschaftlich",
                      "casual", "vertraut", "familiär"}


_FIELD_ALIASES: dict[str, str] = {
    "name": "name",
    "email": "emails", "mail": "emails", "e-mail": "emails", "emails": "emails",
    "rolle": "role", "role": "role", "beziehung": "role",
    "anrede": "formality", "formality": "formality",
    "notizen": "notes", "notes": "notes", "notiz": "notes",
    "vermerk": "notes", "anmerkung": "notes",
    "geburtstag": "birthday", "birthday": "birthday",
    "telefon": "phones", "phone": "phones", "phones": "phones",
    "tel": "phones", "nummer": "phones", "handy": "phones",
    "mobil": "phones", "telefonnummer": "phones", "handynummer": "phones",
    "adresse": "address", "address": "address", "anschrift": "address",
    "organisation": "organization", "organization": "organization",
    "firma": "organization", "unternehmen": "organization",
    "titel": "title", "title": "title", "jobtitel": "title",
    "position": "title",
    "gruppe": "categories", "gruppen": "categories",
    "kategorie": "categories", "kategorien": "categories",
    "categories": "categories",
    "spitzname": "nickname", "nickname": "nickname",
    "jahrestag": "anniversary", "anniversary": "anniversary",
    "hochzeitstag": "anniversary",
    "website": "url", "url": "url", "webseite": "url",
    "homepage": "url",
    "vcard_uid": "vcard_uid",
}

_ALLOWED_FIELDS_DISPLAY = (
    "name, email, telefon, rolle, anrede, notizen, geburtstag, "
    "adresse, firma, titel, gruppe, spitzname, jahrestag, website"
)

# Mapping Feld-Abfrage-Typ → menschenlesbarer Name
_FIELD_QUERY_LABELS: dict[str, str] = {
    "birthday": "Geburtstag",
    "address": "Adresse",
    "phones": "Telefonnummer",
    "emails": "Email",
    "categories": "Gruppen",
    "organization": "Arbeitgeber",
}


class ContactCommandHandler(CommandHandler):
    """Kontaktbuch-Commands für Matrix."""

    def __init__(self, contact_store: ContactStore | None = None,
                 default_user_id: str = "",
                 carddav_sync: CardDAVSyncClient | None = None) -> None:
        self._store = contact_store
        self._default_user_id = default_user_id
        self._carddav_sync = carddav_sync

    @property
    def simple_commands(self) -> set[str]:
        return {"kontakte"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (CONTACT_SYNC_PATTERN, "contact_sync", False, False),
            (CONTACT_UPDATE_PATTERN, "contact_update", False, True),
            (CONTACT_DELETE_PATTERN, "contact_delete", False, False),
            (CONTACT_FIELD_QUERY_PATTERN, "contact_field_query", False, False),
            (CONTACT_GROUP_PATTERN, "contact_group", False, False),
            (CONTACT_WHO_PATTERN, "contact_who", False, False),
            (CONTACT_LOOKUP_PATTERN, "contact_lookup", False, False),
            (CONTACT_SEARCH_PATTERN, "contact_search", False, False),
            (CONTACT_ADD_NATURAL_PATTERN, "contact_add_natural", False, False),
            (CONTACT_ADD_PATTERN, "contact_add", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "kontakte": [
                "kontakte", "adressbuch", "kontaktliste",
                "meine kontakte", "alle kontakte",
            ],
            "contact_add": [
                "neuer kontakt", "kontakt speichern",
                "kontakt anlegen", "kontakt hinzufügen",
            ],
            "contact_who": [
                "wer ist", "kennst du",
            ],
            "contact_search": [
                "kontakt suche", "kontakt finden",
                "finde kontakt", "suche kontakt",
            ],
            "contact_delete": [
                "kontakt löschen", "kontakt entfernen",
                "lösche kontakt",
            ],
            "contact_update": [
                "kontakt ändern", "kontakt bearbeiten",
                "kontakt aktualisieren",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "kontakt: Name, Rolle, Email, Anrede – Kontakt anlegen",
            "kontakt ändern #<ID>: feld=wert – Kontakt bearbeiten (z.B. kontakt ändern #118: adresse=Musterstr. 1)",
            "wer ist <Name>? – Kontakt abrufen",
            "wann hat <Name> geburtstag? – Geburtstag abfragen",
            "was ist die adresse von <Name>? – Adresse abfragen",
            "kontakte – Alle Kontakte auflisten",
            "kontakte suche <Begriff> – Kontakt suchen",
            "kontakte gruppe <Name> – Kontakte einer Gruppe anzeigen",
            "kontakt löschen #<ID> – Kontakt löschen",
            "kontakte sync – Kontakte mit Nextcloud synchronisieren",
            "kontakte sync push – Nur lokal → Nextcloud",
            "kontakte sync pull – Nur Nextcloud → lokal",
            "kontakte sync reset – Alles löschen + frischer Pull",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        """Führt einen Kontakt-Command aus."""
        if not self._store:
            return self.not_configured(command, "Kontaktbuch")
        dispatch = {
            "kontakte": self._cmd_list,
            "contact_add": self._cmd_add,
            "contact_add_natural": self._cmd_add_natural,
            "contact_update": self._cmd_update,
            "contact_who": self._cmd_who,
            "contact_lookup": self._cmd_lookup,
            "contact_search": self._cmd_search,
            "contact_delete": self._cmd_delete,
            "contact_sync": self._cmd_sync,
            "contact_field_query": self._cmd_field_query,
            "contact_group": self._cmd_group,
        }
        handler = dispatch.get(command)
        if handler:
            return handler(raw_text)
        return CommandResult(command=command, success=False,
                             text=f"Unbekannter Command: {command}")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _cmd_add(self, raw_text: str) -> CommandResult:
        match = CONTACT_ADD_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="contact_add", success=False,
                                 text="Format: kontakt: Name, Rolle, Email, Anrede")
        fields = self._parse_contact_fields(match.group(1))
        if not fields or not fields.get("name"):
            return CommandResult(command="contact_add", success=False,
                                 text="Mindestens ein Name ist nötig.")
        user_id = self._default_user_id
        contact = self._store.add(
            user_id, name=fields.pop("name"), **fields,
        )
        return CommandResult(
            command="contact_add", success=True,
            text=f"📇 Kontakt gespeichert: {contact.format_short()}",
        )

    def _cmd_add_natural(self, raw_text: str) -> CommandResult:
        match = CONTACT_ADD_NATURAL_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="contact_add_natural", success=False,
                                 text="Format: kontakt: Name, Rolle, Email, Anrede")
        name = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        if not name:
            return CommandResult(command="contact_add_natural", success=False,
                                 text="Mindestens ein Name ist nötig.")
        fields = self._parse_contact_fields(name)
        user_id = self._default_user_id
        contact = self._store.add(
            user_id, name=fields.pop("name"), **fields,
        )
        return CommandResult(
            command="contact_add_natural", success=True,
            text=f"📇 Kontakt gespeichert: {contact.format_short()}",
        )

    def _cmd_update(self, raw_text: str) -> CommandResult:
        match = CONTACT_UPDATE_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(command="contact_update", success=False,
                                 text="Format: kontakt ändern #ID: feld=wert")
        id_str = match.group(1)   # Branch 1: numerische ID
        name_str = match.group(2)  # Branch 2: Name nach #
        fields_raw = match.group(3).strip()

        # Kontakt auflösen: per ID oder per Name
        if id_str:
            contact = self._store.get_by_id(int(id_str))
        else:
            contact = self._find_contact_for_query(name_str)
        if not contact:
            label = f"#{id_str}" if id_str else f"'{name_str}'"
            return CommandResult(command="contact_update", success=False,
                                 text=f"Kontakt {label} nicht gefunden.")

        updates: dict[str, str] = {}
        warnings: list[str] = []
        parsed = self._parse_field_assignments(fields_raw)
        for raw_key, val in parsed:
            resolved = self._resolve_field_key(raw_key.strip())
            if resolved:
                updates[resolved] = val.strip()
            else:
                warnings.append(
                    f"⚠️ Unbekanntes Feld '{raw_key.strip()}' ignoriert. "
                    f"Erlaubt: {_ALLOWED_FIELDS_DISPLAY}"
                )
        if not updates and not warnings:
            return CommandResult(
                command="contact_update", success=False,
                text=None, fallthrough=True,
            )
        contact_id = contact.id
        contact = self._store.update(contact_id, **updates)
        if not contact:
            return CommandResult(command="contact_update", success=False,
                                 text=f"Kontakt #{contact_id} nicht gefunden.")
        text = f"📇 Aktualisiert: {contact.format_short()}"
        if warnings:
            text += "\n" + "\n".join(warnings)
        return CommandResult(
            command="contact_update", success=True, text=text,
        )

    @staticmethod
    def _parse_field_assignments(fields_raw: str) -> list[tuple[str, str]]:
        """Parst Feld-Zuweisungen aus verschiedenen Formaten.

        Unterstützt:
        - feld=wert, feld2=wert2   (klassisch)
        - feld: wert               (LLM-Variante, Wert darf Kommas enthalten)
        """
        results: list[tuple[str, str]] = []
        if "=" in fields_raw:
            # Mehrere Felder: feld1=wert1, feld2=wert2
            # Einzelnes Feld: feld=wert (Kommas im Wert erhalten)
            eq_count = fields_raw.count("=")
            if eq_count == 1:
                raw_key, val = fields_raw.split("=", 1)
                results.append((raw_key, val))
            else:
                for part in fields_raw.split(","):
                    if "=" in part:
                        raw_key, val = part.split("=", 1)
                        results.append((raw_key, val))
            return results
        # Fallback: feld: wert (einzelnes Feld, Wert darf Kommas enthalten)
        colon_match = re.match(r"(\w+)\s*:\s*(.+)", fields_raw, re.DOTALL)
        if colon_match:
            results.append((colon_match.group(1), colon_match.group(2)))
        return results

    @staticmethod
    def _resolve_field_key(raw_key: str) -> str | None:
        """Löst Feld-Aliase auf. Bei Tippfehler: bester startswith-Match oder None."""
        lower = raw_key.lower().strip()
        if lower in _FIELD_ALIASES:
            return _FIELD_ALIASES[lower]
        for alias in _FIELD_ALIASES:
            if alias.startswith(lower) or lower.startswith(alias):
                return _FIELD_ALIASES[alias]
        return None

    def _find_contact_fuzzy(self, name: str, command: str) -> CommandResult:
        """Sucht Kontakt: exakt → 1 Treffer direkt, mehrere → Rückfrage."""
        user_id = self._default_user_id
        exact = self._store.find_by_name(user_id, name)
        if exact:
            return CommandResult(command=command, success=True,
                                 text=exact.format_detail())
        results = self._store.search(user_id, name, limit=5)
        if len(results) == 1:
            return CommandResult(command=command, success=True,
                                 text=results[0].format_detail())
        if len(results) > 1:
            lines = [f"📇 {len(results)} Kontakte gefunden – welchen meinst du?"]
            for c in results:
                lines.append(f"  {c.format_short()}")
            return CommandResult(command=command, success=True, text="\n".join(lines))
        return CommandResult(command=command, success=False,
                             text=None, fallthrough=True)

    def _find_contact_for_query(self, name: str) -> Contact | None:
        """Sucht Kontakt für Feld-Abfragen: exakt → direkt, FTS → 1 Treffer."""
        user_id = self._default_user_id
        exact = self._store.find_by_name(user_id, name)
        if exact:
            return exact
        results = self._store.search(user_id, name, limit=2)
        if len(results) == 1:
            return results[0]
        return None

    def _cmd_who(self, raw_text: str) -> CommandResult:
        match = CONTACT_WHO_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="contact_who", success=False,
                                 text=None, fallthrough=True)
        return self._find_contact_fuzzy(match.group(1).strip(), "contact_who")

    def _cmd_lookup(self, raw_text: str) -> CommandResult:
        match = CONTACT_LOOKUP_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="contact_lookup", success=False,
                                 text=None, fallthrough=True)
        name_str = match.group(1) or match.group(2) or match.group(4)
        id_str = match.group(3)
        if id_str:
            contact = self._store.get_by_id(int(id_str))
            if contact:
                return CommandResult(command="contact_lookup", success=True,
                                     text=contact.format_detail())
            return CommandResult(command="contact_lookup", success=False,
                                 text=None, fallthrough=True)
        if name_str:
            return self._find_contact_fuzzy(name_str.strip(), "contact_lookup")
        return CommandResult(command="contact_lookup", success=False,
                             text=None, fallthrough=True)

    def _cmd_field_query(self, raw_text: str) -> CommandResult:
        """Beantwortet gezielte Feld-Abfragen wie 'wann hat Lisa Geburtstag?'."""
        match = CONTACT_FIELD_QUERY_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="contact_field_query", success=False,
                                 text=None, fallthrough=True)

        groups = match.groups()
        # Gruppen: (0) wann hat X geburtstag, (1) wann ist Xs geburtstag,
        #          (2) geburtstag von X, (3) adresse, (4) telefon, (5) email,
        #          (6) adresse2, (7) gruppe, (8) wo arbeitet/wohnt
        name = None
        query_type = None
        for i, g in enumerate(groups):
            if g:
                name = g.strip()
                if i in (0, 1, 2):
                    query_type = "birthday"
                elif i in (3, 6):
                    query_type = "address"
                elif i == 4:
                    query_type = "phones"
                elif i == 5:
                    query_type = "emails"
                elif i == 7:
                    query_type = "categories"
                elif i == 8:
                    # "wo arbeitet X" → organization, "wo wohnt X" → address
                    lower = raw_text.lower()
                    if "arbeitet" in lower:
                        query_type = "organization"
                    else:
                        query_type = "address"
                break

        if not name or not query_type:
            return CommandResult(command="contact_field_query", success=False,
                                 text=None, fallthrough=True)

        contact = self._find_contact_for_query(name)
        if not contact:
            return CommandResult(
                command="contact_field_query", success=False,
                text=f"Kontakt '{name}' nicht gefunden.",
            )

        return self._format_field_answer(contact, query_type)

    def _format_field_answer(self, contact: Contact,
                             query_type: str) -> CommandResult:
        """Formatiert die Antwort für eine Feld-Abfrage."""
        name = contact.name

        if query_type == "birthday":
            if not contact.birthday:
                text = f"{name} hat keinen Geburtstag eingetragen."
            else:
                bday = contact.birthday
                if bday.startswith("0000-"):
                    text = f"{name} hat am {bday[5:]} Geburtstag."
                else:
                    text = f"{name} hat am {bday} Geburtstag."
                    # Tage bis zum nächsten Geburtstag berechnen
                    try:
                        today = date.today()
                        bday_date = date.fromisoformat(bday)
                        next_bday = bday_date.replace(year=today.year)
                        if next_bday < today:
                            next_bday = next_bday.replace(year=today.year + 1)
                        days_until = (next_bday - today).days
                        if days_until == 0:
                            text += " Das ist heute! 🎂"
                        elif days_until == 1:
                            text += " Das ist morgen!"
                        else:
                            text += f" – in {days_until} Tagen."
                    except (ValueError, TypeError):
                        pass

        elif query_type == "address":
            if not contact.address:
                text = f"Für {name} ist keine Adresse eingetragen."
            else:
                text = f"{name}: {contact.address}"

        elif query_type == "phones":
            phone_items = contact.get_phones_list()
            if not phone_items:
                text = f"Für {name} ist keine Telefonnummer eingetragen."
            elif len(phone_items) == 1:
                text = f"{name}: {phone_items[0].get('number', '')}"
            else:
                from elder_berry.tools.contact_store import _PHONE_TYPE_LABELS
                lines = [f"{name} hat {len(phone_items)} Nummern:"]
                for pi in phone_items:
                    label = _PHONE_TYPE_LABELS.get(
                        pi.get("type", ""), pi.get("type", ""),
                    )
                    lines.append(f"  {label}: {pi.get('number', '')}")
                text = "\n".join(lines)

        elif query_type == "emails":
            email_items = contact.get_emails_list()
            if not email_items:
                text = f"Für {name} ist keine Email eingetragen."
            elif len(email_items) == 1:
                text = f"{name}: {email_items[0].get('email', '')}"
            else:
                from elder_berry.tools.contact_store import _EMAIL_TYPE_LABELS
                lines = [f"{name} hat {len(email_items)} Email-Adressen:"]
                for ei in email_items:
                    label = _EMAIL_TYPE_LABELS.get(
                        ei.get("type", ""), ei.get("type", ""),
                    )
                    lines.append(f"  {label}: {ei.get('email', '')}")
                text = "\n".join(lines)

        elif query_type == "categories":
            cats = contact.get_categories_list()
            if not cats:
                text = f"{name} ist keiner Gruppe zugeordnet."
            else:
                text = f"{name} ist in: {', '.join(cats)}"

        elif query_type == "organization":
            if not contact.organization:
                text = f"Für {name} ist kein Arbeitgeber eingetragen."
            else:
                text = f"{name} arbeitet bei {contact.organization}"
                if contact.title:
                    text += f" (als {contact.title})"
                text += "."

        else:
            text = f"Feld '{query_type}' unbekannt."

        return CommandResult(
            command="contact_field_query", success=True, text=text,
        )

    def _cmd_group(self, raw_text: str) -> CommandResult:
        """Listet alle Kontakte einer Gruppe/Kategorie."""
        match = CONTACT_GROUP_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="contact_group", success=False,
                                 text="Format: kontakte gruppe <Name>")
        group_name = match.group(1).strip()
        contacts = self._store.find_by_category(
            self._default_user_id, group_name,
        )
        if not contacts:
            return CommandResult(
                command="contact_group", success=True,
                text=f"Keine Kontakte in der Gruppe '{group_name}'.",
            )
        lines = [f"📇 Gruppe '{group_name}' ({len(contacts)} Kontakte):"]
        for c in contacts:
            parts = [c.name]
            if c.role:
                parts.append(f"– {c.role}")
            phone = c.phone
            if phone:
                parts.append(f"📞 {phone}")
            lines.append(f"  {' '.join(parts)}")
        return CommandResult(
            command="contact_group", success=True, text="\n".join(lines),
        )

    def _cmd_search(self, raw_text: str) -> CommandResult:
        match = CONTACT_SEARCH_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="contact_search", success=False,
                                 text="Format: kontakte suche <Begriff>")
        query = match.group(1).strip()
        results = self._store.search(self._default_user_id, query)
        if not results:
            return CommandResult(command="contact_search", success=True,
                                 text="Keine Kontakte gefunden.")
        lines = [f"📇 {len(results)} Treffer:"]
        for c in results:
            lines.append(f"  {c.format_short()}")
        return CommandResult(command="contact_search", success=True,
                             text="\n".join(lines))

    def _cmd_list(self, _raw_text: str) -> CommandResult:
        contacts = self._store.list_all(self._default_user_id, limit=200)
        if not contacts:
            return CommandResult(command="kontakte", success=True,
                                 text="Keine Kontakte gespeichert.")
        lines = [f"📇 {len(contacts)} Kontakte:"]
        for c in contacts:
            lines.append(f"  {c.format_short()}")
        return CommandResult(command="kontakte", success=True,
                             text="\n".join(lines))

    def _cmd_delete(self, raw_text: str) -> CommandResult:
        match = CONTACT_DELETE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="contact_delete", success=False,
                                 text="Format: kontakt löschen #<ID> oder <Name>")
        id_str = match.group(1)
        name_str = match.group(2)
        if id_str:
            ok = self._store.delete(int(id_str))
            label = f"#{id_str}"
        else:
            ok = self._store.delete_by_name(
                self._default_user_id, name_str.strip())
            label = name_str.strip()
        if ok:
            return CommandResult(command="contact_delete", success=True,
                                 text=f"📇 Kontakt {label} gelöscht.")
        return CommandResult(command="contact_delete", success=False,
                             text=f"Kontakt {label} nicht gefunden.")

    def _cmd_sync(self, raw_text: str) -> CommandResult:
        if not self._carddav_sync:
            return self.not_configured(
                "contact_sync", "CardDAV-Sync (Nextcloud)", setup_step=4,
            )
        match = CONTACT_SYNC_PATTERN.match(raw_text.strip())
        direction = match.group(1).lower() if match and match.group(1) else None
        user_id = self._default_user_id

        try:
            if direction == "push":
                contacts = self._store.list_all(user_id, limit=1000)
                result = self._carddav_sync.push_contacts(contacts)
            elif direction == "pull":
                remote_data = self._carddav_sync.pull_contacts(user_id)
                pulled = 0
                for data in remote_data:
                    vcard_uid = data.pop("vcard_uid", "")
                    self._store.add_or_update_by_vcard_uid(
                        user_id, vcard_uid=vcard_uid, **data,
                    )
                    pulled += 1
                from elder_berry.tools.carddav_sync import SyncResult
                result = SyncResult(pulled=pulled)
            elif direction == "reset":
                result = self._carddav_sync.reset_and_pull(
                    self._store, user_id,
                )
            else:
                result = self._carddav_sync.sync(self._store, user_id)
        except Exception as exc:
            logger.error("CardDAV Sync fehlgeschlagen: %s", exc)
            return CommandResult(
                command="contact_sync", success=False,
                text=f"Sync fehlgeschlagen: {exc}",
            )

        text = f"📇 Kontakte-Sync abgeschlossen: {result}"
        if result.errors:
            text += "\n⚠️ Fehler:\n" + "\n".join(
                f"  - {e}" for e in result.errors
            )
        return CommandResult(command="contact_sync", success=True, text=text)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    _PHONE_PATTERN = re.compile(
        r"^[\+]?[\d\s\-/().]{6,}$",
    )

    @classmethod
    def _parse_contact_fields(cls, raw: str) -> dict[str, str]:
        """Parst komma-separierte Kontakt-Felder.

        Erkennt:
        - Explizite Zuweisungen: adresse=Wert, gruppe: Wert, rolle=Wert
        - Auto-Detection: Email (@), Telefon (Ziffern), Anrede
        - Erstes Feld ohne Zuweisung: Name
        - Rest ohne Zuweisung: Rolle, ggf. Notizen

        Zuweisungen (= oder :) werden über _FIELD_ALIASES aufgelöst und
        haben Vorrang vor Auto-Detection.
        """
        # Sonderfall: Adressen können Kommas enthalten. Wenn ein Teil
        # eine Zuweisung mit key= oder key: ist, kann der Wert bis zur
        # nächsten Zuweisung reichen. Daher: erst alle Zuweisungen
        # extrahieren, dann den Rest per Auto-Detection verarbeiten.
        _ASSIGN_RE = re.compile(
            r"(?:^|,)\s*"
            r"(?:–\s*)?"  # optionaler Dash-Prefix (LLM-Artefakt)
            r"(\w+)\s*[=:]\s*",
        )

        # Schritt 1: Zuweisungen finden und extrahieren
        assignments: dict[str, str] = {}
        remaining_parts: list[str] = []

        # Finde alle Zuweisung-Positionen
        matches = list(_ASSIGN_RE.finditer(raw))
        if matches:
            # Text vor der ersten Zuweisung → normal per Komma splitten
            prefix = raw[:matches[0].start()].strip().rstrip(",").strip()
            if prefix:
                remaining_parts = [
                    p.strip() for p in prefix.split(",") if p.strip()
                ]

            # Jede Zuweisung: Wert geht bis zur nächsten Zuweisung oder Ende
            for i, m in enumerate(matches):
                raw_key = m.group(1)
                val_start = m.end()
                val_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
                val = raw[val_start:val_end].strip().rstrip(",").strip()
                field = cls._resolve_field_key(raw_key)
                if field and val:
                    if field == "emails":
                        assignments[field] = json.dumps(
                            [{"type": "home", "email": val}],
                        )
                    elif field == "phones":
                        assignments[field] = json.dumps(
                            [{"type": "cell", "number": val}],
                        )
                    else:
                        assignments[field] = val
        else:
            remaining_parts = [p.strip() for p in raw.split(",") if p.strip()]

        # Schritt 2: Nicht-zugewiesene Teile per Auto-Detection
        parts = remaining_parts
        if not parts and not assignments:
            return {}

        result: dict[str, str] = {
            "name": "", "emails": "[]", "role": "",
            "formality": "förmlich", "notes": "", "phones": "[]",
        }

        for part in parts:
            lower = part.lower()
            if not result["name"]:
                result["name"] = part
            elif "@" in part:
                result["emails"] = json.dumps(
                    [{"type": "home", "email": part}],
                )
            elif cls._PHONE_PATTERN.match(part):
                result["phones"] = json.dumps(
                    [{"type": "cell", "number": part}],
                )
            elif lower in _FORMALITY_FOERMLICH:
                result["formality"] = "förmlich"
            elif lower in _FORMALITY_LOCKER:
                result["formality"] = "locker"
            elif not result["role"]:
                result["role"] = part
            else:
                notes = result.get("notes", "")
                result["notes"] = (notes + " " + part).strip()

        # Schritt 3: Zuweisungen überschreiben Auto-Detection
        result.update(assignments)

        return result
