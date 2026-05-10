"""ActionSequence – DTOs fuer Phase 82 Multi-Action-Sequencing.

Saleria kann mehrere heterogene Commands in einer LLM-Antwort buendeln:

    {"action": "action_sequence", "params": {
        "steps": [
            {"action": "remote_command", "params": {"command": "todo: A"}},
            {"action": "remote_command", "params": {"command": "notiz: ..."}},
        ],
        "on_failure": "continue"
    }, "response": "Ich erledige das in 2 Schritten."}

Etappe 1 beschraenkt Steps strikt auf ``action: "remote_command"``
(Allowlist). Andere Action-Types werden beim Routing als FAILURE
markiert. Begruendung: der Silent-Execution-Pfad nutzt
``RemoteCommandHandler.execute()`` direkt -- analog zum Multi-Line-
Quick-Fix in ``message_handlers.py:1410``.

Siehe ``docs/concepts/phase-82-multi-action-sequencing.md`` fuer das
volle Konzept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

OnFailure = Literal["continue", "stop"]
"""Strategie wenn ein Step fehlschlaegt.

- ``continue`` (default): naechster Step laeuft trotzdem.
- ``stop``: restliche Steps werden als ``skipped`` markiert.
"""

ALLOWED_STEP_ACTIONS: frozenset[str] = frozenset({"remote_command"})
"""Whitelist erlaubter Step-Action-Types in Etappe 1.

Strikt: alles andere -> FAILURE mit Reason "step-action nicht erlaubt".
Erweiterung kommt, wenn der Bedarf real ist -- nicht spekulativ.
"""


@dataclass(frozen=True)
class ActionStep:
    """Ein einzelner Step in einer ActionSequence.

    Frozen-Top-Level: ``action``/``params`` koennen nicht reassigned
    werden. Achtung: ``params`` ist ein dict und intern weiterhin
    mutierbar -- die Bridge muss hier vorsichtig sein.
    """

    action: str
    params: dict[str, Any]


@dataclass(frozen=True)
class StepOutcome:
    """Ergebnis eines einzelnen Step-Runs.

    Attributes:
        index: 0-basierter Step-Index in der Sequence.
        status: ``"success"`` / ``"failure"`` / ``"skipped"``.
        summary: kurzer Text fuer die Sammel-Antwort.
        reason: bei ``failure``/``skipped`` der Grund (z.B.
            "Pending-Confirmation nicht erlaubt", "step-action nicht
            erlaubt", "Timeout").
    """

    index: int
    status: Literal["success", "failure", "skipped"]
    summary: str
    reason: str = ""


@dataclass(frozen=True)
class ActionSequenceResult:
    """Aggregiertes Ergebnis einer ActionSequence-Ausfuehrung.

    Wird von ``BridgeMessageHandler._handle_action_sequence()`` erzeugt
    und in eine Sammel-Antwort fuer den User formatiert.
    """

    steps_total: int
    steps_succeeded: int
    steps_failed: int
    steps_skipped: int
    outcomes: list[StepOutcome] = field(default_factory=list)


def parse_steps(raw: Any) -> list[ActionStep] | None:
    """Validiert und parst die ``steps``-Liste aus den LLM-Params.

    Returns:
        Liste von ActionStep wenn die Form OK ist, sonst None.
        None bedeutet: Top-Level-Form ist kaputt (kein Listentyp,
        leerer Eintrag, fehlendes ``action``-Feld). Ungueltige Steps
        werden NICHT hier gefiltert -- die Bridge laeuft sie und
        markiert sie pro Step als FAILURE (Allowlist-Check, Recursion-
        Guard, etc.). So erfaehrt der User welcher Step warum invalid
        war.
    """
    if not isinstance(raw, list):
        return None
    parsed: list[ActionStep] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        action = item.get("action")
        if not isinstance(action, str) or not action:
            return None
        params = item.get("params", {})
        if not isinstance(params, dict):
            return None
        parsed.append(ActionStep(action=action, params=params))
    return parsed


def normalize_on_failure(raw: Any) -> OnFailure:
    """Normalisiert ``on_failure`` aus den LLM-Params.

    Default ``continue`` wenn Wert fehlt oder ungueltig ist.
    """
    if raw == "stop":
        return "stop"
    return "continue"
