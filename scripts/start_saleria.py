#!/usr/bin/env python3
"""
start_saleria.py – Startet den vollständigen Elder-Berry Assistenten.

Verwendung:
    python scripts/start_saleria.py                  # Matrix-Modus (Standard)
    python scripts/start_saleria.py --mode terminal  # Terminal-Modus
    python scripts/start_saleria.py --mode voice     # Voice-Modus (STT + TTS)
    python scripts/start_saleria.py --no-memory      # Ohne RAG-Gedächtnis
    python scripts/start_saleria.py --no-tts         # Ohne Sprachausgabe

Voraussetzungen Tower (Windows):
    pip install -e ".[windows,tts-neural,avatar,matrix,remote,memory,stt]"
    ANTHROPIC_API_KEY in .env
    Ollama läuft: ollama serve
    Embedding-Modell: ollama pull nomic-embed-text
"""
from __future__ import annotations

import argparse
import logging
import os
import platform
import sys
from pathlib import Path

# Projektpfad sicherstellen
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("saleria")

# ---------------------------------------------------------------------------
# Argument-Parser
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Elder-Berry Assistentin – Saleria Berry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["terminal", "matrix", "voice"],
        default="matrix",
        help="Eingabe-Modus (Standard: matrix)",
    )
    parser.add_argument("--no-memory", action="store_true", help="RAG-Gedächtnis deaktivieren")
    parser.add_argument("--no-tts", action="store_true", help="Sprachausgabe deaktivieren")
    parser.add_argument("--no-avatar", action="store_true", help="Avatar deaktivieren")
    parser.add_argument("--whisper-model", default="medium", help="Whisper-Modell (tiny/base/small/medium/large-v3)")
    parser.add_argument("--debug", action="store_true", help="Debug-Logging aktivieren")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Komponenten-Initialisierung
# ---------------------------------------------------------------------------

def init_llm():
    from elder_berry.llm.router import LLMRouter
    router = LLMRouter.create_default()
    backend = router.active_backend
    if backend == "none":
        logger.error("Kein LLM-Backend verfügbar! ANTHROPIC_API_KEY setzen oder Ollama starten.")
        sys.exit(1)
    logger.info("LLM-Backend: %s", backend)
    return router


def init_actions_db() -> tuple:
    from elder_berry.actions.db import ActionsDB
    db_path = Path(os.environ.get("DATA_PATH", Path.home() / ".elder-berry" / "actions.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = ActionsDB(db_path)
    logger.info("ActionsDB: %s", db_path)
    return db


def init_controller():
    """ActionController – nur auf Windows verfügbar."""
    if platform.system() != "Windows":
        logger.warning("ActionController: nicht verfügbar (kein Windows)")
        return _make_dummy_controller()
    try:
        from elder_berry.actions.windows_controller import WindowsActionController
        ctrl = WindowsActionController()
        logger.info("ActionController: WindowsActionController")
        return ctrl
    except ImportError as e:
        logger.warning("ActionController: Windows-Pakete fehlen (%s) – Dummy aktiv", e)
        return _make_dummy_controller()


def _make_dummy_controller():
    """Minimaler Dummy-Controller für Nicht-Windows-Umgebungen."""
    from unittest.mock import MagicMock
    from elder_berry.actions.base import ActionController
    dummy = MagicMock(spec=ActionController)
    dummy.press_key.return_value = None
    dummy.type_text.return_value = None
    return dummy


def init_tts(no_tts: bool):
    """TTS-Engine – bevorzugt CoquiTTS, Fallback pyttsx3, oder None."""
    if no_tts:
        logger.info("TTS: deaktiviert")
        return None
    try:
        from elder_berry.tts.coqui_engine import CoquiTTSEngine
        tts = CoquiTTSEngine()
        logger.info("TTS: CoquiTTSEngine (XTTS v2)")
        return tts
    except (ImportError, Exception) as e:
        logger.debug("CoquiTTS nicht verfügbar: %s", e)

    if platform.system() == "Windows":
        try:
            from elder_berry.tts.windows_engine import WindowsTTSEngine
            tts = WindowsTTSEngine()
            logger.info("TTS: WindowsTTSEngine (SAPI5)")
            return tts
        except (ImportError, Exception) as e:
            logger.warning("WindowsTTS nicht verfügbar: %s", e)

    logger.warning("TTS: kein Engine verfügbar")
    return None


def init_character():
    from elder_berry.character.saleria import SaleriaEngine
    engine = SaleriaEngine()
    logger.info("Charakter: %s", engine._personality.name)
    return engine


def init_memory(no_memory: bool):
    if no_memory:
        logger.info("Memory: deaktiviert")
        return None
    try:
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        from elder_berry.memory.embedding import OllamaEmbeddingClient
        db_path = Path(os.environ.get(
            "MEMORY_DB_PATH",
            Path.home() / ".elder-berry" / "memory"
        ))
        embedding_model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
        embed_client = OllamaEmbeddingClient(model=embedding_model)
        if not embed_client.is_available():
            logger.warning(
                "Ollama für Embeddings nicht erreichbar – Memory ohne semantische Suche"
            )
            embed_client = None
        store = ChromaMemoryStore(db_path=db_path, embedding_client=embed_client)
        logger.info("Memory: ChromaMemoryStore → %s", db_path)
        return store
    except ImportError:
        logger.warning("Memory: chromadb nicht installiert (pip install chromadb)")
        return None
    except Exception as e:
        logger.warning("Memory: Initialisierung fehlgeschlagen: %s", e)
        return None


def init_avatar(no_avatar: bool):
    if no_avatar:
        return None
    try:
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer
        renderer = LayeredSpriteRenderer()
        logger.info("Avatar: LayeredSpriteRenderer")
        return renderer
    except (ImportError, Exception) as e:
        logger.debug("Avatar nicht verfügbar: %s", e)
        return None


def init_system_monitor():
    from elder_berry.system.info import SystemMonitor
    return SystemMonitor()


def init_stt(mode: str, whisper_model: str):
    """STT-Engine: Pflicht für voice-Modus, optional für matrix-Modus."""
    if mode not in ("voice", "matrix"):
        return None
    try:
        from elder_berry.stt.faster_whisper_engine import FasterWhisperEngine
        stt = FasterWhisperEngine(model_size=whisper_model)
        logger.info("STT: FasterWhisperEngine (Modell: %s)", whisper_model)
        return stt
    except ImportError:
        if mode == "voice":
            logger.error("STT: faster-whisper nicht installiert (pip install faster-whisper)")
            sys.exit(1)
        else:
            logger.warning(
                "STT: faster-whisper nicht installiert – Sprachnachrichten via Matrix nicht verfügbar"
            )
            return None


# ---------------------------------------------------------------------------
# Lauf-Modi
# ---------------------------------------------------------------------------

def run_terminal(assistant):
    """Einfacher Terminal-Loop: Text eingeben, Antwort erhalten."""
    print("\n─── Saleria Terminal-Modus ───")
    print("Eingabe: Text tippen + Enter | 'exit' zum Beenden\n")
    try:
        while True:
            try:
                user_input = input("Du: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user_input.lower() in ("exit", "quit", "bye"):
                break
            if not user_input:
                continue
            result = assistant.process(user_input)
            print(f"Saleria [{result.emotion or 'neutral'}]: {result.response}")
            if result.action_executed:
                status = "✓" if result.action_success else "✗"
                print(f"  [{status} Aktion: {result.action_executed}]")
    finally:
        print("\nAuf Wiedersehen!")


def run_voice(assistant, stt):
    """Voice-Loop: Mikrofon aufnehmen → Whisper → Assistant → TTS."""
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        logger.error("sounddevice/numpy nicht installiert")
        sys.exit(1)

    SAMPLE_RATE = 16000
    RECORD_SECONDS = 5  # Aufnahmedauer in Sekunden (später durch VAD ersetzen)

    print("\n─── Saleria Voice-Modus ───")
    print(f"Aufnahme: {RECORD_SECONDS}s nach Enter | 'exit' zum Beenden\n")
    try:
        while True:
            try:
                cmd = input("Enter zum Aufnehmen (oder 'exit'): ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if cmd.lower() in ("exit", "quit"):
                break

            print(f"  Aufnahme läuft ({RECORD_SECONDS}s) ...")
            audio = sd.rec(
                int(RECORD_SECONDS * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
            )
            sd.wait()
            audio_data = (audio.flatten() * 32768).astype(np.int16)

            print("  Transkribiere ...")
            result_stt = stt.transcribe_bytes(
                audio_data.tobytes(), sample_rate=SAMPLE_RATE
            )
            user_input = result_stt.text.strip()
            if not user_input:
                print("  (kein Text erkannt)")
                continue

            print(f"Du: {user_input}")
            result = assistant.process(user_input)
            print(f"Saleria [{result.emotion or 'neutral'}]: {result.response}")
    finally:
        print("\nAuf Wiedersehen!")


def run_matrix(assistant, stt=None):
    """Matrix-Modus: MatrixBridge startet bidirektionalen Chat über Matrix."""
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.comms.matrix_channel import MatrixChannel
    from elder_berry.comms.bridge import MatrixBridge
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.comms.alert_monitor import AlertMonitor, AlertConfig
    from elder_berry.system.info import SystemMonitor

    secrets = SecretStore()
    homeserver = secrets.get_or_none("matrix_homeserver") or os.environ.get(
        "MATRIX_HOMESERVER", "https://matrix.last-strawberry.com"
    )
    user_id = secrets.get_or_none("matrix_user_id") or os.environ.get("MATRIX_USER_ID")
    token = secrets.get_or_none("matrix_access_token") or os.environ.get("MATRIX_ACCESS_TOKEN")

    if not user_id or not token:
        logger.error(
            "Matrix-Credentials fehlen. Setze via SecretStore:\n"
            "  from elder_berry.core.secret_store import SecretStore\n"
            "  s = SecretStore()\n"
            "  s.set('matrix_homeserver', 'https://matrix.last-strawberry.com')\n"
            "  s.set('matrix_user_id', '@saleria:matrix.last-strawberry.com')\n"
            "  s.set('matrix_access_token', 'syt_...')"
        )
        sys.exit(1)

    channel = MatrixChannel(homeserver=homeserver, user_id=user_id, access_token=token)

    # RemoteCommandHandler
    remote = RemoteCommandHandler(
        system_monitor=SystemMonitor(),
        action_controller=assistant._controller,
    )

    # ClaudeAgent (optional)
    claude_agent = None
    anthropic_key = secrets.get_or_none("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            from elder_berry.comms.claude_agent import ClaudeAgent
            claude_agent = ClaudeAgent(
                api_key=anthropic_key,
                project_root=_PROJECT_ROOT,
            )
            logger.info("ClaudeAgent: aktiv")
        except Exception as e:
            logger.warning("ClaudeAgent nicht verfügbar: %s", e)

    # AlertMonitor
    alert_config = AlertConfig(disk_threshold_percent=90.0)
    alert_monitor = AlertMonitor(config=alert_config)

    if stt:
        logger.info("Matrix-STT: Sprachnachrichten werden transkribiert")

    bridge = MatrixBridge(
        channel=channel,
        assistant=assistant,
        remote_commands=remote,
        claude_agent=claude_agent,
        alert_monitor=alert_monitor,
        stt=stt,
    )

    logger.info("Matrix-Bridge startet – Saleria ist online")
    print(f"\n─── Saleria Matrix-Modus ───")
    print(f"Bot: {user_id}")
    print("Ctrl+C zum Beenden\n")

    try:
        bridge.start()
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown ...")
    finally:
        bridge.stop()
        logger.info("Saleria beendet.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    print("═" * 50)
    print("  Saleria Berry – Elder-Berry Assistent")
    print(f"  Modus: {args.mode.upper()}")
    print("═" * 50)

    llm = init_llm()
    db = init_actions_db()
    controller = init_controller()
    tts = init_tts(args.no_tts)
    character = init_character()
    memory = init_memory(args.no_memory)
    avatar = init_avatar(args.no_avatar)
    monitor = init_system_monitor()
    stt = init_stt(args.mode, args.whisper_model)

    from elder_berry.core.assistant import Assistant
    assistant = Assistant(
        llm=llm,
        actions_db=db,
        controller=controller,
        tts=tts,
        character=character,
        avatar=avatar,
        system_monitor=monitor,
        memory=memory,
    )

    print()
    if args.mode == "terminal":
        run_terminal(assistant)
    elif args.mode == "voice":
        run_voice(assistant, stt)
    else:
        run_matrix(assistant, stt=stt)


if __name__ == "__main__":
    main()
