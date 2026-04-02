"""CalendarCommandHandler – Kalender-Commands (Termine).

Unterstützt CalDAV (Nextcloud) und Google Calendar als Backend.
Commands:
- termine / termine morgen / termine woche / termine monat / termine N → Termine abfragen
- termin: Titel Datum Uhrzeit → Termin erstellen
- termin suche <Begriff> → Termine durchsuchen
- termin löschen <ID|Index|alle|Titel> → Termin(e) löschen
"""
from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.tools.google_calendar import GoogleCalendarClient

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Patterns
# ------------------------------------------------------------------

TERMINE_PATTERN = re.compile(
    r"^termine?\s+(morgen|woche|nächste\s+woche|diese\s+woche"
    r"|monat|dieser\s+monat|diesen\s+monat|restlicher\s+monat"
    r"|(\d{1,2}))$",
    re.IGNORECASE,
)

# Regex für Termin-Erstellung (flexibel):
# "termin: Zahnarzt 2026-03-20 14:00"
# "termin: Zahnarzt morgen 14:00"
# "termin: Zahnarzt 30.03 14:00"
# "termin: Zahnarzt 30.03.2026 14:00"
# "termin: Geburtstag Lisa 28.09 jährlich"  (Ganztags + Wiederholung)
# "termin: Urlaub 15.07"  (Ganztags ohne Uhrzeit)
# Auch ohne Doppelpunkt: "termin Zahnarzt morgen 14:00"
# Auch mit "erstelle": "erstelle termin Zahnarzt morgen 14:00"
TERMIN_CREATE_PATTERN = re.compile(
    r"^(?:erstelle?\s+(?:(?:einen?\s+)?termin\s*[:\s]?\s*)"  # "erstelle termin ..."
    r"|termin[:\s]\s*)"                                        # oder "termin: ..."
    r"(.+?)\s+"                                                # Titel (non-greedy)
    r"(morgen|übermorgen|uebermorgen"                           # Wort-Datum
    r"|\d{1,2}\.\d{1,2}(?:\.\d{2,4})?"                        # DD.MM oder DD.MM.YY(YY)
    r"|\d{4}-\d{2}-\d{2})"                                    # YYYY-MM-DD
    r"(?:\s+(?:um\s+)?(\d{1,2}:\d{2})(?:\s*uhr)?)?"           # Uhrzeit (optional)
    r"(?:\s+(jährlich|monatlich|wöchentlich|täglich"            # Wiederholung (optional)
    r"|yearly|monthly|weekly|daily)"
    r"(?:\s+wiederhol(?:en|end))?)?$",
    re.IGNORECASE,
)

# Regex für Termin löschen:
# "termin löschen abc123", "lösche termin abc123", "lösche den termin abc123"
# "termin löschen alle", "lösche alle termine"
# "lösch den 2. termin", "entferne termin 1"
TERMIN_DELETE_PATTERN = re.compile(
    r"(?:termin[e]?\s+(?:löschen|lösche|entferne[n]?|lösch|storniere[n]?)\s+(.+)"
    r"|(?:lösche?|entferne?|storniere?)\s+(?:den\s+|die\s+|alle\s+)?(?:termin[e]?\s+)?(.+?)(?:\s+termin[e]?)?$"
    r")",
    re.IGNORECASE,
)

# Regex für Termin-Suche: "termin suche Zahnarzt", "suche den termin Zahnarzt"
TERMIN_SEARCH_PATTERN = re.compile(
    r"(?:termine?\s+(?:suche?|finde?|such)\s+(.+)"
    r"|(?:suche?|finde?)\s+(?:mir\s+)?(?:bitte\s+)?(?:den\s+)?termin\s+(.+))",
    re.IGNORECASE,
)


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _parse_natural_date(date_str: str) -> datetime | None:
    """Parst natürliche Datumsangaben in ein datetime.date.

    Unterstützt: morgen, übermorgen, DD.MM, DD.MM.YYYY, DD.MM.YY, YYYY-MM-DD.
    """
    from datetime import date, timedelta

    lower = date_str.lower().strip()

    if lower == "morgen":
        d = date.today() + timedelta(days=1)
        return datetime(d.year, d.month, d.day)
    if lower in ("übermorgen", "uebermorgen"):
        d = date.today() + timedelta(days=2)
        return datetime(d.year, d.month, d.day)

    # YYYY-MM-DD
    try:
        return datetime.strptime(lower, "%Y-%m-%d")
    except ValueError:
        pass

    # DD.MM.YYYY
    try:
        return datetime.strptime(lower, "%d.%m.%Y")
    except ValueError:
        pass

    # DD.MM.YY
    try:
        return datetime.strptime(lower, "%d.%m.%y")
    except ValueError:
        pass

    # DD.MM (aktuelles Jahr anfügen, da strptime ohne Jahr deprecated ab 3.15)
    if re.match(r"^\d{1,2}\.\d{1,2}$", lower):
        try:
            year = date.today().year
            return datetime.strptime(f"{lower}.{year}", "%d.%m.%Y")
        except ValueError:
            pass

    return None


def _parse_recurrence(text: str) -> list[str] | None:
    """Übersetzt Wiederholungstext in RRULE-Strings für die Google Calendar API."""
    if not text:
        return None
    mapping = {
        "jährlich": "RRULE:FREQ=YEARLY",
        "yearly": "RRULE:FREQ=YEARLY",
        "monatlich": "RRULE:FREQ=MONTHLY",
        "monthly": "RRULE:FREQ=MONTHLY",
        "wöchentlich": "RRULE:FREQ=WEEKLY",
        "weekly": "RRULE:FREQ=WEEKLY",
        "täglich": "RRULE:FREQ=DAILY",
        "daily": "RRULE:FREQ=DAILY",
    }
    rrule = mapping.get(text.lower().strip())
    return [rrule] if rrule else None


# ------------------------------------------------------------------
# Handler
# ------------------------------------------------------------------

class CalendarCommandHandler(CommandHandler):
    """Handler für Kalender-Commands (Termine)."""

    def __init__(
        self,
        calendar: GoogleCalendarClient | None = None,
    ) -> None:
        self._calendar = calendar
        self._last_events: list = []

    # -- CommandHandler interface ------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"termine", "kalender"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        # NOTE: TERMIN_CREATE_PATTERN must come BEFORE TERMINE_PATTERN
        # (order matters for matching priority)
        return [
            (TERMIN_CREATE_PATTERN, "termin_create", False, False),
            (TERMIN_DELETE_PATTERN, "termin_delete", False, False),
            (TERMIN_SEARCH_PATTERN, "termin_search", False, True),
            (TERMINE_PATTERN, "termine", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "termine: Termine heute anzeigen",
            "termine morgen: Termine morgen",
            "termine woche: Termine der nächsten 7 Tage",
            "termine monat: Termine bis Monatsende",
            "termin suche <begriff>: Termine durchsuchen",
            "termin: <Titel> <Datum> <Uhrzeit>: Termin erstellen (morgen, übermorgen, DD.MM, YYYY-MM-DD)",
            "lösche termin <Titel/ID>: Termin löschen",
            "lösche den 2. termin / lösche alle termine: Aus letztem Ergebnis",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "termine_monat": [
                "diesen monat", "dieser monat", "restlicher monat",
                "monat termine", "monatsübersicht", "monatsplan",
                "was steht diesen monat an", "termine im monat",
            ],
            "termine_woche": [
                "nächste woche", "diese woche", "woche termine",
                "wochenplan", "wochenübersicht",
            ],
            "termine_morgen": [
                "morgen termine", "habe ich morgen",
                "bin ich morgen frei", "was hab ich morgen vor",
            ],
            "termine": [
                "was steht an", "welche termine",
                "nächster termin", "termine heute", "habe ich termine",
                "zeitplan", "terminplan", "agenda", "was hab ich vor",
                "hab ich heute was", "bin ich heute frei",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        """Führt einen erkannten Calendar-Command aus."""
        if command in ("termine", "kalender"):
            return self._cmd_termine(raw_text, variant="termine")
        if command == "termine_monat":
            return self._cmd_termine(raw_text, variant="termine_monat")
        if command == "termine_woche":
            return self._cmd_termine(raw_text, variant="termine_woche")
        if command == "termine_morgen":
            return self._cmd_termine(raw_text, variant="termine_morgen")
        if command == "termin_create":
            return self._cmd_termin_create(raw_text)
        if command == "termin_search":
            return self._cmd_termin_search(raw_text)
        if command == "termin_delete":
            return self._cmd_termin_delete(raw_text)

        return CommandResult(
            command=command, success=False,
            text=f"Unbekannter Calendar-Command: {command}",
        )

    # -- Command implementations ------------------------------------

    def _cmd_termine(self, raw_text: str, variant: str = "termine") -> CommandResult:
        """Termine abfragen (heute, morgen, woche, N Tage)."""
        if not self._calendar:
            return CommandResult(
                command="termine",
                success=False,
                text="Kalender nicht konfiguriert.",
            )

        normalized = raw_text.strip().lower()
        match = TERMINE_PATTERN.match(normalized)

        try:
            # Keyword-Variante hat Vorrang (z.B. "nächste woche" → termine_woche)
            if variant == "termine_monat":
                days = self._days_remaining_in_month()
                events = self._calendar.get_events(days=days)
                label = f"Termine (restlicher Monat, {days} Tage)"
            elif variant == "termine_woche":
                events = self._calendar.get_events(days=7)
                label = "Termine (nächste 7 Tage)"
            elif variant == "termine_morgen":
                events = self._calendar.get_tomorrow()
                label = "Termine morgen"
            elif match:
                param = match.group(1).lower()
                if param == "morgen":
                    events = self._calendar.get_tomorrow()
                    label = "Termine morgen"
                elif param in ("woche", "nächste woche", "diese woche"):
                    events = self._calendar.get_events(days=7)
                    label = "Termine (nächste 7 Tage)"
                elif param in ("monat", "dieser monat", "diesen monat",
                               "restlicher monat"):
                    days = self._days_remaining_in_month()
                    events = self._calendar.get_events(days=days)
                    label = f"Termine (restlicher Monat, {days} Tage)"
                elif match.group(2):
                    days = int(match.group(2))
                    events = self._calendar.get_events(days=days)
                    label = f"Termine (nächste {days} Tage)"
                else:
                    events = self._calendar.get_today()
                    label = "Termine heute"
            else:
                events = self._calendar.get_today()
                label = "Termine heute"

            # Letzte Events speichern (für "lösche alle/den 2.")
            self._last_events = events

            text = f"{label}:\n{self._calendar.format_events(events)}"
            return CommandResult(command="termine", success=True, text=text)

        except Exception as e:
            logger.error("Kalender-Abfrage fehlgeschlagen: %s", e)
            return CommandResult(
                command="termine",
                success=False,
                text=f"Kalender-Fehler: {e}",
            )

    @staticmethod
    def _days_remaining_in_month() -> int:
        """Berechnet die verbleibenden Tage bis Monatsende (inkl. heute)."""
        today = date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        return last_day - today.day + 1  # +1: heute mitzählen

    def _cmd_termin_create(self, raw_text: str) -> CommandResult:
        """Neuen Termin erstellen."""
        if not self._calendar:
            return CommandResult(
                command="termin_create",
                success=False,
                text="Kalender nicht konfiguriert.",
            )

        match = TERMIN_CREATE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="termin_create",
                success=False,
                text="Format: termin: Titel morgen 14:00\n"
                     "Oder Ganztags: termin: Titel 30.03\n"
                     "Datum-Formate: morgen, übermorgen, 30.03, 30.03.2026, 2026-03-30",
            )

        title = match.group(1).strip()
        date_str = match.group(2)
        time_str = match.group(3)  # None wenn keine Uhrzeit
        recurrence_str = match.group(4)  # None wenn keine Wiederholung

        # Natürliche Datumsangaben parsen (morgen, DD.MM, etc.)
        date_parsed = _parse_natural_date(date_str)
        if not date_parsed:
            return CommandResult(
                command="termin_create",
                success=False,
                text=f"Ungültiges Datum: '{date_str}'.\n"
                     "Erlaubt: morgen, übermorgen, 30.03, 30.03.2026, 2026-03-30",
            )

        all_day = time_str is None
        if not all_day:
            try:
                hour, minute = time_str.split(":")
                start = date_parsed.replace(hour=int(hour), minute=int(minute))
            except (ValueError, IndexError):
                return CommandResult(
                    command="termin_create",
                    success=False,
                    text=f"Ungültige Uhrzeit: '{time_str}'. Format: HH:MM",
                )
        else:
            start = date_parsed

        recurrence = _parse_recurrence(recurrence_str) if recurrence_str else None

        try:
            event = self._calendar.create_event(
                summary=title, start=start,
                all_day=all_day, recurrence=recurrence,
            )
            text = f"Termin erstellt: {event.format_short()}"
            if recurrence:
                text += f" (wiederholt: {recurrence_str})"
            return CommandResult(
                command="termin_create",
                success=True,
                text=text,
            )
        except Exception as e:
            logger.error("Termin erstellen fehlgeschlagen: %s", e)
            return CommandResult(
                command="termin_create",
                success=False,
                text=f"Termin erstellen fehlgeschlagen: {e}",
            )

    def _cmd_termin_search(self, raw_text: str) -> CommandResult:
        """Termine per Volltextsuche finden."""
        if not self._calendar:
            return CommandResult(
                command="termin_search", success=False,
                text="Kalender nicht konfiguriert.",
            )

        match = TERMIN_SEARCH_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="termin_search", success=False,
                text="Format: termin suche <Begriff>",
            )

        # Zwei alternative Gruppen im Pattern
        query = (match.group(1) or match.group(2) or "").strip()
        try:
            events = self._calendar.search_events(query, days=90)
            if not events:
                return CommandResult(
                    command="termin_search", success=True,
                    text=f"Keine Termine gefunden für '{query}'.",
                )

            self._last_events = events

            text = f"Suche '{query}' ({len(events)} Treffer):\n"
            text += self._calendar.format_events(events)
            return CommandResult(command="termin_search", success=True, text=text)

        except Exception as e:
            logger.error("Termin-Suche fehlgeschlagen: %s", e)
            return CommandResult(
                command="termin_search", success=False,
                text=f"Termin-Suche fehlgeschlagen: {e}",
            )

    def _cmd_termin_delete(self, raw_text: str) -> CommandResult:
        """Termin(e) löschen per Event-ID, Index oder 'alle'."""
        if not self._calendar:
            return CommandResult(
                command="termin_delete", success=False,
                text="Kalender nicht konfiguriert.",
            )

        normalized = raw_text.strip().lower()

        # "alle" erkennen bevor Regex parst (Regex konsumiert "alle" als Optionalgruppe)
        if re.search(r"alle\s+termin", normalized) or normalized.endswith("alle"):
            return self._delete_all_events()

        match = TERMIN_DELETE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="termin_delete", success=False,
                text="Format: termin löschen <ID> oder lösche den 2. termin",
            )

        target = (match.group(1) or match.group(2) or "").strip().rstrip(".")

        # Füllwörter entfernen (bitte, mal, doch, morgen ohne Datum-Kontext)
        filler = {"bitte", "mal", "doch", "jetzt", "sofort", "gleich",
                  "morgen", "heute", "den", "die", "das", "termin", "termine"}
        clean_words = [w for w in target.lower().split() if w not in filler]
        clean_target = " ".join(clean_words).strip()

        # Wenn nach Füllwort-Bereinigung nichts übrig: "lösch den termin (bitte)"
        # → bei genau 1 Event: diesen löschen
        if not clean_target and self._last_events:
            if len(self._last_events) == 1:
                return self._delete_event_by_index(1)
            return CommandResult(
                command="termin_delete", success=False,
                text=f"Welchen? Es gibt {len(self._last_events)} Termine.\n"
                     "Sag z.B. 'lösche den 1. termin' oder 'lösche alle termine'.",
            )

        # Index-basiert: "1", "2.", "den 1.", "den ersten"
        index = self._parse_index(target)
        if index is not None:
            return self._delete_event_by_index(index)

        # Titel-Suche in letzten Events (bevorzugt, wenn Events vorhanden)
        if self._last_events:
            return self._delete_event_by_title(target)

        # Fallback: Direkte Event-ID (z.B. "abc123def")
        if len(target) > 3:
            return self._delete_event_by_id(target)

        return CommandResult(
            command="termin_delete", success=False,
            text="Keine Termine zum Löschen. Frag erst nach Terminen.",
        )

    def _delete_all_events(self) -> CommandResult:
        """Löscht alle Events aus dem letzten Ergebnis."""
        if not self._last_events:
            return CommandResult(
                command="termin_delete", success=False,
                text="Keine Termine zum Löschen. Frag erst nach Terminen.",
            )

        deleted = 0
        errors = []
        for event in self._last_events:
            if not event.event_id:
                continue
            try:
                self._calendar.delete_event(event.event_id)
                deleted += 1
            except Exception as e:
                errors.append(f"{event.summary}: {e}")

        self._last_events = []

        if errors:
            return CommandResult(
                command="termin_delete", success=False,
                text=f"{deleted} gelöscht, {len(errors)} Fehler:\n"
                     + "\n".join(errors),
            )

        return CommandResult(
            command="termin_delete", success=True,
            text=f"{deleted} Termin{'e' if deleted != 1 else ''} gelöscht.",
        )

    def _delete_event_by_index(self, index: int) -> CommandResult:
        """Löscht einen Termin per Index (1-basiert) aus dem letzten Ergebnis."""
        if not self._last_events:
            return CommandResult(
                command="termin_delete", success=False,
                text="Keine Termine zum Löschen. Frag erst nach Terminen.",
            )

        if index < 1 or index > len(self._last_events):
            return CommandResult(
                command="termin_delete", success=False,
                text=f"Index {index} ungültig. Es gibt {len(self._last_events)} Termine.",
            )

        event = self._last_events[index - 1]
        if not event.event_id:
            return CommandResult(
                command="termin_delete", success=False,
                text=f"Termin '{event.summary}' hat keine ID.",
            )

        try:
            self._calendar.delete_event(event.event_id)
            self._last_events.pop(index - 1)
            return CommandResult(
                command="termin_delete", success=True,
                text=f"Termin gelöscht: {event.summary}",
            )
        except Exception as e:
            return CommandResult(
                command="termin_delete", success=False,
                text=f"Löschen fehlgeschlagen: {e}",
            )

    def _delete_event_by_id(self, event_id: str) -> CommandResult:
        """Löscht einen Termin direkt per Google Event-ID."""
        try:
            self._calendar.delete_event(event_id)
            # Aus Cache entfernen
            self._last_events = [
                e for e in self._last_events if e.event_id != event_id
            ]
            return CommandResult(
                command="termin_delete", success=True,
                text=f"Termin gelöscht (ID: {event_id}).",
            )
        except Exception as e:
            return CommandResult(
                command="termin_delete", success=False,
                text=f"Löschen fehlgeschlagen: {e}",
            )

    def _delete_event_by_title(self, title: str) -> CommandResult:
        """Löscht einen Termin per Titel-Suche in den letzten Ergebnissen."""
        if not self._last_events:
            return CommandResult(
                command="termin_delete", success=False,
                text="Keine Termine zum Löschen. Frag erst nach Terminen.",
            )

        lower = title.lower()
        matches = [
            e for e in self._last_events
            if lower in e.summary.lower() and e.event_id
        ]

        if not matches:
            return CommandResult(
                command="termin_delete", success=False,
                text=f"Kein Termin mit '{title}' in den letzten Ergebnissen gefunden.",
            )

        if len(matches) > 1:
            names = "\n".join(f"  - {e.summary}" for e in matches)
            return CommandResult(
                command="termin_delete", success=False,
                text=f"Mehrere Treffer für '{title}':\n{names}\n"
                     "Bitte genauer angeben oder Index nutzen (z.B. lösche den 1. termin).",
            )

        event = matches[0]
        try:
            self._calendar.delete_event(event.event_id)
            self._last_events = [
                e for e in self._last_events if e.event_id != event.event_id
            ]
            return CommandResult(
                command="termin_delete", success=True,
                text=f"Termin gelöscht: {event.summary}",
            )
        except Exception as e:
            return CommandResult(
                command="termin_delete", success=False,
                text=f"Löschen fehlgeschlagen: {e}",
            )

    @staticmethod
    def _parse_index(text: str) -> int | None:
        """Parst einen Index aus Text ('1', '2.', 'den 1.', 'ersten', 'zweiten')."""
        clean = re.sub(r"^(?:den|die|das)\s+", "", text.lower()).strip().rstrip(".")

        # Zahl direkt
        if clean.isdigit():
            return int(clean)

        # Ordinalzahlen
        ordinals = {
            "ersten": 1, "erste": 1, "1": 1,
            "zweiten": 2, "zweite": 2, "2": 2,
            "dritten": 3, "dritte": 3, "3": 3,
            "vierten": 4, "vierte": 4,
            "fünften": 5, "fünfte": 5,
        }
        return ordinals.get(clean)
