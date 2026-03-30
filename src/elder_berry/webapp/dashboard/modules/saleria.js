/**
 * SaleriaModule – Zeigt Saleria-Status (Tower-abhängig).
 * Graceful offline wenn Tower nicht erreichbar.
 */
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
        const status = await this.apiFetch(`${this.config.tower_url}/health`);
        const dot  = document.getElementById("saleria-dot");
        const info = document.getElementById("saleria-info");

        if (!status) {
            if (dot) dot.className = "status-dot error";
            if (info) info.textContent = "Tower offline";
            if (this.container) this.container.classList.add("module-offline");
            return;
        }

        if (this.container) this.container.classList.remove("module-offline");

        const saleriaRunning = status.saleria_running ?? false;
        if (dot) dot.className = `status-dot ${saleriaRunning ? "ok" : "warn"}`;

        if (info) {
            if (saleriaRunning) {
                info.textContent = status.last_interaction
                    ? `Letzte Interaktion: ${new Date(status.last_interaction).toLocaleTimeString("de")}`
                    : "Aktiv";
            } else {
                info.textContent = "Saleria inaktiv";
            }
        }
    }
}
