"""Basis für die Assistant-Mixins (Phase 106).

Deklariert die per Konstruktor gesetzten Felder, die von mehr als einem Mixin
gelesen werden, für den Type-Checker. Hat keinen eigenen ``__init__`` –
``Assistant.__init__`` setzt die Felder. Reines State-Contract-Stub.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.actions.db import ActionsDB
    from elder_berry.agent.client import AgentClient
    from elder_berry.avatar.base import AvatarRenderer
    from elder_berry.character.base import CharacterEngine
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.core.audio_analyzer import AudioAnalyzer
    from elder_berry.robot.client import RobotClient
    from elder_berry.tools.proposal_store import ProposalStore
    from elder_berry.tts.base import TTSEngine


class AssistantMixinBase:
    """Gemeinsamer State-Contract der Assistant-Mixins (kein __init__)."""

    _actions_db: ActionsDB
    _character: CharacterEngine | None
    _remote_commands: RemoteCommandHandler | None
    _proposal_store: ProposalStore | None
    _robot: RobotClient | None
    _robot_battery_enabled: bool
    _agent: AgentClient | None
    _agent_online_cache: bool | None
    _tts: TTSEngine | None
    _avatar: AvatarRenderer | None
    _audio_analyzer: AudioAnalyzer
