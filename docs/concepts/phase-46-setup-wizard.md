# Phase 46 – Setup-Wizard (Installationsassistent)

## Ziel

Ein neuer Nutzer kann Elder-Berry von Null aufsetzen: Bootstrap-Script für
die Systeminstallation, dann ein Web-Wizard der Schritt für Schritt alle
Dienste konfiguriert, jede Verbindung testet und am Ende eine funktionierende
Saleria-Instanz liefert.

**Voraussetzungen (extern, nicht Teil des Wizards):**
- Nextcloud-Instanz (self-hosted oder Hoster) – Wizard verlinkt Hilfeseite
- Matrix/Synapse-Server – Wizard verlinkt Hilfeseite
- Windows PC mit Python 3.12+ und Git

## Zwei Stufen

### Stufe 1: Bootstrap-Script (`install.ps1` / `install.sh`)

Einmaliges Script das den Rechner vorbereitet:

```powershell
# install.ps1 (Windows)
# 1. Repository klonen
git clone https://github.com/<user>/Elder-Berry.git C:\Dev\Elder-Berry
cd C:\Dev\Elder-Berry

# 2. Python-venv erstellen
py -3.12 -m venv .venv
.venv\Scripts\activate

# 3. Abhängigkeiten installieren
pip install -e ".[windows,tts-neural,avatar,matrix,remote,memory,stt]"

# 4. Ollama prüfen/installieren (optional)
# → Hinweis: "Installiere Ollama von https://ollama.com für Offline-LLM"

# 5. Setup-Wizard starten
python scripts/setup_wizard.py
# → Öffnet http://localhost:8090/setup im Browser
```

### Stufe 2: Web-Wizard (`/setup`)

Ein mehrstufiger Wizard im Browser der durch alle Konfigurationsschritte führt.
Läuft auf dem bestehenden SettingsDashboard (Port 8090).

**Aktivierung:**
- Automatisch wenn `matrix_access_token` nicht im SecretStore gesetzt ist
- `GET /` redirected zu `/setup` solange Setup nicht abgeschlossen
- Nach Abschluss: normales Dashboard, `/setup` bleibt erreichbar (Re-Konfiguration)

## Wizard-Schritte

### Schritt 1: Willkommen & Voraussetzungen

```
Willkommen bei Elder-Berry!

Dieser Assistent richtet Saleria Berry für dich ein.
Bevor wir starten, prüfe bitte:

[✅] Python 3.12+ installiert
[✅] Git installiert
[⬜] Nextcloud-Instanz verfügbar → [Hilfe-Link]
[⬜] Matrix/Synapse-Server verfügbar → [Hilfe-Link]
[⬜] Anthropic API Key → [Link: console.anthropic.com]

[Weiter →]
```

Automatische Checks wo möglich (Python-Version, Git, Ollama).
Nextcloud/Matrix: nur Hinweis + Link, kein automatischer Check.

### Schritt 2: LLM-Backend

```
Wie soll Saleria denken?

API-Key für Claude (Anthropic):
[________________________] [Testen]
→ ✅ Verbindung erfolgreich (claude-sonnet-4-6)

Ollama (lokales LLM, optional):
→ ✅ Erreichbar (phi4:14b geladen)
   ODER
→ ❌ Nicht erreichbar (Ollama installieren: https://ollama.com)
     Kein Problem – Saleria nutzt dann nur die Claude API.

[← Zurück] [Weiter →]
```

**Aktion:** `anthropic_api_key` → SecretStore, Test-Call an API.

### Schritt 3: Matrix-Verbindung

```
Matrix-Server (Saleria kommuniziert über Matrix):

Homeserver-URL:  [https://matrix.example.com_____] 
Bot-User-ID:     [@saleria:example.com____________]
Access-Token:    [syt_________________________] [?]
Raum-ID:         [!abc:example.com________________]

[Verbindung testen]
→ ✅ Login erfolgreich, Raum erreichbar

Erlaubte Sender (wer darf mit Saleria sprechen):
[@dein_user:example.com___________________________]

[← Zurück] [Weiter →]
```

**Hilfe-Popup [?]:** Erklärt wie man einen Access-Token aus Element exportiert.
**Aktion:** 6 Keys → SecretStore, Login-Test via matrix-nio.

### Schritt 4: Nextcloud

```
Nextcloud (Dateien, Kalender, Kontakte):

Server-URL:      [https://cloud.example.com_______]
Benutzername:    [dein_user________________________]
App-Passwort:    [_________________________________] [?]

[Verbindung testen]
→ ✅ WebDAV erreichbar, CalDAV OK, CardDAV OK

[← Zurück] [Weiter →]
```

**Hilfe [?]:** Erklärt wie man ein App-Passwort in Nextcloud generiert
(Einstellungen → Sicherheit → Neues App-Passwort).
**Aktion:** 3 Keys → SecretStore, WebDAV/CalDAV/CardDAV Verbindungstests.

### Schritt 5: E-Mail

```
E-Mail (Saleria kann Mails lesen und beantworten):

Provider: [Dropdown: Strato / GMX / Gmail / Outlook / ...]
          → füllt Host/Port automatisch aus

Oder manuell:
IMAP-Host: [imap.example.com___]  Port: [993]
SMTP-Host: [smtp.example.com___]  Port: [465]

Benutzername: [user@example.com___________]
Passwort:     [___________________________]

[Verbindung testen]
→ ✅ IMAP OK (12 ungelesene Mails), SMTP OK

[← Zurück] [Weiter →]
```

**Aktion:** 6 Keys → SecretStore, IMAP- + SMTP-Verbindungstest.
Nutzt die bestehende Provider-Liste aus `setup_email.py`.

### Schritt 6: Standort & Wetter

```
Wo bist du zuhause? (für Wetter, Briefing, Routenplanung)

Stadt:        [Berlin_____________________]
Breitengrad:  [52.52_____]
Längengrad:   [13.405____]

[Standort suchen] → füllt Lat/Lon aus Stadt automatisch
                    (Google Geocoding API, falls Maps Key gesetzt)

Zeitzone: [Europe/Berlin ▼]

[← Zurück] [Weiter →]
```

**Aktion:** `weather_city`, `weather_latitude`, `weather_longitude`,
`timezone` → SecretStore.

### Schritt 7: Optionale Dienste

```
Diese Dienste sind optional. Du kannst sie jetzt oder später einrichten.

Web-Suche (Brave Search):
  API-Key: [________________________] [Testen]
  → Kostenlos bis 2000 Anfragen/Monat
  → [Key erstellen: https://brave.com/search/api/]

Sprach-Cloud (ElevenLabs TTS):
  API-Key:  [________________________]
  Voice-ID: [________________________]
  → Bessere Sprachqualität als lokales XTTS v2
  → [Account: https://elevenlabs.io]

Schnelle Sprache-zu-Text (Groq):
  API-Key: [________________________] [Testen]
  → Schneller als lokales Whisper
  → [Key erstellen: https://console.groq.com]

Fitness-Tracker (Berry-Gym):
  API-Token: [________________________]
  → Nur relevant wenn Berry-Gym Instanz vorhanden

Google Maps (Routenplanung):
  API-Key: [________________________] [Testen]
  → [Directions API aktivieren: https://console.cloud.google.com]

RPi5 (Roboter-Hardware):
  IP-Adresse: [192.168.50.220_________]
  → Nur wenn RPi5 mit Elder-Berry Server läuft

[← Zurück] [Weiter →]
```

Jedes Feld ist optional – leere Felder werden übersprungen.

### Schritt 8: Zusammenfassung & Start

```
🎉 Saleria ist bereit!

Konfigurierte Dienste:
  ✅ LLM: Claude Sonnet 4.6 (+ Ollama Fallback)
  ✅ Matrix: @saleria:example.com
  ✅ Nextcloud: cloud.example.com
  ✅ E-Mail: user@strato.de (IMAP + SMTP)
  ✅ Wetter: Berlin (52.52, 13.41)
  ✅ Brave Search
  ❌ ElevenLabs (nicht konfiguriert – lokale TTS wird genutzt)
  ❌ RPi5 (nicht konfiguriert – kein Avatar/Drehteller)

Nächste Schritte:
  1. Starte Saleria: python scripts/start_saleria.py
  2. Öffne Element und schreibe "hallo" an Saleria
  3. Einstellungen: http://localhost:8090

[Saleria starten] [Zum Dashboard]
```

## Architektur

### Neue Dateien

| Datei | Verantwortung |
|-------|---------------|
| `scripts/setup_wizard.py` | Standalone-Starter (startet FastAPI mit nur Setup-Routes) |
| `web/setup_wizard.py` | FastAPI-Routes für den Setup-Wizard |
| `web/templates/setup_wizard.html` | HTML/JS/CSS für den Wizard |
| `web/setup_tests.py` | Verbindungstest-Logik (Matrix, IMAP, SMTP, NC, API) |
| `scripts/install.ps1` | Windows Bootstrap-Script |
| `scripts/install.sh` | Linux Bootstrap-Script (RPi5) |

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `web/settings_dashboard.py` | Setup-Wizard Routes einbinden, Redirect-Logik |
| `scripts/start_saleria.py` | First-Run-Check: wenn kein Matrix-Token → Setup-Wizard starten |

### Setup-Test-Klasse (`web/setup_tests.py`)

```python
class SetupTests:
    """Verbindungstests für den Setup-Wizard."""

    @staticmethod
    async def test_anthropic(api_key: str) -> dict:
        """Testet Anthropic API Key mit minimalem API-Call."""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-sonnet-4-6-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return {"success": True, "model": resp.model}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def test_matrix(homeserver: str, user_id: str, token: str,
                          room_id: str | None) -> dict:
        """Testet Matrix-Login und Raum-Zugriff."""
        try:
            from nio import AsyncClient
            client = AsyncClient(homeserver, user_id)
            client.access_token = token
            resp = await client.whoami()
            result = {"success": True, "user_id": resp.user_id}
            if room_id:
                # Raum beitreten / prüfen
                await client.join(room_id)
                result["room_joined"] = True
            await client.close()
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def test_nextcloud(url: str, user: str, password: str) -> dict:
        """Testet WebDAV, CalDAV, CardDAV Erreichbarkeit."""
        import httpx
        results = {"webdav": False, "caldav": False, "carddav": False}
        auth = (user, password)
        async with httpx.AsyncClient(timeout=10) as client:
            # WebDAV
            try:
                r = await client.request("PROPFIND",
                    f"{url}/remote.php/dav/files/{user}/",
                    auth=auth, headers={"Depth": "0"})
                results["webdav"] = r.status_code in (207, 200)
            except Exception:
                pass
            # CalDAV
            try:
                r = await client.request("PROPFIND",
                    f"{url}/remote.php/dav/calendars/{user}/",
                    auth=auth, headers={"Depth": "0"})
                results["caldav"] = r.status_code in (207, 200)
            except Exception:
                pass
            # CardDAV
            try:
                r = await client.request("PROPFIND",
                    f"{url}/remote.php/dav/addressbooks/users/{user}/",
                    auth=auth, headers={"Depth": "0"})
                results["carddav"] = r.status_code in (207, 200)
            except Exception:
                pass
        success = all(results.values())
        return {"success": success, **results}

    @staticmethod
    async def test_email(imap_host: str, imap_port: int,
                         smtp_host: str, smtp_port: int,
                         user: str, password: str) -> dict:
        """Testet IMAP- und SMTP-Verbindung."""
        import imaplib, smtplib, ssl
        result = {"imap": False, "smtp": False, "unread": 0}
        # IMAP
        try:
            mail = imaplib.IMAP4_SSL(imap_host, imap_port)
            mail.login(user, password)
            mail.select("INBOX")
            _, data = mail.search(None, "UNSEEN")
            result["unread"] = len(data[0].split()) if data[0] else 0
            result["imap"] = True
            mail.logout()
        except Exception:
            pass
        # SMTP
        try:
            ctx = ssl.create_default_context()
            if smtp_port == 465:
                srv = smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx)
            else:
                srv = smtplib.SMTP(smtp_host, smtp_port)
                srv.starttls(context=ctx)
            srv.login(user, password)
            srv.quit()
            result["smtp"] = True
        except Exception:
            pass
        result["success"] = result["imap"] and result["smtp"]
        return result

    @staticmethod
    def test_ollama() -> dict:
        """Prüft ob Ollama erreichbar ist und welche Modelle geladen sind."""
        import httpx
        try:
            r = httpx.get("http://localhost:11434/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            return {"success": True, "models": models}
        except Exception:
            return {"success": False, "models": []}

    @staticmethod
    async def test_brave(api_key: str) -> dict:
        """Testet Brave Search API."""
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": "test"},
                    headers={"X-Subscription-Token": api_key},
                    timeout=10,
                )
            return {"success": r.status_code == 200}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

## API-Endpoints

```python
# Setup-Status
GET  /api/setup/status
  → {"completed": false, "current_step": 3, "steps_total": 8,
     "configured": ["anthropic", "matrix"], "missing": ["nextcloud", ...]}

# Schritt-Daten laden
GET  /api/setup/step/<n>
  → Aktuell gespeicherte Werte für diesen Schritt (ohne Passwörter)

# Schritt speichern + testen
POST /api/setup/step/<n>
  Body: {key: value, ...}
  → Speichert in SecretStore, führt Verbindungstest aus
  → {"success": true, "tests": {"matrix": true, "room_joined": true}}

# Voraussetzungen prüfen
GET  /api/setup/prerequisites
  → {"python": "3.12.4", "git": true, "ollama": {"available": true,
     "models": ["phi4:14b"]}, "pip_packages": {"matrix-nio": true, ...}}

# Einzelnen Dienst testen
POST /api/setup/test/<service>
  Body: {credentials...}
  → {"success": true/false, "details": {...}}

# Setup abschließen
POST /api/setup/complete
  → Markiert Setup als abgeschlossen, redirected zum Dashboard
```

## First-Run-Detection

In `start_saleria.py`:

```python
def check_first_run(secrets: SecretStore) -> bool:
    """Prüft ob die Minimal-Konfiguration vorhanden ist."""
    required = ["matrix_access_token", "matrix_user_id", "matrix_homeserver"]
    return all(secrets.has(k) for k in required)

# Im Hauptablauf:
if not check_first_run(secrets):
    logger.info("Erste Ausführung erkannt – starte Setup-Wizard")
    from elder_berry.web.setup_wizard import run_setup_wizard
    run_setup_wizard(secrets)  # Blockiert bis Setup abgeschlossen
    # Danach normal weiter
```

## Hilfe-Links (extern, keine eigenen Docs)

Keine eigenen Installationsanleitungen – offizielle Dokumentation verlinken.
Pflege eigener Docs wäre Aufwand der sofort veraltet.

| Thema | Link |
|-------|------|
| Nextcloud Installation | https://docs.nextcloud.com/server/latest/admin_manual/installation/ |
| Nextcloud App-Passwort | https://docs.nextcloud.com/server/latest/user_manual/en/session_management.html |
| Matrix/Synapse Setup | https://element-hq.github.io/synapse/latest/setup/installation.html |
| Element Access-Token | Kurze Inline-Anleitung im Wizard (3 Zeilen: Settings → Help & About → Access Token) |
| Anthropic API Key | https://console.anthropic.com/ |
| Ollama | https://ollama.com/download |
| Brave Search API | https://brave.com/search/api/ |
| Google Cloud Console | https://console.cloud.google.com/ |

Diese Links werden direkt im Wizard als `[?]`-Icons neben den Eingabefeldern angezeigt.

## Tests (~40 geplant)

### test_setup_tests.py (~20 Tests)
```
- test_anthropic_valid_key: Erfolgreicher API-Test
- test_anthropic_invalid_key: Falscher Key → success=false
- test_matrix_login_success: Login + Raum beitreten
- test_matrix_login_invalid_token: Falscher Token → Fehler
- test_matrix_no_room: Login OK aber Raum nicht erreichbar
- test_nextcloud_all_ok: WebDAV + CalDAV + CardDAV
- test_nextcloud_partial: Nur WebDAV OK → success=false
- test_nextcloud_unreachable: Server nicht erreichbar
- test_email_imap_ok: IMAP Login + Unread-Count
- test_email_smtp_ok: SMTP Login
- test_email_imap_fail: Falsches Passwort
- test_email_provider_defaults: Provider-Dropdown füllt Felder
- test_ollama_available: Modelle gefunden
- test_ollama_not_running: Timeout → success=false
- test_brave_valid: Erfolgreiche Suche
- test_brave_invalid: Falscher Key → 401
- test_prerequisites_python: Version erkannt
- test_prerequisites_git: Git verfügbar
- test_prerequisites_ollama: Ollama-Status
- test_prerequisites_packages: pip-Pakete geprüft
```

### test_setup_wizard_api.py (~15 Tests)
```
- test_status_fresh: Keine Keys → completed=false, step=1
- test_status_partial: Einige Keys → richtiger current_step
- test_status_complete: Alle Pflicht-Keys → completed=true
- test_step_save_and_test: Keys speichern + Test ausführen
- test_step_save_invalid: Fehlender Pflicht-Key → 400
- test_step_test_failure: Verbindungstest schlägt fehl → success=false
- test_step_skip_optional: Optionale Schritte überspringbar
- test_complete_redirect: Nach Complete → Dashboard
- test_first_run_detection: Kein Token → Setup starten
- test_re_setup: Erneuter Aufruf nach Abschluss möglich
- test_step_preserves_existing: Bestehende Keys nicht überschrieben
- test_password_not_in_get: GET gibt keine Passwörter zurück
- test_wizard_step_order: Schritte nur sequenziell zugänglich
- test_setup_complete_marks_done: Flag gesetzt nach Abschluss
```

### test_install_scripts.py (~5 Tests)
```
- test_install_ps1_syntax: PowerShell-Script ist syntaktisch korrekt
- test_install_sh_syntax: Bash-Script ist syntaktisch korrekt
- test_install_sh_checks_python: Python-Version geprüft
- test_install_creates_venv: venv-Erstellung richtig
- test_install_requirements: pip install Kommando korrekt
```

## Implementierungsschritte

1. **SetupTests**: Verbindungstest-Klasse mit allen Test-Methoden
2. **Setup-Wizard Backend**: FastAPI Routes (`web/setup_wizard.py`)
3. **Setup-Wizard Frontend**: HTML Template mit Step-Navigation + externe Hilfe-Links
4. **First-Run-Detection**: `start_saleria.py` Integration
5. **Bootstrap-Scripts**: `install.ps1` + `install.sh`
6. **SettingsDashboard Integration**: Redirect-Logik, Re-Setup-Möglichkeit
7. **Tests**: test_setup_tests.py + test_setup_wizard_api.py
8. **Commit**: `feature/phase-46-setup-wizard`

## Edge Cases & Einschränkungen

| Fall | Handling |
|------|----------|
| Setup abgebrochen | SecretStore behält gespeicherte Keys, Wizard setzt beim letzten Schritt fort |
| Dienst nach Setup offline | Dashboard zeigt Status, Saleria degradiert graceful |
| Kein Nextcloud | Schritt überspringen → Google Calendar Fallback, keine Cloud-Dateien |
| Kein Matrix | Blockierend – Pflicht. Terminal-Modus als Fallback anbieten |
| Falscher API-Key | Sofortiger Test → roter Hinweis, Schritt nicht abschließbar |
| Bestehende Installation | Re-Setup überschreibt nur explizit geänderte Keys |
| Kein RPi5 | Komplett optional, Saleria läuft als reiner Chat-Bot |

## Abgrenzung

- Wizard installiert NICHT Nextcloud/Matrix (nur Konfiguration + Hilfeseiten)
- Bot-Account muss der Nutzer selbst anlegen
- DNS/SSL sind Voraussetzung
- RPi5-Setup ist eigenes Thema (hardware-spezifisch)

## Sicherheit

- Passwörter als `type="password"`, GET gibt nie Secret-Werte zurück
- Alles via SecretStore (Fernet-verschlüsselt), kein Logging von Secrets
- Wizard nur lokal oder über gesichertes Dashboard erreichbar
