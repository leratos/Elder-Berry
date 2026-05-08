/**
 * ProposalsModule – Plugin-Vorschlaege Review-Workflow (Phase 78 Etappe 3).
 *
 * Listet Saleria-erkannte Capability-Luecken aus /api/proposals und
 * erlaubt Lera den Status-Wechsel (in_pruefung -> in_bearbeitung /
 * abgelehnt -> fertiggestellt) plus Eintragen des implementierten
 * Plugin-Pfads.
 *
 * Markdown-Body kommt server-side bereits durch markdown-it-py +
 * bleach.clean() und wird hier als innerHTML gesetzt -- die Server-
 * Sanitization ist primaerer Schutz, CSP zusaetzlicher Layer.
 *
 * Login-gating: View "proposals" steht in AUTH_TABS (auth.js), die
 * /api/proposals-Routen sitzen hinter DashboardAuthMiddleware
 * (Phase 58, PROTECTED_PREFIXES).
 */
import { DashboardModule } from "./base.js";

const STATUS_LABELS = {
    in_pruefung: "In Pruefung",
    in_bearbeitung: "In Bearbeitung",
    abgelehnt: "Abgelehnt",
    fertiggestellt: "Fertiggestellt",
};

const STATUS_FILTERS = [
    { value: "in_pruefung", label: "In Pruefung" },
    { value: "in_bearbeitung", label: "In Bearbeitung" },
    { value: "abgelehnt", label: "Abgelehnt" },
    { value: "fertiggestellt", label: "Fertiggestellt" },
    { value: "all", label: "Alle" },
];

export default class ProposalsModule extends DashboardModule {
    render() {
        return `
        <div class="card proposals-shell">
            <div class="card-header">
                <span class="card-title">Plugin-Vorschlaege</span>
                <span class="badge" id="proposals-summary-badge">Lade...</span>
            </div>
            <div class="settings-overview">
                <div class="settings-summary" id="proposals-summary"></div>
                <div class="settings-alert" id="proposals-alert"></div>
            </div>
            <div class="settings-toolbar" id="proposals-toolbar">
                ${STATUS_FILTERS.map((f, i) => `
                    <button class="toolbar-button${i === 0 ? " active" : ""}"
                            data-status="${f.value}">${f.label}</button>
                `).join("")}
                <button class="toolbar-button proposals-refresh"
                        id="proposals-refresh">↻ Neu laden</button>
            </div>
            <div class="proposals-table-wrap" id="proposals-table-wrap"></div>
            <div class="proposals-detail" id="proposals-detail"></div>
        </div>`;
    }

    get pollInterval() { return 0; }

    async init() {
        this._statusFilter = "in_pruefung";
        this._selectedId = null;
        this._proposals = [];
        this._detail = null;
        this._bindToolbar();
        await this.refresh();
    }

    async refresh() {
        const url = this._statusFilter === "all"
            ? "/api/proposals"
            : `/api/proposals?status=${encodeURIComponent(this._statusFilter)}`;
        const data = await this.apiFetch(url);
        if (!data) {
            this._renderError();
            return;
        }
        this._proposals = data.proposals || [];
        this._renderSummary();
        this._renderTable();
        if (this._selectedId) {
            await this._loadDetail(this._selectedId);
        }
    }

    _bindToolbar() {
        const toolbar = document.getElementById("proposals-toolbar");
        if (!toolbar) return;
        toolbar.querySelectorAll(".toolbar-button").forEach(btn => {
            btn.addEventListener("click", async () => {
                if (btn.id === "proposals-refresh") {
                    await this.refresh();
                    return;
                }
                toolbar.querySelectorAll(".toolbar-button").forEach(b => {
                    if (b.id !== "proposals-refresh") {
                        b.classList.remove("active");
                    }
                });
                btn.classList.add("active");
                this._statusFilter = btn.dataset.status || "in_pruefung";
                this._selectedId = null;
                this._detail = null;
                this._renderDetail();
                await this.refresh();
            });
        });
    }

    _renderError() {
        this._proposals = [];
        this._selectedId = null;
        this._detail = null;
        const summary = document.getElementById("proposals-summary");
        const alert = document.getElementById("proposals-alert");
        const wrap = document.getElementById("proposals-table-wrap");
        const detail = document.getElementById("proposals-detail");
        const badge = document.getElementById("proposals-summary-badge");
        if (summary) summary.textContent = "Vorschlaege aktuell nicht erreichbar.";
        if (alert) {
            alert.textContent =
                "Ohne /api/proposals kann die Liste nicht geladen werden.";
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
        const summary = document.getElementById("proposals-summary");
        const alert = document.getElementById("proposals-alert");
        const badge = document.getElementById("proposals-summary-badge");
        if (!summary || !alert || !badge) return;

        const filterLabel = STATUS_FILTERS.find(f => f.value === this._statusFilter)
            ?.label || this._statusFilter;

        summary.innerHTML = `
            <div class="summary-grid">
                <div class="summary-item">
                    <span class="summary-label">Filter</span>
                    <strong>${this._escape(filterLabel)}</strong>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Anzahl</span>
                    <strong>${this._proposals.length}</strong>
                </div>
            </div>
        `;

        if (this._proposals.length === 0) {
            alert.textContent = "Keine Vorschlaege fuer diesen Filter.";
            alert.className = "settings-alert ok";
        } else {
            const inPending = this._proposals.filter(
                p => p.status === "in_pruefung"
            ).length;
            if (inPending > 0 && this._statusFilter !== "in_pruefung") {
                alert.textContent =
                    `${inPending} weitere Vorschlaege warten auf Pruefung.`;
                alert.className = "settings-alert warn";
            } else {
                alert.textContent = "";
                alert.className = "settings-alert";
            }
        }

        badge.textContent = `${this._proposals.length}`;
        badge.className = "badge badge-ok";
    }

    _renderTable() {
        const wrap = document.getElementById("proposals-table-wrap");
        if (!wrap) return;
        if (!this._proposals.length) {
            wrap.innerHTML =
                `<div class="settings-empty">Keine Vorschlaege.</div>`;
            return;
        }
        const rows = this._proposals.map(p => this._renderRow(p)).join("");
        wrap.innerHTML = `
            <table class="plugins-table proposals-table">
                <thead>
                    <tr>
                        <th>Titel</th>
                        <th>Intent</th>
                        <th>Status</th>
                        <th>Trigger</th>
                        <th>Letzter Trigger</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
        wrap.querySelectorAll(".proposals-row").forEach(row => {
            row.addEventListener("click", () => {
                this._selectedId = row.dataset.id;
                wrap.querySelectorAll(".proposals-row").forEach(r =>
                    r.classList.toggle("selected", r === row)
                );
                this._loadDetail(this._selectedId);
            });
        });
    }

    _renderRow(p) {
        const lastTrig = p.last_triggered_at
            ? this._fmtDate(p.last_triggered_at)
            : "–";
        return `
            <tr class="proposals-row" data-id="${this._escape(p.id)}">
                <td class="plugins-name">${this._escape(p.title)}</td>
                <td><code>${this._escape(p.id)}</code></td>
                <td>
                    <span class="proposals-status proposals-status-${this._escape(p.status)}">
                        ${this._escape(STATUS_LABELS[p.status] || p.status)}
                    </span>
                </td>
                <td>${p.trigger_count}</td>
                <td>${this._escape(lastTrig)}</td>
            </tr>
        `;
    }

    async _loadDetail(proposalId) {
        const data = await this.apiFetch(
            `/api/proposals/${encodeURIComponent(proposalId)}`
        );
        if (!data) {
            this._detail = null;
        } else {
            this._detail = data;
        }
        this._renderDetail();
    }

    _renderDetail() {
        const detail = document.getElementById("proposals-detail");
        if (!detail) return;
        if (!this._detail) {
            detail.innerHTML = "";
            return;
        }
        const p = this._detail.proposal;
        const triggers = this._detail.triggers || [];
        const history = this._detail.history || [];
        // description_html ist server-side ueber bleach.clean() bereinigt
        // (Konzept §3.8 + R3) -- direkt einsetzen ist sicher.
        const descriptionHtml = this._detail.description_html || "";

        detail.innerHTML = `
            <div class="plugins-detail-card proposals-detail-card">
                <div class="plugins-detail-header">
                    <h4>${this._escape(p.title)}</h4>
                    <span class="proposals-status proposals-status-${this._escape(p.status)}">
                        ${this._escape(STATUS_LABELS[p.status] || p.status)}
                    </span>
                </div>
                <div class="plugins-detail-meta">
                    <div>Intent: <code>${this._escape(p.id)}</code></div>
                    <div>Trigger gesamt: <strong>${p.trigger_count}</strong>
                        (Confidence: ${p.last_confidence?.toFixed(2) ?? "–"})</div>
                    <div>Erstellt: ${this._escape(this._fmtDate(p.created_at))}</div>
                    ${p.suggested_category
                        ? `<div>Kategorie-Vorschlag: ${this._escape(p.suggested_category)}</div>`
                        : ""}
                    ${p.implemented_in
                        ? `<div>Implementiert in: <code>${this._escape(p.implemented_in)}</code></div>`
                        : ""}
                    ${p.rejected_reason
                        ? `<div>Begruendung Ablehnung: ${this._escape(p.rejected_reason)}</div>`
                        : ""}
                </div>
                <div class="proposals-description">
                    ${descriptionHtml}
                </div>
                ${this._renderActionButtons(p)}
                ${this._renderTriggers(triggers)}
                ${this._renderHistory(history)}
            </div>
        `;
        this._bindActionButtons();
    }

    _renderActionButtons(p) {
        // Status-Wechsel ist Lera-only; saleria darf nur in_pruefung setzen.
        // Buttons immer anzeigen, auch fuer abgelehnt/fertiggestellt --
        // Lera kann ihre Meinung aendern.
        return `
            <div class="proposals-actions">
                ${p.status !== "in_bearbeitung"
                    ? `<button class="toolbar-button proposals-action"
                               data-action="in_bearbeitung">▶ In Bearbeitung</button>`
                    : ""}
                ${p.status !== "abgelehnt"
                    ? `<button class="toolbar-button proposals-action"
                               data-action="abgelehnt">✗ Ablehnen</button>`
                    : ""}
                ${p.status !== "fertiggestellt"
                    ? `<button class="toolbar-button proposals-action"
                               data-action="fertiggestellt">✓ Fertig</button>`
                    : ""}
                ${p.status !== "in_pruefung"
                    ? `<button class="toolbar-button proposals-action"
                               data-action="in_pruefung">↺ Zurueck zur Pruefung</button>`
                    : ""}
                <button class="toolbar-button proposals-action"
                        data-action="implementation">📁 Pfad eintragen</button>
            </div>
        `;
    }

    _renderTriggers(triggers) {
        if (!triggers.length) return "";
        const rows = triggers.map(t => `
            <tr>
                <td>${this._escape(this._fmtDate(t.triggered_at))}</td>
                <td>${this._escape(t.sample_message || "")}</td>
                <td>${t.confidence?.toFixed(2) ?? "–"}</td>
            </tr>
        `).join("");
        return `
            <details class="proposals-history">
                <summary>Trigger-Historie (${triggers.length})</summary>
                <table class="plugins-table">
                    <thead>
                        <tr><th>Zeitpunkt</th><th>Anfrage</th><th>Confidence</th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </details>
        `;
    }

    _renderHistory(history) {
        if (!history.length) return "";
        const rows = history.map(h => `
            <tr>
                <td>${this._escape(this._fmtDate(h.timestamp))}</td>
                <td>${this._escape(h.old_status || "—")}</td>
                <td>${this._escape(h.new_status)}</td>
                <td>${this._escape(h.changed_by)}</td>
                <td>${this._escape(h.note || "")}</td>
            </tr>
        `).join("");
        return `
            <details class="proposals-history">
                <summary>Status-Historie (${history.length})</summary>
                <table class="plugins-table">
                    <thead>
                        <tr><th>Zeitpunkt</th><th>Alt</th><th>Neu</th>
                            <th>Wer</th><th>Notiz</th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </details>
        `;
    }

    _bindActionButtons() {
        document.querySelectorAll(".proposals-action").forEach(btn => {
            btn.addEventListener("click", () => this._onAction(btn.dataset.action));
        });
    }

    async _onAction(action) {
        if (!this._selectedId) return;
        if (action === "implementation") {
            const path = window.prompt(
                "Pfad zum implementierten Plugin (z.B. " +
                "src/elder_berry/comms/commands/spotify_commands.py):"
            );
            if (!path) return;
            await this._postImplementation(this._selectedId, path);
            return;
        }
        // Status-Wechsel
        let note = null;
        let rejected_reason = null;
        if (action === "abgelehnt") {
            rejected_reason = window.prompt(
                "Begruendung fuer die Ablehnung (optional):"
            );
            if (rejected_reason === null) return;
        } else {
            note = window.prompt("Notiz zum Status-Wechsel (optional):");
            if (note === null) return;
        }
        await this._postStatus(this._selectedId, action, note, rejected_reason);
    }

    async _postStatus(id, newStatus, note, rejectedReason) {
        const body = { new_status: newStatus };
        if (note) body.note = note;
        if (rejectedReason) body.rejected_reason = rejectedReason;
        const result = await this.apiFetch(
            `/api/proposals/${encodeURIComponent(id)}/status`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            }
        );
        if (!result) {
            window.alert("Status-Wechsel fehlgeschlagen.");
            return;
        }
        await this.refresh();
    }

    async _postImplementation(id, path) {
        const result = await this.apiFetch(
            `/api/proposals/${encodeURIComponent(id)}/implementation`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path }),
            }
        );
        if (!result) {
            window.alert("Pfad-Setzen fehlgeschlagen.");
            return;
        }
        await this.refresh();
    }

    _fmtDate(iso) {
        if (!iso) return "";
        try {
            const d = new Date(iso);
            return d.toLocaleString("de-DE", {
                year: "numeric", month: "2-digit", day: "2-digit",
                hour: "2-digit", minute: "2-digit",
            });
        } catch {
            return iso;
        }
    }

    _escape(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }
}
