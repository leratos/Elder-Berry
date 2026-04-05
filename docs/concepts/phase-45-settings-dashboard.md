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
| Concurrent Writes | asyncio.Lock serialisiert alle SecretStore-Writes |
| Value > 4 096 Zeichen | 400-Fehler mit Hinweis (DoS-Schutz) |
| secrets.enc korrumpiert | Dashboard startet trotzdem, Secret-Sektionen zeigen Fehlerhinweis |
| Kritischer Key geändert (Matrix) | Dashboard zeigt Neustart-Hinweis |
| LLM-Mode nach Neustart | Mode wird aus SecretStore `llm_mode` geladen – bleibt erhalten |

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

---

## Funktionsstabilität

### Input-Validierung

Alle POST-Endpunkte validieren Eingaben bevor sie den SecretStore berühren.
Eine zentrale Validierungsfunktion verhindert, dass die Logik pro Endpoint
dupliziert wird.

**Allgemeine Regeln (für alle Secret-Werte):**

| Regel | Fehler |
|-------|--------|
| `value` ist leer oder nur Whitespace | 400 – „Wert darf nicht leer sein." |
| `value` länger als 4 096 Zeichen | 400 – „Wert zu lang (max. 4 096 Zeichen)." |
| `key` enthält ungültige Zeichen (`[^a-z0-9_]`) | 400 – „Key darf nur Kleinbuchstaben, Ziffern und Unterstriche enthalten." |
| `key` länger als 128 Zeichen | 400 – „Key zu lang (max. 128 Zeichen)." |

**Typ-spezifische Regeln (anhand des Registry-Eintrags):**

```python
# Erweiterung SECRET_REGISTRY um optionalen "validate"-Schlüssel:
{
    "key": "email_imap_port",
    "label": "IMAP Port",
    "category": "E-Mail",
    "type": "int",       # Frontend sendet String → Backend parst zu int vor Validierung
    "min": 1,
    "max": 65535,
},
{
    "key": "matrix_homeserver",
    "label": "Homeserver",
    "category": "Matrix",
    "type": "url",           # muss https:// oder http:// beginnen
},
{
    "key": "weather_latitude",
    "label": "Breitengrad",
    "category": "Wetter & Standort",
    "type": "float",
    "min": -90.0,
    "max": 90.0,
},
```

Validierung erfolgt im Backend – das Frontend zeigt nur den Fehler-Text.

### Concurrent-Write-Schutz

Da der SecretStore File-basiert ist (kein Datenbank-Lock), serialisiert
das `SettingsDashboard` alle schreibenden Zugriffe über ein `asyncio.Lock`:

```python
class SettingsDashboard:
    def __init__(self, ...):
        ...
        self._write_lock = asyncio.Lock()

    # In jedem POST-Handler:
    async with self._write_lock:
        self._secret_store.set(key, value)
```

Das verhindert Race Conditions wenn mehrere Browser-Tabs gleichzeitig
speichern (unwahrscheinlich aber möglich).

### Graceful Degradation bei SecretStore-Fehler

Wenn `secrets.enc` korrumpiert oder nicht lesbar ist, startet das
Dashboard trotzdem. Die Secret-Sektionen zeigen einen Fehlerhinweis:

```json
{
  "available": false,
  "error": "SecretStore nicht lesbar – Datei korrumpiert oder Schlüssel verloren."
}
```

Die Audio- und LLM-Sektionen funktionieren weiterhin (sie brauchen keinen
SecretStore zur Laufzeit).

### LLM-Mode-Persistenz nach Neustart

Der `llm_mode`-Wert wird beim Dashboard-Start aus dem SecretStore geladen
und an den `LLMRouter` übergeben. Damit bleibt der manuelle Override über
Neustarts erhalten:

```python
# In start_saleria.py:
llm_mode = secrets.get_or_none("llm_mode") or "api_preferred"
llm_router = LLMRouter(primary=anthropic, fallback=ollama, mode=llm_mode)
```

Wenn der `LLMRouter` im Dashboard den Mode wechselt, wird er gleichzeitig
im SecretStore gespeichert:

```python
# POST /api/llm/mode Handler:
async with self._write_lock:
    self._llm_router.mode = new_mode
    self._secret_store.set("llm_mode", new_mode)
```

### Neustart-Hinweise für kritische Keys

Manche Keys werden nur beim Start ausgelesen und können nicht live
aktualisiert werden. Das Frontend zeigt einen Hinweis wenn solche
Keys geändert werden:

```python
# Erweiterung SECRET_REGISTRY:
{
    "key": "matrix_access_token",
    "label": "Access Token",
    "category": "Matrix",
    "requires_restart": True,   # NEU
},
```

Das Frontend reagiert darauf:
```
✅ matrix_access_token gespeichert.
⚠️ Dieser Wert wird erst nach einem Neustart von Saleria aktiv.
```

**Keys die einen Neustart erfordern:** alle Matrix-Keys, alle E-Mail-Keys,
`nextcloud_*`, `groq_api_key`, `elevenlabs_*`.

**Keys die sofort aktiv werden:** `weather_city`, `weather_latitude`,
`weather_longitude`, `route_buffer_minutes`, `briefing_time`,
`robot_host`, `tower_host` (Reconnect im Hintergrund), `llm_mode`
(direkte Weiterleitung an LLMRouter).

### Fehler-Isolation zwischen Endpoint-Gruppen

Ein unerwarteter Fehler in einer API-Gruppe (z.B. LLMRouter wirft RuntimeError)
darf nicht das gesamte Dashboard zum Absturz bringen. FastAPI-Exception-Handler
fangen das ab:

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@self._app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unbehandelte Ausnahme in %s: %s", request.url.path, exc)
    return JSONResponse(
        {"error": "Interner Fehler – Details im Log."},
        status_code=500,
    )
```

---

## Sicherheit – Details & Ergänzungen

Die Nginx-Schicht (IP-Whitelist + Basic Auth + Fail2Ban) ist in der
vorherigen Sektion dokumentiert. Dieser Abschnitt ergänzt die
Python-/Anwendungsebene.

### CORS-Konfiguration für Server-Deployment

Die aktuelle Implementierung in `AudioDashboard` setzt:

```python
allow_origins=["*"]   # ← PROBLEM bei Server-Deployment
```

Für den Server-Deployment-Fall muss das auf die tatsächliche Origin
eingeschränkt werden:

```python
ALLOWED_ORIGINS_LOCAL  = ["http://localhost:8090", "http://127.0.0.1:8090"]
# ALLOWED_ORIGINS_SERVER wird aus SecretStore gelesen (Key: "dashboard_origin")
# Beispiel: "https://fern.last-strawberry.com" – kein Hardcode im Code.
ALLOWED_ORIGINS_SERVER = [secret_store.get_or_none("dashboard_origin") or ""]

self._app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS_LOCAL + [o for o in ALLOWED_ORIGINS_SERVER if o],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)
```

Der Wert `ALLOWED_ORIGINS_SERVER` kommt aus einem optionalen
`dashboard_origin`-Key im SecretStore – damit bleibt er
konfigurierbar ohne Code-Änderung.

### Security Response Headers

FastAPI-Middleware setzt sicherheitsrelevante HTTP-Header:

```python
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "  # inline JS für die Cards nötig
            "style-src 'self' 'unsafe-inline';"
        )
        return response
```

Hinweis: `'unsafe-inline'` für Script und Style ist nötig, weil das
bestehende Template Inline-JS und -CSS nutzt. Für eine spätere
Template-Refaktorierung (Phase 50+): Inline-Scripts auf Nonces oder Hashes
umstellen (`script-src 'nonce-{random}'`) – dann kann `'unsafe-inline'`
entfernt werden. Diese Härtung ist als eigene Aufgabe zu verbuchen.

### Audit-Logging für Änderungen

Jede schreibende Operation protokolliert Quelle und Aktion – ohne den Wert:

```python
# Immer loggen, nie den Value!
logger.info(
    "AUDIT: secret '%s' gesetzt von %s",
    key,
    request.client.host if request.client else "unbekannt",
)
logger.info(
    "AUDIT: secret '%s' gelöscht von %s",
    key,
    request.client.host if request.client else "unbekannt",
)
logger.info(
    "AUDIT: LLM-Modus auf '%s' gesetzt von %s",
    new_mode,
    request.client.host if request.client else "unbekannt",
)
```

Das Audit-Log landet in der normalen Saleria-Logdatei – kein separater Store.

### Zweistufiges Löschen (Confirmation)

Das Löschen eines Keys ist nicht rückgängig zu machen. Das UI erzwingt
eine explizite Bestätigung:

```
1. Nutzer klickt "Löschen" neben einem Key.
2. Button wechselt zu "[Wirklich löschen?] [Abbrechen]" (5 Sekunden Timeout).
3. Erst ein zweiter Klick sendet DELETE /api/secrets/delete.
```

Das zweistufige Verfahren ist **rein frontend-seitig** – kein Backend-State nötig.

### Rate-Limiting auf Schreib-Endpunkten

Schutz gegen automatisierte Key-Brute-Force-Versuche (nur relevant bei
Server-Deployment, aber schon beim lokalen Einsatz eine gute Praxis):

**Option A – Nginx `limit_req`** (bevorzugt, kein Python-Code nötig):
```nginx
limit_req_zone $binary_remote_addr zone=settings_writes:10m rate=10r/m;

location /settings/api/secrets/ {
    limit_req zone=settings_writes burst=5 nodelay;
    ...
}
```

**Option B – FastAPI mit `slowapi`** (falls kein Nginx vorgeschaltet):
```python
# Dependency in pyproject.toml [remote]-Gruppe ergänzen: slowapi
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@self._app.post("/api/secrets/set")
@limiter.limit("10/minute")
async def set_secret(request: Request, body: dict | None = None):
    ...
```

Empfehlung: Option A für Server-Deployment, Option B nur wenn kein
Nginx vorhanden (z.B. rein lokaler Betrieb).

### Keine Secrets im Response-Body (Wiederholung + Erweiterung)

- `GET /api/secrets/status` gibt **nur** `is_set: true/false` zurück
- `POST /api/secrets/set` Response enthält **nicht** den gespeicherten Wert
- `GET /api/settings` gibt Werte für nicht-sensitive Settings zurück
  (weather_city, briefing_time etc.) – aber **nicht** für Matrix/Mail/API-Keys
- Alle FastAPI-Response-Schemata explizit modellieren (kein `**kwargs`-Durchschleifen)

**Klassifizierung der Settings nach Sensitivität:**

```python
# Erweiterung SECRET_REGISTRY:
{"key": "anthropic_api_key", ..., "sensitive": True},   # nie im GET
{"key": "weather_city", ..., "sensitive": False},        # im GET erlaubt
{"key": "matrix_password", ..., "sensitive": True},
{"key": "robot_host", ..., "sensitive": False},
```

`GET /api/settings` liefert nur Keys mit `sensitive=False`.

---

## Erweiterbarkeit

### Settings-Schema im SECRET_REGISTRY

Die Registry wird von einem reinen Key-Label-Mapping zu einem
vollständigen Schema ausgebaut. Jede neue Phase kann eigene Keys
mit Validierungsregeln anmelden:

```python
class SecretRegistryEntry(TypedDict, total=False):
    key: str                    # Pflicht
    label: str                  # Pflicht: Anzeigename
    category: str               # Pflicht: Kategorie-Name
    sensitive: bool             # Default: True – nie in GET zurückgeben
    requires_restart: bool      # Default: False
    type: str                   # "str" | "int" | "float" | "url" | "email" | "bool"
    min: float | int            # für type=int/float
    max: float | int            # für type=int/float
    pattern: str                # Regex-Pattern für type=str
    description: str            # Tooltip-Text im Frontend
    link: str                   # Direktlink zum Anbieter-Dashboard
```

Beispiel mit allen Feldern:

```python
{
    "key": "brave_api_key",
    "label": "Brave Search API Key",
    "category": "Suche & Karten",
    "sensitive": True,
    "requires_restart": True,
    "type": "str",
    "pattern": r"^BSA[A-Za-z0-9_-]{30,}$",  # BSA-Präfix + 30+ alphanumerische/Trennzeichen
    "description": "API Key für Brave Web Search. Kostenlos bis 2000 Anfragen/Monat.",
    "link": "https://brave.com/search/api/",
},
```

### Dynamische Registrierung durch andere Module

Neue Module können eigene Keys beim Start anmelden, ohne die zentrale
`SECRET_REGISTRY`-Liste zu editieren:

```python
# In settings_dashboard.py:
class SettingsDashboard:
    _registry: list[SecretRegistryEntry] = list(SECRET_REGISTRY)  # Kopie

    @classmethod
    def register_key(cls, entry: SecretRegistryEntry) -> None:
        """Registriert einen weiteren Key in der Registry.
        
        Aufruf idealerweise vor dem Instanziieren des Dashboards,
        z.B. im __init__.py des jeweiligen Moduls.
        """
        if not any(e["key"] == entry["key"] for e in cls._registry):
            cls._registry.append(entry)
```

Beispiel-Aufruf aus einem zukünftigen Modul:

```python
# src/elder_berry/tools/my_new_tool.py
from elder_berry.web.settings_dashboard import SettingsDashboard

SettingsDashboard.register_key({
    "key": "my_new_api_key",
    "label": "My New Service API Key",
    "category": "Dienste",
    "link": "https://example.com/api",
})
```

### Settings-Change-Callbacks (Observer-Pattern)

Andere Komponenten können auf Änderungen reagieren ohne das Dashboard
zu kennen:

```python
class SettingsDashboard:
    def __init__(self, ...):
        self._change_callbacks: dict[str, list[Callable[[str], None]]] = {}

    def on_change(self, key: str, callback: Callable[[str], None]) -> None:
        """Registriert einen Callback für Änderungen an einem Key.
        
        Callback-Signatur: callback(new_value: str) -> None
        """
        self._change_callbacks.setdefault(key, []).append(callback)

    def _notify_change(self, key: str, new_value: str) -> None:
        for cb in self._change_callbacks.get(key, []):
            try:
                cb(new_value)
            except Exception as e:
                logger.error("Callback-Fehler für '%s': %s", key, e)
```

Anwendungsfall: WeatherClient registriert sich für `weather_city` –
bei Änderung aktualisiert er intern die Stadt, ohne dass Saleria
neu gestartet werden muss:

```python
dashboard.on_change("weather_city", weather_client.set_city)
dashboard.on_change("weather_latitude", weather_client.set_latitude)
```

### Settings-Export / -Import (Backup & Migration)

Für Backups und Instanz-Migrationen: Export aller nicht-sensitiven Settings
sowie der Key-Namen (ohne Values) der sensitiven Settings.

```python
GET  /api/settings/export
  Response: {
    "export_version": 1,
    "exported_at": "2026-04-05T10:00:00Z",
    "non_sensitive": {
        "weather_city": "Berlin",
        "weather_latitude": "52.52",
        "briefing_time": "07:30",
        ...
    },
    "sensitive_keys_set": ["anthropic_api_key", "matrix_access_token", ...]
  }
```

Der Export enthält **keine sensitiven Werte** – er zeigt nur welche Keys
gesetzt sind. Damit kann eine neue Instanz vorbereitet werden (welche Keys
müssen noch gesetzt werden?).

Import ist **nicht** vorgesehen – neue Instanzen nutzen den Setup-Wizard
(Phase 46).

### Neue Settings-Sektion hinzufügen

Checkliste für zukünftige Phasen die eigene Dashboard-Sektionen brauchen:

1. Keys in `SECRET_REGISTRY` eintragen (oder `register_key()` nutzen)
2. API-Endpunkte in `settings_dashboard.py` ergänzen
3. HTML-Card in `settings_dashboard.html` ergänzen
4. Change-Callbacks bei Bedarf registrieren
5. Tests für neue Endpunkte schreiben
6. `HELP_TEXT`-äquivalent im Frontend ergänzen

---

## Nutzen & UX

### "Verbindung testen"-Button pro API-Key

Wiederverwendung der `SetupTests`-Klasse aus Phase 46. Für jeden
testbaren Service erscheint ein [Testen]-Button neben dem Key-Eingabefeld.

```python
POST /api/secrets/test
  Body:    {"key": "anthropic_api_key"}
  Response: {"success": true, "detail": "claude-sonnet-4-6 erreichbar"}

POST /api/secrets/test
  Body:    {"key": "groq_api_key"}
  Response: {"success": false, "detail": "401 Unauthorized – Key ungültig?"}
```

**Testbare Keys** (via SetupTests-Methoden):

| Key | Test-Methode |
|-----|-------------|
| `anthropic_api_key` | `SetupTests.test_anthropic()` |
| `groq_api_key` | `SetupTests.test_groq()` |
| `brave_api_key` | `SetupTests.test_brave()` |
| `google_maps_api_key` | `SetupTests.test_google_maps()` |
| `matrix_access_token` | `SetupTests.test_matrix()` (nutzt gespeicherte Matrix-Keys) |
| `nextcloud_app_password` | `SetupTests.test_nextcloud()` (nutzt gespeicherte NC-Keys) |
| `email_password` | `SetupTests.test_email()` (nutzt gespeicherte Mail-Keys) |
| `elevenlabs_api_key` | `SetupTests.test_elevenlabs()` |

Nicht-testbare Keys (keine API-Verbindung möglich): `weather_city`,
`robot_host` (Ping-Test möglich aber kein sinnvoller API-Test).

### Letzter-Änderungszeitpunkt pro Key

Die `GET /api/secrets/status`-Response wird um `updated_at` ergänzt:

```json
{
  "key": "anthropic_api_key",
  "label": "Claude API",
  "is_set": true,
  "updated_at": "2026-03-15T14:23:00Z"
}
```

**Implementierung**: SecretStore speichert ein separates Metadaten-Dict
mit Timestamps – kein Schema-Bruch der bestehenden `secrets.enc`:

```python
# Separates Metadaten-File: ~/.elder-berry/secrets_meta.json (unverschlüsselt)
{
  "anthropic_api_key": {"updated_at": "2026-03-15T14:23:00Z"},
  "groq_api_key": {"updated_at": "2026-04-01T09:00:00Z"}
}
```

Das Metadaten-File enthält keine sensitiven Werte – keine Verschlüsselung nötig.

**Sicherheitsabwägung**: Die Key-Namen (z.B. `anthropic_api_key`) stehen
unverschlüsselt in der Datei. Ein Angreifer mit Dateisystem-Zugriff erfährt
damit welche Dienste konfiguriert sind. Da jedoch der Dateisystem-Zugriff
bereits Zugang zum verschlüsselten `secrets.enc` bedeutet (und damit den
Key-Namen-Rückschluss über die Registry sowieso erlaubt), ist der Mehrwert
der Verschlüsselung hier marginal. **Voraussetzung**: Das Verzeichnis
`~/.elder-berry/` ist durch OS-Dateisystemberechtigungen geschützt (nur
der Saleria-Benutzer hat Lese-/Schreibzugriff).

### Suchfeld / Filter in der Key-Tabelle

Client-seitiger Filter ohne Backend-Änderung:

```javascript
// In audio_dashboard.html / settings_dashboard.html:
const filterInput = document.getElementById('key-filter');
filterInput.addEventListener('input', () => {
    const term = filterInput.value.toLowerCase();
    document.querySelectorAll('.key-row').forEach(row => {
        const keyName = row.dataset.key.toLowerCase();
        const label   = row.dataset.label.toLowerCase();
        row.style.display = (keyName.includes(term) || label.includes(term))
            ? '' : 'none';
    });
});
```

### Direktlinks zu API-Provider-Dashboards

Der `link`-Eintrag aus dem Registry-Schema wird im Frontend als
[🔗]-Icon neben dem Key-Namen angezeigt. Kein eigener Text nötig –
der Link führt direkt zur Provider-Seite.

| Key | Link-Ziel |
|-----|-----------|
| `anthropic_api_key` | https://console.anthropic.com/ |
| `groq_api_key` | https://console.groq.com/ |
| `elevenlabs_api_key` | https://elevenlabs.io/app/speech-synthesis |
| `brave_api_key` | https://brave.com/search/api/ |
| `google_maps_api_key` | https://console.cloud.google.com/ |

### Dashboard-Health-Widget

Eine kompakte Status-Zeile am Seitenanfang zeigt den Gesundheitszustand:

```
● Saleria läuft  |  ● Anthropic OK  |  ● Ollama OK  |  ● Matrix verbunden
```

Daten kommen vom bestehenden `/health`-Endpoint, der um mehr Felder
erweitert wird:

```python
GET /health
  Response: {
    "status": "ok",
    "hostname": "tower",
    "saleria_running": true,
    "matrix_connected": true,
    "llm_backend": "anthropic",
    "uptime_seconds": 3600
  }
```

Das Widget fragt `/health` alle 30 Sekunden ab (Client-seitiges Polling).

### Kategorien einklappbar (Accordion)

Die API-Key-Tabelle nach Kategorie gruppiert mit Accordion-UI:
Standard: alle ausgeklappt. Nutzer kann Kategorien einklappen.
Zustand wird in `localStorage` gespeichert.

---

## Tests (aktualisiert)

### test_settings_dashboard_api.py (~30 Tests)

```
API-Status:
- test_secrets_status_all_keys: Alle Registry-Keys in Response
- test_secrets_status_set_vs_unset: is_set korrekt für gesetzte/fehlende Keys
- test_secrets_status_no_secret_store: available=false wenn kein SecretStore
- test_secrets_status_grouped: Kategorien korrekt gruppiert
- test_secrets_status_sensitive_hidden: sensitive=True Keys nicht in /api/settings
- test_secrets_status_updated_at: updated_at im Status vorhanden
- test_secrets_set_new_key: Neuen Key setzen → is_set wird true
- test_secrets_set_update: Bestehenden Key überschreiben
- test_secrets_set_empty_value: Leerer Wert → 400
- test_secrets_set_no_body: Kein Body → 400
- test_secrets_set_value_too_long: Value > 4096 Zeichen → 400
- test_secrets_set_invalid_key_chars: Key mit Sonderzeichen → 400
- test_secrets_set_type_validation_int: int-Key mit ungültigem Wert → 400
- test_secrets_set_type_validation_url: url-Key ohne http:// → 400
- test_secrets_delete_existing: Key löschen → is_set wird false
- test_secrets_delete_nonexistent: Nicht vorhandener Key → 404
- test_secrets_delete_confirmation: Zweistufiges Löschen im UI (Frontend-Test)

LLM-Umschalter:
- test_llm_status_api_preferred: Default-Modus korrekt
- test_llm_status_both_available: primary + fallback available
- test_llm_status_ollama_only: Nur Fallback verfügbar
- test_llm_mode_switch_local: Umschalten auf local_only
- test_llm_mode_switch_api: Zurück auf api_preferred
- test_llm_mode_invalid: Ungültiger Modus → 400
- test_llm_mode_no_router: Kein LLMRouter → available=false
- test_llm_mode_persisted_in_secret_store: Mode-Wechsel speichert in SecretStore

Settings:
- test_settings_get_all: Alle nicht-sensitiven Settings in Response
- test_settings_update_single: Einzelnes Setting ändern
- test_settings_update_multiple: Mehrere Settings gleichzeitig
- test_settings_export: Export enthält non_sensitive + sensitive_keys_set

Verbindungstests:
- test_secrets_test_anthropic_valid: Test mit gültigem Key → success
- test_secrets_test_anthropic_invalid: Test mit ungültigem Key → success=false
- test_secrets_test_not_testable: Key ohne Test-Methode → 404

Health:
- test_health_contains_required_fields: Alle neuen Felder im Response
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

### test_settings_stability.py (~8 Tests)

```
- test_concurrent_writes_no_corruption: 20 parallele Writes → kein Datenverlust
- test_secret_store_corrupt_graceful: korrumpierte secrets.enc → Dashboard startet
- test_write_lock_serializes: asyncio.Lock verhindert Race Condition
- test_audit_log_on_set: AUDIT-Log-Eintrag bei set()
- test_audit_log_on_delete: AUDIT-Log-Eintrag bei delete()
- test_restart_hint_flag: requires_restart-Keys liefern Flag im Response
- test_change_callback_called: on_change-Callback wird aufgerufen
- test_change_callback_error_isolated: Fehler im Callback bricht nicht ab
```

---

## Implementierungsschritte (aktualisiert)

1. **SECRET_REGISTRY erweitern**: `sensitive`, `requires_restart`, `type`, `min/max`,
   `pattern`, `description`, `link` Felder hinzufügen
2. **Validierungsfunktion**: zentrale `_validate_secret(key, value)` in dashboard.py
3. **LLMRouter erweitern**: `mode` Property + Setter + `_select_client` Anpassung
4. **asyncio.Lock**: Write-Lock in `SettingsDashboard.__init__` + alle POST-Handler
5. **API-Endpoints Secrets**: `status`, `set`, `delete`, `test`
6. **API-Endpoints LLM**: `status`, `mode`
7. **API-Endpoints Settings**: `GET`, `POST`, `export`
8. **Security-Middleware**: `SecurityHeadersMiddleware` + CORS-Origin aus SecretStore
9. **Audit-Logging**: in allen schreibenden Handlers
10. **Metadaten-Timestamps**: `updated_at` in separatem `secrets_meta.json`
11. **Change-Callbacks**: `on_change()` + `_notify_change()` in SettingsDashboard
12. **HTML-Template**: 3 neue Cards + Health-Widget + Suchfeld + Accordion +
    [Testen]-Buttons + Direktlinks + zweistufiges Löschen
13. **Integration `start_saleria.py`**: LLM-Mode aus SecretStore, LLMRouter + Callbacks
14. **Tests**: `test_settings_dashboard_api.py` + `test_llm_router_mode.py`
    + `test_settings_stability.py`
15. **Commit**: `feature/phase-45-settings-dashboard`
