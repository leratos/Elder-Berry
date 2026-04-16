/**
 * DashboardModule – Basisklasse für alle Dashboard-Module.
 *
 * Jedes Modul implementiert:
 *   render()       → HTML-String für die Modul-Sektion
 *   init()         → Setup nach DOM-Insert (optional)
 *   poll()         → Periodische Aktualisierung (optional)
 *   pollInterval   → Intervall in ms (0 = kein Polling)
 */

// Globaler 401-Handler (von auth.js gesetzt). Gibt true zurück wenn der
// Caller den Request retryen kann, false wenn nicht (z.B. Login-Modal
// wurde geschlossen).
window.__dashboardOn401 = window.__dashboardOn401 || (async () => false);

export class DashboardModule {
    constructor(config) {
        this.config = config;
        this.container = null;
    }

    render() {
        throw new Error("render() not implemented");
    }

    async init() {}

    async poll() {}

    get pollInterval() { return 0; }

    /**
     * Fetch mit Timeout + graceful Fehlerbehandlung.
     * Schickt Cookies (für Dashboard-Login).
     * Bei 401: triggert Login-Modal und retried den Request einmal.
     * Bei anderen Fehlern: gibt null zurück (Modul zeigt Offline-State).
     */
    async apiFetch(url, options = {}) {
        return this._fetchWithRetry(url, options, /* retried= */ false);
    }

    async _fetchWithRetry(url, options, retried) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000);
        try {
            const res = await fetch(url, {
                ...options,
                credentials: "include",
                signal: controller.signal,
            });
            clearTimeout(timeout);
            if (res.status === 401 && !retried) {
                const ok = await window.__dashboardOn401();
                if (ok) {
                    return this._fetchWithRetry(url, options, true);
                }
                return null;
            }
            return res.ok ? await res.json() : null;
        } catch {
            clearTimeout(timeout);
            return null;
        }
    }
}
