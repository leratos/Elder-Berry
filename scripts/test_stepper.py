#!/usr/bin/env python3
"""Standalone Stepper-Motor Test – 28BYJ-48 + ULN2003 via lgpio.

Verkabelung ULN2003 → RPi5:
    IN1 → GPIO 17 (Pin 11)
    IN2 → GPIO 27 (Pin 13)
    IN3 → GPIO 22 (Pin 15)
    IN4 → GPIO 23 (Pin 16)
    VCC → 5V      (Pin 2 oder 4)
    GND → GND     (Pin 6 oder 9)

Verwendung auf RPi5:
    python scripts/test_stepper.py              # 1 volle Umdrehung CW
    python scripts/test_stepper.py --ccw        # 1 volle Umdrehung CCW
    python scripts/test_stepper.py --steps 512  # 512 Half-Steps (~90°)
    python scripts/test_stepper.py --speed 5    # Langsamer (5ms Delay)
    python scripts/test_stepper.py --interactive  # Interaktiver Modus

28BYJ-48 Spezifikationen:
    - Gear Ratio: 64:1 (tatsächlich 63.68395:1)
    - Half-Step Sequenz: 8 Schritte pro Zyklus
    - Steps pro Umdrehung: 4096 Half-Steps (= 64 * 64 / 8 * 8)
    - ~5.625° pro Full-Step, ~2.8125° pro Half-Step
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import lgpio
except ImportError:
    print("ERROR: lgpio nicht verfügbar. Installiere es mit:")
    print("  sudo apt install python3-lgpio")
    sys.exit(1)

# GPIO Pins (BCM-Nummern)
PINS = (17, 27, 22, 23)  # IN1, IN2, IN3, IN4

# Half-Step Sequenz (8 Schritte pro Zyklus, sanftere Bewegung als Full-Step)
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

# 28BYJ-48: 4096 Half-Steps = 1 volle Umdrehung
STEPS_PER_REV = 4096


def setup_gpio() -> int:
    """GPIO-Chip öffnen und Pins als Output konfigurieren."""
    chip = lgpio.gpiochip_open(0)
    for pin in PINS:
        lgpio.gpio_claim_output(chip, pin, 0)
    return chip


def cleanup_gpio(chip: int) -> None:
    """Alle Pins auf 0 setzen und GPIO-Chip schließen."""
    for pin in PINS:
        lgpio.gpio_write(chip, pin, 0)
    lgpio.gpiochip_close(chip)


def step(chip: int, steps: int, delay_ms: float = 2.0) -> None:
    """Bewegt den Motor um die angegebene Anzahl Half-Steps.

    Args:
        chip: lgpio Chip-Handle.
        steps: Anzahl Half-Steps. Positiv = CW, negativ = CCW.
        delay_ms: Verzögerung zwischen Steps in Millisekunden.
                  28BYJ-48 Minimum: ~2ms. Sicher: 3-5ms.
    """
    direction = 1 if steps > 0 else -1
    seq = HALF_STEP_SEQ if direction == 1 else HALF_STEP_SEQ[::-1]
    delay_s = delay_ms / 1000.0

    for i in range(abs(steps)):
        pattern = seq[i % len(seq)]
        for pin_idx, pin in enumerate(PINS):
            lgpio.gpio_write(chip, pin, pattern[pin_idx])
        time.sleep(delay_s)

    # Spulen stromlos schalten (spart Strom, verhindert Erwärmung)
    for pin in PINS:
        lgpio.gpio_write(chip, pin, 0)


def interactive_mode(chip: int, delay_ms: float) -> None:
    """Interaktiver Modus: Motor per Tastatur steuern."""
    print("\n=== Interaktiver Stepper-Test ===")
    print("  r / rechts  → 90° CW")
    print("  l / links   → 90° CCW")
    print("  f / full     → 360° CW")
    print("  b / back     → 360° CCW")
    print("  <zahl>       → N Half-Steps CW (negativ = CCW)")
    print("  q / quit     → Beenden")
    print()

    quarter = STEPS_PER_REV // 4  # 1024 Steps = 90°

    while True:
        try:
            cmd = input("Stepper> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nBeendet.")
            break

        if cmd in ("q", "quit", "exit"):
            break
        elif cmd in ("r", "rechts", "cw"):
            print(f"  → 90° CW ({quarter} Steps)...")
            step(chip, quarter, delay_ms)
        elif cmd in ("l", "links", "ccw"):
            print(f"  → 90° CCW ({quarter} Steps)...")
            step(chip, -quarter, delay_ms)
        elif cmd in ("f", "full", "voll"):
            print(f"  → 360° CW ({STEPS_PER_REV} Steps)...")
            step(chip, STEPS_PER_REV, delay_ms)
        elif cmd in ("b", "back", "zurück"):
            print(f"  → 360° CCW ({STEPS_PER_REV} Steps)...")
            step(chip, -STEPS_PER_REV, delay_ms)
        else:
            try:
                n = int(cmd)
                direction = "CW" if n > 0 else "CCW"
                print(f"  → {abs(n)} Half-Steps {direction}...")
                step(chip, n, delay_ms)
            except ValueError:
                print("  Unbekannter Befehl. Nutze r/l/f/b/<zahl>/q")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="28BYJ-48 Stepper-Motor Test (lgpio)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=STEPS_PER_REV,
        help=f"Anzahl Half-Steps (default: {STEPS_PER_REV} = 1 Umdrehung)",
    )
    parser.add_argument(
        "--ccw",
        action="store_true",
        help="Gegen den Uhrzeigersinn drehen",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=2.0,
        help="Delay zwischen Steps in ms (default: 2.0, langsamer = höher)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interaktiver Modus (Tastatur-Steuerung)",
    )
    args = parser.parse_args()

    print(f"28BYJ-48 Stepper Test")
    print(
        f"  Pins: IN1=GPIO{PINS[0]}, IN2=GPIO{PINS[1]}, "
        f"IN3=GPIO{PINS[2]}, IN4=GPIO{PINS[3]}"
    )
    print(f"  Speed: {args.speed}ms/step")

    chip = setup_gpio()
    print("  GPIO initialisiert ✓")

    try:
        if args.interactive:
            interactive_mode(chip, args.speed)
        else:
            total = -args.steps if args.ccw else args.steps
            direction = "CCW" if args.ccw else "CW"
            degrees = abs(total) / STEPS_PER_REV * 360
            duration = abs(total) * args.speed / 1000

            print(
                f"\n  Drehe {degrees:.1f}° {direction} "
                f"({abs(total)} Steps, ~{duration:.1f}s)..."
            )

            step(chip, total, args.speed)
            print("  Fertig ✓")

    except KeyboardInterrupt:
        print("\n  Abgebrochen!")
    finally:
        cleanup_gpio(chip)
        print("  GPIO aufgeräumt ✓")


if __name__ == "__main__":
    main()
