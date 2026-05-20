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
    ANTHROPIC_API_KEY in .env oder SecretStore
    Ollama läuft: ollama serve
    Embedding-Modell: ollama pull nomic-embed-text
"""

from __future__ import annotations

import argparse
import atexit
import logging
import logging.config
import os
import platform
import signal
import sys
from pathlib import Path

# Projektpfad sicherstellen – ELDER_BERRY_HOME überschreibt den Default
_PROJECT_ROOT = Path(
    os.environ.get("ELDER_BERRY_HOME", Path(__file__).parent.parent)
).resolve()
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402 -- bewusst nach sys.path-Setup

load_dotenv(_PROJECT_ROOT / ".env")

# logs/ Verzeichnis anlegen (für RotatingFileHandler)
_LOG_DIR = _PROJECT_ROOT / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%H:%M:%S",
        },
        "file": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": "INFO",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(_LOG_DIR / "elder_berry.log"),
            "formatter": "file",
            "level": "INFO",
            "maxBytes": 5_000_000,
            "backupCount": 3,
            "encoding": "utf-8",
        },
        # Phase 59: Separates Audit-Log für Security-Events (Lockouts, Blocks).
        "security_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(_LOG_DIR / "security.log"),
            "formatter": "file",
            "level": "DEBUG",
            "maxBytes": 2_000_000,
            "backupCount": 5,
            "encoding": "utf-8",
        },
        "error_collector": {
            "class": "elder_berry.core.error_collector.ErrorCollectorHandler",
            "level": "ERROR",
        },
    },
    "loggers": {
        # Phase 59: elder_berry.security schreibt in security.log + console.
        "elder_berry.security": {
            "handlers": ["security_file", "console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file", "error_collector"],
    },
}

logger = logging.getLogger("saleria")

# dictConfig nur bei direkter Ausführung – nicht beim Import aus Tests.
# Ein Test-Import von ``from start_saleria import run_agent`` würde sonst
# einen ErrorCollectorHandler permanent an den Root-Logger hängen und
# test_bridge.py::TestErrorAlerting im Batch-Lauf stören.
if __name__ == "__main__":
    logging.config.dictConfig(LOGGING_CONFIG)

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
        choices=["terminal", "matrix", "voice", "agent"],
        default="matrix",
        help="Eingabe-Modus (Standard: matrix). 'agent' startet nur den TowerServer.",
    )
    parser.add_argument(
        "--no-memory", action="store_true", help="RAG-Gedächtnis deaktivieren"
    )
    parser.add_argument(
        "--no-tts", action="store_true", help="Sprachausgabe deaktivieren"
    )
    parser.add_argument("--no-avatar", action="store_true", help="Avatar deaktivieren")
    parser.add_argument(
        "--whisper-model",
        default="medium",
        help="Whisper-Modell (tiny/base/small/medium/large-v3)",
    )
    parser.add_argument("--debug", action="store_true", help="Debug-Logging aktivieren")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Secrets → Env-Variablen (damit LLMRouter + andere Komponenten sie finden)
# ---------------------------------------------------------------------------


def _check_first_run() -> bool:
    """Prüft ob die Minimal-Konfiguration vorhanden ist.

    Returns True wenn Matrix-Token vorhanden (= Setup bereits durchlaufen).
    """
    try:
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore()
        required = ["matrix_access_token", "matrix_user_id", "matrix_homeserver"]
        return all(store.has(k) for k in required)
    except Exception:
        return False


def load_secrets_to_env():
    """Lädt API-Keys aus SecretStore in os.environ (wenn nicht bereits gesetzt)."""
    try:
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore()

        key_map = {
            "anthropic_api_key": "ANTHROPIC_API_KEY",
            "openrouter_api_key": "OPENROUTER_API_KEY",
        }
        for secret_name, env_name in key_map.items():
            if env_name not in os.environ:
                val = store.get_or_none(secret_name)
                if val:
                    os.environ[env_name] = val
                    logger.debug("Secret '%s' → $%s geladen", secret_name, env_name)
    except Exception as e:
        logger.debug("SecretStore nicht verfügbar: %s", e)


# Phase 57.4: ``load_allowed_senders`` lebt in einem eigenen Comms-Modul
# und wird von dort importiert – der Test-Code darf die Funktion
# importieren, ohne die Logging-Config dieses Skripts zu triggern.
from elder_berry.comms.allowed_senders import load_allowed_senders  # noqa: E402


# ---------------------------------------------------------------------------
# Komponenten-Initialisierung
# ---------------------------------------------------------------------------


def init_llm():
    from elder_berry.llm.router import LLMRouter

    router = LLMRouter.create_default()
    backend = router.active_backend
    if backend == "none":
        logger.error(
            "Kein LLM-Backend verfügbar! ANTHROPIC_API_KEY setzen oder Ollama starten."
        )
        sys.exit(1)
    logger.info("LLM-Backend: %s", backend)
    return router


def init_actions_db():
    from elder_berry.actions.db import ActionsDB

    db_path = Path(
        os.environ.get("DATA_PATH", Path.home() / ".elder-berry" / "actions.db")
    )
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


def init_character():
    from elder_berry.character.saleria import SaleriaEngine

    engine = SaleriaEngine()
    logger.info("Charakter: %s", engine._personality.name)
    return engine


def init_tts(no_tts: bool, character=None, event_loop=None):
    """TTS-Engine – TTSRouter (ElevenLabs) wenn Keys vorhanden, sonst lokal.

    Reihenfolge:
    1. ElevenLabs vorhanden → TTSRouter (Cloud-TTS, Tower + lokal als Fallback)
    2. CoquiTTS verfügbar → CoquiTTSEngine (lokales XTTS v2)
    3. Windows → WindowsTTSEngine (SAPI5)
    """
    if no_tts:
        logger.info("TTS: deaktiviert")
        return None

    # Lokale TTS-Engine versuchen (für Standalone oder als Fallback)
    local_tts = _init_local_tts(character)

    # Option 1: TTSRouter (ElevenLabs + Tower + lokaler Fallback)
    tts_router = _init_tts_router(event_loop, local_tts=local_tts)
    if tts_router:
        return tts_router

    # Option 2: Nur lokale Engine (kein ElevenLabs konfiguriert)
    if local_tts:
        return local_tts

    logger.warning("TTS: kein Engine verfügbar")
    return None


def _init_local_tts(character=None):
    """Versucht lokale TTS-Engine zu erstellen (CoquiTTS → WindowsTTS).

    Returns:
        TTSEngine oder None.
    """
    # CoquiTTS (XTTS v2)
    try:
        from elder_berry.tts.coqui_engine import CoquiTTSEngine
        from elder_berry.character.base import Emotion

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
        logger.info("TTS lokal: CoquiTTSEngine (XTTS v2)")
        return tts
    except (ImportError, Exception) as e:
        logger.debug("CoquiTTS nicht verfügbar: %s", e)

    # Windows SAPI5
    if platform.system() == "Windows":
        try:
            from elder_berry.tts.windows_engine import WindowsTTSEngine

            tts = WindowsTTSEngine()
            logger.info("TTS lokal: WindowsTTSEngine (SAPI5)")
            return tts
        except (ImportError, Exception) as e:
            logger.debug("WindowsTTS nicht verfügbar: %s", e)

    return None


def _init_tts_router(event_loop=None, local_tts=None):
    """Versucht TTSRouter mit ElevenLabs + Fallback-Kette zu erstellen.

    Fallback: Tower (XTTS v2) → lokale TTSEngine (CoquiTTS/WindowsTTS).

    Returns:
        TTSRouter oder None wenn ElevenLabs-Keys nicht konfiguriert sind.
    """
    try:
        from elder_berry.core.secret_store import SecretStore
        from elder_berry.core.tts_router import TTSRouter
        from elder_berry.tools.elevenlabs_client import ElevenLabsClient

        store = SecretStore()
        api_key = store.get_or_none("elevenlabs_api_key")
        voice_id = store.get_or_none("elevenlabs_voice_id")

        if not api_key or not voice_id:
            logger.debug("ElevenLabs nicht konfiguriert (Keys fehlen)")
            return None

        elevenlabs = ElevenLabsClient(api_key=api_key, voice_id=voice_id)

        # Tower-Fallback (optional)
        tower = _init_tower_agent(store)

        router = TTSRouter(
            elevenlabs=elevenlabs,
            tower=tower,
            local_tts=local_tts,
            event_loop=event_loop,
        )
        fallbacks = []
        if tower:
            fallbacks.append("Tower")
        if local_tts:
            fallbacks.append(type(local_tts).__name__)
        fb_str = " + ".join(fallbacks)
        logger.info(
            "TTS: TTSRouter (ElevenLabs%s)",
            " → " + fb_str if fb_str else "",
        )
        return router
    except Exception as e:
        logger.debug("TTSRouter nicht initialisierbar: %s", e)
        return None


def _init_tower_agent(store=None):
    """Erstellt TowerAgent wenn tower_host konfiguriert ist.

    Phase 57.3: Token wird aus dem SecretStore gelesen und an den
    TowerAgent durchgereicht. Ohne Token funktionieren die Requests
    zum Tower-Server nicht (401).

    Returns:
        TowerAgent oder None.
    """
    try:
        from elder_berry.core.tower_agent import TowerAgent

        if store is None:
            from elder_berry.core.secret_store import SecretStore

            store = SecretStore()

        tower_host = store.get_or_none("tower_host")
        if not tower_host:
            return None

        # Phase 57.3: Token für den Tower-Server
        tower_token = os.environ.get("ELDER_BERRY_TOWER_TOKEN") or store.get_or_none(
            "tower_auth_token"
        )
        if not tower_token:
            logger.warning(
                "TowerAgent: kein Tower-Token konfiguriert – Requests "
                "werden mit 401 abgelehnt. Setze tower_auth_token im "
                "SecretStore oder ELDER_BERRY_TOWER_TOKEN als Env.",
            )

        agent = TowerAgent(tower_host=tower_host, tower_token=tower_token)
        logger.info("TowerAgent: konfiguriert für %s", tower_host)
        return agent
    except Exception as e:
        logger.debug("TowerAgent nicht verfügbar: %s", e)
        return None


def init_memory(no_memory: bool):
    if no_memory:
        logger.info("Memory: deaktiviert")
        return None
    try:
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        from elder_berry.memory.embedding import OllamaEmbeddingClient

        db_path = Path(
            os.environ.get("MEMORY_DB_PATH", Path.home() / ".elder-berry" / "memory")
        )
        embedding_model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
        embed_client = OllamaEmbeddingClient(model=embedding_model)
        if not embed_client.is_available():
            logger.warning(
                "Ollama nicht erreichbar – Memory deaktiviert "
                "(ohne Ollama-Embeddings droht Dimension-Mismatch mit bestehender Collection)"
            )
            return None
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


def _check_local_audio(assistant) -> bool:
    """Prüft ob lokale Audio-Wiedergabe möglich ist (sounddevice oder AgentClient)."""
    # AgentClient am Assistant?
    agent = getattr(assistant, "_agent", None)
    if agent is not None:
        try:
            if agent.is_online():
                return True
        except AttributeError:
            # Duck-typing-Fallback: assistant._agent ist nicht der erwartete
            # AgentClient (z.B. Test-Stub ohne is_online). is_online() selbst
            # faengt Netz-Fehler intern und liefert False.
            pass

    # sounddevice verfügbar?
    try:
        import sounddevice  # noqa: F401

        return True
    except ImportError:
        pass

    return False


def init_audio_converter():
    """AudioConverter für WAV→OGG/Opus (Matrix-Sprachnachrichten)."""
    try:
        from elder_berry.comms.audio_converter import AudioConverter

        converter = AudioConverter()
        if converter.ffmpeg_available:
            logger.info("AudioConverter: ffmpeg verfügbar")
            return converter
        logger.warning("AudioConverter: ffmpeg nicht gefunden – keine Sprachantworten")
        return None
    except ImportError:
        logger.debug("AudioConverter: Modul nicht importierbar")
        return None


def init_stt(mode: str, whisper_model: str, event_loop=None):
    """STT-Engine – STTRouter (Cloud) wenn Keys vorhanden, sonst lokal.

    Reihenfolge:
    1. Groq API Key vorhanden → STTRouter (Cloud-STT, Tower als Fallback)
    2. FasterWhisper verfügbar → FasterWhisperEngine (lokales Whisper)
    """
    if mode not in ("voice", "matrix"):
        return None

    # Option 1: STTRouter (Cloud-STT + Tower-Fallback)
    stt_router = _init_stt_router(event_loop)
    if stt_router:
        return stt_router

    # Option 2: Lokales FasterWhisper
    try:
        from elder_berry.stt.faster_whisper_engine import FasterWhisperEngine

        stt = FasterWhisperEngine(model_size=whisper_model)
        logger.info("STT: FasterWhisperEngine (Modell: %s)", whisper_model)
        return stt
    except ImportError:
        if mode == "voice":
            logger.error(
                "STT: faster-whisper nicht installiert (pip install faster-whisper)"
            )
            sys.exit(1)
        else:
            logger.warning(
                "STT: faster-whisper nicht installiert – Sprachnachrichten via Matrix nicht verfügbar"
            )
            return None


def _init_stt_router(event_loop=None):
    """Versucht STTRouter mit Cloud-STT + optionalem Tower-Fallback zu erstellen.

    Returns:
        STTRouter oder None wenn Groq-Key nicht konfiguriert ist.
    """
    try:
        from elder_berry.core.secret_store import SecretStore
        from elder_berry.core.stt_router import STTRouter
        from elder_berry.tools.cloud_stt_client import CloudSTTClient

        store = SecretStore()
        api_key = store.get_or_none("groq_api_key")

        if not api_key:
            logger.debug("Cloud-STT nicht konfiguriert (groq_api_key fehlt)")
            return None

        cloud_stt = CloudSTTClient(api_key=api_key)

        # Tower-Fallback (optional, wiederverwendet bestehenden TowerAgent)
        tower = _init_tower_agent(store)

        router = STTRouter(
            cloud_stt=cloud_stt,
            tower=tower,
            event_loop=event_loop,
        )
        logger.info(
            "STT: STTRouter (Groq Cloud%s)",
            " + Tower-Fallback" if tower else "",
        )
        return router
    except Exception as e:
        logger.debug("STTRouter nicht initialisierbar: %s", e)
        return None


# ---------------------------------------------------------------------------
# Lauf-Modi
# ---------------------------------------------------------------------------


def _wait_for_port_free(host: str, port: int, timeout: float = 15.0) -> None:
    """Wartet, bis ``host:port`` nicht mehr von einem anderen Prozess belegt ist.

    Hintergrund: Beim Self-Respawn nach `update tower` startet der neue
    Prozess, waehrend der alte uvicorn noch ~1-2 s laeuft und Port 8090
    haelt. Ohne Wait knallt uvicorn beim Bind. Beim *normalen* Erststart
    (kein Vorgaenger) returnt der ``connect`` sofort mit
    ConnectionRefused -- der Wait ist dann unmerklich (~1 ms).

    Loggt eine Warnung, wenn der Port nach ``timeout`` Sekunden noch
    belegt ist; uvicorn versucht den Bind dann trotzdem.
    """
    import socket as _socket
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect((host, port))
            except (OSError, ConnectionRefusedError):
                # Port ist frei -- frueh raus
                return
        _time.sleep(0.5)
    logger.warning(
        "Port %d:%s nach %.0fs noch belegt -- versuche Bind trotzdem.",
        port,
        host,
        timeout,
    )


def run_agent(port: int = 8090):
    """Agent-Modus: Startet nur den TowerServer (FastAPI) ohne Bot/LLM.

    Dieser Modus ist für den Tower-PC gedacht, wenn der Bot auf dem
    Server läuft. Der Tower stellt TTS, STT, PC-Steuerung und
    Screenshots über HTTP bereit.
    """
    try:
        import uvicorn
    except ImportError:
        logger.error(
            "uvicorn nicht installiert. Installiere mit: pip install -e '.[tower]'"
        )
        sys.exit(1)

    # tower/ Package muss importierbar sein
    sys.path.insert(0, str(_PROJECT_ROOT))

    # Phase 57.3: Token laden oder Auto-Generieren
    tower_token = os.environ.get("ELDER_BERRY_TOWER_TOKEN")
    if not tower_token:
        try:
            from elder_berry.core.secret_store import SecretStore

            store = SecretStore()
            tower_token = store.get_or_none("tower_auth_token")
            if not tower_token:
                import secrets as _sec

                tower_token = _sec.token_hex(32)
                store.set("tower_auth_token", tower_token)
                logger.info("Tower-Token automatisch generiert und gespeichert")
                logger.info(
                    "Tower-Token (für X-Saleria-Tower-Token Header): %s",
                    tower_token,
                )
        except Exception as exc:
            logger.error("Tower-Token konnte nicht geladen/generiert werden: %s", exc)
            sys.exit(1)
    os.environ["ELDER_BERRY_TOWER_TOKEN"] = tower_token

    try:
        from tower.tower_server import app  # noqa: F401
    except ImportError as e:
        logger.error("TowerServer nicht importierbar: %s", e)
        sys.exit(1)

    print("\n─── Saleria Agent-Modus (TowerServer) ───")
    print("  Endpunkte: /status, /tts, /stt, /action, /screenshot")
    print(f"  Port: {port}")
    print(
        f"  Token: {'aus Env' if os.environ.get('ELDER_BERRY_TOWER_TOKEN') == tower_token else 'aus SecretStore'}"
    )
    print("  Ctrl+C zum Beenden\n")

    # Phase 57.1: Loopback-Default
    tower_bind = os.environ.get("ELDER_BERRY_TOWER_BIND", "127.0.0.1")
    if tower_bind not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "TowerServer lauscht auf %s:%d – Steuerung ist im Netz "
            "erreichbar. Nur im vertrauenswürdigen Netz nutzen.",
            tower_bind,
            port,
        )

    # Self-Respawn-Race: nach Tower-Update startet der neue Prozess,
    # waehrend der alte uvicorn noch Port 8090 haelt. Wir warten kurz.
    _probe_host = "127.0.0.1" if tower_bind in ("0.0.0.0", "::") else tower_bind
    _wait_for_port_free(_probe_host, port)

    uvicorn.run(
        "tower.tower_server:app",
        host=tower_bind,
        port=port,
        log_level="info",
    )


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
    RECORD_SECONDS = 5

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


def _init_matrix_channel(secrets):
    """Initialisiert MatrixChannel mit Credentials aus SecretStore."""
    from elder_berry.comms.matrix_channel import MatrixChannel

    # Phase 67: kein Phantasie-Default mehr -- wenn der Homeserver fehlt,
    # bricht der Start sauber ab statt gegen matrix.example.com zu reden.
    homeserver = secrets.get_or_none("matrix_homeserver") or os.environ.get(
        "MATRIX_HOMESERVER"
    )
    user_id = secrets.get_or_none("matrix_user_id") or os.environ.get("MATRIX_USER_ID")
    token = secrets.get_or_none("matrix_access_token") or os.environ.get(
        "MATRIX_ACCESS_TOKEN"
    )
    room_id = secrets.get_or_none("matrix_room_id") or os.environ.get("MATRIX_ROOM_ID")

    if not homeserver or not user_id or not token:
        logger.error(
            "Matrix-Credentials fehlen. Setze via SecretStore:\n"
            "  from elder_berry.core.secret_store import SecretStore\n"
            "  s = SecretStore()\n"
            "  s.set('matrix_homeserver', 'https://matrix.example.com')\n"
            "  s.set('matrix_user_id', '@saleria:matrix.example.com')\n"
            "  s.set('matrix_access_token', 'syt_...')"
        )
        sys.exit(1)

    allowed_rooms = [room_id] if room_id else None
    channel = MatrixChannel(
        homeserver=homeserver,
        user_id=user_id,
        access_token=token,
        allowed_rooms=allowed_rooms,
    )
    return channel, user_id, room_id


def _init_productivity_services(secrets, default_user_id):
    """Initialisiert Produktivitäts-Tools: Calendar, Email, Contacts, Todos, etc."""
    svc = {}

    # Calendar: Nextcloud CalDAV (bevorzugt) oder Google Calendar (Fallback)
    calendar_client = None

    # Versuch 1: Nextcloud CalDAV
    if secrets.get_or_none("nextcloud_url"):
        try:
            from elder_berry.tools.caldav_calendar import CalDAVCalendarClient

            cal = CalDAVCalendarClient(secret_store=secrets)
            if cal.is_available():
                calendar_client = cal
                logger.info("Calendar: Nextcloud CalDAV konfiguriert")
        except ImportError:
            logger.debug("CalDAV: caldav-Library nicht installiert")
        except Exception as e:
            logger.warning("CalDAV nicht verfügbar: %s", e)

    # Versuch 2: Google Calendar Fallback
    if calendar_client is None:
        try:
            from elder_berry.tools.google_calendar import GoogleCalendarClient

            cal = GoogleCalendarClient(secret_store=secrets)
            if cal.is_available():
                calendar_client = cal
                logger.info("Calendar: Google Calendar (Fallback)")
        except ImportError:
            logger.debug("Google Calendar: google-api-python-client nicht installiert")
        except Exception as e:
            logger.warning("Google Calendar nicht verfügbar: %s", e)

    if calendar_client:
        svc["calendar"] = calendar_client
    else:
        logger.info("Calendar: kein Provider konfiguriert")

    # Email / IMAP
    if secrets.get_or_none("email_imap_host"):
        try:
            from elder_berry.tools.email_client import IMAPEmailClient

            svc["email_client"] = IMAPEmailClient.from_secret_store(secrets)
            logger.info("Email: IMAP %s", secrets.get("email_imap_host"))
        except Exception as e:
            logger.warning("Email nicht verfügbar: %s", e)

    # Email / SMTP
    if svc.get("email_client") and secrets.get_or_none("email_user"):
        try:
            from elder_berry.tools.email_sender import EmailSender

            sender = EmailSender.from_secret_store(secrets)
            if sender.is_available():
                svc["email_sender"] = sender
                logger.info("Email: SMTP verfügbar")
            else:
                logger.warning("SMTP nicht erreichbar")
        except Exception as e:
            logger.warning("EmailSender nicht verfügbar: %s", e)

    # ContactStore
    try:
        from elder_berry.tools.contact_store import ContactStore

        svc["contact_store"] = ContactStore()
        logger.info("ContactStore initialisiert: %s", svc["contact_store"]._db_path)
    except Exception as e:
        logger.warning("ContactStore nicht verfügbar: %s", e)

    # CalDAVTaskClient (Nextcloud Tasks – ersetzt TodoStore)
    try:
        from elder_berry.tools.caldav_tasks import CalDAVTaskClient

        svc["task_client"] = CalDAVTaskClient(secret_store=secrets)
        logger.info("CalDAVTaskClient initialisiert")
    except Exception as e:
        logger.warning("CalDAVTaskClient nicht verfügbar: %s", e)

    # Berry-Gym
    if secrets.get_or_none("berry_gym_api_token"):
        # Phase 67: berry_gym_url ist Pflicht. Ohne URL waere der Default
        # nicht erreichbar -- besser sauber abschalten als Phantasie-Calls.
        gym_url = secrets.get_or_none("berry_gym_url")
        if not gym_url:
            logger.warning(
                "Berry-Gym: 'berry_gym_api_token' gesetzt, aber "
                "'berry_gym_url' fehlt im SecretStore. Integration "
                "deaktiviert. URL im Dashboard unter 'Dienste' nachtragen.",
            )
        else:
            try:
                from elder_berry.tools.gym_data import GymDataClient

                svc["gym_client"] = GymDataClient(
                    secret_store=secrets,
                    base_url=gym_url,
                )
                logger.info("Berry-Gym: aktiv (%s)", svc["gym_client"]._base_url)
            except Exception as e:
                logger.warning("Berry-Gym nicht verfügbar: %s", e)

    # Weather
    try:
        from elder_berry.tools.weather_client import WeatherClient

        svc["weather"] = WeatherClient(secret_store=secrets)
        logger.info("Weather: aktiv")
    except Exception as e:
        logger.warning("Weather nicht verfügbar: %s", e)

    # FactStore (lokale Key-Value-Fakten -- Phase 91-A)
    try:
        from elder_berry.tools.fact_store import FactStore

        svc["fact_store"] = FactStore()
        logger.info("FactStore: aktiv (DB: %s)", svc["fact_store"]._db_path)
    except Exception as e:
        logger.warning("FactStore nicht verfügbar: %s", e)

    # NextcloudNotesClient (Notizen via Nextcloud Notes API -- Phase 91-B/C)
    if secrets.get_or_none("nextcloud_url"):
        try:
            from elder_berry.tools.nextcloud_notes_client import NextcloudNotesClient

            nc_notes = NextcloudNotesClient(secret_store=secrets)
            if nc_notes.is_available():
                svc["nextcloud_notes"] = nc_notes
                logger.info("Nextcloud Notes: aktiv")
            else:
                logger.warning("Nextcloud Notes: nicht erreichbar")
        except Exception as e:
            logger.warning("Nextcloud Notes nicht verfügbar: %s", e)

    # Reminders
    try:
        from elder_berry.tools.reminder_store import ReminderStore
        from elder_berry.comms.reminder_scheduler import ReminderScheduler

        svc["reminder_store"] = ReminderStore()
        svc["reminder_scheduler"] = ReminderScheduler(
            store=svc["reminder_store"],
            send_reminder=lambda user_id, text: None,
        )
        logger.info("Reminders: aktiv (DB: %s)", svc["reminder_store"]._db_path)
    except Exception as e:
        logger.warning("Reminders nicht verfügbar: %s", e)

    # Nextcloud Files
    if secrets.get_or_none("nextcloud_url"):
        try:
            from elder_berry.tools.nextcloud_files import NextcloudFilesClient

            nc = NextcloudFilesClient(secret_store=secrets)
            if nc.is_available():
                svc["nextcloud_files"] = nc
                logger.info("Nextcloud Files: aktiv (%s)", secrets.get("nextcloud_url"))
            else:
                logger.warning("Nextcloud Files: nicht erreichbar")
        except Exception as e:
            logger.warning("Nextcloud Files nicht verfügbar: %s", e)

    # Stirling-PDF
    if secrets.get_or_none("stirling_pdf_url"):
        try:
            from elder_berry.tools.stirling_pdf import StirlingPDFClient

            spdf = StirlingPDFClient(secret_store=secrets)
            if spdf.is_available():
                svc["stirling_pdf"] = spdf
                logger.info("Stirling-PDF: aktiv (%s)", secrets.get("stirling_pdf_url"))
            else:
                logger.warning("Stirling-PDF: nicht erreichbar")
        except Exception as e:
            logger.warning("Stirling-PDF nicht verfügbar: %s", e)

    # Nextcloud CardDAV Sync
    if secrets.get_or_none("nextcloud_url"):
        try:
            from elder_berry.tools.carddav_sync import CardDAVSyncClient

            carddav = CardDAVSyncClient(secret_store=secrets)
            if carddav.is_available():
                svc["carddav_sync"] = carddav
                logger.info("CardDAV Sync: aktiv (%s)", secrets.get("nextcloud_url"))
            else:
                logger.debug("CardDAV Sync: nicht erreichbar")
        except ImportError:
            logger.debug("CardDAV: vobject nicht installiert")
        except Exception as e:
            logger.warning("CardDAV Sync nicht verfügbar: %s", e)

    # RoutePlanner (Google Maps Directions API)
    if secrets.get_or_none("google_maps_api_key"):
        try:
            from elder_berry.tools.route_planner import RoutePlanner

            svc["route_planner"] = RoutePlanner(
                api_key=secrets.get("google_maps_api_key"),
            )
            logger.info("RoutePlanner: aktiv (Google Maps Directions)")
        except Exception as e:
            logger.warning("RoutePlanner nicht verfügbar: %s", e)

        # Phase 92: Multi-Stop-Routing braucht denselben API-Key plus
        # einen persistenten Session-Store (TTL=1h, restart-fest).
        try:
            from elder_berry.tools.google_maps_route_planner import (
                GoogleMapsRoutePlanner,
            )
            from elder_berry.tools.route_session_store import RouteSessionStore

            svc["multi_stop_route_planner"] = GoogleMapsRoutePlanner(
                api_key=secrets.get("google_maps_api_key"),
            )
            svc["route_session_store"] = RouteSessionStore()
            logger.info(
                "Multi-Stop-Routing: aktiv (Google Directions + Places API)",
            )
        except Exception as e:
            logger.warning("Multi-Stop-Routing nicht verfügbar: %s", e)

    # Daily Briefing
    try:
        from elder_berry.comms.briefing_scheduler import BriefingScheduler

        svc["briefing_scheduler"] = BriefingScheduler(
            send_briefing=lambda text: None,
            calendar=svc.get("calendar"),
            weather=svc.get("weather"),
            reminder_store=svc.get("reminder_store"),
            task_client=svc.get("task_client"),
            email_client=svc.get("email_client"),
            contact_store=svc.get("contact_store"),
            default_user_id=default_user_id,
            briefing_hour=7,
            briefing_minute=30,
        )
        logger.info("Daily Briefing: aktiv (07:30)")
    except Exception as e:
        logger.warning("Daily Briefing nicht verfügbar: %s", e)

    return svc


def _init_context_and_tools(secrets, assistant, svc, tower_agent=None):
    """Initialisiert ContextEnricher, CalendarWatcher und Werkzeuge.

    Args:
        tower_agent: Optionaler TowerAgent. Wird in den ComputerUseController
            gereicht, damit Computer Use auch vom Linux-Server aus über den
            Tower laufen kann (Screenshot + Aktion via HTTP).
    """
    default_user_id = (
        (secrets.get_or_none("matrix_allowed_senders") or "").split(",")[0].strip()
    )
    tools = {}

    # SmartContextProvider (automatische Kontext-Anreicherung für LLM-Anfragen)
    try:
        from elder_berry.core.smart_context import SmartContextProvider

        tools["smart_context_provider"] = SmartContextProvider(
            calendar=svc.get("calendar"),
            task_client=svc.get("task_client"),
            nextcloud_notes=svc.get("nextcloud_notes"),
            contact_store=svc.get("contact_store"),
            reminder_store=svc.get("reminder_store"),
            weather_client=svc.get("weather"),
            default_user_id=default_user_id,
        )
        smart_sources = [
            s
            for s, v in [
                ("Calendar", svc.get("calendar")),
                ("Tasks", svc.get("task_client")),
                ("Notes", svc.get("nextcloud_notes")),
                ("Contacts", svc.get("contact_store")),
                ("Reminders", svc.get("reminder_store")),
                ("Weather", svc.get("weather")),
            ]
            if v
        ]
        logger.info(
            "SmartContextProvider: aktiv (Quellen: %s)",
            ", ".join(smart_sources) or "keine",
        )
    except Exception as e:
        logger.warning("SmartContextProvider nicht verfügbar: %s", e)

    # ContextEnricher
    try:
        from elder_berry.core.context_enricher import ContextEnricher

        tools["context_enricher"] = ContextEnricher(
            nextcloud_notes=svc.get("nextcloud_notes"),
            email_client=svc.get("email_client"),
            weather_client=svc.get("weather"),
            memory_store=assistant._memory,
            llm=assistant._llm,
            default_user_id=default_user_id,
        )
        sources = [
            s
            for s, v in [
                ("Notes", svc.get("nextcloud_notes")),
                ("Mail", svc.get("email_client")),
                ("Weather", svc.get("weather")),
            ]
            if v
        ]
        logger.info(
            "ContextEnricher: aktiv (Quellen: %s)", ", ".join(sources) or "keine"
        )
    except Exception as e:
        logger.warning("ContextEnricher nicht verfügbar: %s", e)

    # CalendarWatcher
    if svc.get("calendar"):
        try:
            from elder_berry.comms.calendar_watcher import CalendarWatcher

            tools["calendar_watcher"] = CalendarWatcher(
                send_alert=lambda text: None,
                calendar=svc["calendar"],
                reminder_minutes=[15, 5],
                poll_interval=300,
                context_enricher=tools.get("context_enricher"),
            )
            logger.info("CalendarWatcher: aktiv (Erinnerungen: 15min, 5min vor Termin)")
        except Exception as e:
            logger.warning("CalendarWatcher nicht verfügbar: %s", e)

    # DocumentReader
    from elder_berry.tools.document_reader import DocumentReader

    tools["document_reader"] = DocumentReader()

    # DocumentClassifier (benötigt AnthropicClient + DocumentReader + optional Stirling-PDF)
    try:
        from elder_berry.llm.anthropic_client import AnthropicClient
        from elder_berry.tools.document_classifier import DocumentClassifier

        anthropic_client = AnthropicClient()
        if anthropic_client.is_available():
            tools["document_classifier"] = DocumentClassifier(
                llm=anthropic_client,
                document_reader=tools["document_reader"],
                stirling_pdf=svc.get("stirling_pdf"),
            )
            logger.info("DocumentClassifier: aktiv (Anthropic + DocumentReader)")
        else:
            logger.warning(
                "DocumentClassifier: nicht verfügbar (Anthropic API Key fehlt)"
            )
    except Exception as e:
        logger.warning("DocumentClassifier nicht verfügbar: %s", e)

    # AudioRouter
    from elder_berry.core.audio_router import AudioRouter

    local_audio_available = _check_local_audio(assistant)
    tools["audio_router"] = AudioRouter(local_available=local_audio_available)
    logger.info(
        "AudioRouter: lokale Wiedergabe %s",
        "verfügbar" if local_audio_available else "nicht verfügbar",
    )

    # ComputerUseController
    if assistant._controller:
        try:
            from elder_berry.actions.computer_use import ComputerUseController
            from elder_berry.llm.anthropic_client import AnthropicClient

            cu_client = AnthropicClient()
            if cu_client.is_available():
                tools["computer_use"] = ComputerUseController(
                    anthropic_client=cu_client,
                    controller=assistant._controller,
                    tower_agent=tower_agent,
                )
                mode = "Tower-Remote" if tower_agent is not None else "lokal"
                logger.info(
                    "ComputerUseController: aktiv (Monitor %d, %s)",
                    tools["computer_use"].monitor_index,
                    mode,
                )
            else:
                logger.info("ComputerUseController: inaktiv (ANTHROPIC_API_KEY fehlt)")
        except Exception as e:
            logger.warning("ComputerUseController nicht verfügbar: %s", e)

    # WebFetcher
    try:
        from elder_berry.tools.web_fetcher import WebFetcher

        tools["web_fetcher"] = WebFetcher()
        logger.info("WebFetcher: aktiv")
    except Exception as e:
        logger.warning("WebFetcher nicht verfügbar: %s", e)

    # BraveSearchClient
    if secrets.get_or_none("brave_api_key"):
        try:
            from elder_berry.tools.brave_search_client import BraveSearchClient

            tools["search_client"] = BraveSearchClient(secret_store=secrets)
            logger.info("BraveSearchClient: aktiv")
        except Exception as e:
            logger.warning("BraveSearchClient nicht verfügbar: %s", e)
    else:
        logger.info("BraveSearchClient: inaktiv (brave_api_key fehlt)")

    # Vision-Client (Kamera)
    try:
        from elder_berry.llm.anthropic_client import AnthropicClient

        vision = AnthropicClient()
        if vision.is_available():
            tools["vision_client"] = vision
            logger.info("Vision-Client (Kamera): aktiv")
        else:
            logger.info("Vision-Client (Kamera): inaktiv (ANTHROPIC_API_KEY fehlt)")
    except Exception as e:
        logger.warning("Vision-Client nicht verfügbar: %s", e)

    return tools


def run_matrix(assistant, stt=None, avatar=None, audio_converter=None, robot=None):
    """Matrix-Modus: MatrixBridge startet bidirektionalen Chat über Matrix."""
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.comms.bridge import MatrixBridge
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.comms.alert_monitor import AlertMonitor, AlertConfig
    from elder_berry.system.info import SystemMonitor

    secrets = SecretStore()

    # --- 1. Matrix-Channel ---
    channel, user_id, room_id = _init_matrix_channel(secrets)

    # Default-User-ID (erster konfigurierter Sender)
    default_user_id = (
        (secrets.get_or_none("matrix_allowed_senders") or "").split(",")[0].strip()
    )

    # --- 2. Produktivitäts-Services ---
    svc = _init_productivity_services(secrets, default_user_id)

    # --- Tower-Agent (SSH-Tunnel zum Tower) ---
    # Vorgezogen: ComputerUseController in _init_context_and_tools bekommt ihn
    # als Remote-Fallback (Screenshot + Aktion via HTTP an den Tower).
    tower_agent = _init_tower_agent(secrets)

    # --- 3. Kontext & Werkzeuge ---
    tools = _init_context_and_tools(secrets, assistant, svc, tower_agent=tower_agent)

    # --- 4. RemoteCommandHandler ---
    remote = RemoteCommandHandler(
        system_monitor=SystemMonitor(),
        controller=assistant._controller,
        secret_store=secrets,
        project_root=_PROJECT_ROOT,
        avatar_renderer=avatar,
        calendar=svc.get("calendar"),
        email_client=svc.get("email_client"),
        gym_client=svc.get("gym_client"),
        weather=svc.get("weather"),
        reminder_store=svc.get("reminder_store"),
        briefing_scheduler=svc.get("briefing_scheduler"),
        document_reader=tools.get("document_reader"),
        audio_router=tools.get("audio_router"),
        computer_use=tools.get("computer_use"),
        search_client=tools.get("search_client"),
        web_fetcher=tools.get("web_fetcher"),
        fact_store=svc.get("fact_store"),
        contact_store=svc.get("contact_store"),
        task_client=svc.get("task_client"),
        robot_client=robot,
        anthropic_client=tools.get("vision_client"),
        nextcloud_files=svc.get("nextcloud_files"),
        nextcloud_notes=svc.get("nextcloud_notes"),
        stirling_pdf=svc.get("stirling_pdf"),
        document_classifier=tools.get("document_classifier"),
        carddav_sync=svc.get("carddav_sync"),
        route_planner=svc.get("route_planner"),
        multi_stop_route_planner=svc.get("multi_stop_route_planner"),
        route_session_store=svc.get("route_session_store"),
        default_user_id=default_user_id,
        tower_agent=tower_agent,
    )
    assistant._remote_commands = remote
    if tools.get("smart_context_provider"):
        assistant._smart_context = tools["smart_context_provider"]

    # Services für Healthcheck registrieren die nicht im RemoteCommandHandler leben
    remote._selfcheck.register_service("tts", assistant._tts)
    remote._selfcheck.register_service("stt", stt)
    remote._selfcheck.register_service("memory", assistant._memory)
    remote._selfcheck.register_service("avatar", avatar)
    remote._selfcheck.register_service("email_sender", svc.get("email_sender"))

    # --- 5. ClaudeAgent ---
    claude_agent = None
    anthropic_key = secrets.get_or_none("anthropic_api_key") or os.environ.get(
        "ANTHROPIC_API_KEY"
    )
    if anthropic_key:
        try:
            from elder_berry.comms.claude_agent import ClaudeAgent

            claude_agent = ClaudeAgent(
                api_key=anthropic_key, project_root=_PROJECT_ROOT
            )
            logger.info("ClaudeAgent: aktiv")
        except Exception as e:
            logger.warning("ClaudeAgent nicht verfügbar: %s", e)

    # --- 6. Monitoring & Security ---
    alert_monitor = AlertMonitor(
        send_alert=lambda text: None,
        config=AlertConfig(disk_threshold_percent=90.0),
    )

    # --- 6b. Phase 78: Plugin-Self-Suggestion ---
    from elder_berry.comms.proposal_notifier import ProposalNotifier
    from elder_berry.tools.intent_aggregator import ProposalIntentAggregator
    from elder_berry.tools.proposal_store import ProposalStore

    # --- 6c. Phase 80: ConversationListStore (Listen-Disambiguation) ---
    from elder_berry.tools.conversation_list_store import ConversationListStore

    conversation_lists = ConversationListStore()
    logger.info("Phase 80: ConversationListStore aktiv (TTL=1h)")

    proposal_store = ProposalStore()
    proposal_room_id = secrets.get_or_none("matrix_proposal_room_id") or room_id
    if not secrets.get_or_none("matrix_proposal_room_id"):
        logger.info(
            "Phase 78: matrix_proposal_room_id nicht gesetzt -- "
            "Plugin-Vorschlaege gehen in den Hauptraum (Fallback)."
        )
    proposal_notifier = ProposalNotifier(channel=channel, room_id=proposal_room_id)
    proposal_aggregator = ProposalIntentAggregator(
        store=proposal_store,
        notifier=proposal_notifier,
        secret_store=secrets,
    )
    assistant._proposal_store = proposal_store
    logger.info("Phase 78: ProposalStore + Aggregator aktiv")

    if stt:
        logger.info("Matrix-STT: Sprachnachrichten werden transkribiert")

    try:
        allowed_senders = load_allowed_senders(secrets)
        logger.info("Allowed-Senders: %d konfiguriert", len(allowed_senders))
    except ValueError as exc:
        # Phase 57.4: strikt fail-closed. Die frühere Design-Entscheidung
        # "leere Liste = keine Filterung" (Phase 32) wird bewusst
        # zurückgenommen – Single-User-Matrix-Bot ohne Sender-Whitelist
        # wäre eine offene Einladung an jeden Matrix-User im Raum.
        logger.error(
            "Allowed-Senders nicht konfiguriert – Matrix-Bridge verweigert "
            "den Start (Phase 57.4, strikt fail-closed).\n"
            "Grund: %s\n"
            "Setze mindestens einen Sender via Dashboard "
            "(http://localhost:8090) oder direkt im SecretStore:\n"
            "    matrix_allowed_senders = '@user:domain.com'\n"
            "Mehrere Sender: komma-getrennt.",
            exc,
        )
        sys.exit(1)

    # --- 7. Summarizer + Bridge ---
    from elder_berry.comms.chat_history import ChatMessage

    def summarizer(old_summary: str, evicted: list[ChatMessage]) -> str:
        evicted_text = "\n".join(
            f"{'User' if m.role == 'user' else 'Saleria'}: {m.text}" for m in evicted
        )
        prompt = (
            f"Bisherige Zusammenfassung: {old_summary or 'Keine'}\n\n"
            f"Neue Nachrichten:\n{evicted_text}\n\n"
            f"Aktualisiere die Zusammenfassung. Maximal 3 Sätze. "
            f"Behalte nur was für den weiteren Gesprächsverlauf relevant ist."
        )
        return assistant._llm.generate(prompt, system="Du fasst Gespräche zusammen.")

    bridge = MatrixBridge(
        channel=channel,
        assistant=assistant,
        audio_converter=audio_converter,
        remote_commands=remote,
        claude_agent=claude_agent,
        alert_monitor=alert_monitor,
        alert_room_id=room_id,
        allowed_senders=allowed_senders,
        stt=stt,
        reminder_scheduler=svc.get("reminder_scheduler"),
        briefing_scheduler=svc.get("briefing_scheduler"),
        calendar_watcher=tools.get("calendar_watcher"),
        document_reader=tools.get("document_reader"),
        audio_router=tools.get("audio_router"),
        summarizer=summarizer,
        email_sender=svc.get("email_sender"),
        email_client=svc.get("email_client"),
        nextcloud_files=svc.get("nextcloud_files"),
        proposal_aggregator=proposal_aggregator,
        conversation_lists=conversation_lists,
    )

    # --- 8. Dashboard + Start ---
    try:
        from elder_berry.web.settings_dashboard import SettingsDashboard

        # Phase 52.1a: Loopback-Default + Token-Schutz
        settings_bind = os.environ.get("ELDER_BERRY_SETTINGS_BIND", "127.0.0.1")
        # Phase 58: Login-Layer aktiv (überlebt VPN-Leak, schützt auch GET).
        # TTL aus Setting "dashboard_session_hours" lesen, Default 12 h.
        try:
            ttl_raw = secrets.get_or_none("dashboard_session_hours")
            session_hours = int(ttl_raw) if ttl_raw else 12
        except (ValueError, TypeError):
            session_hours = 12
        dashboard = SettingsDashboard(
            audio_router=tools.get("audio_router"),
            computer_use=tools.get("computer_use"),
            secret_store=secrets,
            audio_pipeline=bridge.audio_pipeline,
            tower_agent=tower_agent,
            host=settings_bind,
            port=8090,
            require_settings_token=True,
            require_dashboard_login=True,
            dashboard_session_hours=session_hours,
            proposal_store=proposal_store,
        )
        # Gespeicherten STT-Timeout laden und auf Pipeline anwenden
        saved_timeout = dashboard._get_stt_timeout()
        bridge.audio_pipeline.stt_timeout = saved_timeout
        dashboard.start()
    except Exception as e:
        logger.warning("Settings-Dashboard nicht gestartet: %s", e)

    # Phase 52.2: Startup-Summary
    summary = _build_startup_summary(
        assistant=assistant,
        stt=stt,
        robot=robot,
        secrets=secrets,
        svc=svc,
        tools=tools,
        tower_agent=tower_agent,
        matrix_user_id=user_id,
        matrix_room_id=room_id,
        allowed_senders=allowed_senders,
        claude_agent=claude_agent,
    )
    print()
    print(summary.render())
    print()
    _maybe_send_summary_to_matrix(summary, channel, room_id)

    logger.info("Matrix-Bridge startet – Saleria ist online")
    print("─── Saleria Matrix-Modus ───")
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
# Phase 52.2 – Startup Summary Helpers
# ---------------------------------------------------------------------------


def _build_startup_summary(
    *,
    assistant,
    stt,
    robot,
    secrets,
    svc,
    tools,
    tower_agent,
    matrix_user_id,
    matrix_room_id,
    allowed_senders,
    claude_agent,
):
    """Sammelt Komponenten-Status nach dem Init und gibt eine StartupSummary
    zurück. Reine Introspektion – keine Seiteneffekte."""
    from elder_berry.core.startup_summary import StartupSummary

    summary = StartupSummary()

    # LLM
    llm = getattr(assistant, "_llm", None)
    if llm is not None:
        backend = type(llm).__name__
        summary.add("LLM", "ok", backend)
    else:
        summary.add("LLM", "fail", "kein Backend")

    # TTS / STT / Avatar / Memory
    if getattr(assistant, "_tts", None) is not None:
        summary.add("TTS", "ok", type(assistant._tts).__name__)
    else:
        summary.add("TTS", "warn", "deaktiviert")
    summary.add(
        "STT", "ok" if stt else "warn", type(stt).__name__ if stt else "deaktiviert"
    )
    summary.add(
        "Avatar",
        "ok" if getattr(assistant, "_avatar", None) else "warn",
        type(assistant._avatar).__name__ if assistant._avatar else "kein Renderer",
    )
    summary.add(
        "Memory",
        "ok" if getattr(assistant, "_memory", None) else "warn",
        type(assistant._memory).__name__ if assistant._memory else "deaktiviert",
    )

    # Matrix
    summary.add("Matrix", "ok", f"{matrix_user_id} → {matrix_room_id}")
    summary.add(
        "Allowed-Senders",
        "ok" if allowed_senders else "warn",
        f"{len(allowed_senders)} Sender" if allowed_senders else "alle akzeptiert",
    )

    # Tower / RPi5
    summary.add(
        "Tower",
        "ok" if tower_agent else "warn",
        "verbunden" if tower_agent else "nicht konfiguriert",
    )
    summary.add(
        "RPi5 (Robot)",
        "ok" if robot else "warn",
        "verbunden" if robot else "nicht erreichbar",
    )

    # Optionale Services aus svc/tools
    _add_service(summary, "Kalender", svc.get("calendar"))
    _add_service(summary, "E-Mail (IMAP)", svc.get("email_client"))
    _add_service(summary, "E-Mail (SMTP)", svc.get("email_sender"))
    _add_service(summary, "Wetter", svc.get("weather"))
    _add_service(summary, "Fakten (FactStore)", svc.get("fact_store"))
    _add_service(summary, "Notizen (Nextcloud)", svc.get("nextcloud_notes"))
    _add_service(summary, "Kontakte", svc.get("contact_store"))
    _add_service(summary, "Aufgaben", svc.get("task_client"))
    _add_service(summary, "Erinnerungen", svc.get("reminder_store"))
    _add_service(summary, "Nextcloud Files", svc.get("nextcloud_files"))
    _add_service(summary, "Stirling-PDF", svc.get("stirling_pdf"))
    _add_service(summary, "Berry-Gym", svc.get("gym_client"))
    _add_service(summary, "Brave Search", tools.get("search_client"))
    _add_service(summary, "ClaudeAgent", claude_agent)

    return summary


def _add_service(summary, label: str, instance) -> None:
    if instance is None:
        summary.add(label, "warn", "nicht konfiguriert")
    else:
        summary.add(label, "ok", type(instance).__name__)


def _maybe_send_summary_to_matrix(summary, channel, room_id) -> None:
    """Versucht best-effort, die Summary als Matrix-Nachricht zu schicken.

    Fehler werden geloggt, aber nicht propagiert – ein scheiternder
    Send darf den Startup nicht blockieren.

    Hinweis: ``MatrixChannel.send_text`` ist async; vor ``bridge.start()``
    laeuft noch kein Event-Loop, daher ``asyncio.run`` fuer den
    one-shot Send (vermeidet ``RuntimeWarning: coroutine ... was never
    awaited`` im Bestand-Code).
    """
    import asyncio
    import inspect

    if channel is None or not room_id:
        return
    try:
        message = summary.to_matrix_message()
        send = getattr(channel, "send_text", None) or getattr(channel, "send", None)
        if send is None:
            logger.debug(
                "Channel %s hat keine send-Methode – Summary nicht gesendet",
                type(channel).__name__,
            )
            return
        if inspect.iscoroutinefunction(send):
            asyncio.run(send(room_id, message))
        else:
            send(room_id, message)
    except Exception as exc:
        logger.warning("Startup-Summary an Matrix senden fehlgeschlagen: %s", exc)


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
    print(f"  Home:  {_PROJECT_ROOT}")
    print("═" * 50)

    # Agent-Modus: nur TowerServer starten, kein LLM/Bot nötig
    if args.mode == "agent":
        run_agent()
        return

    # Secrets aus SecretStore in Env laden (für LLMRouter etc.)
    load_secrets_to_env()

    # First-Run-Check: wenn kein Matrix-Token → Setup-Wizard starten
    if not _check_first_run():
        logger.info("Erste Ausführung erkannt – starte Setup-Wizard")
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore()

        # Phase 57.1: Bind-Adresse bestimmen
        setup_bind = os.environ.get("ELDER_BERRY_SETUP_BIND", "127.0.0.1")
        compat_mode = False
        migration_marker = (
            _PROJECT_ROOT.parent / ".elder-berry" / ".phase57_migration_done"
        )
        home_env = os.environ.get("ELDER_BERRY_HOME")
        if home_env:
            migration_marker = Path(home_env) / ".phase57_migration_done"

        # Phase 57.1a: Grace-Period – einmaliger LAN-Modus beim Upgrade
        setup_done = store.get_or_none("setup_wizard_completed") == "true"
        if (
            not migration_marker.exists()
            and not setup_done
            and setup_bind == "127.0.0.1"
        ):
            compat_mode = True
            setup_bind = "0.0.0.0"
            logger.warning(
                "Phase 57.1 Upgrade: Setup-Wizard läuft EINMALIG auf "
                "0.0.0.0:8090 (LAN-Kompatibilitätsmodus). Ab dem nächsten "
                "Start gilt 127.0.0.1. Dauerhaft LAN? Setze "
                "ELDER_BERRY_SETUP_BIND=0.0.0.0",
            )
        elif setup_bind not in ("127.0.0.1", "localhost", "::1"):
            logger.warning(
                "Setup-Wizard lauscht auf %s:8090 – Secrets werden im "
                "Klartext übertragen. Nur im vertrauenswürdigen Netz nutzen.",
                setup_bind,
            )

        print("\n  Keine Konfiguration gefunden – Setup-Wizard wird gestartet...")
        if compat_mode:
            print("  LAN-Kompatibilitätsmodus: Wizard auf 0.0.0.0 (einmalig)")
        print("  Öffne http://localhost:8090/setup im Browser\n")
        import webbrowser
        from threading import Timer

        Timer(1.5, webbrowser.open, args=["http://localhost:8090/setup"]).start()
        from elder_berry.web.setup_wizard import run_setup_wizard

        run_setup_wizard(
            store,
            port=8090,
            bind=setup_bind,
            compat_mode=compat_mode,
            migration_marker=migration_marker,
        )
        # Nach dem Wizard Secrets neu laden
        load_secrets_to_env()

    llm = init_llm()
    db = init_actions_db()
    controller = init_controller()
    character = init_character()
    tts = init_tts(args.no_tts, character=character)
    memory = init_memory(args.no_memory)
    avatar = init_avatar(args.no_avatar)
    monitor = init_system_monitor()
    audio_converter = init_audio_converter()
    stt = init_stt(args.mode, args.whisper_model)

    # RobotClient (optional – verbindet Tower mit RPi5-Display)
    robot = None
    try:
        from elder_berry.core.secret_store import SecretStore
        from elder_berry.robot.client import RobotClient

        _secrets = SecretStore()
        robot_host = _secrets.get_or_none("robot_host")
        if robot_host:
            # Phase 59: Robot-Token analog zu Tower-Token – erst Env, dann Store.
            robot_token = os.environ.get(
                "ELDER_BERRY_ROBOT_TOKEN"
            ) or _secrets.get_or_none("robot_auth_token")
            if not robot_token:
                logger.warning(
                    "RobotClient: kein Robot-Token konfiguriert – Requests "
                    "werden mit 401 abgelehnt, falls der RobotServer einen "
                    "Token erwartet. Setze robot_auth_token im SecretStore "
                    "oder ELDER_BERRY_ROBOT_TOKEN als Env.",
                )
            robot = RobotClient(base_url=robot_host, robot_token=robot_token)
            if robot.is_online():
                logger.info("RobotClient: verbunden mit %s", robot_host)
            else:
                logger.warning("RobotClient: %s nicht erreichbar", robot_host)
                robot = None
    except Exception as e:
        logger.debug("RobotClient nicht verfügbar: %s", e)

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
        robot=robot,
    )

    print()
    if args.mode == "terminal":
        run_terminal(assistant)
    elif args.mode == "voice":
        run_voice(assistant, stt)
    else:
        run_matrix(
            assistant,
            stt=stt,
            avatar=avatar,
            audio_converter=audio_converter,
            robot=robot,
        )


_LOCK_FILE = _PROJECT_ROOT / ".saleria.lock"
_lock_fh = None


def _acquire_instance_lock() -> None:
    """Stellt sicher, dass nur eine Instanz von Saleria gleichzeitig läuft.

    Nutzt eine exklusive Dateisperre auf .saleria.lock.
    Unter Windows: msvcrt.locking (OS gibt Lock bei Crash automatisch frei).
    Unter Linux: fcntl.flock.

    Bei einem Restart (alter Prozess beendet sich gerade) kann der Lock
    kurz belegt sein. Daher bis zu 5 Versuche mit 1s Pause.
    """
    import time

    global _lock_fh
    max_attempts = 5

    for attempt in range(max_attempts):
        _lock_fh = open(_LOCK_FILE, "w")
        try:
            if platform.system() == "Windows":
                import msvcrt

                msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Lock erfolgreich erworben
            break
        except (OSError, IOError):
            _lock_fh.close()
            _lock_fh = None
            if attempt < max_attempts - 1:
                logger.info(
                    "Lock belegt, warte 1s (Versuch %d/%d)...",
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(1)
                continue
            # Alle Versuche aufgebraucht
            print("FEHLER: Saleria läuft bereits! Nur eine Instanz erlaubt.")
            print(f"  Lock-Datei: {_LOCK_FILE}")
            print("  Falls kein Prozess läuft: Datei manuell löschen.")
            sys.exit(1)

    _lock_fh.write(str(os.getpid()))
    _lock_fh.flush()
    atexit.register(_release_instance_lock)
    logger.info("Instanz-Lock erworben (PID %d)", os.getpid())


def _release_instance_lock() -> None:
    """Gibt den Instanz-Lock frei.

    Auf Windows: explizit msvcrt.locking(LK_UNLCK) vor close(),
    da close() allein den Lock nicht zuverlässig freigibt.
    """
    global _lock_fh
    if _lock_fh is None:
        return
    try:
        if platform.system() == "Windows":
            import msvcrt

            _lock_fh.seek(0)
            msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass
    try:
        _lock_fh.close()
    except Exception:
        pass
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    _lock_fh = None


def _sigint_handler(signum, frame):
    """Ctrl+C / SIGBREAK: Lock freigeben und sofort beenden.

    os._exit() statt sys.exit(): erzwingt sofortiges Beenden auch wenn
    asyncio-Loops oder Threads hängen (häufig auf Windows in VS Code).
    """
    _release_instance_lock()
    os._exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _sigint_handler)
    # SIGBREAK: Windows-spezifisch, wird von VS Code PowerShell gesendet
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _sigint_handler)
    _acquire_instance_lock()
    main()
