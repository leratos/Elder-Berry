# Phase 83 – Reactive AvatarEngine

**Status:** Konzept (wartet auf Review).
**Branch:** noch keiner – Konzept liegt auf `main`.
**Phasennummer:** 83 (letzte abgeschlossene Phase: 82.1, gemerged via PR #205).

## 1. Ziel und Scope

Salerias Avatar reagiert heute auf den User halb deterministisch (Emotion aus
`[tag]`-Regex der LLM-Antwort), halb zufällig (Idle, Blink, Lip-Sync werden
gewürfelt). Diese Phase ersetzt die Zufalls-Trigger durch semantische Eingaben
und führt eine echte Reaktionslogik zwischen LLM/TTS/Sensoren und dem Renderer
ein.

**Im Scope:**

- Aggregierte Emotionsableitung aus LLM-Tag + EmotionTracker-Trend (+ Stub für
  Sensoren).
- Zustandsmaschine mit Crossfade-Übergängen.
- Lip-Sync-Treiber mit Amplitude-Profil als Default-Implementierung (ersetzt
  das 0.18 s-Würfeln).
- Idle-Verhalten kontextsensitiv (Briefing-Modus, Sensor-Presence).
- Architekturweiche Tower vs. Rootserver vs. RPi5 explizit dokumentieren.

**Explizit nicht in dieser Phase** (jeweils eigene Folgephasen):

- Keine neuen Assets, keine YAML-Erweiterung (`avatar_config.yaml` bleibt
  unverändert).
- Kein Body-Splitting (Arme/Beine als separate Layer).
- Keine generative Bilderstellung.
- Keine ElevenLabs-Alignment-API-Migration (echter Phonem-Sync).
- Kein Rhubarb-Phonem-Pipeline.

## 2. Bestandsaufnahme

### 2.1 Heutiger Datenfluss (Ist-Zustand)

```
Matrix-Message
    -> MatrixBridge / message_handlers
    -> Assistant.process(user_input)
        -> llm.generate()
        -> character.extract_emotion(response_text)   # Regex auf [tag]
        -> avatar.show_emotion(emotion)               # lokaler Renderer (Tower)
        -> robot.set_emotion(emotion_str)             # POST /avatar/emotion
        -> avatar.show_speaking(True) + robot.set_speaking(True)
        -> tts.speak()  /  tts.generate_audio()
        -> avatar.show_speaking(False) + robot.set_speaking(False)
```

### 2.2 Beteiligte Klassen (existierend)

| Datei | Klasse | Rolle |
|---|---|---|
| `character/saleria.py` | `SaleriaEngine.extract_emotion` | Regex `\[emotion\]`, hartes Single-Match → `Emotion` oder `NEUTRAL`. |
| `character/emotion_tracker.py` | `EmotionTracker` | Ringbuffer (5 Einträge, 30 min Decay), Valenz/Trend. **Nur** für System-Prompt-Injection, beeinflusst Avatar nicht. |
| `core/assistant.py` (Z. 60–215) | `Assistant.process` | Orchestriert LLM → Emotion → Avatar → TTS. |
| `core/tts_router.py` | `TTSRouter` | ElevenLabs (MP3) → Tower XTTS v2 (WAV) → lokaler Fallback. **Kein Timing-Output.** |
| `tools/elevenlabs_client.py` | `ElevenLabsClient.synthesize` | Standard-Endpoint, liefert nur MP3-Bytes. |
| `tts/coqui_engine.py` | `CoquiTTSEngine.generate_audio` | XTTS v2 → WAV-Datei, kein Phonem-Output. |
| `avatar/layered_renderer.py` | `LayeredSpriteRenderer` | **Renderer + Verhaltens-Engine in einem.** Eigene Idle, Blink, Lip-Sync per `random`. |
| `avatar/avatar_config_loader.py` | `AvatarConfigLoader` | Lädt `avatar_config.yaml` (Emotionen, Mouth-Weights, Idle-Actions). |
| `robot/server.py` | `AvatarDisplay` ABC | Schmale REST-Surface: `set_emotion(str)`, `set_speaking(bool)`, `get_state()`. |
| `robot/rpi5_avatar.py` | `RPi5AvatarDisplay` | Brücke `AvatarDisplay` → `LayeredSpriteRenderer` im eigenen Thread. |
| `robot/simulator.py` | `SimulatedAvatar` | State-Tracking-Mock für lokale Tests. |
| `robot/client.py` | `RobotClient.set_emotion/set_speaking` | HTTP POST `/avatar/emotion`. |

### 2.3 Strukturelle Schwächen (ehrlich, ohne Beschönigung)

1. **Zufalls-Trigger im Renderer.** `_get_lip_sync_mouth` (Z. 431) würfelt
   alle 0.18 s ± Jitter; `_start_idle_action` (Z. 480) wählt
   `random.choice(_idle_actions_config)`; `_schedule_next_blink` (Z. 416)
   `random.uniform(2.0, 6.0)`. Das ist genau das, was als "wirkt zufällig"
   wahrgenommen wird – nicht ein Bug, sondern Design.
2. **Doppelte EMOTION_MAP.** `layered_renderer.py:73` (hardcoded) und
   `avatar_config.yaml` (geladen über `AvatarConfigLoader`). Der YAML-Pfad
   wird im Konstruktor präferiert, bei Fehler kippt's auf Hardcode – wir
   haben zwei Quellen der Wahrheit, die auseinanderlaufen können.
3. **Binary Emotion.** `extract_emotion` findet maximal **ein** Tag; alles
   sonst ist `NEUTRAL`. Keine Confidence, keine Mischung, kein Decay zur
   Emotion-Vorgängerin.
4. **EmotionTracker entkoppelt.** Phase 18 hat einen sauberen Ringbuffer mit
   Trend-Erkennung gebaut, das Ding versorgt aber ausschließlich den
   LLM-System-Prompt (`get_mood_context`). Der Avatar sieht den Tracker nie.
   Doppelarbeit, die im Code als unverbundene Insel rumliegt.
5. **Harter Emotion-Cut.** `LayeredSpriteRenderer.show_emotion` (Z. 314)
   überschreibt `self._current_emotion` sofort. Cheerful → angry springt
   in einem Frame. Es gibt keinen Übergangs-Mechanismus.
6. **Speaking als Boolean.** `show_speaking(True)` / `show_speaking(False)` –
   der Renderer weiß nichts darüber, *was* gerade gesprochen wird.
   Lip-Sync ist Zufallsauswahl aus einem fixen Gewichtungs-Vektor.
7. **Architekturschicht fehlt.** Es gibt keinen Layer zwischen "Bot
   entscheidet etwas" und "Renderer zeichnet ein Frame". Verhalten lebt im
   Renderer, weil es nirgendwo sonst hingebracht wurde.
8. **`can_blink: false` für sad/sarcastic/angry/thoughtful.** Anatomisch
   fragwürdig (Menschen blinzeln auch traurig). Liest sich wie ein
   Sprite-Schutz-Workaround – es gibt vermutlich keine passende
   Closed-Eye-Variante. Das ist eine versteckte Asset-Lücke, kein
   Design-Argument.
9. **Race-Window auf TTS-Ende.** `show_speaking(False)` läuft im `finally`
   des TTS-Blocks. Wenn die nächste `process()`-Iteration parallel anstößt
   (Matrix-Bridge handlet `handle_remote_command_async`), kann ein
   neues `(True)` vor dem alten `(False)` ankommen – der Avatar bleibt in
   einem ungültigen Zustand. Heute nicht beobachtbar, weil die Bridge
   sequenziell ist, aber das ist eine implizite Annahme, kein Vertrag.
10. **Phase 44 Architekturweiche unaufgelöst.** Saleria ist auf den
    Rootserver migriert (PR-Trail Phase 44). Der RobotClient lebt im
    Bot-Prozess – früher Tower, jetzt Rootserver. Die heutige Topologie
    `Bot (Server) -> RobotClient (HTTP) -> RPi5 (RobotServer)` funktioniert,
    aber der Pfad geht jetzt durchs öffentliche Netz / VPN. Tower ist nicht
    mehr automatisch dazwischen. Wo läuft welche Logik?

## 3. Klassen-Architektur (Soll)

OOP, eine Klasse pro Datei, snake_case, DI über Konstruktor. Keine neue
Pub/Sub-Abstraktion (Begründung in 3.5).

### 3.1 EmotionResolver (`character/emotion_resolver.py`)

Aggregiert mehrere Signal-Quellen zu einer `EmotionDecision`.

```python
@dataclass(frozen=True)
class EmotionDecision:
    emotion: Emotion
    confidence: float          # 0.0–1.0
    source: str                # "llm_tag" | "tracker_trend" | "sensor" | "fallback"
    raw_signals: dict[str, float]  # Debug: alle Eingangs-Scores

class EmotionResolver:
    def __init__(
        self,
        character: CharacterEngine,
        emotion_tracker: EmotionTracker,
        tag_weight: float = 0.7,
        trend_weight: float = 0.2,
        sensor_weight: float = 0.1,
    ) -> None: ...

    def resolve_from_llm(
        self,
        llm_response: str,
        sensor_state: SensorState | None = None,
    ) -> EmotionDecision: ...

    def resolve_from_sensor(
        self,
        sensor_state: SensorState,
    ) -> EmotionDecision | None: ...
```

**Rolle:** ersetzt `character.extract_emotion()` an der Assistant-Stelle.
Verarbeitet `[tag]` als dominantes Signal (Gewicht 0.7), zieht den
`EmotionTracker`-Trend als Glättung dazu (0.2), reserviert 0.1 für Sensoren
(SensorState ist Stub, siehe 3.6). Confidence wird aus den Quell-Scores
aggregiert.

`character.extract_emotion()` bleibt als dünner Adapter erhalten (gibt nur
das LLM-Tag zurück), damit alte Tests grün bleiben. Der neue Pfad geht über
den Resolver.

### 3.2 AvatarController (`avatar/controller.py`)

Zentrale Empfangsstelle für semantische Inputs. Lebt auf **RPi5** im selben
Prozess wie der Renderer (im `_render_loop` von `RPi5AvatarDisplay`).
Implementiert `AvatarDisplay` (das ABC aus `robot/server.py`) und ersetzt
damit die heutige Direkt-Verdrahtung `RPi5AvatarDisplay` → `LayeredSpriteRenderer`.

```python
class AvatarController(AvatarDisplay):
    def __init__(
        self,
        renderer: AvatarRenderer,
        state_machine: AvatarStateMachine,
        lip_sync: LipSyncDriver,
        idle_policy: IdleBehaviorPolicy,
    ) -> None: ...

    # AvatarDisplay-Interface (REST-kompatibel) ---
    def set_emotion(self, emotion: str) -> None: ...
    def set_speaking(self, is_speaking: bool) -> None: ...
    def get_state(self) -> dict: ...

    # Erweiterte semantische API (intern + ggf. neue REST-Routen) ---
    def on_emotion_decision(self, decision: EmotionDecision) -> None: ...
    def on_speech_started(self, audio_meta: AudioMetadata) -> None: ...
    def on_speech_ended(self) -> None: ...
    def on_sensor_event(self, event: SensorEvent) -> None: ...
    def on_action_feedback(self, feedback: ActionFeedback) -> None: ...
```

`AudioMetadata` enthält optional eine Amplitude-Spur (siehe 4). Wenn nicht
vorhanden, fällt der `LipSyncDriver` automatisch auf `RandomLipSyncDriver`
zurück (Bestandsverhalten).

`set_speaking(bool)` bleibt als Legacy-Pfad erhalten und ruft intern
`on_speech_started`/`on_speech_ended` ohne `audio_meta` auf. Damit bleibt
das alte REST-Interface `/avatar/emotion` rückwärtskompatibel.

### 3.3 AvatarStateMachine (`avatar/state_machine.py`)

Hält den aktuellen Zustand, plant Übergänge.

```python
@dataclass
class AvatarState:
    emotion: Emotion
    speaking_count: int        # >=0, Counter statt Boolean (Race-Fix)
    attention: AttentionState  # IDLE | FOCUSED | ALERT
    last_change: float         # monotonic timestamp

class AvatarStateMachine:
    def __init__(
        self,
        crossfade_frames: int = 8,    # 8 frames @ 30 FPS = ~266 ms
        direct_cut_pairs: frozenset[tuple[Emotion, Emotion]] = ...,
    ) -> None: ...

    def request_emotion(self, decision: EmotionDecision) -> None: ...
    def speech_increment(self) -> None: ...      # +1 auf speaking_count
    def speech_decrement(self) -> None: ...      # -1, clamped to 0
    def is_speaking(self) -> bool: ...           # speaking_count > 0
    def current_layers(self, now: float) -> RenderPlan: ...
```

`speaking_count` löst die Race-Condition aus 2.3 #9: kommen zwei
`on_speech_started` schnell hintereinander, geht der Zähler auf 2; erst
nach zwei `on_speech_ended` kippt der Avatar zurück.

`direct_cut_pairs`: Default `{(NEUTRAL, ANGRY), (CHEERFUL, ANGRY),
(MOTIVATED, ANGRY), (NEUTRAL, SAD), (SHY, ANGRY)}` – Emotionen mit
sprunghaftem Wechsel wirken unnatürlich, wenn sie crossgefadet werden
("schmiergesicht"). Bei diesen Paaren direkt umschalten.

`RenderPlan` ist ein DTO, das alle für einen Frame benötigten Layer-Keys
plus Alpha enthält – siehe 3.4.

### 3.4 RenderPlan + LayeredSpriteRenderer-Refactor

Heute mischt `LayeredSpriteRenderer.update()` Rendering und Logik. Ziel:

- StateMachine produziert pro Frame ein `RenderPlan(body, eyes, mouth,
  effect, alpha_overlay)`.
- Renderer hat nur noch `render(plan: RenderPlan) -> None`.
- `render_to_file()` bleibt erhalten (für `selfie`/`avatar`-Command in
  `system_commands.py`).
- Crossfade als Alpha-Blend zwischen "alter Plan" und "neuer Plan", 8 Frames.

Damit verschwinden aus dem Renderer: `_update_blink`, `_update_idle`,
`_get_lip_sync_mouth`, `_schedule_next_*`. Diese Logik wandert in
StateMachine / LipSyncDriver / IdleBehaviorPolicy.

### 3.5 Warum kein AvatarEventBus

Der Planungs-Chat schlug einen `AvatarEventBus` als zentrale Schnittstelle
vor. Ich rate davon ab:

- Das Projekt verwendet durchgängig DI über Konstruktor + direkte Methoden-Calls
  (Bridge, Assistant, RobotClient, BriefingScheduler, CalendarWatcher).
- Ein EventBus würde eine neue Abstraktion einführen, die nirgendwo sonst
  benutzt wird – inkonsistent.
- Die Eingangs-Quellen (LLM, TTS, Sensor, Action-Feedback) haben unterschiedliche
  Latenz und unterschiedliche Konsumenten. Ein Bus suggeriert Gleichheit, die
  nicht da ist.
- AvatarController als direkter Empfänger mit getypten Methoden ist
  refactor-sicher (mypy --strict ab Phase 76).

Wenn später mehrere Subscriber dazukommen (z.B. Logging-Sink, Telemetrie),
kann ein Bus *innerhalb* des AvatarController nachgerüstet werden, ohne die
äußere API zu ändern.

### 3.6 IdleBehaviorPolicy (`avatar/idle_policy.py`)

```python
class IdleBehaviorPolicy:
    def __init__(
        self,
        config: AvatarConfig,
        attention_provider: AttentionProvider,
    ) -> None: ...

    def next_action(self, now: float, mood: Emotion) -> IdleAction | None: ...
    def blink_interval(self, mood: Emotion) -> float: ...
```

- Triggert Idle, wenn `not state_machine.is_speaking()` **und** keine
  Sensor-Aktivität in den letzten N Sekunden.
- Briefing-Modus (formell) reduziert Idle-Frequenz um 50 %, lässt nur
  `soft_close` zu, blendet `surprise`/`smile` aus.
- Per-Emotion-Blink-Frequenz: löst das `can_blink: false`-Problem aus 2.3 #8
  ohne YAML-Änderung. Default-Mapping (im Code, nicht in YAML, weil
  Asset-Phase explizit out-of-scope):
  - `NEUTRAL/CHEERFUL/MOTIVATED/WHISPER`: 2–6 s (heutiges Verhalten).
  - `SAD/DEPRESSED`: 5–10 s (langsamer).
  - `ANGRY`: 6–12 s (selten, intensiver Blick).
  - `SARCASTIC/THOUGHTFUL`: 4–8 s.
  - `SHY`: 1–3 s (häufiger).
- `can_blink: false` aus YAML bleibt als Asset-Lock respektiert (wenn kein
  Close-Eye-Sprite existiert, kann auch nicht geblinzelt werden). Aber das
  ist eine Asset-Frage, nicht eine Verhaltensfrage – im Konzept als Befund
  dokumentiert, Fix in einer späteren Asset-Phase.

### 3.7 AttentionProvider (Stub für 83.5)

```python
class AttentionState(Enum):
    UNKNOWN = "unknown"
    AWAY = "away"
    PRESENT = "present"
    FOCUSED = "focused"

class AttentionProvider(ABC):
    @abstractmethod
    def current(self) -> AttentionState: ...

class NoopAttentionProvider(AttentionProvider):
    def current(self) -> AttentionState:
        return AttentionState.UNKNOWN
```

APDS-9960-Hardware ist laut Roadmap (Phase 10) noch offen. Das Interface
wird in 83.6 eingefroren, die echte Hardware-Implementierung kommt in einer
eigenen Hardware-Phase. Default-Wiring nutzt `NoopAttentionProvider`, damit
sich am Verhalten nichts ändert.

## 4. Lip-Sync via Amplitude-Profil

### 4.1 Was TTS heute liefert (ehrliche Antwort)

- **XTTS v2 (`CoquiTTSEngine.generate_audio`)**: nur WAV-Datei. Keine
  Phoneme, kein Timing.
- **ElevenLabs (`ElevenLabsClient.synthesize`)**: nur MP3-Bytes vom
  Standard-Endpoint. ElevenLabs **hat** einen Streaming-Endpoint mit
  Character-Level-Alignment, aber der Router nutzt ihn nicht – eine
  Migration ist eine eigene Phase, hier out-of-scope.
- **RPi5 hat normalerweise gar kein lokales Audio**. Default ist
  `matrix_only`, Audio geht als Sprachnachricht an Matrix → Handy.

### 4.2 Vorschlag: Amplitude-Profil als Beifahrer

```
Bot (Server) generiert Audio
    -> AudioAnalyzer.profile(audio_bytes) -> AmplitudeTrack
        AmplitudeTrack:
            samples: list[float]  # RMS pro 50ms-Bucket, 0.0–1.0
            duration_ms: int
            generated_at: monotonic_ns
    -> RobotClient.set_speaking(True, amplitude_track=...)
        -> POST /avatar/emotion  { "is_speaking": true, "amplitude": [...] }
RPi5 AvatarController.on_speech_started(audio_meta)
    -> LipSyncDriver.start(audio_meta)
        -> AmplitudeLipSyncDriver: Sample-Lookup nach now-start_time
        -> RandomLipSyncDriver (Fallback): unverändertes Zufalls-Verhalten
```

**Amplitude → Mouth-Frame** (deterministisch, im Code, kein YAML):

| RMS-Bucket | Mouth-Frame (aus `avatar_config.yaml`) |
|---|---|
| 0.00–0.05 | `mouth_neutral_close` (Stille / Pause) |
| 0.05–0.20 | `mouth_tiny` |
| 0.20–0.45 | `mouth_halfopen` |
| 0.45–0.75 | `mouth_open` |
| 0.75–1.00 | `mouth_wide` |

Die Buckets sind bewusst nicht uniform – Sprache hat einen RMS-Median im
Bereich 0.1–0.3, die Verteilung muss den dort liegenden Hauptanteil
ausdifferenzieren.

### 4.3 Was das nicht ist

- **Kein echter A/V-Sync.** Audio läuft am Handy via Matrix, Avatar läuft am
  RPi5. Beide bekommen `start`-Trigger zur gleichen Zeit, aber Netzwerk-
  Latenz und Matrix-Buffering können ±300 ms Drift erzeugen. Akzeptabel,
  weil der Avatar im Hologramm-Gehäuse steht und der User typischerweise
  nicht beides gleichzeitig vergleicht – wenn doch, ist Random-Lip-Sync
  schlechter, nicht besser.
- **Keine Phoneme.** Mund öffnet bei "Mmm" gleich weit wie bei "Aaa". Für
  einen Pepper's Ghost-Avatar in 5"-Größe reicht das. Phoneme/Viseme wäre
  eine spätere Qualitätsstufe (ElevenLabs-Alignment-Migration).

### 4.4 Verhalten ohne Amplitude-Profil

Wenn `audio_meta` nicht mitgesendet wird (alter Bridge-Code, externer
Client, Tests), fällt AvatarController automatisch auf
`RandomLipSyncDriver` zurück – exakt das heutige Verhalten. Damit ist die
Migration risikoarm.

## 5. Crossfade-Übergänge

- 8 Frames @ 30 FPS = ~266 ms.
- Alpha-Blend pro Layer (Body, Eye-L, Eye-R, Mouth, Effect). Renderer
  rendert beide RenderPlans (alt + neu) in einen Offscreen-Buffer, blittet
  mit `alpha = lerp(0.0, 1.0, frame/total)`.
- Performance auf RPi5: pygame `Surface.set_alpha()` ist GPU-beschleunigt
  über SDL2, kein Buffer-Refactor nötig. **Risiko:** doppelte Composition pro
  Frame während Crossfade. Auf RPi5 bei 720x1280 messen, bevor 83.3 mergt.
  Falls < 30 FPS → Auflösung auf 540x960 für die Übergangsphase, oder
  Crossfade auf den Mouth-Layer beschränken (Body/Eyes hart wechseln).
- `direct_cut_pairs` (siehe 3.3) übersprungen den Crossfade.

## 6. Kritische Bewertung (Punkte, die im Planungs-Chat nicht da waren)

### 6.1 Performance auf RPi5

- Heute: 30 FPS, ein `blit_centered`-Pfad pro Layer, kein Alpha. Kopf,
  Augen, Mund, Effect → 4 Blits/Frame.
- Mit Crossfade: 8 Blits/Frame während Übergang, danach wieder 4. Bei
  8-Frame-Übergängen und Crossfade-Trigger pro Emotion-Change: meist <1×
  pro Sekunde aktiv.
- LipSyncDriver: Amplitude-Lookup ist O(1), kein neuer Rechenaufwand.
- **Messung vor 83.3-Merge zwingend.** Falls FPS einbricht: Crossfade auf
  Mouth-Layer beschränken.

### 6.2 Race-Condition TTS-Ende ↔ nächster Emotion-Trigger

- Heute potentiell offen (siehe 2.3 #9). Wird durch `speaking_count` in
  `AvatarStateMachine` gelöst.
- Test: `tests/test_avatar_state_machine.py::test_overlapping_speech_increments`.

### 6.3 Phase-44-Architektur-Frage (muss jetzt entschieden werden)

**Frage:** Wenn Saleria auf dem Rootserver läuft, wo läuft die
EmotionResolver-Logik?

**Antwort dieses Konzepts:**
- **EmotionResolver lebt im Bot-Prozess** (= heute Rootserver). Begründung:
  Resolver braucht LLM-Antwort (lebt im Bot) + EmotionTracker-Historie
  (lebt im Bot). Auf den RPi5 zu pushen wäre unnötiger Roundtrip.
- **AvatarController + StateMachine + LipSyncDriver leben auf dem RPi5.**
  Begründung: Render-Loop läuft dort, Latenz für Übergänge muss
  Frame-genau sein, Netzwerk wäre zu lahm.
- **Transport bleibt das bestehende REST-Interface** `RobotClient` →
  `RobotServer` `/avatar/emotion`. Erweitert um optionales `amplitude`-Feld
  und ein optionales `decision`-Objekt (Emotion + Confidence) für Logging /
  Debug.
- **Schmaler Zustand auf der Bot-Seite.** Bot kennt nur die LLM-Output-
  abgeleitete Emotion. RPi5-AvatarController hält den vollen Zustand
  (speaking_count, attention, idle-state). Damit kein verteilter State.

**Konsequenz für RobotClient-Aufrufe:** `set_emotion(emotion, decision=None)`
und `set_speaking(is_speaking, audio_meta=None)`. Beide Parameter optional,
damit Bestandsaufrufe weiter funktionieren. Erweiterung der REST-Payload
ist additiv (`AvatarRequest` in `robot/server.py` bekommt optionale Felder).

### 6.4 Was wenn der RPi5 weg ist

Wenn `RobotClient.is_online() == False`, hat das heute keine Folgen
außerhalb der Server-Statistik. Der EmotionResolver würde trotzdem laufen
(reine Logik), die `_robot.set_*`-Aufrufe gehen ins Leere. Akzeptabel.

### 6.5 Was wenn der User mehrere Turns parallel triggert

Matrix-Bridge ist heute sequenziell pro User; mehrere User schreiben
gleichzeitig ist denkbar. EmotionResolver ist stateless – ok. Tracker hat
einen Ringbuffer pro Engine-Instanz, nicht pro User – das ist ein
bestehender Bug, nicht neu. AvatarController serialisiert intern via
`AvatarStateMachine`, das schon einen `threading.Lock` braucht (heute
implizit über `RPi5AvatarDisplay._lock`). Im Konzept festschreiben: SM ist
nicht thread-safe by default, AvatarController hält den Lock.

## 7. Migrationspfad (Subphasen)

Reihenfolge so, dass Avatar nie länger als einen Commit kaputt ist:

### 83.1 – EmotionResolver standalone

- Neue Datei `character/emotion_resolver.py`, neue Tests
  `tests/test_emotion_resolver.py`.
- `Assistant._build_system_prompt` unverändert. `character.extract_emotion`
  bleibt als Adapter erhalten. Resolver wird optional in `Assistant`
  injiziert (`emotion_resolver: EmotionResolver | None = None`); wenn
  vorhanden, wird sein `resolve_from_llm()` statt `extract_emotion()`
  gerufen. Default = `None`, kein Verhaltensänderung.
- Renderer unverändert.
- **Akzeptanz:** alle Tests grün, `extract_emotion` bleibt im Suite.
- **Risiko:** minimal, isoliertes Modul.

### 83.2 – AvatarController + StateMachine + RenderPlan

- Neue Dateien `avatar/controller.py`, `avatar/state_machine.py`,
  `avatar/render_plan.py`.
- `LayeredSpriteRenderer` bekommt `render(plan: RenderPlan)`. Alte
  `update()` bleibt als Adapter, der intern den Plan baut. Verhalten
  identisch.
- `RPi5AvatarDisplay` wird umgezogen: statt direkt
  `LayeredSpriteRenderer.show_emotion/show_speaking` ruft es jetzt
  `AvatarController.set_emotion/set_speaking`.
- Idle, Blink, Lip-Sync **bleiben in dieser Subphase im Renderer** (kein
  Refactor in einem Commit). Verhalten identisch.
- **Akzeptanz:** Suite grün, Renderer-Tests unverändert, neue Tests für
  Controller + StateMachine.

### 83.3 – Crossfade

- StateMachine produziert während `_in_transition` zwei RenderPlans (alt +
  neu) mit Alpha. Renderer composited.
- `direct_cut_pairs`-Default wie in 3.3.
- **Pflichtmessung:** 30-FPS-Hold-Test auf RPi5 (oder Simulator mit
  zeitgenauer Frame-Stopwatch).
- **Akzeptanz:** FPS-Test grün, visueller Smoketest auf RPi5.

### 83.4 – LipSyncDriver (RandomLipSync + AmplitudeLipSync)

- Neue Datei `avatar/lip_sync.py` mit ABC + zwei Implementierungen.
- AudioAnalyzer in `core/audio_analyzer.py` (oder in `tts/`, je nachdem
  wo's natürlicher liegt – im Konzept zu klären beim Implementieren).
  Liefert `AmplitudeTrack` aus WAV/MP3-Bytes via numpy RMS.
- `AvatarRequest`-Pydantic-Model in `robot/server.py` bekommt optionales
  `amplitude: list[float] | None = None` und `amplitude_duration_ms: int |
  None = None`.
- `RobotClient.set_speaking(is_speaking, audio_meta=None)`.
- `Assistant` baut nach `tts.generate_audio()` (oder vor `tts.speak()`)
  den `AmplitudeTrack` und sendet ihn mit. Wenn `AudioAnalyzer` nicht
  verfügbar (z.B. PortAudio-Mock im CI), keine Spur → Fallback auf
  `RandomLipSyncDriver`.
- **AmplitudeLipSyncDriver ist Default.** Wenn `audio_meta is not None`
  und nicht leer, wird er aktiviert. Sonst RandomLipSyncDriver.
- **Akzeptanz:** Unit-Tests für beide Driver, Integrationstest mit
  generiertem 1-Sekunden-WAV (Sinus + Stille → 5 Buckets sichtbar).

### 83.5 – Resolver/Controller-Anbindung an Assistant

- `Assistant.__init__` bekommt optional `emotion_resolver` (siehe 83.1) und
  benutzt diesen jetzt aktiv (statt `character.extract_emotion`).
- Spread-Update auf `RobotClient.set_emotion(..., decision=...)` für
  Server-Logging.
- **Akzeptanz:** End-to-End-Test: LLM-Antwort `"[cheerful] Hi"` →
  AvatarController bekommt Decision mit confidence>0.7 → StateMachine
  triggert Übergang von NEUTRAL.

### 83.6 – IdleBehaviorPolicy + AttentionProvider-Stub

- Neue Datei `avatar/idle_policy.py`, Stub-Datei `avatar/attention.py`.
- Idle-Logik aus `LayeredSpriteRenderer._update_idle` / `_schedule_next_idle`
  / `_start_idle_action` rauspflücken → IdleBehaviorPolicy.
- Blink-Logik aus `_update_blink` / `_schedule_next_blink` ebenfalls in
  IdleBehaviorPolicy (Per-Emotion-Intervalle siehe 3.6).
- Briefing-Modus-Erkennung: Assistant kennt den `BriefingScheduler` /
  `briefing_mode`-Flag (existiert in `core/`)? **Zu prüfen beim
  Implementieren** – wenn nicht, in dieser Subphase ein schmales
  `BriefingModeProvider`-Stub einbauen, das auf BriefingScheduler-State
  liest.
- **Akzeptanz:** Tests für Idle-Frequenz pro Mood, formeller vs. casual
  Modus.

## 8. Tests

Pytest-Konvention (eine Testdatei pro Klasse, asyncio_mode=auto). Erwartete
neue Dateien:

| Datei | Umfang |
|---|---|
| `tests/test_emotion_resolver.py` | Tag-Parse, Trend-Aggregation, Sensor-Stub, Confidence-Math, leere LLM-Antwort. |
| `tests/test_avatar_controller.py` | set_emotion/set_speaking-Legacy-Pfad, on_emotion_decision, speech_count, Sensor-Event. |
| `tests/test_avatar_state_machine.py` | request_emotion, Crossfade-Frame-Sequenz, direct_cut_pairs, overlapping speech increments. |
| `tests/test_render_plan.py` | Layer-Defaults, Idle-Override, Speaking-Override-Priorität. |
| `tests/test_lip_sync_driver.py` | RandomLipSyncDriver (Bestand parametrisiert), AmplitudeLipSyncDriver (Bucket-Mapping, Stille-Pausen). |
| `tests/test_audio_analyzer.py` | Sinus → bekannte RMS-Werte, MP3- und WAV-Pfad. |
| `tests/test_idle_behavior_policy.py` | Trigger-Bedingungen, Briefing-Modus, Per-Emotion-Blink-Intervall. |

Bestehende Tests, die anzupassen sind:

- `tests/test_layered_renderer.py`: Renderer-API-Adapter (alte `update()`-
  Tests bleiben grün), zusätzliche Crossfade-Tests.
- `tests/test_rpi5_avatar.py` (falls vorhanden – beim Implementieren
  prüfen): Wiring auf AvatarController.

Mocks: `unittest.mock` reicht. Keine neuen externen Mock-Libraries.

## 9. Risiken

| Risiko | Wahrscheinlichkeit | Gegenmaßnahme |
|---|---|---|
| Crossfade auf RPi5 zu langsam | mittel | Messung vor Merge 83.3, Fallback auf Mouth-only-Crossfade. |
| Amplitude-Profil-Latenz lässt Avatar zu spät loslegen | mittel | `on_speech_started` direkt beim Bot-Generate-Beginn senden, nicht erst nach `generate_audio()`. |
| Bestehende Tests `extract_emotion`-spezifisch brechen | niedrig | Adapter behalten, Resolver opt-in (83.1) → erst in 83.5 verpflichtend. |
| `speaking_count` ändert beobachtbares Verhalten | niedrig | Counter clampt auf >=0; Verhalten bei „normalem" Single-Turn-Flow identisch zu Boolean. |
| `BriefingMode`-Detection-Lücke (83.6) | mittel | Im Konzept als Zu-Prüfen markiert, Subphase 83.6 startet mit kleinem Audit. |

## 10. Was bewusst offen bleibt

- **Wo läuft `AudioAnalyzer`?** `core/`, `tts/`, oder `tools/`? Entscheidung
  beim Implementieren von 83.4. Heutige TTS-Pipeline ist nicht in einer
  Klasse gekapselt, sondern als Methoden-Folge in `Assistant.process()`.
  Der Analyzer ist die natürliche Klammer.
- **Was passiert, wenn der Bot den Avatar nicht mehr nutzt** (z.B. reiner
  Matrix-Modus ohne RPi5): RobotClient ist optional. Resolver läuft
  trotzdem, Decisions landen im Log, ggf. Telemetrie. Nichts kaputt.
- **Asset-Lücke `can_blink: false` für sad/angry/sarcastic/thoughtful**:
  identifiziert, hier dokumentiert, Fix als eigene Asset-Phase. Diese Phase
  respektiert das YAML-Flag.

## 11. Folge-/Out-of-Scope-Phasen (zur Erinnerung)

- **Asset-Erweiterung**: Closed-Eye-Varianten für alle Emotionen, neue
  Mouth-Frames für Phoneme/Viseme.
- **ElevenLabs-Alignment-Migration**: Streaming + Character-Level-Timing für
  echten Phonem-Sync.
- **Body-Splitting**: Arme/Schultern als separate Layer für Gestik.
- **Generative Bilderstellung**: ML-basierte Sprite-Variation.
- **APDS-9960 Hardware-Integration**: AttentionProvider-Implementierung mit
  echter I²C-Kommunikation.

---

**Reviewer-Hinweise:**

1. Crossfade-Default 8 Frames: zu langsam (zu sehr "weich"), zu schnell
   (kaum wahrnehmbar)? Bauchgefühl vs. realer Test ist hier ein
   Implementierungs-Detail.
2. Amplitude-Buckets nicht uniform – ist 0.45–0.75 die richtige Range für
   `mouth_open`? Wird sich beim Implementieren zeigen, ggf. mit der
   Mouth-Frame-Gewichtung aus `avatar_config.yaml:lip_sync.frames`
   abgleichen.
3. Per-Emotion-Blink-Intervalle sind eine Designentscheidung. Wenn Lera
   das anders sieht: Werte sind zentralisiert in `IdleBehaviorPolicy`,
   ein-Zeilen-Edit.
