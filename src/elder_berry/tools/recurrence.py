"""Recurrence – Berechnung und Parsing wiederkehrender Erinnerungen.

Unterstützte Formate:
    daily           → Täglich
    weekly:N        → Wöchentlich (N = ISO-Wochentag, Mo=1 .. So=7)
    monthly:N       → Monatlich am N-ten Tag
    biweekly:N      → Alle 2 Wochen (N = ISO-Wochentag)
    weekdays        → Mo–Fr

Alle Berechnungen erfolgen in lokaler Zeitzone, um Wochentage korrekt
zu bestimmen.  Das Ergebnis wird als UTC-aware datetime zurückgegeben.
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# -------------------------------------------------------------------------
# Recurrence-Format Konstanten
# -------------------------------------------------------------------------

VALID_TYPES = {"daily", "weekly", "monthly", "biweekly", "weekdays"}

_RECURRENCE_RE = re.compile(
    r"^(daily|weekly|monthly|biweekly|weekdays)(?::(\d+))?$"
)

# ISO-Wochentag Mapping: Deutsch → Nummer (Mo=1 .. So=7)
_WEEKDAY_MAP: dict[str, int] = {
    "montag": 1,
    "dienstag": 2,
    "mittwoch": 3,
    "donnerstag": 4,
    "freitag": 5,
    "samstag": 6,
    "sonntag": 7,
}

DEFAULT_TIMEZONE = "Europe/Berlin"


# -------------------------------------------------------------------------
# Parsing: natürliche Sprache → recurrence-String
# -------------------------------------------------------------------------

# "jeden montag", "jeden dienstag", ...
_WEEKLY_RE = re.compile(
    r"jede[nrm]?\s+("
    + "|".join(_WEEKDAY_MAP.keys())
    + r")",
    re.IGNORECASE,
)

# "täglich"
_DAILY_RE = re.compile(r"t[äa]glich", re.IGNORECASE)

# "werktags"
_WEEKDAYS_RE = re.compile(r"werktags", re.IGNORECASE)

# "alle 2 wochen montags" / "alle zwei wochen dienstags"
_BIWEEKLY_RE = re.compile(
    r"alle\s+(?:2|zwei)\s+wochen\s+("
    + "|".join(k + "s?" for k in _WEEKDAY_MAP.keys())
    + r")",
    re.IGNORECASE,
)

# "jeden 1." / "jeden 15." → monatlich
_MONTHLY_RE = re.compile(
    r"jede[nrm]?\s+(\d{1,2})\.",
    re.IGNORECASE,
)


def parse_recurrence(text: str) -> str | None:
    """Versucht aus natürlicher Sprache einen recurrence-String zu extrahieren.

    Args:
        text: Eingabetext (z.B. "jeden montag", "täglich", "werktags").

    Returns:
        Recurrence-String (z.B. "weekly:1", "daily") oder None.
    """
    text = text.strip().lower()

    if _DAILY_RE.search(text):
        return "daily"

    if _WEEKDAYS_RE.search(text):
        return "weekdays"

    m = _BIWEEKLY_RE.search(text)
    if m:
        day_name = m.group(1).rstrip("s")  # "montags" → "montag"
        day_num = _WEEKDAY_MAP.get(day_name)
        if day_num:
            return f"biweekly:{day_num}"

    m = _WEEKLY_RE.search(text)
    if m:
        day_name = m.group(1).lower()
        day_num = _WEEKDAY_MAP.get(day_name)
        if day_num:
            return f"weekly:{day_num}"

    m = _MONTHLY_RE.search(text)
    if m:
        day = int(m.group(1))
        if 1 <= day <= 31:
            return f"monthly:{day}"

    return None


def format_recurrence(recurrence: str) -> str:
    """Formatiert einen recurrence-String als lesbaren deutschen Text.

    Args:
        recurrence: Recurrence-String (z.B. "weekly:1", "daily").

    Returns:
        Lesbarer Text (z.B. "jeden Montag", "täglich").
    """
    m = _RECURRENCE_RE.match(recurrence)
    if not m:
        return recurrence

    rtype = m.group(1)
    param = int(m.group(2)) if m.group(2) else None

    if rtype == "daily":
        return "täglich"

    if rtype == "weekdays":
        return "werktags (Mo–Fr)"

    # Wochentag-Name aus ISO-Nummer
    day_names = {
        1: "Montag", 2: "Dienstag", 3: "Mittwoch", 4: "Donnerstag",
        5: "Freitag", 6: "Samstag", 7: "Sonntag",
    }

    if rtype == "weekly" and param:
        name = day_names.get(param, f"Tag {param}")
        return f"jeden {name}"

    if rtype == "biweekly" and param:
        name = day_names.get(param, f"Tag {param}")
        return f"alle 2 Wochen {name}"

    if rtype == "monthly" and param:
        return f"jeden {param}. des Monats"

    return recurrence


# -------------------------------------------------------------------------
# Berechnung: nächster Fälligkeitstermin
# -------------------------------------------------------------------------

def validate_recurrence(recurrence: str) -> bool:
    """Prüft ob ein recurrence-String gültig ist.

    Args:
        recurrence: Zu prüfender String.

    Returns:
        True wenn gültig.
    """
    m = _RECURRENCE_RE.match(recurrence)
    if not m:
        return False

    rtype = m.group(1)
    param = int(m.group(2)) if m.group(2) else None

    if rtype in ("daily", "weekdays"):
        return param is None

    if rtype in ("weekly", "biweekly"):
        return param is not None and 1 <= param <= 7

    if rtype == "monthly":
        return param is not None and 1 <= param <= 31

    return False


def calculate_next_due(
    current_due: datetime,
    recurrence: str,
    tz_name: str = DEFAULT_TIMEZONE,
) -> datetime:
    """Berechnet den nächsten Fälligkeitstermin nach dem aktuellen.

    Die Berechnung erfolgt in der lokalen Zeitzone (tz_name), damit
    Wochentage und Monatstage korrekt bestimmt werden.  Das Ergebnis
    wird als UTC-aware datetime zurückgegeben.

    Args:
        current_due: Aktueller Fälligkeitstermin (muss timezone-aware sein).
        recurrence: Recurrence-String (z.B. "daily", "weekly:1").
        tz_name: IANA-Zeitzone (z.B. "Europe/Berlin").

    Returns:
        Nächster Fälligkeitstermin als UTC-aware datetime.

    Raises:
        ValueError: Wenn recurrence ungültig ist.
    """
    if not validate_recurrence(recurrence):
        raise ValueError(f"Ungültiges Recurrence-Format: {recurrence}")

    tz = ZoneInfo(tz_name)
    local_due = current_due.astimezone(tz)

    m = _RECURRENCE_RE.match(recurrence)
    rtype = m.group(1)
    param = int(m.group(2)) if m.group(2) else None

    if rtype == "daily":
        next_local = local_due + timedelta(days=1)

    elif rtype == "weekdays":
        next_local = local_due + timedelta(days=1)
        # Vorspulen bis nächster Werktag (Mo=0 .. Fr=4 in Python)
        while next_local.weekday() >= 5:  # 5=Sa, 6=So
            next_local += timedelta(days=1)

    elif rtype == "weekly":
        next_local = local_due + timedelta(weeks=1)

    elif rtype == "biweekly":
        next_local = local_due + timedelta(weeks=2)

    elif rtype == "monthly":
        # Nächster Monat, gleicher Tag
        year = local_due.year
        month = local_due.month + 1
        if month > 12:
            month = 1
            year += 1

        # Tage im Zielmonat prüfen (z.B. 31. → 28. im Februar)
        max_day = calendar.monthrange(year, month)[1]
        day = min(param, max_day)

        next_local = local_due.replace(year=year, month=month, day=day)

    else:
        raise ValueError(f"Unbekannter Recurrence-Typ: {rtype}")

    return next_local.astimezone(timezone.utc)
