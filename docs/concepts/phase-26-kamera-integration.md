# Phase 26 – Kamera-Integration (RPi Camera Module 3)

> **Status:** Konzept
> **Erstellt:** 2026-03-22
> **Abhängigkeit:** RobotServer (Phase 2), AnthropicClient (Phase 5),
>   MatrixBridge (Phase 6), RemoteCommandHandler (Phase 7)

---

## Ziel

Saleria kann über die physische Kamera am RPi5 ihre Umgebung sehen und
auf Anfrage beschreiben. Bilder werden an Matrix gesendet und optional
per Anthropic Vision API analysiert.

**Flow:**
```
User: "was siehst du"
  → Tower: CameraCommandHandler erkennt Command
  → Tower: RobotClient.capture_image() → HTTP GET /camera/capture
  → RPi5: CameraController.capture() → picamera2 → JPEG-Bytes
  → RPi5: Response mit JPEG-Bytes (Base64 in JSON)
  → Tower: JPEG als temp-Datei speichern
  → Tower: Bild an Matrix senden (send_image)
  → Tower: JPEG Base64 → AnthropicClient.describe_image() → Beschreibung
  → Tower: Beschreibung an Matrix senden (send_text) + TTS
```

**Kosten:** ~2–4 Cent pro Kamera-Analyse (JPEG ~1000–2000 Tokens + Beschreibung ~200 Tokens)

---

## Architektur

### Neue Dateien

| Datei | Klasse | Seite | Beschreibung |
|-------|--------|-------|--------------|
| `src/elder_berry/robot/camera_controller.py` | `CameraController` (ABC) + `RPi5Camera` | RPi5 | picamera2-Wrapper, JPEG-Capture |
| `src/elder_berry/comms/commands/camera_commands.py` | `CameraCommandHandler` | Tower | Command-Handler für Kamera-Befehle |
| `tests/test_camera_controller.py` | – | Tower | Unit-Tests CameraController |
| `tests/test_camera_commands.py` | – | Tower | Unit-Tests CameraCommandHandler |

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/elder_berry/robot/server.py` | Neuer Endpoint `GET /camera/capture` + `CameraController` als DI-Parameter |
| `src/elder_berry/robot/client.py` | Neue Methode `capture_image() -> bytes` |
| `src/elder_berry/robot/simulator.py` | `SimulatedCamera` (gibt Dummy-JPEG zurück) |
| `src/elder_berry/llm/anthropic_client.py` | Neue Methode `describe_image(image_base64, prompt, system) -> str` |
| `src/elder_berry/comms/remote_commands.py` | CameraCommandHandler registrieren, RobotClient + AnthropicClient als DI |
| `scripts/start_rpi5.py` | CameraController instanziieren + an RobotServer übergeben |
| `scripts/start_saleria.py` | RobotClient + AnthropicClient an RemoteCommandHandler übergeben |

---

## Teilschritt 1: CameraController (RPi5-Seite)

### Datei: `src/elder_berry/robot/camera_controller.py`

```python
"""CameraController – Kamera-Steuerung für RPi Camera Module 3 (IMX708)."""
from __future__ import annotations

import io
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class CameraController(ABC):
    """ABC für Kamera-Steuerung auf dem RPi5."""

    @abstractmethod
    def is_available(self) -> bool:
        """Prüft ob die Kamera verfügbar und bereit ist."""
        ...

    @abstractmethod
    def capture_jpeg(self, quality: int = 85) -> bytes:
        """Nimmt ein Bild auf und gibt es als JPEG-Bytes zurück.

        Args:
            quality: JPEG-Qualität (1-100, Default 85).

        Returns:
            JPEG-kodierte Bilddaten als bytes.

        Raises:
            RuntimeError: Wenn Kamera nicht verfügbar oder Capture fehlschlägt.
        """
        ...

    @abstractmethod
    def get_resolution(self) -> tuple[int, int]:
        """Gibt die aktuelle Auflösung zurück (width, height)."""
        ...


class RPi5Camera(CameraController):
    """Echte Kamera-Implementierung für RPi Camera Module 3 (picamera2).

    Verwendet picamera2 (libcamera-basiert, Standard auf Bookworm).
    Die Kamera wird lazy initialisiert beim ersten Capture.

    Plattformhinweis: Nur auf RPi5 (Linux mit libcamera) lauffähig.
    """

    def __init__(
        self,
        resolution: tuple[int, int] = (1920, 1080),
    ) -> None:
        self._resolution = resolution
        self._camera = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy-Init: Kamera erst beim ersten Aufruf starten."""
        if self._initialized:
            return

        try:
            from picamera2 import Picamera2

            self._camera = Picamera2()
            config = self._camera.create_still_configuration(
                main={"size": self._resolution, "format": "RGB888"},
            )
            self._camera.configure(config)
            self._camera.start()
            self._initialized = True
            logger.info(
                "RPi5Camera initialisiert: %dx%d",
                self._resolution[0], self._resolution[1],
            )
        except ImportError:
            raise RuntimeError(
                "picamera2 nicht installiert. "
                "Installiere es mit: sudo apt install python3-picamera2"
            )
        except Exception as e:
            raise RuntimeError(f"Kamera-Initialisierung fehlgeschlagen: {e}")

    def is_available(self) -> bool:
        """Prüft ob picamera2 importierbar und Kamera erkannt."""
        try:
            from picamera2 import Picamera2
            cameras = Picamera2.global_camera_info()
            return len(cameras) > 0
        except Exception:
            return False

    def capture_jpeg(self, quality: int = 85) -> bytes:
        """Nimmt ein JPEG-Bild auf."""
        self._ensure_initialized()

        from PIL import Image

        # picamera2 capture_array → numpy → PIL → JPEG bytes
        array = self._camera.capture_array()
        image = Image.fromarray(array)

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        jpeg_bytes = buffer.getvalue()

        logger.info("Capture: %d bytes JPEG", len(jpeg_bytes))
        return jpeg_bytes

    def get_resolution(self) -> tuple[int, int]:
        return self._resolution

    def close(self) -> None:
        """Kamera-Ressourcen freigeben."""
        if self._camera and self._initialized:
            self._camera.stop()
            self._camera.close()
            self._initialized = False
            logger.info("RPi5Camera geschlossen")
```

### Wichtige Hinweise
- **picamera2** ist auf Bookworm vorinstalliert (`sudo apt install python3-picamera2`)
- Lazy-Init: Kamera wird erst beim ersten `capture_jpeg()` gestartet → kein Overhead wenn nicht genutzt
- **PIL/Pillow** wird für JPEG-Encoding gebraucht (auf RPi5: `sudo apt install python3-pil`)
- Auflösung 1920×1080 als Default – genug Detail für Vision-Analyse, nicht übertrieben groß
- `capture_array()` + PIL ist robuster als `capture_file()` weil wir bytes brauchen, keine Datei

---

## Teilschritt 2: Server-Endpoint (RPi5-Seite)

### Datei: `src/elder_berry/robot/server.py` – Änderungen

**Neuer Import oben:**
```python
from elder_berry.robot.camera_controller import CameraController
```

**Neuer DI-Parameter im Konstruktor:**
```python
class RobotServer:
    def __init__(
        self,
        motors: MotorController,
        avatar: AvatarDisplay,
        sensors: SensorManager,
        camera: CameraController | None = None,   # NEU
        hostname: str = "elder-berry-rpi",
    ) -> None:
        self._motors = motors
        self._avatar = avatar
        self._sensors = sensors
        self._camera = camera                      # NEU
        ...
```

**Neue Endpoints in `_register_routes()`:**
```python
        @self.app.get("/camera/capture")
        def camera_capture(quality: int = 85) -> dict:
            """Nimmt ein Bild auf und gibt JPEG als Base64 zurück."""
            if not self._camera:
                return asdict(ApiResponse(
                    success=False,
                    message="Keine Kamera verfügbar",
                ))
            if not self._camera.is_available():
                return asdict(ApiResponse(
                    success=False,
                    message="Kamera nicht erkannt",
                ))
            try:
                import base64
                jpeg_bytes = self._camera.capture_jpeg(quality=quality)
                b64 = base64.b64encode(jpeg_bytes).decode("ascii")
                width, height = self._camera.get_resolution()
                return {
                    "success": True,
                    "image_base64": b64,
                    "format": "jpeg",
                    "width": width,
                    "height": height,
                    "size_bytes": len(jpeg_bytes),
                }
            except Exception as e:
                logger.error("Kamera-Capture fehlgeschlagen: %s", e)
                return asdict(ApiResponse(
                    success=False,
                    message=f"Capture fehlgeschlagen: {e}",
                ))

        @self.app.get("/camera/status")
        def camera_status() -> dict:
            """Gibt den Kamera-Status zurück."""
            if not self._camera:
                return {"available": False, "reason": "Keine Kamera konfiguriert"}
            available = self._camera.is_available()
            resolution = self._camera.get_resolution() if available else None
            return {
                "available": available,
                "resolution": resolution,
            }
```

### Warum GET statt POST?
- Capture ist idempotent (nimmt ein Bild auf, ändert keinen State)
- `quality` als Query-Parameter reicht (kein Body nötig)
- Konsistent mit `/sensor/battery` und `/sensor/all` (auch GET)

### Warum Base64 im JSON statt Raw-Bytes?
- Konsistent mit dem Rest der API (alles JSON)
- AnthropicClient braucht Base64 sowieso für die Vision-API
- Bei 1920×1080 JPEG (quality 85) ≈ 200–500 KB → Base64 ≈ 270–670 KB
- Über LAN (Tower ↔ RPi5) völlig unproblematisch

---

## Teilschritt 3: Client-Erweiterung (Tower-Seite)

### Datei: `src/elder_berry/robot/client.py` – Neue Methoden

```python
    # --- Kamera ---

    def capture_image(self, quality: int = 85) -> bytes | None:
        """Nimmt ein Bild über die RPi5-Kamera auf.

        Args:
            quality: JPEG-Qualität (1-100).

        Returns:
            JPEG-Bytes oder None wenn Kamera nicht verfügbar.

        Raises:
            httpx.HTTPError: Bei Verbindungsproblemen.
        """
        r = self._client.get("/camera/capture", params={"quality": quality})
        r.raise_for_status()
        data = r.json()

        if not data.get("success"):
            logger.warning("Kamera: %s", data.get("message", "unbekannter Fehler"))
            return None

        import base64
        return base64.b64decode(data["image_base64"])

    def camera_status(self) -> dict:
        """Gibt den Kamera-Status vom RPi5 zurück."""
        r = self._client.get("/camera/status")
        r.raise_for_status()
        return r.json()
```

### Timeout-Hinweis
- `capture_image()` kann ~1–2s dauern (Kamera-Init + Capture + Encoding + Transfer)
- Default-Timeout des Clients ist 5s → sollte reichen
- Falls nicht: separater Timeout für Kamera-Calls prüfen

---

## Teilschritt 4: Vision-Analyse (AnthropicClient)

### Datei: `src/elder_berry/llm/anthropic_client.py` – Neue Methode

```python
    def describe_image(
        self,
        image_base64: str,
        prompt: str = "Beschreibe was du auf diesem Bild siehst.",
        system: str = "",
        media_type: str = "image/jpeg",
    ) -> str:
        """Analysiert ein Bild per Claude Vision API.

        Nutzt die Standard Messages API (kein Beta nötig).

        Args:
            image_base64: Base64-kodiertes Bild.
            prompt: Frage/Anweisung zum Bild.
            system: Optionaler System-Prompt.
            media_type: MIME-Type (default: image/jpeg).

        Returns:
            Textuelle Beschreibung des Bildes.

        Raises:
            RuntimeError: Bei API-Fehlern.
        """
        self._check_available()

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ]

        kwargs: dict = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        try:
            msg = self._get_client().messages.create(**kwargs)
            return msg.content[0].text
        except _anthropic.APIStatusError as e:
            raise RuntimeError(
                f"Anthropic API-Fehler: {e.status_code} – {e.message}"
            ) from e
        except _anthropic.APIConnectionError as e:
            raise RuntimeError(f"Anthropic nicht erreichbar: {e}") from e
        except _anthropic.RateLimitError as e:
            raise RuntimeError(f"Anthropic Rate-Limit erreicht: {e}") from e
```

### Hinweis: Kein Beta-Header nötig
- Im Gegensatz zu `computer_use()` ist Vision über die Standard Messages API verfügbar
- Kein `betas=` Parameter, kein Tool-Use → einfacher Call
- Wiederverwendbar für zukünftige Bild-Analyse (z.B. Dokument-OCR, Paket-Erkennung)

---

## Teilschritt 5: CameraCommandHandler (Tower-Seite)

### Datei: `src/elder_berry/comms/commands/camera_commands.py`

```python
"""CameraCommandHandler -- Kamera-Befehle (Foto, Vision-Analyse)."""
from __future__ import annotations

import base64
import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.llm.anthropic_client import AnthropicClient
    from elder_berry.robot.client import RobotClient

logger = logging.getLogger(__name__)

# Regex: "was siehst du <kontext>", "beschreibe was vor dir ist"
CAMERA_DESCRIBE_PATTERN = re.compile(
    r"^(?:was\s+siehst\s+du|was\s+sieht\s+die\s+kamera|beschreibe\s+was"
    r"|schau\s+(?:mal\s+)?(?:was|ob)|guck\s+(?:mal\s+)?(?:was|ob))"
    r"(?:\s+(.+))?$",
    re.IGNORECASE,
)


class CameraCommandHandler(CommandHandler):
    """Handler für Kamera-Befehle (Foto aufnehmen, Vision-Analyse)."""

    def __init__(
        self,
        robot_client: RobotClient | None = None,
        anthropic_client: AnthropicClient | None = None,
    ) -> None:
        self._robot = robot_client
        self._anthropic = anthropic_client

    @property
    def simple_commands(self) -> set[str]:
        return {"foto", "kamera", "kamerabild"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (CAMERA_DESCRIBE_PATTERN, "camera_describe", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "foto / kamera: Foto mit der Kamera aufnehmen",
            "was siehst du [kontext]: Kamerabild aufnehmen + Vision-Analyse",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "foto": [
                "mach ein foto", "nimm ein bild auf", "kamerabild",
                "fotografier", "knips", "mach ein bild",
            ],
            "camera_describe": [
                "was siehst du", "was sieht die kamera",
                "schau mal", "guck mal", "was ist vor dir",
                "kannst du sehen", "siehst du was",
                "zeig mir was du siehst", "was ist da",
                "beschreibe deine umgebung",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command in ("foto", "kamera", "kamerabild"):
            return self._cmd_foto()

        if command == "camera_describe":
            return self._cmd_describe(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Command: {command}",
        )

    def _capture_image(self) -> tuple[bytes | None, str | None]:
        """Nimmt ein Bild auf. Gibt (jpeg_bytes, error_text) zurück."""
        if not self._robot:
            return None, "RobotClient nicht verfügbar (RPi5 nicht verbunden)."

        try:
            jpeg_bytes = self._robot.capture_image()
        except Exception as e:
            logger.error("Kamera-Capture fehlgeschlagen: %s", e)
            return None, f"Kamera-Fehler: {e}"

        if jpeg_bytes is None:
            return None, "Kamera nicht verfügbar oder Capture fehlgeschlagen."

        return jpeg_bytes, None

    def _save_temp_jpeg(self, jpeg_bytes: bytes) -> Path:
        """Speichert JPEG-Bytes als temp-Datei."""
        tmp = tempfile.NamedTemporaryFile(
            suffix=".jpg", prefix="camera_", delete=False,
        )
        tmp_path = Path(tmp.name)
        tmp.write(jpeg_bytes)
        tmp.close()
        return tmp_path

    def _cmd_foto(self) -> CommandResult:
        """Nimmt ein Foto auf und sendet es an Matrix."""
        jpeg_bytes, error = self._capture_image()
        if error:
            return CommandResult(command="foto", success=False, text=error)

        tmp_path = self._save_temp_jpeg(jpeg_bytes)

        return CommandResult(
            command="foto",
            success=True,
            text="📸 Foto aufgenommen.",
            image_path=tmp_path,
        )

    def _cmd_describe(self, raw_text: str) -> CommandResult:
        """Nimmt ein Foto auf, analysiert es per Vision API und beschreibt es.

        Wenn kein AnthropicClient verfügbar: nur Foto ohne Beschreibung.
        """
        jpeg_bytes, error = self._capture_image()
        if error:
            return CommandResult(
                command="camera_describe", success=False, text=error,
            )

        tmp_path = self._save_temp_jpeg(jpeg_bytes)

        # Ohne Vision-API: nur Bild senden
        if not self._anthropic or not self._anthropic.is_available():
            return CommandResult(
                command="camera_describe",
                success=True,
                text="📸 Foto aufgenommen. (Vision-Analyse nicht verfügbar – "
                     "AnthropicClient fehlt oder kein API-Key)",
                image_path=tmp_path,
            )

        # Vision-Analyse
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")

        # Kontext aus dem Befehl extrahieren (optional)
        match = CAMERA_DESCRIBE_PATTERN.match(raw_text.strip())
        extra_context = ""
        if match and match.group(1):
            extra_context = match.group(1).strip()

        prompt = "Beschreibe kurz und präzise was du auf diesem Kamerabild siehst."
        if extra_context:
            prompt = (
                f"Der Nutzer fragt: '{extra_context}'. "
                f"Beantworte die Frage basierend auf dem Kamerabild. "
                f"Sei kurz und präzise."
            )

        system = (
            "Du bist Saleria, eine virtuelle Assistentin. "
            "Du beschreibst was die Kamera sieht. "
            "Antworte auf Deutsch, kurz und natürlich."
        )

        try:
            description = self._anthropic.describe_image(
                image_base64=b64,
                prompt=prompt,
                system=system,
            )
        except Exception as e:
            logger.error("Vision-Analyse fehlgeschlagen: %s", e)
            return CommandResult(
                command="camera_describe",
                success=True,
                text=f"📸 Foto aufgenommen, aber Analyse fehlgeschlagen: {e}",
                image_path=tmp_path,
            )

        return CommandResult(
            command="camera_describe",
            success=True,
            text=description,
            image_path=tmp_path,
        )
```

### Design-Entscheidungen

1. **Zwei Commands statt einem:**
   - `foto` / `kamera`: Nur Bild aufnehmen + an Matrix senden (kostenlos)
   - `was siehst du`: Bild + Vision-Analyse (~3 Cent pro Call)
   - Grund: Nicht jedes Foto braucht eine Analyse. Manchmal will man nur das Bild.

2. **Kontext-Extraktion:**
   - "was siehst du" → generische Beschreibung
   - "was siehst du auf meinem schreibtisch" → fokussierte Antwort
   - "schau mal ob ein Paket da ist" → gezielte Prüfung
   - Der optionale Kontext wird als Prompt an die Vision-API weitergegeben.

3. **Graceful Degradation:**
   - Kein RPi5 → Fehlermeldung
   - Kein AnthropicClient → nur Foto, kein Vision
   - Vision-API-Fehler → Foto wird trotzdem gesendet, Fehler als Text

4. **Bridge-Integration:**
   - `result.image_path` → Bridge sendet Bild via `send_image()` (bestehendes Pattern)
   - `result.text` → Bridge sendet Beschreibung als Text
   - Kein Sonderfall in der Bridge nötig!

---

## Teilschritt 6: Integration

### `src/elder_berry/comms/remote_commands.py` – Änderungen

**Import hinzufügen:**
```python
from elder_berry.comms.commands.camera_commands import CameraCommandHandler
```

**TYPE_CHECKING erweitern:**
```python
if TYPE_CHECKING:
    ...
    from elder_berry.llm.anthropic_client import AnthropicClient
    from elder_berry.robot.client import RobotClient
```

**Konstruktor – neue Parameter:**
```python
    def __init__(
        self,
        ...
        robot_client: RobotClient | None = None,        # NEU
        anthropic_client: AnthropicClient | None = None, # NEU
    ) -> None:
        ...
        # Camera-Handler
        self._camera = CameraCommandHandler(
            robot_client=robot_client,
            anthropic_client=anthropic_client,
        )
```

**Handler-Liste erweitern:**
```python
        self._handlers: list[CommandHandler] = [
            self._system,
            self._weather,
            self._calendar,
            self._mail,
            self._file,
            self._process,
            self._camera,    # NEU – vor _advanced (Keyword-Priorität)
        ]
```

### `scripts/start_rpi5.py` – Änderungen

```python
    # -- Kamera (optional) -----------------------------------------------------
    camera = None
    try:
        from elder_berry.robot.camera_controller import RPi5Camera
        camera = RPi5Camera(resolution=(1920, 1080))
        if camera.is_available():
            logger.info("Kamera erkannt: RPi Camera Module 3")
        else:
            logger.warning("Kamera nicht erkannt – Capture deaktiviert")
            camera = None
    except Exception as e:
        logger.warning("Kamera-Init fehlgeschlagen: %s", e)

    # -- RobotServer -----------------------------------------------------------
    server = RobotServer(
        motors=motors,
        avatar=avatar,
        sensors=sensors,
        camera=camera,          # NEU
        hostname="elder-berry-rpi5",
    )
```

### `scripts/start_saleria.py` – Änderungen

Der `RobotClient` und `AnthropicClient` existieren bereits im Start-Script.
Sie müssen nur an den `RemoteCommandHandler` durchgereicht werden:

```python
    remote_handler = RemoteCommandHandler(
        ...
        robot_client=robot_client,              # NEU
        anthropic_client=anthropic_client,       # NEU
    )
```

**Prüfpunkt:** Lies `start_saleria.py` vor dem Editieren – die Variablennamen
für RobotClient und AnthropicClient müssen exakt stimmen.

### `src/elder_berry/robot/simulator.py` – SimulatedCamera

```python
class SimulatedCamera(CameraController):
    """Simulierte Kamera für lokale Entwicklung."""

    def __init__(self, resolution: tuple[int, int] = (1920, 1080)) -> None:
        self._resolution = resolution

    def is_available(self) -> bool:
        return True

    def capture_jpeg(self, quality: int = 85) -> bytes:
        """Generiert ein minimales JPEG-Testbild (320x240, dunkelgrau)."""
        from PIL import Image
        import io

        img = Image.new("RGB", (320, 240), color=(40, 40, 40))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        logger.info("[SIM] Camera: Simulated capture")
        return buffer.getvalue()

    def get_resolution(self) -> tuple[int, int]:
        return self._resolution
```

**Import hinzufügen in simulator.py:**
```python
from elder_berry.robot.camera_controller import CameraController
```

### HELP_TEXT in `remote_commands.py` erweitern

Am Ende des bestehenden HELP_TEXT einfügen:
```
Kamera:
  foto / kamera – Foto aufnehmen und senden
  was siehst du [kontext] – Kamerabild + KI-Beschreibung
```

---

## Teilschritt 7: Tests

### `tests/test_camera_controller.py`

1. `test_simulated_camera_available` – `is_available()` gibt True
2. `test_simulated_camera_capture_returns_jpeg` – Bytes sind valides JPEG (beginnt mit `\xff\xd8`)
3. `test_simulated_camera_resolution` – `get_resolution()` gibt konfigurierte Auflösung
4. `test_simulated_camera_quality_parameter` – Verschiedene Quality-Werte produzieren verschiedene Größen
5. `test_rpi5_camera_unavailable_without_picamera2` – Import-Fehler gibt `RuntimeError`

### `tests/test_camera_commands.py`

6. `test_parse_foto` – "foto" wird als Command erkannt
7. `test_parse_kamera` – "kamera" wird als Command erkannt
8. `test_parse_kamerabild` – "kamerabild" wird als Command erkannt
9. `test_parse_was_siehst_du` – "was siehst du" → `camera_describe`
10. `test_parse_was_siehst_du_kontext` – "was siehst du auf meinem schreibtisch" → `camera_describe`
11. `test_parse_schau_mal` – "schau mal was da liegt" → `camera_describe`
12. `test_parse_guck_mal` – "guck mal ob jemand da ist" → `camera_describe`
13. `test_keyword_mach_ein_foto` – "mach ein foto" → `foto` (Keyword-Match)
14. `test_keyword_was_siehst_du` – "kannst du sehen was da ist" → `camera_describe` (Keyword)
15. `test_foto_no_robot` – `robot_client=None` → Fehler "RobotClient nicht verfügbar"
16. `test_foto_capture_returns_none` – `capture_image()` gibt None → Fehler
17. `test_foto_success` – Mock-Robot gibt JPEG → `image_path` gesetzt, success=True
18. `test_describe_no_anthropic` – Kein AnthropicClient → nur Foto, kein Vision-Text
19. `test_describe_success` – Mock-Robot + Mock-Anthropic → Beschreibung + Bild
20. `test_describe_vision_error` – Vision wirft Exception → Foto gesendet, Fehlertext
21. `test_describe_with_context` – "was siehst du auf dem tisch" → Kontext in Prompt enthalten
22. `test_foto_temp_file_is_jpeg` – Temp-Datei endet auf .jpg und enthält JPEG-Header
23. `test_no_collision_with_screenshot` – "screenshot" wird NICHT als Kamera-Command erkannt

### Server-/Client-Tests (in bestehende Testfiles integrieren oder separat)

24. `test_server_camera_capture_success` – GET /camera/capture gibt Base64-JPEG
25. `test_server_camera_capture_no_camera` – Kein CameraController → success=False
26. `test_server_camera_status` – GET /camera/status gibt available + resolution
27. `test_client_capture_image` – RobotClient.capture_image() dekodiert Base64 zu bytes
28. `test_client_capture_image_unavailable` – Server gibt success=False → None

---

## Reihenfolge für Claude Code

1. **camera_controller.py** + **simulator.py Erweiterung** (SimulatedCamera)
2. **server.py Änderungen** (Endpoint + DI)
3. **client.py Erweiterung** (capture_image, camera_status)
4. **anthropic_client.py Erweiterung** (describe_image)
5. **camera_commands.py** (neuer CommandHandler)
6. **remote_commands.py** (Integration: Import, DI, Handler-Liste, HELP_TEXT)
7. **start_rpi5.py** (CameraController instanziieren)
8. **start_saleria.py** (RobotClient + AnthropicClient an RemoteCommandHandler)
9. **Tests** (test_camera_controller.py + test_camera_commands.py)
10. **Bestehende Tests ausführen** (keine Regressionen)

---

## RPi5-Setup (Voraussetzungen)

Auf dem RPi5 müssen folgende Pakete installiert sein:
```bash
# picamera2 (normalerweise auf Bookworm vorinstalliert)
sudo apt install python3-picamera2

# Pillow für JPEG-Encoding
sudo apt install python3-pil

# Prüfen ob Kamera erkannt wird
libcamera-hello --list-cameras
```

Falls `picamera2` die System-Python-Version nutzt, aber Elder-Berry in einem
venv läuft: `--system-site-packages` beim venv-Erstellen verwenden, oder
`picamera2` per pip installieren (kann auf Bookworm schwierig sein).

**Empfehlung:** venv mit `--system-site-packages` erstellen, damit picamera2
aus den System-Paketen verfügbar ist.

---

## Offene Fragen / Entscheidungen

### 1. Auflösung
- Default 1920×1080 – genug Detail, nicht zu groß (~300–500 KB JPEG)
- Alternative: 1280×720 (kleinere Bilder → weniger Tokens → billiger)
- **Empfehlung:** 1920×1080, kann per Parameter reduziert werden

### 2. Continuous Capture / Streaming
- Aktuell: Single-Shot pro Befehl
- Kein Video-Stream geplant (zu viel Bandwidth + Kosten)
- Falls nötig: könnte als Phase 26b nachgerüstet werden

### 3. Autofokus / Belichtung
- IMX708 hat Autofokus – picamera2 handhabt das automatisch
- Kein manueller Fokus nötig für Schreibtisch-Distanz (60–80 cm)

### 4. Nachtmodus / IR
- RPi Camera Module 3 Standard (kein NoIR) – IR-Cutfilter eingebaut
- Bei schlechtem Licht: schlechtere Bildqualität, aber kein Showstopper
- Falls nötig: IR-LED + NoIR-Kamera wäre Hardware-Upgrade

### 5. Bildrotation
- Je nach Einbauposition im Gehäuse muss das Bild rotiert werden
- picamera2 kann das: `camera.set_controls({"Transform": libcamera.Transform(rotation=180)})`
- **Erst beim Einbau ins Gehäuse testen** – Rotation als Parameter in RPi5Camera


---

## Hardware-Test-Ergebnisse (2026-03-22)

- **Sensor:** IMX708 erkannt auf `/base/axi/pcie@1000120000/rp1/i2c@88000/imx708@1a`
- **Rotation:** 180° (Kamera kopfüber montiert – picamera2 korrigiert automatisch)
- **Modi:** 1536×864 @120fps, 2304×1296 @56fps, 4608×2592 @14fps
- **Testbild:** 705 KB JPEG bei voller Auflösung (4608×2592)
- **picamera2:** Via `sudo apt install python3-picamera2` ins System installiert,
  venv mit `include-system-site-packages = true` konfiguriert
- **libcamera-tools:** `rpicam-still` / `rpicam-hello` (Bookworm-Namenskonvention, nicht `libcamera-*`)
- **venv:** `/home/pi/elder-berry/.venv` (Python 3.13.5, system-site-packages enabled)

### Anpassung an RPi5Camera aufgrund der Testergebnisse

1. **Rotation:** `Picamera2.global_camera_info()` gibt `Rotation: 180` zurück.
   picamera2 wendet die Rotation bei `create_still_configuration` automatisch an,
   daher ist kein manueller `Transform`-Aufruf nötig. Falls das Bild doch falsch
   orientiert ist, kann in `_ensure_initialized()` ergänzt werden:
   ```python
   from libcamera import Transform
   config = self._camera.create_still_configuration(
       main={"size": self._resolution, "format": "RGB888"},
       transform=Transform(hflip=True, vflip=True),  # 180° Korrektur
   )
   ```

2. **Auflösung:** 4608×2592 wäre volle Sensor-Auflösung, aber 14 fps und
   705 KB pro Bild (~940 KB Base64). Für Vision-Analyse ist das Overkill.
   **Empfehlung bleibt 1920×1080** – picamera2 skaliert automatisch vom
   2304×1296-Modus herunter. Das ergibt ~200–400 KB JPEG.
