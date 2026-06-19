"""BridgeMessageHandler-Mixin: ConversationList-Register + list_pick (Phase 106).

Phase 106 (Modul-Entflechtung): aus ``message_handlers.py`` ausgelagert
(Phase-80-Block, erster Teil). ``self`` ist mit ``BridgeMessageHandler``
typisiert (Vererbung), damit Cross-Block-Zugriffe auflösen.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from elder_berry.comms.handlers._bridge_base import BridgeHandlerBase
from elder_berry.comms.pending_initiative import PendingInitiative

if TYPE_CHECKING:
    from elder_berry.comms.commands.base import CommandResult
    from elder_berry.comms.message_channel import IncomingMessage
    from elder_berry.core.assistant import AssistantResult

logger = logging.getLogger(__name__)


class ListPickMixin(BridgeHandlerBase):
    """ConversationListStore-Registrierung + list_pick-Auflösung + Vorschläge."""

    def _maybe_register_command_list(
        self,
        msg: IncomingMessage,
        result: CommandResult,
    ) -> None:
        """Registriert ``result.list_items`` im ConversationListStore.

        Aufgerufen aus ``handle_remote_command`` als Side-Effekt nach
        erfolgreichem Command. Gates:
        - Store ist verdrahtet (None heisst Phase 80 nicht aktiv)
        - Command war erfolgreich (kein Sinn, Fehler-Listen zu speichern)
        - list_items + list_type sind beide gesetzt

        Fehler beim Registrieren werden geloggt, aber nicht propagiert --
        der User-sichtbare Output muss auch bei Store-Crash funktionieren.
        """
        if self._conversation_lists is None:
            return
        if not result.success:
            return
        if not result.list_items or not result.list_type:
            return
        try:
            list_ref = self._conversation_lists.register(
                user_id=msg.sender,
                list_type=result.list_type,
                items=result.list_items,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ConversationListStore.register fehlgeschlagen "
                "(command=%s, type=%s): %s",
                result.command,
                result.list_type,
                exc,
            )
            return
        logger.debug(
            "ConversationListStore: %s registriert (n=%d, ref=%s)",
            result.list_type,
            len(result.list_items),
            list_ref,
        )

    async def _handle_list_pick(
        self,
        msg: IncomingMessage,
        llm_result: AssistantResult,
    ) -> None:
        """LLM hat list_pick gewaehlt -> Listen-Eintrag aufloesen + Folge-Action.

        Konzept §3.4: Der LLM zeigt nur auf einen Index ('Treffer 2'),
        wir loesen ihn aus dem ConversationListStore auf. Verhindert
        URL-Halluzinationen (Live-Befund Phase 78).

        Erwartete Params: ``{"list_type": "search", "index": 2}`` (1-basiert).
        Folge-Action je list_type (Etappe 2: nur ``search``):
        - search -> ``web_summary`` mit der echten URL
        """
        if llm_result.response:
            self._chat_history.add(msg.sender, "assistant", llm_result.response)
            await self._channel.send_text(msg.room_id, llm_result.response)

        await self._audio.send_audio_if_available(msg.room_id, llm_result, None)

        params = llm_result.action_params or {}
        list_type = str(params.get("list_type", "")).strip()
        index_raw = params.get("index")

        # Param-Validierung
        if not list_type:
            logger.warning("list_pick ohne list_type: %r", params)
            await self._channel.send_text(
                msg.room_id,
                "list_pick: list_type fehlt. Sag mir noch, ob du eine "
                "Suche, Mail oder Notiz meinst.",
            )
            return
        try:
            index = int(index_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            logger.warning("list_pick mit ungueltigem index: %r", index_raw)
            await self._channel.send_text(
                msg.room_id,
                "list_pick: index muss eine Zahl sein.",
            )
            return

        if self._conversation_lists is None:
            logger.warning(
                "list_pick erhalten, aber kein ConversationListStore verdrahtet"
            )
            await self._channel.send_text(
                msg.room_id,
                "Listen-Picker ist gerade nicht verfuegbar. Sag mir die URL "
                "direkt oder mach eine neue Suche.",
            )
            return

        active = self._conversation_lists.get_active(msg.sender, list_type)
        if active is None:
            await self._channel.send_text(
                msg.room_id,
                f"Keine aktive Liste vom Typ '{list_type}' (oder schon "
                "abgelaufen). Mach eine neue Suche, dann sag mir die "
                "Treffer-Nummer.",
            )
            return

        list_ref, _items = active
        # get_item ist 1-basiert, validiert Out-of-Range mit None
        # (Etappe-1-Journal-Hinweis: kein idx-1 hier).
        item = self._conversation_lists.get_item(msg.sender, list_ref, index)
        if item is None:
            await self._channel.send_text(
                msg.room_id,
                f"Treffer {index} gibt es nicht in der aktuellen Liste "
                f"(Typ '{list_type}'). Schau nochmal nach.",
            )
            return

        # Folge-Action je list_type
        if list_type == "search":
            await self._dispatch_search_pick(msg, item)
            return
        if list_type == "mail_inbox":
            await self._dispatch_mail_pick(msg, item)
            return
        if list_type == "note_search":
            await self._dispatch_note_pick(msg, item)
            return
        if list_type in ("route_contact_pick", "route_poi_pick"):
            await self._dispatch_route_pick(msg, list_type, item)
            return
        if list_type == "nearby_place_pick":
            await self._dispatch_nearby_pick(msg, item)
            return

        # Unbekannter list_type (z.B. zukuenftige Phase-80.x-Typen wie
        # 'termine'): klar zurueckmelden statt zu raten.
        logger.warning(
            "list_pick fuer list_type '%s' noch nicht verkabelt",
            list_type,
        )
        await self._channel.send_text(
            msg.room_id,
            f"Listen-Typ '{list_type}' ist noch nicht verkabelt.",
        )

    async def _handle_propose_action(
        self,
        msg: IncomingMessage,
        llm_result: AssistantResult,
        tmp_wav: Path | None,
        prefix: str = "",
    ) -> None:
        """Phase 89 (Pfad C): Saleria schlaegt eine Aktion vor.

        Der vorgeschlagene Command wird NICHT sofort ausgefuehrt. Die Frage
        wird gesendet und als ``PendingInitiative`` abgelegt; die naechste
        kurze Bestaetigung des Users loest die Ausfuehrung deterministisch
        ueber den Bridge-Intercept aus (kein LLM-Interpretations-Risiko).

        Args:
            msg: Eingehende Nachricht (fuer sender/room_id).
            llm_result: Assistant-Ergebnis mit ``action_params``
                (``proposed_command``, ``question``) und ``response``.
            tmp_wav: Optionaler TTS-Ziel-Pfad (Audio-Ausgabe wie im Caller).
            prefix: Vorangestellter Command-Output (Mail-Enrichment-Pfad);
                leer im Standard-LLM-Pfad.
        """
        # Defensive: bei LLM-Drift kann action_params kein dict sein
        # (String/Liste). Dann als ungueltigen Vorschlag behandeln, statt
        # mit .get() den Message-Flow zu craschen (analog action_sequence).
        raw_params = llm_result.action_params
        params = raw_params if isinstance(raw_params, dict) else {}
        proposed = str(params.get("proposed_command", "")).strip()
        question = str(params.get("question", "")).strip()

        # Frage senden + in History (nur die LLM-Antwort, nicht der Prefix --
        # konsistent mit dem bestehenden Enrichment-Verhalten).
        if llm_result.response:
            self._chat_history.add(msg.sender, "assistant", llm_result.response)
            sent = (
                f"{prefix}\n\n{llm_result.response}" if prefix else llm_result.response
            )
            await self._channel.send_text(msg.room_id, sent)
        elif prefix:
            await self._channel.send_text(msg.room_id, prefix)

        await self._audio.send_audio_if_available(msg.room_id, llm_result, tmp_wav)

        # Ohne konkreten Folge-Command bleibt es bei der Frage -- nichts ablegen.
        if not proposed:
            logger.warning(
                "propose_action ohne proposed_command (sender=%s) -- nur Frage gesendet",
                msg.sender,
            )
            return

        self._pending_initiative.set(
            msg.sender,
            PendingInitiative(
                proposed_command=proposed,
                question=question or (llm_result.response or ""),
            ),
        )
        logger.info(
            "Initiativ-Vorschlag abgelegt fuer %s: %r",
            msg.sender,
            proposed,
        )

    async def _dispatch_search_pick(
        self,
        msg: IncomingMessage,
        item: dict[str, Any],
    ) -> None:
        """Web-Summary-Dispatch fuer einen aufgeloesten Such-Treffer.

        Baut den ``fasse <url> zusammen``-Command und delegiert an
        ``handle_remote_command``. Falls die Item-Form mal driftet
        (kein url-Feld), liefern wir eine klare Fehlermeldung statt
        zu craschen.
        """
        url = str(item.get("url", "")).strip()
        if not url:
            logger.warning("list_pick search-Item ohne url: %r", item)
            await self._channel.send_text(
                msg.room_id,
                "Der gewählte Treffer hat keine URL -- such nochmal.",
            )
            return
        if self._remote_commands is None:
            await self._channel.send_text(
                msg.room_id,
                f"Treffer-URL: {url}\n(Web-Zusammenfassung gerade nicht verfuegbar.)",
            )
            return

        from elder_berry.comms.message_channel import IncomingMessage as IM

        command_text = f"fasse {url} zusammen"
        parsed = self._remote_commands.parse_command(command_text)
        if not parsed:
            logger.error(
                "list_pick: web_summary-Command konnte nicht geparst werden: %r",
                command_text,
            )
            await self._channel.send_text(
                msg.room_id,
                f"Treffer-URL: {url}\n(Konnte sie aber nicht zur "
                "Zusammenfassung weiterreichen.)",
            )
            return

        cmd_msg = IM(
            sender=msg.sender,
            room_id=msg.room_id,
            body=command_text,
            timestamp=msg.timestamp,
        )
        # Rekursions-Guard wie bei _handle_llm_remote_command -- der
        # Folge-Command darf bei Fehlschlag NICHT zurueck ans LLM eskalieren
        # (das ist ein User-getriebener Pfad, kein LLM-Halluzinations-Pfad).
        self._in_llm_command.add(msg.sender)
        try:
            await self.handle_remote_command(cmd_msg, parsed)
        finally:
            self._in_llm_command.discard(msg.sender)
