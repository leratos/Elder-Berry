/**
 * AvatarModule – Avatar-Editor als Dashboard-Modul (Phase 58).
 *
 * Funktionen:
 * - Emotion auswählen (Dropdown)
 * - Layer (body/eye/mouth/effect) per Sprite-Auswahl konfigurieren
 * - Live-Preview als gestapelte PNGs (CSS-Layer, nicht Canvas – passt
 *   zum LayeredSpriteRenderer und braucht keine Image-Decoding-Tricks)
 * - Save → PUT /api/avatar/config
 * - Reload → POST /api/avatar/reload
 *
 * Alle API-Aufrufe gehen über apiFetch → Cookie + 401-Handling drin.
 */
import { DashboardModule } from "./base.js";

const CATEGORIES = ["body", "eye", "mouth", "effect"];

export default class AvatarModule extends DashboardModule {
    render() {
        return `
        <div class="card avatar-shell">
            <div class="card-header">
                <span class="card-title">Avatar-Editor</span>
                <span class="badge" id="avatar-status">Lade...</span>
            </div>
            <div class="avatar-layout">
                <section class="avatar-panel avatar-preview-panel">
                    <h3>Vorschau</h3>
                    <div class="avatar-emotion-row">
                        <label for="avatar-emotion">Emotion</label>
                        <select id="avatar-emotion"></select>
                    </div>
                    <div class="avatar-preview" id="avatar-preview"></div>
                </section>
                <section class="avatar-panel avatar-edit-panel">
                    <h3>Layer</h3>
                    <div class="avatar-layers" id="avatar-layers"></div>
                    <div class="avatar-actions">
                        <button id="avatar-save" class="primary-btn">Speichern</button>
                        <button id="avatar-reload" class="secondary-btn">Hot-Reload</button>
                    </div>
                    <div id="avatar-message" class="avatar-message"></div>
                </section>
            </div>
        </div>`;
    }

    async init() {
        this.config = null;
        this.emotions = [];
        this.assets = {};
        this.currentEmotion = null;
        this.reloadAvailable = false;

        await this._loadAssets();
        await this._loadConfig();
        this._bindEvents();
        this._renderEmotionList();
        this._renderLayers();
        this._renderPreview();
    }

    async _loadAssets() {
        const data = await this.apiFetch("/api/avatar/assets");
        if (!data) {
            this._setStatus("Assets nicht erreichbar", true);
            return;
        }
        this.assets = data;
    }

    async _loadConfig() {
        const data = await this.apiFetch("/api/avatar/config");
        if (!data) {
            this._setStatus("Config nicht erreichbar", true);
            return;
        }
        this.config = data.config || {emotions: {}};
        this.emotions = data.emotions || [];
        this.reloadAvailable = !!data.reload_available;
        this.currentEmotion =
            this.emotions.find(e => this.config.emotions?.[e])
            || this.emotions[0] || null;
        this._setStatus(this.reloadAvailable ? "Bereit (Live)" : "Bereit");
    }

    _bindEvents() {
        const sel = this.container.querySelector("#avatar-emotion");
        sel.addEventListener("change", () => {
            this.currentEmotion = sel.value;
            this._renderLayers();
            this._renderPreview();
        });
        const saveBtn = this.container.querySelector("#avatar-save");
        saveBtn.addEventListener("click", () => this._save());
        const reloadBtn = this.container.querySelector("#avatar-reload");
        reloadBtn.addEventListener("click", () => this._reload());
        if (!this.reloadAvailable) {
            reloadBtn.disabled = true;
            reloadBtn.title = "Kein Renderer verfügbar";
        }
    }

    _renderEmotionList() {
        const sel = this.container.querySelector("#avatar-emotion");
        sel.innerHTML = "";
        for (const e of this.emotions) {
            const opt = document.createElement("option");
            opt.value = e;
            opt.textContent = e;
            if (e === this.currentEmotion) opt.selected = true;
            sel.appendChild(opt);
        }
    }

    _currentEmotionLayers() {
        if (!this.currentEmotion) return {};
        const e = this.config.emotions?.[this.currentEmotion];
        if (!e) return {};
        // Config-Format: emotions[name].layers = [{type, sprite, ...}, ...]
        // ODER vereinfacht: emotions[name] = {body, eye, mouth, effect}
        if (Array.isArray(e.layers)) {
            const result = {};
            for (const L of e.layers) {
                if (L.type && L.sprite) result[L.type] = L.sprite;
            }
            return result;
        }
        return e;
    }

    _renderLayers() {
        const wrap = this.container.querySelector("#avatar-layers");
        wrap.innerHTML = "";
        const current = this._currentEmotionLayers();
        for (const cat of CATEGORIES) {
            const row = document.createElement("div");
            row.className = "avatar-layer-row";
            const label = document.createElement("label");
            label.textContent = cat;
            label.htmlFor = `avatar-layer-${cat}`;
            const sel = document.createElement("select");
            sel.id = `avatar-layer-${cat}`;
            sel.dataset.category = cat;
            const empty = document.createElement("option");
            empty.value = "";
            empty.textContent = "(keine)";
            sel.appendChild(empty);
            for (const sprite of this.assets[cat] || []) {
                const opt = document.createElement("option");
                opt.value = sprite;
                opt.textContent = sprite;
                if (sprite === current[cat]) opt.selected = true;
                sel.appendChild(opt);
            }
            sel.addEventListener("change", () => {
                this._setLayer(cat, sel.value);
                this._renderPreview();
            });
            row.appendChild(label);
            row.appendChild(sel);
            wrap.appendChild(row);
        }
    }

    _setLayer(category, sprite) {
        if (!this.currentEmotion) return;
        if (!this.config.emotions) this.config.emotions = {};
        if (!this.config.emotions[this.currentEmotion]) {
            this.config.emotions[this.currentEmotion] = {layers: []};
        }
        const e = this.config.emotions[this.currentEmotion];
        if (Array.isArray(e.layers)) {
            // Layer mit gleichem type ersetzen oder hinzufügen
            const idx = e.layers.findIndex(L => L.type === category);
            if (!sprite) {
                if (idx >= 0) e.layers.splice(idx, 1);
            } else if (idx >= 0) {
                e.layers[idx].sprite = sprite;
            } else {
                e.layers.push({type: category, sprite});
            }
        } else {
            // Vereinfachtes Format
            if (sprite) e[category] = sprite;
            else delete e[category];
        }
    }

    _renderPreview() {
        const preview = this.container.querySelector("#avatar-preview");
        preview.innerHTML = "";
        const current = this._currentEmotionLayers();
        // Render-Reihenfolge body→effect (effect liegt oben)
        for (const cat of CATEGORIES) {
            const sprite = current[cat];
            if (!sprite) continue;
            const img = document.createElement("img");
            img.className = "avatar-layer-img";
            img.alt = `${cat}: ${sprite}`;
            img.src = `/api/avatar/assets/${cat}/${sprite}`;
            preview.appendChild(img);
        }
    }

    async _save() {
        this._setMessage("Speichere...");
        const res = await this.apiFetch("/api/avatar/config", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({config: this.config}),
        });
        if (res && res.saved) {
            this._setMessage("Gespeichert ✔", false);
        } else {
            this._setMessage("Speichern fehlgeschlagen", true);
        }
    }

    async _reload() {
        this._setMessage("Reload...");
        const res = await this.apiFetch("/api/avatar/reload", {
            method: "POST",
        });
        if (res && res.reloaded) {
            this._setMessage("Reload OK ✔", false);
        } else {
            this._setMessage("Reload fehlgeschlagen", true);
        }
    }

    _setStatus(text, error = false) {
        const el = this.container.querySelector("#avatar-status");
        if (!el) return;
        el.textContent = text;
        el.classList.toggle("badge-error", !!error);
    }

    _setMessage(text, error = false) {
        const el = this.container.querySelector("#avatar-message");
        if (!el) return;
        el.textContent = text;
        el.classList.toggle("avatar-message-error", !!error);
    }
}
