/**
 * HarmonyModule – Harmony Remote als Dashboard-Modul.
 *
 * Fernbedienungs-Layout mit geräteabhängigem UI,
 * Haptic Feedback + Long-Press Repeat.
 */
import { DashboardModule } from "./base.js";

// -- Geräte-Layouts (Fallback wenn Server keine liefert) ------------------- //
const DEVICE_LAYOUTS = {
    "Samsung TV": {
        icon: "\ud83d\udcfa",
        power: { cmd: "PowerToggle", label: "ON/OFF TV" },
        volume: { device: "Samsung TV", up: "VolumeUp", down: "VolumeDown" },
        channel: { up: "ChannelUp", down: "ChannelDown" },
        dpad: { center: "Select" },
        actions: [
            { cmd: "Return", label: "\u2190 Zur\u00fcck" },
            { cmd: "Home", label: "\u2302 Home" },
            { cmd: "Menu", label: "\u2630 Men\u00fc" },
        ],
        extras: [
            { cmd: "Guide", label: "Guide" },
            { cmd: "Info", label: "Info" },
            { cmd: "Exit", label: "Exit" },
            { cmd: "Source", label: "Source" },
        ],
        hasNumpad: true,
        mute: { device: "Samsung TV", cmd: "Mute" },
    },
    "Denon AV-Empf\u00e4nger": {
        icon: "\ud83d\udd0a",
        power: { cmd: "PowerToggle", label: "ON/OFF Receiver" },
        volume: { device: "Denon AV-Empf\u00e4nger", up: "VolumeUp", down: "VolumeDown" },
        channel: null,
        dpad: null,
        actions: [],
        extras: [
            { cmd: "InputCd", label: "CD" },
            { cmd: "InputCbl/Sat", label: "SAT" },
            { cmd: "InputMediaPlayer", label: "Media" },
            { cmd: "InputBluRay", label: "Blu-Ray" },
            { cmd: "InputGame", label: "Game" },
            { cmd: "InputAux1", label: "AUX" },
        ],
        hasNumpad: false,
        mute: { device: "Denon AV-Empf\u00e4nger", cmd: "Mute" },
        customCenter: [
            { cmd: "SurroundMode", label: "Surround" },
            { cmd: "Sleep", label: "Sleep" },
        ],
    },
    "Sony PS4": {
        icon: "\ud83c\udfae",
        power: { cmd: "PowerToggle", label: "ON/OFF PS4" },
        volume: { device: "Denon AV-Empf\u00e4nger", up: "VolumeUp", down: "VolumeDown" },
        channel: null,
        dpad: { center: "Cross" },
        actions: [
            { cmd: "Circle", label: "\u25cb Circle" },
            { cmd: "Cross", label: "\u00d7 Cross" },
            { cmd: "Triangle", label: "\u25b3 Triangle" },
            { cmd: "Square", label: "\u25a1 Square" },
        ],
        extras: [
            { cmd: "PS", label: "PS" },
            { cmd: "Options", label: "Options" },
            { cmd: "Share", label: "Share" },
        ],
        hasNumpad: false,
        mute: { device: "Denon AV-Empf\u00e4nger", cmd: "Mute" },
    },
    "Amazon Fire TV": {
        icon: "\ud83d\udd25",
        power: { cmd: "PowerToggle", label: "ON/OFF Fire TV" },
        volume: { device: "Denon AV-Empf\u00e4nger", up: "VolumeUp", down: "VolumeDown" },
        channel: null,
        dpad: { center: "Select" },
        actions: [
            { cmd: "Back", label: "\u2190 Zur\u00fcck" },
            { cmd: "Home", label: "\u2302 Home" },
            { cmd: "Menu", label: "\u2630 Men\u00fc" },
        ],
        extras: [
            { cmd: "Play", label: "\u25b6" },
            { cmd: "Pause", label: "\u23f8" },
            { cmd: "Rewind", label: "\u25c4\u25c4" },
            { cmd: "FastForward", label: "\u25b6\u25b6" },
        ],
        hasNumpad: false,
        mute: { device: "Denon AV-Empf\u00e4nger", cmd: "Mute" },
    },
    "Windows-Computer": {
        icon: "\ud83d\udcbb",
        power: null,
        volume: { device: "Denon AV-Empf\u00e4nger", up: "VolumeUp", down: "VolumeDown" },
        channel: null,
        dpad: { center: "Enter" },
        actions: [
            { cmd: "Back", label: "\u2190 Zur\u00fcck" },
            { cmd: "Escape", label: "Esc" },
        ],
        extras: [
            { cmd: "Play", label: "\u25b6" },
            { cmd: "Pause", label: "\u23f8" },
            { cmd: "SkipBack", label: "\u25c4\u25c4" },
            { cmd: "SkipForward", label: "\u25b6\u25b6" },
        ],
        hasNumpad: false,
        mute: { device: "Denon AV-Empf\u00e4nger", cmd: "Mute" },
    },
};

// Fallback für unbekannte Geräte
const GENERIC_LAYOUT = {
    icon: "\u2699\ufe0f",
    power: { cmd: "PowerToggle", label: "ON/OFF Power" },
    volume: null, channel: null,
    dpad: { center: "Select" },
    actions: [],
    extras: [],
    hasNumpad: false,
    mute: null,
};

export default class HarmonyModule extends DashboardModule {

    constructor(config) {
        super(config);
        this._layouts = { activities: {}, devices: {} };
        this._detailedConfig = { activities: [], devices: [] };
        this._scenes = [];
        this._currentTab = "remote";
        this._selectedDevice = "Samsung TV";
        this._longPressTimer = null;
        this._longPressInterval = null;
    }

    render() {
        return `
        <div class="card" id="harmony-card">
            <div class="card-header">
                <span class="card-title">Fernbedienung</span>
                <span id="harmony-status" class="status-dot"></span>
            </div>
            <div id="harmony-current" class="current-activity">Verbinde...</div>

            <div class="tabs" id="harmony-tabs">
                <div class="tab active" data-mode="remote">Remote</div>
                <div class="tab" data-mode="numpad">Numpad</div>
                <div class="tab" data-mode="activities">Quellen</div>
                <div class="tab" data-mode="scenes">Szenen</div>
            </div>

            <!-- Remote-Modus -->
            <div id="harmony-remote-view" class="remote-view">
                <!-- Geräte-Selector -->
                <div class="device-bar" id="harmony-device-bar"></div>

                <!-- Dynamisches Remote-Layout -->
                <div id="harmony-remote-body"></div>

                <!-- Power (immer sichtbar) -->
                <button class="rbtn rbtn-power" id="harmony-off">&#x23FB; Alles Aus</button>
            </div>

            <!-- Numpad-Modus -->
            <div id="harmony-numpad-view" style="display:none;">
                <div class="remote-numpad" id="harmony-numpad"></div>
            </div>

            <!-- Quellen/Aktivitäten-Modus -->
            <div id="harmony-activities-view" style="display:none;">
                <div id="harmony-act-list" class="remote-act-list"></div>
            </div>

            <!-- Szenen-Modus -->
            <div id="harmony-scenes-view" style="display:none;">
                <div id="harmony-scene-list" class="scene-list"></div>
                <div style="margin-top:8px;">
                    <button class="rbtn rbtn-action" id="harmony-new-scene"
                        >+ Neue Szene</button>
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
        </div>

        <div id="harmony-toast" class="toast"></div>

        <style>
            .remote-view { padding: 4px 0; }

            /* Geräte-Selector-Bar */
            .device-bar {
                display: flex; gap: 6px; margin-bottom: 14px;
                overflow-x: auto; padding: 2px 0 8px;
                -webkit-overflow-scrolling: touch;
                scrollbar-width: none;
            }
            .device-bar::-webkit-scrollbar { display: none; }
            #harmony-card { overflow: visible; }
            .device-chip {
                flex-shrink: 0; padding: 8px 14px;
                background: var(--bg-card-hover);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 20px;
                font-size: 0.78em; color: var(--text-muted);
                cursor: pointer; transition: all 0.15s;
                white-space: nowrap;
                touch-action: manipulation;
                user-select: none; -webkit-user-select: none;
            }
            .device-chip.selected {
                background: var(--accent);
                border-color: var(--accent);
                color: #fff;
            }

            /* Device Power Toggle */
            .remote-power-row {
                display: flex; justify-content: center;
                margin-bottom: 14px;
            }
            .rbtn-device-power {
                padding: 8px 24px; font-size: 0.85em;
                border-radius: 20px;
                border-color: var(--accent-light);
                color: var(--accent-light);
                background: transparent;
            }
            .rbtn-device-power:active {
                background: var(--accent);
                color: #fff;
            }

            /* Remote Main (Vol | DPad | CH) */
            .remote-main {
                display: flex; align-items: center; justify-content: center;
                gap: 12px; margin-bottom: 16px;
            }
            .remote-side {
                display: flex; flex-direction: column; align-items: center; gap: 8px;
            }
            .remote-side-label {
                font-size: 0.65em; text-transform: uppercase;
                letter-spacing: 1px; color: var(--text-muted);
            }

            /* D-Pad */
            .remote-dpad {
                display: grid;
                grid-template-columns: 56px 56px 56px;
                grid-template-rows: 56px 56px 56px;
                gap: 4px;
            }
            .dpad-up    { grid-column: 2; grid-row: 1; }
            .dpad-left  { grid-column: 1; grid-row: 2; }
            .dpad-center{ grid-column: 2; grid-row: 2; }
            .dpad-right { grid-column: 3; grid-row: 2; }
            .dpad-down  { grid-column: 2; grid-row: 3; }

            /* Remote Buttons */
            .rbtn {
                background: var(--bg-card-hover);
                color: var(--text-primary);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: var(--radius-btn);
                font-size: 1em; cursor: pointer;
                transition: transform 0.08s, background 0.12s;
                touch-action: manipulation;
                user-select: none; -webkit-user-select: none;
            }
            .rbtn:active {
                transform: scale(0.92);
                background: var(--accent);
            }
            .rbtn-round {
                width: 50px; height: 50px; border-radius: 50%;
                font-size: 1.3em; font-weight: 700;
                display: flex; align-items: center; justify-content: center;
            }
            .rbtn-dpad {
                width: 100%; height: 100%;
                display: flex; align-items: center; justify-content: center;
                font-size: 1.2em; border-radius: 12px;
            }
            .dpad-center {
                background: var(--accent) !important;
                border-color: var(--accent);
                font-weight: 700; font-size: 0.95em;
            }
            .remote-actions {
                display: flex; gap: 8px; margin-bottom: 12px;
            }
            .rbtn-action {
                flex: 1; padding: 10px 6px;
                font-size: 0.82em; border-radius: 10px;
            }
            .rbtn-mute {
                border-color: var(--status-warn);
                color: var(--status-warn);
            }
            .rbtn-power {
                width: 100%; padding: 12px;
                border-color: var(--status-error);
                color: var(--status-error);
                font-size: 0.9em; border-radius: 12px;
                background: transparent;
            }
            .rbtn-power:active {
                background: rgba(239,68,68,0.2);
                transform: scale(0.97);
            }

            /* Extras Grid */
            .remote-extras {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 6px; margin-bottom: 12px;
            }
            .remote-extras .rbtn {
                padding: 10px 4px; font-size: 0.78em;
                border-radius: 10px;
            }

            /* Center-Bereich (Denon etc.) */
            .remote-center-block {
                display: flex; flex-direction: column; gap: 8px;
                align-items: center; margin-bottom: 16px;
            }
            .remote-center-block .rbtn {
                width: 200px; padding: 14px; font-size: 0.9em;
                border-radius: 12px;
            }

            /* Numpad */
            .remote-numpad {
                display: grid; grid-template-columns: repeat(3, 1fr);
                gap: 6px; max-width: 280px; margin: 0 auto;
            }
            .remote-numpad .rbtn {
                padding: 18px 8px; font-size: 1.3em; font-weight: 500;
                border-radius: 12px;
            }

            /* Aktivitäten */
            .remote-act-list {
                display: flex; flex-direction: column; gap: 8px;
            }
            .rbtn-activity {
                padding: 14px 12px; font-size: 0.95em;
                border-radius: 12px; text-align: left;
            }

            /* Long-press */
            .rbtn-repeat.pressing {
                box-shadow: 0 0 0 3px rgba(124,58,237,0.4);
            }

            /* No-dpad message */
            .remote-no-dpad {
                text-align: center; padding: 12px;
                color: var(--text-muted); font-size: 0.85em;
            }
        </style>`;
    }

    get pollInterval() { return 10000; }

    async init() {
        this._bindTabs();
        this._bindSceneButtons();
        document.getElementById("harmony-off")
            ?.addEventListener("click", () => { this._haptic(); this._powerOff(); });
        await this._loadConfig();
        this._buildDeviceBar();
        this._renderRemote();
        this._buildNumpad();
        this._renderSceneList();
        await this.poll();
    }

    async poll() { await this._pollStatus(); }

    // -- API -------------------------------------------------------------- //

    _api() { return this.config.rpi5_url; }

    async _apiCall(method, path, body) {
        const url = this._api() + path;
        const opts = { method, headers: { "Content-Type": "application/json" } };
        if (body) opts.body = JSON.stringify(body);
        try {
            const r = await fetch(url, opts);
            if (!r.ok) return null;
            return await r.json();
        } catch { return null; }
    }

    _haptic() { if (navigator.vibrate) navigator.vibrate(15); }

    // -- Long-Press ------------------------------------------------------- //

    _bindLongPress(btn, device, cmd) {
        const fire = () => { this._haptic(); this._sendCommand(device, cmd); };
        const start = (e) => {
            e.preventDefault();
            fire();
            btn.classList.add("pressing");
            this._longPressTimer = setTimeout(() => {
                this._longPressInterval = setInterval(fire, 200);
            }, 400);
        };
        const stop = () => {
            btn.classList.remove("pressing");
            clearTimeout(this._longPressTimer);
            clearInterval(this._longPressInterval);
        };
        btn.addEventListener("pointerdown", start);
        btn.addEventListener("pointerup", stop);
        btn.addEventListener("pointerleave", stop);
        btn.addEventListener("pointercancel", stop);
    }

    // -- Status ----------------------------------------------------------- //

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

    // -- Config ----------------------------------------------------------- //

    async _loadConfig() {
        try {
            let configData = await this._apiCall("GET", "/harmony/config/detailed");
            if (!configData) {
                const basic = await this._apiCall("GET", "/harmony/config");
                if (basic) {
                    configData = {
                        activities: (basic.activities || []).map(a => ({ label: a })),
                        devices: (basic.devices || []).map(d => ({
                            label: d, control_groups: [],
                        })),
                    };
                }
            }
            if (configData) this._detailedConfig = configData;
            const layoutData = await this._apiCall("GET", "/harmony/layouts");
            if (layoutData) this._layouts = layoutData;
            const sceneData = await this._apiCall("GET", "/harmony/scenes");
            if (sceneData) this._scenes = sceneData.scenes || [];
        } catch { /* graceful */ }
        this._renderActivities();
    }

    // -- Tabs ------------------------------------------------------------- //

    _bindTabs() {
        document.querySelectorAll("#harmony-tabs .tab").forEach(tab => {
            tab.addEventListener("click", () => {
                this._haptic();
                document.querySelectorAll("#harmony-tabs .tab")
                    .forEach(t => t.classList.remove("active"));
                tab.classList.add("active");
                this._currentTab = tab.dataset.mode;
                ["remote","numpad","activities","scenes"].forEach(v => {
                    const el = document.getElementById(`harmony-${v}-view`);
                    if (el) el.style.display = this._currentTab === v ? "" : "none";
                });
            });
        });
    }

    // -- Device Bar ------------------------------------------------------- //

    _buildDeviceBar() {
        const bar = document.getElementById("harmony-device-bar");
        if (!bar) return;
        bar.innerHTML = "";

        const devices = this._detailedConfig.devices || [];
        devices.forEach(d => {
            const layout = DEVICE_LAYOUTS[d.label] || GENERIC_LAYOUT;
            const chip = document.createElement("div");
            chip.className = "device-chip" +
                (d.label === this._selectedDevice ? " selected" : "");
            chip.textContent = `${layout.icon} ${d.label}`;
            chip.addEventListener("click", () => {
                this._haptic();
                this._selectedDevice = d.label;
                bar.querySelectorAll(".device-chip")
                    .forEach(c => c.classList.remove("selected"));
                chip.classList.add("selected");
                this._renderRemote();
                // Numpad-Tab nur zeigen wenn Gerät es unterstützt
                const numpadTab = document.querySelector(
                    '#harmony-tabs .tab[data-mode="numpad"]');
                if (numpadTab) {
                    numpadTab.style.display = this._getLayout().hasNumpad ? "" : "none";
                }
            });
            bar.appendChild(chip);
        });
    }

    _getLayout() {
        return DEVICE_LAYOUTS[this._selectedDevice] || GENERIC_LAYOUT;
    }

    // -- Remote Rendering ------------------------------------------------- //

    _renderRemote() {
        const body = document.getElementById("harmony-remote-body");
        if (!body) return;
        body.innerHTML = "";

        const layout = this._getLayout();
        const dev = this._selectedDevice;

        // -- Power-Toggle für dieses Gerät
        if (layout.power) {
            const powerRow = document.createElement("div");
            powerRow.className = "remote-power-row";
            const powerBtn = this._makeBtn(
                dev, layout.power.cmd, layout.power.label,
                "rbtn rbtn-device-power");
            powerRow.appendChild(powerBtn);
            body.appendChild(powerRow);
        }

        // -- Hauptbereich: Volume | D-Pad/Center | Channel
        const main = document.createElement("div");
        main.className = "remote-main";

        // Volume (links)
        if (layout.volume) {
            const volSide = this._buildSide(
                layout.volume.device, layout.volume.up, layout.volume.down, "Vol");
            main.appendChild(volSide);
        }

        // Mitte: D-Pad oder Custom Center
        if (layout.dpad) {
            main.appendChild(this._buildDpad(dev, layout.dpad.center));
        } else if (layout.customCenter) {
            const center = document.createElement("div");
            center.className = "remote-center-block";
            layout.customCenter.forEach(c => {
                const btn = this._makeBtn(dev, c.cmd, c.label);
                center.appendChild(btn);
            });
            main.appendChild(center);
        }

        // Channel (rechts)
        if (layout.channel) {
            const chSide = this._buildSide(
                dev, layout.channel.up, layout.channel.down, "CH");
            main.appendChild(chSide);
        }

        body.appendChild(main);

        // -- Action-Buttons + Mute
        if (layout.actions.length > 0 || layout.mute) {
            const actions = document.createElement("div");
            actions.className = "remote-actions";

            layout.actions.forEach(a => {
                const btn = this._makeBtn(dev, a.cmd, a.label, "rbtn rbtn-action");
                actions.appendChild(btn);
            });

            if (layout.mute) {
                const muteBtn = this._makeBtn(
                    layout.mute.device, layout.mute.cmd,
                    "\ud83d\udd07 Stumm", "rbtn rbtn-action rbtn-mute");
                actions.appendChild(muteBtn);
            }

            body.appendChild(actions);
        }

        // -- Extras Grid
        if (layout.extras.length > 0) {
            const extras = document.createElement("div");
            extras.className = "remote-extras";
            layout.extras.forEach(e => {
                extras.appendChild(this._makeBtn(dev, e.cmd, e.label));
            });
            body.appendChild(extras);
        }
    }

    _buildSide(device, upCmd, downCmd, label) {
        const side = document.createElement("div");
        side.className = "remote-side";

        const upBtn = document.createElement("button");
        upBtn.className = "rbtn rbtn-round rbtn-repeat";
        upBtn.textContent = "+";
        this._bindLongPress(upBtn, device, upCmd);
        side.appendChild(upBtn);

        const lbl = document.createElement("div");
        lbl.className = "remote-side-label";
        lbl.textContent = label;
        side.appendChild(lbl);

        const downBtn = document.createElement("button");
        downBtn.className = "rbtn rbtn-round rbtn-repeat";
        downBtn.textContent = "\u2212";
        this._bindLongPress(downBtn, device, downCmd);
        side.appendChild(downBtn);

        return side;
    }

    _buildDpad(device, centerCmd) {
        const grid = document.createElement("div");
        grid.className = "remote-dpad";

        const dirs = [
            ["DirectionUp", "\u25b2", "dpad-up"],
            ["DirectionLeft", "\u25c4", "dpad-left"],
            [centerCmd || "Select", "OK", "dpad-center"],
            ["DirectionRight", "\u25ba", "dpad-right"],
            ["DirectionDown", "\u25bc", "dpad-down"],
        ];

        dirs.forEach(([cmd, label, cls]) => {
            const btn = document.createElement("button");
            btn.className = `rbtn rbtn-dpad ${cls}`;
            btn.textContent = label;
            btn.addEventListener("click", () => {
                this._haptic();
                this._sendCommand(device, cmd);
            });
            grid.appendChild(btn);
        });

        return grid;
    }

    _makeBtn(device, cmd, label, className) {
        const btn = document.createElement("button");
        btn.className = className || "rbtn";
        btn.textContent = label || cmd;
        btn.addEventListener("click", () => {
            this._haptic();
            this._sendCommand(device, cmd);
        });
        return btn;
    }

    // -- Numpad ----------------------------------------------------------- //

    _buildNumpad() {
        const container = document.getElementById("harmony-numpad");
        if (!container) return;
        container.innerHTML = "";

        const dev = this._selectedDevice;
        const keys = ["1","2","3","4","5","6","7","8","9","CH-","0","CH+"];
        keys.forEach(k => {
            const btn = document.createElement("button");
            btn.className = "rbtn";
            if (k === "CH-") {
                btn.textContent = "CH\u25bc";
                btn.addEventListener("click", () => {
                    this._haptic(); this._sendCommand(dev, "ChannelDown");
                });
            } else if (k === "CH+") {
                btn.textContent = "CH\u25b2";
                btn.addEventListener("click", () => {
                    this._haptic(); this._sendCommand(dev, "ChannelUp");
                });
            } else {
                btn.textContent = k;
                btn.addEventListener("click", () => {
                    this._haptic(); this._sendCommand(dev, `Number${k}`);
                });
            }
            container.appendChild(btn);
        });

        // Numpad-Tab Sichtbarkeit
        const numpadTab = document.querySelector(
            '#harmony-tabs .tab[data-mode="numpad"]');
        if (numpadTab) {
            numpadTab.style.display = this._getLayout().hasNumpad ? "" : "none";
        }
    }

    // -- Activities ------------------------------------------------------- //

    _renderActivities() {
        const list = document.getElementById("harmony-act-list");
        if (!list) return;
        list.innerHTML = "";

        (this._detailedConfig.activities || []).forEach(a => {
            const btn = document.createElement("button");
            btn.className = "rbtn rbtn-activity";
            btn.textContent = a.label;
            btn.addEventListener("click", () => {
                this._haptic(); this._startActivity(a.label);
            });
            list.appendChild(btn);
        });

        const offBtn = document.createElement("button");
        offBtn.className = "rbtn rbtn-activity";
        offBtn.style.cssText = "border-color:var(--status-error);color:var(--status-error);";
        offBtn.textContent = "Alles Aus";
        offBtn.addEventListener("click", () => { this._haptic(); this._powerOff(); });
        list.appendChild(offBtn);
    }

    // -- Toast ------------------------------------------------------------ //

    _showToast(msg, ms = 2000) {
        const el = document.getElementById("harmony-toast");
        if (!el) return;
        el.textContent = msg;
        el.classList.add("show");
        setTimeout(() => el.classList.remove("show"), ms);
    }

    // -- Commands --------------------------------------------------------- //

    async _sendCommand(device, command) {
        const data = await this._apiCall("POST", "/harmony/command",
            { device, command });
        if (!data || !data.success) this._showToast("Befehl fehlgeschlagen");
    }

    async _startActivity(name) {
        const data = await this._apiCall("POST", "/harmony/activity",
            { activity: name });
        this._showToast(data?.success ? `${name} gestartet` : "Fehler");
        this._pollStatus();
    }

    async _powerOff() {
        const data = await this._apiCall("POST", "/harmony/off");
        this._showToast(data?.success ? "Alles aus" : "Fehler");
        this._pollStatus();
    }

    // -- Scenes ----------------------------------------------------------- //

    _bindSceneButtons() {
        document.getElementById("harmony-new-scene")
            ?.addEventListener("click", () => this._openSceneEditor());
        document.getElementById("harmony-add-step")
            ?.addEventListener("click", () => this._addSceneStep());
        document.getElementById("harmony-save-scene")
            ?.addEventListener("click", () => this._saveScene());
        document.getElementById("harmony-cancel-scene")
            ?.addEventListener("click", () => this._closeSceneEditor());
    }

    _renderSceneList() {
        const list = document.getElementById("harmony-scene-list");
        if (!list) return;
        list.innerHTML = "";

        if (this._scenes.length === 0) {
            list.innerHTML = '<div class="muted-text">Keine Szenen vorhanden</div>';
            return;
        }
        this._scenes.forEach(scene => {
            const row = document.createElement("div");
            row.style.cssText = "display:flex;align-items:center;gap:6px;margin-bottom:6px;";
            const startBtn = document.createElement("button");
            startBtn.className = "rbtn rbtn-activity"; startBtn.style.flex = "1";
            startBtn.textContent = `\u25b6 ${scene.name}`;
            startBtn.addEventListener("click", () => this._runScene(scene.name));
            const delBtn = document.createElement("button");
            delBtn.className = "btn-danger";
            delBtn.style.cssText = "width:44px;flex-shrink:0;font-size:1.1em;padding:10px;";
            delBtn.textContent = "\u2715";
            delBtn.addEventListener("click", () => this._deleteScene(scene.name));
            row.append(startBtn, delBtn);
            list.appendChild(row);
        });
    }

    async _runScene(name) {
        this._haptic();
        this._showToast(`${name} wird gestartet...`, 3000);
        const data = await this._apiCall("POST", "/harmony/scene/start", { name });
        if (data?.success) {
            this._showToast(`${name}: ${data.steps_ok}/${data.steps_total} OK`);
        } else { this._showToast(data?.error || "Fehler"); }
        this._pollStatus();
    }

    async _deleteScene(name) {
        const data = await this._apiCall("DELETE",
            `/harmony/scene/${encodeURIComponent(name)}`);
        if (data?.success) {
            this._scenes = this._scenes
                .filter(s => s.name.toLowerCase() !== name.toLowerCase());
            this._renderSceneList();
            this._showToast(`${name} gel\u00f6scht`);
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
        } else { nameInput.value = ""; this._addSceneStep(); }
    }

    _closeSceneEditor() {
        const el = document.getElementById("harmony-scene-editor");
        if (el) el.style.display = "none";
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
        cmdInput.type = "text"; cmdInput.placeholder = "Command";
        if (step?.cmd) cmdInput.value = step.cmd;
        const delayInput = document.createElement("input");
        delayInput.type = "number"; delayInput.placeholder = "s";
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
        const name = document.getElementById("harmony-scene-name")?.value?.trim();
        if (!name) { this._showToast("Name eingeben"); return; }
        const stepRows = document.querySelectorAll("#harmony-scene-steps .scene-step");
        const steps = [];
        stepRows.forEach(row => {
            const sel = row.querySelectorAll("select");
            const inp = row.querySelectorAll("input");
            const device = sel[0]?.value || "";
            const cmd = inp[0]?.value?.trim() || "";
            const delay = parseFloat(inp[1]?.value) || 0;
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
        } else { this._showToast(data?.error || "Fehler"); }
    }

    async _loadScenes() {
        try {
            const data = await this._apiCall("GET", "/harmony/scenes");
            this._scenes = data?.scenes || [];
        } catch { this._scenes = []; }
        this._renderSceneList();
    }
}
