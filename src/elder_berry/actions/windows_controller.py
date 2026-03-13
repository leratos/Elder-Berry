"""PC-Steuerung – Windows-Implementierung."""
import logging
import platform

import pyautogui
import pygetwindow as gw

from .base import ActionController, WindowInfo

logger = logging.getLogger(__name__)

# pyautogui Sicherheitseinstellungen
pyautogui.FAILSAFE = True  # Maus in Ecke oben links → Abbruch
pyautogui.PAUSE = 0.05     # Kurze Pause zwischen Aktionen


def _check_platform() -> None:
    """Wirft RuntimeError wenn nicht auf Windows."""
    if platform.system() != "Windows":
        raise RuntimeError(
            f"WindowsActionController ist nur unter Windows verfügbar "
            f"(aktuell: {platform.system()})."
        )


class WindowsActionController(ActionController):
    """
    PC-Steuerung über pyautogui, pygetwindow und pycaw.

    Plattform: Windows only.
    pycaw wird lazy importiert da es COM-Objekte benötigt.
    """

    def __init__(self) -> None:
        _check_platform()
        self._volume_interface = None

    # ------------------------------------------------------------------
    # Lautstärke – lazy init (COM muss im gleichen Thread bleiben)
    # ------------------------------------------------------------------

    def _get_volume_interface(self):
        """Lazy-Init des pycaw Volume-Interface."""
        if self._volume_interface is None:
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None
            )
            self._volume_interface = interface.QueryInterface(IAudioEndpointVolume)
        return self._volume_interface

    # ------------------------------------------------------------------
    # Tastatur
    # ------------------------------------------------------------------

    def press_key(self, key: str) -> None:
        logger.debug("press_key: %s", key)
        pyautogui.press(key)

    def type_text(self, text: str, interval: float = 0.02) -> None:
        logger.debug("type_text: %s Zeichen", len(text))
        pyautogui.typewrite(text, interval=interval)

    def hotkey(self, *keys: str) -> None:
        logger.debug("hotkey: %s", "+".join(keys))
        pyautogui.hotkey(*keys)

    # ------------------------------------------------------------------
    # Maus
    # ------------------------------------------------------------------

    def move_mouse(self, x: int, y: int, duration: float = 0.25) -> None:
        logger.debug("move_mouse: (%d, %d)", x, y)
        pyautogui.moveTo(x, y, duration=duration)

    def click(self, x: int | None = None, y: int | None = None,
              button: str = "left") -> None:
        logger.debug("click: (%s, %s) button=%s", x, y, button)
        pyautogui.click(x=x, y=y, button=button)

    # ------------------------------------------------------------------
    # Fenster
    # ------------------------------------------------------------------

    def list_windows(self) -> list[WindowInfo]:
        windows = []
        for w in gw.getAllWindows():
            if w.title.strip():
                windows.append(WindowInfo(title=w.title, handle=w._hWnd))
        return windows

    def _find_window(self, title: str) -> gw.Win32Window | None:
        """Sucht ein Fenster per Teilstring (case-insensitive)."""
        title_lower = title.lower()
        for w in gw.getAllWindows():
            if title_lower in w.title.lower() and w.title.strip():
                return w
        return None

    def focus_window(self, title: str) -> bool:
        w = self._find_window(title)
        if w is None:
            logger.warning("Fenster nicht gefunden: %s", title)
            return False
        try:
            if w.isMinimized:
                w.restore()
            w.activate()
            logger.info("Fenster fokussiert: %s", w.title)
            return True
        except Exception as e:
            logger.error("Fenster-Fokus fehlgeschlagen: %s", e)
            return False

    def minimize_window(self, title: str) -> bool:
        w = self._find_window(title)
        if w is None:
            return False
        try:
            w.minimize()
            return True
        except Exception as e:
            logger.error("Minimize fehlgeschlagen: %s", e)
            return False

    def maximize_window(self, title: str) -> bool:
        w = self._find_window(title)
        if w is None:
            return False
        try:
            w.maximize()
            return True
        except Exception as e:
            logger.error("Maximize fehlgeschlagen: %s", e)
            return False

    # ------------------------------------------------------------------
    # Lautstärke
    # ------------------------------------------------------------------

    def get_volume(self) -> float:
        vol = self._get_volume_interface()
        level = vol.GetMasterVolumeLevelScalar()
        logger.debug("get_volume: %.2f", level)
        return float(level)

    def set_volume(self, level: float) -> None:
        if not 0.0 <= level <= 1.0:
            raise ValueError(f"Volume level muss zwischen 0.0 und 1.0 liegen, war: {level}")
        vol = self._get_volume_interface()
        vol.SetMasterVolumeLevelScalar(level, None)
        logger.info("set_volume: %.2f", level)

    def mute(self, state: bool = True) -> None:
        vol = self._get_volume_interface()
        vol.SetMute(int(state), None)
        logger.info("mute: %s", state)
