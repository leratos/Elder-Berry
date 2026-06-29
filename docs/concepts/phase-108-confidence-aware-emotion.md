# Phase 108 – Confidence-Aware Emotion (Konzept)

**Befund:** Der Avatar reagiert identitäts-binär; die seit Phase 83.5 **live
berechnete** Emotion-Confidence wird nicht genutzt.
**Branch (geplant):** `feature/phase-108-confidence-aware-emotion`
**Status:** Konzept (Vorschlag, Lera-Wahl). Setzt die Reactive-AvatarEngine
(Phasen 83.1–83.6) fort; alternativ als Sub-Phase **83.7** führbar.

## Ziel

Die `EmotionDecision` (Identität + **Confidence** + Tracker-Trend), die der
`EmotionResolver` heute schon pro Turn liefert, soll das sichtbare Avatar-
Verhalten **tatsächlich formen** – statt nur server-seitig geloggt zu werden.
Ergebnis: weniger sprunghafte, „sicherheitsbewusste" Mimik (unsichere/untagged
Turns reißen das Gesicht nicht mehr herum).

## IST-Zustand (am Code verifiziert 2026-06-29)

Die Reactive-Engine ist großteils gebaut **und live**:

- `EmotionResolver` ist produktiv verdrahtet:
  `scripts/start_saleria.py:1969` instanziiert ihn (teilt sich den
  `EmotionTracker` des Characters), `core/assistant.py:200` nutzt
  `resolve_from_llm`. Er liefert
  `EmotionDecision(emotion, confidence 0.0–0.9, source, raw_signals)`.
- Der Server **sendet** die Decision schon mit:
  `RobotActionMixin._robot_set_emotion(emotion, decision)`
  (`core/assistant_robot.py:67`) → `RobotClient.set_emotion(emotion, decision=)`.

**Wo die Confidence verloren geht:**

1. **REST-Grenze (nur Logging):** `robot/server.py:330-343` ruft
   `self._avatar.set_emotion(request.emotion)` – nur den String – und
   `safe_log`'t `request.decision.confidence/source` „rein additiv". Die ABC
   `AvatarDisplay.set_emotion(self, emotion: str)` (`robot/interfaces.py:44`)
   ist **einarmig**; die Decision kann gar nicht durchgereicht werden.
2. **RPi-Synthese auf 1.0:** `avatar/controller.py:91-100`
   (`set_emotion(str)`) baut eine `EmotionDecision(parsed, confidence=1.0,
   _LEGACY_SOURCE, {})` – **hartcodiert 1.0**. Die `AvatarStateMachine` sieht
   also jede Emotion als 100 % sicher.
3. **StateMachine ignoriert Confidence:** der Crossfade (83.3) entscheidet rein
   über **Identität** (`direct_cut_pairs` + feste `crossfade_frames`);
   Confidence/Intensität spielen keine Rolle.
4. **Identität ist 1 Tag/Turn:** `parse_emotion_tag` findet max. **ein** Tag
   (Phase-83-Schwäche „Binary Emotion"). Der Tracker-Trend hebt nur die
   Confidence bzw. springt ein, wenn kein Tag da ist.

## Gap-Zusammenfassung

| # | Lücke | Ort |
|---|---|---|
| G1 | Confidence wird an der REST-Grenze nur geloggt, nicht durchgereicht | `robot/server.py`, `robot/interfaces.py` |
| G2 | RPi synthetisiert `confidence=1.0` statt der echten | `avatar/controller.py:99` |
| G3 | StateMachine nutzt Confidence nicht (kein Gate/keine Modulation) | `avatar/state_machine.py` |
| G4 | Nur 1 Emotion/Turn, keine Intensität/Mischung (separat, größer) | `character/*`, Prompt |

## Design (Tiers)

### Tier 1 – Confidence ans Verhalten koppeln (Kern, Software-only)

**Transport (G1/G2):** `AvatarDisplay.set_emotion` um ein **optionales**
Confidence-/Decision-Argument erweitern; `robot/server.py` reicht
`request.decision` durch (wird ohnehin schon empfangen) statt es nur zu loggen;
`rpi5_avatar.set_emotion` + `simulator` nehmen die Confidence an und geben sie
über den **schon existierenden** semantischen Pfad `controller.on_emotion_decision`
an die StateMachine – statt im Legacy-`set_emotion(str)` 1.0 zu synthetisieren.

**Verhalten (G3) in `AvatarStateMachine.request_emotion(decision)`:**

- **Confidence-Gate / Hysterese:** eine Decision mit `confidence < θ_low`
  (z. B. 0.3 – typischer Fall: das LLM gab **kein** Tag, nur Tracker-Trend)
  überschreibt eine etablierte aktuelle Emotion **nicht hart**, sondern hält
  sie (bzw. driftet, Tier 3). Killt das „Yank" auf untagged Turns.
- **Crossfade-Modulation (optional):** `confidence` → `crossfade_frames` bzw.
  Hard-Cut-Unterdrückung. Hohe Confidence → klarer/schneller Wechsel; mittlere
  → längerer, sanfter Crossfade.

**Rückwärtskompatibel:** der Legacy-/`extract_emotion`-Pfad sendet keine
Decision → Confidence-Default 1.0 → Verhalten **unverändert** (wichtig für die
Bestandstests, die `set_emotion(str)` nutzen).

**Betroffene Dateien (alle in frisch-strikten Paketen avatar/ + robot/):**
`robot/interfaces.py` (ABC), `robot/schemas.py` (Decision-DTO existiert bereits),
`robot/server.py` (Durchreichen), `robot/simulator.py`, `robot/rpi5_avatar.py`
(`set_emotion`-Signatur + Render-Loop), `avatar/controller.py`,
`avatar/state_machine.py` (Gate) + zugehörige Tests.

### Tier 2 – Intensität / Sekundär-Emotion (optional, größer)

Den LLM-Tag um eine Intensität/Sekundärfarbe erweitern, z. B.
`[cheerful]` → `[cheerful:0.7]` oder Primär|Sekundär `[thoughtful|shy]`.
Berührt `parse_emotion_tag`, den Emotion-System-Prompt und das Resolver-Scoring;
im Renderer ggf. partieller Crossfade Richtung Sekundär oder intensivere
Layer-Variante (**asset-abhängig** – Scope zuerst prüfen). Liefert erst die
echte Confidence-Bandbreite (heute: getaggt ≈ 0.7–0.9, untagged ≤ 0.2).

### Tier 3 – Emotionale Trägheit / Decay-to-Baseline (optional, klein)

Ohne starkes Signal über N Turns driftet die sichtbare Emotion zurück Richtung
`NEUTRAL` (der Tracker decayt bereits für den System-Prompt – der Avatar
spiegelt das nur). Ergänzt Tier 1 zu einem kohärenten Trägheits-Modell.

## Empfehlung

**Tier 1 als Kern-Deliverable einer Phase.** Bester Wert/Aufwand-Quotient, rein
Software, baut direkt auf der gerade strikt-typisierten StateMachine/Controller
(Phase 107). Tier 2/3 als optionale Folge-Etappen nach Lera-Sichtung.

## Offene Entscheidungen (für Lera)

1. **θ_low-Schwelle** + ob die Crossfade-Modulation schon in Tier 1 oder erst
   später kommt.
2. **Confidence-Bandbreite:** Da ein getaggter Turn ~0.7–0.9 liefert und ein
   untagged Turn ≤ 0.2, ist der Haupteffekt von Tier 1 „untagged Turn **hält**
   die Mimik". Reicht das als erster Schritt – oder Tier 2 (Intensität) gleich
   mitnehmen, um echte dynamische Confidence zu bekommen?
3. **Phasennummer/-name:** sequenziell **108** vs. Sub-Phase **83.7** der
   Reactive-AvatarEngine.

## Risiken

- **Cross-package-Schnittstellenänderung** (`AvatarDisplay`-ABC) berührt robot/
  **und** avatar/ + Tests; strikt rückwärtskompatibel halten (Decision optional).
- **Confidence ist heute schmalbandig** → Tier 1 allein kann subtil wirken;
  ehrlich kommunizieren (der sichtbare Effekt sind v. a. untagged Turns).
- **Verhaltens-Tuning** (θ_low, Crossfade) braucht **visuelle** Bestätigung am
  echten RPi5-Display, nicht nur Unit-Tests.

## Definition of Done (Tier 1)

1. Die echte `EmotionDecision`-Confidence erreicht die `AvatarStateMachine`
   (kein hartcodiertes 1.0 mehr im Resolver-Pfad); Legacy-Pfad unverändert.
2. Die StateMachine nutzt die Confidence (Hysterese-Gate); Unit-Tests für die
   Gate-Grenzen (unter/über θ_low, Legacy-1.0).
3. Voller `pytest` + `ruff` + `mypy` (avatar/robot strict, CI-Scope) grün.
4. Visuelle Bestätigung am RPi5 **oder** dokumentierte Sim-Grenze.

## Journal

- Vorschlag/Auswahl: Folge zu `elder-berry#876` (Doku-Sync) – Lera wählte
  „A2: Reichere Emotion".
