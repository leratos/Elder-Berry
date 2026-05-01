"""Kommunikationsprotokoll Tower ↔ Laptop – gemeinsame Nachrichtentypen."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Tower → Laptop: Befehle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionRequest:
    """Aktionsbefehl vom Tower an den Laptop.

    action_type entspricht den ActionController-Methoden:
    press_key, type_text, hotkey, move_mouse, click,
    focus_window, minimize_window, maximize_window,
    set_volume, mute, list_windows.
    """

    action_type: str
    params: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Laptop → Tower: Status / Antworten
# ---------------------------------------------------------------------------


@dataclass
class AgentStatus:
    """Gesamtstatus des Laptop-Agents."""

    online: bool = True
    hostname: str = ""
    uptime: float = 0.0
    available_actions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HealthResponse:
    """Heartbeat-Antwort vom Laptop-Agent."""

    status: str = "ok"
    hostname: str = ""
    uptime: float = 0.0
    version: str = "0.1.0"


@dataclass
class ApiResponse:
    """Einheitliche API-Antwort."""

    success: bool
    message: str = ""
    data: dict[str, Any] | None = None


@dataclass
class ActionResult:
    """Ergebnis einer ausgeführten Aktion."""

    success: bool
    action_type: str
    message: str = ""
    return_value: Any = None
