/**
 * AvatarModule – Avatar-Editor als Dashboard-Modul (Phase 58).
 *
 * Layer-Struktur (1:1 wie Original-Editor + LayeredSpriteRenderer):
 *   - body          (assets aus body/)
 *   - eye_left      (assets aus eye/, gefiltert auf "eye_left_*")
 *   - eye_right     (assets aus eye/, gefiltert auf "eye_right_*")
 *   - mouth         (assets aus mouth/)
 *   - effect        (optional, assets aus effect/)
 *
 * Render-Reihenfolge: body → eye_left → eye_right → mouth → effect
 * Sprites werden voll überlagert (CSS-Stack); jedes eye-Sprite enthält
 * nur das jeweilige Auge im richtigen Pixel-Offset innerhalb der
 * Gesamt-Sprite-Größe (Original-Verhalten, nicht position-basiert).
 *
 * Alle API-Aufrufe gehen über apiFetch → Cookie + 401-Handling drin.
 */
import { DashboardModule } from "./base.js";

// Layer-Konfiguration – Reihenfolge bestimmt Z-Stack (oben = später)
const LAYERS = [
    {key: "body",      category: "body",   filter: null,         optional: false},
    {key: "eye_left",  category: "eye",    filter: "eye_left_",  optional: false},
    {key: "eye_right", category: "eye",    filter: "eye_right_", optional: false},
    {key: "mouth",     category: "mouth",  filter: null,         optional: false},
    {key: "effect",    category: "effect", filter: null,         optional: true},
];

const LAYER_LABELS = {
    body:      "Body",
    eye_left:  "Eye L",
    eye_right: "Eye R",
    mouth:     "Mouth",
    effect:    "Effect",
};

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
        if (!this.config.emotions) this.config.emotions = {};
        this.emotions = data.emotions || [];
        this.reloadAvailable = !!data.reload_available;
        this.currentEmotion =
            this.emotions.find(e => this.config.emotions[e])
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

    _emotionConfig() {
        if (!this.currentEmotion) return {};
        return this.config.emotions[this.currentEmotion] || {};
    }

    _availableSprites(category, filter) {
        const items = this.assets[category] || [];
        if (!filter) return items;
        return items.filter(name => name.startsWith(filter));
    }

    _renderLayers() {
        const wrap = this.container.querySelector("#avatar-layers");
        wrap.innerHTML = "";
        const emo = this._emotionConfig();
        for (const layer of LAYERS) {
            const row = document.createElement("div");
            row.className = "avatar-layer-row";
            const label = document.createElement("label");
            label.textContent = LAYER_LABELS[layer.key] || layer.key;
            label.htmlFor = `avatar-layer-${layer.key}`;
            const sel = document.createElement("select");
            sel.id = `avatar-layer-${layer.key}`;
            sel.dataset.layerKey = layer.key;
            if (layer.optional) {
                const empty = document.createElement("option");
                empty.value = "";
                empty.textContent = "(keine)";
                sel.appendChild(empty);
            }
            const current = emo[layer.key] || "";
            const sprites = this._availableSprites(layer.category, layer.filter);
            for (const sprite of sprites) {
                const opt = document.createElement("option");
                opt.value = sprite;
                opt.textContent = sprite;
                if (sprite === current) opt.selected = true;
                sel.appendChild(opt);
            }
            sel.addEventListener("change", () => {
                this._setLayer(layer.key, sel.value);
                this._renderPreview();
            });
            row.appendChild(label);
            row.appendChild(sel);
            wrap.appendChild(row);
        }
    }

    _setLayer(layerKey, sprite) {
        if (!this.currentEmotion) return;
        if (!this.config.emotions[this.currentEmotion]) {
            this.config.emotions[this.currentEmotion] = {};
        }
        const e = this.config.emotions[this.currentEmotion];
        if (sprite) {
            e[layerKey] = sprite;
        } else {
            delete e[layerKey];
        }
    }

    _renderPreview() {
        const preview = this.container.querySelector("#avatar-preview");
        preview.innerHTML = "";
        const emo = this._emotionConfig();
        for (const layer of LAYERS) {
            const sprite = emo[layer.key];
            if (!sprite) continue;
            const img = document.createElement("img");
            img.className = "avatar-layer-img";
            img.alt = `${layer.key}: ${sprite}`;
            img.src = `/api/avatar/assets/${layer.category}/${sprite}`;
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
