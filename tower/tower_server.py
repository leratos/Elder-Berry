"""TowerServer – FastAPI-Service für Tower-Dienste.

Exponiert TTS, STT, PC-Steuerung und Screenshot über HTTP.
Läuft auf dem Tower-PC und wird vom Server via SSH-Tunnel erreicht.

Starten:
    uvicorn tower.tower_server:app --host 0.0.0.0 --port 8090
"""
from __future__ import annotations

import io
import logging
import socket
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

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
    """Startup: Engines laden. Shutdown: Engines entladen."""
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
            monitor = sct.monitors[1]  # Primärer Monitor
            img = sct.grab(monitor)
            png_bytes = mss.tools.to_png(img.rgb, img.size)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        logger.error("Screenshot-Fehler: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Screenshot-Fehler: {e}",
        ) from e


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
