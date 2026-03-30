/**
 * DashboardModule – Basisklasse für alle Dashboard-Module.
 *
 * Jedes Modul implementiert:
 *   render()       → HTML-String für die Modul-Sektion
 *   init()         → Setup nach DOM-Insert (optional)
 *   poll()         → Periodische Aktualisierung (optional)
 *   pollInterval   → Intervall in ms (0 = kein Polling)
 */
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
     * Gibt null zurück bei Fehler (Modul zeigt Offline-State).
     */
    async apiFetch(url, options = {}) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 3000);
        try {
            const res = await fetch(url, { ...options, signal: controller.signal });
            clearTimeout(timeout);
            return res.ok ? await res.json() : null;
        } catch {
            clearTimeout(timeout);
            return null;
        }
    }
}
