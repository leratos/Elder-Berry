# SSH Reverse Tunnels

> **Zweck:** Lokale Services (Tower-Dashboard, RPi-API) über einen externen
> Server erreichbar machen, ohne dass die Geräte eine öffentliche IP brauchen.
>
> **Richtung:** Client → Server (Reverse Tunnel)
> **Ergebnis:** Server `127.0.0.1:<REMOTE_PORT>` → Client `127.0.0.1:<LOCAL_PORT>`

---

## Übersicht

```
Tower (Windows 11)                    Rootserver                      RPi5 (Linux)
┌──────────────────┐     SSH Tunnel   ┌──────────────────┐  SSH Tunnel  ┌──────────────────┐
│ Dashboard :LOCAL │ ──────────────── │ :PORT_A (lo)     │ ──────────── │ FastAPI :LOCAL    │
└──────────────────┘  -R PORT_A:LOCAL │ :PORT_B (lo)     │ -R PORT_B   └──────────────────┘
                                      └──────────────────┘
                                              │
                                        Nginx Reverse Proxy
                                              │
                                        https://...
```

Beide Tunnel sind unabhängig – jedes Gerät baut seinen eigenen auf.

---

## 1. SSH-Key einrichten (Voraussetzung)

Die Tunnel laufen unbeaufsichtigt (kein Passwort-Prompt). Dafür muss auf
jedem Gerät ein SSH-Key erzeugt und beim Server hinterlegt werden.

### Tower (Windows 11)

```powershell
# Key erzeugen (falls noch keiner existiert):
ssh-keygen -t ed25519 -C "tower"
# → Enter bei allen Fragen (kein Passphrase für unbeaufsichtigten Betrieb)

# Key auf dem Server hinterlegen:
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh <USER>@<SERVER> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

> **Hinweis:** Windows hat kein `ssh-copy-id`. Der `type ... | ssh`-Einzeiler
> ist das Äquivalent.

### RPi5 (Linux)

```bash
# Key erzeugen (falls noch keiner existiert):
ssh-keygen -t ed25519 -C "rpi5"
# → Enter bei allen Fragen (kein Passphrase)

# Key auf dem Server hinterlegen:
ssh-copy-id <USER>@<SERVER>
```

### Testen (beide Geräte)

```bash
ssh -o BatchMode=yes <USER>@<SERVER> "echo OK"
# Muss "OK" ausgeben ohne Passwort-Abfrage.
# Falls Passwort-Prompt kommt: Key nicht korrekt hinterlegt.
```

---

## 2. Server-Seite härten (sshd_config)

SSH auf dem Server so konfigurieren, dass tote Verbindungen schnell erkannt
und der blockierte Port freigegeben wird.

```bash
ssh <USER>@<SERVER>
sudo nano /etc/ssh/sshd_config
```

Prüfen ob folgende Werte gesetzt sind (ist bei den meisten Linux-Distributionen
bereits der Default):

```ini
ClientAliveInterval 30
ClientAliveCountMax 3
```

Das bedeutet: alle 30s ein Keepalive, nach 3 fehlgeschlagenen Versuchen
(= 90s) wird die Session gekillt und der Port freigegeben.

**Wichtig:** Prüfe dass keine `Match`-Blöcke am Ende der Datei diese Werte
überschreiben.

### Verifizieren

```bash
sudo sshd -T | grep -i clientalive
# Erwartete Ausgabe:
# clientaliveinterval 30
# clientalivecountmax 3
```

Falls die Werte anders sind, anpassen und SSH neustarten:

```bash
sudo sshd -t               # Syntax-Check (keine Ausgabe = OK)
sudo systemctl restart sshd
```

> **Warum wichtig?** Ohne Keepalives bleibt bei Netzwerk-Abbruch die alte
> SSH-Session als Zombie auf dem Server. Der Remote-Port bleibt belegt,
> und der Client bekommt "remote port forwarding failed" beim Reconnect.
> Mit den obigen Werten erkennt der Server nach max. 90 Sekunden dass
> die Verbindung tot ist und gibt den Port frei.

---

## 3. Tower (Windows 11): Auto-Reconnect

### Manuell starten (Test)

```powershell
ssh -N -R 127.0.0.1:<REMOTE_PORT>:127.0.0.1:<LOCAL_PORT> `
    -o ServerAliveInterval=15 `
    -o ServerAliveCountMax=3 `
    -o ExitOnForwardFailure=yes `
    <USER>@<SERVER>
```

### Auto-Reconnect Script

Das Script `scripts/ssh-tunnel.ps1` überwacht den Tunnel und baut ihn
bei Abbruch automatisch neu auf:

- **Exponential Backoff:** 5s → 10s → 20s → ... → max 120s
- **Reset** bei erfolgreichem Reconnect
- **Logging** nach `logs/ssh-tunnel.log`

Einrichtung:

```powershell
# 1. Example-Dateien kopieren
Copy-Item scripts\ssh-tunnel.example.ps1 scripts\ssh-tunnel.ps1
Copy-Item scripts\Install-SshTunnelTask.example.ps1 scripts\Install-SshTunnelTask.ps1

# 2. Config in ssh-tunnel.ps1 anpassen (die ersten 4 Variablen):
#    $RemoteUser  = "your-user"
#    $RemoteHost  = "your-server.com"
#    $RemotePort  = 12345
#    $LocalPort   = 8080

# 3. Starten:
powershell -ExecutionPolicy Bypass -File scripts\ssh-tunnel.ps1
```

> **Hinweis:** Die `.example.ps1`-Dateien werden committed (generisch,
> ohne Zugangsdaten). Die kopierten `.ps1`-Dateien sind in `.gitignore`
> und werden nicht ins Repo aufgenommen.

### Als Scheduled Task installieren (Autostart bei Login)

```powershell
# Erhöhte PowerShell (Als Administrator ausführen):
powershell -ExecutionPolicy Bypass -File scripts\Install-SshTunnelTask.ps1
```

Das erstellt einen Scheduled Task mit:

| Einstellung        | Wert                          |
| ------------------ | ----------------------------- |
| Trigger            | Bei Anmeldung                 |
| Restart bei Fehler | Alle 60s, bis zu 999×         |
| Batterie           | Läuft auch im Akkubetrieb     |
| Zeitlimit          | Keins (läuft dauerhaft)       |

**Task verwalten:**

```powershell
# Status prüfen
Get-ScheduledTask -TaskName "Elder-Berry SSH Tunnel" | Get-ScheduledTaskInfo

# Jetzt starten
Start-ScheduledTask -TaskName "Elder-Berry SSH Tunnel"

# Stoppen
Stop-ScheduledTask -TaskName "Elder-Berry SSH Tunnel"

# Entfernen
Unregister-ScheduledTask -TaskName "Elder-Berry SSH Tunnel"
```

---

## 4. RPi5 (Linux): Auto-Reconnect via systemd

Der RPi baut einen eigenen Tunnel auf, damit der Server die RPi-API
(z.B. Avatar, Update-Endpoint) erreichen kann.

### Manuell testen

```bash
ssh -N -R 127.0.0.1:<REMOTE_PORT>:127.0.0.1:<LOCAL_PORT> \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    <USER>@<SERVER>
```

### systemd Service einrichten

```bash
sudo nano /etc/systemd/system/ssh-tunnel.service
```

Inhalt (Platzhalter anpassen):

```ini
[Unit]
Description=SSH Reverse Tunnel to Rootserver
After=network-online.target
Wants=network-online.target
# Max 50 Restarts innerhalb von 10 Minuten, danach stoppt systemd den Service
StartLimitIntervalSec=600
StartLimitBurst=50

[Service]
Type=simple
User=pi
ExecStart=/usr/bin/ssh -N \
    -R 127.0.0.1:<REMOTE_PORT>:127.0.0.1:<LOCAL_PORT> \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o ConnectTimeout=10 \
    -o BatchMode=yes \
    <USER>@<SERVER>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Aktivieren und starten:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ssh-tunnel     # Autostart beim Booten
sudo systemctl start ssh-tunnel      # Jetzt starten
sudo systemctl status ssh-tunnel     # Status prüfen
sudo journalctl -u ssh-tunnel -f     # Live-Logs
```

> **Vorteil gegenüber einem Wrapper-Script:** systemd übernimmt Restart,
> Logging (journalctl), Boot-Autostart und Prozess-Überwachung nativ.
> Kein zusätzliches Script nötig.

---

## 5. Troubleshooting

| Problem | Ursache | Lösung |
| --- | --- | --- |
| `remote port forwarding failed` | Zombie-Prozess blockiert den Port | Warten (max 90s) oder auf Server: `ss -tlnp \| grep <PORT>` → `kill <PID>` |
| Tunnel baut sich nicht auf | DNS/Routing noch nicht bereit | Script/systemd hat Restart, wartet automatisch |
| `Connection refused` | Server-SSH nicht erreichbar | Netzwerk prüfen, `ping <SERVER>` |
| `Permission denied (publickey)` | SSH-Key nicht hinterlegt | Siehe Abschnitt 1 (SSH-Key einrichten) |
| `Host key verification failed` | Server-Key geändert | `ssh-keygen -R <SERVER>` und neu verbinden |
| RPi-Tunnel startet nicht beim Booten | Service nicht enabled | `sudo systemctl enable ssh-tunnel` |
| Tower Scheduled Task startet nicht | Nicht als Admin installiert | Install-Script als Admin ausführen |
| Log wird zu groß (Tower) | Kein Log-Rotation | `logs/ssh-tunnel.log` manuell löschen |

---

## 6. Manuelle Zombie-Bereinigung (Notfall)

Falls der Port trotzdem blockiert bleibt:

```bash
# Auf dem Server:
ss -tlnp | grep <REMOTE_PORT>
# Zeigt die PID des blockierenden Prozesses

# Prozess killen:
kill <PID>

# Oder alle SSH-Sessions des Users auflisten:
who | grep <USER>
```
