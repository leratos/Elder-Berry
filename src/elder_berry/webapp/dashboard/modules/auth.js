/**
 * DashboardAuth – Login/Logout-Helper für das Dashboard (Phase 58).
 *
 * Nicht als DashboardModule – läuft global im Header, nicht in einer
 * View-Sektion. Stellt bereit:
 *
 *   - checkStatus()   → fragt /api/dashboard/auth/status ab,
 *                       schaltet Login-Tabs frei wenn eingeloggt
 *   - showLogin()     → zeigt Login-Modal
 *   - hideLogin()     → versteckt Login-Modal
 *   - logout()        → ruft /api/dashboard/logout
 *   - on401Handler()  → wird global als window.__dashboardOn401 gesetzt
 */

const AUTH_TABS = ["settings", "proposals", "avatar"];

export class DashboardAuth {
    constructor() {
        this.authenticated = false;
        this.passwordSet = false;
        this.modal = null;
        this.form = null;
        this.errorEl = null;
        this.pwInput = null;
        this.logoutBtn = null;
        this._pendingResolve = null;
    }

    async init() {
        this.modal = document.getElementById("login-modal");
        this.form = document.getElementById("login-form");
        this.errorEl = document.getElementById("login-error");
        this.pwInput = document.getElementById("login-password");
        this.logoutBtn = document.getElementById("logout-btn");
        this.loginBtn = document.getElementById("login-btn");

        if (!this.modal || !this.form) {
            console.warn("Login-Modal nicht im DOM – Auth deaktiviert");
            return;
        }

        this.form.addEventListener("submit", (e) => {
            e.preventDefault();
            this._submit();
        });
        if (this.logoutBtn) {
            this.logoutBtn.addEventListener("click", () => this.logout());
        }
        if (this.loginBtn) {
            this.loginBtn.addEventListener("click", () => this.showLogin());
        }
        // Klick auf Backdrop schließt das Modal
        this.modal.addEventListener("click", (e) => {
            if (e.target === this.modal) {
                this._cancelPending();
                this.hideLogin();
            }
        });

        // 401-Handler global registrieren
        window.__dashboardOn401 = async () => this._on401();

        await this.checkStatus();
        this._updateUI();
    }

    _cancelPending() {
        if (this._pendingResolve) {
            const r = this._pendingResolve;
            this._pendingResolve = null;
            r(false);
        }
    }

    async checkStatus() {
        try {
            const res = await fetch("/api/dashboard/auth/status",
                                    {credentials: "include"});
            if (!res.ok) return;
            const data = await res.json();
            this.authenticated = !!data.authenticated;
            this.passwordSet = !!data.password_set;
        } catch (e) {
            console.warn("auth/status nicht erreichbar:", e);
        }
    }

    /**
     * Wird vor View-Wechsel gerufen. Wenn ein geschützter Tab
     * aktiviert wird und kein Login besteht: Modal zeigen + false.
     */
    async ensureAuthForView(viewName) {
        if (!AUTH_TABS.includes(viewName)) return true;
        if (this.authenticated) return true;
        return await this._on401();
    }

    showLogin() {
        if (!this.modal) return;
        this.modal.classList.add("visible");
        if (this.errorEl) this.errorEl.textContent = "";
        setTimeout(() => this.pwInput && this.pwInput.focus(), 50);
        if (!this.passwordSet) {
            if (this.errorEl) {
                this.errorEl.textContent =
                    "Kein Dashboard-Passwort gesetzt – siehe Setup-Wizard.";
            }
        }
    }

    hideLogin() {
        if (!this.modal) return;
        this.modal.classList.remove("visible");
        if (this.pwInput) this.pwInput.value = "";
    }

    async logout() {
        try {
            await fetch("/api/dashboard/logout", {
                method: "POST",
                credentials: "include",
            });
        } catch (e) {
            console.warn("Logout-Fehler:", e);
        }
        this.authenticated = false;
        this._updateUI();
        // Default-View laden
        const def = window.DASHBOARD_CONFIG?.defaultView || "remote";
        if (window.__dashboardSwitchView) {
            window.__dashboardSwitchView(def);
        }
    }

    async _submit() {
        if (this.errorEl) this.errorEl.textContent = "";
        const pw = this.pwInput?.value || "";
        if (!pw) {
            if (this.errorEl) this.errorEl.textContent = "Passwort fehlt.";
            return;
        }
        try {
            const res = await fetch("/api/dashboard/login", {
                method: "POST",
                credentials: "include",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({password: pw}),
            });
            if (res.ok) {
                this.authenticated = true;
                this.hideLogin();
                this._updateUI();
                if (this._pendingResolve) {
                    const r = this._pendingResolve;
                    this._pendingResolve = null;
                    r(true);
                }
                return;
            }
            const data = await res.json().catch(() => ({}));
            if (this.errorEl) {
                this.errorEl.textContent =
                    data.error || `Fehler ${res.status}`;
            }
        } catch (e) {
            if (this.errorEl) this.errorEl.textContent = e.message;
        }
    }

    async _on401() {
        await this.checkStatus();
        if (this.authenticated) return true;
        return new Promise((resolve) => {
            this._pendingResolve = resolve;
            this.showLogin();
            // Wenn Modal geschlossen wird ohne Login: false zurückgeben
            const closeOnEsc = (e) => {
                if (e.key === "Escape") {
                    document.removeEventListener("keydown", closeOnEsc);
                    if (this._pendingResolve) {
                        this._pendingResolve = null;
                        this.hideLogin();
                        resolve(false);
                    }
                }
            };
            this._escListener = closeOnEsc;
            document.addEventListener("keydown", closeOnEsc);
        });
    }

    _updateUI() {
        // Login-Button: nur sichtbar wenn NICHT eingeloggt
        // Logout-Button + Avatar/Settings-Tabs: nur sichtbar wenn eingeloggt
        if (this.loginBtn) {
            this.loginBtn.style.display = this.authenticated ? "none" : "";
        }
        if (this.logoutBtn) {
            this.logoutBtn.style.display = this.authenticated ? "" : "none";
        }
        document.querySelectorAll("#header-nav .nav-tab").forEach(tab => {
            const view = tab.dataset.view;
            if (AUTH_TABS.includes(view)) {
                tab.style.display = this.authenticated ? "" : "none";
            }
        });
    }
}

const authInstance = new DashboardAuth();
window.__dashboardAuth = authInstance;
export default authInstance;
