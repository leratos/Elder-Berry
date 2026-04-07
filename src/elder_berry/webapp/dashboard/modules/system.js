/**
 * SystemModule – Zeigt RPi5/Tower/Saleria Health-Status.
 * Immer sichtbar, pollt alle 30s.
 */
import { DashboardModule } from "./base.js";

export default class SystemModule extends DashboardModule {
    render() {
        return `
        <div class="card">
            <div class="card-header">
                <span class="card-title">Systemstatus</span>
                <span class="badge" id="system-health-badge">Lade...</span>
            </div>
            <div class="settings-summary" id="system-summary"></div>
            <div class="settings-alert" id="system-alert"></div>
            <div class="settings-grid" id="system-grid"></div>
        </div>`;
    }

    get pollInterval() {
        return 30000;
    }

    async init() {
        await this.refresh();
    }

    async poll() {
        await this.refresh();
    }

    async refresh() {
        const [towerStatus, settingsStatus] = await Promise.all([
            this.apiFetch(`${this.config.tower_url}/health`),
            this.apiFetch(`${this.config.tower_url}/api/settings/status`),
        ]);

        const summary = document.getElementById("system-summary");
        const alert = document.getElementById("system-alert");
        const grid = document.getElementById("system-grid");
        const badge = document.getElementById("system-health-badge");
        if (!summary || !alert || !grid || !badge) return;

        if (!towerStatus) {
            summary.textContent = "Tower aktuell nicht erreichbar.";
            alert.textContent = "Ohne Tower-Health sind Runtime- und Settings-Signale unvollst?ndig.";
            alert.className = "settings-alert warn";
            grid.innerHTML = "";
            badge.textContent = "offline";
            badge.className = "badge badge-error";
            return;
        }

        const restartCount = settingsStatus?.restartRequiredSettings?.length || 0;
        const configured = settingsStatus?.configured ?? 0;
        const total = settingsStatus?.total ?? 0;

        summary.innerHTML = `
            <div>Hostname: <strong>${this._escape(towerStatus.hostname || "unbekannt")}</strong></div>
            <div>LLM-Modus: <strong>${this._escape(settingsStatus?.llmMode || "unbekannt")}</strong></div>
            <div>Zeitzone: <strong>${this._escape(settingsStatus?.timezone || "unbekannt")}</strong></div>
            <div>Settings: <strong>${configured}/${total}</strong> konfiguriert</div>
        `;

        alert.textContent = restartCount > 0
            ? `${restartCount} restart-relevante Settings sollten nach ?nderungen neu gestartet werden.`
            : "Aktuell keine restart-relevanten ?nderungen offen.";
        alert.className = restartCount > 0 ? "settings-alert warn" : "settings-alert ok";

        grid.innerHTML = [
            this._card("Tower", towerStatus.status === "ok" ? "Erreichbar" : "Unklar", "runtime", "low"),
            this._card("Saleria-Prozess", towerStatus.saleria_running ? "Läuft" : "Nicht aktiv", "service", towerStatus.saleria_running ? "low" : "medium"),
            this._card("Restart-Hinweis", restartCount > 0 ? `${restartCount} Settings sind restart-relevant.` : "Aktuell keine restart-relevanten Settings offen.", "ops", restartCount > 0 ? "medium" : "low"),
            this._card("Settings-Kategorien", this._formatCategories(settingsStatus?.categories || {}), "overview", "low"),
        ].join("");

        badge.textContent = restartCount > 0 ? "Achtung" : "OK";
        badge.className = restartCount > 0 ? "badge badge-warn" : "badge badge-ok";
    }

    _card(label, text, tag, risk) {
        return `
            <div class="setting-card risk-${this._escape(risk)}">
                <div class="setting-header">
                    <span class="setting-label">${this._escape(label)}</span>
                    <span class="setting-risk">${this._escape(tag)}</span>
                </div>
                <div class="setting-help">${this._escape(text)}</div>
            </div>`;
    }

    _formatCategories(categories) {
        const entries = Object.entries(categories);
        if (!entries.length) return "Keine Kategorien geladen.";
        return entries.map(([key, value]) => `${key}: ${value}`).join(" · ");
    }

    _escape(value) {
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }
}
