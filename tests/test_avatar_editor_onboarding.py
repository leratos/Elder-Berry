"""Tests: Phase 53.2 – Avatar-Editor Onboarding-Modal.

Prüft das Template statisch: HTML-Hooks, CSS-Klassen, JavaScript-Glue
und der localStorage-Key. Kein Browser-Rendering.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parents[1] / "src" / "elder_berry" / "web"
_TEMPLATE = _WEB / "templates" / "avatar_editor.html"
_CSS = _WEB / "static" / "css" / "avatar_editor.css"
_JS = _WEB / "static" / "js" / "avatar_editor.js"


@pytest.fixture(scope="module")
def html() -> str:
    """HTML-Template + externes CSS + externes JS (Phase 63: Code ausgelagert).

    Alle Assertions pruefen weiterhin die Zeichenfolgen unabhaengig davon,
    in welcher Datei sie letztendlich stehen.
    """
    return "\n".join(p.read_text(encoding="utf-8") for p in (_TEMPLATE, _CSS, _JS))


# ---------------------------------------------------------------------------
# Struktur
# ---------------------------------------------------------------------------


class TestModalStructure:
    def test_overlay_element(self, html):
        assert 'id="onboardingOverlay"' in html
        assert 'class="onboarding-overlay"' in html

    def test_dialog_a11y(self, html):
        assert 'role="dialog"' in html
        assert 'aria-modal="true"' in html
        assert 'aria-labelledby="onboardingTitle"' in html

    def test_title_and_subtitle(self, html):
        assert 'id="onboardingTitle"' in html
        assert "Willkommen im Avatar-Editor" in html

    def test_four_explainer_items(self, html):
        # Die vier Punkte: Layer & Assets, Emotionen, Lip-Sync & Breathing,
        # Speichern & Hot-Reload
        assert "Layer &amp; Assets" in html
        assert "Emotionen" in html
        assert "Lip-Sync &amp; Breathing" in html
        assert "Speichern &amp; Hot-Reload" in html


# ---------------------------------------------------------------------------
# Aktionen
# ---------------------------------------------------------------------------


class TestActions:
    def test_dismiss_button(self, html):
        assert 'id="onboardingDismiss"' in html
        assert "nicht mehr anzeigen" in html

    def test_later_button(self, html):
        assert 'id="onboardingLater"' in html
        assert "Später wieder einblenden" in html

    def test_help_button_in_topbar(self, html):
        assert 'id="onboardingShow"' in html
        # Hilfe-Button steht in der Topbar
        help_idx = html.find('id="onboardingShow"')
        topbar_idx = html.find('class="topbar"')
        assert topbar_idx > 0 and help_idx > topbar_idx

    def test_help_button_before_dashboard_link(self, html):
        help_idx = html.find('id="onboardingShow"')
        dash_idx = html.find('href="/"')
        assert 0 < help_idx < dash_idx


# ---------------------------------------------------------------------------
# JavaScript-Glue
# ---------------------------------------------------------------------------


class TestJavaScript:
    def test_localstorage_key_defined(self, html):
        assert 'ONBOARDING_KEY = "elderberry.avatar.onboarding.seen"' in html

    def test_localstorage_check_on_load(self, html):
        assert "localStorage.getItem(ONBOARDING_KEY)" in html
        # Beim Dismiss wird gesetzt
        assert "localStorage.setItem(ONBOARDING_KEY" in html

    def test_functions_defined(self, html):
        assert "function showOnboarding" in html
        assert "function hideOnboarding" in html
        assert "function initOnboarding" in html

    def test_init_registered_on_domcontentloaded(self, html):
        assert 'addEventListener("DOMContentLoaded", initOnboarding)' in html

    def test_escape_closes(self, html):
        assert 'ev.key === "Escape"' in html

    def test_click_outside_closes(self, html):
        # Backdrop-Click: ev.target === overlay
        assert "ev.target === overlay" in html


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


class TestCss:
    def test_overlay_hidden_by_default(self, html):
        assert ".onboarding-overlay {" in html
        # Default display:none, erst .active macht flex
        assert "display: none;" in html

    def test_active_class_shows(self, html):
        assert ".onboarding-overlay.active { display: flex; }" in html

    def test_card_styling_present(self, html):
        assert ".onboarding-card" in html
        assert ".onboarding-actions" in html
