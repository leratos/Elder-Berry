"""Computer Use – Vision-gesteuerte PC-Bedienung via Anthropic API."""
from __future__ import annotations

import base64
import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .base import ActionController
from ..llm.anthropic_client import AnthropicClient, ComputerUseAction

logger = logging.getLogger(__name__)

# Lazy-Imports für optionale Abhängigkeiten
try:
    import mss
    import mss.tools
    _MSS_AVAILABLE = True
except ImportError:
    mss = None  # type: ignore[assignment]
    _MSS_AVAILABLE = False

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False


# Maximale Breite für Screenshots an die API (spart Tokens)
MAX_SCREENSHOT_WIDTH = 1280

# Wartezeit zwischen Aktion und Verification-Screenshot (Sekunden)
VERIFICATION_DELAY = 2.0


@dataclass(frozen=True)
class ComputerUseResult:
    """Ergebnis einer Computer-Use-Aktion."""

    action: ComputerUseAction
    success: bool
    message: str
    verification_image_path: Path | None = None
    error: str | None = None


class ComputerUseController:
    """
    Orchestriert Vision-gesteuerte PC-Bedienung.

    Flow:
    1. Screenshot aufnehmen (mss)
    2. Optional resizen (Pillow)
    3. An Anthropic Computer Use API senden
    4. Strukturierte Aktion empfangen
    5. DPI-kompensierte Koordinaten berechnen
    6. Aktion via ActionController ausführen
    7. Verification-Screenshot aufnehmen

    Args:
        anthropic_client: AnthropicClient mit Computer-Use-Fähigkeit.
        controller: ActionController für die Aktionsausführung.
        monitor_index: Index des Monitors (1=primär, 2=zweiter, ...).
    """

    def __init__(
        self,
        anthropic_client: AnthropicClient,
        controller: ActionController,
        monitor_index: int = 1,
    ) -> None:
        self._anthropic = anthropic_client
        self._controller = controller
        self._monitor_index = monitor_index

    @property
    def monitor_index(self) -> int:
        return self._monitor_index

    @monitor_index.setter
    def monitor_index(self, value: int) -> None:
        self._monitor_index = value

    def get_available_monitors(self) -> list[dict]:
        """Gibt eine Liste verfügbarer Monitore zurück."""
        if not _MSS_AVAILABLE:
            return []
        with mss.mss() as sct:
            monitors = []
            for i, mon in enumerate(sct.monitors):
                if i == 0:
                    continue  # Index 0 = virtueller Gesamtbildschirm
                monitors.append({
                    "index": i,
                    "width": mon["width"],
                    "height": mon["height"],
                    "left": mon["left"],
                    "top": mon["top"],
                })
            return monitors

    def execute_instruction(self, instruction: str) -> ComputerUseResult:
        """
        Führt eine Computer-Use-Anweisung aus.

        Args:
            instruction: Natürlichsprachliche Anweisung (z.B. "klick auf den OK Button").

        Returns:
            ComputerUseResult mit Aktion, Erfolg und optionalem Verification-Screenshot.
        """
        if not _MSS_AVAILABLE:
            return ComputerUseResult(
                action=ComputerUseAction(action="none"),
                success=False,
                message="mss nicht installiert (pip install mss).",
                error="mss_missing",
            )

        # 1. Screenshot aufnehmen
        try:
            screenshot_b64, display_w, display_h = self._capture_screenshot()
        except Exception as e:
            logger.error("Screenshot fehlgeschlagen: %s", e)
            return ComputerUseResult(
                action=ComputerUseAction(action="none"),
                success=False,
                message=f"Screenshot fehlgeschlagen: {e}",
                error="screenshot_failed",
            )

        # 2. Computer Use API aufrufen
        try:
            cu_action = self._anthropic.computer_use(
                screenshot_base64=screenshot_b64,
                instruction=instruction,
                display_width=display_w,
                display_height=display_h,
                system="Du steuerst einen Windows-PC. Führe genau die angewiesene Aktion aus.",
            )
        except RuntimeError as e:
            logger.error("Computer Use API-Fehler: %s", e)
            return ComputerUseResult(
                action=ComputerUseAction(action="none"),
                success=False,
                message=f"API-Fehler: {e}",
                error="api_error",
            )

        # 3. Aktion ausführen
        try:
            self._execute_action(cu_action, display_w, display_h)
        except Exception as e:
            logger.error("Aktionsausführung fehlgeschlagen: %s", e)
            return ComputerUseResult(
                action=cu_action,
                success=False,
                message=f"Aktion '{cu_action.action}' fehlgeschlagen: {e}",
                error="execution_failed",
            )

        # 4. Verification-Screenshot
        time.sleep(VERIFICATION_DELAY)
        verification_path = self._take_verification_screenshot()

        action_desc = self._describe_action(cu_action)
        return ComputerUseResult(
            action=cu_action,
            success=True,
            message=f"Aktion ausgeführt: {action_desc}",
            verification_image_path=verification_path,
        )

    def _capture_screenshot(self) -> tuple[str, int, int]:
        """
        Nimmt einen Screenshot auf, resized optional und gibt
        (base64_png, display_width, display_height) zurück.

        display_width/height sind die Dimensionen des Bildes das an die API
        gesendet wird (nach Resize).
        """
        with mss.mss() as sct:
            monitors = sct.monitors
            if self._monitor_index >= len(monitors):
                self._monitor_index = 1  # Fallback auf primär
            monitor = monitors[self._monitor_index]
            screenshot = sct.grab(monitor)
            raw_width = screenshot.width
            raw_height = screenshot.height
            png_bytes = mss.tools.to_png(screenshot.rgb, screenshot.size)

        # Resize wenn breiter als MAX_SCREENSHOT_WIDTH (spart Tokens)
        if _PIL_AVAILABLE and raw_width > MAX_SCREENSHOT_WIDTH:
            img = Image.open(io.BytesIO(png_bytes))
            scale = MAX_SCREENSHOT_WIDTH / raw_width
            new_height = int(raw_height * scale)
            img = img.resize((MAX_SCREENSHOT_WIDTH, new_height), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            display_w = MAX_SCREENSHOT_WIDTH
            display_h = new_height
        else:
            display_w = raw_width
            display_h = raw_height

        b64 = base64.b64encode(png_bytes).decode("ascii")
        return b64, display_w, display_h

    def _execute_action(
        self,
        action: ComputerUseAction,
        display_w: int,
        display_h: int,
    ) -> None:
        """
        Führt die Computer-Use-Aktion via ActionController aus.

        Koordinaten werden von API-Koordinaten (relativ zum gesendeten Bild)
        auf physische Bildschirm-Koordinaten umgerechnet.
        """
        # Physische Monitor-Dimensionen für Koordinaten-Mapping
        phys_w, phys_h, offset_x, offset_y = self._get_monitor_geometry()

        def _map_coord(coord: tuple[int, int]) -> tuple[int, int]:
            """Mappt API-Koordinaten auf physische Bildschirm-Koordinaten."""
            api_x, api_y = coord
            # Skalierung: API-Bild → physischer Monitor
            scale_x = phys_w / display_w
            scale_y = phys_h / display_h
            phys_x = int(api_x * scale_x) + offset_x
            phys_y = int(api_y * scale_y) + offset_y
            return phys_x, phys_y

        name = action.action

        if name == "screenshot":
            # Claude will einen Screenshot – nichts zu tun
            return

        if name in ("left_click", "right_click", "middle_click", "double_click"):
            if action.coordinate is None:
                raise ValueError(f"Aktion '{name}' benötigt Koordinaten.")
            px, py = _map_coord(action.coordinate)
            button = "left"
            if name == "right_click":
                button = "right"
            elif name == "middle_click":
                button = "middle"
            if name == "double_click":
                self._controller.click(px, py, button="left")
                time.sleep(0.05)
                self._controller.click(px, py, button="left")
            else:
                self._controller.click(px, py, button=button)

        elif name == "type":
            if not action.text:
                raise ValueError("Aktion 'type' benötigt Text.")
            self._controller.type_text(action.text)

        elif name == "key":
            if not action.text:
                raise ValueError("Aktion 'key' benötigt einen Tasten-String.")
            keys = [k.strip() for k in action.text.split("+")]
            if len(keys) > 1:
                self._controller.hotkey(*keys)
            else:
                self._controller.press_key(keys[0])

        elif name == "scroll":
            if action.coordinate is None:
                raise ValueError("Aktion 'scroll' benötigt Koordinaten.")
            px, py = _map_coord(action.coordinate)
            self._controller.move_mouse(px, py, duration=0.1)
            amount = action.scroll_amount or 3
            if action.scroll_direction in ("down", "right"):
                amount = -amount
            # pyautogui.scroll: positiv = hoch, negativ = runter
            try:
                import pyautogui
                pyautogui.scroll(amount)
            except ImportError:
                logger.warning("pyautogui nicht verfügbar für scroll.")

        elif name == "mouse_move":
            if action.coordinate is None:
                raise ValueError("Aktion 'mouse_move' benötigt Koordinaten.")
            px, py = _map_coord(action.coordinate)
            self._controller.move_mouse(px, py)

        else:
            logger.warning("Unbekannte Computer-Use-Aktion: %s", name)

    def _get_monitor_geometry(self) -> tuple[int, int, int, int]:
        """Gibt (width, height, left_offset, top_offset) des Monitors zurück."""
        with mss.mss() as sct:
            monitors = sct.monitors
            if self._monitor_index >= len(monitors):
                self._monitor_index = 1
            mon = monitors[self._monitor_index]
            return mon["width"], mon["height"], mon["left"], mon["top"]

    def _take_verification_screenshot(self) -> Path | None:
        """Nimmt einen Verification-Screenshot auf und gibt den Pfad zurück."""
        try:
            import tempfile
            with mss.mss() as sct:
                monitors = sct.monitors
                if self._monitor_index >= len(monitors):
                    self._monitor_index = 1
                monitor = monitors[self._monitor_index]
                screenshot = sct.grab(monitor)
                # NamedTemporaryFile statt mktemp() – verhindert TOCTOU-Race-Condition
                with tempfile.NamedTemporaryFile(
                    suffix=".png", prefix="cu_verify_", delete=False,
                ) as tmp:
                    tmp_path = Path(tmp.name)
                mss.tools.to_png(
                    screenshot.rgb, screenshot.size, output=str(tmp_path)
                )
                return tmp_path
        except Exception as e:
            logger.error("Verification-Screenshot fehlgeschlagen: %s", e)
            return None

    @staticmethod
    def _describe_action(action: ComputerUseAction) -> str:
        """Erstellt eine lesbare Beschreibung der Aktion."""
        if action.action in ("left_click", "right_click", "middle_click", "double_click"):
            coord = f" bei ({action.coordinate[0]}, {action.coordinate[1]})" if action.coordinate else ""
            return f"{action.action}{coord}"
        if action.action == "type":
            text = action.text or ""
            preview = text[:30] + "..." if len(text) > 30 else text
            return f"type: \"{preview}\""
        if action.action == "key":
            return f"key: {action.text}"
        if action.action == "scroll":
            return f"scroll {action.scroll_direction} ×{action.scroll_amount}"
        return action.action
