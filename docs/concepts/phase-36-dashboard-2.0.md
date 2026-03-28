# Phase 36 – Dashboard 2.0 (Modulare Smart Home PWA)

## Übersicht

Dashboard 2.0 ist eine Progressive Web App (PWA) auf dem Rootserver.
Sie dient als modularer Container für alle Phase-36-Steuerungsfunktionen
und ist auf Handy installierbar.

**Abgrenzung zum bestehenden AudioDashboard:**

| | AudioDashboard (v1) | Dashboard 2.0 |
|---|---|---|
| Zweck | Dev-Settings, Audio-Routing | Alltagssteuerung |
| Zielgerät | Desktop-Browser | Handy (PWA) |
| Hosting | Tower :8090 | Rootserver HTTPS |
| Zugang | Lokal | Heimnetz / VPN |
| Weiterentwicklung | eingefroren | aktiv, modular |

## Kernprinzip: Modul-Architektur

Jedes Modul ist eine eigenständige Einheit:
- Eigene HTML-Sektion (`<section class="module" id="harmony">`)
- Eigene JS-Klasse (`HarmonyModule`, `HAModule`, ...)
- Eigenes API-Ziel (RPi5, Tower, Rootserver)
- Kann ein- und ausgeblendet werden wenn Dienst nicht verfügbar

```
Dashboard 2.0
├── Modul: Harmony Remote   → RPi5 :8001/harmony/*
├── Modul: HA Control       → RPi5 :8001/ha/*       (Phase 36.3)
├── Modul: Saleria Status   → Tower :8000/status     (wenn Tower an)
├── Modul: System           → RPi5 :8001/health      (immer)
└── Modul: [erweiterbar]
```

## Modul-Verfügbarkeit ohne Tower

```
Tower aus:
  ✅ Harmony Remote    (RPi5 direkt)
  ✅ HA Control        (RPi5 direkt)
  ✅ System-Status     (RPi5 direkt)
  ⚠️ Saleria-Status   (zeigt "offline", kein Fehler)

Tower an:
  ✅ alles oben
  ✅ Saleria-Chat / Status aktiv
```

---

## Dateistruktur

```
src/elder_berry/webapp/dashboard/
├── index.html          ← Shell + Module-Loader
├── manifest.json       ← PWA-Manifest
├── sw.js               ← Service Worker (Offline-Cache)
├── style.css           ← Shared Design Tokens
└── modules/
    ├── harmony.js      ← HarmonyModule (Phase 36.1)
    ├── ha.js           ← HomeAssistantModule (Phase 36.3)
    ├── saleria.js      ← SaleriaStatusModule
    └── system.js       ← SystemModule
```

Deployment: Rootserver unter `/dashboard/`
Nginx vhost: `dashboard.last-strawberry.com` oder Unterverzeichnis

---

## Design-System

Weiterführung der bestehenden Ästhetik (AudioDashboard):
- Hintergrund: `#1a1a2e` (bereits etabliert)
- Cards: `#16213e`
- Akzent: `#7c3aed` (Saleria-Lila, konsistent mit Avatar)
- Status-Grün: `#10b981`
- Status-Rot: `#ef4444`
- Font: System-Stack (`-apple-system, BlinkMacSystemFont, "Segoe UI"`)
- Border-Radius Cards: `16px`
- Mobile-first: max-width 480px, kein Scroll nötig für Hauptfunktionen

### CSS Custom Properties (style.css)

```css
:root {
  --bg-primary:    #1a1a2e;
  --bg-card:       #16213e;
  --bg-card-hover: #1e2a4a;
  --accent:        #7c3aed;
  --accent-light:  #a78bfa;
  --text-primary:  #e0e0e0;
  --text-muted:    #8892a4;
  --status-ok:     #10b981;
  --status-warn:   #f59e0b;
  --status-error:  #ef4444;
  --radius-card:   16px;
  --radius-btn:    10px;
  --shadow-card:   0 8px 32px rgba(0,0,0,0.3);
}
```

---

## Module-System (index.html + module.js Pattern)

### Shell (index.html)

Lädt Module dynamisch, zeigt Lade-Status pro Modul,
rendert nur Module die konfiguriert sind.

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Saleria Dashboard</title>
  <link rel="manifest" href="manifest.json">
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="dashboard-header">
    <span class="header-title">Saleria</span>
    <span id="connection-status" class="status-dot"></span>
  </header>

  <main id="module-container"></main>

  <!-- Konfiguration (aus elder_berry.json via /dashboard/config Endpoint) -->
  <script>
    const DASHBOARD_CONFIG = {
      rpi5_url:  "http://192.168.50.220:8001",
      tower_url: "http://192.168.50.X:8000",
      modules:   ["harmony", "system", "saleria"]
      // "ha" wird ergänzt wenn Phase 36.3 deployed
    };
  </script>
  <script type="module" src="modules/loader.js"></script>
</body>
</html>
```

### Modul-Interface (alle Module implementieren dies)

```javascript
// modules/base.js
export class DashboardModule {
  constructor(config) {
    this.config = config;
    this.container = null;
  }

  // Pflicht: gibt HTML-String zurück
  render() { throw new Error("render() not implemented"); }

  // Optional: wird nach DOM-Insert aufgerufen
  async init() {}

  // Optional: Polling-Intervall in ms (0 = kein Polling)
  get pollInterval() { return 0; }

  // Hilfsmethode: fetch mit Timeout + Fehlerbehandlung
  async apiFetch(url, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    try {
      const res = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timeout);
      return res.ok ? await res.json() : null;
    } catch {
      clearTimeout(timeout);
      return null;  // null = Modul zeigt Offline-State, kein throw
    }
  }
}
```

### Module-Loader (modules/loader.js)

```javascript
import { DashboardModule } from "./base.js";

const moduleMap = {
  harmony: () => import("./harmony.js"),
  ha:      () => import("./ha.js"),
  saleria: () => import("./saleria.js"),
  system:  () => import("./system.js"),
};

async function loadModules() {
  const container = document.getElementById("module-container");
  for (const name of DASHBOARD_CONFIG.modules) {
    const loader = moduleMap[name];
    if (!loader) continue;
    try {
      const { default: ModuleClass } = await loader();
      const mod = new ModuleClass(DASHBOARD_CONFIG);
      const section = document.createElement("section");
      section.className = "module";
      section.id = `module-${name}`;
      section.innerHTML = mod.render();
      container.appendChild(section);
      await mod.init();
      if (mod.pollInterval > 0) {
        setInterval(() => mod.poll(), mod.pollInterval);
      }
    } catch (e) {
      console.warn(`Module ${name} failed to load:`, e);
    }
  }
}

loadModules();
```

---

## Modul 1: Harmony Remote (harmony.js)

Erste Implementierung. Direkt gegen RPi5 :8001/harmony/*.

```javascript
// modules/harmony.js
import { DashboardModule } from "./base.js";

export default class HarmonyModule extends DashboardModule {

  render() {
    return `
      <div class="card">
        <div class="card-header">
          <span class="card-title">Harmony</span>
          <span class="status-dot" id="harmony-status"></span>
        </div>
        <div id="harmony-current" class="current-activity">–</div>
        <div id="harmony-activities" class="button-grid"></div>
        <div class="volume-row">
          <button class="btn-icon" id="harmony-vol-down">–</button>
          <button class="btn-icon" id="harmony-mute">🔇</button>
          <button class="btn-icon" id="harmony-vol-up">+</button>
        </div>
        <button class="btn-danger" id="harmony-off">Alles aus</button>
      </div>`;
  }

  get pollInterval() { return 10000; }  // alle 10s Status abfragen

  async init() {
    await this.poll();
    document.getElementById("harmony-vol-up")
      .addEventListener("click", () => this.sendCommand("Receiver", "VolumeUp"));
    document.getElementById("harmony-vol-down")
      .addEventListener("click", () => this.sendCommand("Receiver", "VolumeDown"));
    document.getElementById("harmony-mute")
      .addEventListener("click", () => this.sendCommand("Receiver", "Mute"));
    document.getElementById("harmony-off")
      .addEventListener("click", () => this.powerOff());
  }

  async poll() {
    const base = this.config.rpi5_url;
    const [status, config] = await Promise.all([
      this.apiFetch(`${base}/harmony/status`),
      this.apiFetch(`${base}/harmony/config`),
    ]);

    const dot = document.getElementById("harmony-status");
    const current = document.getElementById("harmony-current");
    const grid = document.getElementById("harmony-activities");

    if (!status) {
      dot.className = "status-dot error";
      current.textContent = "Nicht verbunden";
      return;
    }

    dot.className = `status-dot ${status.connected ? "ok" : "warn"}`;
    current.textContent = status.current_activity ?? "Aus";

    if (config?.activities && grid.children.length === 0) {
      grid.innerHTML = config.activities
        .filter(a => a !== "PowerOff")
        .map(a => `<button class="btn-activity" data-activity="${a}">${a}</button>`)
        .join("");
      grid.querySelectorAll(".btn-activity").forEach(btn => {
        btn.addEventListener("click", () =>
          this.startActivity(btn.dataset.activity));
      });
    }
  }

  async startActivity(name) {
    await this.apiFetch(`${this.config.rpi5_url}/harmony/activity`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ activity: name }),
    });
    setTimeout(() => this.poll(), 1500);
  }

  async sendCommand(device, command) {
    await this.apiFetch(`${this.config.rpi5_url}/harmony/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device, command }),
    });
  }

  async powerOff() {
    await this.apiFetch(`${this.config.rpi5_url}/harmony/off`, {
      method: "POST" });
    setTimeout(() => this.poll(), 1500);
  }
}
```

---

## Modul 2: System (system.js) — immer sichtbar

```javascript
// modules/system.js
import { DashboardModule } from "./base.js";

export default class SystemModule extends DashboardModule {

  render() {
    return `
      <div class="card card-compact">
        <div class="card-header">
          <span class="card-title">System</span>
        </div>
        <div class="status-row">
          <span class="label">RPi5</span>
          <span class="status-dot" id="sys-rpi5"></span>
        </div>
        <div class="status-row">
          <span class="label">Tower</span>
          <span class="status-dot" id="sys-tower"></span>
        </div>
        <div class="status-row">
          <span class="label">Saleria</span>
          <span class="status-dot" id="sys-saleria"></span>
        </div>
      </div>`;
  }

  get pollInterval() { return 30000; }

  async init() { await this.poll(); }

  async poll() {
    const rpi5  = await this.apiFetch(`${this.config.rpi5_url}/health`);
    const tower = await this.apiFetch(`${this.config.tower_url}/health`);

    this._setDot("sys-rpi5",   rpi5  !== null);
    this._setDot("sys-tower",  tower !== null);
    this._setDot("sys-saleria", tower?.saleria_running ?? false);
  }

  _setDot(id, ok) {
    const el = document.getElementById(id);
    if (el) el.className = `status-dot ${ok ? "ok" : "error"}`;
  }
}
```

---

## Modul 3: Saleria Status (saleria.js) — optional, Tower-abhängig

```javascript
// modules/saleria.js
import { DashboardModule } from "./base.js";

export default class SaleriaModule extends DashboardModule {

  render() {
    return `
      <div class="card card-compact">
        <div class="card-header">
          <span class="card-title">Saleria</span>
          <span class="status-dot" id="saleria-dot"></span>
        </div>
        <div id="saleria-info" class="muted-text">Verbinde...</div>
      </div>`;
  }

  get pollInterval() { return 30000; }
  async init() { await this.poll(); }

  async poll() {
    const status = await this.apiFetch(`${this.config.tower_url}/status`);
    const dot  = document.getElementById("saleria-dot");
    const info = document.getElementById("saleria-info");
    if (!status) {
      dot.className = "status-dot error";
      info.textContent = "Tower offline";
      return;
    }
    dot.className = "status-dot ok";
    info.textContent = status.last_seen
      ? `Zuletzt aktiv: ${new Date(status.last_seen).toLocaleTimeString("de")}`
      : "Bereit";
  }
}
```

---

## Modul 4: Home Assistant (ha.js) — Platzhalter für Phase 36.3

```javascript
// modules/ha.js
import { DashboardModule } from "./base.js";

export default class HomeAssistantModule extends DashboardModule {

  render() {
    return `
      <div class="card">
        <div class="card-header">
          <span class="card-title">Smart Home</span>
          <span class="status-dot" id="ha-status"></span>
        </div>
        <div id="ha-scenes" class="button-grid"></div>
        <div id="ha-devices" class="device-list"></div>
      </div>`;
  }

  // Implementierung in Phase 36.3 wenn HomeAssistantAdapter deployed
  get pollInterval() { return 15000; }
  async init() { await this.poll(); }
  async poll() { /* TODO: Phase 36.3 */ }
}
```

---

## PWA: manifest.json + Service Worker

### manifest.json

```json
{
  "name": "Saleria Dashboard",
  "short_name": "Saleria",
  "description": "Smart Home Steuerung",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#1a1a2e",
  "theme_color": "#7c3aed",
  "start_url": "/dashboard/",
  "scope": "/dashboard/",
  "icons": [
    {"src": "/dashboard/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/dashboard/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

### sw.js (Service Worker — Offline-Cache)

```javascript
const CACHE = "saleria-dashboard-v1";
const STATIC = [
  "/dashboard/",
  "/dashboard/index.html",
  "/dashboard/style.css",
  "/dashboard/manifest.json",
  "/dashboard/modules/base.js",
  "/dashboard/modules/loader.js",
  "/dashboard/modules/harmony.js",
  "/dashboard/modules/system.js",
  "/dashboard/modules/saleria.js",
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC))
  );
});

self.addEventListener("fetch", e => {
  // API-Calls nie cachen (immer live oder Fehler)
  if (e.request.url.includes(":8001") ||
      e.request.url.includes(":8000")) return;
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
```

---

## Nginx (Rootserver)

```nginx
# /etc/nginx/sites-available/saleria-dashboard
server {
    listen 443 ssl;
    server_name dashboard.last-strawberry.com;

    ssl_certificate     /etc/letsencrypt/live/last-strawberry.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/last-strawberry.com/privkey.pem;

    # Nur Heimnetz (Änderung wenn VPN eingerichtet)
    allow 192.168.50.0/24;
    deny all;

    root /var/www/saleria-dashboard;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Deploy-Skript (Tower → Rootserver):
```bash
# scripts/deploy_dashboard.sh
rsync -avz src/elder_berry/webapp/dashboard/ \
    user@rootserver:/var/www/saleria-dashboard/
```

---

## Implementierungsreihenfolge

```
Schritt 1 (mit Phase 36.1):
  style.css + index.html Shell + loader.js + base.js
  system.js (immer sichtbar, einfachstes Modul)
  harmony.js (Kern von 36.1)
  manifest.json + sw.js
  Nginx + Deploy-Skript

Schritt 2 (nach Phase 36.1 stabil):
  saleria.js (braucht Tower /status Endpoint)

Schritt 3 (mit Phase 36.3):
  ha.js ausarbeiten
  DASHBOARD_CONFIG.modules += "ha"

Schritt 4 (nach Phase 37.1):
  alexa.js — Skill-Status, manuelle Trigger
```

## Testliste (~15 Tests)

Keine echten Unit-Tests (reines JS/HTML) — stattdessen:

```
Manuelle Tests bei Deploy:
  Dashboard lädt auf Desktop-Chrome
  Dashboard lädt auf Mobile-Safari (iOS)
  Dashboard lädt auf Mobile-Chrome (Android)
  PWA installierbar (Manifest korrekt)
  Offline: statische Assets vorhanden (Service Worker)
  Offline: API-Fehler werden graceful behandelt (kein Crash)
  Harmony-Aktivitäten erscheinen nach Laden
  Aktivität starten: Status aktualisiert sich
  Lautstärke +/-: kein sichtbarer Fehler
  System-Modul: RPi5-Dot grün wenn erreichbar
  System-Modul: Tower-Dot grau wenn aus

Automatisierbare Tests (Playwright, optional):
  test_dashboard_loads_without_errors
  test_harmony_module_renders_activities
  test_system_module_shows_offline_gracefully
```

---

## Offene Entscheidungen

| Punkt | Optionen | Empfehlung |
|-------|---------|-----------|
| Subdomain | dashboard.last-strawberry.com vs. Unterverzeichnis | Subdomain (sauberere URLs) |
| CORS | RPi5 muss Dashboard-Origin erlauben | `allow_origins=["https://dashboard.last-strawberry.com"]` in FastAPI |
| Icon | eigenes Saleria-Icon | 192x192 + 512x512 PNG aus Avatar-Assets extrahieren |
| VPN-Zugang | Nur Heimnetz jetzt, VPN später | WireGuard auf Rootserver (eigene Phase) |
