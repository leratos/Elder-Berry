"""TaskChainRunner – Multi-Step Task Chaining für verkettete Commands.

Erlaubt dem LLM, mehrere Remote-Commands nacheinander auszuführen,
wobei jedes Zwischenergebnis als Kontext für den nächsten Schritt dient.

Beispiel: "Lies meine Mails und trag den Zahnarzttermin ein"
  → Step 1: mails → "3 ungelesene Mails..."
  → Step 2: mail suche Zahnarzt → "Mail gefunden: 15.04 14:00"
  → Step 3: termin: Zahnarzt 2026-04-15 14:00 → "Termin erstellt"
  → DONE → Zusammenfassung an User
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.llm.base import LLMClient

logger = logging.getLogger(__name__)

# Max Zeichen pro Command-Ergebnis im Kontext (verhindert Kontext-Flooding)
DEFAULT_MAX_RESULT_CHARS = 2000
DEFAULT_MAX_STEPS = 5

CHAIN_SYSTEM_PROMPT = """\
Du führst eine mehrstufige Aufgabe aus. Du bekommst die ursprüngliche Anfrage \
des Nutzers und die bisherigen Schritte mit ihren Ergebnissen.

In jedem Schritt antwortest du im JSON-Format:
{{"action": "<command>", "response": "<kurzer Status für den Nutzer>"}}

Regeln:
- "action" ist ein Remote-Command (z.B. "mails", "mail suche Rechnung", \
"termin: Zahnarzt morgen 14:00")
- Nutze die Ergebnisse vorheriger Schritte um den nächsten Schritt zu planen
- Wenn die Aufgabe erledigt ist: {{"action": "DONE", "response": "<Zusammenfassung>"}}
- Wenn du nicht weiterkommst: {{"action": "DONE", "response": "<was schief ging>"}}
- Maximal {max_steps} Schritte erlaubt
- Antworte immer auf Deutsch

Verfügbare Remote-Commands:
- mails: Ungelesene E-Mails anzeigen
- mail suche <begriff>: E-Mails durchsuchen
- mail anhang <id>: Anhänge einer Mail senden
- termine / termine morgen / termine woche: Kalender-Termine
- termin suche <begriff>: Termine durchsuchen
- termin: <Titel> <Datum> <Uhrzeit>: Termin erstellen
- termin löschen <Titel/ID>: Termin löschen
- training / training details / prs: Fitness-Daten
- wetter / wetter morgen / wetter woche: Wetter
- timer <dauer>: Timer setzen
- erinnere mich um/in <zeit>: <nachricht>: Erinnerung
- erinnerungen: Offene Erinnerungen
- briefing: Tagesübersicht
- suche <begriff>: Internet-Suche
- notiz: <text>: Notiz speichern
- merk dir: <schlüssel> ist <wert>: Fakt speichern
- was ist <schlüssel>?: Fakt abrufen
- notizen / notizen suche <begriff>: Notizen verwalten
"""


@dataclass
class StepResult:
    """Ergebnis eines einzelnen Schritts in der Chain."""

    step_number: int
    """1-basierter Schritt-Index."""

    command: str
    """Ausgeführter Remote-Command."""

    result_text: str
    """Ergebnis-Text des Commands (ggf. gekürzt)."""

    success: bool
    """True wenn der Command erfolgreich war."""

    llm_response: str
    """Status-Text den das LLM für den Nutzer generiert hat."""


@dataclass
class ChainResult:
    """Gesamtergebnis einer Multi-Step Chain."""

    steps: list[StepResult] = field(default_factory=list)
    """Alle ausgeführten Schritte."""

    final_summary: str = ""
    """Zusammenfassung des LLM nach Abschluss."""

    completed: bool = False
    """True wenn die Chain mit DONE beendet wurde (nicht abgebrochen)."""

    @property
    def all_success(self) -> bool:
        """True wenn alle Schritte erfolgreich waren."""
        return all(s.success for s in self.steps)

    @property
    def step_count(self) -> int:
        """Anzahl ausgeführter Schritte."""
        return len(self.steps)


class TaskChainRunner:
    """Führt verkettete Remote-Commands basierend auf LLM-Entscheidungen aus.

    Args:
        llm: LLM-Client für die Schritt-Planung.
        remote_commands: RemoteCommandHandler für Command-Ausführung.
        max_steps: Maximale Anzahl Schritte (default: 5).
        max_result_chars: Max Zeichen pro Ergebnis im Kontext (default: 2000).
    """

    def __init__(
        self,
        llm: LLMClient,
        remote_commands: RemoteCommandHandler,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_result_chars: int = DEFAULT_MAX_RESULT_CHARS,
    ) -> None:
        self._llm = llm
        self._remote_commands = remote_commands
        self._max_steps = max_steps
        self._max_result_chars = max_result_chars

    def run(
        self,
        user_request: str,
        chat_history: str = "",
        on_step: callable | None = None,
    ) -> ChainResult:
        """Führt eine Multi-Step Chain aus.

        Args:
            user_request: Ursprüngliche Nutzer-Anfrage.
            chat_history: Bisheriger Chat-Verlauf als Kontext.
            on_step: Optionaler Callback pro Schritt: on_step(StepResult).
                     Kann für Zwischenstatus-Nachrichten genutzt werden.

        Returns:
            ChainResult mit allen Schritten und Zusammenfassung.
        """
        chain = ChainResult()
        system_prompt = self._build_system_prompt()
        step_context = self._build_initial_context(user_request, chat_history)

        for step_num in range(1, self._max_steps + 1):
            logger.info("Chain Step %d/%d", step_num, self._max_steps)

            # LLM nach nächstem Schritt fragen
            raw_response = self._llm.generate(step_context, system=system_prompt)
            logger.debug("Chain LLM-Antwort: %s", raw_response[:200])

            parsed = self._parse_response(raw_response)
            action = parsed.get("action")
            response_text = parsed.get("response", "")

            # DONE → Chain beenden
            if not action or action.upper() == "DONE":
                chain.final_summary = response_text or "Aufgabe abgeschlossen."
                chain.completed = True
                logger.info("Chain beendet nach %d Schritten", chain.step_count)
                break

            # Command ausführen
            step = self._execute_step(step_num, action, response_text)
            chain.steps.append(step)

            # Callback für Zwischenstatus
            if on_step:
                try:
                    on_step(step)
                except Exception as e:
                    logger.debug("on_step Callback Fehler: %s", e)

            # Kontext für nächsten Schritt aufbauen
            step_context = self._build_step_context(
                user_request, chain.steps,
            )
        else:
            # Max Steps erreicht ohne DONE
            chain.final_summary = (
                f"Maximale Schrittanzahl ({self._max_steps}) erreicht. "
                f"{chain.step_count} Schritte ausgeführt."
            )
            logger.warning("Chain max_steps erreicht: %d", self._max_steps)

        return chain

    def _execute_step(
        self, step_num: int, command: str, llm_response: str,
    ) -> StepResult:
        """Führt einen einzelnen Command-Schritt aus."""
        logger.info("Chain execute: %s", command)

        # Command parsen
        parsed_cmd = self._remote_commands.parse_command(command)
        if not parsed_cmd:
            logger.warning("Chain: Command nicht erkannt: %s", command)
            return StepResult(
                step_number=step_num,
                command=command,
                result_text=f"Command nicht erkannt: {command}",
                success=False,
                llm_response=llm_response,
            )

        # Command ausführen
        try:
            result = self._remote_commands.execute(parsed_cmd, command)
            result_text = result.history_text or result.text or ""

            # Ergebnis kürzen wenn nötig
            if len(result_text) > self._max_result_chars:
                result_text = (
                    result_text[: self._max_result_chars]
                    + "\n... (gekürzt)"
                )

            return StepResult(
                step_number=step_num,
                command=command,
                result_text=result_text,
                success=result.success,
                llm_response=llm_response,
            )
        except Exception as e:
            logger.error("Chain Step %d fehlgeschlagen: %s", step_num, e)
            return StepResult(
                step_number=step_num,
                command=command,
                result_text=f"Fehler: {type(e).__name__}: {e}",
                success=False,
                llm_response=llm_response,
            )

    def _build_system_prompt(self) -> str:
        """Baut den System-Prompt für die Chain."""
        return CHAIN_SYSTEM_PROMPT.format(max_steps=self._max_steps)

    def _build_initial_context(
        self, user_request: str, chat_history: str,
    ) -> str:
        """Baut den initialen Kontext für den ersten Schritt."""
        parts = []
        if chat_history:
            parts.append(f"Bisheriger Chat-Verlauf:\n{chat_history}\n")
        parts.append(f"Aufgabe des Nutzers: {user_request}")
        parts.append("\nWas ist der erste Schritt?")
        return "\n".join(parts)

    def _build_step_context(
        self, user_request: str, steps: list[StepResult],
    ) -> str:
        """Baut den Kontext mit bisherigen Schritten für den nächsten LLM-Call."""
        parts = [f"Aufgabe des Nutzers: {user_request}\n"]
        parts.append("Bisherige Schritte:")

        for step in steps:
            status = "OK" if step.success else "FEHLER"
            parts.append(
                f"\nSchritt {step.step_number}: {step.command} → [{status}]"
            )
            if step.result_text:
                parts.append(f"Ergebnis: {step.result_text}")

        parts.append("\nWas ist der nächste Schritt? (oder DONE wenn fertig)")
        return "\n".join(parts)

    def _parse_response(self, raw: str) -> dict:
        """Parst JSON aus der LLM-Antwort (wie Assistant._parse_llm_response)."""
        # Versuch 1: Gesamter String
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Versuch 2: JSON-Block extrahieren
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass

        # Fallback: Rohe Antwort als DONE
        logger.warning("Chain: LLM-Antwort nicht parsbar, beende Chain")
        return {"action": "DONE", "response": raw}
