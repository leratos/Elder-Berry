# Phase 55 – audioop / pydub Migration für Python 3.13

**Status:** Konzept (2026-04-15)
**Priorität:** Mittel – Blocker für RPi5 Bookworm-Update auf Python 3.13
**Branch:** noch keiner – wird in eigener Phase implementiert

## Problem

`pydub` importiert in `pydub/utils.py` unconditional `audioop` aus der Stdlib.
In Python 3.13 wurde das `audioop`-Modul **vollständig entfernt** (PEP 594
"Dead batteries"). Damit gilt:

- Tower + Laptop laufen aktuell auf Python 3.12 → noch unproblematisch,
  aber DeprecationWarning bei jedem Testlauf.
- RPi5 läuft laut `CLAUDE.md` auf System-Python 3.13 (Bookworm) → sobald
  `audio_converter.py` dort einen Pfad mit `from pydub import AudioSegment`
  nimmt, gibt es einen `ImportError`. Das betrifft vermutlich noch nicht den
  RPi5-Code direkt (audio_converter wird hauptsächlich auf Tower verwendet),
  ist aber eine tickende Uhr.

Aktuelle Belegstellen (nur 2):
- `src/elder_berry/comms/audio_converter.py:80` (`to_ogg_opus`)
- `src/elder_berry/comms/audio_converter.py:118` (`get_duration_ms`)

Beide Stellen verwenden pydub nur für **zwei Dinge**:
1. Konvertierung WAV → OGG/Opus (delegiert intern an ffmpeg-Subprozess)
2. Duration-Auslese in Millisekunden

## Optionen

### Option A – `audioop-lts` Backport
- Eigenständiges PyPI-Paket, das `audioop` als reine C-Extension nachliefert
- Quick-Fix: `audioop-lts` in optionale Gruppe `windows`/`tts-neural` → pydub
  funktioniert weiter wie bisher, kein Code-Change
- **Nachteil:** Wir hängen weiter an einem unmaintained Modul (`pydub` selbst
  hat seit 2021 keinen Release mehr). Verlängert das Problem, löst es nicht.
- **Aufwand:** ~5 Minuten

### Option B – pydub komplett ersetzen
Da wir nur zwei Funktionen brauchen, ist pydub Overkill. Direkt-ffmpeg-Aufruf:

```python
import subprocess, json
def to_ogg_opus(input_path, output_path, bitrate="32k"):
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path),
         "-c:a", "libopus", "-b:a", bitrate, str(output_path)],
        check=True, capture_output=True,
    )
    return output_path, _ffprobe_duration_ms(output_path)

def _ffprobe_duration_ms(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return int(float(json.loads(out)["format"]["duration"]) * 1000)
```

- **Vorteil:** Keine Python-Audio-Lib mehr nötig, ffmpeg ist eh
  Pflicht-Dependency, eine Code-Schicht weniger
- **Nachteil:** Zwei zusätzliche `ffprobe`-Aufrufe pro Konvertierung
  (Subprozess-Overhead ~30-50ms, vernachlässigbar)
- **Aufwand:** ~30 Minuten + Tests anpassen

### Option C – `soundfile` + manuelle Duration
- `soundfile` (libsndfile) kann WAV lesen und Duration liefern, aber
  **keine** ogg/opus-Encoding (libsndfile-Build hängt davon ab)
- Würde trotzdem zusätzlich ffmpeg-Subprozess für Encoding brauchen → kein
  klarer Vorteil gegenüber Option B
- **Verwerfen.**

## Empfehlung

**Option B**. Begründung:

1. pydub ist seit ~5 Jahren unmaintained und schleppt nur eine veraltete
   Stdlib-Abhängigkeit nach
2. Wir nutzen <1% der pydub-API
3. `audioop-lts` (Option A) löst nichts strategisch, sondern verschiebt nur
4. ffmpeg ist sowieso harte Voraussetzung – die Annahme ist also schon getroffen

## Aufgaben

- [ ] `audio_converter.py:to_ogg_opus()` direkt auf `subprocess.run(['ffmpeg', ...])` umstellen
- [ ] `audio_converter.py:get_duration_ms()` auf `ffprobe` umstellen
- [ ] `_ffmpeg_available` Check um `_ffprobe_available` ergänzen
- [ ] `pydub` aus `pyproject.toml` entfernen (welche optionale Gruppe?)
- [ ] `tests/test_audio_converter.py` anpassen – ffmpeg-Mocks statt pydub-Mocks
- [ ] Smoke-Test mit echter WAV-Datei auf Tower
- [ ] Smoke-Test auf RPi5 (Python 3.13!) – das ist der eigentliche Acceptance-Test

## Offene Fragen

1. Gibt es noch andere Codepfade (außer `audio_converter.py`), die pydub
   transitiv über andere Pakete laden? `grep -r pydub` in `.venv/Lib/site-packages`
   klären.
2. Wie testet man `subprocess.run`-Aufrufe sauber? Bisheriger Mock-Stil in
   `test_audio_converter.py` nutzt direkt pydub-Mock – muss umgestellt werden.
3. RPi5-Konfiguration: läuft `audio_converter.py` dort tatsächlich? Falls nein,
   reicht es, das Problem auf Tower/Laptop zu fixen und für RPi5 vorzusorgen.

## Nicht-Ziele

- Audio-Bearbeitung in Python (Filter, Effekte) – brauchen wir nicht
- Streaming-Konvertierung – die zwei Belegstellen sind File-basiert
