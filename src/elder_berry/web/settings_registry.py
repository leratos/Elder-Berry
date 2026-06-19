"""Registry-Logik für das Settings-Dashboard (Phase 106).

Enthält die ``SettingDefinition``-Metadaten sowie die *reine* Ableitung und
Serialisierung aus der ``SECRET_REGISTRY``. Ausgelagert aus
``settings_dashboard.py``; die zustandsabhängigen Wert-Methoden
(``_get/_validate/_store_setting_value``) bleiben am Dashboard, weil sie
``SecretStore``/``LLMRouter`` brauchen.

``SettingDefinition`` wird in ``settings_dashboard`` via ``__all__``
re-exportiert, sodass der öffentliche Importpfad
(``elder_berry.web.settings_dashboard.SettingDefinition``) stabil bleibt.

Plattformhinweis: reine Daten-/Konvertierungslogik, plattformunabhängig.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from elder_berry.web.secrets_registry import SecretRegistryEntry, _REGISTRY_BY_KEY

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SettingDefinition:
    """Metadaten für ein Dashboard-Setting."""

    key: str
    label: str
    category: str
    type: Literal["text", "textarea", "select", "number", "secret"]
    source: Literal["secret_store", "derived"] = "secret_store"
    required: bool = False
    restart_required: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    placeholder: str | None = None
    help_text: str | None = None
    options: tuple[dict[str, str], ...] = ()
    secret: bool = False
    min_value: float | None = None
    max_value: float | None = None


def registry_to_setting_definition(
    entry: SecretRegistryEntry,
    *,
    timezone_key: str,
    available_timezones: Sequence[str],
) -> SettingDefinition:
    """Konvertiert einen Registry-Eintrag in eine SettingDefinition.

    ``timezone_key``/``available_timezones`` werden injiziert (UI-spezifisch,
    nicht in der Registry hinterlegt) – das Dashboard reicht dafür seine
    ``TIMEZONE_KEY``/``AVAILABLE_TIMEZONES`` durch.
    """
    key = entry["key"]
    registry_type = entry.get("type", "str")

    ui_type: Literal["text", "textarea", "select", "number", "secret"]
    if registry_type == "textarea":
        ui_type = "textarea"
    elif registry_type == "select":
        ui_type = "select"
    elif registry_type in ("int", "float"):
        ui_type = "number"
    elif entry.get("sensitive", True) and not entry.get("behavior", False):
        ui_type = "secret"
    else:
        ui_type = "text"

    if key == timezone_key:
        options: tuple[dict[str, str], ...] = tuple(
            {"value": tz, "label": tz} for tz in sorted(available_timezones)
        )
    else:
        options = tuple(entry.get("select_options", []))

    risk_raw = entry.get("risk_level", "low")
    # Narrow auf Literal: ternary returnt str (aus dict.get()) | "low"-
    # Literal -- das letzte else "low" macht das Whole zu str. Fix: cast.
    risk_level: Literal["low", "medium", "high"] = cast(
        'Literal["low", "medium", "high"]',
        risk_raw if risk_raw in ("low", "medium", "high") else "low",
    )

    min_value = entry.get("min")
    max_value = entry.get("max")

    return SettingDefinition(
        key=key,
        label=entry["label"],
        category=entry["category"],
        type=ui_type,
        source="secret_store",
        required=entry.get("behavior", False),
        restart_required=entry.get("requires_restart", False),
        risk_level=risk_level,
        placeholder=entry.get("placeholder"),
        help_text=entry.get("description"),
        options=options,
        secret=entry.get("sensitive", True) and not entry.get("behavior", False),
        min_value=float(min_value) if min_value is not None else None,
        max_value=float(max_value) if max_value is not None else None,
    )


def build_setting_definitions(
    keys: Sequence[str],
    *,
    timezone_key: str,
    available_timezones: Sequence[str],
) -> list[SettingDefinition]:
    """Leitet SettingDefinitions aus SECRET_REGISTRY ab (Phase 52).

    Quelle: ``keys`` in der Reihenfolge der Anzeige.
    """
    definitions: list[SettingDefinition] = []
    for key in keys:
        entry = _REGISTRY_BY_KEY.get(key)
        if entry is None:
            logger.warning("Dashboard-Key '%s' nicht in SECRET_REGISTRY", key)
            continue
        definitions.append(
            registry_to_setting_definition(
                entry,
                timezone_key=timezone_key,
                available_timezones=available_timezones,
            )
        )
    return definitions


def serialize_setting_definition(definition: SettingDefinition) -> dict[str, Any]:
    """Serialisiert eine SettingDefinition für die JSON-API."""
    return {
        "key": definition.key,
        "label": definition.label,
        "category": definition.category,
        "type": definition.type,
        "source": definition.source,
        "required": definition.required,
        "restartRequired": definition.restart_required,
        "riskLevel": definition.risk_level,
        "placeholder": definition.placeholder,
        "helpText": definition.help_text,
        "options": list(definition.options),
        "secret": definition.secret,
        "minValue": definition.min_value,
        "maxValue": definition.max_value,
    }
