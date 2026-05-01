"""Live TTS Demo: Text eingeben, Emotion wählen, Saleria spricht.

Ablauf:
1. Ollama wird entladen (VRAM freigeben)
2. XTTS v2 wird geladen
3. Loop: Emotion wählen → Text eingeben → Saleria spricht
4. Bei "exit": XTTS entladen, fertig
"""

import os
import sys
from pathlib import Path

os.environ["COQUI_TOS_AGREED"] = "1"

# Projekt-Root zum Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

from elder_berry.character.base import Emotion
from elder_berry.character.saleria import SaleriaEngine
from elder_berry.tts.coqui_engine import CoquiTTSEngine

EMOTIONS = list(Emotion)


def unload_ollama() -> None:
    """Entlädt Ollama-Modell falls es läuft (VRAM freigeben)."""
    try:
        r = httpx.post(
            "http://localhost:11434/api/generate",
            json={"model": "phi4:14b", "prompt": "", "keep_alive": 0},
            timeout=10,
        )
        if r.status_code == 200:
            print("  Ollama phi4:14b entladen.")
        else:
            print("  Ollama nicht erreichbar oder Modell nicht geladen.")
    except Exception:
        print("  Ollama nicht erreichbar (OK, weiter).")


def print_emotions() -> None:
    """Zeigt die verfügbaren Emotionen mit Nummern."""
    print("\nVerfügbare Emotionen:")
    for i, emo in enumerate(EMOTIONS, 1):
        marker = " *" if emo == Emotion.NEUTRAL else ""
        print(f"  {i:2d}. {emo.value}{marker}")
    print("  (* = Standard bei Enter)")


def select_emotion() -> Emotion:
    """Lässt den Nutzer eine Emotion per Nummer wählen."""
    while True:
        choice = input("\nEmotion [1-10, Enter=neutral]: ").strip()
        if not choice:
            return Emotion.NEUTRAL
        try:
            idx = int(choice)
            if 1 <= idx <= len(EMOTIONS):
                return EMOTIONS[idx - 1]
            print(f"  Bitte 1-{len(EMOTIONS)} eingeben.")
        except ValueError:
            # Direkte Eingabe des Namens erlauben
            for emo in EMOTIONS:
                if emo.value == choice.lower():
                    return emo
            print(f"  Unbekannte Emotion: {choice}")


def main() -> None:
    print("=" * 60)
    print("  Saleria Berry - Live TTS Demo")
    print("  Tippe Text ein, waehle Emotion, hoere Saleria sprechen.")
    print("  'exit' zum Beenden, 'emo' fuer Emotionsliste")
    print("=" * 60)

    # Ollama entladen
    print("\nVorbereitung...")
    unload_ollama()

    # Voice-Map aus SaleriaEngine laden
    character = SaleriaEngine()
    voice_map = {}
    for emotion in Emotion:
        sample = character.get_voice_sample(emotion)
        if sample:
            voice_map[emotion.value] = sample

    default_wav = voice_map.get("neutral")
    print(f"  Voice-Samples: {len(voice_map)} Emotionen geladen")

    # XTTS laden
    print("\nLade XTTS v2 Modell (kann beim ersten Mal dauern)...")
    engine = CoquiTTSEngine(
        voice_map=voice_map,
        default_speaker_wav=default_wav,
        language="de",
    )
    engine.load()
    print(f"  XTTS geladen auf: {engine._device}")

    print_emotions()

    # Aktuelle Emotion merken
    current_emotion = Emotion.NEUTRAL
    print(f"\nAktuelle Emotion: {current_emotion.value}")

    while True:
        text = input("\nText (oder 'exit'/'emo'): ").strip()

        if not text:
            continue
        if text.lower() == "exit":
            break
        if text.lower() == "emo":
            current_emotion = select_emotion()
            print(f"  Emotion gesetzt: {current_emotion.value}")
            continue

        # Emotion wechseln mit [emotion] Prefix
        for emo in EMOTIONS:
            tag = f"[{emo.value}]"
            if text.lower().startswith(tag):
                current_emotion = emo
                text = text[len(tag) :].strip()
                print(f"  Emotion gewechselt: {current_emotion.value}")
                break

        if not text:
            continue

        print(f'  Saleria ({current_emotion.value}): "{text}"')
        print("  Generiere Audio...", end="", flush=True)
        try:
            engine.speak(text, emotion=current_emotion.value)
            print(" OK")
        except Exception as e:
            print(f" FEHLER: {e}")

    # Aufräumen
    print("\nEntlade XTTS...")
    engine.unload()
    print("Fertig. Tschuess!")


if __name__ == "__main__":
    main()
