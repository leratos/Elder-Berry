# Phase 58 – Dashboard-Login + Avatar-Tab 🔐🎭

**Status:** Konzept (2026-04-16)
**Branch:** `feature/phase-58-dashboard-login-avatar`
**Roadmap-Referenz:** Folge-Phase nach 57 (Security-Härtung)

## 1. Ausgangslage

Das Dashboard ist über `fern.example.com` öffentlich erreichbar
(per dedizierter VPN-IP zugriffsbeschränkt). Phase 52 hat einen
statischen `X-Saleria-Settings-Token` als Schutz für *schreibende*
Endpoints eingeführt, Phase 57 hat den Setup-Wizard hinter den
First-Run-Gate gestellt. Drei Lücken bleiben:

- **L1 – VPN ist Single-Point-of-Failure:** Bei Fehlkonfiguration,
  VPN-Leak oder versehentlichem Direkt-Bind ist das Dashboard offen
  für jeden, der die Domain kennt.
- **L2 – Lesende Endpoints sind ungeschützt:** `/api/secrets/status`,
  `/api/settings/values`, `/api/system/*` antworten ohne Auth – ein
  Angreifer sieht z.B. welche API-Keys gesetzt sind.
- **L3 – Browser kennt den Token nicht:** Das Dashboard-JS sendet
  keinen `X-Saleria-Settings-Token`-Header. Schreibende Operationen
  via Web-UI laufen daher in 401, der Nutzer kann SecretStore-Werte
  nicht über das Dashboard editieren (regelmäßiger Pain-Point).

Zusätzlich fehlt im Dashboard ein eigener Tab für den **Avatar-Editor**
– dieser läuft aktuell unter `/avatar/editor` separat und ist ohne
direkten Link aus dem Dashboard heraus auffindbar.

## 2. Ziel

1. **Login-Layer** als zweite Verteidigungslinie über VPN/Token –
   schützt **lesend und schreibend** alle Settings-/System-Endpoints.
2. **Fernbedienung bleibt ohne Login** – Freundin & Gäste im LAN
   sollen TV/Denon weiter steuern können.
3. **Avatar-Editor als dritter Header-Tab** im Dashboard (hinter
   Login).
4. **L3 wird mitgelöst:** Eingeloggte Sessions akzeptieren
   schreibende Requests automatisch, ohne dass das JS einen Token
   kennt.

## 3. Sicherheitsmodell

```
┌─────────────────────────────────────────────────────────────┐
│  Schicht 1: VPN (NordVPN dedizierte IP)                     │
│  └─ schützt vor wahllosem Internet-Zugriff                  │
├─────────────────────────────────────────────────────────────┤
│  Schicht 2: DashboardAuthMiddleware (NEU, Phase 58)         │
│  └─ schützt /api/settings, /api/secrets, /api/system,       │
│     /api/llm, /api/avatar, /avatar/editor (auch GET!)       │
│  └─ verlangt HttpOnly-Session-Cookie eb_dashboard_session   │
│  └─ /harmony/* bleibt offen (Fernbedienung)                 │
├─────────────────────────────────────────────────────────────┤
│  Schicht 3: SettingsTokenMiddleware (Phase 52, erweitert)   │
│  └─ schützt schreibende Endpoints zusätzlich                │
│  └─ akzeptiert ENTWEDER X-Saleria-Settings-Token            │
│     ODER valides Session-Cookie (NEU)                       │
│  └─ CLI-Skripte können weiter mit Token arbeiten            │
└─────────────────────────────────────────────────────────────┘
```

### Cookie-Mechanik

- **Format:** `<base64(payload)>.<base64(hmac)>` mit
  `payload = {"iat": <ts>, "exp": <ts>}`
- **Signatur:** HMAC-SHA256 mit Secret aus `SecretStore`-Key
  `dashboard_session_secret` (auto-generiert beim ersten Start, 32 B
  Zufall).
- **Cookie:** `eb_dashboard_session`, `HttpOnly`, `SameSite=Lax`,
  `Secure` automatisch gesetzt wenn Request via HTTPS.
- **TTL:** Default 12 h, sliding (jeder authentifizierte Request
  erneuert das Expiry um TTL). Konfigurierbar via Setting
  `dashboard_session_hours` (Range 1–168).
- **Stateless:** Kein Server-Side-Session-Store nötig – Tower-Restart
  invalidiert alle Sessions automatisch (Secret bleibt, Cookies sind
  zeitsigniert; bei Wechsel des Secrets via CLI verfallen alle).

### Passwort-Speicherung

- **Hash:** `bcrypt` (cost factor 12) – im SecretStore unter
  `dashboard_password_hash`.
- **Klartext** wird nirgends persistiert.
- **Rotation:** über Setup-Wizard (Initial), `/api/dashboard/password`
  (im UI nach Login) oder `scripts/set_dashboard_password.py` (Reset).

## 4. Geschützte vs. offene Pfade

### Vom Login geschützt (auch GET)

- `/api/settings/*`
- `/api/secrets/*`
- `/api/system/*`
- `/api/llm/*`
- `/api/audio/*`, `/api/monitor/*`, `/api/timezone`,
  `/api/stt-timeout`, `/api/allowed-senders`
- `/api/avatar/*`
- `/avatar/editor`
- `/api/setup/*` (nur nach First-Run – während des Wizards offen)

### Offen (kein Login)

- `/` (Dashboard-HTML, sonst kein Login-UI darstellbar)
- `/static/*`, `/manifest.json`, `/favicon.ico`, `/sw.js`,
  `/icon-*.png`, `/style.css`, `/modules/*.js` (Static Assets)
- `/api/dashboard/login`, `/api/dashboard/logout`,
  `/api/dashboard/auth/status`
- `/harmony/*` (Fernbedienung – LAN-Gäste)
- `/api/setup/*` (während Wizard läuft)

## 5. Komponenten

### Backend

| Datei | Zweck |
|-------|-------|
| `web/dashboard_auth.py` | `DashboardAuthManager` – PW-Hash, Session-Cookie-Sign/Verify |
| `web/dashboard_auth_middleware.py` | `DashboardAuthMiddleware` – Pfad-basierter Login-Check |
| `web/settings_token_middleware.py` | erweitert: Cookie ODER Token |
| `web/settings_dashboard.py` | registriert Middleware + 4 neue Endpoints |
| `web/setup_wizard.py` | neuer Step „Dashboard-Passwort" (Pflicht) |
| `scripts/set_dashboard_password.py` | CLI-Reset-Tool |

### Frontend

| Datei | Zweck |
|-------|-------|
| `webapp/dashboard/index.html` | Login-Modal HTML, Avatar-Tab, Logout-Button |
| `webapp/dashboard/style.css` | Modal-Styles, Logout-Button |
| `webapp/dashboard/modules/auth.js` | Login-Flow, Status-Check, 401-Handler |
| `webapp/dashboard/modules/base.js` | `apiFetch` mit `credentials: "include"` + 401-Trigger |
| `webapp/dashboard/modules/loader.js` | `avatar` + `auth` in moduleMap, view-Mapping |
| `webapp/dashboard/modules/avatar.js` | echtes Avatar-Modul (Canvas-Preview, Save) |

### Endpoints

```
POST /api/dashboard/login          {password} → 200 + Cookie / 401
POST /api/dashboard/logout                    → 200 (löscht Cookie)
GET  /api/dashboard/auth/status               → {authenticated, expires_at, password_set}
POST /api/dashboard/password       {current_password, new_password} → 200 / 401
```

## 6. Setup-Wizard-Integration

Der Setup-Wizard fragt vor dem Abschluss ein Dashboard-Passwort ab.
Pflicht – ohne PW kein `setup_wizard_completed=true`. Das Passwort
wird via `DashboardAuthManager.set_password()` direkt im SecretStore
abgelegt.

Damit kann jeder neue Nutzer (z.B. dein Kollege) den Stack ohne
CLI-Eingriff aufsetzen.

## 7. Test-Plan

| Datei | Was |
|-------|-----|
| `tests/test_dashboard_auth.py` | bcrypt-Hash, Cookie-Sign/Verify, Expiry, sliding renewal, falsches PW |
| `tests/test_dashboard_auth_middleware.py` | Schutz GET+POST, Cookie-Validation, Wizard-Exemption, Harmony offen, statische Assets offen |
| `tests/test_settings_token_middleware.py` (Update) | Cookie-OR-Token |
| `tests/test_setup_wizard.py` (Update) | PW-Step ist Pflicht für Wizard-Abschluss |

Ziel: keine Regression in den bestehenden 338 Tests.

## 8. Dependencies

- **Neu:** `bcrypt` in `pyproject.toml` `[project.optional-dependencies]`
  Gruppe `windows` (Settings-Dashboard läuft nur auf Tower/Laptop).

## 9. Out of Scope (für spätere Phasen)

- Multi-User (aktuell ein einziges PW für Dashboard)
- TOTP/2FA als zweiter Faktor
- Audit-Log über Login-Versuche
- Brute-Force-Rate-Limit (aktuell akzeptabel weil hinter VPN+Login)
