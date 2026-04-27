const TOKEN_KEY = "saleria.settings.token";
const TOKEN_HEADER = "X-Saleria-Settings-Token";
const TEST_SERVICES = new Set([
    "anthropic_api_key", "groq_api_key", "elevenlabs_api_key",
    "matrix_homeserver", "matrix_password", "matrix_access_token",
    "email_user", "smtp_host",
    "nextcloud_url", "stirling_pdf_url",
    "brave_api_key", "google_maps_api_key",
]);

let token = localStorage.getItem(TOKEN_KEY) || "";
let secretsByCategory = {};
let behaviorSchema = {};
let behaviorValues = {};
let activeCategory = null;

function authHeaders() {
    return token ? { [TOKEN_HEADER]: token } : {};
}

function setTokenStatus(state) {
    const el = document.getElementById("tokenStatus");
    if (state === "ok") {
        el.textContent = "Token: aktiv";
        el.className = "token-status ok";
    } else if (state === "fail") {
        el.textContent = "Token: ungültig";
        el.className = "token-status fail";
    } else {
        el.textContent = "Token: nicht gesetzt";
        el.className = "token-status";
    }
}

function showTokenModal() {
    document.getElementById("tokenModal").classList.remove("hidden");
    document.getElementById("tokenInput").focus();
}
function hideTokenModal() {
    document.getElementById("tokenModal").classList.add("hidden");
}
document.getElementById("tokenSubmit").addEventListener("click", () => {
    const v = document.getElementById("tokenInput").value.trim();
    if (!v) return;
    token = v;
    localStorage.setItem(TOKEN_KEY, token);
    hideTokenModal();
    setTokenStatus("ok");
});

async function loadAll() {
    try {
        const [secResp, schemaResp, valResp] = await Promise.all([
            fetch("/api/secrets/status"),
            fetch("/api/settings/schema"),
            fetch("/api/settings/values"),
        ]);
        const sec = await secResp.json();
        const schema = await schemaResp.json();
        const values = await valResp.json();

        secretsByCategory = {};
        if (sec.available && sec.categories) {
            for (const cat of sec.categories) {
                secretsByCategory[cat.name] = cat.keys;
            }
        }
        behaviorSchema = {};
        for (const def of schema.settings || []) {
            behaviorSchema[def.key] = def;
        }
        behaviorValues = values.values || {};
        renderTabs();
    } catch (e) {
        const container = document.getElementById("fieldContainer");
        const div = document.createElement("div");
        div.className = "empty-tab";
        div.textContent = "Fehler beim Laden: " + e.message;
        container.replaceChildren(div);
    }
}

function renderTabs() {
    const cats = Object.keys(secretsByCategory).sort();
    // Verhalten + Sicherheit aus dem Schema synthetisieren
    const behaviorCats = new Set();
    for (const def of Object.values(behaviorSchema)) {
        behaviorCats.add(def.category);
    }
    for (const c of behaviorCats) {
        if (!cats.includes(c)) cats.push(c);
    }
    const tabList = document.getElementById("tabList");
    tabList.innerHTML = "";
    for (const cat of cats) {
        const btn = document.createElement("button");
        btn.className = "tab-button";
        btn.textContent = cat;
        btn.addEventListener("click", () => selectTab(cat));
        tabList.appendChild(btn);
    }
    if (cats.length > 0) {
        const initial = window.location.hash.replace("#", "") || cats[0];
        selectTab(decodeURIComponent(initial));
    }
}

function selectTab(cat) {
    activeCategory = cat;
    document.getElementById("currentTab").textContent = cat;
    for (const btn of document.querySelectorAll(".tab-button")) {
        btn.classList.toggle("active", btn.textContent === cat);
    }
    renderFields();
    window.location.hash = encodeURIComponent(cat);
}

function renderFields() {
    const container = document.getElementById("fieldContainer");
    container.innerHTML = "";
    const secrets = secretsByCategory[activeCategory] || [];
    const behavior = Object.values(behaviorSchema).filter(
        d => d.category === activeCategory,
    );
    if (secrets.length === 0 && behavior.length === 0) {
        container.innerHTML = `<div class="empty-tab">Keine Einträge.</div>`;
        return;
    }
    for (const item of secrets) {
        container.appendChild(renderSecretField(item));
    }
    for (const def of behavior) {
        container.appendChild(renderBehaviorField(def));
    }
}

function makeBadges({ riskLevel, restartRequired, isSet, secret }) {
    const badges = document.createElement("div");
    badges.className = "badges";
    if (secret) {
        const b = document.createElement("span");
        b.className = "badge " + (isSet ? "set" : "unset");
        b.textContent = isSet ? "gesetzt" : "leer";
        badges.appendChild(b);
    }
    if (riskLevel === "high" || riskLevel === "medium") {
        const b = document.createElement("span");
        b.className = "badge " + riskLevel;
        b.textContent = riskLevel === "high" ? "kritisch" : "vorsicht";
        badges.appendChild(b);
    }
    if (restartRequired) {
        const b = document.createElement("span");
        b.className = "badge restart";
        b.textContent = "Restart";
        badges.appendChild(b);
    }
    return badges;
}

function renderSecretField(item) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const head = document.createElement("div");
    head.className = "field-header";
    const label = document.createElement("div");
    label.className = "field-label";
    label.textContent = item.label;
    head.appendChild(label);
    head.appendChild(makeBadges({
        riskLevel: item.risk_level,
        restartRequired: item.requires_restart,
        isSet: item.is_set,
        secret: item.sensitive !== false,
    }));
    wrap.appendChild(head);

    if (item.description) {
        const help = document.createElement("div");
        help.className = "field-help";
        help.textContent = item.description;
        wrap.appendChild(help);
    }

    const row = document.createElement("div");
    row.className = "field-row";
    const input = document.createElement("input");
    input.type = item.sensitive === false ? "text" : "password";
    input.placeholder = item.is_set ? "•••• (gesetzt)" : "leer";
    row.appendChild(input);

    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Speichern";
    row.appendChild(saveBtn);

    if (TEST_SERVICES.has(item.key)) {
        const testBtn = document.createElement("button");
        testBtn.className = "test";
        testBtn.textContent = "Testen";
        testBtn.addEventListener("click", () => testService(item.key, msg));
        row.appendChild(testBtn);
    }
    wrap.appendChild(row);

    const msg = document.createElement("div");
    msg.className = "field-message";
    wrap.appendChild(msg);

    saveBtn.addEventListener("click", async () => {
        if (!input.value.trim()) {
            msg.textContent = "Wert darf nicht leer sein.";
            msg.className = "field-message error";
            return;
        }
        if (item.risk_level === "high") {
            if (!confirm(`'${item.label}' ist als kritisch markiert. Wirklich überschreiben?`)) {
                return;
            }
        }
        await saveSecret(item.key, input.value, msg, input);
    });
    return wrap;
}

function renderBehaviorField(def) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const head = document.createElement("div");
    head.className = "field-header";
    const label = document.createElement("div");
    label.className = "field-label";
    label.textContent = def.label;
    head.appendChild(label);
    head.appendChild(makeBadges({
        riskLevel: def.riskLevel,
        restartRequired: def.restartRequired,
        isSet: true,
        secret: false,
    }));
    wrap.appendChild(head);

    if (def.helpText) {
        const help = document.createElement("div");
        help.className = "field-help";
        help.textContent = def.helpText;
        wrap.appendChild(help);
    }

    const row = document.createElement("div");
    row.className = "field-row";
    let input;
    const current = behaviorValues[def.key];
    if (def.type === "select" && def.options.length > 0) {
        input = document.createElement("select");
        for (const opt of def.options) {
            const o = document.createElement("option");
            o.value = opt.value;
            o.textContent = opt.label;
            if (String(current) === String(opt.value)) o.selected = true;
            input.appendChild(o);
        }
    } else if (def.type === "textarea") {
        input = document.createElement("textarea");
        input.value = current || "";
        if (def.placeholder) input.placeholder = def.placeholder;
    } else if (def.type === "number") {
        input = document.createElement("input");
        input.type = "number";
        input.value = current ?? "";
        if (def.minValue != null) input.min = def.minValue;
        if (def.maxValue != null) input.max = def.maxValue;
    } else {
        input = document.createElement("input");
        input.type = "text";
        input.value = current ?? "";
    }
    row.appendChild(input);

    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Speichern";
    row.appendChild(saveBtn);
    wrap.appendChild(row);

    const msg = document.createElement("div");
    msg.className = "field-message";
    wrap.appendChild(msg);

    saveBtn.addEventListener("click", async () => {
        if (def.riskLevel === "high") {
            if (!confirm(`'${def.label}' ist als kritisch markiert. Wirklich überschreiben?`)) {
                return;
            }
        }
        await saveBehavior(def.key, input.value, msg);
    });
    return wrap;
}

async function saveSecret(key, value, msg, input) {
    if (!token) { showTokenModal(); return; }
    msg.textContent = "Speichere …";
    msg.className = "field-message";
    try {
        const r = await fetch("/api/secrets/set", {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({ key, value }),
        });
        const data = await r.json();
        if (r.status === 401) {
            setTokenStatus("fail");
            showTokenModal();
            return;
        }
        if (!r.ok) {
            msg.textContent = "Fehler: " + (data.error || r.status);
            msg.className = "field-message error";
            return;
        }
        setTokenStatus("ok");
        msg.textContent = data.requires_restart
            ? "Gespeichert – Neustart erforderlich." : "Gespeichert.";
        msg.className = "field-message ok";
        input.value = "";
        await loadAll();
    } catch (e) {
        msg.textContent = "Netzwerkfehler: " + e;
        msg.className = "field-message error";
    }
}

async function saveBehavior(key, value, msg) {
    if (!token) { showTokenModal(); return; }
    msg.textContent = "Speichere …";
    msg.className = "field-message";
    try {
        const r = await fetch("/api/settings/update", {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({ key, value }),
        });
        const data = await r.json();
        if (r.status === 401) {
            setTokenStatus("fail");
            showTokenModal();
            return;
        }
        if (!r.ok) {
            msg.textContent = "Fehler: " + (data.error || r.status);
            msg.className = "field-message error";
            return;
        }
        setTokenStatus("ok");
        msg.textContent = data.restartRequired
            ? "Gespeichert – Neustart erforderlich." : "Gespeichert.";
        msg.className = "field-message ok";
        await loadAll();
    } catch (e) {
        msg.textContent = "Netzwerkfehler: " + e;
        msg.className = "field-message error";
    }
}

async function testService(key, msg) {
    msg.textContent = "Teste …";
    msg.className = "field-message";
    try {
        const r = await fetch(`/api/setup/test/${encodeURIComponent(key)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({}),
        });
        const data = await r.json();
        if (data.success || r.ok) {
            msg.textContent = data.message || "Verbindung ok.";
            msg.className = "field-message ok";
        } else {
            msg.textContent = "Test fehlgeschlagen: " + (data.error || data.message || r.status);
            msg.className = "field-message error";
        }
    } catch (e) {
        msg.textContent = "Netzwerkfehler: " + e;
        msg.className = "field-message error";
    }
}

// Phase 65 (M-4): Globales Logout-Button im Header.
const logoutAllBtn = document.getElementById("logoutAllBtn");
if (logoutAllBtn) {
    logoutAllBtn.addEventListener("click", async () => {
        const ok = confirm(
            "Alle anderen Sessions abmelden?\n\n" +
            "Deine aktuelle Session bleibt aktiv, aber alle anderen " +
            "Geraete/Browser werden beim naechsten Request ausgeloggt."
        );
        if (!ok) return;
        logoutAllBtn.disabled = true;
        try {
            const r = await fetch("/api/dashboard/logout-all", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
            });
            if (r.ok) {
                alert("Alle anderen Sessions wurden abgemeldet.");
            } else if (r.status === 401) {
                alert("Login abgelaufen. Bitte neu einloggen.");
                window.location.href = "/login";
            } else {
                alert("Fehler (" + r.status + ") beim Abmelden.");
            }
        } catch (e) {
            alert("Netzwerkfehler: " + e);
        } finally {
            logoutAllBtn.disabled = false;
        }
    });
}

if (token) setTokenStatus("ok");
loadAll();
