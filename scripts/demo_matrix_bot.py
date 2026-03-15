"""Demo: Matrix-Bot – Saleria via Matrix mit LLM + TTS + Audio + Remote-Commands.

Modi (kombinierbar):
  1. Echo-Modus (Standard): Einfaches Echo, kein LLM nötig.
  2. Remote-Modus (--remote): Direkte Commands (status, screenshot, media, volume).
     Kein LLM nötig – nicht-erkannte Nachrichten werden als Echo beantwortet.
  3. LLM-Modus (--llm): Volle Pipeline – LLM + TTS + WAV→OGG → Sprachnachricht.
     Kombinierbar mit --remote: Commands direkt, Rest über LLM.
  4. Agent-Modus (--agent): Claude API für komplexe Projekt-Anfragen.
     Trigger: "claude" im Text + Auftrag in Anführungszeichen.
     Kombinierbar mit --llm und --remote.

Verwendung:
    python scripts/demo_matrix_bot.py                          # Echo-Modus
    python scripts/demo_matrix_bot.py --remote                 # Remote-Commands
    python scripts/demo_matrix_bot.py --llm                    # LLM-Modus
    python scripts/demo_matrix_bot.py --llm --remote --agent   # Alles kombiniert

Voraussetzung:
    - Secrets gespeichert via SecretStore (matrix_homeserver, matrix_user_id,
      matrix_password, matrix_room_id)
    - Matrix-Server erreichbar
    - LLM-Modus: Ollama lokal + ffmpeg installiert
    - Remote-Modus: mss installiert (für Screenshots)
    - Agent-Modus: anthropic_api_key im SecretStore
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Projekt-Root zum Python-Path hinzufügen
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from elder_berry.comms.matrix_channel import MatrixChannel
from elder_berry.comms.message_channel import IncomingMessage
from elder_berry.core.secret_store import SecretStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("demo_matrix_bot")


def create_remote_handler():
    """Erstellt einen RemoteCommandHandler mit verfügbaren Dependencies."""
    from elder_berry.comms.remote_commands import RemoteCommandHandler

    monitor = None
    controller = None

    try:
        from elder_berry.system.info import SystemMonitor
        monitor = SystemMonitor()
        logger.info("SystemMonitor geladen")
    except Exception as e:
        logger.warning("SystemMonitor nicht verfügbar: %s", e)

    try:
        from elder_berry.actions.windows_controller import WindowsActionController
        controller = WindowsActionController()
        logger.info("ActionController geladen (Media + Volume)")
    except Exception as e:
        logger.warning("ActionController nicht verfügbar: %s", e)

    handler = RemoteCommandHandler(
        system_monitor=monitor,
        controller=controller,
    )
    logger.info("RemoteCommandHandler erstellt")
    return handler


def create_claude_agent():
    """Erstellt einen ClaudeAgent (wenn API-Key im SecretStore vorhanden).

    Returns:
        ClaudeAgent oder None bei Fehler.
    """
    try:
        from elder_berry.comms.claude_agent import ClaudeAgent

        store = SecretStore()
        api_key = store.get_or_none("anthropic_api_key")
        if not api_key:
            logger.error(
                "Secret 'anthropic_api_key' fehlt! "
                "Speichere ihn mit: SecretStore().set('anthropic_api_key', 'sk-ant-...')"
            )
            return None

        project_root = Path(__file__).resolve().parent.parent
        agent = ClaudeAgent(api_key=api_key, project_root=project_root)
        logger.info("ClaudeAgent erstellt (Modell: %s)", agent.model)
        return agent

    except Exception as e:
        logger.error("ClaudeAgent konnte nicht erstellt werden: %s", e)
        return None


def create_assistant_and_converter():
    """Erstellt Assistant + AudioConverter für den LLM-Modus.

    Returns:
        Tuple (assistant, audio_converter) oder None bei Fehler.
    """
    try:
        from elder_berry.actions.db import ActionsDB
        from elder_berry.actions.windows_controller import WindowsActionController
        from elder_berry.comms.audio_converter import AudioConverter
        from elder_berry.core.assistant import Assistant
        from elder_berry.llm.ollama_client import OllamaClient

        llm = OllamaClient()
        db = ActionsDB()
        controller = WindowsActionController()
        converter = AudioConverter()

        # SystemMonitor optional
        monitor = None
        try:
            from elder_berry.system.info import SystemMonitor
            monitor = SystemMonitor()
        except Exception:
            pass

        # Character optional (muss vor TTS geladen werden für Voice-Map)
        character = None
        try:
            from elder_berry.character.base import Emotion
            from elder_berry.character.saleria import SaleriaEngine
            character = SaleriaEngine()
            logger.info("SaleriaEngine geladen")
        except Exception as e:
            logger.warning("Character nicht verfügbar: %s", e)

        # TTS optional – Voice-Map aus Character aufbauen
        tts = None
        try:
            from elder_berry.tts.coqui_engine import CoquiTTSEngine

            voice_map = {}
            default_wav = None
            if character:
                for emotion in Emotion:
                    sample = character.get_voice_sample(emotion)
                    if sample:
                        voice_map[emotion.value] = sample
                default_wav = voice_map.get("neutral")
                logger.info("Voice-Map: %d Emotionen geladen", len(voice_map))

            tts = CoquiTTSEngine(
                voice_map=voice_map,
                default_speaker_wav=default_wav,
                language="de",
            )
            tts.load()
            logger.info("CoquiTTS geladen")
        except Exception as e:
            logger.warning("TTS nicht verfügbar (nur Text-Antworten): %s", e)

        assistant = Assistant(
            llm=llm,
            actions_db=db,
            controller=controller,
            tts=tts,
            character=character,
            system_monitor=monitor,
        )

        logger.info("Assistant erstellt (LLM: Ollama, TTS: %s)", "aktiv" if tts else "aus")
        return assistant, converter

    except Exception as e:
        logger.error("Fehler beim Erstellen des Assistants: %s", e)
        return None


async def run_echo_mode(channel: MatrixChannel) -> None:
    """Echo-Modus: Empfängt Nachrichten, antwortet mit Echo."""

    async def on_message(msg: IncomingMessage) -> None:
        logger.info("[Echo] %s: %s", msg.sender, msg.body)
        reply = f"Echo: {msg.body}"
        await channel.send_text(msg.room_id, reply)

    await channel.connect()
    channel.on_message(on_message)

    logger.info("Echo-Bot laeuft! Schreibe eine Nachricht in Element.")
    logger.info("Strg+C zum Beenden.")

    try:
        await channel.sync_loop()
    except KeyboardInterrupt:
        pass
    finally:
        await channel.disconnect()


async def run_remote_mode(channel: MatrixChannel) -> None:
    """Remote-Modus: Direkte Commands, Echo-Fallback für alles andere."""
    from elder_berry.comms.remote_commands import RemoteCommandHandler

    handler = create_remote_handler()

    async def on_message(msg: IncomingMessage) -> None:
        logger.info("[Remote] %s: %s", msg.sender, msg.body)

        command = handler.parse_command(msg.body)
        if command:
            result = handler.execute(command, msg.body)

            if result.text:
                await channel.send_text(msg.room_id, result.text)

            if result.image_path and result.image_path.exists():
                try:
                    await channel.send_image(msg.room_id, result.image_path)
                except NotImplementedError:
                    await channel.send_text(
                        msg.room_id, "Screenshot aufgenommen, Bild-Upload nicht verfügbar.",
                    )
                finally:
                    result.image_path.unlink(missing_ok=True)
        else:
            # Kein Command → Echo
            await channel.send_text(msg.room_id, f"Echo: {msg.body}")

    await channel.connect()
    channel.on_message(on_message)

    logger.info("Remote-Bot laeuft! Commands: status, screenshot, pause, play, skip, next, volume <0-100>")
    logger.info("Strg+C zum Beenden.")

    try:
        await channel.sync_loop()
    except KeyboardInterrupt:
        pass
    finally:
        await channel.disconnect()


async def run_llm_mode(
    channel: MatrixChannel, use_remote: bool, use_agent: bool,
) -> None:
    """LLM-Modus: Volle Pipeline mit MatrixBridge."""
    components = create_assistant_and_converter()
    if components is None:
        logger.error("Konnte LLM-Modus nicht starten.")
        return

    assistant, converter = components

    remote_handler = None
    if use_remote:
        remote_handler = create_remote_handler()

    claude_agent = None
    if use_agent:
        claude_agent = create_claude_agent()
        if claude_agent is None:
            logger.warning("Agent-Modus deaktiviert (kein API-Key).")

    from elder_berry.comms.bridge import MatrixBridge

    bridge = MatrixBridge(
        channel=channel,
        assistant=assistant,
        audio_converter=converter,
        remote_commands=remote_handler,
        claude_agent=claude_agent,
    )

    bridge.start()
    parts = ["LLM"]
    if use_remote:
        parts.append("Remote")
    if claude_agent:
        parts.append("Agent")
    mode_info = " + ".join(parts)
    logger.info("Saleria-Bot laeuft im %s-Modus!", mode_info)
    if use_remote:
        logger.info("Direkte Commands: status, screenshot, pause, play, skip, next, volume <0-100>")
    if claude_agent:
        logger.info("Claude-Agent: Schreibe 'claude \"Dein Auftrag hier\"'")
    logger.info("Strg+C zum Beenden.")

    try:
        # Warte bis Strg+C
        while bridge.is_running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
        logger.info("Bot beendet.")


async def main(use_llm: bool, use_remote: bool, use_agent: bool) -> None:
    # Credentials laden
    store = SecretStore()
    required_keys = [
        "matrix_homeserver", "matrix_user_id",
        "matrix_password", "matrix_room_id",
    ]

    for key in required_keys:
        if not store.has(key):
            logger.error("Secret '%s' fehlt! Bitte zuerst einrichten.", key)
            sys.exit(1)

    homeserver = store.get("matrix_homeserver")
    user_id = store.get("matrix_user_id")
    password = store.get("matrix_password")
    room_id = store.get("matrix_room_id")

    logger.info("Verbinde zu %s als %s ...", homeserver, user_id)

    channel = MatrixChannel(
        homeserver=homeserver,
        user_id=user_id,
        password=password,
        allowed_rooms=[room_id],
    )

    if use_llm or use_agent:
        await run_llm_mode(channel, use_remote, use_agent)
    elif use_remote:
        await run_remote_mode(channel)
    else:
        await run_echo_mode(channel)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Saleria Matrix Bot")
    parser.add_argument(
        "--llm", action="store_true",
        help="LLM-Modus: Volle Pipeline mit Ollama + TTS + Audio",
    )
    parser.add_argument(
        "--remote", action="store_true",
        help="Remote-Commands: status, screenshot, media, volume (kein LLM nötig)",
    )
    parser.add_argument(
        "--agent", action="store_true",
        help="Claude-Agent: Komplexe Anfragen via Anthropic API "
             '(Trigger: claude "Auftrag")',
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(
            use_llm=args.llm, use_remote=args.remote, use_agent=args.agent,
        ))
    except KeyboardInterrupt:
        print("\nBeendet.")
