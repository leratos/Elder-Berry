"""ContactCommandHandler – Kontaktbuch-Commands.

Commands:
- kontakt: Name, Rolle, Email, Anrede       → Kontakt anlegen/aktualisieren
- kontakt ändern #ID: Feld=Wert             → Kontakt bearbeiten
- wer ist <Name>?                           → Kontakt abrufen
- kontakte                                   → Alle Kontakte auflisten
- kontakte suche <Begriff>                   → Volltextsuche
- kontakt löschen #<ID>                      → Per ID löschen
- kontakt löschen <Name>                     → Per Name löschen
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.tools.carddav_sync import CardDAVSyncClient
    from elder_berry.tools.contact_store import ContactStore

logger = logging.getLogger(__name__)

CONTACT_SYNC_PATTERN = re.compile(
    r"^kontakte?\s+sync(?:\s+(push|pull))?\s*$",
    re.IGNORECASE,
)

CONTACT_ADD_PATTERN = re.compile(
    r"^(?:neuer?\s+)?kontakt[:\s]+(.+)$", re.IGNORECASE,
)

CONTACT_UPDATE_PATTERN = re.compile(
    r"kontakt\s+(?:ändern\s+)?#?(\d+)[:\s]+(.+)", re.IGNORECASE,
)

CONTACT_WHO_PATTERN = re.compile(
    r"^wer\s+ist\s+(.+?)\??\s*$", re.IGNORECASE,
)

CONTACT_SEARCH_PATTERN = re.compile(
    r"^kontakte?\s+suche?\s+(.+)$", re.IGNORECASE,
)

CONTACT_DELETE_PATTERN = re.compile(
    r"^kontakte?\s+(?:löschen|lösche|entferne?)\s+(?:#(\d+)|(.+))$",
    re.IGNORECASE,
)

_FORMALITY_FOERMLICH = {"förmlich", "formell", "sie"}
_FORMALITY_LOCKER = {"locker", "informell", "du"}


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
            (CONTACT_ADD_PATTERN, "contact_add", False, False),
            (CONTACT_UPDATE_PATTERN, "contact_update", False, True),
            (CONTACT_WHO_PATTERN, "contact_who", False, False),
            (CONTACT_SEARCH_PATTERN, "contact_search", False, False),
            (CONTACT_DELETE_PATTERN, "contact_delete", False, False),
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
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "kontakt: Name, Rolle, Email, Anrede – Kontakt anlegen",
            "wer ist <Name>? – Kontakt abrufen",
            "kontakte – Alle Kontakte auflisten",
            "kontakte suche <Begriff> – Kontakt suchen",
            "kontakt löschen #<ID> – Kontakt löschen",
            "kontakte sync – Kontakte mit Nextcloud synchronisieren",
            "kontakte sync push – Nur lokal → Nextcloud",
            "kontakte sync pull – Nur Nextcloud → lokal",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        """Führt einen Kontakt-Command aus."""
        if not self._store:
            return CommandResult(
                command=command, success=False,
                text="Kontaktbuch nicht konfiguriert.",
            )
        dispatch = {
            "kontakte": self._cmd_list,
            "contact_add": self._cmd_add,
            "contact_update": self._cmd_update,
            "contact_who": self._cmd_who,
            "contact_search": self._cmd_search,
            "contact_delete": self._cmd_delete,
            "contact_sync": self._cmd_sync,
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
            user_id, name=fields["name"], email=fields.get("email", ""),
            role=fields.get("role", ""),
            formality=fields.get("formality", "förmlich"),
            notes=fields.get("notes", ""),
        )
        return CommandResult(
            command="contact_add", success=True,
            text=f"📇 Kontakt gespeichert: {contact.format_short()}",
        )

    def _cmd_update(self, raw_text: str) -> CommandResult:
        match = CONTACT_UPDATE_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(command="contact_update", success=False,
                                 text="Format: kontakt ändern #ID: feld=wert")
        contact_id = int(match.group(1))
        fields_raw = match.group(2).strip()
        updates: dict[str, str] = {}
        for part in fields_raw.split(","):
            if "=" in part:
                key, val = part.split("=", 1)
                updates[key.strip().lower()] = val.strip()
        contact = self._store.update(
            contact_id,
            name=updates.get("name", ""),
            email=updates.get("email", ""),
            role=updates.get("rolle", updates.get("role", "")),
            formality=updates.get("anrede", updates.get("formality", "")),
            notes=updates.get("notizen", updates.get("notes", "")),
        )
        if not contact:
            return CommandResult(command="contact_update", success=False,
                                 text=f"Kontakt #{contact_id} nicht gefunden.")
        return CommandResult(
            command="contact_update", success=True,
            text=f"📇 Aktualisiert: {contact.format_short()}",
        )

    def _cmd_who(self, raw_text: str) -> CommandResult:
        match = CONTACT_WHO_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="contact_who", success=False,
                                 text=None, fallthrough=True)
        name = match.group(1).strip()
        contact = self._store.find_by_name(self._default_user_id, name)
        if contact:
            text = f"📇 {contact.format_short()}"
            if contact.notes:
                text += f"\n📝 {contact.notes}"
            return CommandResult(command="contact_who", success=True,
                                 text=text)
        # Kein Kontakt → fallthrough an LLM
        return CommandResult(command="contact_who", success=False,
                             text=None, fallthrough=True)

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
        contacts = self._store.list_all(self._default_user_id)
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
            return CommandResult(
                command="contact_sync", success=False,
                text="CardDAV-Sync nicht konfiguriert (Nextcloud-Credentials fehlen).",
            )
        match = CONTACT_SYNC_PATTERN.match(raw_text.strip())
        direction = match.group(1).lower() if match and match.group(1) else None
        user_id = self._default_user_id

        try:
            if direction == "push":
                contacts = self._store.list_all(user_id, limit=1000)
                result = self._carddav_sync.push_contacts(contacts)
            elif direction == "pull":
                remote = self._carddav_sync.pull_contacts(user_id)
                pulled = 0
                for rc in remote:
                    self._store.add(
                        user_id, name=rc.name, email=rc.email,
                        role=rc.role, formality=rc.formality,
                        notes=rc.notes, birthday=rc.birthday,
                    )
                    pulled += 1
                from elder_berry.tools.carddav_sync import SyncResult
                result = SyncResult(pulled=pulled)
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

    @staticmethod
    def _parse_contact_fields(raw: str) -> dict[str, str]:
        """Parst komma-separierte Kontakt-Felder.

        Erkennt automatisch:
        - Email: enthält "@"
        - Anrede: "förmlich"/"locker" etc.
        - Erstes Feld: Name
        - Rest: Rolle, ggf. Notizen
        """
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            return {}
        result: dict[str, str] = {
            "name": parts[0], "email": "", "role": "",
            "formality": "förmlich", "notes": "",
        }
        for part in parts[1:]:
            lower = part.lower()
            if "@" in part:
                result["email"] = part
            elif lower in _FORMALITY_FOERMLICH:
                result["formality"] = "förmlich"
            elif lower in _FORMALITY_LOCKER:
                result["formality"] = "locker"
            elif not result["role"]:
                result["role"] = part
            else:
                notes = result.get("notes", "")
                result["notes"] = (notes + " " + part).strip()
        return result
