# RPi5 Einrichtung

> **Hardware:** Raspberry Pi 5 (4 GB)
> **OS:** Raspberry Pi OS Lite (64-bit, Bookworm)
> **Hostname:** elderberry
> **Zweck:** Avatar-Display, Kamera, Drehteller für Elder-Berry

Der RPi5 ist der "Körper" von Saleria – er steuert das Pepper's Ghost Hologramm-Display,
die Kamera und den Drehteller. Der Tower kommuniziert via REST API (FastAPI, Port 8000).

---

## Headless-Setup

### 1. Image flashen

- **Raspberry Pi Imager** öffnen ([Download](https://www.raspberrypi.com/software/))
- **Device:** Raspberry Pi 5
- **OS:** Raspberry Pi OS Lite (64-bit)
- **Customization** (vor dem Flashen):

| Einstellung | Wert |
|---|---|
| Hostname | `elderberry` |
| Enable SSH | An (Password Authentication) |
| Username | `pi` |
| WLAN SSID/Password | (dein WLAN) |
| WLAN Country | DE |
| Timezone | Europe/Berlin |

### 2. Erster Boot + SSH

```bash
# ~60 Sekunden warten, dann:
ssh pi@elderberry.local
# Oder direkt per IP: ssh pi@192.168.x.x
```

### 3. System-Update

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### 4. Basis-Pakete

```bash
sudo apt install -y \
  git python3-pip python3-venv python3-dev \
  i2c-tools libopenblas-dev ffmpeg curl htop
```

### 5. I2C aktivieren (für Stepper-Motor)

```bash
sudo raspi-config
# → Interface Options → I2C → Enable → Finish → Reboot
```

### 6. GPU-Zugriff & Display-Rotation

```bash
# User muss in video/render-Gruppe sein (für kmsdrm/DRM-Framebuffer)
sudo usermod -aG video,render pi
```

Das DSI-Display ist im Gehäuse baulich um 180° verdreht eingebaut
(Flachband-Führung). Die Drehung passiert **im Render**, nicht in der
Firmware:

```bash
python scripts/start_rpi5.py --rotation 180   # Default
python scripts/start_rpi5.py --rotation 0     # falls Hardware-Einbau wechselt
```

> **Warum nicht `display_lcd_rotate=`?**
> Auf RPi5 mit `vc4-kms-v3d`-Treiber (Default seit Bookworm) wird
> `display_lcd_rotate=` in `/boot/firmware/config.txt` **ignoriert**.
> Die Option stammt aus der Legacy-Firmware-Pipeline und greift im
> KMS-Modus nicht. Wenn pygame ausserhalb eines Compositors läuft
> (`XDG_SESSION_TYPE=tty`), gibt es auch keinen Compositor, der die
> Rotation übernehmen könnte. Daher wird die Drehung über
> `pygame.transform.flip()` direkt im Render-Loop gemacht
> (siehe `LayeredSpriteRenderer.update()`).
>
> Unterstützte Werte: `0` und `180`. `90`/`270` sind nicht
> implementiert (würden Width/Height-Tausch und Buffer-Refactor
> erfordern und werden im Pepper's-Ghost-Setup nicht gebraucht).

Für Autostart per systemd: `--rotation 180` an die `ExecStart`-Zeile
hängen oder Default beibehalten (RPi5AvatarDisplay nutzt 180° als
Default).

### 7. Statische IP (empfohlen)

```bash
sudo nmcli con mod "preconfigured" \
  ipv4.method manual \
  ipv4.addresses 192.168.50.220/24 \
  ipv4.gateway 192.168.50.1 \
  ipv4.dns "192.168.50.1"
sudo reboot
```

IP-Adressen an dein Netzwerk anpassen!

---

## Elder-Berry installieren

```bash
cd /home/pi/Elder-Berry
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[robot,avatar]"
pip install pygame-ce  # WICHTIG: Standard-pygame hat kein kmsdrm auf Bookworm Lite!
```

> **Warum pygame-ce?** RPi OS Lite (Bookworm) liefert SDL2 ohne kmsdrm/fbcon/x11-Backend —
> nur `dummy` funktioniert. `pygame-ce` (Community Edition) bringt eine eigene SDL2 mit
> kmsdrm-Support mit. Gleiche API, Drop-in Replacement, kein Code-Änderung nötig.

---

## Avatar-Display starten

### Manuell

```bash
SDL_VIDEODRIVER=kmsdrm python scripts/start_rpi5.py              # Fullscreen (DSI)
SDL_VIDEODRIVER=kmsdrm python scripts/start_rpi5.py --windowed   # Debug
```

### Autostart (systemd)

```bash
sudo nano /etc/systemd/system/elder-berry.service
```

```ini
[Unit]
Description=Elder-Berry Avatar Display
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Elder-Berry
ExecStart=/home/pi/Elder-Berry/.venv/bin/python scripts/start_rpi5.py
Restart=on-failure
RestartSec=5
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=DISPLAY=:0

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable elder-berry    # Autostart beim Booten
sudo systemctl start elder-berry     # Jetzt starten
sudo systemctl status elder-berry    # Status prüfen
sudo journalctl -u elder-berry -f    # Live-Logs
```

---

## Tower-Verbindung

Auf dem Tower den RPi5 im SecretStore registrieren:

```python
from elder_berry.core.secret_store import SecretStore
SecretStore().set("robot_host", "http://192.168.50.220:8000")
```

Der Tower steuert den Avatar dann automatisch via `RobotClient`:

- LLM-Emotion → `POST /avatar/emotion` → Display wechselt Ausdruck
- TTS-Sprechen → Lip-Sync auf dem Display
- Health-Check → `GET /health`

## SSH Reverse Tunnel (RPi → Rootserver)

Der RPi baut einen SSH Reverse Tunnel zum Rootserver auf, damit dieser die
RPi-API erreichen kann (z.B. für `update rpi` via Matrix). Ohne Tunnel
wäre der RPi nur im lokalen Netzwerk erreichbar.

Vollständige Anleitung (SSH-Key-Setup, sshd-Härtung, systemd Service):
→ **[docs/ssh-tunnel.md](ssh-tunnel.md)**, Abschnitte 1, 2 und 4.

Kurzfassung:

```bash
# 1. SSH-Key erzeugen + beim Server hinterlegen (einmalig)
ssh-keygen -t ed25519 -C "rpi5"
ssh-copy-id <USER>@<SERVER>

# 2. Testen (muss ohne Passwort durchgehen)
ssh -o BatchMode=yes <USER>@<SERVER> "echo OK"

# 3. systemd Service anlegen
sudo nano /etc/systemd/system/ssh-tunnel.service
# → Inhalt siehe docs/ssh-tunnel.md Abschnitt 4

# 4. Aktivieren
sudo systemctl daemon-reload
sudo systemctl enable --now ssh-tunnel
```

## Harmony Hub (Phase 37.1)

Der RPi5 steuert den Harmony Hub direkt per WebSocket — ohne Logitech-Cloud.

### 1. aioharmony installieren

```bash
source /home/pi/Elder-Berry/.venv/bin/activate
pip install aioharmony
```

### 2. Config-Datei bereitstellen

Die Config wurde vom Tower aus dem Hub exportiert und liegt im Repo unter
`config/harmony_config_backup.json`. Sie muss auf den RPi5 kopiert werden:

```bash
mkdir -p /home/pi/.elder-berry
# Vom Tower kopieren (einmalig):
scp user@<tower-ip>:/c/Dev/Elder-Berry/config/harmony_config_backup.json \
    /home/pi/.elder-berry/harmony_config.json
```

### 3. Verbindung testen

```bash
source /home/pi/Elder-Berry/.venv/bin/activate
python -c "
import asyncio
from aioharmony.harmonyapi import HarmonyAPI
async def test():
    h = HarmonyAPI('192.168.50.133')
    if await h.connect():
        print('OK — aktive Aktivität:', await h.get_current_activity())
        await h.close()
    else:
        print('FEHLER: Hub nicht erreichbar')
asyncio.run(test())
"
```

### 4. Endpoint prüfen

Nach Neustart des elder-berry Services sollte der Harmony-Endpoint antworten:

```bash
curl http://localhost:8000/harmony/status
```

> **Hinweis:** Der Hub hat die feste IP `192.168.50.133` (per MAC-Reservierung im Router).
> Falls sich die IP ändert, muss sie im SecretStore (`harmony_hub_ip`) angepasst werden.

---

## Remote-Update via Matrix

Vom Handy aus (Element):

- `update rpi` — Git Pull + pip install + systemctl restart
- `update alles` — Tower + RPi5 nacheinander

---

## Troubleshooting

| Problem | Lösung |
|---|---|
| RPi5 nicht im Netzwerk | WLAN-Daten beim Flashen prüfen, 5 GHz vs. 2.4 GHz |
| SSH "Connection refused" | 60-90s warten, SSH beim Flashen aktiviert? |
| "Host key verification failed" | `ssh-keygen -R elderberry.local` |
| Display bleibt schwarz | `SDL_VIDEODRIVER=kmsdrm` gesetzt? DSI-Kabel prüfen |
| `kmsdrm not available` | `pygame-ce` statt `pygame` installiert? `pip install pygame-ce` |
| Display steht Kopf | `python scripts/start_rpi5.py --rotation 180` (Default) -- nicht `display_lcd_rotate=`, das wirkt auf RPi5/KMS nicht |
| `Permission denied` auf Display | `sudo usermod -aG video,render pi` + neu einloggen |
| Statische IP geht nicht | `nmcli con show "preconfigured"` prüfen |
| Harmony Hub nicht erreichbar | Hub-IP `192.168.50.133` anpingen, WLAN-Netz identisch? |
| `aioharmony` Import-Fehler | `pip install aioharmony` im venv vergessen? |
| `/harmony/status` 404 | Git-Stand aktuell? `git pull` + `pip install -e ".[robot,avatar]"` |
| Harmony Config fehlt | `harmony_config.json` nach `/home/pi/.elder-berry/` kopieren |
