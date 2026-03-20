# Phase 24 – Avatar Asset Management & Animationssystem

> **Status:** Konzept
> **Erstellt:** 2026-03-20
> **Abhängigkeit:** LayeredSpriteRenderer (Phase 3), RPi5 Avatar-Display (Phase 10),
>   FastAPI Web-Interface (Phase 12)

---

## Ziel

Salerias Avatar wird ausdrucksstärker und einfacher konfigurierbar.
Neue Assets (Bodies, Augen, Münder) können über ein Web-Interface visuell
zugewiesen werden, statt Python-Dicts im Code zu editieren. Zusätzlich
bekommt der Avatar subtile Animationen (Atmen, verbesserte Lip-Sync),
die ihn lebendiger wirken lassen.

**Aktuell:**
- 3 Bodies, 14 Augen-Sprites, 6 Mund-Sprites (21 Assets gesamt)
- 8 von 10 Emotionen nutzen denselben `idle`-Body
- Emotion-zu-Asset-Mapping hardcoded in `layered_renderer.py` (EMOTION_MAP)
- Lip-Sync: feste 4-Frame-Rotation (close → halfopen → open → halfopen)
- Kein Atmen, keine Übergangs-Animationen

**Nachher:**
- 7 Bodies, ~20 Augen-Sprites, ~10 Mund-Sprites
- Jede Emotion hat eine visuell unterscheidbare Kombination
- Mapping konfigurierbar über YAML (editierbar via Web-UI)
- Subtiles Atmen, randomisierte Lip-Sync, optionale Effekt-Layer

---

## Teilschritt 1: Neue Assets erstellen

### 1.1 Neue Body-Varianten (4 Stück)

| Asset | Pose | Emotionen |
|-------|------|-----------|
| `body_relaxed.png` | Arme locker, eine Hand an der Hüfte | neutral, whisper, cheerful (neuer Default) |
| `body_energetic.png` | Aufrecht, Faust geballt oder Arme leicht gehoben | motivated |
| `body_withdrawn.png` | Schultern eingezogen, Arme nah am Körper | shy, sad, depressed |
| `body_gesture.png` | Eine Hand ausgestreckt/präsentierend | cheerful (alternativ), Idle-Animation |

Der bestehende `idle` (verschränkte Arme) wird zu `body_crossed` umbenannt
und explizit `sarcastic` zugewiesen (verschränkte Arme + Seitenblick = perfekt).

**Anforderungen an alle Bodies:**
- 512x1024 RGBA, transparenter Hintergrund
- Gesichtsbereich blank (keine Augen/Mund eingezeichnet) — nur Haut, Haare, Nase
- Gleiche Körperposition/Anker: Füße und Kopf auf gleicher Höhe wie bei `idle`
- Stilistisch konsistent: gleicher Anime-Stil, dunkelrot/schwarz Outfit

### 1.2 Neue Mund-Sprites (4 Stück)

| Asset | Beschreibung | Emotionen |
|-------|-------------|-----------|
| `mouth_smile.png` | Geschlossener Mund, Mundwinkel nach oben | cheerful (Default-Mund) |
| `mouth_smirk.png` | Einseitiges Grinsen | sarcastic |
| `mouth_pout.png` | Schmollmund, leicht nach unten | sad, depressed |
| `mouth_grin.png` | Offenes Lächeln mit Zähnen | motivated |

### 1.3 Neue Augen-Sprites (4 Stück)

| Asset | Beschreibung | Emotionen |
|-------|-------------|-----------|
| `eye_left_cheerful.png` / `eye_right_cheerful.png` | Lachende Augen (halb-geschlossen, nach oben gebogen) | cheerful, motivated |
| `eye_left_halfclose.png` / `eye_right_halfclose.png` | Halb-geschlossen, schläfrig | whisper, depressed |

### 1.4 Optionale Idle-Augen (2 Stück)

| Asset | Beschreibung | Verwendung |
|-------|-------------|------------|
| `eye_left_down_open.png` / `eye_right_down_open.png` | Blick nach unten | Idle-Animation (lesen/nachdenken) |

### Neues EMOTION_MAP nach Asset-Ergänzung

```
neutral    → body_relaxed  + eye_open         + mouth_neutral_close
cheerful   → body_relaxed  + eye_cheerful     + mouth_smile
sarcastic  → body_crossed  + eye_side         + mouth_smirk
motivated  → body_energetic+ eye_cheerful     + mouth_grin
thoughtful → body_thinking + eye_side         + mouth_think_close
whisper    → body_relaxed  + eye_halfclose    + mouth_halfopen
shy        → body_withdrawn+ eye_close        + mouth_neutral_close
depressed  → body_withdrawn+ eye_halfclose    + mouth_pout
sad        → body_withdrawn+ eye_sad          + mouth_pout
angry      → body_angry    + eye_angry        + mouth_angry_open
```

---

## Teilschritt 2: Breathing-Animation (Code-only)

Subtile Atembewegung im Idle-Zustand — kein neues Asset nötig.

### Umsetzung

In `LayeredSpriteRenderer.update()`:

```python
import math

# Sanfter Sinus-Offset auf Y-Achse (±2 Pixel)
breath_offset = math.sin(time.monotonic() * 1.2) * 2.0
```

Der Offset wird beim Blitten aller Layer auf die Y-Position addiert.
Bei 1024px Höhe sind ±2px kaum wahrnehmbar aber geben dem Avatar "Leben".

### Parameter

| Konstante | Wert | Beschreibung |
|-----------|------|-------------|
| `BREATH_SPEED` | 1.2 | Frequenz (Zyklen/Sekunde) |
| `BREATH_AMPLITUDE` | 2.0 | Pixel Auslenkung |

Nur aktiv wenn `not self._is_speaking` — beim Sprechen dominiert Lip-Sync.

---

## Teilschritt 3: Verbesserte Lip-Sync

### Stufe 1: Randomisierte Rotation (Code-only)

Statt feste Reihenfolge `[close, halfopen, open, halfopen]`:
- Mund-Zustände werden zufällig gewählt (gewichtet)
- Gewichte: `close: 0.2, halfopen: 0.4, open: 0.3, wide: 0.1`
- Timing leicht variabel: ±30ms Jitter auf `LIP_SYNC_INTERVAL`
- Wirkt sofort natürlicher, keine neuen Assets nötig

### Stufe 2: Mehr Mund-Frames (2 neue Assets)

| Asset | Beschreibung |
|-------|-------------|
| `mouth_tiny.png` | Leicht geöffnet (kleiner als halfopen) |
| `mouth_wide.png` | Weit geöffnet (größer als open) |

Erweitert die Lip-Sync-Palette auf 6 Stufen:
`close → tiny → halfopen → open → wide → open → halfopen → ...`

### Stufe 3: Amplitude-basierte Lip-Sync (Langfristig)

- TTS-Audio-Stream analysieren (RMS-Amplitude pro Frame)
- Laute Stellen → `mouth_open` / `mouth_wide`
- Leise Stellen → `mouth_halfopen` / `mouth_tiny`
- Pausen → `mouth_neutral_close`
- Abhängig davon wie der TTS-Output aktuell gestreamt wird (CoquiTTSEngine → WAV)

---

## Teilschritt 4: Asset-Konfiguration externalisieren

### YAML-Config statt hardcoded EMOTION_MAP

Neue Datei: `src/elder_berry/avatar/assets/avatar_config.yaml`

```yaml
version: 1

emotions:
  neutral:
    body: body_relaxed
    eye_left: eye_left_open
    eye_right: eye_right_open
    mouth: mouth_neutral_close
    can_blink: true
  cheerful:
    body: body_relaxed
    eye_left: eye_left_cheerful
    eye_right: eye_right_cheerful
    mouth: mouth_smile
    can_blink: true
  # ... alle 10 Emotionen

lip_sync:
  mode: weighted_random  # sequential | weighted_random
  frames:
    mouth_neutral_close: 0.2
    mouth_halfopen: 0.4
    mouth_open: 0.3
    mouth_wide: 0.1
  interval: 0.18
  jitter: 0.03

breathing:
  enabled: true
  speed: 1.2
  amplitude: 2.0

idle_actions:
  - name: glance_left
    eye_left: eye_left_side_open
    eye_right: eye_right_side_open
    duration: 2.0
  - name: glance_down
    eye_left: eye_left_down_open
    eye_right: eye_right_down_open
    duration: 2.0
  - name: smile
    mouth: mouth_smile
    duration: 2.0
  - name: soft_close
    eye_left: eye_left_close
    eye_right: eye_right_close
    duration: 2.0
  - name: surprise
    eye_left: eye_left_surprise_open
    eye_right: eye_right_surprise_open
    mouth: mouth_open
    duration: 1.5
```

### Änderungen am Renderer

- `LayeredSpriteRenderer.__init__()` lädt `avatar_config.yaml` statt hardcoded Dict
- `EMOTION_MAP` wird aus YAML generiert
- `LIP_SYNC_MOUTHS` wird aus YAML gelesen
- Hot-Reload: Config kann zur Laufzeit neu geladen werden (für Web-Editor)
- Fallback: wenn YAML fehlt, greift der bestehende hardcoded Default

---

## Teilschritt 5: Web-Interface (Avatar-Editor)

### Architektur

- Neue Route im bestehenden FastAPI-Server: `/avatar/editor`
- Rein statisches Frontend: HTML + Vanilla JS + Canvas (kein Framework)
- Backend-Endpoints:
  - `GET /avatar/assets` → Liste aller verfügbaren Sprites pro Kategorie
  - `GET /avatar/assets/{category}/{name}` → Sprite-PNG servieren
  - `GET /avatar/config` → aktuelle YAML-Config als JSON
  - `PUT /avatar/config` → Config speichern (validiert)
  - `POST /avatar/preview` → serverseitig gerenderte Preview als PNG (optional)

### Frontend-Features

1. **Asset-Browser**: Thumbnail-Grid pro Kategorie (body / eye / mouth)
2. **Emotion-Editor**: Pro Emotion Dropdowns für Body, Eye L, Eye R, Mouth
3. **Live-Canvas-Preview**: Layer werden clientseitig auf ein `<canvas>` composited
   - Sofortige Vorschau ohne Server-Roundtrip
   - Transparenz-Compositing direkt im Browser
4. **Animation-Preview**: Blink/Lip-Sync/Breathing simulieren im Canvas
5. **Save**: Speichert Config → Backend validiert → YAML schreiben
6. **Hot-Reload-Button**: Renderer lädt Config neu ohne Neustart

### Datei-Struktur

```
src/elder_berry/
├── avatar/
│   ├── assets/
│   │   ├── avatar_config.yaml     ← NEU: externalisierte Config
│   │   ├── body/
│   │   ├── eye/
│   │   └── mouth/
│   ├── avatar_config_loader.py    ← NEU: YAML laden + validieren
│   ├── layered_renderer.py        ← GEÄNDERT: Config statt hardcoded Dict
│   └── ...
├── web/
│   ├── avatar_editor.py           ← NEU: FastAPI-Endpoints
│   └── templates/
│       └── avatar_editor.html     ← NEU: Editor-UI
```

---

## Teilschritt 6: Effekt-Layer (Optional, Niedrige Priorität)

Optionaler vierter Layer über Body + Eyes + Mouth:

| Effekt | Emotion | Beschreibung |
|--------|---------|-------------|
| `effect_tear.png` | sad | Einzelne Träne an der Wange |
| `effect_sweat.png` | shy | Anime-Schweißtropfen |
| `effect_sparkle.png` | motivated | Leichtes Glitzern/Sternchen |
| `effect_dots.png` | thoughtful | "..." Denkblasen-Andeutung |

Umsetzung: Neuer Unterordner `assets/effect/`, optionaler `effect`-Key
in der YAML-Config pro Emotion. Renderer zeichnet Effect-Layer als letztes.

---

## Reihenfolge & Aufwand

| Schritt | Was | Aufwand | Abhängigkeit |
|---------|-----|---------|-------------|
| 1 | Neue Assets erstellen (extern, Zeichner/AI) | Extern | Keine |
| 2 | Breathing-Animation im Renderer | ~30 Min | Keine |
| 3a | Randomisierte Lip-Sync | ~30 Min | Keine |
| 3b | Neue Lip-Sync-Frames (Assets) | Extern | Schritt 1 |
| 4 | YAML-Config + Config-Loader | ~2h | Schritt 1 (Assets müssen benannt sein) |
| 5 | Web-Interface Avatar-Editor | ~4-6h | Schritt 4 |
| 6 | Effekt-Layer | ~1h Code + Assets extern | Schritt 4 |

Schritte 2 und 3a sind unabhängig von neuen Assets und können sofort umgesetzt werden.
Schritt 4 kann parallel zum Asset-Erstellen vorbereitet werden.

---

## Abgrenzung

- **Kein Skelett-Animations-System** — das Layer-System bleibt, keine Bones/Rigging
- **Kein Echtzeit-Audio-Lip-Sync in v1** — kommt ggf. als Stufe 3, aber nicht in dieser Phase
- **Keine Augenbrauen als eigener Layer** — wäre ein grundlegender Asset-Refactor
  (alle bestehenden Eye-Sprites müssten neu gezeichnet werden). Kann als spätere Phase erwogen werden.
- **Keine neuen Emotionen** — die 10 bestehenden bleiben, sie werden nur visuell besser differenziert

---

## Technische Risiken

| Risiko | Mitigation |
|--------|-----------|
| Neue Assets passen stilistisch nicht zu bestehenden | Style-Guide mit Referenz-Assets mitliefern |
| Body-Anker stimmt nicht → Avatar "springt" bei Emotionswechsel | Anforderung: identische Fuß/Kopf-Position in allen Bodies |
| YAML-Config wird korrupt → Avatar kaputt | Validierung beim Laden, Fallback auf hardcoded Default |
| Web-Editor ist Security-Risiko (Dateisystem-Zugriff) | Nur im lokalen Netz, keine öffentlichen Endpoints, Pfad-Validierung |
| Canvas-Compositing im Browser sieht anders aus als PyGame | Gleiche Blend-Mode verwenden (RGBA alpha compositing) |
