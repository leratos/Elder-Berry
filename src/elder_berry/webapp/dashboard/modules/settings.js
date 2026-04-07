/**
 * SettingsModule – Zentrale Übersicht und Bearbeitung für Phase 45 Settings.
 */
import { DashboardModule } from "./base.js";

export default class SettingsModule extends DashboardModule {
    render() {
        return `
        <div class="card settings-shell">
            <div class="card-header">
                <span class="card-title">Settings</span>
                <span class="badge" id="settings-restart-badge">Lade...</span>
            </div>
            <div class="settings-overview" id="settings-overview">
                <div class="settings-summary" id="settings-summary"></div>
                <div class="settings-alert" id="settings-overview-alert"></div>
            </div>
            <div class="settings-layout">
                <section class="settings-panel settings-panel-overview">
                    <div class="settings-panel-header">
                        <h3>Overview</h3>
                        <p>Aktueller Zustand, Risiken und restart-relevante Hinweise.</p>
                    </div>
                    <div class="settings-insights" id="settings-insights"></div>
                </section>
                <section class="settings-panel settings-panel-edit">
                    <div class="settings-panel-header">
                        <h3>Edit</h3>
                        <p>Bekannte Settings gezielt ändern, ohne die Übersicht zu verlieren.</p>
                    </div>
                    <div class="settings-toolbar" id="settings-toolbar">
                        <button class="toolbar-button active" data-filter="all">Alle</button>
                        <button class="toolbar-button" data-filter="high">High Risk</button>
                        <button class="toolbar-button" data-filter="restart">Neustart nötig</button>
                    </div>
                    <div class="settings-groups" id="settings-groups"></div>
                </section>
                <section class="settings-panel settings-panel-secrets">
                    <div class="settings-panel-header">
                        <h3>API-Keys &amp; Secrets</h3>
                        <p>Status aller bekannten Keys – Werte werden nie angezeigt.</p>
                    </div>
                    <div class="settings-search">
                        <input type="text" id="secrets-filter" class="setting-input"
                               placeholder="Key oder Label filtern..." />
                    </div>
                    <div id="secrets-categories"></div>
                </section>
            </div>
        </div>`;
    }

    get pollInterval() { return 30000; }

    async init() {
        this.currentFilter = "all";
        this._deleteConfirmKey = null;
        this._deleteTimeout = null;
        await this.refresh();
        this._bindToolbar();
        this._bindSecretsFilter();
    }

    async poll() {
        await this.refresh();
    }

    async refresh() {
        const [schemaRes, valuesRes, statusRes, secretsRes] = await Promise.all([
            this.apiFetch(`/api/settings/schema`),
            this.apiFetch(`/api/settings/values`),
            this.apiFetch(`/api/settings/status`),
            this.apiFetch(`/api/secrets/status`),
        ]);

        if (!schemaRes || !valuesRes || !statusRes) {
            this._renderError();
            return;
        }

        this.schema = schemaRes.settings || [];
        this.values = valuesRes.values || {};
        this.status = statusRes;
        this.secrets = secretsRes;

        this._renderSummary();
        this._renderInsights();
        this._renderGroups();
        this._renderSecrets();
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
        const alert = document.getElementById("settings-overview-alert");
        const insights = document.getElementById("settings-insights");
        const groups = document.getElementById("settings-groups");
        const badge = document.getElementById("settings-restart-badge");
        if (summary) summary.textContent = "Settings aktuell nicht erreichbar.";
        if (alert) {
            alert.textContent = "Ohne Settings-Status sind Übersicht und Bearbeitung momentan eingeschränkt.";
            alert.className = "settings-alert warn";
        }
        if (insights) insights.innerHTML = "";
        if (groups) groups.innerHTML = "";
        if (badge) {
            badge.textContent = "offline";
            badge.className = "badge badge-error";
        }
    }

    _renderSummary() {
        const summary = document.getElementById("settings-summary");
        const alert = document.getElementById("settings-overview-alert");
        const badge = document.getElementById("settings-restart-badge");
        if (!summary || !alert || !badge) return;

        const restartCount = (this.status.restartRequiredSettings || []).length;
        const highRiskCount = this.schema.filter(item => item.riskLevel === "high").length;
        const mediumRiskCount = this.schema.filter(item => item.riskLevel === "medium").length;

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
                <div class="summary-item">
                    <span class="summary-label">Medium Risk</span>
                    <strong>${mediumRiskCount}</strong>
                </div>
            </div>
        `;

        alert.textContent = restartCount > 0
            ? `${restartCount} restart-relevante Settings sollten nach Änderungen neu gestartet werden.`
            : "Aktuell keine restart-relevanten Änderungen offen.";
        alert.className = restartCount > 0 ? "settings-alert warn" : "settings-alert ok";

        badge.textContent = restartCount > 0 ? "Restart relevant" : "Live/ok";
        badge.className = restartCount > 0 ? "badge badge-warn" : "badge badge-ok";
    }

    _renderInsights() {
        const container = document.getElementById("settings-insights");
        if (!container) return;

        const restartItems = this.status.restartRequiredSettings || [];
        const highRiskItems = this.schema.filter(item => item.riskLevel === "high");
        const categoryEntries = Object.entries(this.status.categories || {});

        container.innerHTML = [
            this._renderInsightCard(
                "Restart-Folgen",
                restartItems.length
                    ? `${restartItems.length} Settings haben Betriebsfolgen nach Änderungen.`
                    : "Keine offenen restart-relevanten Änderungen.",
                restartItems.length ? restartItems.join(", ") : "Änderungen können aktuell ohne zusätzlichen Restart-Hinweis geprüft werden.",
                restartItems.length ? "warn" : "ok"
            ),
            this._renderInsightCard(
                "Risiko-Fokus",
                `${highRiskItems.length} High-Risk-Settings im Registry-Scope.`,
                highRiskItems.length
                    ? highRiskItems.map(item => item.label).join(", ")
                    : "Aktuell keine High-Risk-Settings erkannt.",
                highRiskItems.length ? "warn" : "ok"
            ),
            this._renderInsightCard(
                "Kategorien",
                `${categoryEntries.length} Settings-Kategorien aktiv.`,
                categoryEntries.length
                    ? categoryEntries.map(([key, value]) => `${key}: ${value}`).join(" · ")
                    : "Noch keine Kategorien verfügbar.",
                "neutral"
            ),
        ].join("");
    }

    _renderInsightCard(title, headline, detail, tone = "neutral") {
        return `
            <div class="settings-insight settings-insight-${this._escape(tone)}">
                <div class="settings-insight-title">${this._escape(title)}</div>
                <div class="settings-insight-headline">${this._escape(headline)}</div>
                <div class="settings-insight-detail">${this._escape(detail)}</div>
            </div>
        `;
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
                <div class="settings-group-header">
                    <h4>${this._escape(category)}</h4>
                    <span>${settings.length} Einträge</span>
                </div>
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
        const meta = `
            <div class="setting-meta">
                <span>Quelle: ${this._escape(setting.source || "registry")}</span>
                <span>Typ: ${this._escape(setting.type || "text")}</span>
            </div>
        `;
        const input = this._renderInput(setting, value);
        return `
            <div class="setting-card ${riskClass}">
                <div class="setting-header">
                    <label class="setting-label" for="setting-${setting.key}">${this._escape(setting.label)}</label>
                    <span class="setting-risk">${this._escape(setting.riskLevel || "low")}</span>
                </div>
                ${restartHint}
                ${helpText}
                ${meta}
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

        const response = await fetch(`/api/settings/update`, {
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

    // ----------------------------------------------------------
    // Secrets-Sektion: Accordion, Suchfeld, 2-Stufen-Löschen
    // ----------------------------------------------------------

    _bindSecretsFilter() {
        const input = document.getElementById("secrets-filter");
        if (!input) return;
        input.addEventListener("input", () => {
            const term = input.value.toLowerCase();
            document.querySelectorAll(".secret-row").forEach(row => {
                const key = (row.dataset.key || "").toLowerCase();
                const label = (row.dataset.label || "").toLowerCase();
                row.style.display = (key.includes(term) || label.includes(term)) ? "" : "none";
            });
        });
    }

    _renderSecrets() {
        const container = document.getElementById("secrets-categories");
        if (!container || !this.secrets || !this.secrets.available) {
            if (container) container.innerHTML = `<div class="settings-empty">Secrets nicht verfügbar.</div>`;
            return;
        }

        const savedState = this._loadAccordionState();
        container.innerHTML = (this.secrets.categories || []).map(cat => {
            const isOpen = savedState[cat.name] !== false; // Default: offen
            return `
            <div class="secrets-category">
                <div class="secrets-category-header" data-category="${this._escape(cat.name)}">
                    <span class="accordion-icon">${isOpen ? "▼" : "▶"}</span>
                    <strong>${this._escape(cat.name)}</strong>
                    <span class="secrets-category-count">${cat.keys.filter(k => k.is_set).length}/${cat.keys.length}</span>
                </div>
                <div class="secrets-category-body" style="${isOpen ? "" : "display:none"}">
                    <table class="secrets-table">
                        <thead><tr><th>Key</th><th>Label</th><th>Status</th><th>Aktionen</th></tr></thead>
                        <tbody>
                            ${cat.keys.map(k => this._renderSecretRow(k)).join("")}
                        </tbody>
                    </table>
                </div>
            </div>`;
        }).join("");

        this._bindAccordion(container);
        this._bindSecretActions(container);
    }

    _renderSecretRow(entry) {
        const statusIcon = entry.is_set ? "✅" : "❌";
        const linkHtml = entry.link
            ? `<a href="${this._escape(entry.link)}" target="_blank" rel="noopener" class="secret-link" title="Anbieter-Dashboard">🔗</a>`
            : "";
        const updatedAt = entry.updated_at
            ? `<span class="secret-updated" title="Zuletzt geändert">${new Date(entry.updated_at).toLocaleString()}</span>`
            : "";
        const restartBadge = entry.requires_restart
            ? `<span class="setting-flag setting-flag-small">Restart</span>`
            : "";

        return `
        <tr class="secret-row" data-key="${this._escape(entry.key)}" data-label="${this._escape(entry.label)}">
            <td class="secret-key">${this._escape(entry.key)} ${linkHtml} ${restartBadge}</td>
            <td>${this._escape(entry.label)}</td>
            <td class="secret-status">${statusIcon} ${updatedAt}</td>
            <td class="secret-actions">
                <button class="secret-edit-btn" data-key="${this._escape(entry.key)}" title="Setzen/Ändern">✏️</button>
                ${entry.is_set ? `<button class="secret-delete-btn" data-key="${this._escape(entry.key)}" title="Löschen">🗑️</button>` : ""}
            </td>
        </tr>
        <tr class="secret-edit-row" id="edit-row-${entry.key}" style="display:none">
            <td colspan="4">
                <div class="secret-edit-form">
                    <input type="password" class="setting-input secret-value-input"
                           id="secret-input-${entry.key}" placeholder="Neuer Wert..." />
                    <button class="secret-save-btn" data-key="${this._escape(entry.key)}">Speichern</button>
                    <button class="secret-cancel-btn" data-key="${this._escape(entry.key)}">Abbrechen</button>
                    <span class="secret-feedback" id="secret-feedback-${entry.key}"></span>
                </div>
            </td>
        </tr>`;
    }

    _bindAccordion(container) {
        container.querySelectorAll(".secrets-category-header").forEach(header => {
            header.addEventListener("click", () => {
                const body = header.nextElementSibling;
                const icon = header.querySelector(".accordion-icon");
                const cat = header.dataset.category;
                if (body.style.display === "none") {
                    body.style.display = "";
                    if (icon) icon.textContent = "▼";
                    this._saveAccordionState(cat, true);
                } else {
                    body.style.display = "none";
                    if (icon) icon.textContent = "▶";
                    this._saveAccordionState(cat, false);
                }
            });
        });
    }

    _loadAccordionState() {
        try {
            return JSON.parse(localStorage.getItem("secrets-accordion") || "{}");
        } catch { return {}; }
    }

    _saveAccordionState(category, isOpen) {
        const state = this._loadAccordionState();
        state[category] = isOpen;
        localStorage.setItem("secrets-accordion", JSON.stringify(state));
    }

    _bindSecretActions(container) {
        // Edit-Button: Zeile aufklappen
        container.querySelectorAll(".secret-edit-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                const key = btn.dataset.key;
                const editRow = document.getElementById(`edit-row-${key}`);
                if (editRow) editRow.style.display = editRow.style.display === "none" ? "" : "none";
            });
        });

        // Save-Button: Wert speichern
        container.querySelectorAll(".secret-save-btn").forEach(btn => {
            btn.addEventListener("click", () => this._onSecretSave(btn.dataset.key));
        });

        // Cancel-Button: Zeile zuklappen
        container.querySelectorAll(".secret-cancel-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                const editRow = document.getElementById(`edit-row-${btn.dataset.key}`);
                if (editRow) editRow.style.display = "none";
            });
        });

        // Delete-Button: 2-Stufen-Löschen
        container.querySelectorAll(".secret-delete-btn").forEach(btn => {
            btn.addEventListener("click", () => this._onSecretDelete(btn));
        });
    }

    async _onSecretSave(key) {
        const input = document.getElementById(`secret-input-${key}`);
        const feedback = document.getElementById(`secret-feedback-${key}`);
        if (!input || !feedback) return;

        const value = input.value;
        if (!value.trim()) {
            feedback.textContent = "Wert darf nicht leer sein.";
            feedback.className = "secret-feedback error";
            return;
        }

        feedback.textContent = "Speichere...";
        feedback.className = "secret-feedback";

        try {
            const res = await fetch("/api/secrets/set", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ key, value }),
            });
            const data = await res.json();
            if (!res.ok) {
                feedback.textContent = data.error || "Fehler";
                feedback.className = "secret-feedback error";
                return;
            }
            feedback.textContent = data.requires_restart ? "Gespeichert – Neustart nötig" : "Gespeichert";
            feedback.className = data.requires_restart ? "secret-feedback warn" : "secret-feedback ok";
            input.value = "";
            setTimeout(() => this.refresh(), 500);
        } catch (err) {
            feedback.textContent = "Netzwerkfehler";
            feedback.className = "secret-feedback error";
        }
    }

    _onSecretDelete(btn) {
        const key = btn.dataset.key;

        // Stufe 1: Bestätigungsmodus aktivieren
        if (this._deleteConfirmKey !== key) {
            // Reset vorherige Bestätigung
            if (this._deleteTimeout) clearTimeout(this._deleteTimeout);
            this._deleteConfirmKey = key;
            btn.textContent = "Wirklich?";
            btn.classList.add("confirm");
            // Nach 5 Sekunden zurücksetzen
            this._deleteTimeout = setTimeout(() => {
                this._deleteConfirmKey = null;
                btn.textContent = "🗑️";
                btn.classList.remove("confirm");
            }, 5000);
            return;
        }

        // Stufe 2: Tatsächlich löschen
        clearTimeout(this._deleteTimeout);
        this._deleteConfirmKey = null;
        btn.textContent = "...";
        fetch("/api/secrets/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ key }),
        }).then(res => {
            if (res.ok) {
                setTimeout(() => this.refresh(), 300);
            } else {
                btn.textContent = "Fehler";
                setTimeout(() => { btn.textContent = "🗑️"; btn.classList.remove("confirm"); }, 2000);
            }
        }).catch(() => {
            btn.textContent = "🗑️";
            btn.classList.remove("confirm");
        });
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
