# Saleria Voice Samples

Reference-Audio-Dateien fuer den fiktiven V-Tuber-Charakter **Saleria Berry**.
Die WAVs werden vom XTTS v2 Voice-Cloning-Pfad als Referenz-Stimme geladen
(siehe `src/elder_berry/tts/xtts_engine.py`) und liefern fuer jede Emotion
einen kurzen Audio-Schnipsel.

## Herkunft

Die Samples wurden vom Maintainer (Lera) **synthetisch erzeugt** -- ueber
mehrere TTS-Tools und anschliessende Bearbeitung -- und stellen explizit
**keine reale Person** dar. Es handelt sich nicht um Voice-Cloning eines
existierenden Menschen, sondern um eine bewusst konstruierte
Charakter-Stimme fuer eine fiktive Figur.

Konsequenzen:
- Keine Persoenlichkeitsrechte Dritter beruehrt.
- Keine externe Lizenz (Voice-Actor, Stockaudio o.ae.) zu beachten.
- Saleria gehoert als Charakter zum Projekt; Stimme + Avatar bilden
  eine Einheit.

## Lizenz

MIT, identisch zum Rest des Repositorys (siehe [`LICENSE`](../../../../LICENSE)).
Damit darf der Inhalt unter den MIT-Bedingungen weiterverwendet werden --
inklusive der Pflicht, Copyright-Hinweis und Lizenztext mitzuliefern.

Hinweis: Wer die Samples zusammen mit XTTS v2 als Reference-Audio benutzt,
gibt damit aber automatisch die XTTS-eigene Lizenz (Coqui Public Model
License, CPML, **non-commercial**) auf den daraus erzeugten Output mit.
Die Lizenz der WAVs ist davon unabhaengig MIT.

## Enthaltene Dateien

Eine Datei pro Emotion -- die Namen entsprechen den Saleria-Emotionen,
die der Avatar/TTS-Stack ansteuert:

| Datei | Emotion |
|---|---|
| `saleria-neutral.wav` | neutral |
| `saleria-cheerful.wav` | cheerful |
| `saleria-sarcastic.wav` | sarcastic |
| `saleria-motivated.wav` | motivated |
| `saleria-thoughtful.wav` | thoughtful |
| `saleria-whisper.wav` | whisper |
| `saleria-shy.wav` | shy |
| `saleria-depressed.wav` | depressed |
| `saleria-sad.wav` | sad |
| `saleria-angry.wav` | angry |

Alle Dateien sind Mono-WAVs in der vom XTTS-Loader erwarteten Sample-Rate.
Wer sie ersetzen oder erweitern will: identisches Naming-Schema verwenden,
sonst greift der Emotion-Lookup ins Leere.
