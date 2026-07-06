# Phase 110 – Sichtbarer Intensitäts-Blend (Konzept)

**Branch:** `feature/phase-110-emotion-intensity-blend`
**Status:** Umsetzung (Lera-Go, Modell B). Realisiert **Tier 2b** aus
`docs/concepts/phase-108-confidence-aware-emotion.md`: die in Phase 109
geparste Intensität wird jetzt **sichtbar** – `[angry:0.4]` zeigt eine mildere
Wut im Gesicht (Blend Richtung neutral), statt nur die Confidence zu skalieren.

## Lera-Entscheidung (Modell B)

Die Intensität bedeutet ab jetzt **Anzeige-Tiefe**, nicht mehr „Sicherheit":

- Jede **getaggte** Emotion **schaltet um** und wird mit Tiefe = Intensität
  gezeigt (Blend primär ↔ neutral). `[angry:0.4]` = 40 % Wut über 60 % neutral.
- Das **Phase-108-Gate** hält nur noch **tag-lose** (Tracker-only) Turns – also
  echte Identitäts-Unsicherheit. Ein Tag ist immer „sicher genug" zum Umschalten.

**Folge für Phase 109:** die dortige Confidence-Skalierung
(`scores[tag] += tag_weight * intensity`) wird **zurückgenommen** – ein Tag trägt
wieder die volle `tag_weight`-Confidence (Gate-Verhalten wie Tier 1). Die
Intensität wandert in ein **eigenes Feld** und steuert ausschließlich den Blend.
Parsing (`parse_emotion_tag_with_intensity`) und Prompt aus Phase 109 bleiben.

## Datenfluss (intensity end-to-end)

1. **Resolver** (`EmotionResolver`): `EmotionDecision` bekommt ein Feld
   `intensity: float` (Default 1.0). `confidence` ist wieder
   intensitäts-**unabhängig** (`tag_weight`). Intensität 0 zählt als kein Signal
   (kein Score/Record → Fallback), damit `[emotion:0.0]` nicht „leer" schaltet.
2. **Transport** (REST): `AvatarDecision.intensity` (gebunden 0–1, kein inf/NaN);
   `RobotClient.set_emotion` serialisiert es; `robot/server.py` reicht es an
   `AvatarDisplay.set_emotion(emotion, confidence, intensity)` – nur wenn
   `decision.emotion == request.emotion`, sonst 1.0.
3. **RPi5** (`rpi5_avatar`): speichert die Intensität, der Render-Loop reicht das
   `(emotion, confidence, intensity)`-Tripel an `controller.set_emotion`.
4. **Controller**: synthetisiert die `EmotionDecision` mit der echten Intensität.
5. **StateMachine**: `AvatarState.intensity`; `request_emotion` übernimmt die
   Intensität der **akzeptierten** Emotion (bei Gate-Reject bleibt alt).
6. **Renderer-Blend** (`transition_at`): im **eingeschwungenen** Zustand
   (kein Crossfade) wird bei `intensity < 1.0` `previous = NEUTRAL`,
   `current = emotion @ alpha = lerp(intensity)` zurückgegeben → der vorhandene
   Cross-Dissolve (`_composite_full`) blendet die Emotion über neutral. Bei
   `intensity == 1.0` bleibt es opak (byte-identisch zu heute).

## Bewusste Vereinfachungen / Grenzen (v1)

- **Kein Intensitäts-Asset** existiert – der Blend Richtung **neutral** ist die
  asset-freie Approximation von „mild". Visuelles Feintuning am RPi5-Display.
- **Crossfade unverändert** (voll alt→neu); erst der **eingeschwungene** Zustand
  zeigt den Intensitäts-Blend. Auf crossgefadeten Wechseln gibt es daher kurz
  (~266 ms) die volle Emotion, dann das Absinken auf die Ziel-Intensität – ein
  bewusst akzeptierter v1-Artefakt (Direct-Cut-Paare springen sofort auf mild).
- Ein gehaltener Blend rendert pro Frame über den Crossfade-Pfad (teurer als der
  opake Fast-Path), liegt aber im §6.1-30-FPS-Budget (vom Crossfade-Benchmark
  gedeckt). Nur Emotionen mit `intensity < 1.0` betroffen.

## Definition of Done

1. `EmotionDecision.intensity` + intensitäts-unabhängige `confidence`; Intensität
   end-to-end bis zur StateMachine transportiert (Schema gebunden 0–1).
2. `transition_at` liefert im eingeschwungenen Zustand den Neutral-Blend bei
   `intensity < 1.0`; `intensity == 1.0` byte-identisch opak.
3. Gate hält nur tag-lose Turns; getaggte Emotionen schalten immer.
4. Legacy-Pfad (kein Resolver) transportiert die Intensität ebenfalls.
5. Voller pytest + ruff + mypy (avatar/robot strict) grün.

## Journal

- Folge zu `elder-berry#881` (Phase 109 / PR #339 gemergt) – Lera-Wahl „Tier 2b,
  Modell B".
