"""Live Avatar + TTS Demo: Saleria spricht und zeigt Emotionen.

Ablauf:
1. Ollama wird entladen (VRAM freigeben)
2. XTTS v2 wird geladen
3. PyGame-Fenster öffnet sich mit Saleria
4. Terminal: Text eingeben → Saleria spricht + Avatar zeigt Emotion + Lip-Sync
5. Bei "exit": Alles herunterfahren

Steuerung:
- Text eingeben + Enter → Saleria spricht mit aktueller Emotion
- "emo" → Emotion wählen
- [emotion] Text → Emotion inline wechseln (z.B. "[angry] Das nervt!")
- "exit" → Beenden
"""
import os
import queue
import sys
import threading
from pathlib import Path

os.environ["COQUI_TOS_AGREED"] = "1"

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

from elder_berry.character.base import Emotion
from elder_berry.character.saleria import SaleriaEngine
from elder_berry.tts.coqui_engine import CoquiTTSEngine
from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

EMOTIONS = list(Emotion)
ASSETS_DIR = Path(__file__).parent.parent / "src" / "elder_berry" / "avatar" / "assets"


def unload_ollama() -> None:
    """Entlädt Ollama-Modell falls es läuft."""
    try:
        r = httpx.post(
            "http://localhost:11434/api/generate",
            json={"model": "phi4:14b", "prompt": "", "keep_alive": 0},
            timeout=10,
        )
        if r.status_code == 200:
            print("  Ollama phi4:14b entladen.")
    except Exception:
        print("  Ollama nicht erreichbar (OK).")


def print_emotions() -> None:
    """Zeigt die verfügbaren Emotionen."""
    print("\nVerfügbare Emotionen:")
    for i, emo in enumerate(EMOTIONS, 1):
        marker = " *" if emo == Emotion.NEUTRAL else ""
        print(f"  {i:2d}. {emo.value}{marker}")
    print("  (* = Standard)")


def select_emotion() -> Emotion:
    """Lässt den Nutzer eine Emotion wählen."""
    while True:
        choice = input("Emotion [1-10, Enter=neutral]: ").strip()
        if not choice:
            return Emotion.NEUTRAL
        try:
            idx = int(choice)
            if 1 <= idx <= len(EMOTIONS):
                return EMOTIONS[idx - 1]
        except ValueError:
            for emo in EMOTIONS:
                if emo.value == choice.lower():
                    return emo
        print(f"  Ungueltig. 1-{len(EMOTIONS)} oder Emotionsname.")


def input_thread_fn(cmd_queue: queue.Queue, stop_event: threading.Event) -> None:
    """Liest Benutzereingaben in einem separaten Thread."""
    while not stop_event.is_set():
        try:
            text = input("\n> ").strip()
            cmd_queue.put(text)
            if text.lower() == "exit":
                break
        except EOFError:
            cmd_queue.put("exit")
            break


def main() -> None:
    print("=" * 60)
    print("  Saleria Berry - Avatar + TTS Live Demo")
    print("=" * 60)

    # Vorbereitung
    print("\nVorbereitung...")
    unload_ollama()

    character = SaleriaEngine()
    voice_map = {}
    for emotion in Emotion:
        sample = character.get_voice_sample(emotion)
        if sample:
            voice_map[emotion.value] = sample

    default_wav = voice_map.get("neutral")
    print(f"  Voice-Samples: {len(voice_map)} Emotionen")

    # TTS laden
    print("\nLade XTTS v2...")
    engine = CoquiTTSEngine(
        voice_map=voice_map,
        default_speaker_wav=default_wav,
        language="de",
    )
    engine.load()
    print(f"  XTTS auf: {engine._device}")

    # Avatar starten
    print("\nStarte Avatar...")
    renderer = LayeredSpriteRenderer(assets_dir=ASSETS_DIR)
    renderer.initialize(512, 1024)

    current_emotion = Emotion.NEUTRAL
    renderer.show_emotion(current_emotion)

    print_emotions()
    print(f"\nAktuelle Emotion: {current_emotion.value}")
    print("Eingabe: Text → Saleria spricht | 'emo' → Emotion | 'exit' → Ende")
    print("Inline: [angry] Das nervt! | [cheerful] Super!")

    # Input-Thread starten
    cmd_queue: queue.Queue[str] = queue.Queue()
    stop_event = threading.Event()
    input_t = threading.Thread(
        target=input_thread_fn, args=(cmd_queue, stop_event), daemon=True,
    )
    input_t.start()

    # TTS-Thread Referenz
    tts_thread: threading.Thread | None = None
    speaking = False

    try:
        while renderer.is_running():
            # Avatar Frame rendern
            renderer.update()

            # Prüfe ob TTS fertig ist
            if speaking and tts_thread and not tts_thread.is_alive():
                renderer.show_speaking(False)
                speaking = False

            # Prüfe auf neue Eingaben
            try:
                text = cmd_queue.get_nowait()
            except queue.Empty:
                continue

            if text.lower() == "exit":
                break

            if text.lower() == "emo":
                current_emotion = select_emotion()
                renderer.show_emotion(current_emotion)
                print(f"  Emotion: {current_emotion.value}")
                continue

            if not text:
                continue

            # Inline Emotion-Tag parsen
            for emo in EMOTIONS:
                tag = f"[{emo.value}]"
                if text.lower().startswith(tag):
                    current_emotion = emo
                    text = text[len(tag):].strip()
                    renderer.show_emotion(current_emotion)
                    print(f"  Emotion: {current_emotion.value}")
                    break

            if not text:
                continue

            # Warte bis vorheriges TTS fertig ist
            if tts_thread and tts_thread.is_alive():
                print("  Warte auf vorherige Sprachausgabe...")
                tts_thread.join()
                renderer.show_speaking(False)

            print(f"  [{current_emotion.value}] \"{text}\"")

            # Avatar Emotion setzen + Lip-Sync starten
            renderer.show_emotion(current_emotion)
            renderer.show_speaking(True)
            speaking = True

            # TTS im Hintergrund
            def speak_task(t=text, e=current_emotion.value):
                try:
                    engine.speak(t, emotion=e)
                except Exception as err:
                    print(f"  TTS-Fehler: {err}")

            tts_thread = threading.Thread(target=speak_task, daemon=True)
            tts_thread.start()

    except KeyboardInterrupt:
        print("\n\nAbgebrochen.")

    # Aufräumen
    print("\nFahre herunter...")
    stop_event.set()
    if tts_thread and tts_thread.is_alive():
        tts_thread.join(timeout=5)
    renderer.shutdown()
    engine.unload()
    print("Fertig!")


if __name__ == "__main__":
    main()
