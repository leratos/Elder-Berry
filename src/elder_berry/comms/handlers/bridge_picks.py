"""BridgeMessageHandler-Mixin: Pick-Dispatch + Standort + Nearby (Phase 106).

Phase 106 (Modul-Entflechtung): aus ``message_handlers.py`` ausgelagert
(Phase-80-Block, zweiter Teil + Phase-97-Standort). ``self`` ist mit
``BridgeMessageHandler`` typisiert (Vererbung), damit Cross-Block-Zugriffe
auflösen.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from elder_berry.comms.commands.mail_commands import MAIL_ID_PATTERN
from elder_berry.comms.handlers._bridge_base import BridgeHandlerBase

if TYPE_CHECKING:
    from elder_berry.comms.message_channel import IncomingMessage

logger = logging.getLogger(__name__)


class PickDispatchMixin(BridgeHandlerBase):
    """Mail-Reroute, Nearby-Folge-Turn, Standort + Pick-Dispatcher (mail/route/..)."""

    async def _maybe_reroute_mail_to_list_pick(
        self,
        msg: IncomingMessage,
    ) -> bool:
        """Reroute "mail N" auf den N-ten Eintrag der aktiven mail_inbox-Liste.

        Hintergrund: ``MAIL_ID_PATTERN`` matcht "lies Mail 3" /  "Mail 3"
        direkt in der Bridge-Vorpruefung -- der LLM-list_pick-Pfad waere nie
        erreicht und "3" wuerde als IMAP-UID interpretiert. Diese Heuristik
        gibt einer aktiven Inbox-Liste Vorrang, solange N im Listen-Range
        liegt. Bei N > len(items) bleibt der echte UID-Lookup erhalten.

        Returns:
            True wenn rerouted (Caller soll early-returnen), sonst False.
        """
        # Caller filtert self._conversation_lists is not None.
        assert self._conversation_lists is not None

        match = MAIL_ID_PATTERN.match(msg.body.strip().lower())
        if not match:
            return False
        try:
            n = int(match.group(1))
        except (TypeError, ValueError):
            return False
        if n < 1:
            return False

        active = self._conversation_lists.get_active(msg.sender, "mail_inbox")
        if active is None:
            return False
        list_ref, items = active
        if n > len(items):
            # User meint vermutlich eine echte UID jenseits der aktuellen
            # Inbox-Liste -- regulaerer mail_by_id-Pfad uebernimmt.
            return False

        item = self._conversation_lists.get_item(msg.sender, list_ref, n)
        if item is None:
            return False

        logger.info(
            "mail_by_id rerouted zu list_pick (n=%d, msg_id=%s) -- "
            "aktive mail_inbox-Liste hat Vorrang vor UID-Lookup",
            n,
            item.get("msg_id"),
        )
        await self._dispatch_mail_pick(msg, item)
        return True

    async def _maybe_continue_nearby_draft(
        self, msg: IncomingMessage
    ) -> bool:
        """Phase 97: Folge-Turn der Umkreissuche (Early-Intercept).

        Liegt ein offener Nearby-Draft (Key = default_user_id im Handler),
        wird ``msg.body`` als Antwort auf die Rueckfrage gedeutet. Der Handler
        entscheidet selbst, ob die Antwort passt (sonst ``fallthrough`` ->
        normaler LLM-Flow, der Draft bleibt erhalten).

        Returns:
            True wenn die Antwort verarbeitet wurde (Caller returnt early).
        """
        if self._remote_commands is None:
            return False
        handler = self._remote_commands.get_handler("nearby_place")
        if handler is None:
            return False
        has_pending = getattr(handler, "has_pending_draft", None)
        continue_with = getattr(handler, "continue_with_answer", None)
        if not callable(has_pending) or not callable(continue_with):
            return False
        if not has_pending():
            return False

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, continue_with, msg.body)
        except Exception as exc:  # noqa: BLE001
            logger.error("Nearby continue_with_answer crashed: %s", exc)
            return False

        if result.fallthrough:
            # Antwort passte nicht (z.B. unrelated) -> normaler LLM-Flow.
            return False
        if result.text:
            await self._channel.send_text(msg.room_id, result.text)
        # Folge-Liste (Pick) registrieren, damit "Treffer N" funktioniert.
        self._maybe_register_command_list(msg, result)
        if result.success and result.text:
            history = result.history_text or result.text
            self._chat_history.add(msg.sender, "user", msg.body)
            self._chat_history.add(msg.sender, "assistant", history)
        return True

    async def handle_location_message(
        self, msg: IncomingMessage
    ) -> None:
        """Phase 97 E5: Matrix-Standort-Share (m.location) verarbeiten.

        Liegt ein offener Nearby-Draft, fuellen die Koordinaten den
        Standort (``continue_with_location``) -- der Geocode-Call entfaellt.
        Ohne offenen Draft gibt es einen kurzen Hinweis (Lera-Entscheidung
        E5: kein TTL-Vormerken, Freitext+Geocoding bleibt der Normalweg).
        """
        location = msg.location
        if location is None:
            logger.warning("handle_location_message ohne location -- ignoriert")
            return

        no_search_hint = (
            "Ich habe deinen Standort bekommen -- gerade läuft aber keine "
            "Ortssuche. Frag mich z.B. 'Wo ist die nächste Apotheke?' und "
            "teil ihn dann nochmal."
        )

        handler = None
        if self._remote_commands is not None:
            handler = self._remote_commands.get_handler("nearby_place")
        has_pending = getattr(handler, "has_pending_draft", None)
        continue_with = getattr(handler, "continue_with_location", None)
        if not callable(has_pending) or not callable(continue_with):
            await self._channel.send_text(msg.room_id, no_search_hint)
            return
        if not has_pending():
            await self._channel.send_text(msg.room_id, no_search_hint)
            return

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, continue_with, location.lat, location.lng
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Nearby continue_with_location crashed: %s", exc)
            await self._channel.send_text(
                msg.room_id,
                "Dein Standort kam an, aber die Ortssuche hat gerade ein "
                "Problem. Versuch es nochmal oder nenn mir den Ort als Text.",
            )
            return

        if result.fallthrough:
            # Draft zwischen has_pending() und Aufruf verschwunden (TTL).
            await self._channel.send_text(msg.room_id, no_search_hint)
            return
        if result.text:
            await self._channel.send_text(msg.room_id, result.text)
        # Folge-Liste (Pick) registrieren, damit "Treffer N" funktioniert.
        self._maybe_register_command_list(msg, result)
        if result.success and result.text:
            history = result.history_text or result.text
            self._chat_history.add(msg.sender, "user", "[Standort geteilt]")
            self._chat_history.add(msg.sender, "assistant", history)

    async def _dispatch_mail_pick(
        self,
        msg: IncomingMessage,
        item: dict[str, Any],
    ) -> None:
        """Mail-Show-Dispatch fuer einen aufgeloesten Mail-Inbox-Treffer.

        Baut ``mail #<msg_id>`` und delegiert an ``handle_remote_command``.
        Dort matcht ``MAIL_ID_PATTERN`` -> ``mail_by_id`` -> Mail-Body geht
        ueber ``_handle_mail_summary`` ans LLM (bestehende Pipeline aus
        Phase 28+).
        """
        msg_id = str(item.get("msg_id", "")).strip()
        if not msg_id:
            logger.warning("list_pick mail-Item ohne msg_id: %r", item)
            await self._channel.send_text(
                msg.room_id,
                "Die gewählte Mail hat keine ID -- ruf die Inbox nochmal ab.",
            )
            return
        if self._remote_commands is None:
            await self._channel.send_text(
                msg.room_id,
                f"Mail #{msg_id} kann gerade nicht abgerufen werden "
                "(Remote-Commands inaktiv).",
            )
            return

        from elder_berry.comms.message_channel import IncomingMessage as IM

        command_text = f"mail #{msg_id}"
        parsed = self._remote_commands.parse_command(command_text)
        if not parsed:
            logger.error(
                "list_pick: mail_by_id-Command konnte nicht geparst werden: %r",
                command_text,
            )
            await self._channel.send_text(
                msg.room_id,
                f"Mail #{msg_id} (konnte sie aber nicht zur Anzeige weiterreichen).",
            )
            return

        cmd_msg = IM(
            sender=msg.sender,
            room_id=msg.room_id,
            body=command_text,
            timestamp=msg.timestamp,
        )
        self._in_llm_command.add(msg.sender)
        try:
            await self.handle_remote_command(cmd_msg, parsed)
        finally:
            self._in_llm_command.discard(msg.sender)

    async def _dispatch_route_pick(
        self,
        msg: IncomingMessage,
        list_type: str,
        item: dict[str, Any],
    ) -> None:
        """Phase 92: Route-Disambig-Pick (Kontakt oder POI).

        Anders als search/mail/note: der Multi-Stop-Pfad ist mehrstufig.
        Wir reichen das Item direkt an den MultiStopRouteCommandHandler
        weiter; sein ``continue_with_pick`` liefert das naechste
        CommandResult (entweder neue Liste fuer den naechsten Pick oder
        die finale Route). Eine Folge-Liste registrieren wir hier wieder
        wie ein normales Command-Resultat, damit der user den naechsten
        Treffer per "Treffer N" auswaehlen kann.
        """
        if self._remote_commands is None:
            await self._channel.send_text(
                msg.room_id,
                "Multi-Stop-Routing ist gerade nicht verfuegbar.",
            )
            return
        handler = self._remote_commands.get_handler("multi_stop_route")
        if handler is None:
            await self._channel.send_text(
                msg.room_id,
                "Multi-Stop-Routenplanung ist nicht konfiguriert.",
            )
            return
        # Direktaufruf der Public-Methode -- die laeuft synchron mit
        # SQLite + httpx, daher in den Executor. Der Handler nutzt
        # intern seine eigene default_user_id als Session-Key (Codex-
        # Review-Finding 2026-05-20: Turn 1 schreibt unter
        # self._user_id, also muss Turn N auch dort lesen -- msg.sender
        # darf NICHT als Session-Key dienen, sonst bricht Disambig wenn
        # default_user_id != msg.sender).
        loop = asyncio.get_running_loop()
        try:
            continue_method = handler.continue_with_pick  # type: ignore[attr-defined]
            result = await loop.run_in_executor(
                None,
                continue_method,
                list_type,
                item,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Multi-Stop continue_with_pick crashed: %s", exc)
            await self._channel.send_text(
                msg.room_id,
                f"Fehler bei Routenplanung: {type(exc).__name__}",
            )
            return

        if result.text:
            await self._channel.send_text(msg.room_id, result.text)
        # Folge-Liste registrieren (z.B. naechste contact_pick oder
        # poi_pick), damit der naechste Pick wieder via list_pick laeuft.
        self._maybe_register_command_list(msg, result)
        if result.success and result.text:
            history = result.history_text or result.text
            self._chat_history.add(msg.sender, "user", msg.body)
            self._chat_history.add(msg.sender, "assistant", history)

    async def _dispatch_nearby_pick(
        self,
        msg: IncomingMessage,
        item: dict[str, Any],
    ) -> None:
        """Phase 97: Nearby-Pick -> Google-Maps-Place-Link (terminal).

        Anders als route_*_pick einstufig: das Item traegt name + place_id,
        der Link wird direkt gebaut (kein Folge-Command). Maps routet ab
        'Dein Standort', daher Place-Link statt Route (Konzept §5).
        """
        name = str(item.get("name", "")).strip()
        place_id = str(item.get("place_id", "")).strip()
        if not name or not place_id:
            logger.warning("nearby_place_pick-Item ohne name/place_id: %r", item)
            await self._channel.send_text(
                msg.room_id,
                "Der gewählte Ort hat keine gültige ID mehr. "
                "Mach nochmal eine Suche.",
            )
            return
        from elder_berry.tools.maps_link_builder import MapsLinkBuilder

        try:
            link = MapsLinkBuilder().build_place_link(name, place_id)
        except ValueError as exc:
            logger.warning("nearby build_place_link: %s", exc)
            await self._channel.send_text(
                msg.room_id,
                "Konnte keinen Karten-Link bauen.",
            )
            return
        text = f"{name}:\n-> {link}"
        await self._channel.send_text(msg.room_id, text)
        self._chat_history.add(msg.sender, "user", msg.body)
        self._chat_history.add(msg.sender, "assistant", text)

    async def _dispatch_note_pick(
        self,
        msg: IncomingMessage,
        item: dict[str, Any],
    ) -> None:
        """Notiz-Show-Dispatch fuer einen aufgeloesten note_search-Treffer.

        Anders als search/mail_inbox kein Round-Trip durch ein Folge-Command:
        Notizen sind klein und der volle Content liegt schon im Item, also
        formatieren wir direkt aus den Item-Feldern. Spart einen
        ``note_show``-Command, der sonst nur fuer den Pick existieren wuerde.
        """
        note_id = item.get("id")
        key = item.get("key")
        content = str(item.get("content", "")).strip()
        if not content:
            logger.warning("list_pick note-Item ohne content: %r", item)
            await self._channel.send_text(
                msg.room_id,
                "Die gewaehlte Notiz hat keinen Inhalt -- such nochmal.",
            )
            return

        if key:
            text = f"\U0001f511 Notiz #{note_id} -- {key}: {content}"
        else:
            text = f"\U0001f4dd Notiz #{note_id}: {content}"
        await self._channel.send_text(msg.room_id, text)
        # Damit das LLM beim naechsten Turn weiss, welche Notiz angezeigt wurde
        self._chat_history.add(msg.sender, "assistant", text)
