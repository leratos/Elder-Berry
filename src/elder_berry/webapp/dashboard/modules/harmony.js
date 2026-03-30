/**
 * HarmonyModule – Harmony Remote als Dashboard-Modul.
 *
 * Komplette Fernbedienung: Aktivitäten, Geräte, Szenen,
 * Layouts, D-Pad, Numpad, Transport, Colors.
 */
import { DashboardModule } from "./base.js";

export default class HarmonyModule extends DashboardModule {

    constructor(config) {
        super(config);
        this._layouts = { activities: {}, devices: {} };
        this._detailedConfig = { activities: [], devices: [] };
        this._scenes = [];
        this._currentMode = "activity";
    }

    render() {
        return `
        <div class="card">
            <div class="card-header">
                <span class="card-title">Harmony</span>
                <span id="harmony-status" class="status-dot"></span>
            </div>
            <div id="harmony-current" class="current-activity">Verbinde...</div>

            <div class="tabs" id="harmony-tabs">
                <div class="tab active" data-mode="activity">Aktivitäten</div>
                <div class="tab" data-mode="device">Geräte</div>
                <div class="tab" data-mode="scenes">Szenen</div>
            </div>

            <!-- Aktivitäts-Modus -->
            <div id="harmony-activity-view">
                <div class="selector">
                    <select id="harmony-act-select"></select>
                </div>
                <div id="harmony-act-sections"></div>
            </div>

            <!-- Geräte-Modus -->
            <div id="harmony-device-view" style="display:none;">
                <div class="selector">
                    <select id="harmony-dev-select"></select>
                </div>
                <div id="harmony-dev-sections"></div>
            </div>

            <!-- Szenen-Modus -->
            <div id="harmony-scenes-view" style="display:none;">
                <div id="harmony-scene-list" class="scene-list"></div>
                <div style="margin-top:8px;">
                    <button class="btn-accent" id="harmony-new-scene"
                        style="font-size:0.85em;padding:10px;">+ Neue Szene</button>
                </div>
                <div id="harmony-scene-editor" class="scene-editor" style="display:none;">
                    <input id="harmony-scene-name" type="text"
                        placeholder="Szenen-Name (z.B. Gaming)">
                    <div class="section-title">Steps</div>
                    <div id="harmony-scene-steps"></div>
                    <button id="harmony-add-step"
                        style="font-size:0.85em;padding:8px;margin-top:4px;">+ Step</button>
                    <div class="editor-actions" style="display:flex;gap:6px;margin-top:8px;">
                        <button class="btn-accent" id="harmony-save-scene"
                            style="flex:1;">Speichern</button>
                        <button id="harmony-cancel-scene" style="flex:1;">Abbrechen</button>
                    </div>
                </div>
            </div>

            <div style="margin-top:12px;">
                <button class="btn-danger" id="harmony-off">Alles Aus</button>
            </div>
        </div>

        <div id="harmony-toast" class="toast"></div>`;
    }

    get pollInterval() { return 10000; }

    async init() {
        this._bindTabs();
        this._bindButtons();
        await this._loadConfig();
        await this._loadScenes();
        await this.poll();
    }

    async poll() {
        await this._pollStatus();
    }

    // -- API ---------------------------------------------------------- //

    _api() { return this.config.rpi5_url; }

    async _apiCall(method, path, body) {
        const url = this._api() + path;
        const opts = { method, headers: { "Content-Type": "application/json" } };
        if (body) opts.body = JSON.stringify(body);
        try {
            const r = await fetch(url, opts);
            return await r.json();
        } catch {
            return null;
        }
    }

    // -- Status ------------------------------------------------------- //

    async _pollStatus() {
        const data = await this._apiCall("GET", "/harmony/status");
        const dot = document.getElementById("harmony-status");
        const current = document.getElementById("harmony-current");

        if (!data || !data.connected) {
            if (dot) dot.className = "status-dot error";
            if (current) current.textContent = data ? "Hub offline" : "Nicht erreichbar";
            return;
        }

        if (dot) dot.className = "status-dot ok";
        if (current) current.textContent = data.current_activity || "Standby";
    }

    // -- Config Loading ----------------------------------------------- //

    async _loadConfig() {
        try {
            const [configData, layoutData] = await Promise.all([
                this._apiCall("GET", "/harmony/config/detailed"),
                this._apiCall("GET", "/harmony/layouts"),
            ]);
            if (configData) this._detailedConfig = configData;
            if (layoutData) this._layouts = layoutData;
        } catch { /* graceful */ }

        this._populateActivitySelect();
        this._populateDeviceSelect();
    }

    // -- Tabs --------------------------------------------------------- //

    _bindTabs() {
        const tabs = document.querySelectorAll("#harmony-tabs .tab");
        tabs.forEach(tab => {
            tab.addEventListener("click", () => {
                tabs.forEach(t => t.classList.remove("active"));
                tab.classList.add("active");
                this._currentMode = tab.dataset.mode;
                this._showCurrentView();
            });
        });
    }

    _showCurrentView() {
        const act = document.getElementById("harmony-activity-view");
        const dev = document.getElementById("harmony-device-view");
        const scn = document.getElementById("harmony-scenes-view");
        if (act) act.style.display = this._currentMode === "activity" ? "" : "none";
        if (dev) dev.style.display = this._currentMode === "device" ? "" : "none";
        if (scn) scn.style.display = this._currentMode === "scenes" ? "" : "none";
    }

    // -- Buttons ------------------------------------------------------ //

    _bindButtons() {
        const off = document.getElementById("harmony-off");
        if (off) off.addEventListener("click", () => this._powerOff());

        const newScene = document.getElementById("harmony-new-scene");
        if (newScene) newScene.addEventListener("click", () => this._openSceneEditor());

        const addStep = document.getElementById("harmony-add-step");
        if (addStep) addStep.addEventListener("click", () => this._addSceneStep());

        const save = document.getElementById("harmony-save-scene");
        if (save) save.addEventListener("click", () => this._saveScene());

        const cancel = document.getElementById("harmony-cancel-scene");
        if (cancel) cancel.addEventListener("click", () => this._closeSceneEditor());

        const actSelect = document.getElementById("harmony-act-select");
        if (actSelect) actSelect.addEventListener("change", () => this._renderActivityLayout());

        const devSelect = document.getElementById("harmony-dev-select");
        if (devSelect) devSelect.addEventListener("change", () => this._renderDeviceLayout());
    }

    // -- Toast -------------------------------------------------------- //

    _showToast(msg, ms = 2000) {
        const el = document.getElementById("harmony-toast");
        if (!el) return;
        el.textContent = msg;
        el.classList.add("show");
        setTimeout(() => el.classList.remove("show"), ms);
    }

    // -- Commands ----------------------------------------------------- //

    async _sendCommand(device, command) {
        try {
            const data = await this._apiCall("POST", "/harmony/command",
                { device, command });
            if (!data || !data.success) this._showToast("Befehl fehlgeschlagen");
        } catch {
            this._showToast("Verbindungsfehler");
        }
    }

    async _startActivity(name) {
        try {
            const data = await this._apiCall("POST", "/harmony/activity",
                { activity: name });
            this._showToast(data?.success ? `${name} gestartet` : "Fehler");
            this._pollStatus();
        } catch {
            this._showToast("Verbindungsfehler");
        }
    }

    async _powerOff() {
        try {
            const data = await this._apiCall("POST", "/harmony/off");
            this._showToast(data?.success ? "Alles aus" : "Fehler");
            this._pollStatus();
        } catch {
            this._showToast("Verbindungsfehler");
        }
    }

    // -- Activity Mode ------------------------------------------------ //

    _populateActivitySelect() {
        const select = document.getElementById("harmony-act-select");
        if (!select) return;
        select.innerHTML = "";

        const names = Object.keys(this._layouts.activities || {});
        if (names.length === 0) {
            (this._detailedConfig.activities || []).forEach(a => {
                const opt = document.createElement("option");
                opt.value = a.label; opt.textContent = a.label;
                select.appendChild(opt);
            });
        } else {
            names.forEach(name => {
                const opt = document.createElement("option");
                opt.value = name; opt.textContent = name;
                select.appendChild(opt);
            });
        }
        this._renderActivityLayout();
    }

    _renderActivityLayout() {
        const select = document.getElementById("harmony-act-select");
        const container = document.getElementById("harmony-act-sections");
        if (!select || !container) return;

        const name = select.value;
        const layout = (this._layouts.activities || {})[name];

        if (layout && layout.sections) {
            this._renderSections(container, layout.sections);
        } else {
            container.innerHTML = "";
            const btn = document.createElement("button");
            btn.className = "btn-accent";
            btn.textContent = `${name} starten`;
            btn.addEventListener("click", () => this._startActivity(name));
            container.appendChild(btn);
        }
    }

    // -- Device Mode -------------------------------------------------- //

    _populateDeviceSelect() {
        const select = document.getElementById("harmony-dev-select");
        if (!select) return;
        select.innerHTML = "";

        const names = Object.keys(this._layouts.devices || {});
        if (names.length === 0) {
            (this._detailedConfig.devices || []).forEach(d => {
                const opt = document.createElement("option");
                opt.value = d.label; opt.textContent = d.label;
                select.appendChild(opt);
            });
        } else {
            names.forEach(name => {
                const opt = document.createElement("option");
                opt.value = name; opt.textContent = name;
                select.appendChild(opt);
            });
        }
        this._renderDeviceLayout();
    }

    _renderDeviceLayout() {
        const select = document.getElementById("harmony-dev-select");
        const container = document.getElementById("harmony-dev-sections");
        if (!select || !container) return;

        const name = select.value;
        const layout = (this._layouts.devices || {})[name];

        if (layout && layout.sections) {
            this._renderSections(container, layout.sections);
        } else {
            const device = (this._detailedConfig.devices || [])
                .find(d => d.label === name);
            if (device) {
                const sections = device.control_groups.map(g => ({
                    label: g.name, type: "grid", columns: 3,
                    buttons: g.commands.map(cmd => ({
                        device: name, cmd, label: cmd,
                    })),
                }));
                this._renderSections(container, sections);
            } else {
                container.innerHTML =
                    '<div class="section-title">Kein Gerät gewählt</div>';
            }
        }
    }

    // -- Layout Rendering --------------------------------------------- //

    _renderSections(container, sections) {
        container.innerHTML = "";
        (sections || []).forEach(sec => {
            const div = document.createElement("div");
            div.className = "section";

            const title = document.createElement("div");
            title.className = "section-title";
            title.textContent = sec.label || "";
            div.appendChild(title);

            switch (sec.type) {
                case "dpad":      this._renderDpad(div, sec); break;
                case "numpad":    this._renderNumpad(div, sec); break;
                case "transport": this._renderTransport(div, sec); break;
                case "colors":   this._renderColors(div, sec); break;
                default:         this._renderGrid(div, sec);
            }
            container.appendChild(div);
        });
    }

    _makeBtn(device, cmd, label, extraClass) {
        const btn = document.createElement("button");
        btn.textContent = label || cmd;
        if (extraClass) btn.className = extraClass;
        btn.addEventListener("click", () => this._sendCommand(device, cmd));
        return btn;
    }

    _renderDpad(container, sec) {
        const dev = sec.device || "";
        const grid = document.createElement("div");
        grid.className = "dpad";

        grid.append(
            this._makeBtn(dev, "DirectionUp", "\u25b2", "up"),
            this._makeBtn(dev, "DirectionLeft", "\u25c4", "left"),
            this._makeBtn(dev, sec.center || "Select", "\u25cf", "center"),
            this._makeBtn(dev, "DirectionRight", "\u25ba", "right"),
            this._makeBtn(dev, "DirectionDown", "\u25bc", "down"),
        );
        container.appendChild(grid);

        if (sec.extra && sec.extra.length) {
            const extra = document.createElement("div");
            extra.className = "dpad-extra";
            extra.style.cssText =
                "display:flex;gap:6px;justify-content:center;margin-top:6px;" +
                "max-width:260px;margin-left:auto;margin-right:auto;";
            sec.extra.forEach(e => {
                const btn = this._makeBtn(dev, e.cmd, e.label);
                btn.style.flex = "1";
                extra.appendChild(btn);
            });
            container.appendChild(extra);
        }
    }

    _renderGrid(container, sec) {
        const cols = sec.columns || 3;
        const grid = document.createElement("div");
        grid.className = "btn-grid";
        grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

        (sec.buttons || []).forEach(b => {
            grid.appendChild(
                this._makeBtn(b.device || sec.device || "", b.cmd, b.label)
            );
        });
        container.appendChild(grid);
    }

    _renderNumpad(container, sec) {
        const dev = sec.device || "";
        const grid = document.createElement("div");
        grid.className = "btn-grid";
        grid.style.cssText =
            "grid-template-columns:repeat(3,1fr);max-width:260px;margin:0 auto;";

        ["1","2","3","4","5","6","7","8","9","-","0","ChannelList"].forEach(k => {
            const label = k === "ChannelList" ? "CH" : k;
            const cmd = k === "-" ? "-"
                : k === "ChannelList" ? "ChannelList"
                : `Number${k}`;
            const btn = this._makeBtn(dev, cmd, label);
            btn.style.padding = "16px 8px";
            btn.style.fontSize = "1.1em";
            grid.appendChild(btn);
        });
        container.appendChild(grid);
    }

    _renderTransport(container, sec) {
        const dev = sec.device || "";
        const row = document.createElement("div");
        row.style.cssText = "display:flex;gap:6px;justify-content:center;";

        [["Rewind", "\u25c4\u25c4"], ["Play", "\u25b6"],
         ["Pause", "\u23f8"], ["FastForward", "\u25b6\u25b6"]
        ].forEach(([cmd, lbl]) => {
            const btn = this._makeBtn(dev, cmd, lbl);
            btn.style.cssText = "flex:1;max-width:70px;padding:14px 4px;font-size:1.2em;";
            row.appendChild(btn);
        });
        container.appendChild(row);
    }

    _renderColors(container, sec) {
        const dev = sec.device || "";
        const row = document.createElement("div");
        row.style.cssText = "display:flex;gap:6px;justify-content:center;";

        const colors = [
            ["Red", "\ud83d\udd34", "var(--status-error)"],
            ["Green", "\ud83d\udfe2", "var(--status-ok)"],
            ["Blue", "\ud83d\udd35", "#3498db"],
            ["Yellow", "\ud83d\udfe1", "var(--status-warn)"],
        ];
        colors.forEach(([cmd, lbl, color]) => {
            const btn = this._makeBtn(dev, cmd, lbl);
            btn.style.cssText =
                `flex:1;max-width:80px;padding:12px 4px;font-size:1.1em;` +
                `border-color:${color};color:${color};`;
            row.appendChild(btn);
        });
        container.appendChild(row);
    }

    // -- Scenes ------------------------------------------------------- //

    async _loadScenes() {
        try {
            const data = await this._apiCall("GET", "/harmony/scenes");
            this._scenes = data?.scenes || [];
        } catch {
            this._scenes = [];
        }
        this._renderSceneList();
    }

    _renderSceneList() {
        const list = document.getElementById("harmony-scene-list");
        if (!list) return;
        list.innerHTML = "";

        if (this._scenes.length === 0) {
            list.innerHTML = '<div class="section-title">Keine Szenen vorhanden</div>';
            return;
        }

        this._scenes.forEach(scene => {
            const row = document.createElement("div");
            row.style.cssText = "display:flex;align-items:center;gap:6px;margin-bottom:6px;";

            const startBtn = document.createElement("button");
            startBtn.className = "btn-accent";
            startBtn.style.flex = "1";
            startBtn.textContent = `\u25b6 ${scene.name}`;
            startBtn.addEventListener("click", () => this._runScene(scene.name));

            const delBtn = document.createElement("button");
            delBtn.className = "btn-danger";
            delBtn.style.cssText = "width:44px;flex-shrink:0;font-size:1.1em;";
            delBtn.textContent = "\u2715";
            delBtn.addEventListener("click", () => this._deleteScene(scene.name));

            row.append(startBtn, delBtn);
            list.appendChild(row);
        });
    }

    async _runScene(name) {
        this._showToast(`${name} wird gestartet...`, 3000);
        const data = await this._apiCall("POST", "/harmony/scene/start", { name });
        if (data?.success) {
            this._showToast(`${name}: ${data.steps_ok}/${data.steps_total} OK`);
        } else {
            this._showToast(data?.error || "Fehler");
        }
        this._pollStatus();
    }

    async _deleteScene(name) {
        const data = await this._apiCall("DELETE",
            `/harmony/scene/${encodeURIComponent(name)}`);
        if (data?.success) {
            this._scenes = this._scenes
                .filter(s => s.name.toLowerCase() !== name.toLowerCase());
            this._renderSceneList();
            this._showToast(`${name} gelöscht`);
        }
    }

    _openSceneEditor(existing) {
        const editor = document.getElementById("harmony-scene-editor");
        const nameInput = document.getElementById("harmony-scene-name");
        const stepsDiv = document.getElementById("harmony-scene-steps");
        if (!editor) return;

        editor.style.display = "";
        stepsDiv.innerHTML = "";

        if (existing) {
            nameInput.value = existing.name;
            (existing.steps || []).forEach(step => this._addSceneStep(step));
        } else {
            nameInput.value = "";
            this._addSceneStep();
        }
    }

    _closeSceneEditor() {
        const editor = document.getElementById("harmony-scene-editor");
        if (editor) editor.style.display = "none";
    }

    _addSceneStep(step) {
        const stepsDiv = document.getElementById("harmony-scene-steps");
        if (!stepsDiv) return;

        const row = document.createElement("div");
        row.className = "scene-step";

        const devSel = document.createElement("select");
        (this._detailedConfig.devices || []).forEach(d => {
            const opt = document.createElement("option");
            opt.value = d.label; opt.textContent = d.label;
            devSel.appendChild(opt);
        });
        if (step?.device) devSel.value = step.device;

        const cmdInput = document.createElement("input");
        cmdInput.type = "text";
        cmdInput.placeholder = "Command";
        if (step?.cmd) cmdInput.value = step.cmd;

        const delayInput = document.createElement("input");
        delayInput.type = "number";
        delayInput.placeholder = "s";
        delayInput.min = "0"; delayInput.step = "0.5";
        delayInput.style.maxWidth = "60px";
        if (step?.delay_after) delayInput.value = step.delay_after;

        const removeBtn = document.createElement("button");
        removeBtn.textContent = "\u2715";
        removeBtn.style.cssText = "width:36px;padding:6px;font-size:0.9em;";
        removeBtn.addEventListener("click", () => row.remove());

        row.append(devSel, cmdInput, delayInput, removeBtn);
        stepsDiv.appendChild(row);
    }

    async _saveScene() {
        const nameInput = document.getElementById("harmony-scene-name");
        const name = nameInput?.value?.trim();
        if (!name) { this._showToast("Name eingeben"); return; }

        const stepRows = document.querySelectorAll("#harmony-scene-steps .scene-step");
        const steps = [];
        stepRows.forEach(row => {
            const selects = row.querySelectorAll("select");
            const inputs = row.querySelectorAll("input");
            const device = selects[0]?.value || "";
            const cmd = inputs[0]?.value?.trim() || "";
            const delay = parseFloat(inputs[1]?.value) || 0;
            if (device && cmd) {
                const s = { device, cmd };
                if (delay > 0) s.delay_after = delay;
                steps.push(s);
            }
        });

        if (steps.length === 0) { this._showToast("Mindestens ein Step"); return; }

        const data = await this._apiCall("POST", "/harmony/scenes", { name, steps });
        if (data?.success) {
            this._showToast(`${name} gespeichert`);
            this._closeSceneEditor();
            await this._loadScenes();
        } else {
            this._showToast(data?.error || "Fehler");
        }
    }
}
