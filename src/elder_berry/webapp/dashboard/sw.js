// Phase 96-E: Bump bei jeder index.html-Aenderung, sonst behaelt ein
// installierter Service-Worker das alte HTML (hier: tote LAN-rpi5_url) cache-first.
const CACHE = "saleria-dashboard-v12";
const STATIC = [
    "/",
    "/index.html",
    "/style.css",
    "/modules/base.js",
    "/modules/loader.js",
    "/modules/harmony.js",
    "/modules/system.js",
    "/modules/saleria.js",
];

self.addEventListener("install", e => {
    e.waitUntil(
        caches.open(CACHE).then(c => c.addAll(STATIC))
    );
    self.skipWaiting();
});

self.addEventListener("activate", e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(k => k !== CACHE).map(k => caches.delete(k))
            )
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", e => {
    // API-Calls nie cachen – immer live oder Fehler
    if (e.request.url.includes("192.168.")) {
        return;
    }
    e.respondWith(
        caches.match(e.request).then(r => r || fetch(e.request))
    );
});
