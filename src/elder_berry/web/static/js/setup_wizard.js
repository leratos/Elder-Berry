const TOTAL_STEPS = 8;
let currentStep = 1;
let providers = {};

// Helper: get value from input
function v(id) { return document.getElementById(id)?.value || ''; }

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    buildProgressBar();
    bindNavigationHandlers();
    bindTestHandlers();
    bindMiscHandlers();
    await loadPrerequisites();
    await loadProviders();
    await loadStatus();
});

function buildProgressBar() {
    const bar = document.getElementById('progressBar');
    bar.innerHTML = '';
    for (let i = 1; i <= TOTAL_STEPS; i++) {
        const s = document.createElement('div');
        s.className = 'progress-step';
        s.dataset.step = i;
        bar.appendChild(s);
    }
}

function updateProgressBar() {
    document.querySelectorAll('.progress-step').forEach(el => {
        const s = parseInt(el.dataset.step);
        el.className = 'progress-step';
        if (s < currentStep) el.classList.add('done');
        else if (s === currentStep) el.classList.add('active');
    });
}

function goToStep(n) {
    currentStep = n;
    document.querySelectorAll('.step').forEach(el => el.classList.remove('active'));
    const step = document.getElementById('step' + n);
    if (step) step.classList.add('active');
    updateProgressBar();
    if (n === 2) checkOllama();
    if (n === 8) loadSummary();
    loadStepValues(n);
}

async function loadStatus() {
    try {
        const r = await fetch('/api/setup/status');
        const data = await r.json();
        goToStep(data.current_step || 1);
    } catch {
        goToStep(1);
    }
}

async function loadPrerequisites() {
    try {
        const r = await fetch('/api/setup/prerequisites');
        const data = await r.json();
        const pyEl = document.getElementById('prereqPython');
        const pyOk = data.python && data.python.startsWith('3.1');
        pyEl.textContent = pyOk ? '☑' : '☐';
        pyEl.className = pyOk ? 'check' : 'fail';
        pyEl.parentElement.innerHTML = pyEl.outerHTML + ' Python ' + (data.python || '?');

        const gitEl = document.getElementById('prereqGit');
        gitEl.textContent = data.git ? '☑' : '☐';
        gitEl.className = data.git ? 'check' : 'fail';

        const ollamaEl = document.getElementById('prereqOllama');
        if (data.ollama?.available) {
            ollamaEl.textContent = '☑';
            ollamaEl.className = 'check';
            const models = data.ollama.models?.join(', ') || '';
            ollamaEl.parentElement.innerHTML = ollamaEl.outerHTML + ' Ollama' + (models ? ' (' + models + ')' : '');
        } else {
            ollamaEl.textContent = '☐';
            ollamaEl.className = 'uncheck';
        }
    } catch { /* ignore */ }
}

async function loadProviders() {
    try {
        const r = await fetch('/api/setup/providers');
        providers = await r.json();
        const sel = document.getElementById('emailProvider');
        for (const name of Object.keys(providers)) {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name.charAt(0).toUpperCase() + name.slice(1);
            sel.appendChild(opt);
        }
    } catch { /* ignore */ }
}

function fillEmailProvider() {
    const name = document.getElementById('emailProvider').value;
    if (!name || !providers[name]) return;
    const p = providers[name];
    document.getElementById('email_imap_host').value = p.imap_host;
    document.getElementById('email_imap_port').value = p.imap_port;
    document.getElementById('smtp_host').value = p.smtp_host;
    document.getElementById('smtp_port').value = p.smtp_port;
}

async function loadStepValues(n) {
    try {
        const r = await fetch('/api/setup/step/' + n);
        const data = await r.json();
        if (!data.values) return;
        for (const [key, info] of Object.entries(data.values)) {
            const el = document.getElementById(key);
            if (!el) continue;
            if (info.value !== undefined && info.value !== null) {
                el.value = info.value;
            } else if (info.is_set && el.type === 'password') {
                el.placeholder = '(bereits gesetzt)';
            }
        }
    } catch { /* ignore */ }
}

// Collect step field IDs
const stepFields = {
    2: ['anthropic_api_key'],
    3: ['matrix_homeserver', 'matrix_user_id', 'matrix_access_token', 'matrix_room_id', 'matrix_allowed_senders'],
    4: ['nextcloud_url', 'nextcloud_user', 'nextcloud_app_password'],
    5: ['email_user', 'email_password', 'email_imap_host', 'email_imap_port', 'smtp_host', 'smtp_port'],
    6: ['weather_city', 'weather_latitude', 'weather_longitude', 'user_timezone'],
    7: ['brave_api_key', 'elevenlabs_api_key', 'elevenlabs_voice_id', 'groq_api_key', 'berry_gym_api_token', 'google_maps_api_key', 'robot_host'],
};

async function saveStep(n) {
    const fields = stepFields[n] || [];
    const body = {};
    let hasValue = false;
    for (const id of fields) {
        const val = v(id);
        if (val) { body[id] = val; hasValue = true; }
    }
    const optionalSteps = [4, 5, 6, 7];
    if (!hasValue && optionalSteps.includes(n)) {
        goToStep(n + 1);
        return;
    }
    try {
        const r = await fetch('/api/setup/step/' + n, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
        const data = await r.json();
        if (!r.ok) {
            alert(data.error || 'Fehler beim Speichern');
            return;
        }
        if (data.tests) {
            for (const [service, result] of Object.entries(data.tests)) {
                showTestResult(service, result);
            }
            const anyFailed = Object.values(data.tests).some(t => !t.success);
            if (anyFailed) return;
        }
        goToStep(n + 1);
    } catch (e) {
        alert('Netzwerkfehler: ' + e.message);
    }
}

async function testService(service, params) {
    const el = document.getElementById('test-' + service);
    if (el) {
        el.className = 'test-result loading';
        el.textContent = 'Teste...';
    }
    try {
        const r = await fetch('/api/setup/test/' + service, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(params),
        });
        const data = await r.json();
        showTestResult(service, data);
    } catch (e) {
        if (el) {
            el.className = 'test-result error';
            el.textContent = 'Netzwerkfehler: ' + e.message;
        }
    }
}

function showTestResult(service, result) {
    const el = document.getElementById('test-' + service);
    if (!el) return;
    if (result.success) {
        el.className = 'test-result success';
        let msg = '✅ Verbindung erfolgreich';
        if (result.model) msg += ' (' + result.model + ')';
        if (result.user_id) msg += ' – ' + result.user_id;
        if (result.room_joined) msg += ', Raum OK';
        if (result.webdav !== undefined) {
            msg = '✅ WebDAV: ' + (result.webdav ? 'OK' : 'FAIL') +
                  ', CalDAV: ' + (result.caldav ? 'OK' : 'FAIL') +
                  ', CardDAV: ' + (result.carddav ? 'OK' : 'FAIL');
        }
        if (result.imap !== undefined) {
            msg = '✅ IMAP: ' + (result.imap ? 'OK' : 'FAIL') +
                  ', SMTP: ' + (result.smtp ? 'OK' : 'FAIL');
            if (result.unread > 0) msg += ' (' + result.unread + ' ungelesen)';
        }
        if (result.models) msg += ' – Modelle: ' + result.models.join(', ');
        el.textContent = msg;
    } else {
        el.className = 'test-result error';
        el.textContent = '❌ ' + (result.error || 'Test fehlgeschlagen');
    }
}

async function checkOllama() {
    const el = document.getElementById('test-ollama');
    try {
        const r = await fetch('/api/setup/test/ollama', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: '{}',
        });
        const data = await r.json();
        showTestResult('ollama', data);
    } catch {
        if (el) {
            el.className = 'test-result error';
            el.textContent = '❌ Nicht erreichbar';
        }
    }
}

async function loadSummary() {
    try {
        const r = await fetch('/api/setup/status');
        const data = await r.json();
        const list = document.getElementById('summaryList');
        list.innerHTML = '';
        const labels = {
            anthropic: 'LLM (Claude API)',
            matrix: 'Matrix',
            nextcloud: 'Nextcloud',
            email: 'E-Mail',
            weather: 'Wetter & Standort',
            brave: 'Brave Search',
            elevenlabs: 'ElevenLabs TTS',
            groq: 'Groq STT',
            google_maps: 'Google Maps',
            rpi5: 'RPi5 Hardware',
        };
        const all = [...(data.configured || []), ...(data.missing || [])];
        for (const svc of all) {
            const li = document.createElement('li');
            const ok = (data.configured || []).includes(svc);
            const icon = document.createElement('span');
            icon.className = ok ? 'configured' : 'not-configured';
            icon.textContent = ok ? '✅' : '❌';
            li.appendChild(icon);
            li.appendChild(document.createTextNode(' ' + (labels[svc] || svc)));
            if (!ok) {
                const note = document.createElement('span');
                note.className = 'not-configured-note';
                note.textContent = ' (nicht konfiguriert)';
                li.appendChild(note);
            }
            list.appendChild(li);
        }
    } catch { /* ignore */ }
}

// Phase 63: Ruft den Server-Proxy /api/setup/geocode (statt direkt Nominatim),
// damit CSP connect-src 'self' strikt bleiben kann.
async function geocodeCity() {
    const city = v('weather_city');
    const el = document.getElementById('geocode-result');
    if (!city) {
        el.className = 'test-result error';
        el.textContent = 'Bitte Stadt eingeben.';
        return;
    }
    el.className = 'test-result loading';
    el.textContent = 'Suche...';
    try {
        const r = await fetch('/api/setup/geocode?q=' + encodeURIComponent(city));
        const data = await r.json();
        if (data.success) {
            document.getElementById('weather_latitude').value = data.lat.toFixed(4);
            document.getElementById('weather_longitude').value = data.lon.toFixed(4);
            el.className = 'test-result success';
            el.textContent = '✅ ' + data.display_name;
        } else {
            el.className = 'test-result error';
            el.textContent = '❌ ' + (data.error || 'Ort nicht gefunden.');
        }
    } catch (e) {
        el.className = 'test-result error';
        el.textContent = '❌ Geocoding fehlgeschlagen: ' + e.message;
    }
}

async function completeSetup() {
    const btn = document.querySelector('#step8 .btn-success');
    const errEl = document.getElementById('dashboardPasswordError');
    errEl.textContent = '';

    const pw = document.getElementById('dashboardPassword').value;
    const pw2 = document.getElementById('dashboardPasswordConfirm').value;
    if (!pw || pw.length < 8) {
        errEl.textContent = 'Passwort muss mindestens 8 Zeichen lang sein.';
        return;
    }
    if (pw !== pw2) {
        errEl.textContent = 'Passwörter stimmen nicht überein.';
        return;
    }

    if (btn) { btn.disabled = true; btn.textContent = 'Wird abgeschlossen...'; }
    try {
        const rPw = await fetch('/api/setup/dashboard-password', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password: pw}),
        });
        if (!rPw.ok) {
            const dPw = await rPw.json();
            errEl.textContent = dPw.error || 'Passwort konnte nicht gesetzt werden.';
            if (btn) { btn.disabled = false; btn.textContent = 'Setup abschließen'; }
            return;
        }
        const r = await fetch('/api/setup/complete', {method: 'POST'});
        const data = await r.json();
        if (data.standalone) {
            renderStandaloneCompletion();
        } else if (data.redirect) {
            window.location.href = data.redirect;
        }
    } catch (e) {
        alert('Fehler: ' + e.message);
        if (btn) { btn.disabled = false; btn.textContent = 'Setup abschließen'; }
    }
}

function renderStandaloneCompletion() {
    const step = document.getElementById('step8');
    step.innerHTML = '';
    const h2 = document.createElement('h2');
    h2.textContent = 'Setup abgeschlossen!';
    step.appendChild(h2);

    const p1 = document.createElement('p');
    p1.className = 'completion-success';
    p1.textContent = 'Die Konfiguration wurde gespeichert.';
    step.appendChild(p1);

    const p2 = document.createElement('p');
    p2.className = 'completion-command-label';
    p2.textContent = 'Starte Saleria jetzt mit:';
    step.appendChild(p2);

    const code = document.createElement('code');
    code.className = 'completion-command';
    code.textContent = 'python scripts/start_saleria.py';
    step.appendChild(code);

    const p3 = document.createElement('p');
    p3.className = 'completion-footnote';
    p3.textContent = 'Dieses Fenster kann geschlossen werden.';
    step.appendChild(p3);
}

// =====================================================================
// Phase 63 -- Event-Bindings (ersetzt alle frueheren onclick/onchange)
// =====================================================================
function bindNavigationHandlers() {
    // Hilfs-Funktion: Binde einen Button an "goToStep(n)".
    const nav = [
        ['#step1 .btn-primary', () => goToStep(2)],
        ['#step2 .btn-secondary', () => goToStep(1)],
        ['#step2 .btn-primary', () => saveStep(2)],
        ['#step3 .btn-secondary', () => goToStep(2)],
        ['#step3 .btn-primary', () => saveStep(3)],
        ['#step4 .btn-secondary', () => goToStep(3)],
        ['#step4 .btn-primary', () => saveStep(4)],
        ['#step5 .btn-row .btn-secondary', () => goToStep(4)],
        ['#step5 .btn-row .btn-primary', () => saveStep(5)],
        ['#step6 .btn-secondary', () => goToStep(5)],
        ['#step6 .btn-primary', () => saveStep(6)],
        ['#step7 .btn-secondary', () => goToStep(6)],
        ['#step7 .btn-primary', () => saveStep(7)],
        ['#step8 .btn-secondary', () => goToStep(7)],
        ['#step8 .btn-success', () => completeSetup()],
    ];
    for (const [sel, fn] of nav) {
        const el = document.querySelector(sel);
        if (el) el.addEventListener('click', fn);
    }
}

function bindTestHandlers() {
    // Service-Test-Buttons: per data-Attribute entschluesselt.
    document.querySelectorAll('[data-test-service]').forEach(btn => {
        btn.addEventListener('click', () => {
            const service = btn.dataset.testService;
            const paramsSpec = btn.dataset.testParams || '';
            const params = {};
            if (paramsSpec) {
                // Format: "key1=id1,key2=id2"
                for (const pair of paramsSpec.split(',')) {
                    const [k, id] = pair.split('=');
                    if (k && id) params[k.trim()] = v(id.trim());
                }
            }
            testService(service, params);
        });
    });
}

function bindMiscHandlers() {
    // Matrix-Access-Token Help-Link (war: onclick="alert(...);return false;")
    const mxHelp = document.getElementById('matrixTokenHelp');
    if (mxHelp) {
        mxHelp.addEventListener('click', (ev) => {
            ev.preventDefault();
            alert('Element: Settings → Help & About → Access Token kopieren');
        });
    }
    // E-Mail-Provider-Select
    const provSel = document.getElementById('emailProvider');
    if (provSel) provSel.addEventListener('change', fillEmailProvider);

    // Geocode-Button
    const geoBtn = document.getElementById('btnGeocode');
    if (geoBtn) geoBtn.addEventListener('click', geocodeCity);
}
