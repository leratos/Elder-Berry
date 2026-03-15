# RPi5 Setup-Anleitung (Headless)

> **Hardware:** Raspberry Pi 5 (4GB)
> **OS:** Raspberry Pi OS Lite (64-bit, Bookworm)
> **Hostname:** elderberry
> **Zweck:** I/O-Controller für Elder-Berry (Sensoren, Motoren, Avatar-Display)
> **Erstellt:** 2026-03-15

---

## Schritt 1 – Image flashen (Tower)

### 1.1 Raspberry Pi Imager öffnen
- Download (falls nötig): https://www.raspberrypi.com/software/
- Version: v2.0.6+

### 1.2 Einstellungen im Imager
- **Device:** Raspberry Pi 5
- **OS:** Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**
- **Storage:** microSD-Karte (min. 32GB, A2 Class 10)

### 1.3 Customization (Zahnrad / "Edit Settings" – VOR dem Flashen!)

| Einstellung | Wert |
|------------|------|
| Hostname | `elderberry` |
| Enable SSH | ✅ An, Password Authentication |
| Username | `pi` |
| Password | (sicheres Passwort wählen) |
| Configure WLAN | ✅ An |
| WLAN SSID | (dein WLAN-Name) |
| WLAN Password | (dein WLAN-Passwort) |
| WLAN Country | DE |
| Timezone | Europe/Berlin |
| Keyboard Layout | de |

### 1.4 Flashen
- "Write" klicken → warten → microSD entnehmen

### 1.5 Erster Boot
- microSD in RPi5 stecken
- Stromversorgung anschließen (USB-C, 5V/5A empfohlen)
- ~60 Sekunden warten (erster Boot dauert länger)

## Schritt 2 – SSH-Verbindung (Tower)

```powershell
ssh pi@elderberry.local
```

Falls `elderberry.local` nicht aufgelöst wird:
- Im Router nachschauen welche IP der RPi5 bekommen hat
- `ssh pi@192.168.x.x` direkt verwenden
- Oder: `ping elderberry.local` testen

> **Tipp:** Beim ersten Verbinden kommt eine Fingerprint-Warnung → mit `yes` bestätigen.

## Schritt 3 – System-Update

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

Nach Reboot (~30 Sekunden) erneut per SSH verbinden.

## Schritt 4 – Python prüfen

```bash
python3 --version
# Ergebnis: Python 3.13.5 (Bookworm aktuell)
```

Python 3.13 ist neuer als auf Tower/Laptop (3.12). Das ist okay –
RPi5 läuft anderen Code (RobotServer), 3.13 ist rückwärtskompatibel.

```bash
sudo apt install -y python3-venv python3-dev
```

## Schritt 5 – Basis-Packages installieren

```bash
sudo apt install -y \
  git \
  python3-pip \
  python3-venv \
  python3-dev \
  i2c-tools \
  libopenblas-dev \
  ffmpeg \
  curl \
  htop
```

- `i2c-tools`: für Motor HAT (I²C) Diagnose
- `libopenblas-dev`: numpy/scipy Support (ersetzt libatlas-base-dev auf Bookworm 2025+)
- `ffmpeg`: Audio-Konvertierung (Matrix Phase 6)

## Schritt 6 – I²C aktivieren (für Motor HAT)

```bash
sudo raspi-config
```

→ **Interface Options** → **I2C** → **Enable** → Finish → Reboot

Prüfen:
```bash
sudo i2cdetect -y 1
# Sollte leere Tabelle zeigen (noch kein HAT angeschlossen)
```

## Schritt 7 – Statische IP einrichten (optional aber empfohlen)

Damit der Tower den RPi5 immer unter derselben IP findet:

```bash
sudo nmcli con show
# Zeigt WLAN-Verbindung, Name merken (z.B. "preconfigured")

sudo nmcli con mod "preconfigured" \
  ipv4.method manual \
  ipv4.addresses 192.168.50.220/24 \
  ipv4.gateway 192.168.50.1 \
  ipv4.dns "192.168.50.1"

sudo reboot
```

> **WICHTIG:** IP-Adressen an dein Netzwerk anpassen!
> - `192.168.50.220` = gewünschte feste IP für RPi5
> - `192.168.50.1` = dein Router (Asusrouter typisch)
> - Nach Reboot: `ssh pi@192.168.50.220`

## Schritt 8 – Projekt-Verzeichnis + venv

```bash
mkdir -p /home/pi/elder-berry
cd /home/pi/elder-berry

# venv erstellen (Python 3.13)
python3 -m venv .venv

# Aktivieren
source .venv/bin/activate

# pip upgraden
pip install --upgrade pip setuptools wheel

# Prüfen
python --version
pip --version
```

## Schritt 9 – SSH-Key (optional, empfohlen)

Auf dem **Tower** (PowerShell):
```powershell
# Falls noch kein Key existiert:
ssh-keygen -t ed25519 -C "elder-berry-tower"

# Key auf RPi5 kopieren (Windows hat kein ssh-copy-id):
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh pi@192.168.50.220 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Danach: SSH ohne Passwort möglich.

## Schritt 10 – Firewall (optional)

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 8000/tcp    # FastAPI RobotServer
sudo ufw enable
sudo ufw status
```

## Schritt 11 – Verifizierung

Checkliste – alles muss grün sein:

```
[ ] SSH-Verbindung funktioniert (pi@elderberry.local oder IP)
[ ] python3 --version → 3.11+ (idealerweise 3.12)
[ ] pip --version (im venv)
[ ] git --version
[ ] i2cdetect -y 1 → keine Fehler
[ ] ffmpeg -version → installiert
[ ] Statische IP vergeben (optional)
[ ] SSH-Key eingerichtet (optional)
[ ] Firewall aktiv (optional)
```

---

## Troubleshooting

### RPi5 nicht im Netzwerk gefunden
- WLAN-Daten beim Flashen korrekt eingegeben?
- 5GHz vs. 2.4GHz: RPi5 unterstützt beides, aber manche Router trennen
- microSD nochmal im Imager flashen mit korrekten WLAN-Daten

### SSH "Connection refused"
- RPi5 noch nicht fertig gebootet → 60-90 Sekunden warten
- SSH nicht aktiviert → microSD nochmal flashen mit SSH-Option

### "Host key verification failed"
- Alte Einträge löschen: `ssh-keygen -R elderberry.local`
- Oder: `ssh-keygen -R 192.168.50.220`

### Python-Version
- Aktuelles Bookworm liefert Python 3.13 (nicht 3.12 wie Tower/Laptop)
- Das ist okay – RPi5 läuft anderen Code, 3.13 ist rückwärtskompatibel
- Falls Kompatibilitätsprobleme: pyenv oder deadsnakes PPA (aber auf ARM nicht immer verfügbar)

### Statische IP funktioniert nicht nach Reboot
```bash
# Status prüfen:
nmcli con show "preconfigured"
# Falls zurückgesetzt: NetworkManager Config prüfen
sudo nmcli general status
```

---

## Nächste Schritte nach Setup

1. Elder-Berry Code auf RPi5 deployen (Phase 2 Robot-Server)
2. Display anschließen (DSI, wenn Hardware da)
3. Motor HAT + Motoren testen
4. Kamera-Modul anschließen + testen
