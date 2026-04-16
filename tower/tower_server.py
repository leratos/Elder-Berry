"""TowerServer – FastAPI-Service für Tower-Dienste.

Exponiert TTS, STT, PC-Steuerung und Screenshot über HTTP.
Läuft auf dem Tower-PC und wird vom Server via SSH-Tunnel erreicht.

Phase 57.3: Alle Endpoints sind mit ``X-Saleria-Tower-Token`` geschützt.
Token-Quelle (Priorität): Env ``ELDER_BERRY_TOWER_TOKEN`` → SecretStore
``tower_auth_token``. Ohne Token verweigert der Server den Start.

Starten:
    ELDER_BERRY_TOWER_TOKEN=<token> uvicorn tower.tower_server:app --port 8090
"""
from __future__ import annotations

import io
import logging
import os
import secrets as _secrets
import socket
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class TTSRequest(BaseModel):
    """TTS-Anfrage: Text + optionale Emotion."""

    text: str
    emotion: str | None = None


class ActionRequest(BaseModel):
    """PC-Steuerungs-Anfrage: Aktionsname + Parameter."""

    action: str
    params: dict = {}


# ---------------------------------------------------------------------------
# Engine-Holder – Lazy-Init der schweren Komponenten
# ---------------------------------------------------------------------------


class _Engines:
    """Hält Referenzen auf die Tower-Engines (lazy-initialisiert)."""

    def __init__(self) -> None:
        self.tts = None  # CoquiTTSEngine | None
        self.stt = None  # FasterWhisperEngine | None
        self.actions = None  # WindowsActionController | None
        self._monitor_index = 1  # Aktiver Monitor für Computer Use / Screenshot

    def init_tts(self) -> None:
        """Initialisiert CoquiTTSEngine mit Default-Konfiguration."""
        from elder_berry.tts.coqui_engine import CoquiTTSEngine

        voice_dir = Path("data/voices")
        voice_map = {}
        if voice_dir.exists():
            for wav in voice_dir.glob("*.wav"):
                voice_map[wav.stem] = wav
            logger.info("TTS Voice-Map: %s", list(voice_map.keys()))

        default_wav = voice_map.get("neutral") or (
            next(iter(voice_map.values())) if voice_map else None
        )

        self.tts = CoquiTTSEngine(
            voice_map=voice_map,
            default_speaker_wav=default_wav,
        )
        self.tts.load()
        logger.info("CoquiTTSEngine geladen")

    def init_stt(self) -> None:
        """Initialisiert FasterWhisperEngine."""
        from elder_berry.stt.faster_whisper_engine import FasterWhisperEngine

        self.stt = FasterWhisperEngine(model_size="medium", language="de")
        self.stt.load()
        logger.info("FasterWhisperEngine geladen")

    def init_actions(self) -> None:
        """Initialisiert WindowsActionController."""
        from elder_berry.actions.windows_controller import WindowsActionController

        self.actions = WindowsActionController()
        logger.info("WindowsActionController initialisiert")

    def shutdown(self) -> None:
        """Entlädt alle Engines und gibt Ressourcen frei."""
        if self.tts is not None:
            self.tts.unload()
            self.tts = None
            logger.info("CoquiTTSEngine entladen")
        if self.stt is not None:
            self.stt.unload()
            self.stt = None
            logger.info("FasterWhisperEngine entladen")
        self.actions = None


engines = _Engines()


# ---------------------------------------------------------------------------
# Phase 57.3: Tower-Token-Middleware
# ---------------------------------------------------------------------------


class TowerTokenMiddleware(BaseHTTPMiddleware):
    """Schützt alle Endpoints mit ``X-Saleria-Tower-Token``."""

    HEADER_NAME = "X-Saleria-Tower-Token"

    async def dispatch(self, request, call_next):
        expected = getattr(request.app.state, "tower_token", None)
        if not expected:
            return JSONResponse(
                {"error": "Tower-Token nicht konfiguriert (Serverfehler)."},
                status_code=500,
            )
        token = request.headers.get(self.HEADER_NAME)
        if not token or not _secrets.compare_digest(token, expected):
            return JSONResponse(
                {
                    "error": "Tower-Token erforderlich oder ungültig.",
                    "header": self.HEADER_NAME,
                },
                status_code=401,
            )
        return await call_next(request)


def _load_tower_token() -> str:
    """Lädt den Tower-Token aus Env oder SecretStore.

    Raises ``RuntimeError`` wenn weder Env noch Store einen Token liefern.
    """
    token = os.environ.get("ELDER_BERRY_TOWER_TOKEN")
    if token:
        logger.info("Tower-Token aus Env-Variable geladen")
        return token

    try:
        from elder_berry.core.secret_store import SecretStore
        store = SecretStore()
        token = store.get_or_none("tower_auth_token")
        if token:
            logger.info("Tower-Token aus SecretStore geladen")
            return token
    except Exception as exc:
        logger.debug("SecretStore nicht verfügbar: %s", exc)

    raise RuntimeError(
        "Kein Tower-Token konfiguriert. "
        "Setze ELDER_BERRY_TOWER_TOKEN oder lege 'tower_auth_token' "
        "im SecretStore an (Settings-Dashboard)."
    )


# ---------------------------------------------------------------------------
# Action-Dispatcher – mappt Aktionsnamen auf Controller-Methoden
# ---------------------------------------------------------------------------

# Erlaubte Aktionen und ihre Parameter-Signaturen.
# Key = Aktionsname vom Client, Value = (Methodenname, [erwartete Params])
_ACTION_MAP: dict[str, tuple[str, list[str]]] = {
    "press_key": ("press_key", ["key"]),
    "type_text": ("type_text", ["text"]),
    "hotkey": ("hotkey", ["keys"]),
    "move_mouse": ("move_mouse", ["x", "y"]),
    "click": ("click", []),
    "list_windows": ("list_windows", []),
    "focus_window": ("focus_window", ["title"]),
    "minimize_window": ("minimize_window", ["title"]),
    "maximize_window": ("maximize_window", ["title"]),
    "get_volume": ("get_volume", []),
    "set_volume": ("set_volume", ["level"]),
    "mute": ("mute", []),
}


def _dispatch_action(
    controller,
    action: str,
    params: dict,
) -> dict:
    """Ruft die passende Controller-Methode auf.

    Returns:
        Ergebnis-Dict mit ``success`` und ``result``.

    Raises:
        HTTPException: Bei unbekannter Aktion oder fehlenden Parametern.
    """
    if action not in _ACTION_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannte Aktion: {action}. "
                   f"Erlaubt: {sorted(_ACTION_MAP.keys())}",
        )

    method_name, required_params = _ACTION_MAP[action]
    method = getattr(controller, method_name)

    # hotkey erwartet *keys (varargs)
    if action == "hotkey":
        keys = params.get("keys", [])
        if not keys:
            raise HTTPException(status_code=422, detail="hotkey: 'keys' Liste fehlt")
        result = method(*keys)
    else:
        # Fehlende Pflichtparameter prüfen
        missing = [p for p in required_params if p not in params]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"{action}: fehlende Parameter: {missing}",
            )
        # Nur erwartete + optionale Parameter übergeben
        result = method(**params)

    # Ergebnis normalisieren
    if result is None:
        return {"success": True}
    if isinstance(result, bool):
        return {"success": result}
    if isinstance(result, (int, float)):
        return {"success": True, "result": result}
    if isinstance(result, list):
        # list_windows → Liste von WindowInfo
        return {
            "success": True,
            "result": [
                {"title": w.title, "handle": w.handle}
                if hasattr(w, "title") else str(w)
                for w in result
            ],
        }
    return {"success": True, "result": result}


# ---------------------------------------------------------------------------
# FastAPI Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: Token prüfen, Engines laden. Shutdown: Engines entladen."""
    # Phase 57.3: Token laden – ohne Token kein Start
    try:
        app.state.tower_token = _load_tower_token()
    except RuntimeError as exc:
        logger.error("%s", exc)
        import sys
        sys.exit(1)

    logger.info("TowerServer startet auf %s", socket.gethostname())

    # Engines initialisieren – Fehler einzeln fangen damit
    # die anderen trotzdem starten
    for name, init_fn in [
        ("TTS", engines.init_tts),
        ("STT", engines.init_stt),
        ("Actions", engines.init_actions),
    ]:
        try:
            init_fn()
        except Exception:
            logger.exception("Fehler beim Initialisieren von %s", name)

    yield

    logger.info("TowerServer fährt herunter")
    engines.shutdown()


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="Elder-Berry Tower Server", lifespan=lifespan)
app.add_middleware(TowerTokenMiddleware)


@app.get("/status")
async def status():
    """Heartbeat-Endpoint – prüft ob der Tower erreichbar ist."""
    return {
        "online": True,
        "hostname": socket.gethostname(),
        "tts_available": engines.tts is not None,
        "stt_available": engines.stt is not None,
        "actions_available": engines.actions is not None,
    }


@app.get("/system")
async def system_info():
    """Systeminfo vom Tower (CPU, RAM, GPU, Top-Prozesse)."""
    try:
        from elder_berry.system.info import SystemMonitor
        monitor = SystemMonitor()
        info = monitor.get_info(top_processes=5)
        return {
            "platform": info.platform,
            "cpu": {
                "usage_percent": info.cpu.usage_percent,
                "core_count": info.cpu.core_count,
                "thread_count": info.cpu.thread_count,
                "freq_mhz": info.cpu.freq_mhz,
            },
            "ram": {
                "total_mb": info.ram.total_mb,
                "used_mb": info.ram.used_mb,
                "usage_percent": info.ram.usage_percent,
            },
            "gpus": [
                {
                    "name": g.name,
                    "vram_total_mb": g.vram_total_mb,
                    "vram_used_mb": g.vram_used_mb,
                    "gpu_util_percent": g.gpu_util_percent,
                    "temperature_c": g.temperature_c,
                }
                for g in info.gpus
            ],
            "top_processes": info.top_processes,
        }
    except Exception as e:
        logger.error("System-Info Fehler: %s", e)
        raise HTTPException(status_code=500, detail=f"System-Info Fehler: {e}") from e


@app.get("/avatar")
async def avatar(emotion: str = "neutral"):
    """Rendert Avatar als PNG (headless, kein Fenster nötig)."""
    try:
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer
        from elder_berry.character.base import Emotion
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Avatar-Renderer nicht verfügbar (pygame fehlt)",
        )

    try:
        emo = Emotion(emotion)
    except ValueError:
        emo = Emotion.NEUTRAL

    try:
        renderer = LayeredSpriteRenderer()
        with tempfile.NamedTemporaryFile(
            suffix=".png", prefix="avatar_", delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)

        renderer.render_to_file(tmp_path, emo)
        png_bytes = tmp_path.read_bytes()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        logger.error("Avatar-Render Fehler: %s", e)
        raise HTTPException(status_code=500, detail=f"Avatar-Fehler: {e}") from e
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.post("/tts")
async def tts(request: TTSRequest):
    """Synthetisiert Text zu WAV via CoquiTTSEngine (XTTS v2)."""
    if engines.tts is None:
        raise HTTPException(status_code=503, detail="TTS-Engine nicht verfügbar")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Text darf nicht leer sein")

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)

        engines.tts.generate_audio(text, tmp_path, request.emotion)
        wav_bytes = tmp_path.read_bytes()
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:
        logger.error("TTS-Fehler: %s", e)
        raise HTTPException(status_code=500, detail=f"TTS-Fehler: {e}") from e
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.post("/stt")
async def stt(file: UploadFile):
    """Transkribiert Audio via FasterWhisperEngine."""
    if engines.stt is None:
        raise HTTPException(status_code=503, detail="STT-Engine nicht verfügbar")

    audio_data = await file.read()
    if not audio_data:
        raise HTTPException(status_code=422, detail="Leere Audio-Datei")

    try:
        # Audio in temporäre Datei schreiben (FasterWhisper braucht Dateipfad)
        suffix = Path(file.filename).suffix if file.filename else ".ogg"
        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False,
        ) as tmp:
            tmp.write(audio_data)
            tmp_path = Path(tmp.name)

        result = engines.stt.transcribe(tmp_path)
        return {
            "text": result.text,
            "language": result.language,
            "confidence": result.confidence,
        }
    except Exception as e:
        logger.error("STT-Fehler: %s", e)
        raise HTTPException(status_code=500, detail=f"STT-Fehler: {e}") from e
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.post("/action")
async def action(request: ActionRequest):
    """Führt eine PC-Steuerungsaktion aus."""
    if engines.actions is None:
        raise HTTPException(
            status_code=503, detail="ActionController nicht verfügbar",
        )

    try:
        return _dispatch_action(engines.actions, request.action, request.params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Action-Fehler (%s): %s", request.action, e)
        raise HTTPException(
            status_code=500, detail=f"Action-Fehler: {e}",
        ) from e


@app.get("/monitors")
async def get_monitors():
    """Verfügbare Monitore für Computer Use."""
    try:
        import mss
    except ImportError:
        return {"available": False, "monitors": [], "selected": 1}

    try:
        with mss.mss() as sct:
            monitors = []
            for i, mon in enumerate(sct.monitors):
                if i == 0:
                    continue  # Index 0 = "alle Monitore kombiniert"
                monitors.append({
                    "index": i,
                    "width": mon["width"],
                    "height": mon["height"],
                    "left": mon["left"],
                    "top": mon["top"],
                })
        # Aktuellen Index aus engines.actions oder Default 1
        selected = getattr(engines, "_monitor_index", 1)
        return {
            "available": True,
            "monitors": monitors,
            "selected": selected,
            "monitorCount": len(monitors),
        }
    except Exception as e:
        logger.error("Monitor-Abfrage Fehler: %s", e)
        return {"available": False, "monitors": [], "selected": 1}


@app.post("/monitor")
async def set_monitor(body: dict | None = None):
    """Monitor-Index für Computer Use setzen."""
    if not body or "index" not in body:
        raise HTTPException(status_code=400, detail="Parameter 'index' fehlt.")

    try:
        index = int(body["index"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Ungültiger Monitor-Index.")

    try:
        import mss
        with mss.mss() as sct:
            valid = set(range(1, len(sct.monitors)))
    except ImportError:
        raise HTTPException(status_code=503, detail="mss nicht installiert.")

    if index not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Monitor {index} nicht verfügbar. Gültig: {sorted(valid)}",
        )

    engines._monitor_index = index
    logger.info("Monitor-Index geändert: %d", index)
    return {"selected": index}


@app.get("/screenshot")
async def screenshot():
    """Nimmt einen Screenshot des Tower-Desktops auf (PNG)."""
    try:
        import mss
        import mss.tools
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="mss nicht installiert (pip install mss)",
        )

    try:
        with mss.mss() as sct:
            mon_idx = getattr(engines, "_monitor_index", 1)
            if mon_idx >= len(sct.monitors):
                mon_idx = 1
            monitor = sct.monitors[mon_idx]
            img = sct.grab(monitor)
            png_bytes = mss.tools.to_png(img.rgb, img.size)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        logger.error("Screenshot-Fehler: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Screenshot-Fehler: {e}",
        ) from e


# ---------------------------------------------------------------------------
# System-Update
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@app.post("/system/update")
async def system_update():
    """Git pull + pip install.  Beendet den Prozess danach mit exit(1),
    damit der Task-Scheduler ihn mit neuem Code neu startet."""
    import subprocess
    import sys
    import threading

    cwd = str(_PROJECT_ROOT)
    steps: list[str] = []

    # 1. git fetch
    try:
        r = subprocess.run(
            ["git", "fetch", "origin"],
            capture_output=True, text=True,
            timeout=30, cwd=cwd,
        )
        if r.returncode != 0:
            return {"success": False, "message": f"Git Fetch fehlgeschlagen: {r.stderr}"}
    except Exception as e:
        return {"success": False, "message": f"Git Fetch Fehler: {e}"}

    # 2. Commits behind?
    try:
        r = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..@{u}"],
            capture_output=True, text=True,
            timeout=10, cwd=cwd,
        )
        behind = int(r.stdout.strip()) if r.returncode == 0 else 0
    except Exception:
        behind = 0

    if behind == 0:
        return {"success": True, "message": "Alles aktuell -- kein Update noetig."}

    steps.append(f"{behind} neue(r) Commit(s)")

    # 3. git pull --ff-only
    try:
        r = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True, text=True,
            timeout=60, cwd=cwd,
        )
        if r.returncode != 0:
            return {"success": False, "message": f"Git Pull fehlgeschlagen: {r.stderr}"}
        steps.append("Code aktualisiert")
    except Exception as e:
        return {"success": False, "message": f"Git Pull Fehler: {e}"}

    # 4. pip install (Windows Tower extras)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e",
             ".[windows,tts-neural,avatar,matrix,remote,memory,stt]",
             "--quiet"],
            capture_output=True, text=True,
            timeout=300, cwd=cwd,
        )
        if r.returncode == 0:
            steps.append("Dependencies installiert")
        else:
            steps.append(f"pip Warnung: {r.stderr[:200]}")
    except Exception as e:
        steps.append(f"pip Fehler: {e}")

    # 5. Verzögerter Exit – Response geht noch raus, dann beendet sich
    #    der Prozess. Task-Scheduler startet ihn automatisch neu.
    def _delayed_exit():
        import time
        time.sleep(2)
        logger.info("Tower-Update abgeschlossen – beende Prozess fuer Neustart")
        os._exit(1)

    threading.Thread(target=_delayed_exit, daemon=True).start()
    steps.append("Neustart in 2 Sekunden...")

    return {"success": True, "message": " | ".join(steps)}


# ---------------------------------------------------------------------------
# CLI-Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8090)
