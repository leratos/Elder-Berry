#!/usr/bin/env python3
"""Standalone Hall-Sensor Test – A3144 via lgpio.

Verkabelung A3144 → RPi5 (flache Seite zu dir, Beschriftung lesbar):
    Pin 1 (links)  → 3.3V  (Pin 1)
    Pin 2 (mitte)  → GND   (Pin 9 oder 14)
    Pin 3 (rechts) → GPIO 24 (Pin 18)

Interner Pull-up wird aktiviert. A3144 Output:
    HIGH (1) = kein Magnet
    LOW  (0) = Magnet erkannt (Südpol zur bedruckten Seite)

Verwendung:
    python scripts/test_hall.py             # Continuous polling
    python scripts/test_hall.py --pin 25    # Anderer GPIO-Pin
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import lgpio
except ImportError:
    print("ERROR: lgpio nicht verfügbar.")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="A3144 Hall-Sensor Test")
    parser.add_argument(
        "--pin",
        type=int,
        default=24,
        help="GPIO-Pin (BCM, default: 24)",
    )
    args = parser.parse_args()

    pin = args.pin
    print(f"A3144 Hall-Sensor Test")
    print(f"  GPIO: {pin} (Pin {pin})")
    print(f"  HIGH = kein Magnet, LOW = Magnet erkannt")
    print(f"  Strg+C zum Beenden\n")

    chip = lgpio.gpiochip_open(0)
    lgpio.gpio_claim_input(chip, pin, lgpio.SET_PULL_UP)

    last_state = -1
    trigger_count = 0

    try:
        while True:
            state = lgpio.gpio_read(chip, pin)

            if state != last_state:
                trigger_count += 1 if state == 0 else 0
                status = "🧲 MAGNET ERKANNT" if state == 0 else "   kein Magnet"
                print(f"  [{trigger_count:3d}] GPIO {pin} = {state}  {status}")
                last_state = state

            time.sleep(0.01)  # 10ms polling

    except KeyboardInterrupt:
        print(f"\n  Beendet. {trigger_count} Auslösungen erkannt.")
    finally:
        lgpio.gpiochip_close(chip)


if __name__ == "__main__":
    main()
