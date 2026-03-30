/**
 * Module-Loader – Lädt Dashboard-Module dynamisch anhand der Konfiguration.
 */

const moduleMap = {
    harmony: () => import("./harmony.js"),
    system:  () => import("./system.js"),
    saleria: () => import("./saleria.js"),
};

async function loadModules() {
    const container = document.getElementById("module-container");
    const config = window.DASHBOARD_CONFIG;

    if (!config || !config.modules) {
        console.error("DASHBOARD_CONFIG fehlt oder hat keine modules");
        return;
    }

    for (const name of config.modules) {
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
        } catch (e) {
            console.warn(`Modul ${name} konnte nicht geladen werden:`, e);
        }
    }
}

loadModules();
