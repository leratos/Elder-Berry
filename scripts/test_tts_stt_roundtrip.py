"""TTS→STT Roundtrip-Test: Text generieren, transkribieren, vergleichen.

Ablauf:
1. CoquiTTSEngine lädt XTTS v2 auf GPU
2. Generiert 3 WAV-Dateien mit verschiedenen Emotionen
3. XTTS wird entladen
4. faster-whisper transkribiert die WAVs
5. Vergleich: Eingangstext vs. erkannter Text
"""
import sys
from pathlib import Path

# Projekt-Root zum Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from elder_berry.character.base import Emotion
from elder_berry.character.saleria import SaleriaEngine
from elder_berry.tts.coqui_engine import CoquiTTSEngine

OUTPUT_DIR = Path(__file__).parent.parent / "test_output"

# Testsätze: (Text, Emotion)
TEST_CASES = [
    ("Hallo, ich bin Saleria Berry. Willkommen in meiner Welt.", "neutral"),
    ("Das war wirklich fantastisch! Ich bin begeistert!", "cheerful"),
    ("Oh, das hast du jetzt nicht wirklich gesagt, oder?", "sarcastic"),
]


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    # --- Phase 1: TTS ---
    print("=" * 60)
    print("Phase 1: Text-to-Speech (XTTS v2)")
    print("=" * 60)

    character = SaleriaEngine()
    voice_map = {}
    for emotion in Emotion:
        sample = character.get_voice_sample(emotion)
        if sample:
            voice_map[emotion.value] = sample

    default_wav = voice_map.get("neutral")
    engine = CoquiTTSEngine(
        voice_map=voice_map,
        default_speaker_wav=default_wav,
        language="de",
    )

    print(f"\nVoice-Map: {len(voice_map)} Emotionen")
    print(f"Default WAV: {default_wav}")
    print("Lade XTTS-Modell...")
    engine.load()
    print(f"Modell geladen auf: {engine._device}\n")

    generated_files = []
    for i, (text, emotion) in enumerate(TEST_CASES, 1):
        output_path = OUTPUT_DIR / f"test_{i}_{emotion}.wav"
        print(f"[{i}/{len(TEST_CASES)}] Emotion: {emotion}")
        print(f"  Input:  \"{text}\"")
        print(f"  Output: {output_path.name}")
        engine.generate_audio(text, output_path, emotion=emotion)
        generated_files.append((text, emotion, output_path))
        print(f"  OK ({output_path.stat().st_size / 1024:.1f} KB)\n")

    print("Entlade XTTS...")
    engine.unload()
    print("XTTS entladen.\n")

    # --- Phase 2: STT ---
    print("=" * 60)
    print("Phase 2: Speech-to-Text (faster-whisper)")
    print("=" * 60)

    from faster_whisper import WhisperModel

    print("\nLade Whisper-Modell (medium)...")
    whisper = WhisperModel("medium", device="cuda", compute_type="float16")
    print("Whisper geladen.\n")

    results = []
    for i, (original_text, emotion, audio_path) in enumerate(generated_files, 1):
        print(f"[{i}/{len(generated_files)}] Transkribiere: {audio_path.name}")
        segments, info = whisper.transcribe(str(audio_path), language="de")
        transcribed = " ".join(seg.text.strip() for seg in segments).strip()
        print(f"  Original:      \"{original_text}\"")
        print(f"  Transkribiert: \"{transcribed}\"")

        # Einfacher Vergleich: Wörter-Überlappung
        orig_words = set(original_text.lower().replace(".", "").replace(",", "").replace("!", "").replace("?", "").split())
        trans_words = set(transcribed.lower().replace(".", "").replace(",", "").replace("!", "").replace("?", "").split())
        if orig_words:
            overlap = len(orig_words & trans_words) / len(orig_words) * 100
        else:
            overlap = 0.0
        print(f"  Wort-Überlappung: {overlap:.0f}%\n")
        results.append((emotion, original_text, transcribed, overlap))

    # --- Zusammenfassung ---
    print("=" * 60)
    print("Zusammenfassung")
    print("=" * 60)
    for emotion, original, transcribed, overlap in results:
        status = "PASS" if overlap >= 50 else "FAIL"
        print(f"  [{status}] {emotion:12s} | Überlappung: {overlap:5.1f}% | \"{transcribed[:50]}\"")

    avg_overlap = sum(r[3] for r in results) / len(results)
    print(f"\n  Durchschnitt: {avg_overlap:.1f}%")
    print(f"  Audio-Dateien: {OUTPUT_DIR}")

    del whisper
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("\nWhisper entladen. VRAM freigegeben.")


if __name__ == "__main__":
    main()
