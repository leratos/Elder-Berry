# SSH Reverse Tunnel – Tower → Rootserver

> **Zweck:** Ein lokales Web-Interface (z.B. Dashboard) über einen externen
> Server erreichbar machen, ohne dass der Tower eine öffentliche IP braucht.
>
> **Richtung:** Tower → Server (Reverse Tunnel)
> **Ergebnis:** Server `127.0.0.1:<REMOTE_PORT>` → Tower `127.0.0.1:<LOCAL_PORT>`

---

## Übersicht

```
Tower (Windows 11)                    Rootserver
┌──────────────────┐     SSH Tunnel   ┌──────────────────┐
│ Service :LOCAL   │ ──────────────── │ :REMOTE (lo)     │
└──────────────────┘  -R REMOTE:LOCAL └──────────────────┘
                                              │
                                        Nginx Reverse Proxy
                                              │
                                        https://...
```

---

## 1. Server-Seite härten (sshd_config)

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

> **Warum wichtig?** Ohne Keepalives bleibt bei VPN-/Netzwerk-Abbruch
> die alte SSH-Session als Zombie auf dem Server. Der Remote-Port bleibt
> belegt, und der Client bekommt "remote port forwarding failed" beim
> Reconnect-Versuch. Mit den obigen Werten erkennt der Server nach
> max. 90 Sekunden dass die Verbindung tot ist und gibt den Port frei.

---

## 2. Tower-Seite: Tunnel mit Auto-Reconnect

### Voraussetzungen

- Windows 11 OpenSSH Client (ist standardmäßig installiert)
- SSH-Key beim Server hinterlegt (`ssh-copy-id <USER>@<SERVER>`)
- **Kein Passwort-Prompt** – der Tunnel läuft unbeaufsichtigt

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

| Einstellung | Wert |
|---|---|
| Trigger | Bei Anmeldung |
| Restart bei Fehler | Alle 60s, bis zu 999× |
| Batterie | Läuft auch im Akkubetrieb |
| Zeitlimit | Keins (läuft dauerhaft) |

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

## 3. Troubleshooting

| Problem | Ursache | Lösung |
|---|---|---|
| `remote port forwarding failed` | Alter Zombie-Prozess blockiert den Port | Warten (max 45s nach sshd-Härtung) oder auf Server: `ss -tlnp \| grep <PORT>` und ggf. `kill <PID>` |
| Tunnel baut sich nicht auf nach VPN-Reconnect | DNS/Routing noch nicht bereit | Script hat Backoff, wartet automatisch |
| `Connection refused` | Server-SSH nicht erreichbar | VPN/Netzwerk prüfen, `ping <SERVER>` |
| `Permission denied (publickey)` | SSH-Key nicht hinterlegt | `ssh-copy-id <USER>@<SERVER>` |
| Log wird zu groß | Kein Log-Rotation | Manuell löschen oder Logfile in `.gitignore` |
| Scheduled Task startet nicht | Nicht als Admin installiert | Install-Script als Admin ausführen |

---

## 4. Manuelle Zombie-Bereinigung (Notfall)

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
