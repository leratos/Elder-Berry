/**
 * SystemModule – Zeigt RPi5/Tower/Saleria Health-Status.
 * Immer sichtbar, pollt alle 30s.
 */
import { DashboardModule } from "./base.js";

export default class SystemModule extends DashboardModule {

    render() {
        return `
        <div class="card card-compact">
            <div class="card-header">
                <span class="card-title">System</span>
            </div>
            <div class="status-row" id="sys-rpi5-row">
                <span class="label">RPi5</span>
                <span class="status-info">
                    <span class="value" id="sys-rpi5-info"></span>
                    <span class="status-dot" id="sys-rpi5"></span>
                </span>
            </div>
            <div class="status-row" id="sys-tower-row">
                <span class="label">Tower</span>
                <span class="status-info">
                    <span class="value" id="sys-tower-info"></span>
                    <span class="status-dot" id="sys-tower"></span>
                </span>
            </div>
            <div class="status-row" id="sys-saleria-row">
                <span class="label">Saleria</span>
                <span class="status-info">
                    <span class="value" id="sys-saleria-info"></span>
                    <span class="status-dot" id="sys-saleria"></span>
                </span>
            </div>
        </div>`;
    }

    get pollInterval() { return 30000; }

    async init() { await this.poll(); }

    async poll() {
        const rpi5  = await this.apiFetch(`${this.config.rpi5_url}/health`);
        const tower = await this.apiFetch(`${this.config.tower_url}/health`);

        this._updateRow("sys-rpi5", rpi5, rpi5 !== null);
        this._updateRow("sys-tower", tower, tower !== null);

        const saleriaOk = tower?.saleria_running ?? false;
        this._setDot("sys-saleria", saleriaOk);
        const saleriaInfo = document.getElementById("sys-saleria-info");
        if (saleriaInfo) {
            if (!tower) {
                saleriaInfo.textContent = "";
            } else {
                saleriaInfo.textContent = saleriaOk ? "aktiv" : "inaktiv";
            }
        }

        // Connection-Dot im Header
        const connDot = document.getElementById("connection-status");
        if (connDot) {
            connDot.className = `status-dot ${rpi5 !== null ? "ok" : "error"}`;
        }
    }

    _updateRow(prefix, data, online) {
        this._setDot(prefix, online);
        const info = document.getElementById(`${prefix}-info`);
        if (!info) return;

        if (!online) {
            info.textContent = "offline";
            return;
        }

        const parts = [];
        if (data.uptime != null) {
            parts.push(this._formatUptime(data.uptime));
        }
        if (data.cpu_temp != null) {
            parts.push(`${data.cpu_temp}°C`);
        }
        info.textContent = parts.join(" · ") || "online";
    }

    _setDot(id, ok) {
        const el = document.getElementById(id);
        if (el) el.className = `status-dot ${ok ? "ok" : "error"}`;
    }

    _formatUptime(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m`;
    }
}
