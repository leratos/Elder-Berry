"""Tests fuer --profile in scripts/start_rpi5.py (Phase 111, E2, Ae9).

* frame zweigt ab, BEVOR uvicorn, RobotServer oder das Avatar-Display
  importiert werden (Subprozess-Probe).
* Regressionstest "Stamm-Wiring unveraendert": ohne --profile werden genau
  die Komponenten wie vor Phase 111 gebaut (Konstruktoren gepatcht).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
START_RPI5 = PROJECT_ROOT / "scripts" / "start_rpi5.py"


def _load():
    spec = importlib.util.spec_from_file_location("start_rpi5_profile_test", START_RPI5)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Argumente
# ---------------------------------------------------------------------------


def test_profile_default_is_stamm(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["start_rpi5.py"])
    args = _load().parse_args()
    assert args.profile == "stamm"
    assert args.frame_rotation is None
    assert (args.width, args.height, args.rotation) == (720, 1280, 180)


def test_frame_options_parse(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "start_rpi5.py",
            "--profile",
            "frame",
            "--frame-rotation",
            "270",
            "--frame-view",
            "ueberblendung",
            "--frame-video-driver",
            "dummy",
        ],
    )
    args = _load().parse_args()
    assert args.profile == "frame"
    assert args.frame_rotation == 270
    assert args.frame_view == "ueberblendung"


def test_invalid_frame_rotation_rejected(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["start_rpi5.py", "--frame-rotation", "45"])
    with pytest.raises(SystemExit):
        _load().parse_args()


# ---------------------------------------------------------------------------
# Frueh-Ausstieg: keine Server-/Avatar-Importe
# ---------------------------------------------------------------------------

_PROBE = textwrap.dedent(
    """
    import importlib.util, sys, types
    fake = types.ModuleType("elder_berry.room_display.frame_profile")
    def run_frame(args):
        heavy = [m for m in ("uvicorn", "elder_berry.robot.server",
                             "elder_berry.robot.rpi5_avatar",
                             "elder_berry.avatar.layered_renderer", "pygame")
                 if m in sys.modules]
        print("HEAVY", heavy, "PROFILE", args.profile)
        return 7
    fake.run_frame = run_frame
    sys.modules["elder_berry.room_display.frame_profile"] = fake
    spec = importlib.util.spec_from_file_location("start_rpi5", sys.argv[1])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.argv = ["start_rpi5.py", "--profile", "frame"]
    module.main()
    """
)


def test_frame_branches_before_server_imports():
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(START_RPI5)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=PROJECT_ROOT,
    )
    assert proc.returncode == 7, proc.stdout + proc.stderr  # Exit-Code von run_frame
    assert "HEAVY [] PROFILE frame" in proc.stdout, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# Regressionstest Stamm-Wiring (Ae9)
# ---------------------------------------------------------------------------


class _Recorder:
    """Ersetzt eine Klasse und merkt sich die Konstruktor-Aufrufe."""

    def __init__(self, name, calls, **attrs):
        self._name = name
        self._calls = calls
        self._attrs = attrs

    def __call__(self, *args, **kwargs):
        self._calls.append((self._name, args, kwargs))
        instance = SimpleNamespace(**self._attrs)
        instance.start = lambda: self._calls.append((f"{self._name}.start", (), {}))
        instance.stop = lambda: self._calls.append((f"{self._name}.stop", (), {}))
        instance.close = lambda: self._calls.append((f"{self._name}.close", (), {}))
        return instance


@pytest.fixture
def stamm_wiring(monkeypatch):
    calls: list[tuple[str, tuple, dict]] = []
    rec = lambda name, **attrs: _Recorder(name, calls, **attrs)  # noqa: E731
    monkeypatch.setattr(
        "elder_berry.robot.rpi5_avatar.RPi5AvatarDisplay", rec("Avatar")
    )
    monkeypatch.setattr("elder_berry.robot.simulator.SimulatedMotors", rec("Motors"))
    monkeypatch.setattr("elder_berry.robot.simulator.SimulatedSensors", rec("Sensors"))
    monkeypatch.setattr(
        "elder_berry.robot.camera_controller.RPi5Camera",
        rec("Camera", is_available=lambda: True),
    )
    monkeypatch.setattr(
        "elder_berry.robot.turntable_controller.RPi5TurntableController",
        rec("Turntable"),
    )
    monkeypatch.setattr(
        "elder_berry.robot.harmony_adapter.HarmonyAdapter", rec("Harmony")
    )
    monkeypatch.setattr(
        "elder_berry.core.secret_store.SecretStore",
        rec("SecretStore", get_or_none=lambda k: None),
    )
    monkeypatch.setattr(
        "elder_berry.robot.server.RobotServer", rec("RobotServer", app="APP")
    )
    monkeypatch.setattr(
        "uvicorn.run", lambda app, **kw: calls.append(("uvicorn.run", (app,), kw))
    )
    monkeypatch.setattr("signal.signal", lambda signum, handler: None)
    monkeypatch.delenv("ELDER_BERRY_ROBOT_TOKEN", raising=False)
    monkeypatch.delitem(
        sys.modules, "elder_berry.room_display.frame_profile", raising=False
    )
    monkeypatch.setattr(sys, "argv", ["start_rpi5.py"])
    return calls


def test_stamm_wiring_unchanged(stamm_wiring):
    from elder_berry.avatar.layered_renderer import CrossfadeScope

    _load().main()
    calls = stamm_wiring
    names = [name for name, _, _ in calls]

    assert names == [
        "Avatar",
        "Motors",
        "Sensors",
        "Camera",
        "Turntable",
        "Harmony",
        "SecretStore",
        "RobotServer",
        "Avatar.start",
        "uvicorn.run",
        "Avatar.stop",
        "Turntable.close",
    ]
    by_name = {name: (args, kwargs) for name, args, kwargs in calls}
    assert by_name["Avatar"][1] == {
        "width": 720,
        "height": 1280,
        "fullscreen": True,
        "rotation": 180,
        "crossfade_scope": CrossfadeScope.FULL,
    }
    assert by_name["Camera"][1] == {"resolution": (1920, 1080)}
    assert by_name["Turntable"][1] == {"step_delay_ms": 2.0}
    assert by_name["Harmony"][1] == {"hub_ip": "192.168.50.133"}
    server_kwargs = by_name["RobotServer"][1]
    assert server_kwargs["hostname"] == "elder-berry-rpi5"
    assert server_kwargs["service_name"] == "elder-berry"
    assert server_kwargs["robot_token"] is None
    assert server_kwargs["alexa_verifier"] is None
    assert server_kwargs["camera"] is not None
    assert server_kwargs["turntable"] is not None
    assert server_kwargs["harmony"] is not None
    assert by_name["uvicorn.run"] == (
        ("APP",),
        {"host": "127.0.0.1", "port": 8000, "log_level": "info"},
    )
    # Das Profil stamm laedt das Raumdisplay nicht.
    assert "elder_berry.room_display.frame_profile" not in sys.modules
