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

### 6. Statische IP (empfohlen)

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
cd /home/pi/elder-berry
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[robot,avatar]"
pip install pygame-ce
```

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
WorkingDirectory=/home/pi/elder-berry
ExecStart=/home/pi/elder-berry/.venv/bin/python scripts/start_rpi5.py
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
| Statische IP geht nicht | `nmcli con show "preconfigured"` prüfen |
