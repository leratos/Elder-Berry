"""Regex-Patterns + Dauer-Parser für den WeatherCommandHandler (Phase 106).

Leaf-Modul (nur stdlib ``re``/``datetime``), damit Shell und Mixins die
Konstanten zyklusfrei teilen. Die Patterns werden in ``weather_commands.py``
re-exportiert, sodass ``from ...weather_commands import WEATHER_PATTERN`` etc.
(Tests) stabil bleibt.
"""

from __future__ import annotations

import re
from datetime import timedelta

# Regex für Training-Subcommands: "training details", "training woche"
TRAINING_PATTERN = re.compile(
    r"^training\s+(details|woche|week|letzte[sr]?)$",
    re.IGNORECASE,
)

# Regex: "wetter morgen", "wetter woche", "wetter 3" (Tage), "wetter übermorgen"
WEATHER_PATTERN = re.compile(
    r"^wetter\s+(morgen|heute|woche|übermorgen|uebermorgen|(\d{1,2}))$",
    re.IGNORECASE,
)

# Regex: "wetter in Leipzig", "wie ist das wetter in Berlin morgen",
# "wetter Berlin" (Ort ohne Präposition – Negativliste für Zeitwörter)
_WEATHER_TIME_WORDS = r"(?:morgen|heute|übermorgen|uebermorgen|woche|draußen)"
WEATHER_LOCATION_PATTERN = re.compile(
    r"(?:wetter|temperatur).*?(?:\s+in\s+([A-ZÄÖÜa-zäöüß][\w\s\-]+?)"
    r"|\s+(?!"
    + _WEATHER_TIME_WORDS
    + r"(?:\s|$))([A-ZÄÖÜ][\wäöüß\-]+(?:\s+[A-ZÄÖÜ][\wäöüß\-]+)*))"
    r"(?:\s+(?:morgen|heute|übermorgen|uebermorgen|woche|\d{1,2}))?$",
    re.IGNORECASE,
)

# Regex: "timer 20 min", "timer 5 min", "timer 1 stunde", "timer 90 sekunden"
TIMER_PATTERN = re.compile(
    r"^timer\s+(\d+)\s*(min(?:uten?)?|h(?:ours?)?|stunden?|sek(?:unden?)?|s|m)$",
    re.IGNORECASE,
)

# Regex: "erinnere mich um 18:00: Wäsche", "erinnere mich in 2 stunden: Kuchen"
REMINDER_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"(?:um\s+(\d{1,2}:\d{2})|in\s+(\d+)\s*(min(?:uten?)?|stunden?|h))"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# Regex: "lösche erinnerung 3", "lösche alle erinnerungen"
REMINDER_DELETE_PATTERN = re.compile(
    r"(?:lösche?|entferne?|cancel)\s+(?:erinnerung(?:en)?|timer|reminder)\s*(\d+)?|"
    r"(?:erinnerung(?:en)?|timer)\s+(?:löschen|lösche|entferne)(?:\s+(\d+))?|"
    r"(?:lösche?|entferne?)\s+alle\s+(?:erinnerung(?:en)?|timer)",
    re.IGNORECASE,
)

# --- Wiederkehrende Erinnerungen ---

_WEEKDAY_NAMES = r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag"

# Einmalige Erinnerung mit konkretem Wochentag/Datum/Relativtag.
# Beispiele:
#   "erinnere mich am Montag um 09:00: Bad Belzig anrufen"
#   "erinnere mich nächsten Montag um 9:00: Test"
#   "erinnere mich Montag um 9:00: Test"          (kurz, ohne "am")
#   "erinnere mich am 12.05. um 9:00: Mietvertrag"
#   "erinnere mich am 12.05.2026 um 9:00: ..."
#   "erinnere mich morgen um 8:30: Brötchen"
#   "erinnere mich übermorgen um 14:00: Anruf"
_REMINDER_DATE_DDMM = r"\d{1,2}\.\d{1,2}(?:\.(?:\d{2,4})?)?"
_REMINDER_REL_DAY = r"morgen|übermorgen|uebermorgen"
# Group 1: Praefix (am | naechsten | kommenden | None) -- explizites
# "naechsten/kommenden" erzwingt +7 Tage auch wenn Wochentag = heute mit
# noch zukuenftiger Uhrzeit (Codex-Review P2: explicit-next must honor).
REMINDER_DATE_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"(?:"
    r"(?:(am|nächsten|naechsten|kommenden)\s+)?(" + _WEEKDAY_NAMES + r")"
    r"|am\s+(" + _REMINDER_DATE_DDMM + r")"
    r"|(" + _REMINDER_REL_DAY + r")"
    r")"
    r"\s+um\s+(\d{1,2}:\d{2})"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# "erinnere mich jeden montag um 9:00: Wochenbericht"
RECURRING_WEEKLY_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"jede[nrm]?\s+(" + _WEEKDAY_NAMES + r")\s+"
    r"um\s+(\d{1,2}:\d{2})"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# "erinnere mich täglich um 8:00: Standup"
RECURRING_DAILY_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"t[äa]glich\s+"
    r"um\s+(\d{1,2}:\d{2})"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# "erinnere mich werktags um 7:30: Aufstehen"
RECURRING_WEEKDAY_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"werktags\s+"
    r"um\s+(\d{1,2}:\d{2})"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# "erinnere mich jeden 1. um 10:00: Miete"
RECURRING_MONTHLY_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"jede[nrm]?\s+(\d{1,2})\.\s+"
    r"um\s+(\d{1,2}:\d{2})"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)


def _parse_duration(amount: int, unit: str) -> timedelta:
    """Parst Zeiteinheiten in timedelta.

    Unterstützt: min/minuten/m, stunde/stunden/h, sek/sekunden/s.
    """
    u = unit.lower().rstrip(".")
    if u in ("min", "minuten", "minute", "m"):
        return timedelta(minutes=amount)
    if u in ("h", "hours", "hour", "stunde", "stunden"):
        return timedelta(hours=amount)
    if u in ("sek", "sekunden", "sekunde", "s"):
        return timedelta(seconds=amount)

    raise ValueError(f"Unbekannte Zeiteinheit: {unit}")
