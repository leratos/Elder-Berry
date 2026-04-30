"""Secret-Registry – Single Source of Truth für alle Dashboard-Keys.

Dieses Modul ist ein Leaf: es importiert weder ``settings_dashboard`` noch
``secrets_api`` und bricht damit den ehemaligen Modul-Zyklus zwischen den
beiden (CodeQL ``py/unsafe-cyclic-import``).

Enthält:
- ``SecretRegistryEntry``: TypedDict-Schema eines Eintrags
- ``SECRET_REGISTRY``: Liste aller bekannten Keys
- ``_REGISTRY_BY_KEY``: Lookup-Dict ``key → entry``
- ``validate_secret``: zentrale Wert-Validierung
"""

from __future__ import annotations

import re
from typing import NotRequired, TypedDict

# ---------------------------------------------------------------------------
# Konstanten für Validierung
# ---------------------------------------------------------------------------

_VALID_KEY_RE = re.compile(r"^[a-z0-9_]{1,128}$")
_MAX_VALUE_LENGTH = 4096


class SecretRegistryEntry(TypedDict):
    """Schema für einen Registry-Eintrag.

    Phase 52: Felder ``behavior``, ``risk_level``, ``placeholder`` und
    ``select_options`` erweitern die Registry zur Single Source of Truth
    für das Unified Settings-Panel.
    """

    key: str
    label: str
    category: str
    sensitive: NotRequired[bool]  # Default: True
    behavior: NotRequired[bool]  # Phase 52: non-secret behavior setting
    requires_restart: NotRequired[bool]  # Default: False
    type: NotRequired[str]  # "str" | "int" | "float" | "url" | "textarea" | "select"
    min: NotRequired[float | int]
    max: NotRequired[float | int]
    pattern: NotRequired[str]
    description: NotRequired[str]
    link: NotRequired[str]
    risk_level: NotRequired[str]  # Phase 52: "low" | "medium" | "high"
    placeholder: NotRequired[str]  # Phase 52: UI placeholder
    select_options: NotRequired[list[dict[str, str]]]  # Phase 52: für type="select"


SECRET_REGISTRY: list[SecretRegistryEntry] = [
    # --- KI & Sprache ---
    {
        "key": "anthropic_api_key",
        "label": "Claude API",
        "category": "KI & Sprache",
        "sensitive": True,
        "requires_restart": True,
        "description": "API Key für Anthropic Claude.",
        "link": "https://console.anthropic.com/",
    },
    {
        "key": "groq_api_key",
        "label": "Groq",
        "category": "KI & Sprache",
        "sensitive": True,
        "requires_restart": True,
        "description": "API Key für Groq (optional).",
        "link": "https://console.groq.com/",
    },
    {
        "key": "elevenlabs_api_key",
        "label": "ElevenLabs API",
        "category": "KI & Sprache",
        "sensitive": True,
        "requires_restart": True,
        "description": "API Key für ElevenLabs TTS.",
        "link": "https://elevenlabs.io/app/speech-synthesis",
    },
    {
        "key": "elevenlabs_voice_id",
        "label": "ElevenLabs Voice",
        "category": "KI & Sprache",
        "sensitive": False,
        "requires_restart": True,
        "description": "Voice-ID für ElevenLabs TTS.",
    },
    # --- Suche & Karten ---
    {
        "key": "brave_api_key",
        "label": "Brave Search",
        "category": "Suche & Karten",
        "sensitive": True,
        "requires_restart": True,
        "description": "API Key für Brave Web Search.",
        "link": "https://brave.com/search/api/",
    },
    {
        "key": "google_maps_api_key",
        "label": "Google Maps",
        "category": "Suche & Karten",
        "sensitive": True,
        "requires_restart": True,
        "description": "Google Directions API Key.",
        "link": "https://console.cloud.google.com/",
    },
    {
        "key": "google_oauth_tokens",
        "label": "Google OAuth",
        "category": "Suche & Karten",
        "sensitive": True,
        "requires_restart": True,
        "description": "Google Calendar OAuth Tokens (Legacy-Fallback).",
    },
    # --- Matrix ---
    {
        "key": "matrix_homeserver",
        "label": "Homeserver",
        "category": "Matrix",
        "sensitive": False,
        "requires_restart": True,
        "type": "url",
        "description": "URL des Matrix-Homeservers (z.B. https://matrix.example.com).",
    },
    {
        "key": "matrix_user_id",
        "label": "User ID",
        "category": "Matrix",
        "sensitive": False,
        "requires_restart": True,
        "description": "Matrix User-ID (z.B. @bot:example.com).",
    },
    {
        "key": "matrix_password",
        "label": "Passwort",
        "category": "Matrix",
        "sensitive": True,
        "requires_restart": True,
    },
    {
        "key": "matrix_access_token",
        "label": "Access Token",
        "category": "Matrix",
        "sensitive": True,
        "requires_restart": True,
    },
    {
        "key": "matrix_room_id",
        "label": "Room ID",
        "category": "Matrix",
        "sensitive": False,
        "requires_restart": True,
        "description": "Matrix-Raum-ID (z.B. !abc:example.com).",
    },
    {
        "key": "matrix_allowed_senders",
        "label": "Erlaubte Sender",
        "category": "Matrix",
        "sensitive": False,
        "requires_restart": True,
        "type": "textarea",
        "risk_level": "high",
        "placeholder": "@user:matrix.example.com\n@admin:matrix.example.com",
        "description": "Eine Matrix-ID pro Zeile. Nur diese Sender dürfen Saleria steuern.",
    },
    # --- E-Mail ---
    {
        "key": "email_user",
        "label": "Benutzer",
        "category": "E-Mail",
        "sensitive": False,
        "requires_restart": True,
    },
    {
        "key": "email_password",
        "label": "Passwort",
        "category": "E-Mail",
        "sensitive": True,
        "requires_restart": True,
    },
    {
        "key": "email_imap_host",
        "label": "IMAP Host",
        "category": "E-Mail",
        "sensitive": False,
        "requires_restart": True,
    },
    {
        "key": "email_imap_port",
        "label": "IMAP Port",
        "category": "E-Mail",
        "sensitive": False,
        "requires_restart": True,
        "type": "int",
        "min": 1,
        "max": 65535,
    },
    {
        "key": "smtp_host",
        "label": "SMTP Host",
        "category": "E-Mail",
        "sensitive": False,
        "requires_restart": True,
    },
    {
        "key": "smtp_port",
        "label": "SMTP Port",
        "category": "E-Mail",
        "sensitive": False,
        "requires_restart": True,
        "type": "int",
        "min": 1,
        "max": 65535,
    },
    # --- Nextcloud ---
    {
        "key": "nextcloud_url",
        "label": "URL",
        "category": "Nextcloud",
        "sensitive": False,
        "requires_restart": True,
        "type": "url",
    },
    {
        "key": "nextcloud_user",
        "label": "Benutzer",
        "category": "Nextcloud",
        "sensitive": False,
        "requires_restart": True,
    },
    {
        "key": "nextcloud_app_password",
        "label": "App-Passwort",
        "category": "Nextcloud",
        "sensitive": True,
        "requires_restart": True,
    },
    # --- Dienste ---
    {
        "key": "berry_gym_url",
        "label": "Berry-Gym URL",
        "category": "Dienste",
        "sensitive": False,
        "requires_restart": False,
        "type": "url",
        "description": "URL der Berry-Gym Instanz (z.B. https://gym.example.com). "
        "Phase 67: ohne URL bleibt die Gym-Integration deaktiviert.",
    },
    {
        "key": "berry_gym_api_token",
        "label": "Berry-Gym API Token",
        "category": "Dienste",
        "sensitive": True,
        "requires_restart": False,
        "description": "Fitness-Tracker API Token. Aktiv nur in Kombination mit "
        "'berry_gym_url'.",
    },
    {
        "key": "stirling_pdf_url",
        "label": "URL",
        "category": "Dienste",
        "sensitive": False,
        "requires_restart": False,
        "type": "url",
        "description": "Stirling PDF Service URL.",
    },
    {
        "key": "stirling_pdf_api_key",
        "label": "API Key",
        "category": "Dienste",
        "sensitive": True,
        "requires_restart": False,
    },
    # --- Infrastruktur ---
    {
        "key": "robot_host",
        "label": "RPi5 Host",
        "category": "Infrastruktur",
        "sensitive": False,
        "requires_restart": False,
        "description": "IP/Hostname des RPi5.",
    },
    {
        "key": "tower_host",
        "label": "Tower Host",
        "category": "Infrastruktur",
        "sensitive": False,
        "requires_restart": False,
        "description": "IP/Hostname des Towers (z.B. 127.0.0.1:12769 via SSH-Tunnel).",
    },
    {
        "key": "tower_auth_token",
        "label": "Tower-Token",
        "category": "Infrastruktur",
        "sensitive": True,
        "requires_restart": True,
        "risk_level": "high",
        "description": "Auth-Token für den Tower-Server (Header X-Saleria-Tower-Token). "
        "Wird beim ersten Agent-Start automatisch generiert.",
    },
    # --- Wetter & Standort ---
    {
        "key": "weather_city",
        "label": "Stadt",
        "category": "Wetter & Standort",
        "sensitive": False,
        "requires_restart": False,
    },
    {
        "key": "weather_latitude",
        "label": "Breitengrad",
        "category": "Wetter & Standort",
        "sensitive": False,
        "requires_restart": False,
        "type": "float",
        "min": -90.0,
        "max": 90.0,
    },
    {
        "key": "weather_longitude",
        "label": "Längengrad",
        "category": "Wetter & Standort",
        "sensitive": False,
        "requires_restart": False,
        "type": "float",
        "min": -180.0,
        "max": 180.0,
    },
    # --- Verhalten (Phase 52: Behavior-Settings, kein Secret) ---
    {
        "key": "user_timezone",
        "label": "Zeitzone",
        "category": "Verhalten",
        "sensitive": False,
        "behavior": True,
        "requires_restart": False,
        "type": "select",
        "risk_level": "low",
        "description": "Standard-Zeitzone für Erinnerungen, Briefings und zeitbezogene Antworten.",
    },
    {
        "key": "stt_timeout",
        "label": "STT-Timeout (Sekunden)",
        "category": "Verhalten",
        "sensitive": False,
        "behavior": True,
        "requires_restart": False,
        "type": "float",
        "risk_level": "medium",
        "min": 5,
        "max": 600,
        "description": "Wie lange auf Spracheingabe gewartet wird, bevor abgebrochen wird.",
    },
    {
        "key": "llm_mode",
        "label": "LLM-Modus",
        "category": "Verhalten",
        "sensitive": False,
        "behavior": True,
        "requires_restart": True,
        "type": "select",
        "risk_level": "medium",
        "select_options": [
            {"value": "api_preferred", "label": "API bevorzugt"},
            {"value": "local_preferred", "label": "Lokal bevorzugt"},
            {"value": "fallback_only", "label": "Nur Fallback/Lokal"},
        ],
        "description": "Steuert, ob API-Modelle oder lokale Modelle bevorzugt verwendet werden.",
    },
]

# Schnellzugriff: key → Entry
_REGISTRY_BY_KEY: dict[str, SecretRegistryEntry] = {
    e["key"]: e for e in SECRET_REGISTRY
}


def validate_secret(key: str, value: str) -> None:
    """Zentrale Validierung für Secret-Keys und -Werte.

    Raises
    ------
    ValueError
        Bei ungültigem Key oder Wert.
    """
    if not _VALID_KEY_RE.match(key):
        raise ValueError(
            "Key darf nur Kleinbuchstaben, Ziffern und Unterstriche enthalten "
            "(max. 128 Zeichen)."
        )
    if not value or not value.strip():
        raise ValueError("Wert darf nicht leer sein.")
    if len(value) > _MAX_VALUE_LENGTH:
        raise ValueError(f"Wert zu lang (max. {_MAX_VALUE_LENGTH} Zeichen).")
    entry = _REGISTRY_BY_KEY.get(key)
    if not entry:
        return
    entry_type = entry.get("type", "str")
    if entry_type == "int":
        try:
            num = int(value)
        except ValueError:
            raise ValueError(f"Wert für '{key}' muss eine Ganzzahl sein.") from None
        if "min" in entry and num < entry["min"]:
            raise ValueError(f"Wert für '{key}' muss >= {entry['min']} sein.")
        if "max" in entry and num > entry["max"]:
            raise ValueError(f"Wert für '{key}' muss <= {entry['max']} sein.")
    elif entry_type == "float":
        try:
            num_f = float(value)
        except ValueError:
            raise ValueError(f"Wert für '{key}' muss eine Zahl sein.") from None
        if "min" in entry and num_f < entry["min"]:
            raise ValueError(f"Wert für '{key}' muss >= {entry['min']} sein.")
        if "max" in entry and num_f > entry["max"]:
            raise ValueError(f"Wert für '{key}' muss <= {entry['max']} sein.")
    elif entry_type == "url":
        if not value.startswith(("http://", "https://")):
            raise ValueError(
                f"Wert für '{key}' muss mit http:// oder https:// beginnen."
            )
    if "pattern" in entry:
        if not re.match(entry["pattern"], value):
            raise ValueError(
                f"Wert für '{key}' entspricht nicht dem erwarteten Format."
            )
