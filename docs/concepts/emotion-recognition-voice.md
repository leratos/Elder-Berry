# Emotion Recognition (Voice) – Analyse & Konzept

> **Status:** Analyse (kein Implementierungsplan, Entscheidungsgrundlage)
> **Erstellt:** 2026-03-19 (Claude App)
> **Umsetzung:** Offen – abhängig von Ergebnissen dieser Analyse
> **Abhängigkeit:** FasterWhisperEngine (Phase 5), SaleriaEngine (Phase 3)

---

## Ziel

Saleria erkennt die Stimmung des Nutzers aus der Stimme und passt ihren
Antwortton entsprechend an. Kein Sentiment-Analysis auf Text (das macht
das LLM bereits implizit), sondern Audio-basierte Emotionserkennung.

---

## Ist-Zustand: Was haben wir bereits?

### FasterWhisperEngine liefert:
- `TranscriptionResult.confidence` (float 0.0–1.0, aus avg_logprob)
- `TranscriptionResult.segments` (mit Zeitstempeln pro Segment)
- `TranscriptionResult.language` (erkannte Sprache)

### Was davon für Emotionen nutzbar ist:
**Kurz: fast nichts.**

- **confidence (avg_logprob):** Misst wie sicher Whisper sich bei der Transkription ist.
  Niedrige Konfidenz = schlecht erkannt (Nuscheln, Hintergrundgeräusche), NICHT = traurig.
  Ein fröhlicher Mensch der leise spricht hat niedrige Konfidenz.
  Ein wütender Mensch der laut und deutlich schreit hat hohe Konfidenz.
  → **Kein brauchbarer Proxy für Emotionen.**

- **Sprechgeschwindigkeit (aus Segmenten ableitbar):**
  Zeichen/Sekunde pro Segment → schnell = aufgeregt/ängstlich, langsam = traurig/nachdenklich.
  Problem: Extrem grob. Kulturelle/persönliche Baseline fehlt. Stille-Pausen
  (die VAD rausfiltert) sind oft informativer als Sprechgeschwindigkeit.
  → **Schwacher Indikator, allein nicht brauchbar.**

- **Tonhöhe (Pitch):** Whisper liefert KEINEN Pitch-Wert. Müsste separat aus
  dem Audio extrahiert werden (z.B. mit librosa, parselmouth/Praat).
  → **Nicht vorhanden, müsste neu implementiert werden.**

### Fazit Ist-Zustand:
Die bestehende STT-Pipeline liefert keine verwertbaren Emotionsdaten.
Emotion Recognition erfordert ein dediziertes System.

---

## Option 1: Regelbasiert (Audio-Features)

**Ansatz:** Aus dem Roh-Audio akustische Features extrahieren und mit
einfachen Regeln auf Emotionen mappen.

**Features:**
| Feature | Library | Was es misst |
|---|---|---|
| Pitch (F0) | librosa / parselmouth | Grundfrequenz der Stimme |
| Pitch-Varianz | librosa | Monoton vs. expressiv |
| Energie (RMS) | librosa | Lautstärke / Intensität |
| Sprechrate | Whisper-Segmente | Wörter/Sekunde |
| Stille-Anteil | librosa (VAD) | Pausen zwischen Sätzen |
| Spektrale Merkmale (MFCCs) | librosa | Klangfarbe |

**Regel-Mapping (stark vereinfacht):**
- Hoher Pitch + hohe Energie + schnelle Sprechrate → aufgeregt/wütend
- Niedriger Pitch + niedrige Energie + langsame Sprechrate → traurig
- Mittlerer Pitch + hohe Pitch-Varianz → fröhlich
- Monotoner Pitch + niedrige Energie → gelangweilt/deprimiert

**Vorteile:**
- Kein ML-Modell nötig, kein VRAM
- Deterministisch, debugbar
- librosa ist leichtgewichtig (~30MB)

**Nachteile:**
- Extrem ungenau. Emotionserkennung per Regeln funktioniert in der
  Forschung seit 30 Jahren schlecht. Accuracy typischerweise 40-55%
  (kaum besser als Zufall bei 7 Emotionsklassen).
- Keine Personalisierung: Was für Person A "aufgeregt" klingt, ist
  für Person B normal.
- Deutsche Sprache: Wenig Forschung zu Pitch-Emotion-Mapping auf Deutsch.

**Bewertung: ⭐⭐ – Spielerei, kein echter Nutzen.**

---

## Option 2: Dediziertes ML-Modell (SER – Speech Emotion Recognition)

**Ansatz:** Vortrainiertes Modell das direkt aus Audio-Waveforms Emotionen
klassifiziert. Kein Feature-Engineering nötig.

**Kandidaten:**

### emotion2vec (Alibaba DAMO)
- **Architektur:** Self-supervised, basiert auf data2vec
- **Accuracy:** ~90% auf IEMOCAP (Englisch), State-of-the-Art (Stand 2024)
- **Sprachen:** Primär Englisch trainiert, Cross-Language-Transfer unklar
- **Größe:** ~300MB (base), ~90MB (small)
- **VRAM:** ~500MB–1GB bei Inference
- **Python-Package:** `pip install funasr` (Alibaba FunASR Toolkit)
- **Emotionsklassen:** angry, happy, neutral, sad (4 Klassen)
- **Problem:** FunASR ist ein großes Toolkit (>500MB Install), heavy dependency.
  Nur für 4 Emotionsklassen. Deutsch nicht offiziell unterstützt.

### SpeechBrain (emotion recognition recipe)
- **Architektur:** wav2vec 2.0 Fine-Tuned auf IEMOCAP
- **Accuracy:** ~65-75% auf IEMOCAP (je nach Split)
- **Sprachen:** Englisch (IEMOCAP). Deutsche Modelle müssten selbst trainiert werden.
- **Größe:** wav2vec 2.0 base = ~360MB
- **VRAM:** ~1-2GB bei Inference
- **Python-Package:** `pip install speechbrain` (sauberer als FunASR)
- **Emotionsklassen:** angry, happy, neutral, sad (IEMOCAP-Standard)
- **Problem:** Kein deutsches Modell out-of-the-box. Fine-Tuning nötig.

### Wav2Vec2 + EmoDB (Deutsch)
- **Ansatz:** wav2vec 2.0 (facebook/wav2vec2-large-xlsr-53-german) fine-tuned auf EmoDB
- **EmoDB:** Berlin Database of Emotional Speech (TU Berlin)
  - 535 Äußerungen, 10 Sprecher, 7 Emotionen (Ärger, Ekel, Angst, Freude, Langeweile, Trauer, Neutral)
  - Professionelle Schauspieler → sehr "sauber", aber nicht naturalistisch
  - Frei verfügbar für Forschung
  - **ACHTUNG:** Originale TU-Berlin-Website ist de facto tot (weiße Seite).
    Datensatz ist auf GitHub ausgelagert:
    - Übersicht: https://audeering.github.io/datasets/datasets/emodb.html
    - Repository: https://github.com/audeering/datasets
- **Accuracy:** ~85% auf EmoDB (aber: kleiner, sauberer Datensatz → overfitting-Risiko)
- **VRAM:** ~1.5GB (wav2vec2-large)
- **Problem:** EmoDB ist winzig (535 Samples). Modell generalisiert schlecht auf
  echte Alltagssprache. Schauspieler-Emotionen ≠ natürliche Emotionen.

### Hugging Face Community-Modelle
- Diverse fine-tuned Modelle auf HuggingFace Hub, z.B.:
  - `ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition` (Englisch)
  - `superb/wav2vec2-base-superb-er` (IEMOCAP, Englisch)
- Kein etabliertes deutsches Modell mit guter Qualität gefunden.
- Community-Modelle: Qualität stark schwankend, oft auf kleinen Datensätzen.

**Bewertung Option 2 insgesamt: ⭐⭐⭐**
- ML-Modelle sind deutlich besser als Regeln
- Aber: Deutsch ist unterrepräsentiert
- VRAM-Kosten: 0.5–2GB zusätzlich zum LLM (phi4 braucht ~8GB)
  → Auf Tower (16GB) machbar, auf Laptop (8GB) eng
- Fine-Tuning auf Deutsch wäre nötig → eigenes ML-Projekt

---

## Option 3: Hybrid (Audio-Features + LLM-Textanalyse)

**Ansatz:** Statt reiner Audio-Emotion-Erkennung: einfache Audio-Features
(Energie, Sprechrate) als Hinweise extrahieren und zusammen mit dem
transkribierten Text ans LLM geben. Das LLM entscheidet.

**Flow:**
```
Audio → FasterWhisper (Text + Segmente)
     → librosa (Energie, Sprechrate)  ──┐
                                         ├→ LLM: "Text: '...' | Sprechrate: schnell | Energie: hoch"
     → Transkribierter Text ────────────┘    → LLM erkennt Emotion aus Kontext + Hinweisen
```

**Vorteile:**
- Kein ML-Modell, kein VRAM
- LLM ist bereits gut in Textbasierter Sentiment-Analyse
- Audio-Features als Zusatzinformation, nicht als alleinige Quelle
- Funktioniert auf Deutsch (LLM versteht Deutsch)
- Leichtgewichtig: nur librosa (~30MB) als Dependency

**Nachteile:**
- Audio-Features sind grob (Energie, Sprechrate – kein Pitch ohne parselmouth)
- LLM-Call pro Nachricht ist sowieso da → kein Extra-Call, aber System-Prompt wird länger
- Qualität hängt von der LLM-Qualität ab (phi4 lokal vs. Sonnet remote)
- Nicht validierbar: keine Ground-Truth zum Testen

**Bewertung: ⭐⭐⭐⭐ – Bester Kosten/Nutzen-Kompromiss.**

---

## VRAM-Budget (Tower: 16GB)

| Komponente | VRAM | Status |
|---|---|---|
| phi4:14b (Ollama) | ~8-9 GB | Läuft |
| XTTS v2 (CoquiTTS) | ~1.5 GB | Läuft |
| FasterWhisper medium | ~1.5 GB | Läuft (Lazy-Load) |
| ChromaDB Embeddings | ~0.5 GB | Läuft (Ollama-shared) |
| **Frei verfügbar** | **~3-5 GB** | |

→ Ein SER-Modell (0.5–2GB) passt KNAPP auf den Tower.
→ Auf dem Laptop (8GB) geht es nicht gleichzeitig mit phi4.
→ Hybrid-Ansatz (Option 3) braucht 0 GB VRAM.

---

## Integrationspunkte im bestehenden Code

### Wo würde Emotion Recognition eingehängt?

**1. STT-Ebene (FasterWhisperEngine):**
- `transcribe()` / `transcribe_bytes()` liefert `TranscriptionResult`
- Neues Feld: `audio_features: AudioFeatures | None`
- AudioFeatures DTO: energy_rms, speaking_rate_wps, pitch_mean, pitch_std
- Berechnung in `_run_transcription()` nach Whisper, vor Return

**2. Bridge-Ebene (MatrixBridge):**
- Matrix-Sprachnachricht → FasterWhisper → TranscriptionResult (mit AudioFeatures)
- AudioFeatures als Kontext an Assistant.process() übergeben
- Neuer Parameter: `audio_context: str | None = None`

**3. Assistant-Ebene:**
- `process()` bekommt `audio_context`
- Wird in System-Prompt eingebaut:
  "Hinweis zur Stimme des Nutzers: Sprechrate überdurchschnittlich schnell,
   Energie hoch. Berücksichtige dies bei deiner Einschätzung der Stimmung."
- LLM entscheidet ob und wie es die Info nutzt

**4. SaleriaEngine:**
- `extract_emotion()` bleibt unverändert (parst LLM-Output)
- LLM wählt Emotion basierend auf Text + Audio-Kontext

### Was sich NICHT ändert:
- Emotion-Set (10 Emotionen) bleibt gleich
- Avatar-Steuerung (show_emotion) bleibt gleich
- TTS Voice-Map bleibt gleich
- Gesamter Flow bleibt gleich – nur der Input ans LLM wird reicher

---

## Empfehlung

**Option 3 (Hybrid) als erster Schritt:**
- Aufwand: Klein (1-2 Tage, eine Phase)
- Risiko: Niedrig (keine neue Dependency außer librosa, kein VRAM)
- Nutzen: LLM bekommt Hinweise zur Sprechweise → bessere Emotionswahl
- Messbar: Vorher/Nachher-Vergleich der Emotions-Verteilung in Logs

**Option 2 (ML-Modell) als späterer Upgrade-Pfad:**
- Erst wenn Option 3 sich als zu ungenau erweist
- Dann: emotion2vec (small, ~90MB) ausprobieren, Cross-Language-Transfer testen
- Falls Deutsch schlecht: Fine-Tuning auf EmoDB + eigene Samples evaluieren
- Das ist ein eigenes ML-Projekt (1-2 Wochen), kein Nachmittags-Feature

**Option 1 (Regelbasiert) verwerfen:**
- Zu ungenau, der Aufwand für Feature-Engineering lohnt sich nicht
  wenn das LLM die gleiche Arbeit besser kann

---

## Offene Entscheidungen

1. **Wann umsetzen?** Option 3 könnte als Phase 17 eingeplant werden.
   Niedrige Priorität – erst wenn Phase 15+16 abgeschlossen sind und
   Saleria regelmäßig per Sprachnachricht genutzt wird.

2. **librosa als Dependency:** ~30MB, gut maintained, MIT-Lizenz.
   Alternativen: parselmouth (Praat-Wrapper, besser für Pitch),
   torchaudio (bereits in PyTorch-Ökosystem, aber heavy).
   Empfehlung: librosa für v1, parselmouth als Ergänzung wenn Pitch nötig.

3. **Baseline-Kalibrierung:** Salerias Einschätzung könnte verbessert werden
   wenn sie eine persönliche Baseline hat ("wie spricht der User normalerweise?").
   Das erfordert persistente Audio-Statistiken pro User – Scope für v2.

4. **Privacy:** Audio-Features (Energie, Sprechrate) sind anonymisiert –
   kein Roh-Audio wird gespeichert. Nur numerische Werte im LLM-Kontext.
   Datenschutzrechtlich unbedenklich für Single-User-System.
