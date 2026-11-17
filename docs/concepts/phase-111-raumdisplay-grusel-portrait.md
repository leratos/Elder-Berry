# Phase 111 – Raumdisplay „Rahmen“ mit Inhaltsmodus Grusel-Portrait

**Status:** freigegeben durch Lera am 2026-11-17; Entscheidungen D1–D7 getroffen (#1475), D8 nur bedingt offen (§10)
**Branch:** `phase-111-raumdisplay-portrait`, drei Teil-PRs (D6)
**Grundlage:** elder-berry #1443–#1468, insbesondere Preflight #1459, Auswertung #1460, Entscheidungen #1461 und #1467; Sensorwerte #1436–#1441; Selfie-Bugfix #1462–#1464; Preflight E0 #1473, Konzeptänderungen Ae1–Ae16 #1474, Entscheidungen D1–D7 #1475
**Quelle:** Diese Datei ist der Wortlaut von #1469 (ab „# Phase 111“) und #1470 mit den Änderungen aus #1474 und #1475, in die Abschnitte eingearbeitet. Die Journal-Einträge bleiben die Quelle.
**Code-Stand der Aussagen:** am Code geprüft in E0 (#1473) auf main @ 5b2cce0.
**Termine:** Party 2026-12-31 · Entscheidungstor Stufe 1: 2026-12-06 (#1461)

## 1. Ziel

Bis Silvester entsteht **ein** Bilderrahmen mit eigener Hardware: RPi, 7-Zoll-DSI-Display (720×1280 nativ, quer betrieben), Camera Module 3 Standard, APDS-9960 und BME280. Er zeigt ein Gemälde. Tritt ein Gast in den Nahbereich, nimmt er ein Foto auf, lässt daraus über OpenRouter ein Gruselgemälde erzeugen und zeigt es an. Der Rahmen läuft **ohne Tower, ohne Bot und ohne Heimnetz**, nur mit Internet (#1454, #1455).

Architektonisch ist das der erste Ausschnitt der Geräteklasse **Raumdisplay** (#1444, #1445): ein Geräteprofil „Rahmen“ und ein Inhaltsmodus „Portrait“. Weitere Modi wie Rezepte folgen später.

### Nicht-Ziele (ausdrücklich nicht in Phase 111)

- Mehrgeräte-Registry, Bot oder Matrix steuern den Rahmen (#1459 P1 a–g): eigene Phase nach Silvester (#1461 Punkt 2)
- Bildgenerierung über den Bot (Variante B): Ziel der Geräteklasse, nicht für Silvester (#1461 Punkt 1)
- Hotspot-Rückfall des Pi mit Einrichtungsseite (#1454 b): nach Silvester (#1467 Punkt 3)
- Frei kombinierte Prompt-Bausteine (#1453): spätere Erweiterung (#1467 Punkt 1)
- Galerie früherer Gemälde im Rahmen (D3): wird nicht gebaut, auch nicht als Schalter
- Stufe 2 aus #1457 (Bewegungspfade, Tiefenmasken, neue Sprites) und die Sprite-Erweiterung (#1455)
- Änderungen am Stamm-Pfad: Pepper's-Ghost-Renderer, additiver Crossfade, schwarzer Hintergrund (#1460 K4)
- AttentionProvider im `rpi5_avatar`-Renderloop per DI injizierbar machen. **Korrektur cd zu #1460 K6:** Das braucht nur der Stamm, der Rahmen nutzt `rpi5_avatar` nicht. Es gehört in die spätere Sensor-Phase des Stamms.
- Doku-Schuld K9 (architecture.md, Roadmap) und der ungenutzte `OpenRouterClient` (Chat, K8)
- ERROR-Regel in `message_handlers` bei `success=False` (#1459, Entscheidung Lera offen)
- mypy für den Bestand in `llm/` (Ae8): Folgepunkt nach Phase 111
- Doku-Drift in `docs/rpi5_setup.md` (`harmony_hub_ip`, I2C „für Stepper-Motor“) und die fehlende Stamm-Kamera nach dokumentiertem Setup (Ae16): nur notiert; M-E0-1 entscheidet über einen eigenen Folgepunkt

## 2. Leitprinzipien

1. **Stufe 0 ist Pflicht, Stufe 1 steht hinter dem Tor.** Stufe 1 beginnt nur, wenn Stufe 0 bis 2026-12-06 abgenommen ist (#1461). Wann Stufe 0 als abgenommen gilt, regelt D5 (§9).
2. **Der Rahmen ist autark.** Er braucht kein Element aus Heimnetz, Tower, Bot oder Tunnel. Fällt das Internet aus, greifen lokale Rückfälle (#1449 Punkt 5).
3. **Der Stamm bleibt unverändert.** Das Profil „Stamm“ ist der Default und verhält sich exakt wie heute. Der Portrait-Modus ist ein eigener Anzeigepfad (K4).
4. **Vorhandenes wiederverwenden:** `RPi5Camera`, `AttentionProvider`, `SecretStore`, `core/http_defaults.USER_AGENT`, für Stufe 1 der headless-Pfad von `LayeredSpriteRenderer`. Kein neuer Renderer. (`SensorManager` wird nicht wiederverwendet, siehe Ae11 in §4.2.)
5. **Austauschbare Bildgenerierung.** Eine ABC plus OpenRouter-Implementierung. Der Wechsel zu Variante B ändert nur das Wiring (#1461).
6. **Datenschutz per Konstruktion.** Gästefotos werden nie auf einen Datenträger geschrieben und nie geloggt. Sie werden bei **jedem** Ausgang verworfen (#1467 Punkt 2).
7. **Testbare Logik.** Die Zustandsmaschine ist reine Logik mit injizierter Uhr und hat keine Hardware-Abhängigkeit. Die Szene wählt der Code, nicht das Modell (#1453).
8. **Konventionen:** eine Klasse pro Datei (snake_case), Constructor-DI, Kommunikation über ABCs.

## 3. Ausgangslage im Code (verifiziert in E0, #1473, main @ 5b2cce0)

| Bereich | Befund | Quelle |
|---|---|---|
| Geräteprofil | `start_rpi5.py` startet immer das Avatar-Display (Thread) und blockiert mit uvicorn den Main-Thread. `hostname` und Harmony (`hub_ip`) sind fest verdrahtet. Kamera, Drehteller, Harmony und Alexa werden optional versucht. Es gibt kein Profil. `--rotation` erlaubt nur 0/180. `--benchmark-crossfade` zweigt bereits direkt nach dem Logging-Setup ab (Muster für das Profil) | #1459 P1, #1473 |
| Renderer | `LayeredSpriteRenderer`: schwarzer Hintergrund, additiver Crossfade, Ebenen zentriert und Fit-to-Window. `ALLOWED_ROTATIONS=(0,180)` | #1459 P2, #1473 |
| Headless | `render_to_file` ist headless und ruft seit #1463 kein `pygame.init()` mehr auf; `PYGAME_HIDE_SUPPORT_PROMPT` ist gesetzt. Ausgabe 512×1024 auf Schwarz, opak (kein Alpha) | #1459 P3, #1463, #1473 |
| Sensoren | `SensorManager`-ABC in `robot/interfaces.py` (`get_battery`, `get_all`), einzige Implementierung `SimulatedSensors`. `AttentionProvider`-ABC in `avatar/attention.py` mit `current() -> AttentionState {UNKNOWN, AWAY, PRESENT, FOCUSED}`. Kein I2C-Treiber, keine smbus-Abhängigkeit | #1459 P4, #1473 |
| Kamera | `robot/camera_controller.py`: `CameraController`-ABC und `RPi5Camera` (picamera2, Pillow), Still RGB888 1920×1080, Lazy-Init. `capture_jpeg` arbeitet nur im RAM. Keine Rotation, kein Flip, keine Autofokus-Steuerung. `is_available()` liefert bei jedem Fehler still `False` | #1459 P5, #1473 |
| Bildgenerierung | Es gibt keinen Client. `LLMClient` ist nur für Text. `llm/openrouter_client.py` (Chat) wird in `src/` nicht genutzt, hat aber Tests | #1459 P6, #1473 |
| Secrets | `core/secret_store.py`, Fernet unter `~/.elder-berry/secrets.enc`. Masterkey im OS-Keyring nur, wenn der **laufende Prozess** ein Backend erreicht, sonst `~/.elder-berry/secret.key` (chmod 600). Ein Prozess im Keyring-Pfad migriert eine vorhandene `secret.key` in den Keyring und löscht die Datei. Eine CLI zum Setzen gibt es nicht | #1459 P6, #1473 F3 |
| Tower | Die RPi-Seite hat keine funktionale Tower-Abhängigkeit. Die Importe von `core/` und `llm/` laden aber `Assistant`, `LLMRouter` und den Anthropic-SDK mit (ca. 1,2 s im Devcontainer, Pi nicht gemessen) | #1459 P7, #1473 F7 |
| Abhängigkeiten | Laut `docs/rpi5_setup.md` landen auf dem RPi **beide** Pakete, pygame und pygame-ce, mit gleichem Importnamen. Das venv wird ohne `--system-site-packages` angelegt; picamera2 und Pillow sind danach nicht im venv | #1463, #1464, #1473 F8 |
| Autostart | Im Repo liegen nur Units für Bot und Tower (`server/*.service`). Für den RPi gibt es nur eine Inline-Vorlage in `docs/rpi5_setup.md` | #1473 F4 |
| CI | CI installiert weder `[avatar]` noch `[server]`, echte pygame-Tests werden übersprungen. Pillow ist im Test-Job ebenfalls nicht installiert. `llm/` ist nicht im mypy-Umfang | #1463, #1473 |

## 4. Architektur

### 4.1 Geräteprofil „Rahmen“ (K5, Ae9)

- `start_rpi5.py --profile {stamm,frame}`, Default `stamm`. Für `stamm` ändert sich nichts, auch nicht in der Startreihenfolge.
- Einhängung als Früh-Ausstieg direkt nach dem Logging-Setup (Muster `--benchmark-crossfade`): `if args.profile == "frame": sys.exit(run_frame(args))`. `run_frame` wird lazy aus `room_display/frame_profile.py` importiert. Der Stamm-Code danach bleibt textgleich. Subparser werden nicht verwendet, weil sie den bestehenden Aufruf ohne Subkommando brechen würden.
- Das Profil `frame` verdrahtet in diesem **eigenen** Modul, damit der Stamm-Pfad nicht verzweigt wird:
  - kein Avatar-Display, kein Harmony, kein Drehteller
  - echte Sensoren (APDS, BME minimal, siehe D1), Kamera und `RoomDisplayApp` mit `PortraitMode`
  - **kein RobotServer (Port 8000).** In Phase 111 gibt es keinen Konsumenten (K1). Im fremden WLAN verkleinert das die Angriffsfläche. Diagnose läuft über SSH und journald.
  - kein `ELDER_BERRY_ROBOT_TOKEN`, kein Tunnel
- Das Profil `frame` ignoriert `--width`, `--height` und `--rotation` des Stamms. Anzeige-Parameter wie Auflösung und Rotation sowie die Portrait-Parameter kommen aus `frame_config.yaml` mit eigenen CLI-Overrides. Default unter `room_display/frame_config.yaml`, User-Override unter `~/.elder-berry/frame_config.yaml` (Muster `avatar_config_loader`, Ae13).
- `tests/test_start_rpi5_token.py` bleibt grün. Der Regressionstest „Stamm-Wiring unverändert“ wird neu geschrieben (Konstruktoraufrufe patchen und prüfen).
- Autostart: eigene Unit `server/elder-berry-frame.service` mit Platzhalter-Header wie `server/*.service`, `Restart=always`, ohne `ELDER_BERRY_ROBOT_TOKEN`, ohne `DISPLAY` (Ae12). Die Inline-Vorlage aus `docs/rpi5_setup.md` wird nicht kopiert.

### 4.2 Neue und geänderte Klassen

Paket `src/elder_berry/room_display/` für die Geräteklasse. Die Orte für Treiber und Clients folgen bestehenden Paketen (bestätigt in E0, #1473 Teil 3). `room_display/__init__.py` und `room_display/portrait/__init__.py` importieren nichts Schweres.

| Datei | Klasse | Zweck |
|---|---|---|
| `room_display/content_mode.py` | `ContentMode` (ABC) | `on_enter()`, `update(now)`, `render(display)`, `on_exit()`. Bewusst klein, damit ein Rezept-Modus später andocken kann |
| `room_display/room_display_app.py` | `RoomDisplayApp` | pygame-ce/kmsdrm-Loop, hostet genau einen `ContentMode`, ignoriert alle Eingabe-Events (Touch, R12), blendet den Cursor aus, beendet sich bei SIGTERM sauber |
| `room_display/oriented_display.py` | `OrientedDisplay` | Logisch 1280×720 quer, physisch je nach M3 (§4.3). Standbilder werden **beim Laden** gedreht, nicht pro Frame |
| `room_display/frame_profile.py` | `run_frame(args)` | Wiring des Profils `frame` (§4.1) |
| `room_display/portrait/portrait_state_machine.py` | `PortraitStateMachine` | Reine Logik (§4.4), Uhr injiziert |
| `room_display/portrait/portrait_mode.py` | `PortraitMode` (`ContentMode`) | Verbindet Zustandsmaschine, Sensor, Kamera, Generator und Anzeige. Die Generierung läuft in einem Worker-Thread und meldet ihr Ergebnis über eine Queue. Hält die Sperre nach `CREDIT_EXHAUSTED` bis zum Neustart |
| `room_display/portrait/scene_catalog.py` + `scenes.yaml` | `SceneCatalog` | Lädt die Szenen, setzt den Prompt aus Szene und festem Kern zusammen, Auswahl per Shuffle-Bag ohne Wiederholung (§4.5) |
| `room_display/portrait/painting_store.py` | `PaintingStore` | Legt Gemälde persistent ab, schreibt atomar und prüft den freien Speicher |
| `room_display/portrait/photo_pipeline.py` | `PhotoPipeline` | Aufnahme in den RAM über ein schmales Protocol, Rotation, Verkleinerung auf 1024 px, Gesichtsprüfung. Kein Schreiben auf einen Datenträger |
| `room_display/portrait/face_detector.py` | `FaceDetector` (ABC) plus `NullFaceDetector` | Gesichtsprüfung (#1449 Punkt 3). Die Implementierung hängt an D2 |
| `llm/image_generator.py` | `ImageGenerator` (ABC), `ImageRequest`, `ImageResult` | `generate(request) -> ImageResult`, Status `OK / REFUSED / ERROR / TIMEOUT / CREDIT_EXHAUSTED` (Ae1), Dauer, Kosten (`usage.cost`, falls geliefert). Der Generator ist zustandslos |
| `llm/openrouter_image_generator.py` | `OpenRouterImageGenerator` | `POST /api/v1/images` mit den Feldern aus Ae3 (§4.6), `provider`-Optionen per Konfiguration (Ae4). httpx-Client, Schlüssel und Timeout (Default 90 s) per DI, `USER_AGENT`. Kein Streaming (E7) |
| `robot/apds9960_proximity.py` | `Apds9960Proximity` | Minimaler smbus2-Treiber: Konfiguration B aus #1440 (PPULSE 0xFF, CONTROL 0x0D, ENABLE 0x07), PDATA lesen, optional Offset-Register |
| `avatar/proximity_attention_provider.py` | `ProximityAttentionProvider` (`AttentionProvider`) | PDATA → `AWAY / PRESENT / FOCUSED` mit Schwellen, Hysterese und Entprellung; erkennt Sättigung als Sensorfehler |
| `robot/bme280_reader.py` | `Bme280Reader` | D1: nur Log und WARNING-Schwelle für die Gehäuseluft, Adresse **0x76** (#1439). **Kein** `SensorManager`: `get_battery()` passt nicht, `BatteryStatus` kennt „keine Batterie“ nicht (Ae11) |
| `robot/camera_controller.py` | `RPi5Camera` (erweitert) | Aufnahme in den Speicher, Rotation/Flip per Konfiguration, Autofokus-Zyklus, Kamera bleibt warm. Nur `RPi5Camera` wird erweitert, die ABC `CameraController` bleibt unverändert (Ae10) |
| `scripts/portrait_scene_test.py` | CLI | Szenen-Tests mit **demselben** Generator und Katalog wie im Betrieb (§4.6). Ersetzt das Wegwerf-Skript |
| `scripts/set_frame_api_key.py` | CLI | Setzt `openrouter_frame_api_key` im SecretStore des Rahmen-Pi (§4.6, Ae6, E6) |
| `server/elder-berry-frame.service` | systemd-Unit | §4.1, Ae12 |

Geänderte Dateien (vorläufig): `scripts/start_rpi5.py` (Profil), `pyproject.toml` (Extra `[frame]`, mypy-Overrides), `docs/` (Abschnitt Rahmen-Setup), CI (Job mit pygame-ce, mypy-Umfang: `room_display/` und **nur** die zwei neuen `llm/`-Dateien, Ae8).

### 4.3 Anzeige und Querbetrieb – Verzweigung nach M3/M4

Das Panel ist nativ 720×1280 hochkant. Die Gemälde sind 16:9 quer. Der Renderer kann nur 0 und 180 Grad (#1459 P2). Die Maße aus #1443 passen zum offiziellen Raspberry Pi Touch Display 2; das ist nicht bestätigt, für M3 aber relevant.

`OrientedDisplay` kapselt die Ausrichtung **in beiden Zweigen**. Der Unterschied liegt nur in der Konfiguration und im Leistungsrisiko, nicht in der Code-Struktur:

- **Zweig M3-A** (KMS liefert ein Querbild 1280×720): `OrientedDisplay` mit Rotation 0, Bilder werden 1:1 dargestellt.
- **Zweig M3-B** (KMS liefert kein Querbild): `OrientedDisplay` mit Rotation 90 oder 270. Jedes Standbild wird **einmal beim Laden** auf 720×1280 gedreht. Überblendungen zwischen zwei schon gedrehten Bildern kosten dann pro Frame nicht mehr als im Zweig A. Pro Frame gedreht wird nur dynamisch zusammengesetzter Inhalt (Stufe 1).

**Erwartung cd (nicht verifiziert):** Die vc4-Hardware des RPi dreht vermutlich nur 0/180, und SDL/kmsdrm wertet eine Rotation aus `cmdline.txt` vermutlich nicht aus. M3-B ist deshalb der Planungs-Default, M3-A ein möglicher Bonus. Der Plan hängt nicht am Ausgang von M3.

**M4 wird aufgeteilt:**
- M4 wie in #1459 (`--benchmark-crossfade`) misst den additiven Avatar-Crossfade. Das ist **nur für Stufe 1** relevant (Saleria-Ebene).
- **M4′ (neu)** misst die Bildrate der Portrait-Überblendungen auf dem Rahmen-Pi nach E2 (§7). Sie entscheidet über die Übergänge in Stufe 0.

### 4.4 Ablauf: Zustandsmaschine (Stufe 0)

```
           Zufallstimer              FOCUSED-Flanke (entprellt)
  IDLE ──────────────▶ IDLE_VARIANT      │
   ▲ ◀── nach t_var ──┘                  ▼
   │                                   CAPTURE ── kein Gesicht ──▶ FALLBACK
   │                                     │                           │
   │                                     ▼                           │
   │                                 GENERATING ── Fehler/Timeout ──▶┤
   │                                     │  /Ablehnung/offline/Kredit│
   │                                     ▼                           │
   │                                   REVEAL ─────────────────────▶ │
   │                                                                 ▼
   └──────────── AWAY ≥ t_rearm und t_min_cycle abgelaufen ───── COOLDOWN
```

| Zustand | Anzeige | Verhalten |
|---|---|---|
| `IDLE` | Standardgemälde (Landschaft) | Auslösung scharf. Zufallstimer (Vorschlag 45–120 s) für den Bildwechsel aus #1448. Frühere Gemälde erscheinen nicht (D3) |
| `IDLE_VARIANT` | Variante des Gemäldes oder ein dezentes Spukbild, wenige Sekunden | Auslösung bleibt scharf |
| `CAPTURE` | **Heller Frame als Blitz** (#1449 Punkt 2), ca. 300–500 ms | Autofokus-Zyklus, 2–3 Aufnahmen gestaffelt über ca. 1 s, beste Aufnahme mit Gesicht wählen (#1449 Punkt 3). Ob der AF-Zyklus geht, klärt M-E0-3 |
| `GENERATING` | Überbrückung in zwei Phasen: (1) 0–15 s eine kurze Sequenz, die typische ca. 12 s abdeckt; (2) ab 15 s eine langsamere Schleife bis zum Timeout (#1451 Punkt 1) | Worker-Thread, genau eine Generierung gleichzeitig. Harter Timeout **90 s** (#1451), als Wanduhr-Grenze im Worker; der httpx-Timeout allein ist keine Gesamtgrenze |
| `REVEAL` | Gemälde einblenden, Haltezeit (Vorschlag mindestens 30 s, länger bei weiter `PRESENT`, höchstens 90 s) | Gemälde über `PaintingStore` speichern |
| `FALLBACK` | Vorbereitetes Schockbild aus dem lokalen Satz | Ohne API-Aufruf, wenn kein Gesicht gefunden wurde oder die Kredit-Sperre aktiv ist |
| `COOLDOWN` | Übergang zurück zu `IDLE` | Wieder scharf erst nach `AWAY` ≥ `t_rearm` (Vorschlag 3 s) **und** abgelaufener Mindestzykluszeit (#1448: keine Wiederholung, solange jemand davor steht) |

**Ergebniskategorien der Generierung (Ae1):**

| Antwort | Kategorie |
|---|---|
| 200 mit `data[0].b64_json` | `OK` |
| 200 ohne Bild oder mit `error`-Feld im Body | `ERROR` |
| 400 | `ERROR` (**nicht** `REFUSED`: ein falscher Parameter darf nicht unbemerkt als Schockbild enden) |
| 402 | `CREDIT_EXHAUSTED` |
| 403 mit `error.metadata.reasons` | `REFUSED` |
| 403 ohne `reasons`, 401, 404, 413, 429, 5xx, 524, 529 | `ERROR` |
| Client-Timeout | `TIMEOUT` |

`CREDIT_EXHAUSTED`: einmal WARNING; alle weiteren Auslösungen gehen bis zum Neustart ohne API-Aufruf in `FALLBACK`. Die Sperre hält `PortraitMode`, nicht der Generator. Bei `ERROR` und `REFUSED` werden HTTP-Status, `error.code` und die `metadata` ohne `flagged_input` geloggt. Alle Nicht-`OK`-Kategorien führen in `FALLBACK`.

**Schutz gegen Dauerauslösung und Kosten:**
- Die Hysterese der Schwellen (`FOCUSED` ein/aus) kommt aus der Kalibrierung M5 und steht in der Konfiguration.
- Bleibt PDATA länger als 60 s gesättigt oder `FOCUSED`, gilt das als **Sensorfehler**: Auslösung aus, WARNING ins Log, der Rahmen läuft als reines Gemälde weiter. Hintergrund ist das Übersprechen mit Grundwert 128 bei Konfiguration B (#1440). Nach dem Einbau kann der Grundwert anders liegen.
- **Lokale Obergrenze** für Generierungen, Vorschlag 40 pro Stunde. Ist sie erreicht, folgt der Rückfall. Das ergänzt das Kreditlimit des Schlüssels und ersetzt es nicht.
- Abrechnung (Ae5): Laut OpenRouter-Guide werden 502 und abgebrochene Streams nicht berechnet. Ob ein Request ohne Streaming nach einem Client-Timeout berechnet wird, ist nicht belegt; das Kreditlimit begrenzt den Schaden.

**Offline:** Es gibt keine eigene Netzprüfung. DNS- und Verbindungsfehler schlagen schnell fehl (Verbindungsaufbau höchstens 10 s, kein Retry) und führen direkt in `FALLBACK`.

### 4.5 Szenen (#1467 Punkt 1)

- Datei `room_display/portrait/scenes.yaml` im Repo (Ae13). Die Prompts sind nicht geheim.
- Der **feste Kern** wird vom Code immer angehängt und nicht in jeder Szene wiederholt: Gemäldestil, alle Gesichter erkennbar, Horror nur durch Atmosphäre, kein Blut, keine Verletzungen, keine Gewalt, nicht fotorealistisch, 16:9. Formuliert ist er für eine **beliebige Personenzahl** („everyone in this photo“, vgl. Amulti #1452). Er steht im Code (`scene_catalog.CORE_PROMPT`), nicht in der YAML, damit eine Bearbeitung der Szenen ihn nicht entfernen kann.
- Ein Test sichert ab, dass jeder zusammengesetzte Prompt die Kernbedingungen enthält.
- Auswahl: Shuffle-Bag ohne Wiederholung, bis jede Szene einmal dran war. Beim Neumischen ist die erste Szene nie die zuletzt gezeigte. Nach einem Neustart darf sich eine Szene wiederholen.
- Modell, Qualität und `provider`-Optionen stehen in der Sektion `generation` von `scenes.yaml`: `openai/gpt-image-2.6-flare`, Qualität `low` als Kandidat (#1451 Punkt 4), `provider: {data_collection: deny, zdr: true}` (Ae4). Sie liegen dort und nicht in `frame_config.yaml`, damit Szenen-Test-CLI und Betrieb dieselbe Quelle lesen und das Ergebnis des ZDR-Checks an genau einer Stelle steht (Entscheidung cc in E1). Die Endbewertung der Qualität erfolgt am 7-Zoll-Display. Die Ausgabe ist 1536×864 und wird auf 1280×720 skaliert.
- Entwürfe für 6 Szenen stehen in **Anhang A** und in `scenes.yaml`. Getestet ist davon nur S1 (A+/Amulti).

### 4.6 Bildgenerierung und Schlüssel (#1461 Punkt 1)

- `OpenRouterImageGenerator` liest den Schlüssel nicht selbst. Er bekommt ihn per DI aus dem `SecretStore` des Rahmen-Pi.
- Schlüsselname: `openrouter_frame_api_key`, bewusst verschieden vom `openrouter_api_key` des Bots, damit eine Verwechslung mit dem Produktivschlüssel auffällt.
- Es ist ein eigener OpenRouter-Schlüssel mit Kreditlimit (Vorschlag: einige USD; der Testpreis lag bei 0,02–0,033 USD pro Bild, #1451). Nach der Party wird er widerrufen (Checkliste §4.8).
- **SecretStore (Ae6):** Rahmen-Wiring und `scripts/set_frame_api_key.py` bauen den SecretStore mit `use_keyring=False`. Der Masterkey liegt damit deterministisch in `~/.elder-berry/secret.key` neben `secrets.enc`. Das schützt vor Klartext im Repo, in Logs und in Backups, **nicht** vor jemandem mit der SD-Karte. Der eigentliche Schutz sind Kreditlimit und Widerruf.
  - Hintergrund (#1473 F3): Im Auto-Modus entscheidet jeder Prozess selbst, ob er den Keyring nutzt. Eine SSH-Session mit Keyring und ein Dienst ohne Session-Bus würden sich gegenseitig den Schlüssel unbrauchbar machen.
  - Umgekehrt würde `use_keyring=False` auf einem Rechner, dessen `secrets.enc` mit einem Keyring-Key verschlüsselt ist, still einen neuen Dateischlüssel erzeugen und den Bestand unlesbar machen. Deshalb: (a) Die Szenen-Test-CLI nutzt **keinen** SecretStore. (b) `set_frame_api_key.py` bricht ab, wenn `secrets.enc` existiert, `secret.key` aber fehlt. (c) Ein Test deckt (b) ab.
- Einspielen des Schlüssels: `scripts/set_frame_api_key.py` (E6, Vorlage `scripts/set_dashboard_password.py`). Der Schlüssel wird per `getpass` verdeckt abgefragt und landet nicht in der Shell-History.
- **Request (Ae3):** `POST https://openrouter.ai/api/v1/images` mit `model`, `prompt`, `input_references` (Data-URL), `aspect_ratio` „16:9“, `quality`, `n=1` und `output_format` „png“ (explizit). **Nicht** gesendet werden `size`, `resolution`, `seed` (für flare nicht in `supported_parameters`). Das Feld `user` wird nie mit Gästedaten gefüllt. `provider` nur, wenn konfiguriert (Ae4).
- **Response** laut Doku (#1473 F10): `{"created", "data": [{"b64_json", "media_type"?}], "usage"?: {"cost"?}}`, nur `b64_json`, kein URL-Feld. Fehlerbody `{"error": {"code", "message", "metadata"?}}`; Moderation als 403 mit `metadata.reasons`. Wie eine Ablehnung durch das Safety-System von OpenAI selbst ankommt, ist nicht dokumentiert; die Szenen-Tests zeigen es.
- **Datenschutz beim Anbieter (Ae4):** Bevorzugt wird `provider.data_collection="deny"` mit `provider.zdr=true` gesendet. Die Szenen-Test-CLI prüft einmal (`--check-zdr`), ob flare damit einen Endpoint findet. Funktioniert es, bleiben die Werte in der Konfiguration. Schlägt es fehl, entscheidet Lera D8 (§10).
- **Logging (Ae2):** Request- und Response-Bodies werden nie geloggt, auch nicht im Fehlerfall: Der Request enthält das Gästefoto als Data-URL, die Antwort das Bild als Base64. Nie Schlüssel, Bild-Bytes oder Base64. Den httpx-Logger auf WARNING setzen. Geloggt werden Dauer, HTTP-Status, Ergebniskategorie, `error.code`, Szene und Kosten.
- **Szenen-Test-CLI** (`scripts/portrait_scene_test.py`, Ae6a):
  - Der Schlüssel wird bei jedem Lauf per `getpass` abgefragt, kein SecretStore, nichts persistiert.
  - Eingabe: Bilddatei(en). EXIF-Drehung und Verkleinerung auf 1024 px im RAM (Pillow).
  - Parameter: Szene oder „alle“, Anzahl der Läufe, Qualität, optional `--no-zdr`.
  - Ausgabe: CSV (Zeit, Eingabe, Lauf, Szene, Status, HTTP-Status, `error.code`, Dauer, Kosten, Bilddatei; **kein** `flagged_input`) und die Ergebnisbilder in einem Temp-Verzeichnis, dessen Pfad am Ende ausgegeben wird.
  - Modus `--check-zdr`: ein einzelner Lauf mit `data_collection=deny` und `zdr=true`. Ausgabe „ZDR verfuegbar“ oder der Fehler. Grundlage für D8.
  - Damit testet Lera die Szenen (1 und 2 Personen, je 2–3 Läufe, #1467) mit dem Prompt-Aufbau des Betriebs. **Voraussetzung:** Das Wegwerf-Skript aus `C:\Dev\Elder-Berry\scripts` ist entfernt (#1466); vor dem ersten Commit `git status` prüfen.
- Streaming (#1451 Punkt 2) ist **optional** (E7) und kommt erst, wenn der Kern läuft. Die ABC bekommt dafür eine optionale Methode oder Unterklasse, damit der Kern nicht davon abhängt. Zweiter Nutzen laut Doku: Ein abgebrochener Stream wird nicht berechnet (Ae5).

### 4.7 Speicher- und Löschregel (#1467 Punkt 2)

- **Gästefotos:** Sie existieren nur im RAM, als Rohaufnahme und als verkleinerte JPEG-Kopie. Es gibt **keine** Zwischendatei, auch nicht in `/tmp`. Nach jedem Ausgang (Erfolg, Fehler, Timeout, Ablehnung, Kredit-Sperre, kein Gesicht, Abbruch durch Shutdown) werden alle Referenzen in einem `finally` verworfen. Das ist strenger als „nach der Generierung löschen“, weil es von vornherein nichts zu löschen gibt.
- **Gemälde:** persistent unter `~/.elder-berry/portrait/paintings/`, nicht in einem Temp-Verzeichnis. Dateiname `YYYYMMDD-HHMMSS_<szene>.png`, atomar geschrieben (temporäre Datei, dann umbenennen). Bei weniger als z. B. 200 MB freiem Speicher wird nicht gespeichert, die Anzeige läuft weiter, und es gibt eine WARNING.
- Am Rahmen gibt es **keinen** QR-Code und keinen Link.
- **Galerie (D3):** nein. Während der Party zeigt der Rahmen nur das jeweils eigene Ergebnis; frühere Gemälde erscheinen nicht im Leerlauf. Es gibt dafür keinen Konfigurationsschalter.
- **Weitergabe (D4):** Lera kopiert die Gemälde nach der Party per scp und löscht sie danach auf dem Pi. Die Weitergabe erfolgt über **einen** Nextcloud-Freigabelink für alle Gäste mit 30 Tagen Ablauf. Damit sehen alle Gäste alle Gemälde; Lera hat das in Kenntnis davon gewählt, dass Gemälde mehrere Gäste zeigen können (R7). Kein Code, Schritt in der Party-Checkliste (§4.8).
- Was OpenRouter und OpenAI speichern, liegt außerhalb dieser Regel; `data_collection=deny` und `zdr=true` werden bevorzugt (Ae4). Lera liest die Richtlinien vor der Party (#1449).

### 4.8 Abhängigkeiten, Setup, Betrieb

- **pygame-Drift (#1464):** Rahmen-Pis dürfen nur pygame-ce haben. Neues Extra `[frame]` mit `pygame-ce` und `smbus2`; httpx ist Core. Das Extra `[frame]` wird nie mit `[avatar]` kombiniert, analog der Regel für `[server]` aus #1463. Der Stamm-Setup bleibt unverändert, die Drift dort ist ein Folgepunkt aus #1463.
- **Setup Rahmen-Pi (Ae7):**
  - venv mit `--system-site-packages`.
  - picamera2 ausdrücklich per apt (`python3-picamera2`).
  - Kein `python3-pygame` per apt; das venv hat nur pygame-ce.
  - Pillow kommt auf dem Pi aus apt. Ob `[frame]` Pillow zusätzlich deklariert, entscheidet cc in E4 mit Begründung. Pflicht dabei: genau eine Pillow-Quelle im venv nachweisen, und die Pillow-Tests laufen in CI (heute hat der CI-Test-Job kein Pillow).
  - bei D2(a): `python3-opencv` per apt.
- **Setup-Doku Rahmen:** eigener Abschnitt mit Installation, I2C, Kamera, Unit, Schlüssel und WLAN.
- **WLAN-Checkliste (#1467 Punkt 3):** Heim-WLAN, Partyort-WLAN und Handy-Hotspot vorab speichern. Vorher `nmcli general status` prüfen. SSH über den Hotspot vorab testen. Die IP über die Geräteliste des Handys finden. Neue Netze im Notfall per `nmtui` setzen.
- **Party-Checkliste:** Schlüssel eingespielt und Limit gesetzt; Modellverfügbarkeit ohne Schlüssel per `GET https://openrouter.ai/api/v1/images/models` (grep `gpt-image-2.6-flare`) eine Woche vorher und am Partytag prüfen (Ae14); Szenen getestet; Rückfallbilder vorhanden; Stromversorgung ohne Unterspannung; nach der Party Schlüssel widerrufen, Gemälde per scp kopieren, auf dem Pi löschen und per Nextcloud-Link mit 30 Tagen Ablauf freigeben (D4).
- Temperatur: CPU-Temperatur aus `/sys/class/thermal` und `vcgencmd get_throttled` alle 5 min ins Log. Dazu die BME-Gehäuseluft mit einer WARNING-Schwelle (D1, streichbar).

### 4.9 Stufe 1 hinter dem Tor (nur Umriss)

Stufe 1 beginnt nur, wenn das Tor am 2026-12-06 bestanden ist (#1461). Inhalt aus #1457 und #1460 K4:
- `LayeredSpriteRenderer` bekommt eine headless-Ausgabe als RGBA-Fläche mit **transparentem** Hintergrund (neben `render_to_file`). Der Stamm-Pfad bleibt unberührt.
- `GhostOverlay` im Portrait-Modus mit Position, Skalierung und Deckkraft. Dazu ein Gemäldefilter zur Laufzeit (Farbangleich, Leinwandtextur). Ein- und Ausblenden an 2–3 festen Orten je Standardgemälde.
- Saleria-Auftritte ersetzen oder ergänzen `IDLE_VARIANT` und überbrücken `GENERATING`.
- Grundlage für die Aufwandsschätzung sind M4 und M4′. Stufe 1 bekommt vor dem Start einen eigenen Spezifikationseintrag.

## 5. Etappen

Die Reihenfolge folgt dem kritischen Pfad. Die Szenen brauchen die längste Vorlaufzeit für Tests und hängen nicht an der Hardware, deshalb kommen sie zuerst.

| Etappe | Inhalt | Hardware nötig | Vorschlag Termin |
|---|---|---|---|
| **E0 Preflight** (cc, nur lesen) | erledigt: #1473 | nein | 11-17 |
| **E1 Bildgenerierung + Szenen** | Konzeptdatei, `ImageGenerator`, `OpenRouterImageGenerator`, `SceneCatalog`, `scenes.yaml`, Szenen-Test-CLI mit `--check-zdr`, Tests, mypy-Umfang | nein | 11-22 |
| **E2 Anzeige + Profil** | `--profile frame`, `frame_profile.py`, `frame_config.yaml`, `RoomDisplayApp`, `OrientedDisplay`, `ContentMode`, Überblendungen, FPS-Log, CI-Job pygame-ce; danach M3/M4′ | Rahmen-Pi + Display | 11-27 |
| **E3 Sensorik** | `Apds9960Proximity`, `ProximityAttentionProvider`; als letzte Aufgabe `Bme280Reader` (D1, streichbar); danach M5 | APDS am Pi | 11-29 |
| **E4 Kamera** | Erweiterung `RPi5Camera`, `PhotoPipeline`, `FaceDetector` (D2, Messwert mit Pi-Modell); vorher M-E0-1 und M-E0-3; danach M6 | Kamera am Pi | 11-29 |
| **E5 Portrait-Modus** | Zustandsmaschine, `PortraitMode` inkl. Kredit-Sperre, `PaintingStore`, Rückfälle, Obergrenze, Löschregel, Wiring; vorher M-E0-4 | alles | 12-03 |
| **E6 Setup + Betrieb** | Extra `[frame]`, Setup-Doku, `server/elder-berry-frame.service`, `set_frame_api_key.py`, Checklisten; vorher M-E0-2 auf dem Rahmen-Pi | Pi | 12-04 |
| **Abnahme Stufe 0** | A1–A12 (§9), Tor nach D5 | Test-Aufbau | **bis 12-06** |
| E7 (Kann) | Streaming als Überbrückung | – | nach Tor |
| E8 Stufe 1 | §4.9 | – | nur bei bestandenem Tor |

**Einordnung cd:** Die Termine sind ambitioniert. Bis zum 12-06 bleiben 20 Tage, der Rahmen ist noch nicht gekauft, und das Pi-Modell der Rahmen-Hardware ist offen (#1445). E2–E4 brauchen einen Test-Aufbau (Pi, Display, Kamera, APDS am Steckbrett), aber **nicht** den fertigen Rahmen. Wie die Abnahme den Rahmen einbezieht, regelt D5.

**PR-Schnitt (D6):** Ein Branch `phase-111-raumdisplay-portrait` mit drei Teil-PRs: (1) E1, (2) E2+E3+E4, (3) E5+E6. Jeder PR hat den Commit-Footer `Journal: elder-berry#<Auftrags-id>`, Review durch Codex, Merge durch Lera. Die Abweichung von der Präzedenz „ein PR pro Phase“ ist bewusst entschieden.

### E0 – Preflight-Fragen (erledigt, #1473)

F1 Änderungen seit b4a4012 · F2 Argumente von `start_rpi5.py` und Einhängen des Profils · F3 SecretStore auf einem headless-Pi und CLI · F4 systemd-Unit · F5 picamera2 (Speicher, Autofokus, Rotation; der libcamera-`Transform` kann nur spiegeln und 180 Grad, 90 Grad per Pillow) · F6 Orte für Provider-Clients und YAMLs · F7 Importierbarkeit ohne Server-Extras · F8 venv und Pillow-Quelle · F9 OpenCV · F10 Schema der OpenRouter Image API. Die Antworten stehen in #1473 und sind in §3, §4 und §7 eingearbeitet (#1474).

## 6. Tests

**Unit-Tests (CI):**
- `PortraitStateMachine` mit Fake-Uhr: alle Übergänge; Timeout bei 90 s; keine erneute Auslösung, solange `FOCUSED`/`PRESENT`; Wiederscharfschaltung nur nach `AWAY` ≥ `t_rearm`; Sensorfehler nach 60 s Sättigung; Obergrenze pro Stunde; kein Gesicht führt ohne Generator-Aufruf in `FALLBACK`; nach `CREDIT_EXHAUSTED` führt die nächste Auslösung ohne Generator-Aufruf in `FALLBACK`.
- `SceneCatalog`: keine Wiederholung innerhalb eines Durchlaufs; kein Doppel am Übergang beim Neumischen; **jeder** Prompt enthält die Kernbedingungen; ungültige oder leere YAML führt zu einem klaren Fehler beim Laden.
- `OpenRouterImageGenerator` mit `httpx.MockTransport`: 200 mit Bild → `OK` inkl. Kosten; 200 ohne Bild → `ERROR`; 200 mit `error`-Feld → `ERROR`; 400 → `ERROR`; 402 → `CREDIT_EXHAUSTED`; 403 mit `reasons` → `REFUSED`; 403 ohne `reasons` → `ERROR`; 429/502/529 → `ERROR`; Timeout → `TIMEOUT`; Verbindungsfehler → `ERROR` ohne Wartezeit; Request-Body genau nach Ae3, `provider` nur wenn konfiguriert; `USER_AGENT` gesetzt; **Schlüssel, „sk-or“, „base64,“ und „data:image“ tauchen in keinem Log-Record auf** (caplog, Ae2).
- Szenen-Test-CLI: Argumentparser und CSV-Schreiber mit gemocktem Generator; es wird kein Schlüssel in eine Datei geschrieben.
- `set_frame_api_key.py`: Abbruch, wenn `secrets.enc` existiert, `secret.key` aber fehlt (Ae6c).
- `PhotoPipeline`/`PortraitMode`: Für jeden Ausgang wird keine Datei geschrieben (tmp_path und überwachtes `open`); die Fotopuffer sind nach dem Ausgang freigegeben (weakref).
- `PaintingStore`: atomares Schreiben, Verhalten bei vollem Speicher, Dateiname.
- `ProximityAttentionProvider` mit Fake-Treiber: Schwellen, Hysterese, Entprellung, Sättigung.
- `Apds9960Proximity` mit gemocktem smbus2: richtige Registerwerte (Konfiguration B).
- Kamera-Rotation und Verkleinerung mit Pillow (keine Hardware). Die Pillow-Tests müssen in CI laufen (Ae7).
- Profil `stamm`: Das Wiring entspricht dem Stand vor Phase 111 (neuer Regressionstest, Konstruktoraufrufe gepatcht); `tests/test_start_rpi5_token.py` bleibt grün (Ae9).

**pygame-Tests:** `OrientedDisplay` (Dreh-Mathematik, Bild beim Laden gedreht) und `RoomDisplayApp` (ignoriert Eingabe-Events) laufen mit `pytest.importorskip("pygame")` und `SDL_VIDEODRIVER=dummy`. Damit sie nicht nur lokal laufen, bekommt **CI einen Job mit pygame-ce** (Folgepunkt aus #1463, hier fällig). Der mypy-Umfang in CI wird um `room_display/` und die zwei neuen Dateien `llm/image_generator.py` und `llm/openrouter_image_generator.py` erweitert, **nicht** um ganz `llm/` (Ae8).

**Hardware-Tests:** Messungen M3–M9, M-E0-1 bis M-E0-4 und Abnahme durch Lera.

## 7. Messungen für Lera (mit Auswertungsregel)

**M-E0-1 bis M-E0-4 (aus #1473, Ae15).** Befehle und Auswertungsregeln stehen in #1473 Abschnitt 4 und gelten unverändert. Reihenfolge:
- **M-E0-2** (SecretStore-Pfad) vor E6, auf dem **Rahmen**-Pi. Nur `keyring.get_keyring()` abfragen, kein `SecretStore().get/.set`.
- **M-E0-1** (Stamm-venv, picamera2/Pillow-Quelle) vor E4/E6.
- **M-E0-3** (picamera2-Autofokus, OpenCV per apt) vor E4.
- **M-E0-4** (Importzeit und RAM) vor E5. Ein Lazy-`llm/__init__` wäre eine Bestandsänderung und braucht Lera-OK.
- E1 hängt an keiner dieser Messungen.

**M3 – Querbetrieb (präzisiert gegenüber #1459).** Auf dem Rahmen-Pi mit dem Display:
1. `python -c "import pygame; pygame.display.init(); print(pygame.display.get_desktop_sizes())"` unter `SDL_VIDEODRIVER=kmsdrm`, einmal ohne und einmal mit Rotationseintrag. Welcher Eintrag (`cmdline.txt` `video=DSI-1:…,rotate=90` oder Overlay-Parameter) passt, legt cc in E2 nach der Raspberry-Pi-Doku fest.
2. Testbild mit Text „OBEN LINKS“ in der Ecke und einem Kreis in der Mitte.

Auswertung:
- Größe 1280×720 und das Testbild steht richtig, der Kreis ist rund: **M3-A**, Rotation 0.
- Größe 720×1280 oder das Bild steht hochkant: **M3-B**, Software-Rotation 90/270, Richtung nach Testbild. **Der Plan ändert sich nicht.**
- Kreis ist oval: Seitenverhältnis bzw. Modus falsch, vor E2-Abnahme klären.

**M4 – wie #1459**, nur für Stufe 1. Exit 0 heißt, der Avatar-Crossfade hält 30 FPS. Exit 1 heißt, für Stufe 1 MOUTH_ONLY oder eine kleinere Saleria-Ebene einplanen.

**M4′ – Portrait-Überblendung (nach E2).** Die FPS-Logzeile während 10 Überblendungen ablesen.
- ≥ 24 FPS: Übergänge wie geplant.
- 10–24 FPS: Überblendungen verkürzen (≤ 0,5 s) und Stufe 1 als Risiko ans Tor melden.
- < 10 FPS: Stufe 0 mit harten Schnitten; Stufe 1 entfällt, weil das Tor nicht bestanden werden kann.

**M5 – APDS nach dem Einbau** (Passepartout-Bohrung, Konfiguration B). Grundwert ohne Person über 2 min; Wert bei Gesicht in 30/40/50 cm; Gegenprobe mit dunklem Stoff; Vorbeigehen in 1 m.
- Grundwert stabil (± 15) und Gesicht bei 40 cm ≥ Grundwert + 40: Schwellen in die Konfiguration übernehmen (FOCUSED ein bei ca. Grundwert + 30, aus bei + 15).
- Grundwert driftet oder sättigt: Offset-Register nutzen (#1440) oder die Bohrung vergrößern, dann wiederholen.
- Dunkler Stoff bei 40 cm unter Schwelle: Auslöseabstand verkürzen und mit M6 abgleichen.

**M6 – Kameraausschnitt beim Auslöseabstand.** Eine Person und zwei Personen lösen aus. Die verworfenen Fotos werden nicht gespeichert; zur Messung zeigt ein Debug-Schalter der Test-CLI das Bild nur an.
- Gesicht vollständig und nicht am Rand: Montage ok.
- Gesicht angeschnitten: Kameraneigung oder -position ändern bzw. Auslöseabstand anpassen. Danach die Szenen mit Rahmenbildern (angeschnittene Personen, #1468) erneut testen.

**M7 – Ende-zu-Ende im Fremdnetz.** Nur Handy-Hotspot, Tower aus, 10 Auslösungen.
- Alle enden in Gemälde oder Rückfall und das Maximum liegt ≤ 95 s: bestanden.
- Hänger oder Absturz: Log sichern und an cc.

**M8 – Wärme.** 3 h Betrieb im geschlossenen Rahmen oder Rückkasten. `vcgencmd get_throttled` am Ende und die Temperatur-Logzeilen.
- `throttled=0x0` und CPU < 80 °C: bestanden.
- Drosselung: Lüftung bzw. Rückkasten nachbessern (#1443 Punkt 4).

**M9 – Strom.** Unter Last (Display hell, Kamera, Generierung) kommt keine Unterspannungsmeldung (`vcgencmd get_throttled`, Bit 0/16). Sonst ein anderes Netzteil.

## 8. Risiken

| # | Risiko | Gegenmaßnahme |
|---|---|---|
| R1 | Zeit: 20 Tage bis zum Tor, Rahmen nicht gekauft, Pi-Modell offen | Hardware-unabhängige Etappe E1 zuerst; Test-Aufbau statt Rahmen für E2–E4; Tor schützt Stufe 0; D5 |
| R2 | Latenz zweigipflig: 12 von 15 Läufen 10–14 s, 3 von 15 bei 42–45 s, zur Partyzeit eventuell schlechter | Überbrückung in zwei Phasen, Timeout 90 s, Rückfall; optional Streaming (E7) |
| R3 | Ablehnungen auf der Party (Kostüme mit Kunstblut oder Spielzeugwaffen), trotz 0 von 15 im Test | Kategorie `REFUSED` führt zum Schockbild; Szenen-Tests; Kern ohne Gewalt |
| R4 | APDS-Grundwert nach dem Einbau anders, Dauerauslösung frisst Guthaben | M5, Sättigungserkennung, Obergrenze pro Stunde, Kreditlimit, Kredit-Sperre nach 402 |
| R5 | Schlüssel auf einem Gerät im fremden Haus, SecretStore ohne echten Schutz auf dem Pi; Keyring/Datei-Mismatch | eigener Schlüssel, Kreditlimit, Widerruf nach der Party (§4.6); `use_keyring=False` mit Abbruch-Schutz (Ae6); M-E0-2 |
| R6 | Datenschutz beim Anbieter außerhalb eigener Kontrolle | Opt-in durch Annäherung, Gäste informiert (#1449); `data_collection=deny` + `zdr=true` bevorzugt (Ae4), sonst D8; Lera liest die Richtlinien |
| R7 | Ein Gemälde zeigt mehrere Gäste, die Weitergabe betrifft also auch Dritte | D4: ein gemeinsamer Link, bewusst gewählt |
| R8 | Querbetrieb oder Bildrate (M3/M4′) | Drehung beim Laden; Verzweigung in §4.3 und §7 |
| R9 | pygame und pygame-ce gleichzeitig auf dem Rahmen-Pi | Extra `[frame]`, kein `python3-pygame` per apt, Setup-Doku, A11 |
| R10 | Modell `gpt-image-2.6-flare` bis Silvester geändert, verteuert oder entfernt | Modell in `scenes.yaml`; Prüfung per `/api/v1/images/models` eine Woche vorher und am Partytag (Ae14) |
| R11 | Gesichtsprüfung braucht eine schwere Abhängigkeit oder kostet auf dem Pi zu viel Zeit | `FaceDetector`-ABC mit `NullFaceDetector`; D2 mit Schwelle 300 ms |
| R12 | Gäste fassen das Display an | Eingabe-Events werden ignoriert, keine Beenden-Geste |

## 9. Abnahmekriterien Stufe 0

- **A1 Autark:** Tower aus, Rahmen nur am Handy-Hotspot. Nach dem Einschalten zeigt er innerhalb von 90 s das Standardgemälde, ohne Eingriff. Im Log gibt es keine Verbindung zu Bot, Tunnel oder Tower, und es läuft kein Port 8000 (`ss -tlnp`).
- **A2 Auslösung:** Annäherung auf den konfigurierten Abstand löst genau eine Aufnahme aus. Weiter davor stehen löst nicht erneut aus. Nach Weggehen ≥ `t_rearm` ist eine neue Auslösung möglich. 10× Vorbeigehen in 1 m ergibt 0 Auslösungen.
- **A3 Ablauf:** 10 Auslösungen mit 1–2 Personen enden je in Gemälde oder Rückfall. Kein Hänger, Maximum von der Auslösung bis zur Anzeige ≤ 95 s. Bis alle Szenen einmal dran waren, wiederholt sich keine.
- **A4 Rückfall:** Hotspot aus führt zum Schockbild in ≤ 10 s und dann zurück zu `IDLE`. Ein künstlicher Timeout (Testkonfiguration) führt nach 90 s zum Schockbild. Ohne Gesicht gibt es keinen API-Aufruf (Log). Ein simulierter 402 führt zum Schockbild; die nächste Auslösung erzeugt keinen API-Aufruf.
- **A5 Löschregel:** Nach A3/A4 findet sich kein Gästefoto auf dem Datenträger (`find / -newer <Startmarke> \( -name '*.jpg' -o -name '*.png' \)` ohne Treffer außerhalb des Gemälde-Verzeichnisses). `journalctl` enthält weder Schlüssel noch Bilddaten (`grep` auf `sk-or`, `base64,` und `data:image`).
- **A6 Persistenz:** Die Gemälde überstehen einen Neustart. Ihre Zahl entspricht den erfolgreichen Generierungen.
- **A7 Ausrichtung:** Das Gemälde steht quer, unverzerrt und aufrecht. Die Person auf dem generierten Gemälde steht aufrecht (Kamera-Rotation korrekt, #1451).
- **A8 Stamm unverändert:** Mit Profil `stamm` startet der Stamm wie vorher und der Avatar rendert. Die bestehenden Tests sind grün.
- **A9 Qualität:** Alle Tests sind grün, inklusive des neuen pygame-ce-Jobs in CI; ruff sauber; mypy sauber im CI-Umfang (`core`, `tools`, `web`, `comms`, `agent`, `robot`, `avatar`, `room_display` sowie `llm/image_generator.py` und `llm/openrouter_image_generator.py`). Welche Tests in CI übersprungen werden, wird benannt.
- **A10 Wärme:** M8 bestanden.
- **A11 Setup:** Ein nach der Doku aufgesetzter Rahmen-Pi hat nur pygame-ce (`pip show pygame` → not found) und genau eine Pillow-Quelle.
- **A12 Schlüssel:** Eigener Schlüssel mit gesetztem Limit, nicht im Repo, nicht im Log. Der Widerruf steht in der Checkliste.

**Tor-Kriterium 2026-12-06 (D5):** Stufe 0 gilt als abgenommen, wenn A1–A9, A11 und A12 auf dem Test-Aufbau bestanden sind (Pi, Display, Kamera, APDS am Steckbrett). A10 (Wärme, M8) und die mechanische Fertigstellung des Rahmens folgen bis spätestens 2026-12-27. Ist das Tor nicht bestanden, entfällt Stufe 1 für Silvester (#1461).

## 10. Entscheidungen (Lera, 2026-11-17, #1475)

- **D1 BME280:** minimal und streichbar. `robot/bme280_reader.py` (`Bme280Reader`, kein `SensorManager`, Ae11) schreibt nur ins Log und warnt ab einer Schwelle. Letzte Aufgabe in E3; bei Zeitnot fällt sie weg, ohne dass Stufe 0 leidet. Die Hardware wird in jedem Fall eingebaut.
- **D2 Gesichtsprüfung:** OpenCV-Haar per apt (`python3-opencv`), wenn die Prüfung in E4 auf dem Pi unter 300 ms je Bild liegt. Sonst `NullFaceDetector`. Ein Messwert mit Pi-Modell geht in die E4-Meldung. Voraussetzung ist M-E0-3.
- **D3 Galerie:** nein (§4.7). Es gibt keinen Konfigurationsschalter; die Funktion wird nicht gebaut.
- **D4 Weitergabe:** scp durch Lera, danach Löschen auf dem Pi, ein Nextcloud-Freigabelink für alle Gäste mit 30 Tagen Ablauf (§4.7). Kein Code, Schritt in der Party-Checkliste (E6).
- **D5 Tor:** Software auf dem Test-Aufbau (§9).
- **D6 PR-Schnitt:** ein Branch, drei Teil-PRs (§5).
- **D7 Sprache:** Diese Datei wird auf Deutsch geführt.
- **D8 (bedingt offen, Ae4):** Nur falls der ZDR-Check in E1 scheitert: flare ohne ZDR bzw. mit `data_collection=allow`, oder ein anderes Modell. Die Gäste sind informiert (#1449); die Regel aus #1467 bleibt unberührt.

Weiter offen außerhalb dieser Datei: Rahmenkauf und Pi-Modell (R1) sowie die Messungen M-E0-1 bis M-E0-4 (§7).

## Anhang A – Szenenentwürfe (ungetestet außer S1)

Die Szenen stehen als Daten in `src/elder_berry/room_display/portrait/scenes.yaml` (IDs `s1_moonlit_parlour` … `s6_attic_of_dolls`). Der feste Kern wird vom Code angehängt (`scene_catalog.CORE_PROMPT`):
> „Keep every face in this photo clearly recognizable. Painterly brushstrokes, aged canvas with cracked varnish. Horror through atmosphere only: no blood, no wounds, no gore, no violence. Not photorealistic. Landscape format 16:9.“

- **S1 Moonlit parlour** (entspricht A+/Amulti, getestet #1451/#1452/#1466): „Transform everyone in this photo into a haunted Victorian oil painting portrait: deathly pale skin with a faint grey-green tint, dark hollow shadows around the eyes, pale clouded eyes with a cold faint glow, fixed unblinking stares and smiles that feel slightly wrong. Cold moonlight through a tall window, a guttering candle with rising smoke, cobwebs, a decaying canvas with mold stains and peeling paint. In the darkness behind them, a faint ghostly figure, and a pale translucent hand resting on a shoulder.“
- **S2 Forgotten library:** „Transform everyone in this photo into a haunted oil painting set in a decaying candlelit library: towering shelves of rotting books, dust drifting in the air, a tall shadowy figure half-hidden between the shelves. Their skin is ashen, their eyes dim and glassy, their expressions frozen in eerie calm.“
- **S3 Crypt:** „Transform everyone in this photo into a haunted gothic oil painting in an ancient stone crypt: a flickering oil lamp, low mist creeping over the floor, black ravens perched on a cracked sarcophagus. Their faces are pale as marble, their eyes catch the lamplight with a cold glint, their stares fixed on the viewer.“
- **S4 Abandoned ballroom:** „Transform everyone in this photo into a haunted baroque oil painting in an abandoned ballroom, dressed in faded period costume: chandeliers draped in cobwebs, cold blue light through broken windows, translucent ghostly dancers frozen mid-step in the background. Their smiles are polite but subtly wrong, their skin grey and waxen.“
- **S5 Hall of mirrors:** „Transform everyone in this photo into a haunted Victorian oil painting in a hall of tarnished mirrors: lightning flashes through a window, and the reflections do not quite match the people — in the glass, dark shapes stand where no one is. Pale skin, shadowed eyes, a faint uncanny glow in their gaze.“
- **S6 Attic of dolls:** „Transform everyone in this photo into a haunted oil painting in a dusty attic lit by a single lantern: rows of cracked porcelain dolls on the shelves seem to turn their heads toward them, rain streaks the small round window. Their faces are pallid, their eyes clouded, their expressions eerily still.“

Testregel nach #1467: Jede Szene wird mit 1 und mit 2 Personen je 2–3 Mal getestet, möglichst mit Kamerabildern aus dem Rahmen (M6). Szenen mit Ablehnung oder schlechter Erkennbarkeit werden entschärft oder gestrichen. Für den Betrieb bleiben 4–6 Szenen. Risiko bei S5: Das Modell könnte Gesichter in den Spiegeln verdoppeln; die Erkennbarkeit hat Vorrang.
