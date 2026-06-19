"""BridgeMessageHandler – Nachrichtenverarbeitung für die MatrixBridge.

Kapselt alle Handler-Methoden die von der Bridge an verschiedene
Subsysteme delegieren:
- Remote Commands (direkte Befehle ohne LLM)
- Claude Agent (komplexe Anfragen via Claude API)
- LLM Enrichment (Dokument-/Mail-Zusammenfassungen)
- Assistant Messages (Standard-LLM-Flow)
- Multi-Step Tasks (TaskChainRunner)
- Pending Confirmations → delegiert an ConfirmationHandler

Phase 106 (Modul-Entflechtung): Die Handler-Logik ist in Mixins unter
``elder_berry.comms.handlers`` geschnitten (Enrichment / FileHub / ListPick /
PickDispatch / LlmFlow / ActionSequence / SubCommand). ``BridgeMessageHandler``
erbt sie. Bewusst HIER geblieben sind die beiden logger-asserted Einstiege
``handle_remote_command`` und ``handle_assistant_message`` (ihr ``logger`` ist
damit der dieses Moduls -> ``patch("…message_handlers.logger")`` greift ohne
Umweg), die Pending-Confirmation-Delegatoren und ``__init__``. ``logger`` und
``BridgeMessageHandler`` bleiben am öffentlichen Importpfad.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from elder_berry.comms.confirmation_handlers import ConfirmationHandler
from elder_berry.comms.handlers.bridge_actionseq import ActionSequenceMixin
from elder_berry.comms.handlers.bridge_enrichment import EnrichmentMixin
from elder_berry.comms.handlers.bridge_filehub import FileHubMixin
from elder_berry.comms.handlers.bridge_listpick import ListPickMixin
from elder_berry.comms.handlers.bridge_llmflow import LlmFlowMixin
from elder_berry.comms.handlers.bridge_picks import PickDispatchMixin
from elder_berry.comms.handlers.bridge_subcommand import SubCommandMixin
from elder_berry.comms.pending_confirmation import PendingAction
from elder_berry.comms.pending_initiative import PendingInitiativeStore

if TYPE_CHECKING:
    from elder_berry.comms.audio_pipeline import AudioPipeline
    from elder_berry.comms.chat_history import ChatHistory
    from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
    from elder_berry.comms.pending_confirmation import PendingConfirmationStore
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.comms.scheduler_manager import SchedulerManager
    from elder_berry.core.assistant import Assistant
    from elder_berry.core.task_chain import TaskChainRunner
    from elder_berry.comms.claude_agent import ClaudeAgent
    from elder_berry.tools.conversation_list_store import ConversationListStore
    from elder_berry.tools.email_client import IMAPEmailClient
    from elder_berry.tools.email_sender import EmailSender
    from elder_berry.tools.intent_aggregator import ProposalIntentAggregator
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient

    # CommandResult ist konkrete Klasse aus base.py (nicht Optional-DTO).
    from elder_berry.comms.commands.base import CommandResult

logger = logging.getLogger(__name__)


class BridgeMessageHandler(
    EnrichmentMixin,
    FileHubMixin,
    ListPickMixin,
    PickDispatchMixin,
    LlmFlowMixin,
    ActionSequenceMixin,
    SubCommandMixin,
):
    """Verarbeitet eingehende Nachrichten für die MatrixBridge.

    Wird von MatrixBridge erstellt und erhält alle nötigen Dependencies
    über den Konstruktor. Die Handler-Logik liegt in den geerbten Mixins
    (Phase 106); hier bleiben ``__init__``, die beiden logger-asserted
    Einstiege (Remote-Command / Standard-LLM) und die Pending-Confirmation-
    Delegatoren.
    """

    def __init__(
        self,
        channel: MessageChannel,
        assistant: Assistant,
        audio_pipeline: AudioPipeline,
        chat_history: ChatHistory,
        pending: PendingConfirmationStore,
        remote_commands: RemoteCommandHandler | None = None,
        claude_agent: ClaudeAgent | None = None,
        task_chain: TaskChainRunner | None = None,
        email_sender: EmailSender | None = None,
        email_client: IMAPEmailClient | None = None,
        nextcloud_files: NextcloudFilesClient | None = None,
        proposal_aggregator: ProposalIntentAggregator | None = None,
        conversation_lists: ConversationListStore | None = None,
        pending_initiative: PendingInitiativeStore | None = None,
    ) -> None:
        self._channel = channel
        self._assistant = assistant
        self._audio = audio_pipeline
        self._chat_history = chat_history
        self._pending = pending
        # Phase 89 (Pfad C): Store für Saleria-Initiativ-Vorschläge. Default
        # erzeugt eine eigene Instanz; im Bridge-Betrieb wird dieselbe Instanz
        # injiziert, die der Bridge-Intercept prüft.
        self._pending_initiative = pending_initiative or PendingInitiativeStore()
        self._remote_commands = remote_commands
        self._claude_agent = claude_agent
        self._task_chain = task_chain
        self._email_sender = email_sender
        self._email_client = email_client
        self._nc_files = nextcloud_files
        self._proposal_aggregator = proposal_aggregator
        self._conversation_lists = conversation_lists
        # Mutable State (gesetzt von Bridge)
        self.restart_cooldown_until: float = 0.0
        self._scheduler_mgr: SchedulerManager | None = None
        # Guard gegen Endlosrekursion: LLM → remote_command → fallthrough → LLM → ...
        self._in_llm_command: set[str] = set()

        # Confirmation-Handler (Mail, Filing, Restart, Nextcloud)
        self._confirm = ConfirmationHandler(self)

    # ------------------------------------------------------------------
    # Remote Commands
    # ------------------------------------------------------------------

    # Commands die länger brauchen (Netzwerk-Sync, Updates etc.)
    _LONG_RUNNING_COMMANDS = {
        "contact_sync",
        "system_update",
        "git_pull",
        # Phase 101-T (PR #318 Codex P2): LLM-Triage laeuft synchron im Executor;
        # im Privacy-Modus ueber lokales Ollama (bis 120s HTTP-Timeout) -> der
        # Default-60s-Command-Timeout wuerde dem Nutzer einen Timeout zeigen,
        # waehrend der Thread noch klassifiziert.
        "mail_triage",
    }

    async def handle_remote_command(
        self,
        msg: IncomingMessage,
        command: str,
    ) -> None:
        """Führt einen direkten Remote-Command aus und sendet das Ergebnis."""
        # Bridge.handle_message filtert "if self._remote_commands:" bevor
        # parse_command + diese Methode laufen.
        assert self._remote_commands is not None

        # Phase 80 Etappe 3 Korrektur: "lies Mail 3" / "Mail 3" matcht
        # MAIL_ID_PATTERN direkt -- die Bridge wuerde sonst "3" als IMAP-UID
        # interpretieren und der list_pick-Pfad waere nie erreicht. Wenn eine
        # aktive mail_inbox-Liste existiert und N <= len(items), reroute auf
        # den Listen-Eintrag (echte msg_id). N > len -> echter UID-Lookup.
        # _in_llm_command-Guard verhindert Rekursion: wenn _dispatch_mail_pick
        # die echte UID dispatcht und die zufaellig auch <= len(items) ist,
        # darf der Reroute nicht erneut zuschlagen.
        if (
            command == "mail_by_id"
            and self._conversation_lists is not None
            and msg.sender not in self._in_llm_command
        ):
            if await self._maybe_reroute_mail_to_list_pick(msg):
                return

        logger.info("Remote-Command erkannt: %s", command)
        timeout = 300.0 if command in self._LONG_RUNNING_COMMANDS else 60.0

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._remote_commands.execute,
                    command,
                    msg.body,
                ),
                timeout=timeout,
            )

            # Fallthrough: Command erkannt aber nichts gefunden → LLM
            # ABER: nicht wenn wir bereits aus einem LLM-initiierten Command
            # kommen (verhindert Endlosrekursion LLM→Command→fallthrough→LLM)
            if result.fallthrough:
                if msg.sender in self._in_llm_command:
                    logger.warning(
                        "Fallthrough '%s' blockiert (LLM-initiiert, Rekursions-Guard)",
                        command,
                    )
                    return
                logger.debug("Command '%s' fallthrough → LLM", command)
                await self.handle_assistant_message(msg)
                return

            # Dokument-Zusammenfassung: Rohtext ans LLM schicken
            if (
                result.command == "document_summary"
                and result.success
                and result.history_text
            ):
                await self._handle_document_summary(msg, result)
                return

            # Web-Zusammenfassung: Webseiten-Inhalt ans LLM schicken
            if (
                result.command == "web_summary"
                and result.success
                and result.history_text
            ):
                await self._handle_web_summary(msg, result)
                return

            # Mail per ID: Body ans LLM schicken
            if (
                result.command == "mail_by_id"
                and result.success
                and result.history_text
            ):
                await self._handle_mail_summary(msg, result)
                return

            # Pending Confirmation (Phase 28: Email-Reply Draft)
            if result.pending_confirmation and result.pending_data:
                action_type = (
                    result.pending_data.pop("action_type", None) or result.command
                )
                pending_action = PendingAction(
                    action_type=action_type,
                    description=result.text or "",
                    data=result.pending_data,
                )
                self._pending.set(msg.sender, pending_action)
                if result.text:
                    await self._channel.send_text(msg.room_id, result.text)
                self._chat_history.add(msg.sender, "user", msg.body)
                self._chat_history.add(
                    msg.sender,
                    "assistant",
                    result.text or "",
                )
                return

            # Phase 80: Strukturierte Mehrfachergebnisse im
            # ConversationListStore registrieren -- danach kann der LLM
            # via list_pick auf Eintrag N zeigen, ohne URLs zu raten.
            # Side-Effekt; Register-Fehler darf den User-Flow nicht
            # crashen (defensiv: log+continue).
            self._maybe_register_command_list(msg, result)

            # Text-Antwort senden
            if result.text:
                await self._channel.send_text(msg.room_id, result.text)

            # Command-Ergebnis in Chat-History speichern
            if result.success and result.text:
                history_content = result.history_text or result.text
                self._chat_history.add(msg.sender, "user", msg.body)
                self._chat_history.add(msg.sender, "assistant", history_content)

            # Fehlgeschlagene Commands loggen (nicht bei Fallthrough –
            # das ist kein Fehler, sondern bewusste Delegation ans LLM)
            if not result.success and not result.fallthrough:
                logger.error(
                    "Command '%s' fehlgeschlagen: %s",
                    command,
                    result.text or "Command fehlgeschlagen",
                    extra={"sender": msg.sender, "handler": f"command:{command}"},
                )

            await self._apply_command_side_effects(msg, result)

            # Restart
            if result.restart:
                if time.monotonic() < self.restart_cooldown_until:
                    logger.warning(
                        "Restart-Cooldown aktiv, ignoriere restart-Befehl (noch %.0fs)",
                        self.restart_cooldown_until - time.monotonic(),
                    )
                    await self._channel.send_text(
                        msg.room_id,
                        "Restart-Cooldown aktiv – ich wurde gerade erst "
                        "neu gestartet. Bitte warte noch etwas.",
                    )
                    return
                from elder_berry.comms.restart_manager import perform_restart

                await perform_restart(
                    self._channel,
                    self._scheduler_mgr,
                    msg.room_id,
                    msg_server_ts=msg.timestamp,
                )

        except asyncio.TimeoutError:
            logger.error("Timeout bei Remote-Command '%s' (%.0fs)", command, timeout)
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Zeitüberschreitung bei der Command-Ausführung.",
                )
            except Exception:
                # Best-effort: Timeout-Notification darf den Outer-Handler nicht crashen.
                pass
        except Exception as e:
            logger.error(
                "Remote-Command '%s' fehlgeschlagen: %s",
                command,
                e,
                extra={"sender": msg.sender, "handler": "command"},
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Command-Fehler: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")

    async def _apply_command_side_effects(
        self,
        msg: IncomingMessage,
        result: CommandResult,
    ) -> None:
        """Liefert Artefakte aus einem CommandResult an den User aus.

        Phase 82 PR-Review (Codex P2): Vorher waren image_path/file_path/
        file_paths inline in ``handle_remote_command`` -- die Sequenz-Pipeline
        (``_execute_single_step``) konnte sie nicht nutzen und meldete dem
        User Erfolg, ohne das eigentliche Artefakt zu liefern (z.B. Foto in
        einer "mach Foto UND schreib Notiz"-Sequenz). Jetzt nutzen beide
        Pfade denselben Helper, eine Quelle der Wahrheit.

        Bewusst NICHT enthalten:
        - ``result.text`` -- Caller-spezifisch (Sequenz hat Sammel-Antwort).
        - ``result.list_items`` -- bleibt in ``_maybe_register_command_list``,
          weil die Reihenfolge "registrieren VOR send_text" semantisch
          wichtig ist (User koennte sofort auf die Liste antworten).
        - ``result.restart`` -- Caller-spezifisch (Cooldown-Logik in
          ``handle_remote_command``; in der Sequenz wird restart als FAILURE
          markiert, siehe ``_execute_single_step``).
        - ``result.pending_confirmation`` -- Caller-spezifisch.
        """
        # Bild senden (Screenshot): direkt per Matrix (Inline-Preview)
        if result.image_path and result.image_path.exists():
            try:
                await self._channel.send_image(
                    msg.room_id,
                    result.image_path,
                )
            except NotImplementedError:
                await self._channel.send_text(
                    msg.room_id,
                    "Screenshot aufgenommen, aber Bild-Upload nicht unterstützt.",
                )
            finally:
                result.image_path.unlink(missing_ok=True)

        # Datei senden: über Nextcloud (Upload + Share-Link) oder Matrix-Fallback
        if result.file_path and result.file_path.exists():
            await self._send_file_via_nc_or_matrix(
                msg.room_id,
                result.file_path,
            )

        # Mehrere Dateien senden (z.B. Mail-Anhänge)
        if result.file_paths:
            if result.command == "mail_attachment" and self._nc_files:
                await self._handle_attachment_upload_with_menu(
                    msg,
                    result.file_paths,
                )
            else:
                for fpath in result.file_paths:
                    if fpath.exists():
                        await self._send_file_via_nc_or_matrix(
                            msg.room_id,
                            fpath,
                            cleanup=True,
                        )

    # ------------------------------------------------------------------
    # Pending Confirmation – delegiert an ConfirmationHandler
    # ------------------------------------------------------------------

    async def handle_pending_confirm(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Führt eine bestätigte PendingAction aus."""
        # ConfirmationHandler liest restart_cooldown_until via self._p
        # (Parent-Reference, siehe confirmation_handlers.py:422). Die alte
        # Direkt-Zuweisung war eine tote Refactoring-Spur.
        await self._confirm.handle_confirm(msg, action)

    async def handle_pending_modify(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Generiert einen neuen Draft basierend auf der Änderungsanweisung."""
        await self._confirm.handle_modify(msg, action)

    async def handle_filing_response(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Verarbeitet Filing-Antworten die kein Standard-Confirm/Cancel sind."""
        await self._confirm.handle_filing_response(msg, action)

    async def handle_attachment_menu_response(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Verarbeitet Anhang-Aktionsmenü-Antworten."""
        await self._confirm.handle_attachment_menu(msg, action)

    # ------------------------------------------------------------------
    # Standard LLM (Assistant)
    # ------------------------------------------------------------------

    async def handle_assistant_message(self, msg: IncomingMessage) -> None:
        """Delegiert an Assistant.process() (Standard-LLM-Flow)."""
        # Phase 97: Nearby-Rueckfrage-Folgeturn. Liegt ein offener Draft
        # (default_user_id), wird die Freitext-Antwort ("zu Fuss"/"Leipzig")
        # als fehlendes Feld gedeutet -- VOR dem LLM (Early-Intercept).
        if await self._maybe_continue_nearby_draft(msg):
            return

        tmp_wav: Path | None = None

        try:
            loop = asyncio.get_running_loop()

            self._chat_history.add(msg.sender, "user", msg.body)
            chat_context = self._chat_history.format_for_prompt(msg.sender)

            # Phase 70 (H-2): TOCTOU-frei via NamedTemporaryFile.
            # tmp_wav wurde oben deklariert (Line 663) -- redundante Re-Annotation
            # entfernt.
            if self._audio.audio_to_matrix:
                with tempfile.NamedTemporaryFile(
                    suffix=".wav",
                    delete=False,
                ) as fh:
                    tmp_wav = Path(fh.name)
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._assistant.process,
                    msg.body,
                    tmp_wav,
                    chat_context,
                ),
                timeout=120.0,
            )

            # Phase 82: action_sequence hat harten Vorrang vor allen anderen
            # Action-Types. Insbesondere darf der Multi-Line-Quick-Fix in
            # _handle_llm_remote_command nicht greifen, wenn Saleria
            # action_sequence emittiert hat (Vermeidung von Doppel-
            # Verarbeitung, siehe Konzept §3.2).
            if (
                result.action_executed == "action_sequence"
                and result.action_success
                and self._remote_commands
            ):
                await self._handle_action_sequence(msg, result)
                return

            # Multi-Step
            if (
                result.action_executed == "multi_step"
                and result.action_success
                and self._task_chain
            ):
                await self._handle_multi_step(msg, result, chat_context)
                return

            # Phase 80: LLM -> list_pick (User referenziert Listen-Position)
            if result.action_executed == "list_pick" and result.action_success:
                await self._handle_list_pick(msg, result)
                return

            # LLM → Remote Command
            if (
                result.action_executed == "remote_command"
                and result.action_success
                and self._remote_commands
            ):
                await self._handle_llm_remote_command(msg, result)
                return

            # Phase 89 (Pfad C): LLM → Initiativ-Vorschlag (propose_action).
            # Command NICHT sofort ausfuehren -- als PendingInitiative ablegen.
            if result.action_executed == "propose_action" and result.action_success:
                await self._handle_propose_action(msg, result, tmp_wav)
                return

            if result.response:
                self._chat_history.add(msg.sender, "assistant", result.response)
                await self._channel.send_text(msg.room_id, result.response)

            await self._audio.send_audio_if_available(msg.room_id, result, tmp_wav)

            # Phase 78: Plugin-Kandidat aus dem LLM-Output an den
            # Aggregator weiterreichen. Nur im echten LLM-Fallback (keine
            # action_executed) -- bei multi_step / remote_command sind
            # wir oben schon mit return abgewichen.
            if self._proposal_aggregator and result.plugin_candidate:
                await self._invoke_proposal_aggregator(msg, result.plugin_candidate)

        except asyncio.TimeoutError:
            logger.error("Timeout bei LLM-Verarbeitung (120s)")
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Zeitüberschreitung bei der Verarbeitung. Bitte erneut versuchen.",
                )
            except Exception:
                # Best-effort: Timeout-Notification darf den Outer-Handler nicht crashen.
                pass
        except Exception as e:
            logger.error(
                "Fehler bei Nachrichtenverarbeitung: %s",
                e,
                extra={"sender": msg.sender, "handler": "llm"},
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Fehler bei der Verarbeitung: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")
        finally:
            if tmp_wav and tmp_wav.exists():
                tmp_wav.unlink(missing_ok=True)

    async def _invoke_proposal_aggregator(
        self,
        msg: IncomingMessage,
        candidate: dict[str, Any],
    ) -> None:
        """Reicht einen <plugin-candidate>-Block an den Aggregator weiter.

        Defensiv: Fehler im Aggregator-Pfad duerfen den Hauptflow nicht
        crashen (Konzept §3.5 -- Vorschlaegse sind ein Nebenprodukt).
        """
        assert self._proposal_aggregator is not None  # caller-side checked
        try:
            await self._proposal_aggregator.record(
                intent=str(candidate.get("intent", "")),
                title=str(candidate.get("title", "")),
                description=str(candidate.get("description", "")),
                sample=msg.body,
                sender=msg.sender,
                confidence=float(candidate.get("confidence", 0.0)),
                category=candidate.get("category"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ProposalAggregator: record() fehlgeschlagen fuer %r: %s",
                candidate.get("intent"),
                exc,
            )
