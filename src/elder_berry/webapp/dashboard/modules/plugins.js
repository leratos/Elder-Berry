/**
 * PluginsModule – Read-Only Plugin-Inspector (Phase 77.5).
 *
 * Liest GET /api/plugins (hinter Dashboard-Login, R5 im Konzept) und
 * rendert eine Tabelle mit allen geladenen Plugins. Source-Filter +
 * Summary-Counter. Klick auf eine Zeile zeigt Manifest-Details.
 *
 * Pollt nicht: Plugin-Liste aendert sich nur bei Saleria-Restart, ein
 * Refresh-Button reicht.
 */
import { DashboardModule } from "./base.js";

const SOURCE_LABELS = {
    builtin: "Builtin",
    user_dir: "User-Dir",
    entry_point: "Entry-Point",
};

export default class PluginsModule extends DashboardModule {
    render() {
        return `
        <div class="card plugins-shell">
            <div class="card-header">
                <span class="card-title">Plugins</span>
                <span class="badge" id="plugins-summary-badge">Lade...</span>
            </div>
            <div class="settings-overview">
                <div class="settings-summary" id="plugins-summary"></div>
                <div class="settings-alert" id="plugins-alert"></div>
            </div>
            <div class="settings-toolbar" id="plugins-toolbar">
                <button class="toolbar-button active" data-source="all">Alle</button>
                <button class="toolbar-button" data-source="builtin">Builtin</button>
                <button class="toolbar-button" data-source="user_dir">User-Dir</button>
                <button class="toolbar-button" data-source="entry_point">Entry-Point</button>
                <button class="toolbar-button plugins-refresh" id="plugins-refresh">↻ Neu laden</button>
            </div>
            <div class="plugins-table-wrap" id="plugins-table-wrap"></div>
            <div class="plugins-detail" id="plugins-detail"></div>
        </div>`;
    }

    get pollInterval() { return 0; }

    async init() {
        this._sourceFilter = "all";
        this._selectedPlugin = null;
        this._bindToolbar();
        await this.refresh();
    }

    async refresh() {
        const data = await this.apiFetch("/api/plugins");
        if (!data) {
            this._renderError();
            return;
        }
        this._data = data;
        this._renderSummary();
        this._renderTable();
        this._renderDetail();
    }

    _bindToolbar() {
        document.querySelectorAll("#plugins-toolbar .toolbar-button").forEach(btn => {
            btn.addEventListener("click", () => {
                if (btn.id === "plugins-refresh") {
                    this.refresh();
                    return;
                }
                document
                    .querySelectorAll("#plugins-toolbar .toolbar-button")
                    .forEach(b => {
                        if (b.id !== "plugins-refresh") {
                            b.classList.remove("active");
                        }
                    });
                btn.classList.add("active");
                this._sourceFilter = btn.dataset.source || "all";
                this._renderTable();
            });
        });
    }

    _renderError() {
        // Codex P2 review: in-memory State + Detail-Pane leeren, sonst
        // koennen Filter-Klicks nach einem fehlgeschlagenen Refresh die
        // Tabelle aus veralteten Daten wiederbeleben, waehrend das Badge
        // "offline" sagt -- bei Incident/Debug-Sessions irrefuehrend.
        this._data = null;
        this._selectedPlugin = null;

        const summary = document.getElementById("plugins-summary");
        const alert = document.getElementById("plugins-alert");
        const wrap = document.getElementById("plugins-table-wrap");
        const detail = document.getElementById("plugins-detail");
        const badge = document.getElementById("plugins-summary-badge");
        if (summary) summary.textContent = "Plugin-Inspector aktuell nicht erreichbar.";
        if (alert) {
            alert.textContent =
                "Ohne /api/plugins kann die Plugin-Uebersicht nicht geladen werden.";
            alert.className = "settings-alert warn";
        }
        if (wrap) wrap.innerHTML = "";
        if (detail) detail.innerHTML = "";
        if (badge) {
            badge.textContent = "offline";
            badge.className = "badge badge-error";
        }
    }

    _renderSummary() {
        const summary = document.getElementById("plugins-summary");
        const alert = document.getElementById("plugins-alert");
        const badge = document.getElementById("plugins-summary-badge");
        if (!summary || !alert || !badge) return;

        const s = this._data.summary || {};
        const bs = s.by_source || {};
        const total = s.total ?? 0;
        const userCount = bs.user_dir ?? 0;
        const epCount = bs.entry_point ?? 0;

        summary.innerHTML = `
            <div class="summary-grid">
                <div class="summary-item">
                    <span class="summary-label">Gesamt</span>
                    <strong>${total}</strong>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Builtin</span>
                    <strong>${bs.builtin ?? 0}</strong>
                </div>
                <div class="summary-item">
                    <span class="summary-label">User-Dir</span>
                    <strong>${userCount}</strong>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Entry-Point</span>
                    <strong>${epCount}</strong>
                </div>
            </div>
        `;

        if (userCount + epCount > 0) {
            alert.textContent =
                `${userCount + epCount} Plugins kommen aus externer Quelle (User-Dir / Entry-Point).`;
            alert.className = "settings-alert warn";
        } else {
            alert.textContent = "Nur Builtin-Plugins geladen.";
            alert.className = "settings-alert ok";
        }

        badge.textContent = `${total} geladen`;
        badge.className = "badge badge-ok";
    }

    _renderTable() {
        const wrap = document.getElementById("plugins-table-wrap");
        if (!wrap || !this._data) return;

        const plugins = (this._data.plugins || []).filter(p =>
            this._sourceFilter === "all" ? true : p.source === this._sourceFilter
        );

        if (!plugins.length) {
            wrap.innerHTML = `<div class="settings-empty">Keine Plugins fuer diesen Filter.</div>`;
            return;
        }

        const rows = plugins.map(p => this._renderRow(p)).join("");
        wrap.innerHTML = `
            <table class="plugins-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Source</th>
                        <th>Prio</th>
                        <th>Category</th>
                        <th>Version</th>
                        <th>Conflicts</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;

        wrap.querySelectorAll(".plugins-row").forEach(row => {
            row.addEventListener("click", () => {
                this._selectedPlugin = row.dataset.name;
                this._renderDetail();
                wrap.querySelectorAll(".plugins-row").forEach(r =>
                    r.classList.toggle("selected", r === row)
                );
            });
        });
    }

    _renderRow(p) {
        const conflicts = (p.conflicts || []).join(", ") || "–";
        const sourceLabel = SOURCE_LABELS[p.source] || p.source;
        return `
            <tr class="plugins-row" data-name="${this._escape(p.name)}">
                <td class="plugins-name">${this._escape(p.name)}</td>
                <td>
                    <span class="plugins-source plugins-source-${this._escape(p.source)}">
                        ${this._escape(sourceLabel)}
                    </span>
                </td>
                <td>${p.priority}</td>
                <td>${this._escape(p.category)}</td>
                <td>${this._escape(p.version)}</td>
                <td>${this._escape(conflicts)}</td>
            </tr>
        `;
    }

    _renderDetail() {
        const detail = document.getElementById("plugins-detail");
        if (!detail) return;
        if (!this._selectedPlugin || !this._data) {
            detail.innerHTML = "";
            return;
        }
        const p = (this._data.plugins || []).find(
            x => x.name === this._selectedPlugin
        );
        if (!p) {
            detail.innerHTML = "";
            return;
        }
        const conflicts = (p.conflicts || []).join(", ") || "(keine)";
        const requires = (p.requires || []).join(", ") || "(keine)";
        const sourcePath = p.source_path
            ? ` <span class="plugins-source-path">(${this._escape(p.source_path)})</span>`
            : "";
        detail.innerHTML = `
            <div class="plugins-detail-card">
                <div class="plugins-detail-header">
                    <h4>${this._escape(p.name)}</h4>
                    <span class="plugins-detail-version">v${this._escape(p.version)}</span>
                </div>
                <div class="plugins-detail-meta">
                    <div>Source: <strong>${this._escape(SOURCE_LABELS[p.source] || p.source)}</strong>${sourcePath}</div>
                    <div>Priority: <strong>${p.priority}</strong></div>
                    <div>Category: <strong>${this._escape(p.category)}</strong></div>
                    <div>Conflicts: <strong>${this._escape(conflicts)}</strong></div>
                    <div>Requires: <strong>${this._escape(requires)}</strong></div>
                </div>
                <div class="plugins-detail-help">
                    <pre>${this._escape(p.help_section_excerpt || "")}</pre>
                </div>
            </div>
        `;
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
