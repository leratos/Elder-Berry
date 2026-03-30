# Phase 37 – Smart Home Integration

## Übersicht & Architekturprinzip

Phase 36 baut Saleria zu einem vollständigen Smart-Home-Controller aus — cloud-unabhängig,
erweiterbar durch ein Plugin/Adapter-System.

**Kernprinzip**: Saleria spricht nie direkt gegen einzelne Systeme (Harmony, HA, Zigbee).
Stattdessen gibt es eine abstrakte `SmartHomeInterface`-Schicht. Alle Adapter
(Harmony, Home Assistant, zukünftige) implementieren dasselbe Interface.
Befehle und Queries gehen immer durch diese Schicht.

```
Saleria (Sprache / Matrix)
         │
         ▼
SmartHomeCommandHandler
         │
         ▼
 SmartHomeInterface  ←── Plugin-Registry
    ├── HarmonyAdapter       (Phase 36.1)
    ├── HomeAssistantAdapter (Phase 36.3)
    └── [ZigbeeAdapter, ...]  (future)
```

### Unterphasen

| Phase | Titel | Abhängigkeit | Status |
|-------|-------|-------------|--------|
| 37.1 | Harmony Hub – vollständige Ablösung | keine | ✓ abgeschlossen |
| 37.2 | Harmony Remote – Erweiterte Steuerung & Szenen | 37.1 | in Arbeit |
| 37.3 | SmartHomeInterface + Plugin-Registry | 37.1 als Referenzimplementierung | offen |
| 37.4 | Home Assistant Adapter | 37.3 | offen |
| 37.5 | Alexa-Integration (Emulated Hue) | 37.1 + 37.4 | nach Umzug |

**Begründung für sofortige Logitech-Ablösung (36.1):**
- Letztes Logitech-Server-Update: September 2024
- Config-Software abgeschaltet: 28. Mai 2025
- Wenn Server abschaltet ohne Vorwarnung: keine Konfigurationsänderungen mehr möglich
- Jetzt testen = Rückfallebene (Logitech-Server läuft noch) + Produktivsystem wenn abgeschaltet

---

# Phase 37.1 – Harmony Hub: Vollständige Logitech-Ablösung

## Deployment-Entscheidung: HarmonyAdapter läuft auf dem RPi5

Der RPi5 (Salerias Gehäuse, 8 GB) läuft 24/7 — der Tower nicht.
TV-Steuerung muss auch funktionieren wenn der Tower aus ist.

```
Tower (Gehirn, läuft nicht immer)
  └── SmartHomeCommandHandler
        └── RobotClient.harmony_*()  ──→  RPi5 :8001/harmony/*
                                            └── HarmonyAdapter
                                                  └── Hub :8088 (WebSocket, lokal)

PWA (Handy, Fernbedienung verlegt)
  └──→ RPi5 :8001/harmony/*  (Tower komplett umgangen)

Config-Mock-Server
  └──→ Rootserver (immer erreichbar, auch bei RPi5-Neustart)
```

**Warum RPi5 statt Tower:**
- RPi5 läuft 24/7 (Display, Avatar, Sensoren)
- Tower kann aus sein — TV-Steuerung muss trotzdem funktionieren
- Passt ins bestehende Pattern: RPi5 ist I/O-Controller für alle
  physischen/lokalen Geräte (Camera, Turntable → jetzt auch Harmony)
- PWA kann direkt gegen RPi5 sprechen ohne Tower als Zwischenstufe

**Konsequenz für die Implementierung:**
- `HarmonyAdapter` → `src/elder_berry/robot/` (neben camera_controller, turntable_controller)
- Neue Endpoints in `src/elder_berry/robot/server.py` (`/harmony/*`)
- Neue Methoden in `src/elder_berry/robot/client.py` (`harmony_*()`)
- `SmartHomeCommandHandler` (Tower) ruft `RobotClient.harmony_*()` auf

## Was ersetzt wird

| Logitech-Komponente | Ersatz in 36.1 | Läuft auf |
|---------------------|----------------|-----------|
| Harmony-App (Steuerung) | Custom PWA | Rootserver |
| Logitech-Cloud (Betrieb) | WebSocket :8088 | RPi5 → Hub direkt |
| `setup.myharmony.com` (Konfiguration) | Config-Mock-Server | Rootserver |
| Alexa-Integration (Sprachsteuerung) | Saleria → RobotClient → RPi5 | Tower + RPi5 |

## User-Flow nach 36.1

```
Nutzer: "mach lauter"
Saleria → HarmonyAdapter.send_command("Receiver", "VolumeUp") → Hub → IR

Nutzer: "fernsehen an"
Saleria → HarmonyAdapter.start_activity("Fernsehen") → Hub

[Fernbedienung verlegt]
→ PWA auf Handy (remote.last-strawberry.com) → Tap "Fernsehen" → Hub

[neue Komponente hinzufügen, Logitech-Server tot]
→ Config-Mock-Server liefert gespeichertes JSON zurück
→ Hub-App nimmt Änderung an
```

---

## 37.1.A – Schritt 0: Konfigurations-Backup (einmalig, sofort)

Solange Logitech-Server noch läuft — dieser Schritt ist zeitkritisch.

```bash
pip install aioharmony

# Hub-IP aus Router (statische IP empfohlen, z.B. per MAC-Reservierung)
python -m aioharmony --harmony_ip 192.168.50.X \
    --protocol WEBSOCKETS show_detailed_config > harmony_config_backup.json
```

Backup ablegen:
- `C:\Dev\Elder-Berry\config\harmony_config_backup.json` (Repo)
- `%USERPROFILE%\.elder-berry\harmony_config.json` (Runtime-Pfad)

Das JSON enthält alle Aktivitäten (mit IDs), alle Geräte und alle IR-Codes.
Es ist die Grundlage für den Config-Mock-Server und den Fallback-Betrieb.

**Statische IP für den Hub im Router setzen** (MAC-Reservierung),
damit `harmony_hub_ip` in der Konfiguration dauerhaft stimmt.

---

## 37.1.B – HarmonyAdapter (läuft auf RPi5)

**Datei**: `src/elder_berry/robot/harmony_adapter.py`

Folgt dem Muster von `camera_controller.py` und `turntable_controller.py`.
Implementiert später das `SmartHomeInterface` (Phase 36.2).
Kommuniziert ausschließlich über WebSocket :8088 — kein Cloud-Auth.
Läuft im Prozess des RobotServers auf dem RPi5.

```python
"""HarmonyAdapter – Lokale Steuerung des Logitech Harmony Hub.

Kommuniziert über die lokale WebSocket-API auf Port 8088.
Kein Logitech-Account, kein Cloud-Zugriff erforderlich.

Wird in Phase 36.2 als SmartHomeInterface-Implementierung formalisiert.
Voraussetzung: Hub und Tower im selben Netzwerk.

Verwendung:
    adapter = HarmonyAdapter(hub_ip="192.168.50.X")
    await adapter.connect()
    await adapter.start_activity("Fernsehen")
    await adapter.send_command(device="Receiver", command="VolumeUp")
    activity = await adapter.get_current_activity()
    await adapter.disconnect()
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path.home() / ".elder-berry" / "harmony_config.json"
_HUB_PORT = 8088


class HarmonyAdapter:
    """Logitech Harmony Hub Steuerung via lokaler WebSocket-API."""

    def __init__(
        self,
        hub_ip: str,
        config_path: Path = _DEFAULT_CONFIG_PATH,
    ) -> None:
        self.hub_ip = hub_ip
        self.config_path = config_path
        self._client = None        # aioharmony HarmonyAPI
        self._config: dict = {}    # gecachte Hub-Konfiguration
        self._connected = False

    # ── Verbindung ────────────────────────────────────────────────────── #

    async def connect(self) -> bool:
        """Verbindet mit Hub. Lädt Config live, Fallback: Backup-JSON."""
        ...

    async def disconnect(self) -> None:
        """Trennt Verbindung sauber."""
        ...

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Aktivitäten ───────────────────────────────────────────────────── #

    async def start_activity(self, activity_name: str) -> bool:
        """Startet Aktivität per Name (case-insensitive)."""
        ...

    async def power_off(self) -> bool:
        """Schaltet alle Geräte aus."""
        ...

    async def get_current_activity(self) -> Optional[str]:
        """Gibt aktuellen Aktivitätsnamen zurück, None wenn PowerOff."""
        ...

    async def list_activities(self) -> list[str]:
        """Alle konfigurierten Aktivitäten."""
        ...

    # ── Gerätebefehle ─────────────────────────────────────────────────── #

    async def send_command(
        self,
        device: str,
        command: str,
        repeat: int = 1,
    ) -> bool:
        """Sendet IR-Befehl an Gerät (case-insensitive Namen)."""
        ...

    async def list_commands(self, device: str) -> list[str]:
        """Alle verfügbaren Befehle für ein Gerät."""
        ...

    async def list_devices(self) -> list[str]:
        """Alle konfigurierten Gerätenamen."""
        ...

    # ── Intern ────────────────────────────────────────────────────────── #

    def _load_backup_config(self) -> dict:
        """Lädt Konfiguration aus lokalem Backup-JSON."""
        ...

    def _find_activity_id(self, name: str) -> Optional[str]:
        ...

    def _find_device_id(self, name: str) -> Optional[str]:
        ...
```

### Abhängigkeit

```
# requirements.txt
aioharmony>=0.5.0
```

### Initialisierung im RobotServer (RPi5)

```python
# src/elder_berry/robot/server.py – create_app() oder Startup-Event
from elder_berry.robot.harmony_adapter import HarmonyAdapter

harmony_adapter = None
hub_ip = config.get("harmony_hub_ip")
if hub_ip:
    harmony_adapter = HarmonyAdapter(hub_ip=hub_ip)
    # connect() lazy beim ersten Request (Hub könnte aus sein beim Start)
```

### elder_berry.json (RPi5-Konfiguration)

```json
{
  "harmony_hub_ip": "192.168.50.X"
}
```

### Konfiguration Backup-Pfad (RPi5)

```python
_DEFAULT_CONFIG_PATH = Path.home() / ".elder-berry" / "harmony_config.json"
# = /home/pi/.elder-berry/harmony_config.json
```

---

## 37.1.C – Config-Mock-Server (Logitech vollständig ablösen)

**Ziel**: Der Hub kann weiterhin Konfigurationsänderungen vornehmen (neue Geräte,
Aktivitäten ändern) — ohne dass Logitechs Server erreichbar sein muss.

**Deployment**: Rootserver (`matrix.last-strawberry.com`) — nicht RPi5.
Der Rootserver ist stabiler als RPi5 (kein Strom-Ausfall durch Neustart,
öffentlich erreichbar für HTTPS-Zertifikat, unabhängig vom Heimnetz).

**Wie der Hub konfiguriert wird** (Reverse-Engineering):
```
Harmony-App → HTTPS POST → setup.myharmony.com/account/getConfig
            ← JSON ← { activities, devices, ir_codes, ... }
```

**Ersatz**:
```
Harmony-App → HTTPS POST → config.last-strawberry.com (dein Rootserver)
            ← JSON ← gespeichertes harmony_config_backup.json
```

### DNS-Override im Heimnetz

Im Router (Pi-hole oder Router-DNS):
```
setup.myharmony.com  →  <Rootserver-IP>
svcs.myharmony.com   →  <Rootserver-IP>
```

Nur für interne Geräte (der Hub fragt nur intern an).
Für alles andere bleibt DNS normal.

### Nginx-Konfiguration (Rootserver)

```nginx
# /etc/nginx/sites-available/harmony-mock
server {
    listen 443 ssl;
    server_name setup.myharmony.com svcs.myharmony.com;

    # Selbst-signiertes Cert (Hub pinnt nicht strikt)
    ssl_certificate     /etc/ssl/harmony-mock/cert.pem;
    ssl_certificate_key /etc/ssl/harmony-mock/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8765;  # FastAPI Mock-Server
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Selbst-signiertes Cert erstellen:
```bash
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout /etc/ssl/harmony-mock/key.pem \
    -out /etc/ssl/harmony-mock/cert.pem \
    -days 3650 \
    -subj "/CN=setup.myharmony.com"
```

### HarmonyMockServer

**Datei**: `src/elder_berry/server/harmony_mock_server.py`

Eigenständiger FastAPI-Server der auf dem Rootserver läuft
(nicht auf dem Tower — der ist nicht immer an).

```python
"""HarmonyMockServer – Lokal gehosteter Ersatz für Logitech-Konfigurations-Server.

Antwortet auf Harmony-Hub-Anfragen mit dem gespeicherten Backup-JSON.
Ermöglicht Konfigurationsänderungen ohne Logitech-Cloud.

Deployment: Rootserver, Port 8765, hinter Nginx mit SSL.
Config-Datei: /etc/elder-berry/harmony_config.json (auf Rootserver)

Endpunkte (aus Reverse-Engineering des Logitech-Protokolls):
  POST /account/getConfig     → gibt harmony_config_backup.json zurück
  POST /account/saveConfig    → speichert neue Konfiguration lokal
  POST /account/getDeviceInfo → IR-Code-Lookup (aus gespeicherter DB)
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import json
from pathlib import Path

CONFIG_PATH = Path("/etc/elder-berry/harmony_config.json")

app = FastAPI(title="Harmony Mock Server")


@app.post("/account/getConfig")
async def get_config(request: Request) -> JSONResponse:
    """Liefert gespeicherte Hub-Konfiguration."""
    ...


@app.post("/account/saveConfig")
async def save_config(request: Request) -> JSONResponse:
    """Speichert geänderte Konfiguration lokal (Persistenz über Server-Neustart)."""
    ...


@app.post("/account/getDeviceInfo")
async def get_device_info(request: Request) -> JSONResponse:
    """IR-Code-Lookup aus lokaler Datenbank."""
    ...
```

### Testprozedur (solange Logitech-Server noch läuft)

```
1. harmony_config_backup.json erstellen (Schritt 0)
2. Mock-Server auf Rootserver deployen
3. DNS-Override auf einem Test-Gerät (nur dieses Gerät, nicht Router-weit)
4. Harmony-App auf Test-Gerät: Konfigurationsänderung vornehmen
5. Prüfen: Hat Hub die Änderung übernommen?
6. Wenn ja: DNS-Override Router-weit ausrollen
7. Logitech-Server bleibt als Backup erreichbar (DNS lässt sich zurücksetzen)
```

**Warum jetzt testen**: Solange echter Server noch läuft, kann bei Fehler
sofort zurückgeschaltet werden (DNS-Override entfernen).

### IR-Code-Datenbank (optional, Phase 36.1+)

Logitech hat eine Datenbank mit ~270.000 Geräten und ihren IR-Codes.
Diese Datenbank ist nicht öffentlich. Optionen für neue Geräte:

1. **IR-Learning direkt am Hub**: Physisch Taste auf Original-Remote drücken,
   Hub lernt den Code — funktioniert ohne Server
2. **LIRC / irdb**: Open-Source IR-Code-Datenbanken für bekannte Geräte
3. **Manuell aus harmony_config_backup.json extrahieren** (alle aktuellen Geräte)

Für 36.1 reicht Option 1 + 3. Option 2 als spätere Erweiterung.

---

## 37.1.D – HarmonyCommandHandler

**Datei**: `src/elder_berry/comms/commands/harmony_commands.py`

```python
"""HarmonyCommandHandler – Sprachbefehle für Harmony Hub.

Löst das Alexa-Lautstärke-Problem: Direkt an Hub, kein Cloud-Umweg.

Pattern-Kollisionsanalyse (gegen alle bestehenden Handler geprüft):
  ⚠️  "lauter"/"leiser" kollidiert mit system_commands (PC-Lautstärke)
      Lösung: harmony_volume_control=true in elder_berry.json
              → Harmony-Handler hat Vorrang wenn Hub verbunden und aktiv

Patterns:
  "fernsehen an" / "tv an" / "musik an"   → start_activity()
  "alles aus" / "harmony aus"             → power_off()
  "mach lauter" / "lauter"               → send_command(receiver, VolumeUp)
  "mach leiser" / "leiser"               → send_command(receiver, VolumeDown)
  "stummschalten" / "stumm"              → send_command(receiver, Mute)
  "was läuft" / "was ist an"             → get_current_activity()
  "harmony aktivitäten"                  → list_activities()
  "harmony geräte"                       → list_devices()
  "harmony befehle [gerät]"              → list_commands(device)
"""
import re
from typing import Optional

ACTIVITY_ON_PATTERN = re.compile(
    r"^(?:starte?\s+)?(?P<activity>fernsehen|tv|musik|radio|gaming|"
    r"film|kino|[a-zäöüß]+(?:\s+[a-zäöüß]+)?)\s+an$",
    re.IGNORECASE,
)
ALL_OFF_PATTERN = re.compile(
    r"^(?:alles?\s+aus|harmony\s+aus|schalte?\s+alles?\s+aus)$",
    re.IGNORECASE,
)
VOLUME_UP_PATTERN   = re.compile(r"^(?:mach\s+)?lauter$", re.IGNORECASE)
VOLUME_DOWN_PATTERN = re.compile(r"^(?:mach\s+)?leiser$", re.IGNORECASE)
MUTE_PATTERN        = re.compile(r"^stummschalten$|^stumm$", re.IGNORECASE)
CURRENT_PATTERN     = re.compile(
    r"^(?:was\s+(?:l[äa]uft|ist\s+an)|harmony\s+status)$", re.IGNORECASE
)
LIST_ACTIVITIES_PATTERN = re.compile(r"^harmony\s+aktivit[äa]ten$", re.IGNORECASE)
LIST_DEVICES_PATTERN    = re.compile(r"^harmony\s+ger[äa]te$", re.IGNORECASE)
LIST_COMMANDS_PATTERN   = re.compile(r"^harmony\s+befehle\s+(?P<device>.+)$", re.IGNORECASE)


class HarmonyCommandHandler:
    def __init__(
        self,
        adapter: "HarmonyAdapter",
        volume_control: bool = True,
    ) -> None:
        self.adapter = adapter
        self.volume_control = volume_control  # aus elder_berry.json

    async def handle(self, text: str, sender: str) -> Optional["CommandResult"]:
        ...
```

---

## 37.1.E – Neue Endpoints in server.py (RPi5)

**Datei**: `src/elder_berry/robot/server.py` — erweitern, nicht neue Datei.
Folgt dem Muster der bestehenden `/camera/*` und `/turntable/*` Endpoints.

```python
# Neue Pydantic-Models (neben AvatarRequest, TurntableRotateRequest etc.)

class HarmonyActivityRequest(BaseModel):
    activity: str          # z.B. "Fernsehen"

class HarmonyCommandRequest(BaseModel):
    device: str            # z.B. "Receiver"
    command: str           # z.B. "VolumeUp"
    repeat: int = 1

# Neue Endpoints:
# GET  /harmony/status   → {"connected": bool, "current_activity": str|null}
# GET  /harmony/config   → {"activities": [...], "devices": [...]}
# POST /harmony/activity → {"success": bool, "activity": str}
# POST /harmony/command  → {"success": bool}
# POST /harmony/off      → {"success": bool}
```

### Neue Methoden in RobotClient (Tower)

**Datei**: `src/elder_berry/robot/client.py` — erweitern.

```python
# Neben capture_image(), rotate_turntable() etc.:

def harmony_status(self) -> dict:
    """GET /harmony/status → {"connected": bool, "current_activity": str|null}"""
    ...

def harmony_config(self) -> dict:
    """GET /harmony/config → {"activities": [...], "devices": [...]}"""
    ...

def harmony_start_activity(self, activity: str) -> bool:
    """POST /harmony/activity"""
    ...

def harmony_send_command(self, device: str, command: str, repeat: int = 1) -> bool:
    """POST /harmony/command"""
    ...

def harmony_power_off(self) -> bool:
    """POST /harmony/off"""
    ...
```

### API-Aufrufe der PWA (gegen RPi5, nicht Tower)

```
GET  http://rpi5-ip:8001/harmony/status
GET  http://rpi5-ip:8001/harmony/config
POST http://rpi5-ip:8001/harmony/activity  {"activity": "Fernsehen"}
POST http://rpi5-ip:8001/harmony/command   {"device": "Receiver", "command": "VolumeUp"}
POST http://rpi5-ip:8001/harmony/off
```

Tower umgehen wenn er aus ist — PWA spricht direkt mit RPi5.

**Hosting**: `remote.last-strawberry.com` (Rootserver, hinter Nginx + HTTPS)
**Datei**: `src/elder_berry/webapp/harmony_remote/index.html` (Single-File PWA)

### Anforderungen

- Aktivitäten als große Tap-Buttons (mobile-first, kein Scrollen)
- Lautstärke +/– Buttons, Mute
- Power-Off Button
- Zeigt aktuelle Aktivität
- Offline-fähig nach erstem Laden (Service Worker)
- Nur im Heimnetz oder via VPN erreichbar (kein öffentlicher Zugang)
- Kein Login (der Hub ist eh nur intern erreichbar)

### API-Aufrufe (gegen RPi5, nicht Tower)

```
GET  http://192.168.50.220:8001/harmony/status
GET  http://tower:8000/harmony/config
POST http://tower:8000/harmony/activity   {"activity": "Fernsehen"}
POST http://tower:8000/harmony/command    {"device": "Receiver", "command": "VolumeUp"}
POST http://tower:8000/harmony/power-off
```

### FastAPI-Endpoints

**Datei**: `src/elder_berry/server/harmony_routes.py`

```python
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/harmony", tags=["harmony"])

class ActivityRequest(BaseModel):
    activity: str

class CommandRequest(BaseModel):
    device: str
    command: str
    repeat: int = 1

# GET  /harmony/status  → {"connected": bool, "current_activity": str|null}
# GET  /harmony/config  → {"activities": [...], "devices": [...]}
# POST /harmony/activity
# POST /harmony/command
# POST /harmony/power-off
```

---

## 37.1.F – Implementierungsreihenfolge

```
Schritt 0 (sofort, einmalig — auf Tower ausführen):
  pip install aioharmony
  python -m aioharmony --harmony_ip 192.168.50.X \
      --protocol WEBSOCKETS show_detailed_config > harmony_config_backup.json
  Backup kopieren nach: C:\Dev\Elder-Berry\config\harmony_config_backup.json
  Statische IP für Hub im Router setzen (MAC-Reservierung)

Schritt 1 – HarmonyAdapter (RPi5):
  NEU:     src/elder_berry/robot/harmony_adapter.py
  pip install aioharmony  (auf RPi5: in /home/pi/elder-berry/.venv)
  harmony_hub_ip in /home/pi/.elder-berry/elder_berry.json
  harmony_config.json auf RPi5 deployen (~/.elder-berry/harmony_config.json)
  TESTS:   tests/test_harmony_adapter.py  (Tower, mit aioharmony-Mocks)

Schritt 2 – RPi5 Server + Tower Client:
  ÄNDERN:  src/elder_berry/robot/server.py   → /harmony/* Endpoints ergänzen
  ÄNDERN:  src/elder_berry/robot/client.py   → harmony_*() Methoden ergänzen
  TESTS:   tests/test_robot_server_harmony.py
           tests/test_robot_client_harmony.py

Schritt 3 – HarmonyCommandHandler (Tower):
  NEU:     src/elder_berry/comms/commands/harmony_commands.py
  Handler spricht gegen RobotClient (nicht direkt gegen HarmonyAdapter)
  Lautstärke-Konflikt: harmony_volume_control flag in elder_berry.json
  In CommandDispatcher registrieren
  TESTS:   tests/test_harmony_commands.py

Schritt 4 – Config-Mock-Server (Rootserver):
  NEU:     src/elder_berry/server/harmony_mock_server.py
  Deploy:  Rootserver, Port 8765
  Nginx:   /etc/nginx/sites-available/harmony-mock (SSL, Proxy)
  DNS:     Pi-hole oder Router: setup.myharmony.com → Rootserver-IP
  Test:    Erst DNS-Override auf Einzelgerät, dann Router-weit
  TESTS:   tests/test_harmony_mock_server.py

Schritt 5 – PWA (Rootserver):
  NEU:     src/elder_berry/webapp/harmony_remote/index.html
  Deploy:  Rootserver, Nginx vhost remote.last-strawberry.com
  API:     Spricht gegen RPi5 :8001/harmony/* (Tower nicht nötig)
```

## 37.1.G – Testliste (~95 Tests)

### test_harmony_adapter.py (~35 Tests)
```
Initialisierung: init_default_path, init_custom_path, load_backup_success,
  load_backup_missing, load_backup_malformed

Verbindung: connect_success, connect_uses_backup_on_failure,
  connect_already_connected, disconnect_clean, is_connected_property

Aktivitäten: start_activity_by_name, start_activity_case_insensitive,
  start_activity_not_found, start_activity_disconnected, power_off,
  get_current_activity_name, get_current_activity_none_on_poweroff,
  list_activities

Gerätebefehle: send_command_success, send_command_device_not_found,
  send_command_unknown_command, send_command_repeat, list_commands,
  list_devices

Intern: find_activity_id_exact, find_activity_id_case_insensitive,
  find_activity_id_not_found, find_device_id_exact,
  find_device_id_case_insensitive, find_device_id_not_found
```

### test_robot_server_harmony.py (~15 Tests)
```
Endpoints gegen TestClient (FastAPI):
  get_status_connected, get_status_disconnected,
  get_config_returns_activities_and_devices,
  post_activity_success, post_activity_not_found_404,
  post_command_success, post_command_device_not_found_404,
  post_command_with_repeat, post_power_off,
  all_endpoints_return_503_when_adapter_not_configured
```

### test_robot_client_harmony.py (~10 Tests)
```
harmony_status_connected, harmony_status_disconnected,
harmony_config_returns_dict, harmony_start_activity_success,
harmony_start_activity_failure, harmony_send_command_success,
harmony_send_command_failure, harmony_power_off,
harmony_methods_handle_connection_error_gracefully
```

### test_harmony_commands.py (~25 Tests)
```
Pattern: activity_on_fernsehen, activity_on_musik, activity_on_gaming,
  activity_on_case_insensitive, all_off_variants,
  volume_up_with_mach, volume_up_bare, volume_down_variants,
  mute_variants, current_pattern_variants,
  list_activities, list_devices, list_commands_with_device

Handler (mit Mock-RobotClient):
  start_activity_success, start_activity_not_found,
  power_off, volume_up, volume_down, mute,
  current_activity_active, current_activity_poweroff,
  no_match_returns_none, robot_client_error_graceful

Kollision: volume_no_collision_with_system_commands,
  activity_no_collision_with_reminder_patterns
```

### test_harmony_mock_server.py (~10 Tests)
```
get_config_returns_backup, save_config_persists,
get_config_after_save_returns_updated, missing_backup_returns_404,
save_config_invalid_json_400,
get_device_info_known_device, get_device_info_unknown_device_404
```

---

# Phase 37.2 – SmartHomeInterface (Plugin/Adapter-Architektur)

## Warum eine Abstraktion

Ohne Interface wäre `SmartHomeCommandHandler` direkt an `HarmonyAdapter` gekoppelt.
Wenn Home Assistant dazukommt, müsste der Handler doppelt geschrieben werden.
Mit Interface: Handler kennt nur `SmartHomeInterface`, Adapter sind austauschbar.

```python
# Ohne Interface (falsch):
class SmartHomeCommandHandler:
    def __init__(self, harmony: HarmonyAdapter, ha: HomeAssistantAdapter):
        # Handler muss beide kennen, kennt Unterschiede, wird riesig

# Mit Interface (richtig):
class SmartHomeCommandHandler:
    def __init__(self, interface: SmartHomeInterface):
        # Handler kennt nur das Interface, egal welche Adapter dahinter
```

## SmartHomeInterface ABC

**Datei**: `src/elder_berry/tools/smart_home_interface.py`

```python
"""SmartHomeInterface – Abstrakte Basis für alle Smart-Home-Adapter.

Alle Adapter (HarmonyAdapter, HomeAssistantAdapter, ...) implementieren dieses
Interface. SmartHomeCommandHandler spricht ausschließlich gegen dieses Interface.

Konzepte:
  Scene:  Benannte Szene / Aktivität (Harmony: "Fernsehen", HA: "Kino-Modus")
  Device: Einzelnes Gerät mit States und Commands
  State:  Aktueller Zustand eines Geräts (on/off, Helligkeit, Temperatur, ...)

Implementierungen registrieren sich in der SmartHomeRegistry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DeviceType(Enum):
    MEDIA    = "media"       # TV, Receiver, Beamer
    LIGHT    = "light"       # Lampen, LED-Strips
    CLIMATE  = "climate"     # Heizung, Klimaanlage
    SWITCH   = "switch"      # Steckdosen, Schalter
    COVER    = "cover"       # Rollläden, Jalousien
    SENSOR   = "sensor"      # Temperatursensor, Bewegungsmelder (read-only)
    GENERIC  = "generic"     # Alles andere


@dataclass(frozen=True)
class DeviceState:
    """Aktueller Zustand eines Geräts."""
    device_id: str
    name: str
    device_type: DeviceType
    is_on: Optional[bool]                    # None wenn nicht anwendbar
    attributes: dict[str, Any] = field(default_factory=dict)
    # z.B. {"brightness": 80, "temperature": 21.5, "volume": 40}


@dataclass(frozen=True)
class SmartDevice:
    """Metadaten eines Geräts (keine Zustandsdaten)."""
    device_id: str
    name: str
    device_type: DeviceType
    adapter_name: str       # z.B. "harmony", "homeassistant"
    available_commands: list[str] = field(default_factory=list)


class SmartHomeInterface(ABC):
    """Abstrakte Basis für alle Smart-Home-Adapter."""

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Eindeutiger Name des Adapters, z.B. 'harmony', 'homeassistant'."""
        ...

    @abstractmethod
    async def connect(self) -> bool:
        """Verbindet mit dem System. True bei Erfolg."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        ...

    # ── Szenen ────────────────────────────────────────────────────────── #

    @abstractmethod
    async def list_scenes(self) -> list[str]:
        """Alle verfügbaren Szenen/Aktivitäten."""
        ...

    @abstractmethod
    async def activate_scene(self, scene_name: str) -> bool:
        """Aktiviert eine Szene. False wenn nicht gefunden."""
        ...

    @abstractmethod
    async def get_current_scene(self) -> Optional[str]:
        """Aktuelle Szene, None wenn keine aktiv."""
        ...

    # ── Geräte ────────────────────────────────────────────────────────── #

    @abstractmethod
    async def list_devices(self) -> list[SmartDevice]:
        """Alle verwalteten Geräte."""
        ...

    @abstractmethod
    async def get_device_state(self, device_id: str) -> Optional[DeviceState]:
        """Zustand eines Geräts."""
        ...

    @abstractmethod
    async def send_command(
        self,
        device_id: str,
        command: str,
        params: dict[str, Any] | None = None,
    ) -> bool:
        """Sendet Befehl an Gerät. False bei Fehler oder Gerät nicht gefunden."""
        ...

    @abstractmethod
    async def turn_on(self, device_id: str, **kwargs: Any) -> bool:
        ...

    @abstractmethod
    async def turn_off(self, device_id: str) -> bool:
        ...
```

## SmartHomeRegistry

**Datei**: `src/elder_berry/tools/smart_home_registry.py`

**Wichtige Architektur-Unterscheidung (Tower vs. RPi5):**

```
Tower (SmartHomeRegistry)
  ├── HarmonyRobotClientProxy  → implements SmartHomeInterface
  │     └── RobotClient.harmony_*() → HTTP → RPi5 → HarmonyAdapter → Hub
  │
  └── HomeAssistantAdapter     → implements SmartHomeInterface
        └── aiohttp → HTTP → HA REST API (direkt, kein RPi5-Umweg)
```

Warum dieser Unterschied:
- Harmony braucht einen IR-Blaster → physisch am RPi5, HarmonyAdapter muss dort laufen
- Home Assistant ist eine reine REST-API → Tower kann direkt sprechen
- `HarmonyRobotClientProxy` ist ein dünner Wrapper: übersetzt SmartHomeInterface-Aufrufe
  in RobotClient-Methoden. Kein Harmony-Protokoll-Wissen auf dem Tower.

```python
"""SmartHomeRegistry – Verwaltet alle registrierten Smart-Home-Adapter.

Adapter auf dem Tower:
  - HarmonyRobotClientProxy (Proxy für RPi5-seitigen HarmonyAdapter)
  - HomeAssistantAdapter (direkte REST-Verbindung)
  - Weitere zukünftige Adapter

Verwendung:
    registry = SmartHomeRegistry()
    registry.register(HarmonyRobotClientProxy(robot_client))
    registry.register(HomeAssistantAdapter(base_url="...", token="..."))
    devices = await registry.list_all_devices()
    adapter, device = await registry.find_device("Receiver")
"""
from __future__ import annotations

from typing import Optional

from elder_berry.tools.smart_home_interface import SmartHomeInterface, SmartDevice


class SmartHomeRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SmartHomeInterface] = {}

    def register(self, adapter: SmartHomeInterface) -> None:
        self._adapters[adapter.adapter_name] = adapter

    def get_adapter(self, name: str) -> Optional[SmartHomeInterface]:
        return self._adapters.get(name)

    @property
    def adapters(self) -> list[SmartHomeInterface]:
        return list(self._adapters.values())

    async def list_all_devices(self) -> list[SmartDevice]:
        """Geräte aus allen verbundenen Adaptern."""
        ...

    async def find_device(
        self, name: str
    ) -> Optional[tuple[SmartHomeInterface, SmartDevice]]:
        """Sucht Gerät in allen Adaptern (case-insensitive)."""
        ...

    async def connect_all(self) -> dict[str, bool]:
        """Verbindet alle Adapter, gibt Status zurück."""
        ...
```

## HarmonyRobotClientProxy (36.2, neu)

**Datei**: `src/elder_berry/tools/harmony_robot_client_proxy.py`

Dünner Wrapper auf dem Tower. Übersetzt SmartHomeInterface in RobotClient-Calls.
Kein aioharmony, kein Hub-Protokollwissen auf dem Tower.

```python
"""HarmonyRobotClientProxy – Tower-seitiger SmartHomeInterface-Adapter für Harmony.

Delegiert alle Aufrufe an RobotClient (→ RPi5 → HarmonyAdapter → Hub).
Implementiert SmartHomeInterface damit der Tower Harmony wie jeden
anderen Adapter behandeln kann.

Datei: src/elder_berry/tools/harmony_robot_client_proxy.py
"""
from elder_berry.tools.smart_home_interface import (
    SmartHomeInterface, SmartDevice, DeviceState, DeviceType
)
from elder_berry.robot.client import RobotClient


class HarmonyRobotClientProxy(SmartHomeInterface):

    def __init__(self, robot_client: RobotClient) -> None:
        self._client = robot_client

    @property
    def adapter_name(self) -> str:
        return "harmony"

    async def connect(self) -> bool:
        status = self._client.harmony_status()
        return status.get("connected", False)

    async def is_connected(self) -> bool:
        return self._client.harmony_status().get("connected", False)

    async def list_scenes(self) -> list[str]:
        return self._client.harmony_config().get("activities", [])

    async def activate_scene(self, scene_name: str) -> bool:
        return self._client.harmony_start_activity(scene_name)

    async def get_current_scene(self) -> str | None:
        return self._client.harmony_status().get("current_activity")

    async def list_devices(self) -> list[SmartDevice]:
        names = self._client.harmony_config().get("devices", [])
        return [
            SmartDevice(
                device_id=name.lower(),
                name=name,
                device_type=DeviceType.MEDIA,
                adapter_name="harmony",
            )
            for name in names
        ]

    async def send_command(self, device_id: str, command: str, params=None) -> bool:
        repeat = (params or {}).get("repeat", 1)
        return self._client.harmony_send_command(device_id, command, repeat)

    async def turn_on(self, device_id: str, **kwargs) -> bool:
        # Harmony hat kein generisches "turn_on" für Geräte —
        # sinnvoll nur über Aktivität. Fallback: letzten Aktivitätsnamen nutzen.
        return False  # Explizit via activate_scene()

    async def turn_off(self, device_id: str) -> bool:
        return self._client.harmony_power_off()

    async def get_device_state(self, device_id: str) -> DeviceState | None:
        # Harmony kennt keinen Gerätezustand (IR ist one-way)
        current = self._client.harmony_status().get("current_activity")
        return DeviceState(
            device_id=device_id,
            name=device_id,
            device_type=DeviceType.MEDIA,
            is_on=current is not None,
            attributes={"current_activity": current},
        )
```

## HarmonyAdapter refaktoriert (36.2)

`HarmonyAdapter` auf dem RPi5 bekommt in Phase 36.2 das `SmartHomeInterface`
als formale Basisklasse — aber nur für Konsistenz und Dokumentation.
Der Tower kommuniziert weiterhin ausschließlich über `RobotClient` /
`HarmonyRobotClientProxy`. Die `SmartHomeInterface`-Implementierung auf
dem RPi5 ist nicht für die Tower-Registry gedacht, sondern für:
- Konsistente Struktur über alle Adapter
- Direkte Nutzung wenn zukünftige Logik auf dem RPi5 selbst läuft

## SmartHomeCommandHandler (36.2)

**Datei**: `src/elder_berry/comms/commands/smart_home_commands.py`

Ersetzt `HarmonyCommandHandler` als einzigen Entry-Point für alle
Smart-Home-Sprachbefehle. Spricht gegen `SmartHomeRegistry`.

```
Pattern-Hierarchie:
  1. Adapter-spezifische Befehle: "harmony status", "ha status"
  2. Szenen/Aktivitäten: "fernsehen an", "kino-modus"
  3. Geräte-Befehle: "mach lauter", "licht an", "rollläden runter"
  4. Globale Befehle: "alles aus", "was ist an"
```

Lautstärke-Kollision mit SystemVolumeHandler: gelöst durch Priorität
(SmartHomeCommandHandler läuft vor SystemVolumeHandler, prüft ob
ein Media-Gerät aktiv ist bevor er matched).

## Testliste Phase 36.2 (~45 Tests)

```
test_smart_home_interface.py (~5):
  interface_is_abstract, cannot_instantiate_without_all_methods

test_smart_home_registry.py (~10):
  register_adapter, get_adapter_by_name, get_unknown_adapter_none,
  list_all_devices_combines_adapters, find_device_exact,
  find_device_case_insensitive, find_device_not_found,
  connect_all_reports_per_adapter, connect_all_partial_failure

test_harmony_robot_client_proxy.py (~15):
  adapter_name_is_harmony, connect_delegates_to_robot_client,
  list_scenes_maps_activities, activate_scene_delegates,
  get_current_scene_active, get_current_scene_none_on_poweroff,
  list_devices_returns_smart_devices_with_media_type,
  send_command_with_repeat, send_command_passes_device_and_command,
  turn_off_calls_power_off, turn_on_returns_false_explicit,
  get_device_state_active, get_device_state_poweroff,
  robot_client_error_propagates_as_false

test_harmony_adapter_interface_conformance.py (~5):
  # Regressions-Tests: HarmonyAdapter erfüllt SmartHomeInterface
  harmony_adapter_is_smart_home_interface,
  all_abstract_methods_implemented,
  list_scenes_returns_list_of_str,
  send_command_signature_matches_interface

test_smart_home_commands.py (~10):
  activity_command_routes_via_registry,
  volume_up_routes_to_harmony_when_active,
  volume_up_falls_through_when_nothing_active,
  all_off_calls_power_off_on_all_adapters,
  what_is_on_collects_from_registry,
  adapter_specific_command_harmony,
  unknown_command_returns_none
```

---

# Phase 37.3 – Home Assistant Adapter

## Übersicht

Home Assistant (HA) läuft auf einem RPi oder als VM im Heimnetz.
Die HA REST API (lokal, kein Cloud-Zugriff) ist vollständig dokumentiert.

**Kann sofort konzeptionell entwickelt werden** — für Tests wird HA gemockt.
Produktiver Einsatz nach Umzug wenn HA-Instanz eingerichtet ist.

## HomeAssistantAdapter

**Datei**: `src/elder_berry/tools/home_assistant_adapter.py`

```python
"""HomeAssistantAdapter – Schnittstelle zu Home Assistant.

Implementiert SmartHomeInterface. Kommuniziert mit HA REST API (lokal).
Kein Cloud-Zugriff, kein Nabu-Casa erforderlich.

Voraussetzung: HA im Heimnetz erreichbar, Long-Lived Access Token.

elder_berry.json:
    "homeassistant_url": "http://192.168.50.Y:8123"
    "homeassistant_token": "eyJ..."

Capability-Mapping (HA-Entities → SmartDevice):
    light.*       → DeviceType.LIGHT      (turn_on mit brightness/color)
    media_player.*→ DeviceType.MEDIA      (volume, play/pause, source)
    climate.*     → DeviceType.CLIMATE    (temperature, hvac_mode)
    switch.*      → DeviceType.SWITCH     (turn_on/off)
    cover.*       → DeviceType.COVER      (open/close/set_position)
    sensor.*      → DeviceType.SENSOR     (state read-only)
    scene.*       → als Szenen in list_scenes()
    script.*      → als Szenen in list_scenes() (ausführbare Skripte)
    automation.*  → als Szenen (trigger-fähig)
"""
from __future__ import annotations
import aiohttp
from elder_berry.tools.smart_home_interface import SmartHomeInterface, SmartDevice, DeviceState, DeviceType

class HomeAssistantAdapter(SmartHomeInterface):

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._session: aiohttp.ClientSession | None = None
        self._connected = False

    @property
    def adapter_name(self) -> str:
        return "homeassistant"

    # Alle Interface-Methoden werden auf HA REST API gemappt:
    # GET  /api/states           → list_devices()
    # POST /api/services/...     → send_command(), turn_on(), turn_off()
    # GET  /api/states/{entity}  → get_device_state()
    # POST /api/services/scene/turn_on → activate_scene()
```

## HA-spezifische Saleria-Commands (36.3)

```
"licht an"                → turn_on("light.wohnzimmer")
"licht aus"               → turn_off("light.wohnzimmer")
"helligkeit 50%"          → send_command("light.X", "set_brightness", {brightness_pct: 50})
"temperatur 21 Grad"      → send_command("climate.X", "set_temperature", {temperature: 21})
"rollläden runter"        → turn_off("cover.X")  (cover: off = closed)
"kino-modus"              → activate_scene("scene.kino_modus")
"ha status"               → get_current_scene() + list connected entities
```

## Testliste Phase 36.3 (~30 Tests)

```
test_home_assistant_adapter.py:
  init_strips_trailing_slash, adapter_name_is_homeassistant,
  connect_success_with_valid_token, connect_fails_with_invalid_token,
  list_devices_maps_entity_types, get_device_state_light,
  get_device_state_media_player, get_device_state_unknown_entity,
  send_command_calls_service_endpoint, turn_on_light, turn_on_with_brightness,
  turn_off_light, turn_on_media_player, set_volume, activate_scene,
  list_scenes_includes_scenes_scripts_automations,
  get_current_scene_returns_active_scene,
  api_error_returns_false_not_exception,
  timeout_returns_false_not_exception,
  entity_unavailable_reflects_in_state
```

---

# Offene Punkte / Entscheidungsbedarf

| Punkt | Optionen | Empfehlung |
|-------|---------|-----------|
| Lautstärke-Kollision | Präfix / Kontext / Config-Flag | Config-Flag `harmony_volume_control` in elder_berry.json |
| Hub-IP statisch | MAC-Reservierung im Router | Vor Schritt 1 erledigen |
| DNS-Override | Pi-hole / Router-DNS | Pi-hole wenn vorhanden, sonst Router-DNS |
| HA-Token-Sicherheit | Plaintext in elder_berry.json vs. secrets.json | Eigene `secrets.json` (gitignored), getrennt von Konfiguration |
| PWA-Zugang | Kein Login / IP-Whitelist / VPN | Nginx `allow 192.168.50.0/24; deny all;` |
| RPi5 Port | :8001 (neben :8000 Tower)? | RPi5 läuft bereits auf :8001 prüfen (steht in robot/server.py) |
| HA-Deployment | Eigener RPi / VM / Container | Entscheidung nach Umzug — adapter ist bereits mockbar |
| Alexa-Emulation | Emulated Hue vs. HA Cloud-Alexa | Emulated Hue (lokal, kein Amazon-Account nötig) |

## Neue Dateien (Gesamtübersicht)

```
RPi5:
  src/elder_berry/robot/harmony_adapter.py         (36.1 — neu)
  src/elder_berry/robot/server.py                  (36.1 — erweitern)
  src/elder_berry/robot/client.py                  (36.1 — erweitern)

Tower (Tools):
  src/elder_berry/tools/smart_home_interface.py    (36.2 — neu, ABC)
  src/elder_berry/tools/smart_home_registry.py     (36.2 — neu)
  src/elder_berry/tools/harmony_robot_client_proxy.py (36.2 — neu)
  src/elder_berry/tools/home_assistant_adapter.py  (36.3 — neu)

Tower (Commands):
  src/elder_berry/comms/commands/harmony_commands.py     (36.1 — neu)
  src/elder_berry/comms/commands/smart_home_commands.py  (36.2 — ersetzt harmony_commands)

Rootserver:
  src/elder_berry/server/harmony_mock_server.py    (36.1 — neu)
  src/elder_berry/webapp/harmony_remote/index.html (36.1 — neu, PWA)

Tests:
  tests/test_harmony_adapter.py                    (36.1)
  tests/test_robot_server_harmony.py               (36.1)
  tests/test_robot_client_harmony.py               (36.1)
  tests/test_harmony_commands.py                   (36.1)
  tests/test_harmony_mock_server.py                (36.1)
  tests/test_smart_home_interface.py               (36.2)
  tests/test_smart_home_registry.py                (36.2)
  tests/test_harmony_robot_client_proxy.py         (36.2)
  tests/test_harmony_adapter_interface_conformance.py (36.2)
  tests/test_smart_home_commands.py                (36.2)
  tests/test_home_assistant_adapter.py             (36.3)
```

Gesamttests Phase 36: ~170 (36.1: ~95, 36.2: ~45, 36.3: ~30)

---

# Phase 37.4 – Alexa-Integration (Platzhalter)

## Kontext

Alexa wird täglich für Heimsteuerung genutzt ("Alexa schalte Kronleuchter ein",
"schalte Fernseher ein"). Aktuell läuft das über Logitech-Cloud (Harmony) und
direkte Geräte-Skills. Nach Phase 36.1–36.3 soll Alexa gegen die eigene
Infrastruktur sprechen — lokal, ohne Logitech-Cloud, ohne herstellerspezifische Skills.

## Abhängigkeiten

- **36.1 muss abgeschlossen sein**: Harmony läuft lokal auf RPi5
- **36.3 sollte abgeschlossen sein**: HA ist der natürliche Alexa-Unterbau
- **Umzug muss erfolgt sein**: HA-Instanz muss stabil laufen

## Technischer Ansatz: Emulated Hue

Der RPi5 gibt sich gegenüber Alexa als Philips-Hue-Bridge aus.
Alexa entdeckt ihn automatisch im lokalen Netzwerk (UPnP-Discovery).
Geräte und Szenen erscheinen als Hue-Lampen — Alexa kann sie
ein-/ausschalten ohne Cloud-Verbindung zu Drittanbietern.

```
Alexa → (UPnP Discovery) → RPi5 :80 (Emulated Hue API)
      → "schalte Fernseher ein"
      → RPi5 → HarmonyAdapter → Hub → IR → TV

Alexa → "schalte Kronleuchter ein"
      → RPi5 → HomeAssistantAdapter → HA → Zigbee/Z-Wave → Lampe
```

## Alternativer Ansatz: HA Cloud + Alexa Skill

Home Assistant hat einen offiziellen Alexa-Skill über Nabu Casa (kostenpflichtig,
~7€/Monat) oder selbst-gehostete HA Cloud. Vorteil: volle HA-Entity-Unterstützung
inklusive Dimmen, Farbtemperatur, Szenen. Nachteil: erfordert externe Erreichbarkeit
des HA-Servers (HTTPS, Port-Forwarding oder Nabu Casa).

**Empfehlung**: Emulated Hue für einfache Ein/Aus-Befehle, HA Cloud-Option
wenn Dimmen und komplexere Szenen gebraucht werden.

## Was implementiert werden muss (Phase 36.4)

```
Auf RPi5:
  - Emulated Hue Server (Python: phue-emulator oder aiohue-emulator)
  - Device-Registry: welche HA-Entities / Harmony-Aktivitäten als
    "Hue-Lampen" erscheinen sollen
  - Mapping: Alexa-Gerätename → SmartHomeInterface-Befehl

Konfiguration (elder_berry.json auf RPi5):
  "alexa_devices": {
    "Kronleuchter":   {"adapter": "homeassistant", "entity": "light.kronleuchter"},
    "Fernseher":      {"adapter": "harmony",        "activity": "Fernsehen"},
    "Musik":          {"adapter": "harmony",        "activity": "Musik"}
  }
```

## Testliste Phase 36.4 (~20 Tests, noch nicht ausgearbeitet)

```
- UPnP-Discovery antwortet korrekt
- Alexa-Gerät erscheint nach Discovery
- turn_on mappt auf korrekten Adapter-Befehl
- turn_off mappt auf korrekten Adapter-Befehl
- Unbekanntes Gerät: 404
- Mapping aus elder_berry.json wird korrekt geladen
- Konfigurationsänderung ohne Neustart wirksam
```

## Hinweis

Phase 36.4 ist bewusst nicht ausgearbeitet — Implementierungsdetails
hängen von der HA-Instanz und dem konkreten Gerätepark nach dem Umzug ab.
Das Konzept wird in einem eigenen Chat ausgearbeitet wenn 36.3 abgeschlossen ist.
