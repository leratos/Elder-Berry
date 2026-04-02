"""BridgeMessageHandler – Nachrichtenverarbeitung für die MatrixBridge.

Kapselt alle Handler-Methoden die von der Bridge an verschiedene
Subsysteme delegieren:
- Remote Commands (direkte Befehle ohne LLM)
- Claude Agent (komplexe Anfragen via Claude API)
- LLM Enrichment (Dokument-/Mail-Zusammenfassungen)
- Assistant Messages (Standard-LLM-Flow)
- Multi-Step Tasks (TaskChainRunner)
- Pending Confirmations (Email-Reply Draft → Bestätigung → Senden)
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.pending_confirmation import PendingAction

if TYPE_CHECKING:
    from elder_berry.comms.audio_pipeline import AudioPipeline
    from elder_berry.comms.chat_history import ChatHistory
    from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
    from elder_berry.comms.pending_confirmation import PendingConfirmationStore
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.comms.restart_manager import perform_restart
    from elder_berry.comms.scheduler_manager import SchedulerManager
    from elder_berry.core.assistant import Assistant
    from elder_berry.core.task_chain import TaskChainRunner
    from elder_berry.comms.claude_agent import ClaudeAgent
    from elder_berry.tools.email_sender import EmailSender
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient

logger = logging.getLogger(__name__)


class BridgeMessageHandler:
    """Verarbeitet eingehende Nachrichten für die MatrixBridge.

    Wird von MatrixBridge erstellt und erhält alle nötigen Dependencies
    über den Konstruktor. Enthält die gesamte Handler-Logik für:
    - Remote Commands, Claude Agent, LLM-Anreicherung
    - Standard-LLM-Flow, Multi-Step, Pending Confirmations
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
        nextcloud_files: NextcloudFilesClient | None = None,
    ) -> None:
        self._channel = channel
        self._assistant = assistant
        self._audio = audio_pipeline
        self._chat_history = chat_history
        self._pending = pending
        self._remote_commands = remote_commands
        self._claude_agent = claude_agent
        self._task_chain = task_chain
        self._email_sender = email_sender
        self._nc_files = nextcloud_files
        # Mutable State (gesetzt von Bridge)
        self.restart_cooldown_until: float = 0.0
        self._scheduler_mgr: SchedulerManager | None = None
        # Guard gegen Endlosrekursion: LLM → remote_command → fallthrough → LLM → ...
        self._in_llm_command: set[str] = set()

    # ------------------------------------------------------------------
    # Remote Commands
    # ------------------------------------------------------------------

    # Commands die länger brauchen (Netzwerk-Sync, Updates etc.)
    _LONG_RUNNING_COMMANDS = {
        "contact_sync", "system_update", "git_pull",
    }

    async def handle_remote_command(
        self, msg: IncomingMessage, command: str,
    ) -> None:
        """Führt einen direkten Remote-Command aus und sendet das Ergebnis."""
        logger.info("Remote-Command erkannt: %s", command)
        timeout = 300.0 if command in self._LONG_RUNNING_COMMANDS else 60.0

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._remote_commands.execute, command, msg.body,
                ),
                timeout=timeout,
            )

            # Fallthrough: Command erkannt aber nichts gefunden → LLM
            # ABER: nicht wenn wir bereits aus einem LLM-initiierten Command
            # kommen (verhindert Endlosrekursion LLM→Command→fallthrough→LLM)
            if result.fallthrough:
                if msg.sender in self._in_llm_command:
                    logger.warning(
                        "Fallthrough '%s' blockiert (LLM-initiiert, "
                        "Rekursions-Guard)", command,
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
                pending_action = PendingAction(
                    action_type=result.command,
                    description=result.text or "",
                    data=result.pending_data,
                )
                self._pending.set(msg.sender, pending_action)
                if result.text:
                    await self._channel.send_text(msg.room_id, result.text)
                self._chat_history.add(msg.sender, "user", msg.body)
                self._chat_history.add(
                    msg.sender, "assistant", result.text or "",
                )
                return

            # Text-Antwort senden
            if result.text:
                await self._channel.send_text(msg.room_id, result.text)

            # Command-Ergebnis in Chat-History speichern
            if result.success and result.text:
                history_content = result.history_text or result.text
                self._chat_history.add(msg.sender, "user", msg.body)
                self._chat_history.add(msg.sender, "assistant", history_content)

            # Fehlgeschlagene Commands loggen
            if not result.success:
                logger.error(
                    "Command '%s' fehlgeschlagen: %s",
                    command, result.text or "Command fehlgeschlagen",
                    extra={"sender": msg.sender, "handler": f"command:{command}"},
                )

            # Bild senden (Screenshot): direkt per Matrix (Inline-Preview)
            if result.image_path and result.image_path.exists():
                try:
                    await self._channel.send_image(
                        msg.room_id, result.image_path,
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
                    msg.room_id, result.file_path,
                )

            # Mehrere Dateien senden (z.B. Mail-Anhänge)
            for fpath in (result.file_paths or []):
                if fpath.exists():
                    await self._send_file_via_nc_or_matrix(
                        msg.room_id, fpath, cleanup=True,
                    )

            # Restart
            if result.restart:
                if time.monotonic() < self.restart_cooldown_until:
                    logger.warning(
                        "Restart-Cooldown aktiv, ignoriere restart-Befehl "
                        "(noch %.0fs)",
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
                    self._channel, self._scheduler_mgr,
                    msg.room_id, msg_server_ts=msg.timestamp,
                )

        except asyncio.TimeoutError:
            logger.error("Timeout bei Remote-Command '%s' (%.0fs)", command, timeout)
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Zeitüberschreitung bei der Command-Ausführung.",
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(
                "Remote-Command '%s' fehlgeschlagen: %s", command, e,
                extra={"sender": msg.sender, "handler": "command"},
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Command-Fehler: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")

    # ------------------------------------------------------------------
    # Pending Confirmation (Phase 28)
    # ------------------------------------------------------------------

    async def handle_pending_confirm(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Führt eine bestätigte PendingAction aus."""
        if action.action_type in ("mail_reply", "mail_reply_modify"):
            await self._execute_mail_send(msg, action)
        elif action.action_type == "nextcloud_setup":
            await self._execute_nextcloud_setup(msg, action)
        elif action.action_type in ("update", "update_all"):
            await self._execute_restart_confirm(msg, action)
        else:
            logger.warning("Unbekannter PendingAction-Typ: %s", action.action_type)
            await self._channel.send_text(
                msg.room_id, f"Unbekannte Aktion: {action.action_type}",
            )
            self._pending.clear(msg.sender)

    async def _execute_mail_send(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Sendet eine bestätigte Email-Antwort via SMTP."""
        if not self._email_sender:
            await self._channel.send_text(
                msg.room_id, "SMTP nicht konfiguriert.",
            )
            self._pending.clear(msg.sender)
            return

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._email_sender.send_reply(
                        to=action.data["to"],
                        subject=action.data["subject"],
                        body=action.data["draft_text"],
                        in_reply_to=action.data.get("in_reply_to", ""),
                        references=action.data.get("references", ""),
                    ),
                ),
                timeout=30.0,
            )

            if result.success:
                self._pending.clear(msg.sender)
                await self._channel.send_text(
                    msg.room_id,
                    f"\u2705 Antwort auf #{action.data['msg_id']} gesendet "
                    f"an {result.to}.",
                )
                self._chat_history.add(msg.sender, "user", "ja")
                self._chat_history.add(
                    msg.sender, "assistant",
                    f"Email-Antwort gesendet an {result.to}: "
                    f"{action.data['subject']}",
                )
            else:
                await self._channel.send_text(
                    msg.room_id,
                    f"\u274c Senden fehlgeschlagen: {result.error}\n"
                    f"Versuche es mit 'ja' erneut oder 'nein' zum Verwerfen.",
                )
        except asyncio.TimeoutError:
            logger.error("Timeout beim Email-Senden (30s)")
            await self._channel.send_text(
                msg.room_id,
                "Zeitüberschreitung beim Email-Senden.\n"
                "Versuche es mit 'ja' erneut oder 'nein' zum Verwerfen.",
            )
        except Exception as e:
            logger.error("Email senden fehlgeschlagen: %s", e)
            await self._channel.send_text(
                msg.room_id,
                f"\u274c Fehler beim Senden: {type(e).__name__}",
            )
            self._pending.clear(msg.sender)

    async def _execute_restart_confirm(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Führt einen bestätigten Neustart aus (nach 'update' ohne neue Commits)."""
        self._pending.clear(msg.sender)
        self._chat_history.add(msg.sender, "user", "ja")
        self._chat_history.add(msg.sender, "assistant", "🔄 Neustart bestätigt.")

        if time.monotonic() < self.restart_cooldown_until:
            await self._channel.send_text(
                msg.room_id,
                "Restart-Cooldown aktiv – ich wurde gerade erst "
                "neu gestartet. Bitte warte noch etwas.",
            )
            return

        await self._channel.send_text(msg.room_id, "🔄 Starte neu …")
        from elder_berry.comms.restart_manager import perform_restart
        await perform_restart(
            self._channel, self._scheduler_mgr,
            msg.room_id, msg_server_ts=msg.timestamp,
        )

    async def _execute_nextcloud_setup(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Führt das bestätigte Nextcloud-Setup aus (löschen + Ordner anlegen)."""
        if not self._nc_files:
            await self._channel.send_text(
                msg.room_id, "Nextcloud nicht konfiguriert.",
            )
            self._pending.clear(msg.sender)
            return

        to_delete: list[str] = action.data.get("to_delete", [])
        to_create: list[str] = action.data.get("to_create", [])

        await self._channel.send_text(
            msg.room_id, "Nextcloud-Setup wird ausgeführt …",
        )

        try:
            from elder_berry.tools.nextcloud_files import NextcloudError

            loop = asyncio.get_running_loop()
            deleted: list[str] = []
            created: list[str] = []
            errors: list[str] = []

            # 1. Löschen
            for name in to_delete:
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(
                            None, self._nc_files.delete, name,
                        ),
                        timeout=15.0,
                    )
                    deleted.append(name)
                except NextcloudError as e:
                    errors.append(f"Löschen '{name}': {e}")
                except asyncio.TimeoutError:
                    errors.append(f"Löschen '{name}': Timeout")

            # 2. Ordner anlegen (Parent-first Reihenfolge)
            for path in to_create:
                try:
                    is_new = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, self._nc_files.mkdir, path,
                        ),
                        timeout=10.0,
                    )
                    if is_new:
                        created.append(path)
                except NextcloudError as e:
                    errors.append(f"mkdir '{path}': {e}")
                except asyncio.TimeoutError:
                    errors.append(f"mkdir '{path}': Timeout")

            # Ergebnis
            lines = ["\u2705 Nextcloud-Setup abgeschlossen.\n"]
            if deleted:
                lines.append(f"Gelöscht: {', '.join(deleted)}")
            if created:
                lines.append(f"Erstellt: {len(created)} Ordner")
            if errors:
                lines.append(f"\n\u26a0\ufe0f Fehler ({len(errors)}):")
                for err in errors:
                    lines.append(f"  • {err}")

            self._pending.clear(msg.sender)
            await self._channel.send_text(msg.room_id, "\n".join(lines))

            self._chat_history.add(msg.sender, "user", "ja")
            self._chat_history.add(
                msg.sender, "assistant",
                f"Nextcloud-Setup: {len(deleted)} gelöscht, "
                f"{len(created)} Ordner erstellt",
            )

        except Exception as e:
            logger.error("Nextcloud-Setup fehlgeschlagen: %s", e)
            await self._channel.send_text(
                msg.room_id,
                f"\u274c Nextcloud-Setup fehlgeschlagen: {type(e).__name__}",
            )
            self._pending.clear(msg.sender)

    async def handle_pending_modify(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Generiert einen neuen Draft basierend auf der Änderungsanweisung."""
        if action.action_type not in ("mail_reply", "mail_reply_modify"):
            await self._channel.send_text(
                msg.room_id,
                "Ändern wird für diesen Aktionstyp nicht unterstützt.",
            )
            return

        modify_instruction = action.data.get("modify_instruction", "")
        if not modify_instruction:
            await self._channel.send_text(
                msg.room_id, "Format: ändern: <was soll anders sein>",
            )
            return

        try:
            loop = asyncio.get_running_loop()
            new_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._remote_commands.execute,
                    "mail_reply_modify",
                    f"#{action.data['msg_id']} {modify_instruction}",
                ),
                timeout=120.0,
            )
            if new_result.success and new_result.pending_data:
                new_action = PendingAction(
                    action_type="mail_reply",
                    description=new_result.text or "",
                    data=new_result.pending_data,
                )
                self._pending.set(msg.sender, new_action)
                await self._channel.send_text(
                    msg.room_id, new_result.text,
                )
                self._chat_history.add(msg.sender, "user", msg.body)
                self._chat_history.add(
                    msg.sender, "assistant", new_result.text or "",
                )
            else:
                await self._channel.send_text(
                    msg.room_id,
                    new_result.text or "Draft-Änderung fehlgeschlagen.",
                )
        except asyncio.TimeoutError:
            logger.error("Timeout bei Draft-Änderung (120s)")
            await self._channel.send_text(
                msg.room_id,
                "Zeitüberschreitung bei der Draft-Generierung.",
            )
        except Exception as e:
            logger.error("Draft-Änderung fehlgeschlagen: %s", e)
            await self._channel.send_text(
                msg.room_id,
                f"\u274c Änderung fehlgeschlagen: {type(e).__name__}",
            )

    # ------------------------------------------------------------------
    # Claude Agent
    # ------------------------------------------------------------------

    async def handle_claude_agent(
        self, msg: IncomingMessage, claude_text: str,
    ) -> None:
        """Delegiert an ClaudeAgent.process() für komplexe Anfragen."""
        logger.info("ClaudeAgent verarbeitet: %s", claude_text[:100])

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._claude_agent.process, claude_text,
                ),
                timeout=180.0,
            )

            if result.summary:
                await self._channel.send_text(msg.room_id, result.summary)

            if result.details:
                if result.action_taken == "screenshot" and result.success:
                    image_path = Path(result.details)
                    if image_path.exists():
                        try:
                            await self._channel.send_image(
                                msg.room_id, image_path,
                            )
                        except NotImplementedError:
                            await self._channel.send_text(
                                msg.room_id,
                                "Screenshot aufgenommen, aber Bild-Upload "
                                "nicht unterstützt.",
                            )
                        finally:
                            image_path.unlink(missing_ok=True)
                else:
                    details = result.details
                    if len(details) > 4000:
                        details = details[:4000] + "\n... (gekürzt)"
                    await self._channel.send_text(msg.room_id, details)

        except asyncio.TimeoutError:
            logger.error("Timeout bei ClaudeAgent (180s)")
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Zeitüberschreitung beim Claude-Agent. Bitte erneut versuchen.",
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(
                "ClaudeAgent Fehler: %s", e,
                extra={"sender": msg.sender, "handler": "agent"},
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Agent-Fehler: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")

    # ------------------------------------------------------------------
    # LLM Enrichment (Dokumente, Mails)
    # ------------------------------------------------------------------

    async def _handle_llm_enrichment(
        self, msg: IncomingMessage, result,
        prompt_intro: str, prompt_instruction: str,
        error_log_msg: str, error_fallback_suffix: str,
    ) -> None:
        """Gemeinsame Logik für LLM-basierte Anreicherung."""
        try:
            loop = asyncio.get_running_loop()

            self._chat_history.add(msg.sender, "user", msg.body)
            self._chat_history.add(msg.sender, "assistant", result.history_text)

            summary_prompt = (
                f"{prompt_intro}\n\n"
                f"{result.history_text}\n\n"
                f"{prompt_instruction}"
            )
            chat_context = self._chat_history.format_for_prompt(msg.sender)

            tmp_wav = (
                Path(tempfile.mktemp(suffix=".wav"))
                if self._audio.audio_to_matrix else None
            )
            llm_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._assistant.process, summary_prompt,
                    tmp_wav, chat_context,
                ),
                timeout=120.0,
            )

            if llm_result.response:
                response = f"{result.text}\n\n{llm_result.response}"
                self._chat_history.add(msg.sender, "assistant", llm_result.response)
                await self._channel.send_text(msg.room_id, response)
            else:
                await self._channel.send_text(msg.room_id, result.text)

            await self._audio.send_audio_if_available(
                msg.room_id, llm_result, tmp_wav,
            )

        except Exception as e:
            logger.error(error_log_msg, e)
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"{result.text}\n\n({error_fallback_suffix}: {type(e).__name__})",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")

    # ------------------------------------------------------------------
    # Nextcloud File-Hub
    # ------------------------------------------------------------------

    async def _send_file_via_nc_or_matrix(
        self, room_id: str, file_path: Path, cleanup: bool = False,
    ) -> None:
        """Sendet eine Datei: bevorzugt über Nextcloud (Upload + Share-Link),
        Fallback auf direkten Matrix-Upload.

        Args:
            room_id: Matrix-Room-ID.
            file_path: Lokaler Pfad zur Datei.
            cleanup: Datei nach dem Senden löschen.
        """
        # Versuch: Nextcloud Upload + Share-Link
        if self._nc_files is not None:
            link = await self._upload_to_nc_and_share(file_path)
            if link:
                filename = file_path.name
                await self._channel.send_text(
                    room_id, f"📎 {filename}: {link}",
                )
                if cleanup:
                    file_path.unlink(missing_ok=True)
                return

        # Fallback: direkter Matrix-Upload
        try:
            await self._channel.send_file(room_id, file_path)
        except NotImplementedError:
            await self._channel.send_text(
                room_id, "Datei-Upload nicht unterstützt.",
            )
        finally:
            if cleanup:
                file_path.unlink(missing_ok=True)

    async def _upload_to_nc_and_share(self, file_path: Path) -> str | None:
        """Upload zu Nextcloud + Share-Link erstellen.

        Zielordner: /Saleria/YYYY-MM/<dateiname>

        Returns:
            Share-Link URL oder None bei Fehler.
        """
        from datetime import datetime

        month_folder = datetime.now().strftime("%Y-%m")
        remote_path = f"Saleria/{month_folder}/{file_path.name}"

        loop = asyncio.get_running_loop()
        try:
            # Upload (blockierend → in Executor)
            await loop.run_in_executor(
                None, self._nc_files.upload, file_path, remote_path,
            )
            # Share-Link erstellen
            link = await loop.run_in_executor(
                None, self._nc_files.share_link, remote_path,
            )
            logger.info("NC File-Hub: %s → %s", file_path.name, link)
            return link
        except Exception as exc:
            logger.warning("NC Upload/Share fehlgeschlagen, Fallback auf Matrix: %s", exc)
            return None

    async def _handle_document_summary(self, msg: IncomingMessage, result) -> None:
        await self._handle_llm_enrichment(
            msg=msg, result=result,
            prompt_intro="Der Nutzer möchte folgendes Dokument zusammengefasst haben.",
            prompt_instruction="Fasse den Inhalt zusammen.",
            error_log_msg="Dokument-Zusammenfassung LLM fehlgeschlagen: %s",
            error_fallback_suffix="LLM-Zusammenfassung fehlgeschlagen",
        )

    async def _handle_mail_summary(self, msg: IncomingMessage, result) -> None:
        await self._handle_llm_enrichment(
            msg=msg, result=result,
            prompt_intro="Der Nutzer hat folgende E-Mail abgerufen.",
            prompt_instruction=(
                "Beantworte die Anfrage des Nutzers basierend auf dem Inhalt "
                "dieser Mail und dem bisherigen Gesprächsverlauf."
            ),
            error_log_msg="Mail-Summary LLM fehlgeschlagen: %s",
            error_fallback_suffix="LLM-Verarbeitung fehlgeschlagen",
        )

    # ------------------------------------------------------------------
    # Standard LLM (Assistant)
    # ------------------------------------------------------------------

    async def handle_assistant_message(self, msg: IncomingMessage) -> None:
        """Delegiert an Assistant.process() (Standard-LLM-Flow)."""
        tmp_wav: Path | None = None

        try:
            loop = asyncio.get_running_loop()

            self._chat_history.add(msg.sender, "user", msg.body)
            chat_context = self._chat_history.format_for_prompt(msg.sender)

            tmp_wav = (
                Path(tempfile.mktemp(suffix=".wav"))
                if self._audio.audio_to_matrix else None
            )
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._assistant.process, msg.body,
                    tmp_wav, chat_context,
                ),
                timeout=120.0,
            )

            # Multi-Step
            if (
                result.action_executed == "multi_step"
                and result.action_success
                and self._task_chain
            ):
                await self._handle_multi_step(msg, result, chat_context)
                return

            # LLM → Remote Command
            if (
                result.action_executed == "remote_command"
                and result.action_success
                and self._remote_commands
            ):
                await self._handle_llm_remote_command(msg, result)
                return

            if result.response:
                self._chat_history.add(msg.sender, "assistant", result.response)
                await self._channel.send_text(msg.room_id, result.response)

            await self._audio.send_audio_if_available(msg.room_id, result, tmp_wav)

        except asyncio.TimeoutError:
            logger.error("Timeout bei LLM-Verarbeitung (120s)")
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Zeitüberschreitung bei der Verarbeitung. Bitte erneut versuchen.",
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(
                "Fehler bei Nachrichtenverarbeitung: %s", e,
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

    # ------------------------------------------------------------------
    # Multi-Step (TaskChainRunner)
    # ------------------------------------------------------------------

    async def _handle_multi_step(
        self, msg: IncomingMessage, llm_result, chat_context: str,
    ) -> None:
        """LLM hat multi_step gewählt → TaskChainRunner ausführen."""
        if llm_result.response:
            self._chat_history.add(msg.sender, "assistant", llm_result.response)
            await self._channel.send_text(msg.room_id, llm_result.response)

        await self._audio.send_audio_if_available(msg.room_id, llm_result, None)

        task_text = ""
        if llm_result.action_params and isinstance(llm_result.action_params, dict):
            task_text = llm_result.action_params.get("task", "")

        if not task_text:
            logger.warning("multi_step ohne task-Parameter")
            return

        logger.info("Multi-Step Chain gestartet: %s", task_text[:100])

        try:
            loop = asyncio.get_running_loop()
            step_messages: list[str] = []

            def on_step(step) -> None:
                status = "✓" if step.success else "✗"
                step_messages.append(
                    f"Schritt {step.step_number}: {step.command} [{status}]"
                )

            chain_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._task_chain.run(
                        user_request=task_text,
                        chat_history=chat_context,
                        on_step=on_step,
                    ),
                ),
                timeout=300.0,
            )

            if step_messages:
                steps_text = "\n".join(step_messages)
                await self._channel.send_text(
                    msg.room_id, f"📋 Schritte:\n{steps_text}",
                )

            if chain_result.final_summary:
                await self._channel.send_text(
                    msg.room_id, chain_result.final_summary,
                )
                self._chat_history.add(
                    msg.sender, "assistant", chain_result.final_summary,
                )

            logger.info(
                "Multi-Step Chain abgeschlossen: %d Schritte, completed=%s",
                chain_result.step_count, chain_result.completed,
            )

        except asyncio.TimeoutError:
            logger.error("Timeout bei Multi-Step Chain (300s)")
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Zeitüberschreitung bei der Multi-Step-Verarbeitung.",
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(
                "Multi-Step Chain fehlgeschlagen: %s", e,
                extra={"sender": msg.sender, "handler": "multi_step"},
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Multi-Step Fehler: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Multi-Step Fehlermeldung nicht senden")

    # ------------------------------------------------------------------
    # LLM → Remote Command (mit Retry)
    # ------------------------------------------------------------------

    async def _handle_llm_remote_command(
        self, msg: IncomingMessage, llm_result,
    ) -> None:
        """LLM hat remote_command Aktion gewählt → Command ausführen."""
        if llm_result.response:
            self._chat_history.add(msg.sender, "assistant", llm_result.response)
            await self._channel.send_text(msg.room_id, llm_result.response)

        await self._audio.send_audio_if_available(msg.room_id, llm_result, None)

        command_text = None
        if llm_result.action_params and isinstance(llm_result.action_params, dict):
            command_text = llm_result.action_params.get("command", "")

        if not command_text:
            logger.debug("LLM remote_command ohne command-Parameter")
            return

        logger.info("LLM → remote_command: %s", command_text)

        from elder_berry.comms.message_channel import IncomingMessage as IM

        cmd = self._remote_commands.parse_command(command_text)
        if cmd:
            cmd_msg = IM(
                sender=msg.sender,
                room_id=msg.room_id,
                body=command_text,
                timestamp=msg.timestamp,
            )
            # Rekursions-Guard setzen: verhindert fallthrough → LLM → Endlosschleife
            self._in_llm_command.add(msg.sender)
            try:
                await self.handle_remote_command(cmd_msg, cmd)
            finally:
                self._in_llm_command.discard(msg.sender)
            return

        # Parse fehlgeschlagen → Retry mit Feedback
        logger.info(
            "LLM remote_command nicht erkannt: '%s' – starte Retry", command_text,
        )
        retry_cmd = await self._retry_llm_remote_command(msg, command_text)
        if retry_cmd:
            cmd_msg = IM(
                sender=msg.sender,
                room_id=msg.room_id,
                body=retry_cmd,
                timestamp=msg.timestamp,
            )
            parsed = self._remote_commands.parse_command(retry_cmd)
            if parsed:
                await self.handle_remote_command(cmd_msg, parsed)
                return

        logger.warning(
            "LLM remote_command nach Retry nicht erkannt: '%s'", command_text,
        )

    async def _retry_llm_remote_command(
        self, msg: IncomingMessage, failed_command: str,
    ) -> str | None:
        """Gibt dem LLM Feedback über den fehlgeschlagenen Command.

        Ruft generate_raw() auf, um SmartContext, Memory, TTS und
        Emotion-Extraktion zu umgehen.
        """
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
                    None, self._assistant.generate_raw,
                    retry_prompt, "", chat_context,
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
