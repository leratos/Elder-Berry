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
                    <div class="avatar-emotion-flags">
                        <label class="avatar-flag-row">
                            <input type="checkbox" id="avatar-can-blink">
                            <span>Blinzeln aktiv (can_blink)</span>
                        </label>
                    </div>
                    <h3 style="margin-top:1rem;">Animation</h3>
                    <details class="avatar-anim-section" open>
                        <summary>Lip-Sync (Sprach-Animation)</summary>
                        <div class="avatar-anim-grid">
                            <label>Interval (s)</label>
                            <input type="number" id="avatar-lip-interval"
                                   step="0.01" min="0.05" max="1.0">
                            <label>Jitter (s)</label>
                            <input type="number" id="avatar-lip-jitter"
                                   step="0.01" min="0" max="0.2">
                        </div>
                        <p class="avatar-anim-hint">
                            Mouth-Frames mit Wahrscheinlichkeits-Gewicht (höher = häufiger):
                        </p>
                        <div id="avatar-lip-frames" class="avatar-frames"></div>
                        <div class="avatar-frame-add">
                            <select id="avatar-frame-add-select"></select>
                            <button id="avatar-frame-add-btn" class="secondary-btn">+ Frame</button>
                        </div>
                    </details>
                    <details class="avatar-anim-section">
                        <summary>Breathing (Atem-Animation)</summary>
                        <div class="avatar-anim-grid">
                            <label class="avatar-anim-checkbox-label">
                                <input type="checkbox" id="avatar-breath-enabled">
                                Aktiv
                            </label>
                            <span></span>
                            <label>Speed (Hz)</label>
                            <input type="number" id="avatar-breath-speed"
                                   step="0.1" min="0.1" max="5.0">
                            <label>Amplitude (px)</label>
                            <input type="number" id="avatar-breath-amplitude"
                                   step="0.5" min="0" max="10">
                        </div>
                    </details>
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
        this._renderAnimationParams();
        this._renderLipFrames();
        this._populateFrameAddOptions();
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
        const blink = this.container.querySelector("#avatar-can-blink");
        blink.addEventListener("change", () => {
            const e = this._emotionConfig();
            if (this.currentEmotion) {
                this.config.emotions[this.currentEmotion] = e;
                e.can_blink = blink.checked;
            }
        });
        // Animation-Params: change-handler schreiben direkt in this.config
        const params = [
            ["#avatar-lip-interval",   "lip_sync",  "interval",  "float"],
            ["#avatar-lip-jitter",     "lip_sync",  "jitter",    "float"],
            ["#avatar-breath-enabled", "breathing", "enabled",   "bool"],
            ["#avatar-breath-speed",   "breathing", "speed",     "float"],
            ["#avatar-breath-amplitude","breathing","amplitude", "float"],
        ];
        for (const [sel, group, key, type] of params) {
            const el = this.container.querySelector(sel);
            if (!el) continue;
            el.addEventListener("change", () => {
                if (!this.config[group]) this.config[group] = {};
                if (type === "bool") {
                    this.config[group][key] = el.checked;
                } else {
                    const v = parseFloat(el.value);
                    if (!Number.isNaN(v)) this.config[group][key] = v;
                }
            });
        }
        const addBtn = this.container.querySelector("#avatar-frame-add-btn");
        addBtn.addEventListener("click", () => this._addLipFrame());
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
        const blink = this.container.querySelector("#avatar-can-blink");
        if (blink) {
            // Default true (wie Original-Editor: layers.can_blink !== false)
            blink.checked = emo.can_blink !== false;
        }
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

    _renderAnimationParams() {
        const ls = this.config.lip_sync || {};
        const br = this.config.breathing || {};
        const set = (sel, val) => {
            const el = this.container.querySelector(sel);
            if (el) el.value = val;
        };
        const setCheck = (sel, val) => {
            const el = this.container.querySelector(sel);
            if (el) el.checked = !!val;
        };
        set("#avatar-lip-interval", ls.interval ?? 0.18);
        set("#avatar-lip-jitter", ls.jitter ?? 0.03);
        // breathing.enabled: default true (wie Original br.enabled !== false)
        setCheck("#avatar-breath-enabled", br.enabled !== false);
        set("#avatar-breath-speed", br.speed ?? 1.2);
        set("#avatar-breath-amplitude", br.amplitude ?? 2.0);
    }

    _populateFrameAddOptions() {
        const sel = this.container.querySelector("#avatar-frame-add-select");
        if (!sel) return;
        sel.innerHTML = "";
        for (const sprite of this.assets.mouth || []) {
            const opt = document.createElement("option");
            opt.value = sprite;
            opt.textContent = sprite;
            sel.appendChild(opt);
        }
    }

    _renderLipFrames() {
        const wrap = this.container.querySelector("#avatar-lip-frames");
        if (!wrap) return;
        wrap.innerHTML = "";
        const frames = (this.config.lip_sync && this.config.lip_sync.frames)
            || {};
        const entries = Object.entries(frames);
        if (entries.length === 0) {
            const empty = document.createElement("p");
            empty.className = "avatar-anim-hint";
            empty.textContent =
                "(keine Frames – ohne Frames wird neutral_close benutzt)";
            wrap.appendChild(empty);
            return;
        }
        for (const [name, weight] of entries) {
            const row = document.createElement("div");
            row.className = "avatar-frame-row";
            const nameEl = document.createElement("span");
            nameEl.className = "avatar-frame-name";
            nameEl.textContent = name;
            const weightEl = document.createElement("input");
            weightEl.type = "number";
            weightEl.step = "1";
            weightEl.min = "0";
            weightEl.value = weight;
            weightEl.title = "Wahrscheinlichkeits-Gewicht";
            weightEl.addEventListener("change", () => {
                const v = parseFloat(weightEl.value);
                if (!Number.isNaN(v) && v >= 0) {
                    this.config.lip_sync.frames[name] = v;
                }
            });
            const removeBtn = document.createElement("button");
            removeBtn.className = "avatar-frame-remove";
            removeBtn.textContent = "✕";
            removeBtn.title = "Entfernen";
            removeBtn.addEventListener("click", () => {
                delete this.config.lip_sync.frames[name];
                this._renderLipFrames();
            });
            row.appendChild(nameEl);
            row.appendChild(weightEl);
            row.appendChild(removeBtn);
            wrap.appendChild(row);
        }
    }

    _addLipFrame() {
        const sel = this.container.querySelector("#avatar-frame-add-select");
        if (!sel || !sel.value) return;
        if (!this.config.lip_sync) this.config.lip_sync = {};
        if (!this.config.lip_sync.frames) this.config.lip_sync.frames = {};
        if (this.config.lip_sync.frames[sel.value] === undefined) {
            this.config.lip_sync.frames[sel.value] = 1;
        }
        this._renderLipFrames();
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
