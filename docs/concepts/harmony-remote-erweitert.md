# Harmony Remote – Erweiterte Steuerung & IR-Learning

> **Status (2026-03-29):** Phase 37.2 – Erweiterte Harmony Remote
> Voraussetzung: Phase 37.1 (Harmony Hub Basisintegration) ✓ abgeschlossen
> Entscheidung: PWA-Szenen auf RPi5 (Option B), Saleria nutzt dieselbe Szenen-Engine

## Übersicht

Zwei Erweiterungsstufen für die Harmony Remote PWA:

1. **Erweiterte Fernbedienung** – Geräte-spezifische Layouts mit Steuerkreuz,
   Mediatasten, Input-Switching, Nummernblock. Umschaltbar zwischen Geräten.
2. **IR-Learning & Geräteverwaltung** – Neue Geräte anlegen, IR-Codes anlernen,
   Aktivitäten zusammenstellen. Alles über die PWA, kein Terminal nötig.

---

## Teil 1: Erweiterte Fernbedienung

### Architektur: Aktivitäts-Layouts vs. Geräte-Layouts

Zwei Ansichten die der Nutzer umschalten kann:

```
[Aktivitäts-Modus]              [Geräte-Modus]
┌─────────────────────┐         ┌─────────────────────┐
│ Fernsehen           │         │ ▼ Denon AVR-X3500H  │  ← Dropdown
│                     │         │                     │
│ Steuerkreuz (TV)    │         │ Alle 93 Denon-      │
│ Lautstärke (Denon)  │         │ Befehle nach        │
│ Sender (TV)         │         │ Gruppen sortiert    │
│ Mediatasten (TV)    │         │                     │
│ Smart Hub (TV)      │         │                     │
└─────────────────────┘         └─────────────────────┘
```

**Aktivitäts-Modus** (Standard): Zeigt die wichtigsten Controls für die
aktuelle Aktivität. Befehle kommen von verschiedenen Geräten gleichzeitig
(z.B. Lautstärke → Denon, Navigation → TV). Entspricht dem was man im
Alltag braucht.

**Geräte-Modus** (Experten): Ein Dropdown wählt das Gerät. Zeigt ALLE
verfügbaren Befehle dieses Geräts, gruppiert nach ControlGroup. Für
Input-Switching am Receiver, erweiterte TV-Einstellungen etc.

### Geräte und ihre Layouts

#### Samsung TV – Fernbedienung

```
┌─────────────────────────────┐
│  ⏻ Power                    │
├─────────────────────────────┤
│  1   2   3                  │
│  4   5   6                  │  Nummernblock
│  7   8   9                  │
│  -   0   ChannelList        │
├─────────────────────────────┤
│  CH▲                        │
│  CH Prev    CH▼             │  Sender
├─────────────────────────────┤
│        ▲                    │
│   ◄  Select  ►             │  Steuerkreuz
│        ▼                    │
│  Return    Menu             │
├─────────────────────────────┤
│  ◄◄  ▶  ▶▶                 │
│  ⏹   ⏸   ⏺                │  Transport
├─────────────────────────────┤
│  🔴  🟢  🔵  🟡            │  Farbtasten
├─────────────────────────────┤
│  Guide  Info  Exit          │
│  Home  Source  SmartHub     │  Extras
│  Teletext  Tools  Search   │
├─────────────────────────────┤
│  HDMI1  HDMI2  HDMI3       │
│  TV     AV     Component   │  Inputs
└─────────────────────────────┘
```

**Verfügbare Commands (70):**
- Power: PowerOff, PowerOn, PowerToggle
- NumericBasic: -, 0–9
- Volume: Mute, VolumeDown, VolumeUp
- Channel: ChannelPrev, ChannelDown, ChannelUp
- NavigationBasic: DirectionDown/Left/Right/Up, Select
- TransportBasic: Stop, Play, Rewind, Pause, FastForward
- TransportRecording: Record
- NavigationDVD: Return, Menu
- NavigationDSTB: A, B, C, D, ChannelList, Search
- ColoredButtons: Green, Red, Blue, Yellow
- NavigationExtended: Guide, Info, Exit
- Teletext: Teletext
- Miscellaneous: Home, Source, SmartHub, InputHdmi1/2/3, InputTv,
  InputAv, InputComponent, Tools, WebBrowser, E-Manual, etc.

#### Denon AVR-X3500H – Receiver

```
┌─────────────────────────────┐
│  ⏻ On    ⏻ Off             │
├─────────────────────────────┤
│  Vol–   🔇 Mute   Vol+     │  Lautstärke
├─────────────────────────────┤
│        ▲                    │
│   ◄  Enter  ►              │  Steuerkreuz
│        ▼                    │
│       Back                  │
├─────────────────────────────┤
│  Setup      Info            │
│  Option     Sleep           │
├─────────────────────────────┤
│  INPUT-QUELLEN              │
│  CBL/Sat   Blu-ray  DVD    │
│  Game      MediaPl  TV     │
│  Aux1      Aux2     CD     │
│  BT        HEOS    Tuner   │
│  USB       Phono            │
├─────────────────────────────┤
│  SOUND-MODI                 │
│  Stereo    Direct   Movie   │
│  Music     Game     Standard│
│  DTS-Surr  Atmos   Virtual │
├─────────────────────────────┤
│  Quick 1  Quick 2           │
│  Quick 3  Quick 4           │  QuickSelect
└─────────────────────────────┘
```

**Verfügbare Commands (93):**
- Power: PowerOff, PowerOn, PowerToggle
- Volume: Mute, VolumeDown, VolumeUp
- NavigationBasic: DirectionDown/Left/Right/Up, Enter
- TransportBasic: Play, Pause
- TransportExtended: SkipBack, SkipForward
- NavigationDVD: Back
- Setup: Setup, Sleep
- NavigationExtended: Info, PageDown, PageUp
- RadioTuner: PresetPrev/Next, TuneDown/Up
- Miscellaneous (68): Alle Input-Quellen (InputCbl/Sat, InputBlu-ray,
  InputGame, InputBluetooth, InputHEOS, etc.), alle Sound-Modi
  (ModeStereo, ModeDirect, ModeMovie, ModeMusic, ModeAtmos, etc.),
  Audyssey, DynEQ, Eco, QuickSelect1–4, HDMI-Monitor-Select

#### PS4

```
┌─────────────────────────────┐
│  ⏻ Off     PS               │
├─────────────────────────────┤
│        ▲                    │
│   ◄   OK   ►               │  Steuerkreuz
│        ▼                    │
│       Back                  │
├─────────────────────────────┤
│   △    ○    ×    □          │  Controller
├─────────────────────────────┤
│  ◄◄  ▶  ▶▶                 │
│  ⏹   ⏸                     │  Transport
├─────────────────────────────┤
│  Options  Share  Search     │
│  Info                       │
└─────────────────────────────┘
```

**Verfügbare Commands (23):**
- Power: PowerOff
- NavigationBasic: DirectionDown/Left/Right/Up, OK
- TransportBasic: Stop, Play, Rewind, Pause, FastForward
- NavigationDVD: Back
- NavigationDSTB: Search
- GameType2: Cross, Circle, Square, Triangle
- NavigationExtended: Info
- Miscellaneous: Next Video, Options, Previous Video, PS, Share

#### Amazon Fire TV

```
┌─────────────────────────────┐
│        ▲                    │
│   ◄   OK   ►               │  Steuerkreuz
│        ▼                    │
│  Back   Home   Menu         │
├─────────────────────────────┤
│  ◄◄  ▶  ▶▶                 │
│  ⏹   ⏸                     │  Transport
├─────────────────────────────┤
│  Search    Exit             │
└─────────────────────────────┘
```

**Verfügbare Commands (18):**
- NavigationBasic: DirectionDown/Left/Right/Up, OK
- TransportBasic: Stop, Play, Rewind, Pause, FastForward
- TransportExtended: SkipBackward, SkipForward
- NavigationDVD: Menu, Back
- NavigationDSTB: Search
- NavigationExtended: Exit
- GoogleTVNavigation: Delete
- Miscellaneous: Home

#### Windows-PC (vereinfacht – nur die sinnvollen Remote-Befehle)

```
┌─────────────────────────────┐
│        ▲                    │
│   ◄   OK   ►               │  Steuerkreuz
│        ▼                    │
│  Escape   Enter             │
├─────────────────────────────┤
│  ◄◄  ▶  ▶▶                 │
│  ⏹   ⏸   ⏭               │  Transport
├─────────────────────────────┤
│  Vol–   🔇   Vol+           │  Lautstärke
├─────────────────────────────┤
│  Tab   Alt+Tab   Win+D      │
│  Space  F11(FS)  Escape     │  Shortcuts
├─────────────────────────────┤
│  Sleep   WakeUp   LockPC    │  System
└─────────────────────────────┘
```

**Hinweis:** Der Windows-PC hat 151 Commands (volle Tastatur-Emulation).
Die Remote zeigt nur eine kuratierte Auswahl. Im Geräte-Modus sind alle
151 Befehle verfügbar.

### Aktivitäts-Layout: "Fernsehen"

Kombiniert Befehle von Samsung TV + Denon Receiver:

```
┌─────────────────────────────┐
│  FERNSEHEN              AUS │
├─────────────────────────────┤
│        ▲                    │
│   ◄  Select  ►             │  ← Samsung TV
│        ▼                    │
│  Return    Menu             │  ← Samsung TV
├─────────────────────────────┤
│  Vol–  🔇 Mute  Vol+       │  ← Denon (*)
│  CH▲   CH Prev  CH▼        │  ← Samsung TV
├─────────────────────────────┤
│  ◄◄  ▶  ⏸  ▶▶             │  ← Samsung TV
├─────────────────────────────┤
│  1  2  3  4  5             │
│  6  7  8  9  0             │  ← Samsung TV
├─────────────────────────────┤
│  Guide  Home  Source        │  ← Samsung TV
│  🔴  🟢  🔵  🟡            │  ← Samsung TV
├─────────────────────────────┤
│  [Denon ▼]  [TV ▼]         │  ← Geräte-Schnellzugriff
└─────────────────────────────┘

(*) Lautstärke geht standardmäßig an Denon Receiver,
    nicht an Samsung TV — weil der Receiver den Sound macht.
    Konfigurierbar im Layout-Editor (siehe unten).
```

### UI-Architektur (PWA)

```
harmony_remote/
├── index.html              ← Shell, Router
├── css/
│   └── remote.css          ← Layout, Themes, Button-Styles
├── js/
│   ├── app.js              ← Router, State, API-Client
│   ├── activity-view.js    ← Aktivitäts-Modus
│   ├── device-view.js      ← Geräte-Modus (Dropdown + alle Befehle)
│   ├── layouts.js          ← Layout-Definitionen pro Gerät/Aktivität
│   └── api.js              ← fetch-Wrapper für /harmony/* Endpoints
├── manifest.json
└── sw.js
```

### Layout-Konfiguration (layouts.js / layouts.json)

Layouts werden als JSON definiert — editierbar über UI oder Datei.
Jedes Layout ist ein Array von "Sektionen" mit Button-Definitionen:

```json
{
  "activities": {
    "Fernsehen": {
      "sections": [
        {
          "label": "Navigation",
          "type": "dpad",
          "device": "Samsung TV",
          "center": "Select",
          "extra": [
            {"cmd": "Return", "label": "Zurück"},
            {"cmd": "Menu", "label": "Menü"}
          ]
        },
        {
          "label": "Lautstärke & Sender",
          "type": "grid",
          "buttons": [
            {"device": "Denon AV-Empfänger", "cmd": "VolumeDown", "label": "Vol–"},
            {"device": "Denon AV-Empfänger", "cmd": "Mute", "label": "🔇"},
            {"device": "Denon AV-Empfänger", "cmd": "VolumeUp", "label": "Vol+"},
            {"device": "Samsung TV", "cmd": "ChannelUp", "label": "CH▲"},
            {"device": "Samsung TV", "cmd": "ChannelPrev", "label": "CH←"},
            {"device": "Samsung TV", "cmd": "ChannelDown", "label": "CH▼"}
          ]
        },
        {
          "label": "Transport",
          "type": "grid",
          "buttons": [
            {"device": "Samsung TV", "cmd": "Rewind", "label": "◄◄"},
            {"device": "Samsung TV", "cmd": "Play", "label": "▶"},
            {"device": "Samsung TV", "cmd": "Pause", "label": "⏸"},
            {"device": "Samsung TV", "cmd": "FastForward", "label": "▶▶"}
          ]
        },
        {
          "label": "Nummernblock",
          "type": "numpad",
          "device": "Samsung TV"
        },
        {
          "label": "Extras",
          "type": "grid",
          "buttons": [
            {"device": "Samsung TV", "cmd": "Guide", "label": "Guide"},
            {"device": "Samsung TV", "cmd": "Home", "label": "Home"},
            {"device": "Samsung TV", "cmd": "Source", "label": "Source"}
          ]
        }
      ]
    }
  },
  "devices": {
    "Samsung TV": {
      "sections": "auto"
    },
    "Denon AV-Empfänger": {
      "sections": "auto"
    }
  }
}
```

**`"sections": "auto"`** im Geräte-Modus: Die UI generiert automatisch
Sektionen aus den ControlGroups des Hub-Configs. Keine manuelle Pflege nötig.

### Sektions-Typen

| Typ | Darstellung | Verwendung |
|-----|-------------|------------|
| `dpad` | Steuerkreuz (5 Buttons: ▲◄●►▼) + optionale Extra-Buttons | Navigation |
| `grid` | Flexibles Button-Grid (3 Spalten default) | Lautstärke, Transport, Extras |
| `numpad` | 3×4 Nummernblock (1–9, -, 0, ChList) | Senderwahl |
| `transport` | Mediensteuerung (⏮ ◄◄ ▶ ⏸ ▶▶ ⏭) | Wiedergabe |
| `colors` | 4 Farbtasten nebeneinander (RGBY) | Teletext / HbbTV |
| `inputs` | Benannte Buttons in Grid (z.B. HDMI1, HDMI2) | Input-Switching |

### API-Ergänzungen (RPi5)

Die bestehenden Endpoints reichen für Teil 1 fast komplett.
Eine Ergänzung:

```
GET /harmony/config/detailed
```

Gibt die vollständige Device-Config zurück (nicht nur Namen, sondern
auch alle ControlGroups mit Commands). Damit kann die PWA die
Geräte-Ansicht automatisch generieren.

```json
{
  "activities": [
    {
      "id": "38979034",
      "label": "Fernsehen",
      "volume_device": "62021067",
      "channel_device": "62021067"
    }
  ],
  "devices": [
    {
      "id": "64265888",
      "label": "Denon AV-Empfänger",
      "control_groups": [
        {
          "name": "Power",
          "commands": ["PowerOff", "PowerOn", "PowerToggle"]
        },
        {
          "name": "Volume",
          "commands": ["Mute", "VolumeDown", "VolumeUp"]
        }
      ]
    }
  ]
}
```

### Speicherung der Custom-Layouts

Layouts werden in `~/.elder-berry/harmony_layouts.json` auf dem RPi5
gespeichert. Die PWA lädt sie beim Start und kann sie über einen
neuen Endpoint speichern:

```
GET  /harmony/layouts          → aktuelles Layout-JSON
POST /harmony/layouts          → Layout speichern
```

Default-Layout wird beim ersten Start aus dem Hub-Config automatisch
generiert (Aktivitäts-Layouts aus Activity-ControlGroups, Geräte-Layouts
aus Device-ControlGroups).

### PWA-Installation auf dem Handy

Die Harmony Remote ist als Progressive Web App (PWA) gebaut und kann
direkt auf dem Handy-Homescreen installiert werden — kein App Store nötig.
Nach der Installation verhält sie sich wie eine native App: eigenes Icon,
Vollbild ohne Browser-Leiste, Offline-fähig.

**Installation (einmalig):**

**Android (Chrome):**
1. `fern.last-strawberry.com` im Browser öffnen
2. Chrome zeigt automatisch "Zum Startbildschirm hinzufügen" Banner
3. Falls nicht: Drei-Punkte-Menü (⋮) → "App installieren" / "Zum Startbildschirm"
4. Icon erscheint auf dem Homescreen

**iOS (Safari):**
1. `fern.last-strawberry.com` in Safari öffnen (muss Safari sein, kein Chrome)
2. Teilen-Button (□↑) → "Zum Home-Bildschirm"
3. Name bestätigen → "Hinzufügen"
4. Icon erscheint auf dem Homescreen

**Technische Voraussetzungen für PWA-Installierbarkeit:**

```json
// manifest.json — muss enthalten:
{
  "name": "Harmony Remote",
  "short_name": "Remote",
  "display": "standalone",        // Vollbild, keine Browser-Leiste
  "orientation": "portrait",
  "start_url": "/",
  "scope": "/",
  "background_color": "#1a1a2e",
  "theme_color": "#7c3aed",
  "icons": [
    {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

**Service Worker (sw.js):**
Cacht die statischen Assets (HTML, CSS, JS) beim ersten Laden.
Danach öffnet die App sofort — auch bei schlechtem WLAN.
API-Calls (`/harmony/*`) werden nie gecacht (immer live).

```javascript
const CACHE = "harmony-remote-v1";
const STATIC = ["/", "/index.html", "/css/remote.css",
                "/js/app.js", "/js/api.js", "/js/layouts.js",
                "/js/activity-view.js", "/js/device-view.js",
                "/manifest.json"];

self.addEventListener("install", e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC))));

self.addEventListener("fetch", e => {
  if (e.request.url.includes(":8000")) return;  // API nie cachen
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
```

**Ergebnis:** Du tippst auf das Icon → App öffnet sofort im Vollbild →
Harmony-Steuerung bereit. Kein Browser, kein Tippen von URLs.

**HTTPS-Pflicht:** PWA-Installation erfordert HTTPS. Läuft bereits
über `fern.last-strawberry.com` mit Let's Encrypt auf dem Rootserver.

---

## Teil 2: IR-Learning & Geräteverwaltung

### Voraussetzung

Teil 1 muss stabil laufen. IR-Learning ist eine Erweiterung,
kein Blocker für die tägliche Nutzung.

### Flow: Neuen Befehl anlernen

```
PWA                          RPi5                         Hub
 │                            │                            │
 │  "IR-Lernen starten"       │                            │
 │  Device: Samsung TV        │                            │
 │  Name: "Settings"          │                            │
 ├──POST /harmony/learn──────►│                            │
 │                            ├──learn_command()──────────►│
 │                            │                            │ LED blinkt
 │  "Richte Fernbedienung     │                            │
 │   auf Hub und drücke       │                            │
 │   die Taste..."            │                            │
 │                            │                            │
 │                            │  ◄── IR-Signal empfangen ──┤
 │                            │  ◄── Code gespeichert ─────┤
 │                            │                            │
 │  ◄── "Settings gelernt" ──┤                            │
 │                            │                            │
 │  Button erscheint in UI    │                            │
 │  Config-Backup aktualisiert│                            │
```

### Flow: Neues Gerät anlegen

```
1. PWA: "Neues Gerät" → Name eingeben, Typ wählen
2. RPi5: Gerät in lokaler Config anlegen (leere Command-Liste)
3. PWA: "Taste anlernen" Loop:
   a. Befehlsname eingeben (z.B. "Power", "VolumeUp")
   b. Hub in Lernmodus versetzen
   c. Nutzer drückt Taste auf Original-Fernbedienung
   d. Hub bestätigt → Befehl gespeichert
   e. Wiederholen für weitere Tasten
4. PWA: "Fertig" → Gerät vollständig angelegt
5. Optional: Gerät einer Aktivität zuordnen
```

### API-Endpoints für IR-Learning

```
POST /harmony/learn
  Body: {"device": "Samsung TV", "command_name": "Settings"}
  Response: {"success": true, "status": "waiting_for_ir"}
  → Hub geht in Lernmodus

GET /harmony/learn/status
  Response: {"status": "waiting"|"learned"|"timeout"|"idle"}
  → PWA pollt diesen Endpoint bis Status != "waiting"

POST /harmony/device/create
  Body: {"name": "Neue Soundbar", "type": "media"}
  Response: {"success": true, "device_id": "12345678"}

DELETE /harmony/device/{device_id}/command/{command_name}
  → Einzelnen gelernten Befehl entfernen

DELETE /harmony/device/{device_id}
  → Gerät komplett entfernen
```

### API-Endpoints für Szenen-Verwaltung

```
GET /harmony/scenes
  Response: {"scenes": [{"name": "Gaming", "steps": [...]}]}
  → Alle Szenen auflisten (PWA lädt diese beim Start)

POST /harmony/scenes
  Body: {
    "name": "Gaming",
    "steps": [
      {"device": "Denon AV-Empfänger", "cmd": "PowerOn", "delay_after": 2.0},
      {"device": "Denon AV-Empfänger", "cmd": "InputGame", "delay_after": 1.0},
      {"device": "Samsung TV", "cmd": "PowerOn", "delay_after": 2.0},
      {"device": "Samsung TV", "cmd": "InputHdmi2", "delay_after": 1.0},
      {"device": "Sony PS4", "cmd": "PowerOn"}
    ]
  }
  → Szene erstellen oder aktualisieren

POST /harmony/scene/start
  Body: {"name": "Gaming"}
  → Szene starten (RPi5 führt Steps sequenziell aus)
  → Genutzt von PWA und Saleria

DELETE /harmony/scene/{name}
  → Szene löschen
```

### Einschränkungen

- **IR-Learning braucht physischen Zugang zum Hub** — die
  Original-Fernbedienung muss auf den Hub gerichtet werden.
  Das geht nicht remote, nur im selben Raum.
- **Neue Geräte haben initial kein Layout** — nach dem Anlernen
  erscheinen die Befehle im Geräte-Modus (auto-generiert).
  Ein Custom-Layout muss manuell erstellt werden.
- **aioharmony learn_command()** — die Funktion existiert in der
  Library, aber die Zuverlässigkeit muss getestet werden.
  Fallback: IR-Codes manuell aus LIRC/irdb importieren.
- **Aktivitäten erstellen über die lokale API** — das ist der
  komplexeste Teil. Eine Aktivität ist intern eine Abfolge von
  Power-On-Befehlen + Input-Switching + Delay-Sequenzen.
  Eventuell einfacher: Aktivitäten nur als "Layout-Presets" in
  der PWA abbilden (UI-seitig) statt im Hub selbst.

### Entschieden: PWA-Szenen auf RPi5 (Option B)

Neue Aktivitäten werden als **Szenen auf dem RPi5** gespeichert –
nicht als echte Hub-Aktivitäten. Bestehende Hub-Aktivitäten (Fernsehen)
bleiben wie sie sind.

**Architektur:**

```text
RPi5 (Single Source of Truth)
  ~/.elder-berry/harmony_scenes.json
         │
         ├── GET    /harmony/scenes          → Liste aller Szenen
         ├── POST   /harmony/scenes          → Szene erstellen/bearbeiten
         ├── POST   /harmony/scene/start     → Szene starten (PWA oder Saleria)
         └── DELETE  /harmony/scene/{name}   → Szene löschen
```

**PWA** = Editor + Fernbedienung (erstellt, bearbeitet, startet Szenen)
**RPi5** = Speicher + Executor (einzige Quelle, führt Befehlsketten aus)
**Saleria** = Auslöser via Matrix-Command ("starte Gaming" → RPi5 → Szene)

PWA speichert nichts lokal – holt bei jedem Öffnen die Szenen vom RPi5.
So sind PWA und Saleria immer auf demselben Stand.

**Warum nicht Hub-Aktivitäten?**
- aioharmony Activity-Create API ist schlecht dokumentiert und fragil
- PWA-Szenen bieten volle Kontrolle und sind einfach zu implementieren
- Saleria-Anbindung trivial: selber Endpoint wie PWA

---

## Implementierungsreihenfolge

```
Teil 1 – Erweiterte Fernbedienung
  Schritt 1: /harmony/config/detailed Endpoint (Backend)
  Schritt 2: Layout-System (layouts.json, Sektions-Typen)
  Schritt 3: Geräte-Modus (Dropdown, auto-generierte Layouts aus ControlGroups)
  Schritt 4: Aktivitäts-Layout für "Fernsehen" (manuell kuratiert)
  Schritt 5: /harmony/layouts GET/POST Endpoints
  Schritt 6: UI-Polish (Animations, Haptic Feedback, Long-Press für Repeat)

Teil 2 – Szenen & IR-Learning
  Schritt 7: Szenen-Engine auf RPi5 (harmony_scenes.json, sequenzielle Ausführung)
  Schritt 8: Szenen-API (/harmony/scenes CRUD + /harmony/scene/start)
  Schritt 9: Szenen-UI in PWA (erstellen, bearbeiten, starten)
  Schritt 10: Saleria-Anbindung (Matrix-Command "starte {szene}" → Szenen-Engine)
  Schritt 11: /harmony/learn Endpoint + aioharmony learn_command()
  Schritt 12: Lern-UI in PWA (Wizard: Gerät → Name → Lernen → Fertig)
  Schritt 13: /harmony/device/create + delete Endpoints
```

## Testliste (Schätzung)

```
Teil 1 (~25 Tests):
  Layout-Parsing, Sektions-Rendering, Geräte-Dropdown,
  API /config/detailed, API /layouts GET/POST,
  Auto-Layout-Generierung, Custom-Layout-Override,
  Aktivitäts-Layout Device-Mapping (Vol→Denon, Nav→TV)

Teil 2 (~30 Tests):
  Szenen-Engine: Laden, Speichern, sequenzielle Ausführung, Delay-Handling
  Szenen-API: CRUD-Endpoints, Start-Endpoint, Fehler bei unbekannter Szene
  Szenen-PWA: Erstellen, Bearbeiten, Löschen, Starten
  Saleria: Matrix-Command "starte {szene}" → Szenen-Engine
  IR-Learning: Learn-Endpoint, Learn-Status-Polling, Timeout-Handling
  Geräteverwaltung: Device-Create, Device-Delete, Command-Delete
```