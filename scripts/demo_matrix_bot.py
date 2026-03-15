"""Demo: Matrix-Bot – Saleria via Matrix mit LLM + TTS + Audio.

Zwei Modi:
  1. Echo-Modus (Standard): Einfaches Echo, kein LLM nötig.
  2. LLM-Modus (--llm): Volle Pipeline – LLM + TTS + WAV→OGG → Sprachnachricht.

Verwendung:
    python scripts/demo_matrix_bot.py           # Echo-Modus
    python scripts/demo_matrix_bot.py --llm     # LLM-Modus (Ollama muss laufen)

Voraussetzung:
    - Secrets gespeichert via SecretStore (matrix_homeserver, matrix_user_id,
      matrix_password, matrix_room_id)
    - Matrix-Server erreichbar
    - LLM-Modus: Ollama lokal + ffmpeg installiert
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


async def run_llm_mode(channel: MatrixChannel) -> None:
    """LLM-Modus: Volle Pipeline mit MatrixBridge."""
    components = create_assistant_and_converter()
    if components is None:
        logger.error("Konnte LLM-Modus nicht starten.")
        return

    assistant, converter = components

    from elder_berry.comms.bridge import MatrixBridge

    bridge = MatrixBridge(
        channel=channel,
        assistant=assistant,
        audio_converter=converter,
    )

    bridge.start()
    logger.info("Saleria-Bot laeuft im LLM-Modus!")
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


async def main(use_llm: bool) -> None:
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

    if use_llm:
        await run_llm_mode(channel)
    else:
        await run_echo_mode(channel)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Saleria Matrix Bot")
    parser.add_argument(
        "--llm", action="store_true",
        help="LLM-Modus: Volle Pipeline mit Ollama + TTS + Audio",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(use_llm=args.llm))
    except KeyboardInterrupt:
        print("\nBeendet.")
