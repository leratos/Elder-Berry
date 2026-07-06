# Phase 109 – Emotion-Intensität (Konzept)

**Branch:** `feature/phase-109-emotion-intensity`
**Status:** Umsetzung (Lera-Go). Realisiert **Tier 2a** aus
`docs/concepts/phase-108-confidence-aware-emotion.md`: das LLM-Tag bekommt eine
optionale Intensität, die die `EmotionDecision`-Confidence mit echter Bandbreite
versorgt – und damit das in Phase 108 gebaute Confidence-Gate **graduell** macht.

## Ziel

Heute liefert ein getaggter Turn praktisch immer Confidence ~0.7–0.9 (flach),
ein untagged Turn ≤0.2. Das Phase-108-Gate (Schwelle 0.35) trennt nur „getaggt
vs. untagged". Mit einer expliziten Intensität `[emotion:staerke]` steuert das
LLM, **wie stark** eine Emotion gemeint ist → schwache Emotionen werden vom Gate
gehalten, starke schalten den Ausdruck um.

## Lera-Entscheidungen

- **Scope: nur 2a** (Intensität → Confidence). **Kein** Renderer-Change. Der
  sichtbare Gesichts-Blend (2b, gehaltener primär↔neutral-Blend) bleibt eine
  spätere, eigene Phase – es gibt ohnehin **keine Intensitäts-Assets**, d. h.
  eine sichtbare Abstufung bräuchte echte Renderer-/StateMachine-Arbeit.
- **Tag-Format: `[emotion:intensity]`** (eine Zahl 0.0–1.0), keine
  Sekundär-Emotion.

## Design

### Tag-Parsing (`character/`)

Die Tag-Regex wird intensitäts-fähig:
`\[(<emotions>)(?::(\d*\.?\d+))?\]`. Gruppe 2 (optional) ist die Intensität.

- `parse_emotion_tag(s) -> Emotion | None`: **unverändert** (ignoriert die
  Intensität) – Bestands-API + Tests bleiben grün.
- **NEU** `parse_emotion_tag_with_intensity(s) -> tuple[Emotion, float] | None`
  (ABC + `SaleriaEngine`): liefert Emotion + Intensität; ohne `:x` →
  Intensität **1.0**; der Wert wird hart auf `[0.0, 1.0]` geklemmt.
- `clean_response` / `extract_emotion`: nutzen dieselbe Regex; das ganze
  `[emotion:intensity]` wird gestrippt bzw. die Emotion (ohne Intensität)
  gelesen. Der Legacy-/`extract_emotion`-Pfad bleibt verhaltensgleich.

### Resolver-Scoring (`EmotionResolver`)

Der Tag-Beitrag wird mit der Intensität skaliert:

```text
scores[tag] += tag_weight * intensity     # statt += tag_weight
```

- **Bare Tag** (`[angry]`) → Intensität 1.0 → Beitrag 0.7 = **wie heute**
  (vollständig rückwärtskompatibel; alle Confidence-Skala-Tests unverändert).
- `[angry:0.4]` → Beitrag 0.28 → unter der Gate-Schwelle 0.35 → **gehalten**.
- `[angry:0.9]` → 0.63 → **schaltet um**.
- **Switch-Punkt** ≈ Intensität 0.5 (`0.7 * 0.5 = 0.35`), sofern kein
  gleichgerichteter Tracker-Trend zusätzlich beiträgt.

Die Intensität wird zusätzlich an `set_mood(emotion, intensity)` durchgereicht
(der Parameter existiert bereits, wurde bisher mit dem Default 0.5 gefüttert).

**Bewusste Konsequenz:** bei sehr kleiner Intensität kann ein starker
**gegenläufiger** Tracker-Trend die Identität übernehmen (z. B. `[angry:0.2]`
= 0.14 vs. dominanter cheerful-Trend 0.2). Das ist gewollt: ein kaum gemeintes
Tag soll eine gefestigte jüngste Stimmung nicht hart umwerfen.

### Prompt (`saleria.yaml`)

Die Tag-Anweisung wird um die optionale Stärke ergänzt (mit Beispiel und dem
Hinweis, dass schwache Werte den Ausdruck ruhig lassen). Ohne Stärke gilt volle
Intensität – das LLM **darf** weiter `[emotion]` ohne Zahl schreiben.

## Nicht in dieser Phase

- **2b** sichtbarer Intensitäts-Blend im Renderer (gehaltener Teil-Blend
  primär↔neutral) – eigene Folgephase, braucht Renderer-/StateMachine-Eingriff
  und visuelles Tuning am RPi5-Display.
- Sekundär-Emotion (`[primary|secondary]`).

## Risiken / ehrliche Einschränkung

- Der Effekt hängt davon ab, dass das LLM die Intensität **sinnvoll** vergibt;
  ohne `:x` ändert sich nichts (voll rückwärtskompatibel).
- `character/` ist (noch) nicht im strict-mypy-Tier – die Änderung wird über
  pytest + ruff abgesichert, nicht über das CI-typecheck-Gate.

## Definition of Done

1. `[emotion:intensity]` wird geparst (+ Default 1.0, Clamp 0–1); `clean_response`
   strippt es; Legacy-Pfad unverändert.
2. Resolver skaliert den Tag-Beitrag mit der Intensität; bare Tag = wie bisher.
3. Prompt erklärt das Format.
4. Tests: Parsing (mit/ohne/clamp), Resolver-Confidence (z. B. 0.4 → unter Gate,
   0.9 → drüber), Bestands-Skala-Tests unverändert grün.
5. Voller pytest + ruff grün.

## Journal

- Folge zu `elder-berry#879` (Phase 108 Tier 1 / PR #338) – Lera-Wahl „ja tier 2",
  Scope 2a + Tag `[emotion:intensity]`.
