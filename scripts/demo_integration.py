"""Live-Integration-Test: Assistant + Simulator + alle Komponenten.

Startet den RPi5-Simulator im Hintergrund und verbindet den Assistant
mit einem RobotClient. Testet den vollen Flow:
  Input → LLM → Aktion → Robot → TTS → Avatar

Verwendung:
    python scripts/demo_integration.py              # Mit Mock-LLM
    python scripts/demo_integration.py --ollama      # Mit echtem Ollama
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time

import httpx
import uvicorn

# Projekt-Imports
from elder_berry.actions.db import ActionsDB
from elder_berry.character.saleria import SaleriaEngine
from elder_berry.core.assistant import Assistant
from elder_berry.llm.base import LLMClient
from elder_berry.robot.client import RobotClient
from elder_berry.robot.simulator import create_simulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("demo_integration")

SIMULATOR_HOST = "127.0.0.1"
SIMULATOR_PORT = 8321  # Nicht 8000, um Konflikte zu vermeiden


# ---------------------------------------------------------------------------
# Mock-LLM für Tests ohne Ollama
# ---------------------------------------------------------------------------

class DemoMockLLM(LLMClient):
    """Mock-LLM der Robot-Aktionen aus dem Input ableitet."""

    def generate(self, prompt: str, *, system: str = "") -> str:
        lower = prompt.lower()

        if "vorwärts" in lower or "fahr" in lower:
            return json.dumps({
                "action": "robot_drive",
                "params": {"direction": "forward", "speed": 0.7},
                "response": "[motivated] Auf geht's, ich fahre vorwärts!",
            })
        if "links" in lower:
            return json.dumps({
                "action": "robot_drive",
                "params": {"direction": "left", "speed": 0.5},
                "response": "[cheerful] Okay, ich biege links ab!",
            })
        if "rechts" in lower:
            return json.dumps({
                "action": "robot_drive",
                "params": {"direction": "right", "speed": 0.5},
                "response": "[cheerful] Nach rechts, verstanden!",
            })
        if "stopp" in lower or "halt" in lower:
            return json.dumps({
                "action": "robot_stop",
                "params": {"reason": "user_command"},
                "response": "[neutral] Angehalten.",
            })
        if "akku" in lower or "batterie" in lower:
            return json.dumps({
                "action": None, "params": {},
                "response": "[thoughtful] Lass mich den Akku-Status prüfen...",
            })
        return json.dumps({
            "action": None, "params": {},
            "response": "[neutral] Verstanden. Was soll ich tun?",
        })

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Mock ActionController (kein echter PC-Zugriff im Test)
# ---------------------------------------------------------------------------

class DemoMockController:
    """Dummy-Controller der nichts tut."""
    def press_key(self, key: str) -> None: pass
    def type_text(self, text: str) -> None: pass
    def hotkey(self, *keys: str) -> None: pass
    def set_volume(self, level: float) -> None: pass
    def mute(self, state: bool = True) -> None: pass
    def focus_window(self, title: str) -> bool: return False
    def minimize_window(self, title: str) -> bool: return False
    def maximize_window(self, title: str) -> bool: return False
    def list_windows(self) -> list: return []
    def get_volume(self) -> float: return 0.5


# ---------------------------------------------------------------------------
# Simulator-Thread
# ---------------------------------------------------------------------------

def start_simulator_background() -> threading.Thread:
    """Startet den Simulator-Server in einem Daemon-Thread."""
    sim = create_simulator(host=SIMULATOR_HOST, port=SIMULATOR_PORT)
    config = uvicorn.Config(
        sim.app, host=SIMULATOR_HOST, port=SIMULATOR_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread


def wait_for_simulator(timeout: float = 5.0) -> bool:
    """Wartet bis der Simulator erreichbar ist."""
    deadline = time.monotonic() + timeout
    url = f"http://{SIMULATOR_HOST}:{SIMULATOR_PORT}/health"
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    return False


# ---------------------------------------------------------------------------
# Automatischer Test-Durchlauf
# ---------------------------------------------------------------------------

def run_automated_tests(assistant: Assistant, robot: RobotClient) -> None:
    """Führt automatische Testszenarien durch."""
    print("\n" + "=" * 60)
    print("  AUTOMATISCHER INTEGRATIONS-TEST")
    print("=" * 60)

    scenarios = [
        ("Fahr vorwärts", "robot_drive"),
        ("Biege links ab", "robot_drive"),
        ("Stopp!", "robot_stop"),
        ("Wie ist der Akku?", None),
        ("Hallo!", None),
    ]

    passed = 0
    failed = 0

    for user_input, expected_action in scenarios:
        print(f"\n--- Input: \"{user_input}\" ---")
        result = assistant.process(user_input)

        # Status vom Simulator holen
        status = robot.get_status()

        print(f"  Antwort:  {result.response}")
        print(f"  Emotion:  {result.emotion}")
        print(f"  Aktion:   {result.action_executed}")
        print(f"  Erfolg:   {result.action_success}")
        print(f"  Motor:    {status.current_direction} "
              f"(aktiv={status.motors_active})")
        print(f"  Avatar:   {status.avatar_emotion} "
              f"(speaking={status.avatar_speaking})")
        print(f"  Akku:     {status.battery.percentage}% "
              f"({status.battery.voltage}V)")

        # Prüfungen
        ok = True
        if expected_action and result.action_executed != expected_action:
            print(f"  FEHLER: Erwartete Aktion '{expected_action}', "
                  f"bekam '{result.action_executed}'")
            ok = False
        if expected_action and not result.action_success:
            print(f"  FEHLER: Aktion nicht erfolgreich")
            ok = False

        if ok:
            print("  OK")
            passed += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  Ergebnis: {passed}/{passed + failed} bestanden")
    if failed:
        print(f"  {failed} FEHLGESCHLAGEN")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Interaktiver Modus
# ---------------------------------------------------------------------------

def run_interactive(assistant: Assistant, robot: RobotClient) -> None:
    """Interaktiver Modus: Eingabe → Verarbeitung → Status-Anzeige."""
    print("\n" + "=" * 60)
    print("  INTERAKTIVER MODUS")
    print("  Befehle: 'fahr vorwärts', 'stopp', 'akku', 'quit'")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            break

        result = assistant.process(user_input)
        status = robot.get_status()

        print(f"  Saleria [{result.emotion}]: {result.response}")
        if result.action_executed:
            ok = "OK" if result.action_success else "FEHLER"
            print(f"  Aktion: {result.action_executed} → {ok}")
        print(f"  Robot: Motor={status.current_direction} "
              f"Akku={status.battery.percentage}%")

    print("\nBye!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Elder-Berry Integration Demo")
    parser.add_argument(
        "--ollama", action="store_true",
        help="Echtes Ollama LLM statt Mock verwenden",
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true",
        help="Interaktiver Modus statt automatischem Test",
    )
    args = parser.parse_args()

    # 1. Simulator starten
    print("Starte RPi5-Simulator...")
    start_simulator_background()
    if not wait_for_simulator():
        print("FEHLER: Simulator nicht erreichbar!")
        sys.exit(1)
    print(f"Simulator läuft auf {SIMULATOR_HOST}:{SIMULATOR_PORT}")

    # 2. LLM wählen
    if args.ollama:
        from elder_berry.llm.ollama_client import OllamaClient
        llm = OllamaClient()
        print("LLM: Ollama (phi4:14b)")
    else:
        llm = DemoMockLLM()
        print("LLM: Mock (Demo-Modus)")

    # 3. Komponenten aufbauen
    robot = RobotClient(
        base_url=f"http://{SIMULATOR_HOST}:{SIMULATOR_PORT}",
    )
    character = SaleriaEngine()
    actions_db = ActionsDB()
    controller = DemoMockController()

    assistant = Assistant(
        llm=llm,
        actions_db=actions_db,
        controller=controller,
        character=character,
        robot=robot,
    )

    # 4. Health-Check
    health = robot.health()
    print(f"Robot Health: {health.status} ({health.hostname})")
    battery = robot.get_battery()
    print(f"Robot Akku: {battery.percentage}% ({battery.voltage}V)")

    # 5. Test oder interaktiv
    try:
        if args.interactive:
            run_interactive(assistant, robot)
        else:
            run_automated_tests(assistant, robot)
    finally:
        robot.close()
        print("\nRobotClient geschlossen.")


if __name__ == "__main__":
    main()
