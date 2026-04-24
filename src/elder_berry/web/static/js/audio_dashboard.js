// --- Audio ---
const statusEl = document.getElementById("status");
const labelEl = document.getElementById("modeLabel");
const btnEl = document.getElementById("toggleBtn");
const audioInfoEl = document.getElementById("audioInfo");

function updateAudioUI(data) {
    const isLocal = data.mode === "matrix_and_local";
    labelEl.textContent = isLocal ? "Matrix + Lokal" : "Nur Matrix";
    statusEl.className = "status" + (isLocal ? " local" : "");
    btnEl.disabled = !data.local_available;

    if (!data.local_available) {
        btnEl.textContent = "Lokale Wiedergabe nicht verfügbar";
        audioInfoEl.textContent = "sounddevice/AgentClient nicht erkannt";
    } else {
        btnEl.textContent = isLocal
            ? "Lokale Wiedergabe deaktivieren"
            : "Lokale Wiedergabe aktivieren";
        audioInfoEl.textContent = "";
    }
}

async function fetchAudioStatus() {
    try {
        const r = await fetch("/api/audio");
        updateAudioUI(await r.json());
    } catch (e) {
        labelEl.textContent = "Verbindungsfehler";
    }
}

async function toggleAudio() {
    btnEl.disabled = true;
    try {
        const r = await fetch("/api/audio", { method: "POST" });
        updateAudioUI(await r.json());
    } catch (e) {
        labelEl.textContent = "Fehler";
    }
}

// --- Monitor ---
const monitorSelect = document.getElementById("monitorSelect");
const monitorInfo = document.getElementById("monitorInfo");
const monitorCard = document.getElementById("monitorCard");

async function fetchMonitors() {
    try {
        const r = await fetch("/api/monitors");
        const data = await r.json();

        if (!data.available) {
            monitorSelect.innerHTML = '<option value="">Computer Use nicht aktiv</option>';
            monitorSelect.disabled = true;
            monitorInfo.textContent = "ComputerUseController nicht konfiguriert";
            return;
        }

        monitorSelect.innerHTML = "";
        data.monitors.forEach(m => {
            const opt = document.createElement("option");
            opt.value = m.index;
            opt.textContent = `Monitor ${m.index}: ${m.width}x${m.height}`;
            if (m.index === data.selected) opt.selected = true;
            monitorSelect.appendChild(opt);
        });

        const sel = data.monitors.find(m => m.index === data.selected);
        if (sel) {
            monitorInfo.textContent = `Aktiv: ${sel.width}x${sel.height} (Position: ${sel.left}, ${sel.top})`;
        }
    } catch (e) {
        monitorInfo.textContent = "Verbindungsfehler";
    }
}

async function setMonitor(index) {
    if (!index) return;
    try {
        const r = await fetch("/api/monitor", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ index: parseInt(index) }),
        });
        const data = await r.json();
        if (data.error) {
            monitorInfo.textContent = data.error;
        } else {
            const sel = data.monitors.find(m => m.index === data.selected);
            if (sel) {
                monitorInfo.textContent = `Aktiv: ${sel.width}x${sel.height} (Position: ${sel.left}, ${sel.top})`;
            }
        }
    } catch (e) {
        monitorInfo.textContent = "Fehler beim Setzen";
    }
}

// --- Allowed Senders ---
const senderBadge = document.getElementById("senderBadge");
const senderInput = document.getElementById("senderInput");
const senderSaveBtn = document.getElementById("senderSaveBtn");
const senderRemoveBtn = document.getElementById("senderRemoveBtn");
const senderMsg = document.getElementById("senderMsg");

function updateSenderUI(data) {
    if (!data.available) {
        senderBadge.textContent = "Nicht verfügbar";
        senderBadge.className = "status-badge inactive";
        senderInput.disabled = true;
        senderSaveBtn.disabled = true;
        senderRemoveBtn.disabled = true;
        senderMsg.textContent = "SecretStore nicht konfiguriert";
        return;
    }
    senderInput.disabled = false;
    senderSaveBtn.disabled = false;
    if (data.configured) {
        senderBadge.textContent = data.count + " Sender konfiguriert";
        senderBadge.className = "status-badge active";
        senderRemoveBtn.disabled = false;
    } else {
        senderBadge.textContent = "Nicht konfiguriert";
        senderBadge.className = "status-badge inactive";
        senderRemoveBtn.disabled = true;
    }
}

async function fetchSenders() {
    try {
        const r = await fetch("/api/allowed-senders");
        updateSenderUI(await r.json());
    } catch (e) {
        senderMsg.textContent = "Verbindungsfehler";
    }
}

async function saveSenders() {
    const val = senderInput.value.trim();
    if (!val) {
        senderMsg.textContent = "Bitte mindestens eine Matrix-ID eingeben.";
        return;
    }
    senderSaveBtn.disabled = true;
    senderMsg.textContent = "";
    try {
        const r = await fetch("/api/allowed-senders", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ senders: val }),
        });
        const data = await r.json();
        if (data.error) {
            senderMsg.textContent = data.error;
        } else {
            updateSenderUI(data);
            senderInput.value = "";
            senderMsg.textContent = "Gespeichert! Neustart erforderlich.";
        }
    } catch (e) {
        senderMsg.textContent = "Fehler beim Speichern";
    }
    senderSaveBtn.disabled = false;
}

async function removeSenders() {
    senderRemoveBtn.disabled = true;
    senderMsg.textContent = "";
    try {
        const r = await fetch("/api/allowed-senders", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "remove" }),
        });
        const data = await r.json();
        updateSenderUI(data);
        senderMsg.textContent = "Entfernt! Neustart erforderlich.";
    } catch (e) {
        senderMsg.textContent = "Fehler beim Entfernen";
    }
}

// --- Timezone ---
const timezoneSelect = document.getElementById("timezoneSelect");
const timezoneInfo = document.getElementById("timezoneInfo");

async function fetchTimezone() {
    try {
        const r = await fetch("/api/timezone");
        const data = await r.json();

        timezoneSelect.innerHTML = "";
        data.available.forEach(tz => {
            const opt = document.createElement("option");
            opt.value = tz;
            opt.textContent = tz;
            if (tz === data.timezone) opt.selected = true;
            timezoneSelect.appendChild(opt);
        });

        timezoneInfo.textContent = "Aktiv: " + data.timezone;
    } catch (e) {
        timezoneInfo.textContent = "Verbindungsfehler";
    }
}

async function setTimezone(tz) {
    if (!tz) return;
    try {
        const r = await fetch("/api/timezone", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ timezone: tz }),
        });
        const data = await r.json();
        if (data.error) {
            timezoneInfo.textContent = data.error;
        } else {
            timezoneInfo.textContent = "Aktiv: " + data.timezone;
        }
    } catch (e) {
        timezoneInfo.textContent = "Fehler beim Setzen";
    }
}

// --- STT Timeout ---
const sttTimeoutSlider = document.getElementById("sttTimeoutSlider");
const sttTimeoutValue = document.getElementById("sttTimeoutValue");
const sttTimeoutInfo = document.getElementById("sttTimeoutInfo");

async function fetchSttTimeout() {
    try {
        const r = await fetch("/api/stt-timeout");
        const data = await r.json();
        sttTimeoutSlider.value = data.timeout;
        sttTimeoutValue.textContent = data.timeout + "s";
        sttTimeoutInfo.textContent = "Aktiv: " + data.timeout + "s";
        if (!data.available) {
            sttTimeoutInfo.textContent += " (nur gespeichert, Pipeline nicht verbunden)";
        }
    } catch (e) {
        sttTimeoutInfo.textContent = "Verbindungsfehler";
    }
}

async function setSttTimeout(value) {
    try {
        const r = await fetch("/api/stt-timeout", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ timeout: parseFloat(value) }),
        });
        const data = await r.json();
        if (data.error) {
            sttTimeoutInfo.textContent = data.error;
        } else {
            sttTimeoutInfo.textContent = "Aktiv: " + data.timeout + "s";
        }
    } catch (e) {
        sttTimeoutInfo.textContent = "Fehler beim Setzen";
    }
}

// --- Event-Listener (ersetzt die frueheren inline-Handler) ---
btnEl.addEventListener("click", toggleAudio);
monitorSelect.addEventListener("change", (e) => setMonitor(e.target.value));
senderSaveBtn.addEventListener("click", saveSenders);
senderRemoveBtn.addEventListener("click", removeSenders);
timezoneSelect.addEventListener("change", (e) => setTimezone(e.target.value));
sttTimeoutSlider.addEventListener("input", (e) => {
    sttTimeoutValue.textContent = e.target.value + "s";
});
sttTimeoutSlider.addEventListener("change", (e) => setSttTimeout(e.target.value));

// Init
fetchAudioStatus();
fetchMonitors();
fetchSenders();
fetchTimezone();
fetchSttTimeout();
