"""Kanonische LLM-Routing-Modi – einzige Quelle der Wahrheit.

Phase 98: Vor dieser Datei kannten Router (``llm/router.py``) und UI/Registry
(``web/settings_dashboard.py`` / ``web/secrets_registry.py``) unterschiedliche
Wertemengen für ``llm_mode`` – über das Dashboard gespeicherte Modi waren für
den Router ungültig. Diese Datei definiert die Modi (+ Anzeige-Labels) an
**einer** Stelle; Router, llm_api, Settings-Dashboard und Secrets-Registry
importieren von hier.

Bewusst ein reines Konstanten-Modul ohne schwere Importe (kein httpx /
anthropic), damit jeder Layer (auch ``web/``) gefahrlos importieren kann und
kein Import-Zyklus entsteht.
"""

from __future__ import annotations

#: Reihenfolge = Anzeige-Reihenfolge im Dashboard-Dropdown.
LLM_MODES: tuple[str, ...] = ("api_preferred", "local_preferred", "local_only")

#: Default, wenn kein (gültiger) Modus persistiert ist.
DEFAULT_LLM_MODE = "api_preferred"

#: SecretStore-Key, unter dem der Modus persistiert wird. Zentral hier, damit
#: sowohl die Web-Schicht (Dashboard/llm_api) als auch ``init_llm`` denselben
#: Key nutzen, ohne dass ``init_llm`` die Web-Schicht importieren muss.
LLM_MODE_KEY = "llm_mode"

#: key -> deutsches Label für Dashboard/Registry-Dropdown.
LLM_MODE_LABELS: dict[str, str] = {
    "api_preferred": "API bevorzugt",
    "local_preferred": "Lokal bevorzugt",
    "local_only": "Nur lokal",
}

#: Legacy-/Alt-Werte, die früher im SecretStore landen konnten, auf die
#: kanonische Menge abgebildet. ``fallback_only`` ("Nur Fallback/Lokal") war
#: das alte Registry-Label für die harte Lokal-Semantik.
_LEGACY_ALIASES: dict[str, str] = {
    "fallback_only": "local_only",
}


def normalize_llm_mode(value: str | None) -> str | None:
    """Kanonisiert einen Modus-Wert auf die gültige Menge.

    Args:
        value: Roh-Wert (z. B. aus dem SecretStore oder einem Request-Body).

    Returns:
        Den kanonischen Modus aus :data:`LLM_MODES`, oder ``None`` wenn der
        Wert weder gültig noch ein bekannter Legacy-Alias ist. Der Aufrufer
        entscheidet, ob er bei ``None`` auf :data:`DEFAULT_LLM_MODE`
        zurückfällt (Read-Back) oder einen Fehler wirft (Validierung).
    """
    if value is None:
        return None
    candidate = value.strip()
    if candidate in LLM_MODES:
        return candidate
    return _LEGACY_ALIASES.get(candidate)


def llm_mode_options() -> list[dict[str, str]]:
    """Dropdown-Optionen (``value``/``label``) in kanonischer Reihenfolge.

    Genutzt von der Secrets-Registry, damit die UI-Optionen aus derselben
    Quelle stammen wie die Router-Validierung.
    """
    return [{"value": mode, "label": LLM_MODE_LABELS[mode]} for mode in LLM_MODES]
