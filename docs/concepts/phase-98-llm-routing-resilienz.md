# Phase 98 – Health-aware LLM-Routing + Privacy-Modus (Konzept)

## Ziel

Drei am Code verifizierte Bugs im LLM-Routing beheben, die zusammen dafür
sorgen, dass Saleria bei einer Cloud-Störung grundlos „dümmer" oder ganz
stumm wird, und dass die im Dashboard angebotenen Routing-Modi faktisch nie
end-to-end funktioniert haben:

1. **Kein Runtime-Fallback**: Bei einer Anthropic-Störung/Rate-Limit fliegt
   ein `RuntimeError`, statt auf das danebenlaufende Ollama (phi4:14b)
   auszuweichen. Der „Offline-Fallback" greift heute nur, wenn **kein** Key
   gesetzt ist – nicht bei einem Laufzeitfehler trotz Key.
2. **Mode geht beim Neustart verloren**: `/api/llm/mode` persistiert den Modus
   in den SecretStore, aber `init_llm()` liest ihn beim Start nie zurück → nach
   jedem Restart wieder `api_preferred`.
3. **Wertemengen-Mismatch**: UI/Registry kennen
   `{api_preferred, local_preferred, fallback_only}`, der Router nur
   `{api_preferred, local_only}` → über das Settings-Dashboard gespeicherte
   Modi sind für den Router ungültig (und würden nach Fix #2 den
   Router-Konstruktor mit `ValueError` crashen).

Zusätzlich (Lera-Entscheid: **mitnehmen**) ein **Privacy-Modus**: ein
Laufzeit-Schalter, der STT/TTS/LLM hart auf die lokale Pipeline (Tower
FasterWhisper / Tower-XTTS bzw. lokale Engine / Ollama) zwingt – mit **harter**
lokal-only-Semantik (failt statt still in die Cloud zurückzufallen) und
sichtbarem Statusfeedback. Deckt das Projektprinzip „Lokale KI-Pipeline, kein
Cloud-Zwang" ab; heute geht Sprachaudio an Groq/ElevenLabs.

## Leitprinzipien

- **Runtime-Health statt nur Key-Existenz**: Verfügbarkeit eines Backends
  entscheidet sich am tatsächlichen Antwortverhalten zur Laufzeit, nicht nur
  an `bool(api_key)`. Vorbild ist das bereits existierende Muster in
  `core/tts_router.py` / `core/stt_router.py` (try primär → `except` → warn →
  nächstes Backend → erst dann Unavailable).
- **Eine Quelle der Wahrheit**: Die Menge der gültigen Routing-Modi (+ Labels)
  lebt an **einer** Stelle (`llm/modes.py`) und wird von Router, llm_api,
  Settings-Dashboard und Secrets-Registry importiert. Kein hartcodiertes
  Vokabular mehr an vier Orten.
- **Kein Flapping**: Ein gestörtes Backend wird nach einem Fehler für eine
  Cooldown-Zeit übersprungen (schlanker Circuit-Breaker), statt bei jeder
  Nachricht erneut in den langsamen Timeout zu laufen.
- **Transparenz statt stiller Degradation**: Jeder Backend-Wechsel wird
  geloggt **und** im Chat einmalig markiert (Hin- und Rückweg), damit ein
  lokales Ausweichmodell nicht als „Saleria ist plötzlich dumm" missverstanden
  wird.
- **Privacy = hart, nicht best-effort**: Im Privacy-Modus ist ein Cloud-Call
  ein Fehler, kein stiller Fallback. Lieber sichtbar scheitern als heimlich
  Audio/Text in die Cloud schicken.
- **Composition/DI bleibt**: keine neuen Parallelstrukturen, keine globalen
  Singletons; `PrivacyState` wird explizit per Konstruktor injiziert.

## Problemanalyse (am echten Code verifiziert, 2026-06-14)

### Bug 1 – Kein Runtime-Fallback

- `llm/anthropic_client.py:86-88`: `is_available()` → `bool(self._api_key)`,
  prüft nur Key-Existenz.
- `llm/router.py:92-94`: `generate()` ruft `_select_client().generate()`
  **ohne** try/except. `AnthropicClient.generate()` wandelt
  `APIStatusError` / `RateLimitError` / `APIConnectionError` in `RuntimeError`
  (`anthropic_client.py:117-124`) → der propagiert ungebremst.
- `_select_client()` (`router.py:67-87`) wechselt nur dann auf Ollama, wenn
  `is_available()` False ist – also nur ohne Key. Ein Laufzeitfehler **trotz**
  Key fällt durch, obwohl Ollama erreichbar wäre.

### Bug 2 – Mode geht beim Neustart verloren

- `web/llm_api.py:82-85`: POST `/api/llm/mode` setzt den Router live **und**
  persistiert `LLM_MODE_KEY` im SecretStore. Korrekt.
- `scripts/start_saleria.py:195-206`: `init_llm()` ruft
  `LLMRouter.create_default()` (Default `api_preferred`) und liest den
  persistierten Modus **nie** zurück. `init_llm()` hat aktuell nicht einmal
  Zugriff auf den SecretStore.

### Bug 3 – Wertemengen-Mismatch

- Router: `VALID_MODES = ("api_preferred", "local_only")` (`router.py:22`);
  `llm_api.py:74` validiert dieselben zwei.
- Settings-Dashboard (`settings_dashboard.py:448` + `:482`) und Registry
  (`secrets_registry.py:379-381`) verwenden
  `{api_preferred, local_preferred, fallback_only}`.
- `secrets_registry.validate_secret()` hat **keine** `select`-Validierung
  (nur int/float/url/pattern) → die Optionsmenge wird dort nicht erzwungen;
  einzige Schranke ist das hartcodierte Set im Dashboard.
- Folge: Zwei UIs schreiben denselben Key `llm_mode` mit zwei Vokabularen;
  der Dashboard-Pfad aktualisiert den Live-Router gar nicht. Zusammen mit
  Bug 2 hat die 3-Modi-UI **nie** funktioniert.

## Lösung / Architektur

### Kanonische Modi (Lera-Entscheid: Option B – 3 Modi)

| Modus | Backend-Reihenfolge | Semantik |
|-------|---------------------|----------|
| `api_preferred`  | Anthropic → Ollama | Cloud zuerst, lokal als Fallback (Default) |
| `local_preferred`| Ollama → Anthropic | Lokal zuerst, Cloud nur als Fallback |
| `local_only`     | Ollama (hart)      | Nur lokal, kein Cloud-Fallback |

Legacy-Wert `fallback_only` („Nur Fallback/Lokal") wird beim Read auf
`local_only` normalisiert (`normalize_llm_mode()`), damit bereits gespeicherte
Dashboard-Werte nicht crashen.

### 98-A – Single Source of Truth: `llm/modes.py` (neu)

Schlankes, reines Konstanten-Modul (kein httpx/anthropic-Import):

```python
LLM_MODES: tuple[str, ...] = ("api_preferred", "local_preferred", "local_only")
DEFAULT_LLM_MODE = "api_preferred"
LLM_MODE_LABELS: dict[str, str] = {
    "api_preferred":   "API bevorzugt",
    "local_preferred": "Lokal bevorzugt",
    "local_only":      "Nur lokal",
}
_LEGACY_ALIASES = {"fallback_only": "local_only"}

def normalize_llm_mode(value: str | None) -> str | None:
    """Kanonisiert/validiert einen Modus. None bei unbekanntem Wert."""
```

Importiert von: `router.py` (`VALID_MODES = LLM_MODES`), `llm_api.py`,
`settings_dashboard.py`, `secrets_registry.py`.

### 98-B – Runtime-Fallback + Circuit-Breaker im `LLMRouter`

`generate()` iteriert über die mode-abhängige Backend-Reihenfolge:

```python
order = self._ordered_backends()        # je Modus, s. Tabelle
for i, client in enumerate(order):
    last = i == len(order) - 1
    if not last and self._in_cooldown(client):
        continue                        # gestörtes Backend überspringen
    if not client.is_available():
        continue
    try:
        result = client.generate(prompt, system)
    except Exception as exc:            # Runtime-Fehler → Backend trippen
        self._trip_cooldown(client)
        logger.warning("LLM-Backend %s fehlgeschlagen: %s", name, exc)
        continue
    self._record_served(client, top=order[0])
    return result
raise RuntimeError("Kein LLM-Backend verfügbar. ...")
```

- **Circuit-Breaker**: pro Client-Objekt ein `cooldown_until` (Dict keyed auf
  `id(client)`), `time.monotonic()`-basiert. Default `cooldown_seconds=60.0`,
  per Konstruktor injizierbar (Tests). Das **letzte** Backend der Kette wird
  nie wegen Cooldown übersprungen (Last-Resort).
- **Degradations-Signal**: `_degraded` (True, wenn das bedienende Backend
  nicht das Top-Backend des Modus ist) + `pop_backend_notice() -> str | None`,
  das den Wechsel **einmalig** pro Transition meldet (degrade ↔ recover).
- `active_backend` liefert das zuletzt bediente Backend, sonst (vor dem ersten
  `generate()`) das erste verfügbare der Kette – Tests
  `test_active_backend_*` bleiben grün.
- `local_only` = Kette `[fallback]`; schlägt Ollama fehl → `RuntimeError`
  (harte Semantik erhalten).
- Bestehende Tests (`test_prefers_primary_when_available` inkl.
  `fallback.generate.assert_not_called()`, `test_falls_back_to_fallback`,
  `test_raises_when_neither_available` mit Match „Kein LLM-Backend") bleiben
  gültig.

### 98-C – Mode-Read-Back in `init_llm()`

`init_llm(secret_store)` (DI): nach `create_default()` den persistierten
`llm_mode` lesen, via `normalize_llm_mode()` kanonisieren und `router.mode`
setzen. Unbekannt/leer → `DEFAULT_LLM_MODE`. `main()` reicht den ohnehin
vorhandenen `SecretStore` herein.

### 98-D – Web-Angleichung (eine Quelle, Live-Apply)

- `web/llm_api.py`: Validierung gegen `LLM_MODES` (Import). Status-Endpoint um
  `degraded: bool` ergänzt.
- `web/settings_dashboard.py`: `_get_setting_value` normalisiert via
  `normalize_llm_mode`; `_validate_setting_value` gegen `LLM_MODES`. Der
  generische Settings-Schreibpfad wendet den Modus **live** auf
  `self._llm_router` an (beide Schreibpfade konvergieren). `requires_restart`
  entfällt damit faktisch.
- `web/secrets_registry.py`: `select_options` aus `LLM_MODE_LABELS` ableiten;
  optional generische `select`-Validierung in `validate_secret` gegen
  `select_options` (schließt die erkannte Lücke).

### 98-E – Chat-Markierung des Backend-Wechsels

`core/assistant.py` (`process()`, nach `self._llm.generate(...)`): falls der
Router `pop_backend_notice()` einen Hinweis liefert, wird er knapp an
`response_text` angehängt, z. B. „_(Hinweis: Cloud-LLM gerade nicht erreichbar
– ich antworte lokal über Ollama.)_". Nur Transitionen, nicht jede Nachricht.

### 98-P – Privacy-Modus (eigene Etappe)

- `core/privacy_state.py` (neu): `PrivacyState` mit `enabled`, `enable()`,
  `disable()`, `is_enabled`. Per DI in `LLMRouter`, `STTRouter`, `TTSRouter`
  injiziert (optionaler Konstruktor-Parameter, Default = aus).
- **LLM**: bei `is_enabled` Kette hart `[fallback]` (Ollama), unabhängig vom
  `mode`; Fehler → `RuntimeError`.
- **STT**: `transcribe_async()` überspringt Groq, geht direkt auf Tower; Tower
  down → `STTUnavailableError` (kein Cloud-Fallback).
- **TTS**: `synthesize()` / `generate_audio()` überspringen ElevenLabs,
  nutzen Tower-XTTS bzw. lokale Engine (beide ohne Cloud); kein ElevenLabs.
- **Command**: Toggle in `comms/commands/system_commands.py`
  („lokaler modus an/aus", „privatmodus", Status) mit sichtbarer Rückmeldung;
  setzt `PrivacyState`.

**Scope-Festlegung (Privacy):** `PrivacyState` ist ein **geräteweiter
Laufzeit-Schalter**, nicht pro Matrix-Raum. Begründung: Saleria hat **ein**
physisches Mikrofon/Lautsprecher (Audio ist inhärent geräteweit), und „nichts
verlässt die Box" ist als globaler Schalter die sichere Semantik. Eine
pro-Raum-/pro-User-Isolation (nur LLM) wäre ein separater Follow-up und ist
hier bewusst **nicht** umgesetzt (YAGNI).

## Betroffene Dateien / Klassen

| Datei | Änderung |
|-------|----------|
| `src/elder_berry/llm/modes.py` *(neu)* | Kanonische Modi + Labels + `normalize_llm_mode()` |
| `src/elder_berry/llm/router.py` | Runtime-Fallback, Circuit-Breaker, 3 Modi, `pop_backend_notice()`, `degraded`; `VALID_MODES = LLM_MODES`; optional `PrivacyState` |
| `scripts/start_saleria.py` | `init_llm(secret_store)` Read-Back; `PrivacyState` erzeugen + in LLM/STT/TTS/Command verdrahten |
| `src/elder_berry/web/llm_api.py` | Validierung gegen `LLM_MODES`; Status `degraded` |
| `src/elder_berry/web/settings_dashboard.py` | Kanonische Menge + Normalisierung; Live-Apply auf `_llm_router` |
| `src/elder_berry/web/secrets_registry.py` | `select_options` aus `LLM_MODE_LABELS`; `select`-Validierung in `validate_secret` |
| `src/elder_berry/core/assistant.py` | Backend-Hinweis aus `pop_backend_notice()` an Antwort anhängen |
| `src/elder_berry/core/privacy_state.py` *(neu)* | `PrivacyState` |
| `src/elder_berry/core/stt_router.py` | Privacy-Pfad (hart Tower, kein Groq) |
| `src/elder_berry/core/tts_router.py` | Privacy-Pfad (hart Tower/lokal, kein ElevenLabs) |
| `src/elder_berry/comms/commands/system_commands.py` | Privacy-Toggle-Command + Hilfe |

## Tests

- `tests/test_llm_router.py` (erweitern): Runtime-Fallback (primär
  `generate` wirft → fallback bedient); Circuit-Breaker (gestörtes Backend
  wird im Cooldown übersprungen, nach Ablauf wieder versucht – mit injizierter
  Zeit); `local_preferred`-Reihenfolge; `local_only` Hard-Fail;
  `pop_backend_notice()` (einmalig je Transition).
- `tests/test_llm_modes.py` *(neu)*: `normalize_llm_mode` inkl. Legacy-Alias.
- `tests/test_llm_api.py` (erweitern): Validierung gegen kanonische Menge;
  `degraded` im Status.
- `tests/test_settings_dashboard.py` (erweitern): kanonische Menge,
  Normalisierung, Live-Apply.
- `tests/test_start_saleria*`: `init_llm` wendet persistierten Modus an
  (Read-Back), unbekannter Wert → Default.
- `tests/test_privacy_state.py` *(neu)* + Router-Privacy-Pfade in
  `test_llm_router.py` / `test_stt_router.py` / `test_tts_router.py`;
  Command-Test für den Toggle.
- pytest `asyncio_mode=auto`, eine Testklasse pro Datei.

## Offene Entscheidungen (durch Lera entschieden)

- **Vokabular**: Option **B** (3 Modi `{api_preferred, local_preferred,
  local_only}`, eine Quelle der Wahrheit). ✅
- **Privacy-Modus**: **mitnehmen** (eigene Etappe 98-P). ✅
- **Phasennummer**: **98** (Roadmap endet bei 97). ✅

## YAGNI-Grenzen

- **Kein** Health-Poller-Thread: Der Fallback ist live-pro-Call; der
  Circuit-Breaker reicht gegen Flapping.
- **Keine** pro-Raum-Privacy (s. Scope-Festlegung) – geräteweiter
  Laufzeitschalter genügt.
- **Keine** Änderung am Anthropic-/Ollama-Wire-Protokoll, kein neues
  Result-Objekt; `is_available()` der Clients bleibt unverändert (der
  Runtime-Health lebt im Router, nicht im Client).
- **Kein** persistenter Privacy-Zustand über Neustart (Laufzeit-Schalter;
  nach Restart wieder aus – bewusst, „privacy default off, explizit an").

## Bekannte Risiken

- Der Runtime-Fallback maskiert eine dauerhafte Anthropic-Fehlkonfiguration
  (z. B. ungültiger Key → 401) als „läuft lokal weiter". → Deshalb wird der
  Wechsel geloggt **und** im Chat markiert; 401/Auth bleibt im Log
  unterscheidbar.
- `local_preferred` als neuer Default-Pfad lenkt Last auf Ollama (phi4:14b,
  langsamer/schwächer). Bewusst nur, wenn der Nutzer ihn wählt; Default bleibt
  `api_preferred`.
- Privacy-Verdrahtung berührt mehrere `init_*`-Funktionen in
  `start_saleria.py`; Fehlerquelle = vergessenes Backend. → Akzeptanztest
  prüft alle drei Pipelines.

## Definition of Done

1. Code committed (Branch `feature/phase-98-llm-routing-resilienz`), **kein PR**
   (macht Lera).
2. Voller `pytest` grün; `ruff` + `mypy --strict` auf allen geänderten Modulen.
3. **Kern-Akzeptanztest**: Anthropic-`generate()` wirft zur Laufzeit (trotz
   gesetztem Key) → Antwort kommt aus Ollama, **ohne** Bot-Neustart; der
   Wechsel ist geloggt und im Chat markiert.
4. **Read-Back-Akzeptanz**: `llm_mode` im SecretStore = `local_preferred` →
   nach `init_llm()` ist `router.mode == "local_preferred"`.
5. **Privacy-Akzeptanz**: Schalter an → STT/TTS/LLM nutzen ausschließlich
   lokale Backends; Cloud-Ausfallpfade werden nicht beschritten; sichtbares
   Statusfeedback.
6. Append-only Journal-Eintrag mit ausgeführten Tests + nächstem Schritt.
