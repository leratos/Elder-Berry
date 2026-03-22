# Phase 27 – Drehteller-Steuerung (28BYJ-48 Stepper + A3144 Hall-Sensor)

## Übersicht

Software-Integration des Drehtellers in die Projekt-Architektur.
Hardware ist bereits getestet und funktionsfähig (test_stepper.py, test_hall.py).

### Hardware-Fakten

- **Stepper**: 28BYJ-48 + ULN2003 Driver, Half-Step-Sequenz, 4096 Steps/Umdrehung
- **Hall-Sensor**: A3144, GPIO 24, interner Pull-up, HIGH = kein Magnet, LOW = Magnet
- **Magnet**: Neodym 4×1.5mm, montiert am Kabelausgang (1 cm versetzt)
- **GPIO**: 17/27/22/23 (Stepper IN1–IN4), 24 (Hall-Sensor)
- **Rotationslimit**: ±180° (USB-C Kabel-Constraint)
- **Home-Position**: Hall-Sensor am Kabelausgang → 0° = Kabelausgang

### Architektur-Pattern

Folgt dem etablierten Pattern: ABC + echte Implementierung + Simulator + DI.
Referenz: CameraController / RPi5Camera / SimulatedCamera.

---

## 1. TurntableController ABC + RPi5TurntableController

**Datei**: `src/elder_berry/robot/turntable_controller.py`

**Plattformhinweis**: RPi5TurntableController nur auf RPi5 (Linux mit lgpio) lauffähig.

### Threading-Modell

Der 28BYJ-48 wird per Blocking-Loop angesteuert (time.sleep pro Step).Rotation läuft daher in einem **Background-Thread**, damit der FastAPI-Server
weiterhin Requests annehmen kann.

- `rotate_to()` / `rotate_by()` / `home()` starten einen Worker-Thread
- `is_moving` → True solange Thread läuft
- `stop()` setzt `_stop_requested`-Flag → Thread prüft es pro Step und bricht ab
- Nur eine Rotation gleichzeitig (Lock oder Prüfung auf `is_moving`)

### Homing-Algorithmus

1. Prüfe ob bereits auf Home (Hall-Sensor LOW) → wenn ja, setze Position = 0, fertig
2. Drehe **immer links** (CCW, negative Steps)
3. Jeden Step: Hall-Sensor lesen
4. Hall LOW → Stopp, Position = 0 Steps, `_is_homed = True`
5. **Sicherheitslimit**: 4200 Steps (~369°) ohne Trigger → `RuntimeError`
   (> 360° bedeutet Sensor defekt oder Magnet fehlt)
6. Nach Homing: Spulen stromlos schalten (Strom sparen)

### Soft-Limits (±180°)

- Position wird in Steps getrackt (int), relativ zu Home (0)
- +2048 Steps = +180° (CW, "rechts")
- −2048 Steps = −180° (CCW, "links")
- `rotate_to(degrees)` rechnet Grad → Steps, clampt auf [−2048, +2048]
- `rotate_by(degrees)` addiert zum aktuellen Ziel, clampt Ergebnis
- Bei Clamp: Warnung loggen, auf clamped Position fahren (kein Error)
### Klassen-Signatur

```python
"""TurntableController – Drehteller-Steuerung (28BYJ-48 + A3144 Hall-Sensor)."""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Hardware-Konstanten
STEPS_PER_REV = 4096           # Half-Steps pro volle Umdrehung
STEP_DELAY_MS = 2.0            # Millisekunden zwischen Steps (28BYJ-48 safe minimum)
MAX_DEGREES = 180.0            # ±180° Rotationslimit
HOMING_STEP_LIMIT = 4200       # Sicherheitslimit Homing (~369°)

# GPIO Pins (BCM)
STEPPER_PINS = (17, 27, 22, 23)  # IN1, IN2, IN3, IN4
HALL_PIN = 24                     # A3144 Output

# Half-Step Sequenz
HALF_STEP_SEQ = [
    (1, 0, 0, 0),
    (1, 1, 0, 0),
    (0, 1, 0, 0),
    (0, 1, 1, 0),
    (0, 0, 1, 0),
    (0, 0, 1, 1),
    (0, 0, 0, 1),
    (1, 0, 0, 1),
]

def degrees_to_steps(degrees: float) -> int:
    """Konvertiert Grad in Half-Steps (gerundet)."""
    return round(degrees / 360.0 * STEPS_PER_REV)


def steps_to_degrees(steps: int) -> float:
    """Konvertiert Half-Steps in Grad."""
    return steps / STEPS_PER_REV * 360.0


class TurntableController(ABC):
    """ABC für Drehteller-Steuerung."""

    @abstractmethod
    def home(self) -> None:
        """Homing-Sequenz: dreht bis Hall-Sensor auslöst → Position 0°.

        Raises:
            RuntimeError: Wenn Homing fehlschlägt (Sensor defekt, Magnet fehlt).
            RuntimeError: Wenn bereits eine Rotation läuft.
        """
        ...

    @abstractmethod
    def rotate_to(self, degrees: float) -> None:
        """Dreht auf absolute Position (relativ zu Home).
        Args:
            degrees: Zielposition in Grad (wird auf ±180° geclampt).

        Raises:
            RuntimeError: Wenn nicht gehomed.
            RuntimeError: Wenn bereits eine Rotation läuft.
        """
        ...

    @abstractmethod
    def rotate_by(self, degrees: float) -> None:
        """Dreht relativ zur aktuellen Position.

        Args:
            degrees: Rotation in Grad (positiv = CW/rechts, negativ = CCW/links).
                     Ergebnis wird auf ±180° geclampt.

        Raises:
            RuntimeError: Wenn nicht gehomed.
            RuntimeError: Wenn bereits eine Rotation läuft.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Bricht die aktuelle Rotation ab. No-op wenn keine Rotation läuft."""
        ...
    @abstractmethod
    def get_position(self) -> float:
        """Gibt aktuelle Position in Grad zurück. NaN wenn nicht gehomed."""
        ...

    @property
    @abstractmethod
    def is_homed(self) -> bool:
        """True wenn Homing erfolgreich durchgeführt wurde."""
        ...

    @property
    @abstractmethod
    def is_moving(self) -> bool:
        """True wenn eine Rotation läuft."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Ressourcen freigeben (GPIO, Threads)."""
        ...


class RPi5TurntableController(TurntableController):
    """Echte Drehteller-Implementierung für RPi5 (lgpio).

    Plattformhinweis: Nur auf RPi5 (Linux mit lgpio) lauffähig.
    """
    def __init__(
        self,
        step_delay_ms: float = STEP_DELAY_MS,
        auto_home: bool = False,
    ) -> None:
        self._step_delay_ms = step_delay_ms
        self._position_steps: int = 0
        self._is_homed: bool = False
        self._is_moving: bool = False
        self._stop_requested: bool = False
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

        # GPIO initialisieren
        import lgpio
        self._lgpio = lgpio
        self._chip = lgpio.gpiochip_open(0)
        for pin in STEPPER_PINS:
            lgpio.gpio_claim_output(self._chip, pin, 0)
        lgpio.gpio_claim_input(self._chip, HALL_PIN, lgpio.SET_PULL_UP)

        logger.info(
            "RPi5TurntableController initialisiert: Stepper=%s, Hall=GPIO%d",
            STEPPER_PINS, HALL_PIN,
        )
        if auto_home:
            self.home()
    def _read_hall(self) -> bool:
        """Liest Hall-Sensor. Returns True wenn Magnet erkannt (LOW)."""
        return self._lgpio.gpio_read(self._chip, HALL_PIN) == 0

    def _step_motor(self, steps: int) -> int:
        """Bewegt Motor um N Half-Steps. Prüft _stop_requested pro Step.
        Returns: Tatsächlich ausgeführte Steps (mit Vorzeichen)."""
        direction = 1 if steps > 0 else -1
        seq = HALF_STEP_SEQ if direction == 1 else HALF_STEP_SEQ[::-1]
        delay_s = self._step_delay_ms / 1000.0
        executed = 0
        for i in range(abs(steps)):
            if self._stop_requested:
                break
            pattern = seq[i % len(seq)]
            for pin_idx, pin in enumerate(STEPPER_PINS):
                self._lgpio.gpio_write(self._chip, pin, pattern[pin_idx])
            time.sleep(delay_s)
            executed += 1
        # Spulen stromlos
        for pin in STEPPER_PINS:
            self._lgpio.gpio_write(self._chip, pin, 0)
        return executed * direction
    def _step_until_hall(self, max_steps: int) -> int:
        """Dreht CCW bis Hall-Sensor auslöst. Für Homing.
        Returns: Ausgeführte Steps (negativ, da CCW).
        Raises: RuntimeError wenn max_steps erreicht."""
        seq_reversed = HALF_STEP_SEQ[::-1]
        delay_s = self._step_delay_ms / 1000.0
        executed = 0
        for i in range(max_steps):
            if self._stop_requested:
                for pin in STEPPER_PINS:
                    self._lgpio.gpio_write(self._chip, pin, 0)
                raise RuntimeError("Homing abgebrochen (stop() aufgerufen)")
            pattern = seq_reversed[i % len(seq_reversed)]
            for pin_idx, pin in enumerate(STEPPER_PINS):
                self._lgpio.gpio_write(self._chip, pin, pattern[pin_idx])
            time.sleep(delay_s)
            executed += 1
            if self._read_hall():
                for pin in STEPPER_PINS:
                    self._lgpio.gpio_write(self._chip, pin, 0)
                return -executed
        for pin in STEPPER_PINS:
            self._lgpio.gpio_write(self._chip, pin, 0)
        raise RuntimeError(
            f"Homing fehlgeschlagen: Hall-Sensor nach {max_steps} Steps "
            f"(~{steps_to_degrees(max_steps):.0f}°) nicht ausgelöst. "
            f"Sensor defekt oder Magnet fehlt?"
        )
    def _run_home(self) -> None:
        """Worker-Thread für Homing."""
        try:
            self._is_moving = True
            self._stop_requested = False
            if self._read_hall():
                self._position_steps = 0
                self._is_homed = True
                logger.info("Homing: bereits auf Home-Position")
                return
            steps = self._step_until_hall(HOMING_STEP_LIMIT)
            self._position_steps = 0
            self._is_homed = True
            logger.info("Homing erfolgreich: %d Steps gedreht", abs(steps))
        except RuntimeError as e:
            logger.error("Homing fehlgeschlagen: %s", e)
            self._is_homed = False
        finally:
            self._is_moving = False

    def _run_rotate(self, target_steps: int) -> None:
        """Worker-Thread für Rotation."""
        try:
            self._is_moving = True
            self._stop_requested = False
            delta = target_steps - self._position_steps
            if delta == 0:
                return
            executed = self._step_motor(delta)
            self._position_steps += executed            if self._stop_requested:
                logger.info("Rotation abgebrochen bei %.1f°",
                            steps_to_degrees(self._position_steps))
            else:
                logger.info("Rotation abgeschlossen: %.1f°",
                            steps_to_degrees(self._position_steps))
        finally:
            self._is_moving = False

    def _start_worker(self, target: callable, daemon: bool = True) -> None:
        """Startet Worker-Thread. Raises RuntimeError wenn bereits Rotation läuft."""
        if self._is_moving:
            raise RuntimeError("Rotation läuft bereits – erst stop() aufrufen")
        self._worker = threading.Thread(target=target, daemon=daemon)
        self._worker.start()

    def home(self) -> None:
        self._start_worker(self._run_home)

    def rotate_to(self, degrees: float) -> None:
        if not self._is_homed:
            raise RuntimeError("Nicht gehomed – erst home() aufrufen")
        clamped = max(-MAX_DEGREES, min(MAX_DEGREES, degrees))
        if clamped != degrees:
            logger.warning("rotate_to(%.1f°) geclampt auf %.1f°", degrees, clamped)
        target_steps = degrees_to_steps(clamped)
        self._start_worker(lambda: self._run_rotate(target_steps))
    def rotate_by(self, degrees: float) -> None:
        if not self._is_homed:
            raise RuntimeError("Nicht gehomed – erst home() aufrufen")
        current_deg = steps_to_degrees(self._position_steps)
        target_deg = current_deg + degrees
        clamped = max(-MAX_DEGREES, min(MAX_DEGREES, target_deg))
        if clamped != target_deg:
            logger.warning("rotate_by(%.1f°) → Ziel %.1f° geclampt auf %.1f°",
                           degrees, target_deg, clamped)
        target_steps = degrees_to_steps(clamped)
        self._start_worker(lambda: self._run_rotate(target_steps))

    def stop(self) -> None:
        if self._is_moving:
            self._stop_requested = True
            if self._worker and self._worker.is_alive():
                self._worker.join(timeout=5.0)

    def get_position(self) -> float:
        if not self._is_homed:
            return float("nan")
        return steps_to_degrees(self._position_steps)

    @property
    def is_homed(self) -> bool:
        return self._is_homed

    @property
    def is_moving(self) -> bool:
        return self._is_moving
    def close(self) -> None:
        self.stop()
        if hasattr(self, "_chip"):
            for pin in STEPPER_PINS:
                self._lgpio.gpio_write(self._chip, pin, 0)
            self._lgpio.gpiochip_close(self._chip)
            logger.info("RPi5TurntableController: GPIO freigegeben")
```

---

## 2. SimulatedTurntable

**Datei**: `src/elder_berry/robot/simulator.py` (ergänzen)

Simuliert Drehteller-Verhalten ohne GPIO. Synchron (kein Thread nötig).

```python
class SimulatedTurntable(TurntableController):
    """Simulierter Drehteller für Tower-Tests ohne Hardware."""

    def __init__(self) -> None:
        self._position_steps: int = 0
        self._is_homed: bool = False
        self._is_moving: bool = False

    def home(self) -> None:
        self._position_steps = 0
        self._is_homed = True
        logger.info("[SIM] Turntable: Homed")
    def rotate_to(self, degrees: float) -> None:
        if not self._is_homed:
            raise RuntimeError("Nicht gehomed – erst home() aufrufen")
        clamped = max(-MAX_DEGREES, min(MAX_DEGREES, degrees))
        self._position_steps = degrees_to_steps(clamped)
        logger.info("[SIM] Turntable: rotate_to(%.1f°)", clamped)

    def rotate_by(self, degrees: float) -> None:
        if not self._is_homed:
            raise RuntimeError("Nicht gehomed – erst home() aufrufen")
        current = steps_to_degrees(self._position_steps)
        target = max(-MAX_DEGREES, min(MAX_DEGREES, current + degrees))
        self._position_steps = degrees_to_steps(target)
        logger.info("[SIM] Turntable: rotate_by(%.1f°) → %.1f°", degrees, target)

    def stop(self) -> None:
        self._is_moving = False
        logger.info("[SIM] Turntable: Stop")

    def get_position(self) -> float:
        if not self._is_homed:
            return float("nan")
        return steps_to_degrees(self._position_steps)

    @property
    def is_homed(self) -> bool:
        return self._is_homed

    @property
    def is_moving(self) -> bool:
        return self._is_moving
    def close(self) -> None:
        pass
```

---

## 3. Server-Endpoints (RPi5 FastAPI)

**Datei**: `src/elder_berry/robot/server.py` (ergänzen)

### Pydantic-Models

```python
class TurntableRotateRequest(BaseModel):
    """Request: Drehteller rotieren."""
    target_degrees: float | None = None    # Absolute Position
    relative_degrees: float | None = None  # Relative Rotation
    # Genau eines von beiden muss gesetzt sein
```

### Neue Endpoints

```
POST /turntable/rotate  → TurntableRotateRequest → ApiResponse
POST /turntable/home    → (kein Body)             → ApiResponse
POST /turntable/stop    → (kein Body)             → ApiResponse
GET  /turntable/status  → dict
```

### DI-Erweiterung

```python
class RobotServer:
    def __init__(
        self,
        motors: MotorController,
        avatar: AvatarDisplay,
        sensors: SensorManager,
        camera: CameraController | None = None,
        turntable: TurntableController | None = None,  # NEU
        hostname: str = "elder-berry-rpi",
    ) -> None:
```
### Endpoint-Implementierung

```python
# --- Drehteller ---

@self.app.post("/turntable/rotate")
def turntable_rotate(request: TurntableRotateRequest) -> dict:
    if not self._turntable:
        return asdict(ApiResponse(success=False, message="Kein Drehteller"))
    if request.target_degrees is None and request.relative_degrees is None:
        return asdict(ApiResponse(
            success=False,
            message="target_degrees oder relative_degrees erforderlich",
        ))
    try:
        if request.target_degrees is not None:
            self._turntable.rotate_to(request.target_degrees)
            msg = f"Rotation zu {request.target_degrees}° gestartet"
        else:
            self._turntable.rotate_by(request.relative_degrees)
            msg = f"Rotation um {request.relative_degrees}° gestartet"
        return asdict(ApiResponse(success=True, message=msg))
    except RuntimeError as e:
        return asdict(ApiResponse(success=False, message=str(e)))
@self.app.post("/turntable/home")
def turntable_home() -> dict:
    if not self._turntable:
        return asdict(ApiResponse(success=False, message="Kein Drehteller"))
    try:
        self._turntable.home()
        return asdict(ApiResponse(success=True, message="Homing gestartet"))
    except RuntimeError as e:
        return asdict(ApiResponse(success=False, message=str(e)))

@self.app.post("/turntable/stop")
def turntable_stop() -> dict:
    if not self._turntable:
        return asdict(ApiResponse(success=False, message="Kein Drehteller"))
    self._turntable.stop()
    return asdict(ApiResponse(success=True, message="Rotation gestoppt"))

@self.app.get("/turntable/status")
def turntable_status() -> dict:
    if not self._turntable:
        return {"available": False, "reason": "Kein Drehteller konfiguriert"}
    return {
        "available": True,
        "is_homed": self._turntable.is_homed,
        "is_moving": self._turntable.is_moving,
        "position_degrees": self._turntable.get_position(),
    }
```
---

## 4. Client-Erweiterung (Tower-Seite)

**Datei**: `src/elder_berry/robot/client.py` (ergänzen)

```python
# --- Drehteller ---

def rotate_turntable(
    self,
    target_degrees: float | None = None,
    relative_degrees: float | None = None,
) -> ApiResponse:
    """Drehteller rotieren (absolut oder relativ)."""
    payload = {}
    if target_degrees is not None:
        payload["target_degrees"] = target_degrees
    if relative_degrees is not None:
        payload["relative_degrees"] = relative_degrees
    r = self._client.post("/turntable/rotate", json=payload)
    r.raise_for_status()
    return ApiResponse(**r.json())

def home_turntable(self) -> ApiResponse:
    """Homing-Sequenz des Drehtellers starten."""
    r = self._client.post("/turntable/home")
    r.raise_for_status()
    return ApiResponse(**r.json())
def stop_turntable(self) -> ApiResponse:
    """Drehteller-Rotation sofort stoppen."""
    r = self._client.post("/turntable/stop")
    r.raise_for_status()
    return ApiResponse(**r.json())

def turntable_status(self) -> dict:
    """Drehteller-Status abfragen."""
    r = self._client.get("/turntable/status")
    r.raise_for_status()
    return r.json()
```

---

## 5. TurntableCommandHandler

**Datei**: `src/elder_berry/comms/commands/turntable_commands.py`

### Commands

| Command | Beispiel | Aktion |
|---------|----------|--------|
| `drehteller home` | "drehteller home" | Homing-Sequenz |
| `turntable_rotate_by` | "dreh dich um 90 grad" | rotate_by |
| `turntable_rotate_to` | "dreh dich auf 45 grad" | rotate_to |
| `turntable_rotate_dir` | "dreh dich nach links" | rotate_by(-90) |
| `turntable_look_dir` | "schau nach rechts" | rotate_by(90) |
| `drehteller stopp` | "drehteller stopp" | stop() |
| `drehteller status` | "drehteller status" | get_position + Status |
### Regex-Patterns

```python
# "dreh dich um 90 grad (nach links/rechts)"
ROTATE_BY_PATTERN = re.compile(
    r"^dreh\s+dich\s+(?:um\s+)?(\d+)\s*(?:grad|°)"
    r"(?:\s+(?:nach\s+)?(links|rechts))?$",
    re.IGNORECASE,
)

# "dreh dich auf 45 grad" / "dreh auf position 90"
ROTATE_TO_PATTERN = re.compile(
    r"^dreh\s+(?:dich\s+)?auf\s+(?:position\s+)?(-?\d+)\s*(?:grad|°)?$",
    re.IGNORECASE,
)

# "dreh dich nach links/rechts"
ROTATE_DIRECTION_PATTERN = re.compile(
    r"^dreh\s+dich\s+nach\s+(links|rechts)$",
    re.IGNORECASE,
)

# "schau nach links/rechts"
LOOK_DIRECTION_PATTERN = re.compile(
    r"^schau\s+nach\s+(links|rechts)$",
    re.IGNORECASE,
)
```

**Keyword-Kollision – Analyse:**
- "schau nach links/rechts" → TurntableCommandHandler (exakter Match auf "schau nach" + Richtung)
- "schau mal was/ob" → CameraCommandHandler (Pattern: "schau mal" + Frage)
- Kein Overlap: "schau nach" ≠ "schau mal". Trotzdem: TurntableCommandHandler
  muss **vor** CameraCommandHandler in der Handler-Liste stehen.
### Keywords

```python
@property
def keywords(self) -> dict[str, list[str]]:
    return {
        "turntable_rotate_dir": [
            "dreh dich",
            "schau nach links", "schau nach rechts",
            "guck nach links", "guck nach rechts",
            "dreh nach links", "dreh nach rechts",
        ],
        "drehteller home": [
            "home position", "heimposition",
            "drehteller home", "drehteller zurück",
        ],
        "drehteller stopp": [
            "drehteller stopp", "drehteller stop",
            "hör auf zu drehen",
        ],
        "drehteller status": [
            "drehteller status", "drehteller position",
            "wo schaust du hin", "in welche richtung",
        ],
    }
```

### Vollständige Klassen-Signatur

```python
"""TurntableCommandHandler – Drehteller-Befehle."""
from __future__ import annotations
import logging
import re
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.robot.client import RobotClient

logger = logging.getLogger(__name__)

DEFAULT_ROTATION_DEGREES = 90.0


class TurntableCommandHandler(CommandHandler):
    """Handler für Drehteller-Befehle."""

    def __init__(self, robot_client: RobotClient | None = None) -> None:
        self._robot = robot_client

    @property
    def simple_commands(self) -> set[str]:
        return {"drehteller home", "drehteller stopp", "drehteller status"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (ROTATE_BY_PATTERN, "turntable_rotate_by", False, False),
            (ROTATE_TO_PATTERN, "turntable_rotate_to", False, False),            (ROTATE_DIRECTION_PATTERN, "turntable_rotate_dir", False, False),
            (LOOK_DIRECTION_PATTERN, "turntable_look_dir", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "drehteller home: Drehteller auf Home-Position fahren",
            "dreh dich um <grad> [nach links/rechts]: Drehteller relativ drehen",
            "dreh dich nach links/rechts: 90° in Richtung drehen",
            "dreh dich auf <grad>: Drehteller auf Position fahren",
            "drehteller stopp: Rotation sofort abbrechen",
            "drehteller status: Aktuelle Position anzeigen",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if not self._robot:
            return CommandResult(
                command=command, success=False,
                text="RobotClient nicht verfügbar (RPi5 nicht verbunden).",
            )
        if command == "drehteller home":
            return self._cmd_home()
        if command == "drehteller stopp":
            return self._cmd_stop()
        if command == "drehteller status":
            return self._cmd_status()
        if command in ("turntable_rotate_by", "turntable_rotate_to",
                       "turntable_rotate_dir", "turntable_look_dir"):
            return self._cmd_rotate(command, raw_text)        return CommandResult(
            command=command, success=False,
            text=f"Unbekannter Command: {command}",
        )

    def _cmd_home(self) -> CommandResult:
        try:
            resp = self._robot.home_turntable()
            return CommandResult(command="drehteller home",
                                success=resp.success, text=resp.message)
        except Exception as e:
            return CommandResult(command="drehteller home", success=False,
                                text=f"Homing fehlgeschlagen: {e}")

    def _cmd_stop(self) -> CommandResult:
        try:
            resp = self._robot.stop_turntable()
            return CommandResult(command="drehteller stopp",
                                success=resp.success, text=resp.message)
        except Exception as e:
            return CommandResult(command="drehteller stopp", success=False,
                                text=f"Stopp fehlgeschlagen: {e}")

    def _cmd_status(self) -> CommandResult:
        try:
            status = self._robot.turntable_status()
            if not status.get("available"):
                return CommandResult(command="drehteller status",
                                    success=False, text="Drehteller nicht verfügbar.")
            pos = status.get("position_degrees", 0)            homed = status.get("is_homed", False)
            moving = status.get("is_moving", False)
            parts = []
            if not homed:
                parts.append("⚠️ Nicht gehomed")
            else:
                parts.append(f"Position: {pos:.1f}°")
            if moving:
                parts.append("🔄 Dreht sich gerade")
            return CommandResult(command="drehteller status",
                                success=True, text=" | ".join(parts))
        except Exception as e:
            return CommandResult(command="drehteller status", success=False,
                                text=f"Status-Abfrage fehlgeschlagen: {e}")

    def _cmd_rotate(self, command: str, raw_text: str) -> CommandResult:
        normalized = raw_text.strip().lower()

        # "dreh dich nach links/rechts" oder "schau nach links/rechts"
        if command in ("turntable_rotate_dir", "turntable_look_dir"):
            match = (ROTATE_DIRECTION_PATTERN.match(normalized)
                     or LOOK_DIRECTION_PATTERN.match(normalized))
            if not match:
                return CommandResult(command=command, success=False,
                                    text="Richtung nicht erkannt.")
            direction = match.group(1)
            degrees = DEFAULT_ROTATION_DEGREES
            if direction == "links":
                degrees = -degrees
            return self._execute_rotate_by(degrees)
        # "dreh dich um 90 grad (nach links/rechts)"
        if command == "turntable_rotate_by":
            match = ROTATE_BY_PATTERN.match(normalized)
            if not match:
                return CommandResult(command=command, success=False,
                                    text="Grad-Angabe nicht erkannt.")
            degrees = float(match.group(1))
            direction = match.group(2)  # "links" / "rechts" / None
            if direction == "links":
                degrees = -degrees
            return self._execute_rotate_by(degrees)

        # "dreh dich auf 45 grad"
        if command == "turntable_rotate_to":
            match = ROTATE_TO_PATTERN.match(normalized)
            if not match:
                return CommandResult(command=command, success=False,
                                    text="Position nicht erkannt.")
            degrees = float(match.group(1))
            return self._execute_rotate_to(degrees)

        return CommandResult(command=command, success=False,
                             text=f"Rotation-Command nicht erkannt: {command}")

    def _execute_rotate_by(self, degrees: float) -> CommandResult:
        try:
            resp = self._robot.rotate_turntable(relative_degrees=degrees)
            return CommandResult(command="turntable_rotate",
                                success=resp.success, text=resp.message)        except Exception as e:
            return CommandResult(command="turntable_rotate", success=False,
                                text=f"Rotation fehlgeschlagen: {e}")

    def _execute_rotate_to(self, degrees: float) -> CommandResult:
        try:
            resp = self._robot.rotate_turntable(target_degrees=degrees)
            return CommandResult(command="turntable_rotate",
                                success=resp.success, text=resp.message)
        except Exception as e:
            return CommandResult(command="turntable_rotate", success=False,
                                text=f"Rotation fehlgeschlagen: {e}")
```

---

## 6. Integration

### 6.1 remote_commands.py

Änderungen:

```python
# Import hinzufügen
from elder_berry.comms.commands.turntable_commands import TurntableCommandHandler

# Im __init__:
self._turntable = TurntableCommandHandler(
    robot_client=robot_client,
)

# In der Handler-Liste (VOR _camera wegen "schau nach" Pattern-Priorität):
self._handlers: list[CommandHandler] = [
    self._system,
    self._weather,
    self._calendar,    self._mail,
    self._file,
    self._process,
    self._turntable,   # NEU – vor _camera wegen "schau nach" Patterns
    self._camera,
]
```

HELP_TEXT ergänzen (nach "Kamera:"-Block):

```
Drehteller:
  drehteller home – Home-Position anfahren
  dreh dich um <grad> [nach links/rechts] – Relativ drehen
  dreh dich nach links/rechts – 90° in Richtung drehen
  dreh dich auf <grad> – Auf absolute Position fahren
  schau nach links/rechts – Drehteller in Richtung drehen
  drehteller stopp – Rotation sofort abbrechen
  drehteller status – Aktuelle Position anzeigen
```

### 6.2 start_rpi5.py

```python
# Nach Kamera-Init, vor RobotServer:

# -- Drehteller (optional) ---------------------------------------------------
turntable = None
try:
    from elder_berry.robot.turntable_controller import RPi5TurntableController
    turntable = RPi5TurntableController(step_delay_ms=2.0)
    logger.info("Drehteller initialisiert (Homing manuell via API)")
except ImportError:
    logger.info("Drehteller: lgpio nicht verfügbar (kein RPi5?)")
except Exception as e:
    logger.warning("Drehteller-Init fehlgeschlagen: %s", e)
# RobotServer – turntable Parameter hinzufügen:
server = RobotServer(
    motors=motors,
    avatar=avatar,
    sensors=sensors,
    camera=camera,
    turntable=turntable,  # NEU
    hostname="elder-berry-rpi5",
)

# Im finally-Block: turntable.close() ergänzen
finally:
    avatar.stop()
    if turntable:
        turntable.close()
    logger.info("RPi5 beendet")
```

**Kein auto_home im Konstruktor!** Homing wird manuell via `/turntable/home` ausgelöst,
damit der Server beim Start nicht blockiert falls der Sensor ein Problem hat.

### 6.3 start_saleria.py

**Keine Änderung nötig.** Der `robot_client` wird bereits an `RemoteCommandHandler`
übergeben. `TurntableCommandHandler` bekommt denselben `robot_client` via DI –
das passiert innerhalb von `RemoteCommandHandler.__init__()`.

### 6.4 simulator.py (create_simulator)

```python
def create_simulator(...) -> RobotServer:
    server = RobotServer(
        motors=SimulatedMotors(),
        avatar=SimulatedAvatar(),
        sensors=SimulatedSensors(),
        turntable=SimulatedTurntable(),  # NEU
        hostname="elder-berry-simulator",
    )
```
---

## 7. Tests

### 7.1 test_turntable_controller.py

Tests für TurntableController ABC + SimulatedTurntable + Hilfsfunktionen.

| # | Test | Beschreibung |
|---|------|-------------|
| 1 | `test_simulated_home` | home() setzt Position auf 0° |
| 2 | `test_simulated_rotate_to` | rotate_to(90) → Position 90° |
| 3 | `test_simulated_rotate_by` | rotate_by(45) + rotate_by(-30) → 15° |
| 4 | `test_simulated_clamp_positive` | rotate_to(200) → clamped auf 180° |
| 5 | `test_simulated_clamp_negative` | rotate_to(-200) → clamped auf -180° |
| 6 | `test_simulated_rotate_by_clamp` | Position 170° + rotate_by(30) → 180° |
| 7 | `test_simulated_not_homed_error` | rotate_to ohne home → RuntimeError |
| 8 | `test_simulated_get_position_nan` | get_position() vor home → NaN |
| 9 | `test_simulated_close` | close() ohne Fehler |
| 10 | `test_degrees_to_steps` | degrees_to_steps(90) → 1024 |
| 11 | `test_steps_to_degrees` | steps_to_degrees(2048) → 180.0 |
| 12 | `test_degrees_to_steps_roundtrip` | degrees → steps → degrees konsistent |

### 7.2 test_turntable_server.py

Server-Endpoint-Tests mit SimulatedTurntable + TestClient.
| # | Test | Beschreibung |
|---|------|-------------|
| 13 | `test_status_no_turntable` | GET /turntable/status ohne Drehteller → available=False |
| 14 | `test_status_not_homed` | Status vor Homing → is_homed=False |
| 15 | `test_home_endpoint` | POST /turntable/home → success |
| 16 | `test_rotate_absolute` | POST /turntable/rotate target_degrees=90 → success |
| 17 | `test_rotate_relative` | POST /turntable/rotate relative_degrees=45 → success |
| 18 | `test_rotate_no_params` | POST /turntable/rotate ohne Body → Fehler |
| 19 | `test_rotate_not_homed` | Rotation ohne Homing → Fehler |
| 20 | `test_stop_endpoint` | POST /turntable/stop → success |
| 21 | `test_status_after_rotate` | Status nach rotate → korrekte Position |

### 7.3 test_turntable_client.py

Client-Tests mit httpx MockTransport.

| # | Test | Beschreibung |
|---|------|-------------|
| 22 | `test_rotate_turntable_absolute` | rotate_turntable(target_degrees=90) → korrekte Payload |
| 23 | `test_rotate_turntable_relative` | rotate_turntable(relative_degrees=45) → korrekte Payload |
| 24 | `test_home_turntable` | home_turntable() → POST /turntable/home |
| 25 | `test_stop_turntable` | stop_turntable() → POST /turntable/stop |
| 26 | `test_turntable_status` | turntable_status() → dict mit Position |

### 7.4 test_turntable_commands.py

CommandHandler-Tests.
| # | Test | Beschreibung |
|---|------|-------------|
| 27 | `test_simple_commands` | "drehteller home/stopp/status" erkannt |
| 28 | `test_pattern_rotate_by` | "dreh dich um 90 grad" → turntable_rotate_by |
| 29 | `test_pattern_rotate_by_links` | "dreh dich um 45 grad nach links" → -45° |
| 30 | `test_pattern_rotate_to` | "dreh dich auf 120 grad" → turntable_rotate_to |
| 31 | `test_pattern_rotate_to_negative` | "dreh dich auf -90 grad" → -90° |
| 32 | `test_pattern_direction_links` | "dreh dich nach links" → -90° |
| 33 | `test_pattern_direction_rechts` | "dreh dich nach rechts" → +90° |
| 34 | `test_pattern_look_links` | "schau nach links" → -90° |
| 35 | `test_pattern_look_rechts` | "schau nach rechts" → +90° |
| 36 | `test_keyword_dreh_dich` | "dreh dich" als Keyword erkannt |
| 37 | `test_keyword_schau_nach` | "schau nach links" als Keyword erkannt |
| 38 | `test_keyword_wo_schaust_du` | "wo schaust du hin" → drehteller status |
| 39 | `test_no_robot_client` | Ohne RobotClient → Fehlertext |
| 40 | `test_home_execute` | home-Command wird ausgeführt |
| 41 | `test_status_execute` | status-Command zeigt Position |
| 42 | `test_no_collision_schau_mal` | "schau mal was" wird NICHT von Turntable gematcht |
| 43 | `test_no_collision_schau_mal_ob` | "schau mal ob" wird NICHT von Turntable gematcht |
| 44 | `test_command_descriptions` | command_descriptions nicht leer |

**Gesamt: 44 Tests**
---

## 8. Datei-Übersicht

### Neue Dateien
- `src/elder_berry/robot/turntable_controller.py` — ABC + RPi5TurntableController (~280 Zeilen)
- `src/elder_berry/comms/commands/turntable_commands.py` — TurntableCommandHandler (~200 Zeilen)
- `tests/test_turntable_controller.py` — 12 Tests
- `tests/test_turntable_server.py` — 9 Tests
- `tests/test_turntable_client.py` — 5 Tests
- `tests/test_turntable_commands.py` — 18 Tests

### Geänderte Dateien
- `src/elder_berry/robot/server.py` — turntable DI + 4 Endpoints + TurntableRotateRequest
- `src/elder_berry/robot/client.py` — 4 Methoden (rotate, home, stop, status)
- `src/elder_berry/robot/simulator.py` — SimulatedTurntable + create_simulator
- `src/elder_berry/comms/remote_commands.py` — Import + DI + Handler-Liste + HELP_TEXT
- `scripts/start_rpi5.py` — RPi5TurntableController Init + close()

### Nicht geändert
- `scripts/start_saleria.py` — robot_client wird bereits durchgereicht
- `src/elder_berry/robot/protocol.py` — kein neues DTO nötig (ApiResponse + dict reichen)

---

## 9. Offene Fragen / Entscheidungen

### Bereits entschieden
- **Homing-Richtung**: Immer links (CCW) – kann schlimmstenfalls ~360° drehen ohne Kabelschaden
- **Auto-Home beim Start**: Nein – manuell via API, damit Server nicht blockiert
- **Rotation-Threading**: Background-Thread pro Rotation, stop-Flag pro Step
- **Soft-Limit**: ±180° mit Clamp + Warnung (kein harter Error)
### Noch offen (für spätere Phasen)
- **Automatisches Homing beim Systemstart**: CalendarWatcher-ähnlicher Autostart?
  Erstmal manuell, kann später ergänzt werden.
- **Kamera-Tracking**: "Dreh dich zum Gesicht" → Kamera + Face Detection → Rotation.
  Eigenständige Phase, nicht Scope von Phase 27.


---

## 10. Hardware-Notiz: USB-C Kabelführung

### Problem
RPi5 sitzt auf dem Drehteller (dreht sich mit), USB-C Stromversorgung muss
vom stationären Teil zum drehenden Teil gelangen. ±180° Rotation darf das
Kabel nicht beschädigen oder an interne Bauteile zerren.

### Lösung: Panel-Mount Buchse + Service-Loop

**Außen (stationär):**
- USB-C Panel-Mount Buchse (Female-to-Female) am stationären Gehäuse
- Montage an einer Wurzel-Außenseite (organisch, versteckt im Design)
- Originales RPi5 27W Netzteil steckt von außen ein
- Bohrung ~24mm für Gewinde/Mutter-Befestigung

**Kabelführung (stationär → drehend):**
- Kurzes, flexibles USB-C Kabel (15-20cm, weiches Silikon/Nylon, min. 3A)
- Von Panel-Mount Buchse durch Kanal im stationären Teil (Wurzel)
- Service-Loop (lockere Schlaufe) im Zwischenraum zwischen den Gehäuseteilen
- Durch abgerundeten Durchbruch (R5 oben+unten) im drehenden Teil nach oben
- In den RPi5 USB-C Power-In

**Zugentlastung:**
- Unten: Panel-Mount Buchse ist verschraubt (mechanisch fixiert)
- Oben: Kabelbinder/Clip am RPi5-Montagerahmen

### Stromrechnung
- RPi5 + Display + Kamera + WiFi: ~1.5A
- ULN2003 + 28BYJ-48 Stepper (über RPi5 5V GPIO): ~0.24A
- Hall-Sensor + Sonstiges: ~0.01A
- **Gesamt: ~1.8A** → PD-Verhandlung nicht zwingend nötig (3A reichen)

### USB-PD Hinweis
Billige Panel-Mount Buchsen leiten oft nicht alle CC-Pins durch →
RPi5 erkennt kein PD, limitiert USB-Ports auf 600mA. Für Elder-Berry
irrelevant (keine stromhungrigen USB-Geräte). Falls nötig:
`usb_max_current_enable=1` in `/boot/firmware/config.txt`.

### Ventilation
Keine Schürze zwischen drehendem und stationärem Teil → offener Spalt
dient als Ventilation für BME280 (Temperatur/Luftdruck/Feuchte).
Schürze wurde bewusst weggelassen um Sensor-Verfälschung durch RPi5-Abwärme
zu vermeiden.

### Bestellliste
- [ ] USB-C Panel-Mount Buchse (Female-to-Female, Gewinde, ~24mm Bohrung)
- [ ] Kurzes flexibles USB-C Kabel (15-20cm, min. 3A, weiches Material)
