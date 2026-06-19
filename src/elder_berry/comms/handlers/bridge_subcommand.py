"""BridgeMessageHandler-Mixin: Sub-Command-Ausführung + Retry/Vorschlag (Phase 106).

Phase 106 (Modul-Entflechtung): aus ``message_handlers.py`` ausgelagert
(Phase-82-Block, Ausführungs-Teil). Wird sowohl von der action_sequence-
Engine (``_execute_single_step``) als auch vom LLM→Remote-Command-Pfad
genutzt. ``self`` ist mit ``BridgeMessageHandler`` typisiert (Vererbung).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from elder_berry.comms.action_sequence import StepOutcome
from elder_berry.comms.handlers._bridge_base import BridgeHandlerBase

if TYPE_CHECKING:
    from elder_berry.comms.commands.base import CommandResult
    from elder_berry.comms.message_channel import IncomingMessage

logger = logging.getLogger(__name__)


class SubCommandMixin(BridgeHandlerBase):
    """Einzel-/Multi-Line-Command-Ausführung + Retry + Plugin-Vorschlag."""

    async def _execute_sub_command(
        self,
        index: int,
        command_text: str,
        msg: IncomingMessage,
    ) -> StepOutcome:
        """Fuehrt EINEN Command-String aus, returnt EIN Outcome.

        Phase 82.1: extrahiert aus dem alten ``_execute_single_step``,
        damit derselbe Pfad sowohl von Single-Line-Steps als auch von
        Multi-Line-Sub-Calls genutzt werden kann -- 1 Quelle der
        Wahrheit fuer parse + execute + pending-/restart-Filter +
        side-effects.
        """
        assert self._remote_commands is not None

        # Command parsen
        parsed_cmd = self._remote_commands.parse_command(command_text)
        if parsed_cmd is None:
            return StepOutcome(
                index=index,
                status="failure",
                summary=command_text,
                reason="kein bekannter command",
            )

        # Command ausfuehren
        loop = asyncio.get_running_loop()
        try:
            result: CommandResult = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._remote_commands.execute,
                    parsed_cmd,
                    command_text,
                ),
                timeout=60.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "action_sequence step %d ('%s') fehlgeschlagen: %s",
                index,
                command_text,
                exc,
            )
            return StepOutcome(
                index=index,
                status="failure",
                summary=command_text,
                reason=type(exc).__name__,
            )

        # Pending-Confirmation-Filter (detect-after-fact, R3)
        if result.pending_confirmation:
            # PendingAction NICHT setzen -- die Sequenz darf nicht den User
            # mitten drin in einen Confirm-Flow zwingen. Etappe 3 loest das.
            self._pending.clear(msg.sender)
            return StepOutcome(
                index=index,
                status="failure",
                summary=command_text,
                reason="Step verlangt Bestaetigung -- in Sequenz nicht erlaubt",
            )

        # Restart-Filter (Phase 82 PR-Review): asyncio loop wuerde sterben.
        if result.restart:
            return StepOutcome(
                index=index,
                status="failure",
                summary=command_text,
                reason="Restart darf nicht Teil einer Sequenz sein",
            )

        if result.success:
            # Side-Effects: Bilder, Dateien, list_items registrieren.
            self._maybe_register_command_list(msg, result)
            await self._apply_command_side_effects(msg, result)
            return StepOutcome(
                index=index,
                status="success",
                summary=result.text or command_text,
            )

        return StepOutcome(
            index=index,
            status="failure",
            summary=command_text,
            reason=result.text or "unbekannter Fehler",
        )

    async def _execute_multi_line_commands(
        self,
        msg: IncomingMessage,
        parsed_lines: list[tuple[str, str]],
    ) -> None:
        """Fuehrt mehrere Commands sequentiell aus, sendet eine Sammel-Antwort.

        Args:
            msg: Die Original-User-Nachricht (fuer room_id, sender).
            parsed_lines: ``[(raw_line, parsed_command), ...]`` -- bereits
                via parse_command validiert.
        """
        assert self._remote_commands is not None  # caller-side gepruefft

        loop = asyncio.get_running_loop()
        successes: list[str] = []
        failures: list[tuple[str, str]] = []

        for raw_line, parsed_cmd in parsed_lines:
            try:
                result: CommandResult = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._remote_commands.execute,
                        parsed_cmd,
                        raw_line,
                    ),
                    timeout=60.0,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Multi-Line-Command '%s' fehlgeschlagen: %s",
                    raw_line,
                    exc,
                )
                failures.append((raw_line, type(exc).__name__))
                continue

            if result.success:
                successes.append(result.text or raw_line)
            else:
                failures.append((raw_line, result.text or "unbekannter Fehler"))

        # Sammel-Antwort an den User. Knapp halten: erst Bilanz, dann
        # die Kurz-Texte der Einzel-Ergebnisse.
        bilanz_parts = [f"✅ {len(successes)} ausgefuehrt"]
        if failures:
            bilanz_parts.append(f"❌ {len(failures)} fehlgeschlagen")
        body = " · ".join(bilanz_parts)

        if successes:
            details = "\n".join(f"  - {text}" for text in successes)
            body += f"\n\n{details}"
        if failures:
            fail_lines = "\n".join(f"  - {line}: {reason}" for line, reason in failures)
            body += f"\n\nFehler:\n{fail_lines}"

        try:
            await self._channel.send_text(msg.room_id, body)
        except Exception as exc:  # pragma: no cover
            logger.error(
                "Multi-Line-Sammel-Antwort konnte nicht gesendet werden: %s", exc
            )

    async def _propose_plugin_for_failed_command(
        self,
        msg: IncomingMessage,
        command_text: str,
    ) -> bool:
        """Versucht, aus einem nicht-erkannten Command einen Plugin-Vorschlag zu machen.

        Returns:
            True wenn der Aggregator gefuettert wurde (User bekommt Notiz-
            Hinweis). False wenn nichts passiert ist (User bekommt nur den
            Standard-Hilfe-Hinweis): Aggregator nicht verdrahtet, LLM hat
            keinen plugin-candidate geliefert, Intent ist abgelehnt, oder
            irgendwo ist ein Fehler passiert.
        """
        if self._proposal_aggregator is None:
            return False

        # Dritter LLM-Call: einen <plugin-candidate>-Block fuer den
        # nicht-erkannten Command erfragen. Wenn das LLM unsicher ist,
        # liefert es laut Prompt einen leeren Block (= kein Match).
        prompt = (
            f"Der Befehl '{command_text}' wurde an Saleria gerichtet, "
            f"ist aber im aktuellen System nicht implementiert.\n\n"
            f"Falls das eine echte fehlende Capability ist (kein Tippfehler, "
            f"keine Smalltalk-Frage), antworte AUSSCHLIESSLICH mit einem "
            f"<plugin-candidate>-Block in folgendem Format:\n"
            f"<plugin-candidate>\n"
            f'{{"intent":"snake_case_id","title":"Kurzer Titel",'
            f'"description":"2-3 Saetze was die Capability tun wuerde",'
            f'"category":"medien|system|productivity|...",'
            f'"confidence":0.0-1.0}}\n'
            f"</plugin-candidate>\n\n"
            f"Wenn du dir nicht sicher bist oder es Smalltalk/Tippfehler "
            f"sein koennte: antworte mit dem leeren String, KEINEN Block."
        )

        try:
            from elder_berry.core.assistant import Assistant

            loop = asyncio.get_running_loop()
            raw = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._assistant.generate_raw,
                    prompt,
                    "",
                    "",
                ),
                timeout=30.0,
            )
        except Exception as exc:
            logger.error("Plugin-Vorschlag-LLM fehlgeschlagen: %s", exc)
            return False

        if not raw:
            return False

        _, candidate = Assistant._extract_plugin_candidate(raw)
        if candidate is None:
            return False

        intent = str(candidate.get("intent", "")).strip()
        if not intent:
            return False

        # Status-Check: abgelehnt -> still ueberspringen, kein Re-Vorschlag.
        try:
            if self._proposal_aggregator.is_rejected(intent):
                logger.info(
                    "Plugin-Vorschlag '%s' bereits abgelehnt -- ueberspringe",
                    intent,
                )
                return False
        except Exception as exc:
            logger.error("is_rejected-Check fehlgeschlagen fuer %r: %s", intent, exc)
            # Defensive: lieber einmal zu viel triggern als crashen.

        # An Aggregator weiterreichen; dort greifen Smalltalk-Filter,
        # Confidence-Schwelle, Threshold-Logik (Phase 78).
        try:
            await self._proposal_aggregator.record(
                intent=intent,
                title=str(candidate.get("title", "")),
                description=str(candidate.get("description", "")),
                sample=command_text,
                sender=msg.sender,
                confidence=float(candidate.get("confidence", 0.0)),
                category=candidate.get("category"),
            )
        except Exception as exc:
            logger.error(
                "Plugin-Vorschlag '%s' konnte nicht aufgenommen werden: %s",
                intent,
                exc,
            )
            return False

        logger.info(
            "Phase 81b: Plugin-Vorschlag '%s' aus Command-Fallback aufgenommen",
            intent,
        )
        return True

    async def _retry_llm_remote_command(
        self,
        msg: IncomingMessage,
        failed_command: str,
    ) -> str | None:
        """Gibt dem LLM Feedback über den fehlgeschlagenen Command."""
        assert self._remote_commands is not None  # caller filtered (line above)
        summary = self._remote_commands.get_command_summary()
        retry_prompt = (
            f"Der Command '{failed_command}' wurde nicht erkannt. "
            f"Verfügbare Remote-Commands:\n{summary}\n\n"
            f"Antworte NUR mit dem korrekten Command-String, nichts anderes. "
            f"Beispiel: mail suche Rechnung"
        )

        try:
            loop = asyncio.get_running_loop()
            chat_context = self._chat_history.format_for_prompt(msg.sender)
            raw = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._assistant.generate_raw,
                    retry_prompt,
                    "",
                    chat_context,
                ),
                timeout=60.0,
            )

            if raw:
                candidate = raw.strip()
                if self._remote_commands.parse_command(candidate):
                    logger.info("LLM Retry → Command aus Response: %s", candidate)
                    return candidate

        except Exception as e:
            logger.error("LLM Retry fehlgeschlagen: %s", e)

        return None
