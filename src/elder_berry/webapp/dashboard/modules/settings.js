/**
 * SettingsModule – Zentrale Übersicht und Bearbeitung für Phase 45 Settings.
 */
import { DashboardModule } from "./base.js";

export default class SettingsModule extends DashboardModule {
    render() {
        return `
        <div class="card">
            <div class="card-header">
                <span class="card-title">Settings</span>
                <span class="badge" id="settings-restart-badge">Lade...</span>
            </div>
            <div class="settings-summary" id="settings-summary"></div>
            <div class="settings-toolbar" id="settings-toolbar">
                <button class="toolbar-button active" data-filter="all">Alle</button>
                <button class="toolbar-button" data-filter="high">High Risk</button>
                <button class="toolbar-button" data-filter="restart">Neustart nötig</button>
            </div>
            <div class="settings-groups" id="settings-groups"></div>
        </div>`;
    }

    get pollInterval() { return 30000; }

    async init() {
        this.currentFilter = "all";
        await this.refresh();
        this._bindToolbar();
    }

    async poll() {
        await this.refresh();
    }

    async refresh() {
        const [schemaRes, valuesRes, statusRes] = await Promise.all([
            this.apiFetch(`${this.config.tower_url}/api/settings/schema`),
            this.apiFetch(`${this.config.tower_url}/api/settings/values`),
            this.apiFetch(`${this.config.tower_url}/api/settings/status`),
        ]);

        if (!schemaRes || !valuesRes || !statusRes) {
            this._renderError();
            return;
        }

        this.schema = schemaRes.settings || [];
        this.values = valuesRes.values || {};
        this.status = statusRes;

        this._renderSummary();
        this._renderGroups();
    }

    _bindToolbar() {
        document.querySelectorAll("#settings-toolbar .toolbar-button").forEach(button => {
            button.addEventListener("click", () => {
                document.querySelectorAll("#settings-toolbar .toolbar-button").forEach(btn => btn.classList.remove("active"));
                button.classList.add("active");
                this.currentFilter = button.dataset.filter || "all";
                this._renderGroups();
            });
        });
    }

    _renderError() {
        const summary = document.getElementById("settings-summary");
        const groups = document.getElementById("settings-groups");
        const badge = document.getElementById("settings-restart-badge");
        if (summary) summary.textContent = "Settings aktuell nicht erreichbar.";
        if (groups) groups.innerHTML = "";
        if (badge) {
            badge.textContent = "offline";
            badge.className = "badge badge-error";
        }
    }

    _renderSummary() {
        const summary = document.getElementById("settings-summary");
        const badge = document.getElementById("settings-restart-badge");
        if (!summary || !badge) return;

        const restartCount = (this.status.restartRequiredSettings || []).length;
        const highRiskCount = this.schema.filter(item => item.riskLevel === "high").length;

        summary.innerHTML = `
            <div class="summary-grid">
                <div class="summary-item">
                    <span class="summary-label">Konfiguriert</span>
                    <strong>${this.status.configured}/${this.status.total}</strong>
                </div>
                <div class="summary-item">
                    <span class="summary-label">LLM-Modus</span>
                    <strong>${this._escape(this.status.llmMode || "unbekannt")}</strong>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Zeitzone</span>
                    <strong>${this._escape(this.status.timezone || "unbekannt")}</strong>
                </div>
                <div class="summary-item">
                    <span class="summary-label">High Risk</span>
                    <strong>${highRiskCount}</strong>
                </div>
            </div>
            <div class="settings-alert ${restartCount > 0 ? "warn" : "ok"}">
                ${restartCount > 0 ? `${restartCount} restart-relevante Settings sollten nach Änderungen neu gestartet werden.` : "Aktuell keine restart-relevanten Änderungen offen."}
            </div>
        `;

        badge.textContent = restartCount > 0 ? "Restart relevant" : "Live/ok";
        badge.className = restartCount > 0 ? "badge badge-warn" : "badge badge-ok";
    }

    _renderGroups() {
        const container = document.getElementById("settings-groups");
        if (!container) return;

        const visibleSettings = this.schema.filter(setting => this._matchesFilter(setting));
        const grouped = new Map();
        for (const setting of visibleSettings) {
            if (!grouped.has(setting.category)) grouped.set(setting.category, []);
            grouped.get(setting.category).push(setting);
        }

        if (!visibleSettings.length) {
            container.innerHTML = `<div class="settings-empty">Keine Settings für den aktuellen Filter.</div>`;
            return;
        }

        container.innerHTML = Array.from(grouped.entries()).map(([category, settings]) => `
            <section class="settings-group">
                <h3>${this._escape(category)}</h3>
                <div class="settings-grid">
                    ${settings.map(setting => this._renderSetting(setting)).join("")}
                </div>
            </section>
        `).join("");

        container.querySelectorAll(".settings-save").forEach(button => {
            button.addEventListener("click", (event) => this._onSave(event));
        });
    }

    _matchesFilter(setting) {
        if (this.currentFilter === "high") return setting.riskLevel === "high";
        if (this.currentFilter === "restart") return Boolean(setting.restartRequired);
        return true;
    }

    _renderSetting(setting) {
        const value = this.values?.[setting.key] ?? "";
        const riskClass = `risk-${setting.riskLevel || "low"}`;
        const restartHint = setting.restartRequired ? `<span class="setting-flag">Neustart nötig</span>` : "";
        const helpText = setting.helpText ? `<div class="setting-help">${this._escape(setting.helpText)}</div>` : "";
        const input = this._renderInput(setting, value);
        return `
            <div class="setting-card ${riskClass}">
                <div class="setting-header">
                    <label class="setting-label" for="setting-${setting.key}">${this._escape(setting.label)}</label>
                    <span class="setting-risk">${this._escape(setting.riskLevel || "low")}</span>
                </div>
                ${restartHint}
                ${helpText}
                ${input}
                <div class="setting-actions">
                    <button class="settings-save" data-key="${this._escape(setting.key)}">Speichern</button>
                    <span class="setting-status" id="status-${setting.key}"></span>
                </div>
            </div>
        `;
    }

    _renderInput(setting, value) {
        const safeValue = this._escape(String(value ?? ""));
        const id = `setting-${setting.key}`;
        if (setting.type === "textarea") {
            return `<textarea id="${id}" class="setting-input" rows="4">${safeValue}</textarea>`;
        }
        if (setting.type === "select") {
            const options = (setting.options || []).map(option => {
                const selected = option.value === value ? "selected" : "";
                return `<option value="${this._escape(option.value)}" ${selected}>${this._escape(option.label)}</option>`;
            }).join("");
            return `<select id="${id}" class="setting-input">${options}</select>`;
        }
        if (setting.type === "number") {
            const min = setting.minValue != null ? `min="${setting.minValue}"` : "";
            const max = setting.maxValue != null ? `max="${setting.maxValue}"` : "";
            return `<input id="${id}" class="setting-input" type="number" value="${safeValue}" ${min} ${max} />`;
        }
        return `<input id="${id}" class="setting-input" type="text" value="${safeValue}" />`;
    }

    async _onSave(event) {
        const key = event.currentTarget.dataset.key;
        const input = document.getElementById(`setting-${key}`);
        const status = document.getElementById(`status-${key}`);
        if (!input || !status) return;

        const value = input.value;
        status.textContent = "speichert...";
        status.className = "setting-status";

        const response = await fetch(`${this.config.tower_url}/api/settings/update`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ key, value }),
        });

        let data = null;
        try {
            data = await response.json();
        } catch {
            data = null;
        }

        if (!response.ok) {
            status.textContent = data?.error || "Fehler";
            status.className = "setting-status error";
            return;
        }

        status.textContent = data?.restartRequired ? "Gespeichert, Neustart nötig" : "Gespeichert";
        status.className = data?.restartRequired ? "setting-status warn" : "setting-status ok";
        await this.refresh();
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
