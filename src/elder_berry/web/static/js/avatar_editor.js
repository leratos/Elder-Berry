// ===== Phase 53.2 – Onboarding =====
const ONBOARDING_KEY = "elderberry.avatar.onboarding.seen";

// Helper: escape HTML to prevent XSS when inserting server data into innerHTML
function escHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function showOnboarding() {
    const overlay = document.getElementById("onboardingOverlay");
    if (overlay) overlay.classList.add("active");
}
function hideOnboarding(markSeen) {
    const overlay = document.getElementById("onboardingOverlay");
    if (overlay) overlay.classList.remove("active");
    if (markSeen) {
        try { localStorage.setItem(ONBOARDING_KEY, "1"); } catch (e) { /* ignore */ }
    }
}
function initOnboarding() {
    const dismiss = document.getElementById("onboardingDismiss");
    const later = document.getElementById("onboardingLater");
    const show = document.getElementById("onboardingShow");
    const overlay = document.getElementById("onboardingOverlay");

    if (dismiss) dismiss.addEventListener("click", () => hideOnboarding(true));
    if (later) later.addEventListener("click", () => hideOnboarding(false));
    if (show) show.addEventListener("click", () => showOnboarding());
    if (overlay) overlay.addEventListener("click", (ev) => {
        if (ev.target === overlay) hideOnboarding(false);
    });
    document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && overlay && overlay.classList.contains("active")) {
            hideOnboarding(false);
        }
    });

    let seen = false;
    try { seen = localStorage.getItem(ONBOARDING_KEY) === "1"; } catch (e) { /* ignore */ }
    if (!seen) showOnboarding();
}
document.addEventListener("DOMContentLoaded", initOnboarding);

// ===== State =====
let assets = {};       // {body: [...], eye: [...], mouth: [...], effect: [...]}
let config = null;     // raw YAML config as object
let emotions = [];     // list of emotion names
let reloadAvailable = false;
let selectedEmotion = 'neutral';
let imageCache = {};   // "category/name" → Image
let isSpeaking = false;
let lipSyncTimer = null;

// ===== Init =====
async function init() {
    const [assetsResp, configResp] = await Promise.all([
        fetch('/api/avatar/assets').then(r => r.json()),
        fetch('/api/avatar/config').then(r => r.json()),
    ]);

    assets = assetsResp;
    config = configResp.config;
    emotions = configResp.emotions;
    reloadAvailable = configResp.reload_available;

    if (!reloadAvailable) {
        document.getElementById('btn-reload').disabled = true;
        document.getElementById('btn-reload').title = 'Kein Renderer verbunden';
    }

    buildAssetBrowser();
    buildEmotionEditor();
    buildPreviewDropdown();
    fillParams();
    preloadImages().then(() => renderPreview());
}

// ===== Asset Browser =====
function buildAssetBrowser() {
    const container = document.getElementById('asset-browser');
    container.innerHTML = '';

    const categories = [
        { key: 'body', label: 'Bodies', gridClass: '' },
        { key: 'eye', label: 'Eyes', gridClass: 'eye-grid' },
        { key: 'mouth', label: 'Mouths', gridClass: 'mouth-grid' },
        { key: 'effect', label: 'Effects', gridClass: 'mouth-grid' },
    ];

    for (const cat of categories) {
        const items = assets[cat.key] || [];
        if (items.length === 0 && cat.key === 'effect') continue;

        const section = document.createElement('div');
        section.className = 'asset-category';
        section.innerHTML = `<h3>${cat.label} (${items.length})</h3>`;

        const grid = document.createElement('div');
        grid.className = `asset-grid ${cat.gridClass}`;

        for (const name of items) {
            const thumb = document.createElement('div');
            thumb.className = 'asset-thumb';
            thumb.dataset.category = cat.key;
            thumb.dataset.name = name;
            thumb.innerHTML = `
                <img src="/api/avatar/assets/${escHtml(cat.key)}/${escHtml(name)}" loading="lazy" alt="${escHtml(name)}">
                <span class="asset-name">${escHtml(name)}</span>
            `;
            thumb.addEventListener('click', () => selectAsset(cat.key, name));
            grid.appendChild(thumb);
        }

        section.appendChild(grid);
        container.appendChild(section);
    }
}

function selectAsset(category, name) {
    // Info-Anzeige: welcher Asset ausgewählt wurde
    const thumbs = document.querySelectorAll(`.asset-thumb[data-category="${category}"]`);
    thumbs.forEach(t => t.classList.toggle('active', t.dataset.name === name));
}

// ===== Emotion Editor =====
function buildEmotionEditor() {
    const container = document.getElementById('emotion-editor');
    container.innerHTML = '';

    const emotionData = config.emotions || {};

    for (const emo of emotions) {
        const layers = emotionData[emo] || {};
        const section = document.createElement('div');
        section.className = 'emotion-section';

        const isOpen = emo === selectedEmotion;
        section.innerHTML = `
            <div class="emotion-header">
                <span class="emotion-name">${escHtml(emo)}</span>
                <span class="emotion-toggle">${isOpen ? '▼' : '▶'}</span>
            </div>
            <div class="emotion-fields ${isOpen ? 'open' : ''}" id="fields-${escHtml(emo)}">
                <div class="field-row">
                    <label>Body</label>
                    <select data-emotion="${escHtml(emo)}" data-field="body">
                        ${optionsFor('body', layers.body)}
                    </select>
                </div>
                <div class="field-row">
                    <label>Eye L</label>
                    <select data-emotion="${escHtml(emo)}" data-field="eye_left">
                        ${optionsFor('eye', layers.eye_left, 'eye_left_')}
                    </select>
                </div>
                <div class="field-row">
                    <label>Eye R</label>
                    <select data-emotion="${escHtml(emo)}" data-field="eye_right">
                        ${optionsFor('eye', layers.eye_right, 'eye_right_')}
                    </select>
                </div>
                <div class="field-row">
                    <label>Mouth</label>
                    <select data-emotion="${escHtml(emo)}" data-field="mouth">
                        ${optionsFor('mouth', layers.mouth)}
                    </select>
                </div>
                <div class="field-row">
                    <label>Effect</label>
                    <select data-emotion="${escHtml(emo)}" data-field="effect">
                        <option value="">(none)</option>
                        ${optionsFor('effect', layers.effect || '')}
                    </select>
                </div>
                <div class="field-row">
                    <label>Blink</label>
                    <input type="checkbox" data-emotion="${escHtml(emo)}" data-field="can_blink"
                           ${layers.can_blink !== false ? 'checked' : ''}>
                </div>
            </div>
        `;
        container.appendChild(section);
    }

    // Attach change handlers for live preview
    container.querySelectorAll('select, input[type="checkbox"]').forEach(el => {
        el.addEventListener('change', () => {
            updateConfigFromEditor();
            renderPreview();
        });
    });

    // Phase 63: Emotion-Header-Click (ersetzt onclick="toggleEmotion(this)")
    container.querySelectorAll('.emotion-header').forEach(header => {
        header.addEventListener('click', () => toggleEmotion(header));
    });
}

function optionsFor(category, selected, filterPrefix) {
    const items = assets[category] || [];
    const filtered = filterPrefix
        ? items.filter(n => n.startsWith(filterPrefix))
        : items;
    return filtered.map(n =>
        `<option value="${n}" ${n === selected ? 'selected' : ''}>${n}</option>`
    ).join('');
}

function toggleEmotion(header) {
    const fields = header.nextElementSibling;
    const toggle = header.querySelector('.emotion-toggle');
    const isOpen = fields.classList.toggle('open');
    toggle.textContent = isOpen ? '▼' : '▶';

    if (isOpen) {
        const emo = header.querySelector('.emotion-name').textContent;
        selectedEmotion = emo;
        document.getElementById('preview-emotion').value = emo;
        renderPreview();
    }
}

// ===== Preview =====
function buildPreviewDropdown() {
    const select = document.getElementById('preview-emotion');
    select.innerHTML = emotions.map(e =>
        `<option value="${escHtml(e)}" ${e === selectedEmotion ? 'selected' : ''}>${escHtml(e)}</option>`
    ).join('');
    select.addEventListener('change', () => {
        selectedEmotion = select.value;
        renderPreview();
    });
}

async function preloadImages() {
    const promises = [];
    for (const [category, items] of Object.entries(assets)) {
        for (const name of items) {
            const key = `${category}/${name}`;
            if (!imageCache[key]) {
                const p = new Promise((resolve) => {
                    const img = new Image();
                    img.onload = () => { imageCache[key] = img; resolve(); };
                    img.onerror = () => resolve();
                    img.src = `/api/avatar/assets/${category}/${name}`;
                });
                promises.push(p);
            }
        }
    }
    await Promise.all(promises);
}

function renderPreview() {
    const canvas = document.getElementById('avatar-canvas');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const emoConfig = config.emotions[selectedEmotion];
    if (!emoConfig) return;

    // Draw layers: body → eye_left → eye_right → mouth → effect
    const layers = [
        { category: 'body', name: emoConfig.body },
        { category: 'eye', name: emoConfig.eye_left },
        { category: 'eye', name: emoConfig.eye_right },
    ];

    // Mouth: if speaking, pick random lip-sync mouth
    if (isSpeaking) {
        const lipMouth = getRandomLipSyncMouth();
        layers.push({ category: 'mouth', name: lipMouth });
    } else {
        layers.push({ category: 'mouth', name: emoConfig.mouth });
    }

    // Effect layer (optional)
    if (emoConfig.effect) {
        layers.push({ category: 'effect', name: emoConfig.effect });
    }

    for (const layer of layers) {
        const img = imageCache[`${layer.category}/${layer.name}`];
        if (!img) continue;

        // Center the image
        const scale = Math.min(canvas.width / img.naturalWidth, canvas.height / img.naturalHeight);
        const w = img.naturalWidth * scale;
        const h = img.naturalHeight * scale;
        const x = (canvas.width - w) / 2;
        const y = (canvas.height - h) / 2;
        ctx.drawImage(img, x, y, w, h);
    }
}

function getRandomLipSyncMouth() {
    const frames = config.lip_sync?.frames || {};
    const keys = Object.keys(frames);
    const weights = Object.values(frames);
    if (keys.length === 0) return 'mouth_neutral_close';

    const total = weights.reduce((a, b) => a + b, 0);
    let r = Math.random() * total;
    for (let i = 0; i < keys.length; i++) {
        r -= weights[i];
        if (r <= 0) return keys[i];
    }
    return keys[keys.length - 1];
}

function toggleBlink() {
    const emoConfig = config.emotions[selectedEmotion];
    if (!emoConfig) return;

    // Temporarily swap eyes to closed
    const canvas = document.getElementById('avatar-canvas');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    drawCentered(ctx, canvas, 'body', emoConfig.body);
    drawCentered(ctx, canvas, 'eye', 'eye_left_close');
    drawCentered(ctx, canvas, 'eye', 'eye_right_close');
    drawCentered(ctx, canvas, 'mouth', emoConfig.mouth);
    if (emoConfig.effect) drawCentered(ctx, canvas, 'effect', emoConfig.effect);

    setTimeout(() => renderPreview(), 150);
}

function toggleSpeaking() {
    isSpeaking = !isSpeaking;
    if (isSpeaking) {
        const interval = (config.lip_sync?.interval || 0.18) * 1000;
        lipSyncTimer = setInterval(() => renderPreview(), interval);
    } else {
        clearInterval(lipSyncTimer);
        lipSyncTimer = null;
        renderPreview();
    }
}

function drawCentered(ctx, canvas, category, name) {
    const img = imageCache[`${category}/${name}`];
    if (!img) return;
    const scale = Math.min(canvas.width / img.naturalWidth, canvas.height / img.naturalHeight);
    const w = img.naturalWidth * scale;
    const h = img.naturalHeight * scale;
    const x = (canvas.width - w) / 2;
    const y = (canvas.height - h) / 2;
    ctx.drawImage(img, x, y, w, h);
}

// ===== Config sync =====
function updateConfigFromEditor() {
    const container = document.getElementById('emotion-editor');

    for (const emo of emotions) {
        if (!config.emotions[emo]) config.emotions[emo] = {};
        const layers = config.emotions[emo];

        for (const field of ['body', 'eye_left', 'eye_right', 'mouth', 'effect']) {
            const sel = container.querySelector(`select[data-emotion="${emo}"][data-field="${field}"]`);
            if (sel) {
                if (field === 'effect') {
                    if (sel.value) {
                        layers.effect = sel.value;
                    } else {
                        delete layers.effect;
                    }
                } else {
                    layers[field] = sel.value;
                }
            }
        }

        const cb = container.querySelector(`input[data-emotion="${emo}"][data-field="can_blink"]`);
        if (cb) layers.can_blink = cb.checked;
    }
}

function fillParams() {
    const ls = config.lip_sync || {};
    document.getElementById('param-lip-interval').value = ls.interval || 0.18;
    document.getElementById('param-lip-jitter').value = ls.jitter || 0.03;

    const br = config.breathing || {};
    document.getElementById('param-breath-enabled').checked = br.enabled !== false;
    document.getElementById('param-breath-speed').value = br.speed || 1.2;
    document.getElementById('param-breath-amplitude').value = br.amplitude || 2.0;
}

function collectParams() {
    config.lip_sync = config.lip_sync || {};
    config.lip_sync.interval = parseFloat(document.getElementById('param-lip-interval').value);
    config.lip_sync.jitter = parseFloat(document.getElementById('param-lip-jitter').value);

    config.breathing = config.breathing || {};
    config.breathing.enabled = document.getElementById('param-breath-enabled').checked;
    config.breathing.speed = parseFloat(document.getElementById('param-breath-speed').value);
    config.breathing.amplitude = parseFloat(document.getElementById('param-breath-amplitude').value);
}

// ===== Save & Reload =====
async function saveConfig() {
    updateConfigFromEditor();
    collectParams();

    const statusEl = document.getElementById('status-msg');
    try {
        const resp = await fetch('/api/avatar/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config: config }),
        });
        const data = await resp.json();
        if (resp.ok) {
            statusEl.className = 'status-msg success';
            statusEl.textContent = 'Config gespeichert!';
        } else {
            statusEl.className = 'status-msg error';
            statusEl.textContent = data.error || 'Fehler beim Speichern';
        }
    } catch (err) {
        statusEl.className = 'status-msg error';
        statusEl.textContent = 'Netzwerkfehler: ' + err.message;
    }
    setTimeout(() => { statusEl.className = 'status-msg'; }, 4000);
}

async function reloadRenderer() {
    const statusEl = document.getElementById('status-msg');
    try {
        const resp = await fetch('/api/avatar/reload', { method: 'POST' });
        const data = await resp.json();
        if (resp.ok) {
            statusEl.className = 'status-msg success';
            statusEl.textContent = 'Renderer Config neu geladen!';
        } else {
            statusEl.className = 'status-msg error';
            statusEl.textContent = data.error || 'Reload fehlgeschlagen';
        }
    } catch (err) {
        statusEl.className = 'status-msg error';
        statusEl.textContent = 'Netzwerkfehler: ' + err.message;
    }
    setTimeout(() => { statusEl.className = 'status-msg'; }, 4000);
}

// ===== Preview-Controls + Save/Reload Buttons (ersetzt onclick-Handler) =====
document.getElementById('btn-blink').addEventListener('click', toggleBlink);
document.getElementById('btn-speaking').addEventListener('click', toggleSpeaking);
document.getElementById('btn-save').addEventListener('click', saveConfig);
document.getElementById('btn-reload').addEventListener('click', reloadRenderer);

// ===== Start =====
init();
