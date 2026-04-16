/**
 * Module-Loader – Lädt Dashboard-Module nach Views gruppiert.
 *
 * Views werden per Tab umgeschaltet. Nur die Module der aktiven View
 * sind sichtbar, die anderen werden ausgeblendet (nicht entladen).
 *
 * Phase 58: Login-Gating für die Views "settings" und "avatar".
 * Vor dem Wechsel auf eine geschützte View wird der Login-Status
 * geprüft. Ist der Nutzer nicht eingeloggt, wird das Login-Modal
 * gezeigt – nach erfolgreichem Login wechselt die View.
 */

import authInstance from "./auth.js";

const moduleMap = {
    harmony:  () => import("./harmony.js"),
    system:   () => import("./system.js"),
    settings: () => import("./settings.js"),
    avatar:   () => import("./avatar.js"),
};

const loadedModules = {};   // name → { mod, section }
let activeView = null;

async function loadModules() {
    const container = document.getElementById("module-container");
    const config = window.DASHBOARD_CONFIG;

    if (!config || !config.views) {
        console.error("DASHBOARD_CONFIG fehlt oder hat keine views");
        return;
    }

    // Auth-Helper initialisieren BEVOR Module geladen werden
    await authInstance.init();

    // Alle Module aus allen Views laden (einmalig)
    const allModules = [...new Set(Object.values(config.views).flat())];
    for (const name of allModules) {
        const loader = moduleMap[name];
        if (!loader) {
            console.warn(`Unbekanntes Modul: ${name}`);
            continue;
        }

        try {
            const { default: ModuleClass } = await loader();
            const mod = new ModuleClass(config);

            const section = document.createElement("section");
            section.className = "module";
            section.id = `module-${name}`;
            section.innerHTML = mod.render();
            container.appendChild(section);

            mod.container = section;
            await mod.init();

            if (mod.pollInterval > 0) {
                setInterval(() => mod.poll(), mod.pollInterval);
            }

            loadedModules[name] = { mod, section };
        } catch (e) {
            console.warn(`Modul ${name} konnte nicht geladen werden:`, e);
        }
    }

    // Default-View aktivieren (Fernbedienung – kein Login nötig)
    switchView(config.defaultView || Object.keys(config.views)[0]);
    initNav();
}

async function switchView(viewName) {
    // Phase 58: Login-Gate
    const ok = await authInstance.ensureAuthForView(viewName);
    if (!ok) {
        // Nutzer hat Login abgebrochen → bleibe auf der Default-View
        const def = window.DASHBOARD_CONFIG.defaultView || "remote";
        if (viewName !== def) {
            return switchView(def);
        }
    }

    const config = window.DASHBOARD_CONFIG;
    const viewModules = config.views[viewName] || [];

    // Alle Module ausblenden
    for (const [name, { section }] of Object.entries(loadedModules)) {
        section.style.display = viewModules.includes(name) ? "" : "none";
    }

    activeView = viewName;
    document.body.dataset.view = viewName;

    // Nav-Tabs aktualisieren
    document.querySelectorAll("#header-nav .nav-tab").forEach(tab => {
        tab.classList.toggle("active", tab.dataset.view === viewName);
    });
}

function initNav() {
    document.querySelectorAll("#header-nav .nav-tab").forEach(tab => {
        tab.addEventListener("click", () => switchView(tab.dataset.view));
    });
}

// Globale Hook für auth.js (z.B. beim Logout zur Default-View springen)
window.__dashboardSwitchView = switchView;

loadModules();
