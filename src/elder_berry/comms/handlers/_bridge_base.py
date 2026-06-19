"""Basis für die BridgeMessageHandler-Mixins (Phase 106).

Die Mixins bilden zusammen mit dem Shell ``BridgeMessageHandler`` eine Klasse,
rufen sich aber dicht und bidirektional gegenseitig (und Shell-Methoden) auf.
Damit der Type-Checker das ohne ``self``-Tricks auflöst, deklariert diese Basis
- den geteilten Instanz-State (``self._*``, gesetzt in ``__init__``) und
- die Signaturen der block-übergreifend aufgerufenen Methoden (Stubs).

Die echten Implementierungen liegen in den Mixins bzw. im Shell und überschreiben
die Stubs via MRO; die ``...``-Körper hier laufen nie. Kein Runtime-Verhalten.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from elder_berry.comms.action_sequence import StepOutcome
    from elder_berry.comms.audio_pipeline import AudioPipeline
    from elder_berry.comms.chat_history import ChatHistory
    from elder_berry.comms.claude_agent import ClaudeAgent
    from elder_berry.comms.commands.base import CommandResult
    from elder_berry.comms.confirmation_handlers import ConfirmationHandler
    from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
    from elder_berry.comms.pending_confirmation import PendingConfirmationStore
    from elder_berry.comms.pending_initiative import PendingInitiativeStore
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.comms.scheduler_manager import SchedulerManager
    from elder_berry.core.assistant import Assistant, AssistantResult
    from elder_berry.core.task_chain import TaskChainRunner
    from elder_berry.tools.conversation_list_store import ConversationListStore
    from elder_berry.tools.email_client import IMAPEmailClient
    from elder_berry.tools.email_sender import EmailSender
    from elder_berry.tools.intent_aggregator import ProposalIntentAggregator
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient


class BridgeHandlerBase:
    """Geteilter State-/Methoden-Contract der BridgeMessageHandler-Mixins."""

    # --- Instanz-State (gesetzt in BridgeMessageHandler.__init__) ---
    _channel: MessageChannel
    _assistant: Assistant
    _audio: AudioPipeline
    _chat_history: ChatHistory
    _pending: PendingConfirmationStore
    _pending_initiative: PendingInitiativeStore
    _remote_commands: RemoteCommandHandler | None
    _claude_agent: ClaudeAgent | None
    _task_chain: TaskChainRunner | None
    _email_sender: EmailSender | None
    _email_client: IMAPEmailClient | None
    _nc_files: NextcloudFilesClient | None
    _proposal_aggregator: ProposalIntentAggregator | None
    _conversation_lists: ConversationListStore | None
    restart_cooldown_until: float
    _scheduler_mgr: SchedulerManager | None
    _in_llm_command: set[str]
    _confirm: ConfirmationHandler

    # --- Block-übergreifend aufgerufene Methoden (Implementierung anderswo) ---
    async def handle_remote_command(
        self, msg: IncomingMessage, command: str
    ) -> None: ...

    async def _apply_command_side_effects(
        self, msg: IncomingMessage, result: CommandResult
    ) -> None: ...

    def _maybe_register_command_list(
        self, msg: IncomingMessage, result: CommandResult
    ) -> None: ...

    async def _handle_llm_enrichment(
        self,
        msg: IncomingMessage,
        result: CommandResult,
        prompt_intro: str,
        prompt_instruction: str,
        error_log_msg: str,
        error_fallback_suffix: str,
    ) -> None: ...

    async def _handle_propose_action(
        self,
        msg: IncomingMessage,
        llm_result: AssistantResult,
        tmp_wav: Path | None,
        prefix: str = "",
    ) -> None: ...

    async def _dispatch_mail_pick(
        self, msg: IncomingMessage, item: dict[str, Any]
    ) -> None: ...

    async def _dispatch_note_pick(
        self, msg: IncomingMessage, item: dict[str, Any]
    ) -> None: ...

    async def _dispatch_route_pick(
        self, msg: IncomingMessage, list_type: str, item: dict[str, Any]
    ) -> None: ...

    async def _dispatch_nearby_pick(
        self, msg: IncomingMessage, item: dict[str, Any]
    ) -> None: ...

    def _try_parse_multi_line(
        self, command_text: str
    ) -> list[tuple[str, str]] | None: ...

    async def _execute_multi_line_commands(
        self, msg: IncomingMessage, parsed_lines: list[tuple[str, str]]
    ) -> None: ...

    async def _retry_llm_remote_command(
        self, msg: IncomingMessage, failed_command: str
    ) -> str | None: ...

    async def _propose_plugin_for_failed_command(
        self, msg: IncomingMessage, command_text: str
    ) -> bool:
        raise NotImplementedError

    async def _execute_sub_command(
        self, index: int, command_text: str, msg: IncomingMessage
    ) -> StepOutcome:
        raise NotImplementedError
