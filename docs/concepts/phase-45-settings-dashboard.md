# Phase 45 – Settings Dashboard Erweiterung

## Ziel

Das bestehende Settings Dashboard (localhost:8090) wird um drei neue Sektionen
erweitert: API-Status & -Verwaltung, LLM-Backend-Umschalter und Grundeinstellungen.
Kein neues Dashboard – das vorhandene `AudioDashboard` wird ausgebaut.

## Bestandsaufnahme

### Bestehende Sektionen (audio_dashboard.html)

| Sektion | Funktion |
|---------|----------|
| Audio-Modus | Matrix only / Matrix+Lokal Toggle |
| Monitor-Auswahl | Computer Use Monitor-Index |
| Allowed Senders | Matrix-Whitelist |
| Zeitzone | Dropdown für IANA-Timezone |
| STT-Timeout | Slider 5–600s |
| Avatar-Editor | Link zu /avatar/editor |

### Bestehende Technik

- **Backend**: `web/audio_dashboard.py` (FastAPI, Port 8090)
- **Frontend**: `web/templates/audio_dashboard.html` (Vanilla JS, inline CSS, Dark Theme)
- **Pattern**: Card-basiert, fetch() → JSON API, kein Framework
- **DI**: AudioRouter, ComputerUseController, SecretStore, AudioPipeline bereits injiziert

## Neue Sektionen

### 1. API-Status & Verwaltung

Übersicht aller bekannten API-Keys mit Status (✅ gesetzt / ❌ fehlt).
Formular zum Setzen neuer Keys.

**Bekannte Keys** (in Kategorien gruppiert):

```
KI & Sprache:
  - anthropic_api_key        (Claude API)
  - groq_api_key             (Groq – optional)
  - elevenlabs_api_key       (ElevenLabs TTS – optional)
  - elevenlabs_voice_id      (ElevenLabs Voice – optional)

Suche & Karten:
  - brave_api_key            (Brave Search)
  - google_maps_api_key      (Directions API)
  - google_oauth_tokens      (Google Calendar – Legacy-Fallback)

Matrix:
  - matrix_homeserver
  - matrix_user_id
  - matrix_password
  - matrix_access_token
  - matrix_room_id
  - matrix_allowed_senders

E-Mail:
  - email_user
  - email_password
  - email_imap_host
  - email_imap_port
  - smtp_host
  - smtp_port

Nextcloud:
  - nextcloud_url
  - nextcloud_user
  - nextcloud_app_password

Dienste:
  - berry_gym_api_token      (Fitness-Tracker)
  - stirling_pdf_url         (PDF-Service)
  - stirling_pdf_api_key     (PDF-Service)

Infrastruktur:
  - robot_host               (RPi5 IP)
  - tower_host               (Tower IP)

Wetter & Standort:
  - weather_city
  - weather_latitude
  - weather_longitude
```

**UI-Design:**
- Tabelle: Key-Name | Kategorie | Status (✅/❌)
- Kein Wert anzeigen – nur ob gesetzt
- "Bearbeiten"-Button pro Zeile → Eingabefeld (type=password) + Speichern
- "Neuen Key hinzufügen"-Formular für bisher unbekannte Keys

**API-Endpoints:**
```python
GET  /api/secrets/status   → [{key, category, is_set}]
POST /api/secrets/set      → {key: str, value: str} → {success}
DELETE /api/secrets/delete  → {key: str} → {success}
```

**Sicherheit:**
- Werte werden NIEMALS im GET zurückgegeben – nur `is_set: true/false`
- POST akzeptiert den neuen Wert, gibt aber nie den gespeicherten zurück
- Dashboard ist nur im lokalen Netzwerk erreichbar (0.0.0.0:8090)
- Kein Auth am Dashboard selbst (gleiche Sicherheitsstufe wie bisher)

### 2. LLM-Backend-Umschalter

Anzeige des aktiven Backends + manueller Override.

**Aktueller Zustand:**
- `LLMRouter` wählt automatisch: Anthropic (wenn Key vorhanden) → Ollama (Fallback)
- Kein manueller Override möglich
- `active_backend` Property existiert (read-only)

**Neues Feature:**
- Anzeige: Aktuelles Backend (z.B. "Anthropic Sonnet 4.6" / "Ollama phi4:14b")
- Statusanzeige: Ollama erreichbar? Anthropic-Key gesetzt?
- Toggle: "Nur lokal (Ollama)" / "API bevorzugt (Anthropic → Ollama)"
- Der Toggle setzt einen `llm_mode`-Wert im SecretStore:
  - `api_preferred` (default): Anthropic primär, Ollama Fallback
  - `local_only`: nur Ollama, auch wenn Anthropic verfügbar

**LLMRouter-Erweiterung:**
```python
class LLMRouter(LLMClient):
    def __init__(self, primary, fallback, mode: str = "api_preferred"):
        self._primary = primary
        self._fallback = fallback
        self._mode = mode  # "api_preferred" | "local_only"

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in ("api_preferred", "local_only"):
            raise ValueError(f"Ungültiger LLM-Modus: {value}")
        self._mode = value

    def _select_client(self) -> LLMClient:
        if self._mode == "local_only":
            if self._fallback.is_available():
                return self._fallback
            raise RuntimeError("Ollama nicht erreichbar (local_only Modus).")
        # api_preferred: bestehende Logik
        if self._primary.is_available():
            return self._primary
        if self._fallback.is_available():
            return self._fallback
        raise RuntimeError("Kein LLM-Backend verfügbar.")
```

**API-Endpoints:**
```python
GET  /api/llm/status  → {active_backend, mode, primary_available, fallback_available,
                          primary_name, fallback_name}
POST /api/llm/mode    → {mode: "api_preferred" | "local_only"} → {mode, active_backend}
```

**UI-Design:**
- Card mit Status-Balken (grün: verbunden, rot: nicht erreichbar)
- Zwei große Buttons: "API bevorzugt" / "Nur lokal"
- Aktiver Button hervorgehoben
- Info-Text unter jedem Button: Modellname + Erreichbarkeit

### 3. Grundeinstellungen

Zentrale Konfigurationswerte die aktuell über SecretStore verstreut sind.

**Einstellungen:**

| Setting | SecretStore-Key | UI-Element | Beschreibung |
|---------|----------------|------------|--------------|
| Wetter-Stadt | weather_city | Text-Input | Stadtname für Wetter-Anzeige |
| Wetter-Breite | weather_latitude | Number-Input | Breitengrad |
| Wetter-Länge | weather_longitude | Number-Input | Längengrad |
| Routen-Puffer | route_buffer_minutes | Number-Input (5–60) | Puffer für Abfahrtszeit (Default: 15) |
| Briefing-Uhrzeit | briefing_time | Time-Input (HH:MM) | Tägliches Briefing (Default: 07:30) |
| RPi5-Host | robot_host | Text-Input | IP/Hostname des RPi5 |
| Tower-Host | tower_host | Text-Input | IP/Hostname des Towers |

**API-Endpoints:**
```python
GET  /api/settings         → {weather_city, weather_latitude, ..., briefing_time, ...}
POST /api/settings         → {key: value, ...} → {success, updated_keys}
```

**UI-Design:**
- Formular-Card mit Eingabefeldern (gruppiert)
- "Speichern"-Button am Ende
- Erfolgs-/Fehlermeldung inline
- Wetter: Optionaler "Standort suchen"-Button (Geocoding via Google Maps API)
  → Tier 2, erstmal manuelle Eingabe

### 4. Memory-Browser (Tier 2 – nicht in Phase 45)

Für spätere Erweiterung dokumentiert, nicht Teil des initialen Scope.

- Letzte N Erinnerungen anzeigen (ChromaDB `get_recent()`)
- Suchfeld für semantische Suche (`search()`)
- Collection-Statistik (Anzahl Einträge, letzte Session)
- Einzelne Erinnerungen löschen
- **Warum Tier 2**: UI für Memory-Browsing braucht Paginierung, Filter,
  sinnvolle Formatierung. Aufwand steht nicht im Verhältnis zum Nutzen –
  Saleria per Chat zu fragen ist für Memory-Abruf effizienter.

## Architektur

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `web/audio_dashboard.py` | 3 neue API-Endpoint-Gruppen (secrets, llm, settings) |
| `web/templates/audio_dashboard.html` | 3 neue Cards (API-Status, LLM, Settings) |
| `llm/router.py` | `mode` Property + Setter, `_select_client` Mode-Check |
| `start_saleria.py` | LLM-Mode aus SecretStore lesen → LLMRouter.mode setzen |

### Keine neuen Dateien

Alles wird ins bestehende Dashboard integriert. Kein neues Python-Modul nötig.

### DI-Erweiterung

`AudioDashboard.__init__` bekommt zusätzliche Parameter:

```python
def __init__(
    self,
    audio_router: AudioRouter,
    computer_use: ComputerUseController | None = None,
    secret_store: SecretStore | None = None,
    avatar_renderer: LayeredSpriteRenderer | None = None,
    audio_pipeline: AudioPipeline | None = None,
    llm_router: LLMRouter | None = None,       # NEU
    host: str = "0.0.0.0",
    port: int = 8090,
) -> None:
```

## API-Endpoints (Zusammenfassung)

### Secrets
```
GET  /api/secrets/status
  Response: {
    "categories": [
      {
        "name": "KI & Sprache",
        "keys": [
          {"key": "anthropic_api_key", "label": "Claude API", "is_set": true},
          {"key": "groq_api_key", "label": "Groq", "is_set": false},
          ...
        ]
      },
      ...
    ]
  }

POST /api/secrets/set
  Body:    {"key": "brave_api_key", "value": "BSA..."}
  Response: {"success": true, "key": "brave_api_key"}

POST /api/secrets/delete
  Body:    {"key": "google_oauth_tokens"}
  Response: {"success": true, "key": "google_oauth_tokens"}
```

### LLM
```
GET  /api/llm/status
  Response: {
    "mode": "api_preferred",
    "active_backend": "anthropic",
    "primary": {"name": "Anthropic Sonnet 4.6", "available": true},
    "fallback": {"name": "Ollama phi4:14b", "available": true}
  }

POST /api/llm/mode
  Body:    {"mode": "local_only"}
  Response: {"mode": "local_only", "active_backend": "ollama"}
```

### Settings
```
GET  /api/settings
  Response: {
    "weather_city": "Berlin",
    "weather_latitude": "52.52",
    "weather_longitude": "13.405",
    "route_buffer_minutes": "15",
    "briefing_time": "07:30",
    "robot_host": "192.168.50.220",
    "tower_host": "192.168.50.100"
  }

POST /api/settings
  Body:    {"weather_city": "München", "weather_latitude": "48.14"}
  Response: {"success": true, "updated": ["weather_city", "weather_latitude"]}
```

## Key-Registry (im Backend)

Statische Definition aller bekannten Keys mit Label und Kategorie,
damit das Frontend konsistent gruppieren kann – auch wenn ein Key
noch nicht im SecretStore existiert.

```python
SECRET_REGISTRY: list[dict] = [
    {"key": "anthropic_api_key", "label": "Claude API", "category": "KI & Sprache"},
    {"key": "groq_api_key", "label": "Groq", "category": "KI & Sprache"},
    {"key": "elevenlabs_api_key", "label": "ElevenLabs API", "category": "KI & Sprache"},
    {"key": "elevenlabs_voice_id", "label": "ElevenLabs Voice", "category": "KI & Sprache"},
    {"key": "brave_api_key", "label": "Brave Search", "category": "Suche & Karten"},
    {"key": "google_maps_api_key", "label": "Google Maps", "category": "Suche & Karten"},
    {"key": "google_oauth_tokens", "label": "Google OAuth", "category": "Suche & Karten"},
    {"key": "matrix_homeserver", "label": "Homeserver", "category": "Matrix"},
    {"key": "matrix_user_id", "label": "User ID", "category": "Matrix"},
    {"key": "matrix_password", "label": "Passwort", "category": "Matrix"},
    {"key": "matrix_access_token", "label": "Access Token", "category": "Matrix"},
    {"key": "matrix_room_id", "label": "Room ID", "category": "Matrix"},
    {"key": "matrix_allowed_senders", "label": "Erlaubte Sender", "category": "Matrix"},
    {"key": "email_user", "label": "Benutzer", "category": "E-Mail"},
    {"key": "email_password", "label": "Passwort", "category": "E-Mail"},
    {"key": "email_imap_host", "label": "IMAP Host", "category": "E-Mail"},
    {"key": "email_imap_port", "label": "IMAP Port", "category": "E-Mail"},
    {"key": "smtp_host", "label": "SMTP Host", "category": "E-Mail"},
    {"key": "smtp_port", "label": "SMTP Port", "category": "E-Mail"},
    {"key": "nextcloud_url", "label": "URL", "category": "Nextcloud"},
    {"key": "nextcloud_user", "label": "Benutzer", "category": "Nextcloud"},
    {"key": "nextcloud_app_password", "label": "App-Passwort", "category": "Nextcloud"},
    {"key": "berry_gym_api_token", "label": "API Token", "category": "Dienste"},
    {"key": "stirling_pdf_url", "label": "URL", "category": "Dienste"},
    {"key": "stirling_pdf_api_key", "label": "API Key", "category": "Dienste"},
    {"key": "robot_host", "label": "RPi5 Host", "category": "Infrastruktur"},
    {"key": "tower_host", "label": "Tower Host", "category": "Infrastruktur"},
    {"key": "weather_city", "label": "Stadt", "category": "Wetter & Standort"},
    {"key": "weather_latitude", "label": "Breitengrad", "category": "Wetter & Standort"},
    {"key": "weather_longitude", "label": "Längengrad", "category": "Wetter & Standort"},
]
```

## Tests (~30 geplant)

### test_settings_dashboard_api.py (~20 Tests)

```
API-Status:
- test_secrets_status_all_keys: Alle Registry-Keys in Response
- test_secrets_status_set_vs_unset: is_set korrekt für gesetzte/fehlende Keys
- test_secrets_status_no_secret_store: available=false wenn kein SecretStore
- test_secrets_status_grouped: Kategorien korrekt gruppiert
- test_secrets_set_new_key: Neuen Key setzen → is_set wird true
- test_secrets_set_update: Bestehenden Key überschreiben
- test_secrets_set_empty_value: Leerer Wert → 400
- test_secrets_set_no_body: Kein Body → 400
- test_secrets_delete_existing: Key löschen → is_set wird false
- test_secrets_delete_nonexistent: Nicht vorhandener Key → 404

LLM-Umschalter:
- test_llm_status_api_preferred: Default-Modus korrekt
- test_llm_status_both_available: primary + fallback available
- test_llm_status_ollama_only: Nur Fallback verfügbar
- test_llm_mode_switch_local: Umschalten auf local_only
- test_llm_mode_switch_api: Zurück auf api_preferred
- test_llm_mode_invalid: Ungültiger Modus → 400
- test_llm_mode_no_router: Kein LLMRouter → available=false

Settings:
- test_settings_get_all: Alle Settings-Keys in Response
- test_settings_update_single: Einzelnes Setting ändern
- test_settings_update_multiple: Mehrere Settings gleichzeitig
```

### test_llm_router_mode.py (~10 Tests)

```
- test_mode_default: Default ist "api_preferred"
- test_mode_setter: mode Setter funktioniert
- test_mode_invalid: Ungültiger Wert → ValueError
- test_select_client_api_preferred_both: primary wenn beide verfügbar
- test_select_client_api_preferred_no_primary: fallback wenn primary offline
- test_select_client_local_only: fallback auch wenn primary verfügbar
- test_select_client_local_only_no_fallback: RuntimeError
- test_active_backend_reflects_mode: active_backend ändert sich mit mode
- test_generate_uses_correct_backend: generate() nutzt richtiges Backend
- test_mode_persisted: mode aus SecretStore geladen
```

## Implementierungsschritte

1. **LLMRouter erweitern**: mode Property + Setter + _select_client Anpassung + Tests
2. **API-Endpoints**: secrets/status, secrets/set, secrets/delete in audio_dashboard.py
3. **API-Endpoints**: llm/status, llm/mode in audio_dashboard.py
4. **API-Endpoints**: settings GET/POST in audio_dashboard.py
5. **HTML-Template**: 3 neue Cards (API-Status-Tabelle, LLM-Toggle, Settings-Formular)
6. **Integration**: start_saleria.py – LLMRouter.mode aus SecretStore, LLMRouter an Dashboard DI
7. **Tests**: test_settings_dashboard_api.py + test_llm_router_mode.py
8. **Commit**: `feature/phase-45-settings-dashboard`

## Edge Cases & Einschränkungen

| Fall | Handling |
|------|----------|
| SecretStore nicht verfügbar | Alle Sektionen zeigen "nicht verfügbar" |
| LLMRouter nicht injiziert | LLM-Card ausgeblendet |
| Ollama nicht erreichbar | Fallback-Status rot, local_only wirft Fehler-Hinweis |
| Key mit Sonderzeichen setzen | URL-Encoding im POST, SecretStore speichert raw |
| Dashboard-Zugriff von außen | Nur lokales Netz (kein Reverse Proxy vorgesehen) |
| Unbekannter Key im POST | Wird akzeptiert (SecretStore ist ein offener Key-Value-Store) |
| Concurrent Writes | Last-Write-Wins (SecretStore ist File-basiert, kein Lock) |

## Naming-Vorschlag

`AudioDashboard` ist als Name irreführend – es macht seit Langem mehr als Audio.
Umbenennung zu `SettingsDashboard` in dieser Phase:
- Klasse: `AudioDashboard` → `SettingsDashboard`
- Datei: `audio_dashboard.py` → `settings_dashboard.py`
- Template: `audio_dashboard.html` → `settings_dashboard.html`
- Alle Imports in `start_saleria.py` anpassen

Alternativ: nur Klasse umbenennen, Dateinamen lassen (weniger Churn).
**Empfehlung**: Alles umbenennen – einmaliger Aufwand, sauberer danach.

## Mögliche Erweiterungen (nicht in Phase 45)

- **Memory-Browser** (Tier 2): ChromaDB Memories anzeigen + suchen
- **Service-Health**: Live-Status aller Services (ähnlich selfcheck, aber im Web)
- **Log-Viewer**: Letzte Fehler aus ErrorCollector im Dashboard
- **Backup-Status**: Letztes BorgBackup Datum + Erfolg/Fehler
- **Theme-Toggle**: Dark/Light Mode (aktuell nur Dark)


## Sicherheit (Deployment auf Rootserver)

Das Dashboard wird vom Tower (localhost:8090) über den Rootserver per Nginx
Reverse Proxy erreichbar gemacht – z.B. als `settings.last-strawberry.com`
oder als Pfad unter `fern.last-strawberry.com/settings/`.

### Zwei Schichten: IP-Whitelist + Basic Auth

Beide Maßnahmen greifen auf Nginx-Ebene. Kein Auth-Code im Python nötig.

**Schicht 1: IP-Whitelist (Nginx `allow`/`deny`)**
```nginx
# Feste NordVPN-IP des Nutzers
allow <NORDVPN_DEDICATED_IP>;
# Lokales Netz (Zugriff ohne VPN zuhause)
allow 192.168.50.0/24;
# Alles andere blockieren
deny all;
```

**Schicht 2: Basic Auth (Nginx `auth_basic`)**
```nginx
auth_basic "Elder-Berry Settings";
auth_basic_user_file /etc/nginx/.htpasswd_settings;
```

Passwort-Datei erstellen:
```bash
sudo apt install apache2-utils  # falls nicht vorhanden
sudo htpasswd -c /etc/nginx/.htpasswd_settings lera
# Passwort eingeben
sudo chmod 640 /etc/nginx/.htpasswd_settings
sudo chown root:www-data /etc/nginx/.htpasswd_settings
```

### Nginx Server-Block (Plesk Additional Nginx Directives)

```nginx
location /settings/ {
    # Schicht 1: IP-Whitelist
    allow <NORDVPN_DEDICATED_IP>;
    allow 192.168.50.0/24;
    deny all;

    # Schicht 2: Basic Auth
    auth_basic "Elder-Berry Settings";
    auth_basic_user_file /etc/nginx/.htpasswd_settings;

    # Reverse Proxy zum Tower
    proxy_pass http://<TOWER_LOCAL_IP>:8090/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket Support (falls später nötig)
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### Warum beide Schichten?

| Schicht | Schützt gegen | Schwäche allein |
|---------|---------------|-----------------|
| IP-Whitelist | Alle außer eigene IP | IP-Spoofing (theoretisch), VPN-Provider-Wechsel |
| Basic Auth | Unberechtigte Zugriffe | Brute-Force (ohne IP-Filter), Credential-Leak |
| **Beide zusammen** | Defense in depth | Angreifer braucht richtige IP UND Passwort |

### Fail2Ban-Jail (optional, empfohlen)

Schutz gegen Brute-Force auf Basic Auth:

```ini
# /etc/fail2ban/filter.d/nginx-settings.conf
[Definition]
failregex = ^<HOST> -.*"(GET|POST) /settings/.*" 401
ignoreregex =

# /etc/fail2ban/jail.d/nginx-settings.local
[nginx-settings]
enabled = true
port = http,https
filter = nginx-settings
logpath = /var/www/vhosts/*/logs/proxy_access_ssl_log
maxretry = 5
bantime = 3600
findtime = 600
```

### Tower-seitige Absicherung

Zusätzlich zur Nginx-Schicht: Der Tower akzeptiert nur Anfragen vom
Rootserver (oder aus dem lokalen Netz).

```python
# In SettingsDashboard.__init__:
from fastapi.middleware.trustedhost import TrustedHostMiddleware

# Optional: nur bekannte Hosts akzeptieren
ALLOWED_HOSTS = ["settings.last-strawberry.com", "fern.last-strawberry.com",
                 "localhost", "127.0.0.1"]
```

Alternativ einfacher: Tower-Firewall (Windows Defender Firewall)
erlaubt Port 8090 nur von Rootserver-IP und lokalem Netz.

### Deployment-Varianten

**Option A: Eigene Subdomain** `settings.last-strawberry.com`
- Pro: Saubere Trennung, eigenes SSL-Zertifikat
- Contra: DNS-Eintrag + Let's Encrypt Setup nötig

**Option B: Pfad unter Dashboard 2.0** `fern.last-strawberry.com/settings/`
- Pro: Kein neuer DNS-Eintrag, nutzt bestehendes SSL
- Contra: CORS-Konfiguration nötig, muss mit Dashboard 2.0 koexistieren

**Empfehlung**: Option B – weniger Infrastruktur-Aufwand, Dashboard 2.0
existiert bereits mit Nginx Reverse Proxy zu Tower/RPi5.
