# Phase 106 – Modul-Entflechtung große Dateien (Konzept)

**Befund:** Q1 (sehr große Dateien, AGENTS.md-Richtlinie „max ~400 Zeilen/Chunk")
**Branch (geplant):** `feature/phase-106-modul-entflechtung`
**Status:** Konzept. Größter Umbau, daher zuletzt. Einzeln, mit Re-Exports zur
Importstabilität.

## Ziel

Die >1000-Zeilen-Dateien entlang klarer Verantwortlichkeiten zerlegen, ohne
öffentliche Importpfade oder Test-Direktaufrufe zu brechen.

## Kandidaten (gemessen 2026-06-16)

| Datei | Zeilen | Klasse |
|---|---|---|
| `comms/message_handlers.py` | 2387 | `BridgeMessageHandler` (~36 Methoden) |
| `comms/commands/weather_commands.py` | 1156 | `WeatherCommandHandler` |
| `core/assistant.py` | 1129 | `Assistant` |
| `web/settings_dashboard.py` | 1120 | `SettingsDashboard` |
| `comms/confirmation_handlers.py` | 1087 | `ConfirmationHandler` |
| `robot/server.py` | 1011 | `RobotServer` (+ 8 Pydantic-Modelle, 3 ABCs, Middleware) |

## Hauptkandidat: `message_handlers.py`

### Befund

Eine Gottklasse (`BridgeMessageHandler`) mit ~36 Methoden in **6 logischen
Blöcken** (im Code bereits durch `====`-Kommentar-Blöcke markiert): Remote-Command-
Dispatch · Enrichment (Doku/Web/Mail) · File-Hub/Attachment · list_pick/picks/
nearby · Action-Sequence-Engine · Standard-LLM-Flow. Alle Methoden teilen sich
gemeinsamen `self._*`-State. Einziger Produktiv-Importeur: `bridge.py`.
`ConfirmationHandler` (eigene Datei) greift bereits via `self._p` auf >15 private
Parent-Attribute **und** `_p._handle_llm_enrichment` zu (erprobtes Parent-Ref-Muster).

### Lösung: Mixin-Zerlegung (nicht echte Einzelklassen)

Eine echte „eine-Klasse-pro-Datei"-Trennung ist **nicht** ohne massenhaft
Delegations-Wrapper möglich (Tests rufen `handler._private()` direkt). Der
risikoarme Weg: 6 Mixin-Module unter `comms/handlers/`, plus dünne
Wrapper-Klasse:

```python
class BridgeMessageHandler(
    CommandDispatchMixin, EnrichmentMixin, FileHubMixin,
    ListPickMixin, ActionSequenceMixin, LlmFlowMixin,
):
    # __init__ + handle_claude_agent + handle_pending_* (Confirmation-Delegation)
```

Jede Mixin-Datei ≤ 400 Z. Öffentlicher Importpfad
(`elder_berry.comms.message_handlers.BridgeMessageHandler`) bleibt stabil → weder
`bridge.py` noch `confirmation_handlers.py` noch die 6 Test-Module brechen.
Reihenfolge (klein→groß): zuerst `action_sequence` und `file_hub` (eigene
Test-Module, geringe Kopplung), dann `llm_flow` und `picks`.

### Größtes verstecktes Risiko

`tests/test_comms.py:1162/1197/1224` patcht `elder_berry.comms.message_handlers.logger`.
Drei asserted `logger.error`-Aufrufe (command / command:status / llm) liegen in
`handle_remote_command` bzw. `handle_assistant_message` → wandern in
`CommandDispatchMixin`/`LlmFlowMixin`. **Lösung:** die Mixins importieren den
**einen** Logger aus dem Wrapper-Modul (`from elder_berry.comms.message_handlers
import logger`) statt je `getLogger(__name__)` — so bleibt der Patch gültig. Vor
dem Split die Logger-Assertions inventarisieren.

## Die übrigen 5 Dateien (je Ein-Satz-Ansatz)

- **`confirmation_handlers.py`** (1087): nach Action-Typ in Mixins schneiden
  (Mail-Reply / Filing / Restart / Nextcloud+Attachment); Parent-Ref bleibt.
- **`weather_commands.py`** (1156): entlang der Docstring-Domänen in eigene
  `CommandHandler`-Subklassen teilen — Kern-Wetter, `ReminderCommandHandler`
  (~600 Z. Timer/Reminder), `MiscCommandHandler` (Briefing/Training/PRs).
- **`settings_dashboard.py`** (1120): `SettingDefinition`-Registry +
  Serialisierung/Validierung in ein `settings_registry`-Modul; die ~440 Z.
  Route-Closures aus `_register_routes` in einen Router-Builder.
- **`assistant.py`** (1129): Prompt-Bau (`_build_*`) in einen `PromptBuilder`,
  die Robot-Action-Brücke (`_execute_robot_action`/`_robot_*`/TTS/Lipsync) in ein
  eigenes Modul; `Assistant.process` bleibt Orchestrator.
- **`robot/server.py`** (1011): die 8 Pydantic-Modelle nach `robot/schemas.py`,
  die 3 ABCs (`MotorController`/`AvatarDisplay`/`SensorManager`) nach
  `robot/interfaces.py`; `RobotServer` + `_register_routes` bleiben.

## Risiken

- Mixins haben keinen eigenen `__init__` und setzen `self._*` voraus → für den
  Type-Checker Protocol-/`TYPE_CHECKING`-Stub nötig.
- AGENTS.md „eine Klasse pro Datei": Mixins erfüllen das formal, sind aber keine
  eigenständig nutzbaren Klassen → **mit Lera abstimmen**, ob der Mixin-Ansatz
  akzeptiert wird oder eine andere Dekomposition gewünscht ist.
- Symbol-Verschiebungen (Pydantic-Modelle, ABCs) brauchen **Re-Exports** im
  Ursprungsmodul, sonst brechen externe Importe/Test-Patches.
- `weather_commands`-Split: Pattern-Routing über Confidence/priority — beim
  Verteilen auf mehrere Plugins die priority-Vergabe prüfen (Gleichstand kann
  kippen).

## Offene Entscheidungen (für Lera)

- Mixin-Ansatz akzeptiert (pragmatisch, Surface erhalten) oder echte Sub-Handler
  mit Delegations-Wrappern (sauberer, aber Test-Bruch)?
- `ConfirmationHandler` ins selbe neue `handlers/`-Paket ziehen?

## Definition of Done

1. Pro Datei eine eigene Etappe; nach jeder Etappe voller pytest grün, alle
   Importpfade stabil (Re-Exports), keine still-falsch-grünen Logger-Patches.
2. Jede neue Datei ≤ ~400 Z.; öffentliche API unverändert.
3. Journal-Eintrag je Etappe.
