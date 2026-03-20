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
import os
import platform
import signal
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
# Secrets → Env-Variablen (damit LLMRouter + andere Komponenten sie finden)
# ---------------------------------------------------------------------------

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


def init_actions_db():
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


def init_character():
    from elder_berry.character.saleria import SaleriaEngine
    engine = SaleriaEngine()
    logger.info("Charakter: %s", engine._personality.name)
    return engine


def init_tts(no_tts: bool, character=None):
    """TTS-Engine – bevorzugt CoquiTTS mit Voice-Map, Fallback pyttsx3."""
    if no_tts:
        logger.info("TTS: deaktiviert")
        return None

    try:
        from elder_berry.tts.coqui_engine import CoquiTTSEngine
        from elder_berry.character.base import Emotion

        # Voice-Map aus Character aufbauen
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


def _check_local_audio(assistant) -> bool:
    """Prüft ob lokale Audio-Wiedergabe möglich ist (sounddevice oder AgentClient)."""
    # AgentClient am Assistant?
    agent = getattr(assistant, "_agent", None)
    if agent is not None:
        try:
            if agent.is_online():
                return True
        except Exception:
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
        logger.debug("AudioConverter: pydub nicht installiert")
        return None


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


def run_matrix(assistant, stt=None, avatar=None, audio_converter=None):
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
    room_id = secrets.get_or_none("matrix_room_id") or os.environ.get("MATRIX_ROOM_ID")

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

    allowed_rooms = [room_id] if room_id else None
    channel = MatrixChannel(
        homeserver=homeserver, user_id=user_id, access_token=token,
        allowed_rooms=allowed_rooms,
    )

    # Google Calendar (optional)
    calendar = None
    try:
        from elder_berry.tools.google_calendar import GoogleCalendarClient
        cal = GoogleCalendarClient(secret_store=secrets)
        if cal.is_available():
            calendar = cal
            logger.info("Google Calendar: aktiv")
        else:
            logger.debug("Google Calendar: keine Tokens konfiguriert")
    except ImportError:
        logger.debug("Google Calendar: google-api-python-client nicht installiert")
    except Exception as e:
        logger.warning("Google Calendar nicht verfügbar: %s", e)

    # Email / IMAP (optional)
    email_client = None
    if secrets.get_or_none("email_imap_host"):
        try:
            from elder_berry.tools.email_client import IMAPEmailClient
            email_client = IMAPEmailClient.from_secret_store(secrets)
            logger.info("Email: IMAP %s", secrets.get("email_imap_host"))
        except Exception as e:
            logger.warning("Email nicht verfügbar: %s", e)

    # Berry-Gym (optional)
    gym_client = None
    if secrets.get_or_none("berry_gym_api_token"):
        try:
            from elder_berry.tools.gym_data import GymDataClient
            gym_client = GymDataClient(secret_store=secrets)
            logger.info("Berry-Gym: aktiv (%s)", gym_client._base_url)
        except Exception as e:
            logger.warning("Berry-Gym nicht verfügbar: %s", e)

    # Weather (optional)
    weather = None
    try:
        from elder_berry.tools.weather_client import WeatherClient
        weather = WeatherClient(secret_store=secrets)
        logger.info("Weather: aktiv")
    except Exception as e:
        logger.warning("Weather nicht verfügbar: %s", e)

    # Reminders (optional)
    reminder_store = None
    reminder_scheduler = None
    try:
        from elder_berry.tools.reminder_store import ReminderStore
        from elder_berry.comms.reminder_scheduler import ReminderScheduler
        reminder_store = ReminderStore()
        # Scheduler mit Platzhalter-Callback (Bridge setzt den echten)
        reminder_scheduler = ReminderScheduler(
            store=reminder_store,
            send_reminder=lambda user_id, text: None,
        )
        logger.info("Reminders: aktiv (DB: %s)", reminder_store._db_path)
    except Exception as e:
        logger.warning("Reminders nicht verfügbar: %s", e)

    # Daily Briefing (optional)
    briefing_scheduler = None
    try:
        from elder_berry.comms.briefing_scheduler import BriefingScheduler
        briefing_scheduler = BriefingScheduler(
            send_briefing=lambda text: None,  # Bridge setzt den echten Callback
            calendar=calendar,
            weather=weather,
            reminder_store=reminder_store,
            briefing_hour=7,
            briefing_minute=30,
        )
        logger.info("Daily Briefing: aktiv (07:30)")
    except Exception as e:
        logger.warning("Daily Briefing nicht verfügbar: %s", e)

    # NoteStore – Notizen & Wissensdatenbank (optional)
    note_store = None
    try:
        from elder_berry.tools.note_store import NoteStore
        note_store = NoteStore()
        logger.info("NoteStore: aktiv (DB: %s)", note_store._db_path)
    except Exception as e:
        logger.warning("NoteStore nicht verfügbar: %s", e)

    # ContextEnricher – Kontext-Anreicherung für CalendarWatcher (Phase 21)
    context_enricher = None
    try:
        from elder_berry.core.context_enricher import ContextEnricher
        context_enricher = ContextEnricher(
            note_store=note_store,
            email_client=email_client,
            weather_client=weather,
            memory_store=assistant._memory,
            llm=assistant._llm,
            default_user_id=(
                secrets.get_or_none("matrix_allowed_senders") or ""
            ).split(",")[0].strip(),
        )
        sources = [s for s, v in [
            ("Notes", note_store), ("Mail", email_client),
            ("Weather", weather),
        ] if v]
        logger.info("ContextEnricher: aktiv (Quellen: %s)", ", ".join(sources) or "keine")
    except Exception as e:
        logger.warning("ContextEnricher nicht verfügbar: %s", e)

    # CalendarWatcher – proaktive Kalender-Erinnerungen (optional)
    calendar_watcher = None
    if calendar:
        try:
            from elder_berry.comms.calendar_watcher import CalendarWatcher
            calendar_watcher = CalendarWatcher(
                send_alert=lambda text: None,  # Bridge setzt den echten Callback
                calendar=calendar,
                reminder_minutes=[15, 5],
                poll_interval=300,
                context_enricher=context_enricher,
            )
            logger.info("CalendarWatcher: aktiv (Erinnerungen: 15min, 5min vor Termin)")
        except Exception as e:
            logger.warning("CalendarWatcher nicht verfügbar: %s", e)

    # DocumentReader (Phase 11)
    from elder_berry.tools.document_reader import DocumentReader
    document_reader = DocumentReader()

    # AudioRouter (Phase 12) – prüfe ob lokale Wiedergabe möglich
    from elder_berry.core.audio_router import AudioRouter
    local_audio_available = _check_local_audio(assistant)
    audio_router = AudioRouter(local_available=local_audio_available)
    logger.info(
        "AudioRouter: lokale Wiedergabe %s",
        "verfügbar" if local_audio_available else "nicht verfügbar",
    )

    # ComputerUseController (Phase 13) – Vision-gesteuerte PC-Bedienung
    computer_use = None
    if assistant._controller:
        try:
            from elder_berry.actions.computer_use import ComputerUseController
            from elder_berry.llm.anthropic_client import AnthropicClient
            cu_client = AnthropicClient()
            if cu_client.is_available():
                computer_use = ComputerUseController(
                    anthropic_client=cu_client,
                    controller=assistant._controller,
                )
                logger.info("ComputerUseController: aktiv (Monitor %d)", computer_use.monitor_index)
            else:
                logger.info("ComputerUseController: inaktiv (ANTHROPIC_API_KEY fehlt)")
        except Exception as e:
            logger.warning("ComputerUseController nicht verfügbar: %s", e)

    # BraveSearchClient (Phase 14) – Web-Suche
    search_client = None
    if secrets.get_or_none("brave_api_key"):
        try:
            from elder_berry.tools.brave_search_client import BraveSearchClient
            search_client = BraveSearchClient(secret_store=secrets)
            logger.info("BraveSearchClient: aktiv")
        except Exception as e:
            logger.warning("BraveSearchClient nicht verfügbar: %s", e)
    else:
        logger.info("BraveSearchClient: inaktiv (brave_api_key fehlt)")

    # RemoteCommandHandler – alle Dependencies übergeben
    remote = RemoteCommandHandler(
        system_monitor=SystemMonitor(),
        controller=assistant._controller,
        secret_store=secrets,
        project_root=_PROJECT_ROOT,
        avatar_renderer=avatar,
        calendar=calendar,
        email_client=email_client,
        gym_client=gym_client,
        weather=weather,
        reminder_store=reminder_store,
        briefing_scheduler=briefing_scheduler,
        document_reader=document_reader,
        audio_router=audio_router,
        computer_use=computer_use,
        search_client=search_client,
        note_store=note_store,
    )

    # Assistant: dynamischer Command-Prompt aus Handler-Definitionen
    assistant._remote_commands = remote

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
    alert_monitor = AlertMonitor(send_alert=lambda text: None, config=alert_config)

    if stt:
        logger.info("Matrix-STT: Sprachnachrichten werden transkribiert")

    log_dir = _PROJECT_ROOT / "logs"

    # --- Allowed Senders: Matrix-User-IDs aus SecretStore laden ---
    allowed_senders = None
    raw_senders = secrets.get_or_none("matrix_allowed_senders")
    if raw_senders:
        sender_list = [s.strip() for s in raw_senders.split(",") if s.strip()]
        if sender_list:
            allowed_senders = frozenset(sender_list)
            logger.info("Allowed-Senders: %d konfiguriert", len(allowed_senders))
    if not allowed_senders:
        logger.warning(
            "Allowed-Senders nicht konfiguriert – alle Absender werden akzeptiert. "
            "Setze via Dashboard (http://localhost:8090) oder SecretStore: "
            "matrix_allowed_senders = '@user:domain.com'"
        )

    # Summarizer für ChatHistory Rolling Summary (Phase 23)
    from elder_berry.comms.chat_history import ChatMessage

    def summarizer(old_summary: str, evicted: list[ChatMessage]) -> str:
        evicted_text = "\n".join(
            f"{'User' if m.role == 'user' else 'Saleria'}: {m.text}"
            for m in evicted
        )
        prompt = (
            f"Bisherige Zusammenfassung: {old_summary or 'Keine'}\n\n"
            f"Neue Nachrichten:\n{evicted_text}\n\n"
            f"Aktualisiere die Zusammenfassung. Maximal 3 Sätze. "
            f"Behalte nur was für den weiteren Gesprächsverlauf relevant ist."
        )
        return llm.generate(prompt, system="Du fasst Gespräche zusammen.")

    bridge = MatrixBridge(
        channel=channel,
        assistant=assistant,
        audio_converter=audio_converter,
        remote_commands=remote,
        claude_agent=claude_agent,
        alert_monitor=alert_monitor,
        alert_room_id=room_id,
        error_log_dir=log_dir,
        allowed_senders=allowed_senders,
        stt=stt,
        reminder_scheduler=reminder_scheduler,
        briefing_scheduler=briefing_scheduler,
        calendar_watcher=calendar_watcher,
        document_reader=document_reader,
        audio_router=audio_router,
        summarizer=summarizer,
    )

    # Settings-Dashboard (Web-UI für Audio-Routing + Monitor-Auswahl)
    try:
        from elder_berry.web.audio_dashboard import AudioDashboard
        dashboard = AudioDashboard(
            audio_router=audio_router,
            computer_use=computer_use,
            secret_store=secrets,
            port=8090,
        )
        dashboard.start()
    except Exception as e:
        logger.warning("Settings-Dashboard nicht gestartet: %s", e)

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

    # Secrets aus SecretStore in Env laden (für LLMRouter etc.)
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
            robot = RobotClient(base_url=robot_host)
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
        run_matrix(assistant, stt=stt, avatar=avatar, audio_converter=audio_converter)


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
                    attempt + 1, max_attempts,
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
