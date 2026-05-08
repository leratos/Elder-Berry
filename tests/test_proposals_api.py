"""Tests: /api/proposals -- Dashboard-API fuer Plugin-Vorschlaege (Phase 78 Etappe 3)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from elder_berry.core.audio_router import AudioRouter

try:
    from fastapi.testclient import TestClient

    from elder_berry.tools.proposal_store import ProposalStore
    from elder_berry.web.settings_dashboard import SettingsDashboard

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

# bleach + markdown-it-py liegen in der optionalen [web]-Gruppe und
# werden vom MarkdownRenderer (importiert von proposals_api) gebraucht.
# Ohne die Deps importiert das Dashboard-Modul nicht, aber proposals_api
# wird in settings_dashboard nur lazy geladen -- der Test braucht beide
# Layer trotzdem erreichbar.
HAS_MARKDOWN_DEPS = True
try:
    import bleach  # noqa: F401
    import markdown_it  # noqa: F401
except ImportError:
    HAS_MARKDOWN_DEPS = False

pytestmark = [
    pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert"),
    pytest.mark.skipif(
        not HAS_MARKDOWN_DEPS,
        reason="bleach/markdown-it-py nicht installiert (siehe [web]-Gruppe)",
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ProposalStore]:
    s = ProposalStore(db_path=tmp_path / "proposals.db")
    yield s
    s.close()


@pytest.fixture
def client(store: ProposalStore) -> TestClient:
    """TestClient mit aktivem ProposalStore und ohne Auth-Layer.

    Auth-Tests setzen require_dashboard_login=True separat.
    """
    dashboard = SettingsDashboard(
        audio_router=AudioRouter(local_available=False),
        proposal_store=store,
    )
    return TestClient(dashboard.app)


def _seed(store: ProposalStore, intent: str = "spotify_play_song") -> None:
    store.create_pending(
        intent=intent,
        title="Spotify-Steuerung",
        description_md=(
            "Spielt Tracks ueber die Spotify Web API.\n\n"
            "## Erste Beispielanfrage\n\n"
            '- "spiel was von Hans Zimmer"\n'
        ),
        sample_message="spiel was von Hans Zimmer",
        sender_hash="hash_alice",
        confidence=0.85,
        suggested_category="medien",
        suggested_priority=50,
    )


# ---------------------------------------------------------------------------
# GET /api/proposals
# ---------------------------------------------------------------------------


class TestListProposals:
    def test_empty(self, client: TestClient) -> None:
        r = client.get("/api/proposals")
        assert r.status_code == 200
        assert r.json() == {"proposals": []}

    def test_lists_all(self, client: TestClient, store: ProposalStore) -> None:
        _seed(store, "a")
        _seed(store, "b")
        r = client.get("/api/proposals")
        assert r.status_code == 200
        ids = {p["id"] for p in r.json()["proposals"]}
        assert ids == {"a", "b"}

    def test_filter_by_status(self, client: TestClient, store: ProposalStore) -> None:
        _seed(store, "a")
        _seed(store, "b")
        store.update_status("b", "abgelehnt", "lera", rejected_reason="nope")
        r = client.get("/api/proposals?status=abgelehnt")
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()["proposals"]]
        assert ids == ["b"]

    def test_invalid_status_returns_422(self, client: TestClient) -> None:
        r = client.get("/api/proposals?status=kaputt")
        assert r.status_code == 422
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# GET /api/proposals/{id}
# ---------------------------------------------------------------------------


class TestGetProposalDetail:
    def test_unknown_returns_404(self, client: TestClient) -> None:
        r = client.get("/api/proposals/doesnotexist")
        assert r.status_code == 404
        assert "not found" in r.json()["error"].lower()

    def test_detail_contains_proposal_and_html(
        self, client: TestClient, store: ProposalStore
    ) -> None:
        _seed(store)
        r = client.get("/api/proposals/spotify_play_song")
        assert r.status_code == 200
        body = r.json()
        # Proposal serialisiert
        assert body["proposal"]["id"] == "spotify_play_song"
        assert body["proposal"]["status"] == "in_pruefung"
        assert body["proposal"]["last_confidence"] == 0.85
        # HTML server-side gerendert
        assert "<h2>" in body["description_html"]
        assert "Spotify Web API" in body["description_html"]
        # Trigger-History (1 aus create_pending)
        assert len(body["triggers"]) == 1
        assert body["triggers"][0]["sample_message"] == "spiel was von Hans Zimmer"
        # Status-History (1 Anlage-Eintrag)
        assert len(body["history"]) == 1
        assert body["history"][0]["new_status"] == "in_pruefung"
        assert body["history"][0]["changed_by"] == "saleria"

    def test_html_is_sanitized(
        self, client: TestClient, store: ProposalStore, tmp_path: Path
    ) -> None:
        # Saleria-MD mit XSS-Versuch direkt in DB schreiben
        store.create_pending(
            intent="evil",
            title="Evil",
            description_md="ok <script>alert(1)</script> done",
            sample_message="x",
            sender_hash="h",
            confidence=0.9,
        )
        r = client.get("/api/proposals/evil")
        assert r.status_code == 200
        html = r.json()["description_html"]
        # Aktiver Script-Tag muss raus sein
        assert "<script>" not in html
        assert "</script>" not in html


# ---------------------------------------------------------------------------
# POST /api/proposals/{id}/status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_to_in_bearbeitung(self, client: TestClient, store: ProposalStore) -> None:
        _seed(store)
        r = client.post(
            "/api/proposals/spotify_play_song/status",
            json={"new_status": "in_bearbeitung", "note": "bin dran"},
        )
        assert r.status_code == 200
        assert r.json()["proposal"]["status"] == "in_bearbeitung"
        # History dazugekommen
        history = store.get_history("spotify_play_song")
        assert len(history) == 2
        assert history[1].old_status == "in_pruefung"
        assert history[1].new_status == "in_bearbeitung"
        assert history[1].changed_by == "lera"
        assert history[1].note == "bin dran"

    def test_reject_with_reason(self, client: TestClient, store: ProposalStore) -> None:
        _seed(store)
        r = client.post(
            "/api/proposals/spotify_play_song/status",
            json={
                "new_status": "abgelehnt",
                "note": "passt nicht",
                "rejected_reason": "nutze ich nicht",
            },
        )
        assert r.status_code == 200
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        assert proposal.status == "abgelehnt"
        assert proposal.rejected_reason == "nutze ich nicht"

    def test_missing_new_status_422(self, client: TestClient) -> None:
        r = client.post("/api/proposals/x/status", json={})
        assert r.status_code == 422

    def test_invalid_status_422(self, client: TestClient, store: ProposalStore) -> None:
        _seed(store)
        r = client.post(
            "/api/proposals/spotify_play_song/status",
            json={"new_status": "kaputt"},
        )
        assert r.status_code == 422

    def test_unknown_proposal_404(self, client: TestClient) -> None:
        r = client.post(
            "/api/proposals/nope/status",
            json={"new_status": "in_bearbeitung"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/proposals/{id}/implementation
# ---------------------------------------------------------------------------


class TestSetImplementation:
    def test_sets_path(self, client: TestClient, store: ProposalStore) -> None:
        _seed(store)
        r = client.post(
            "/api/proposals/spotify_play_song/implementation",
            json={"path": "src/elder_berry/comms/commands/spotify_commands.py"},
        )
        assert r.status_code == 200
        assert (
            r.json()["proposal"]["implemented_in"]
            == "src/elder_berry/comms/commands/spotify_commands.py"
        )

    def test_missing_path_422(self, client: TestClient) -> None:
        r = client.post("/api/proposals/x/implementation", json={})
        assert r.status_code == 422

    def test_empty_path_422(self, client: TestClient) -> None:
        r = client.post("/api/proposals/x/implementation", json={"path": "   "})
        assert r.status_code == 422

    def test_unknown_proposal_404(self, client: TestClient) -> None:
        r = client.post("/api/proposals/nope/implementation", json={"path": "x.py"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Routen werden NICHT registriert ohne ProposalStore
# ---------------------------------------------------------------------------


class TestRoutesUnregisteredWithoutStore:
    def test_no_store_no_route(self) -> None:
        dashboard = SettingsDashboard(
            audio_router=AudioRouter(local_available=False),
            proposal_store=None,
        )
        client = TestClient(dashboard.app)
        r = client.get("/api/proposals")
        # FastAPI-Default: 404 auf nicht-registrierte Routen
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Auth-Layer (Phase 58): /api/proposals MUSS hinter Login liegen
# ---------------------------------------------------------------------------


class TestAuthLayer:
    def test_requires_login_when_enabled(
        self, store: ProposalStore, tmp_path: Path
    ) -> None:
        """Wenn require_dashboard_login=True, muss /api/proposals 401
        ohne Cookie liefern (DashboardAuthMiddleware-PROTECTED_PREFIXES).
        """
        import bcrypt

        from elder_berry.core.secret_store import SecretStore
        from elder_berry.web.dashboard_auth import (
            PASSWORD_HASH_KEY,
            SESSION_SECRET_KEY,
        )

        # SecretStore mit gesetztem Passwort + Session-Secret -- sonst
        # ist die Auth-Middleware im "kein Passwort"-Bypass-Mode.
        secret_store = SecretStore(base_dir=tmp_path / ".secrets")
        # Test-Hash mit minimalen Rounds, damit der Test schnell laeuft.
        hashed = bcrypt.hashpw(b"test-pass", bcrypt.gensalt(rounds=4))
        secret_store.set(PASSWORD_HASH_KEY, hashed.decode("ascii"))
        secret_store.set(SESSION_SECRET_KEY, "x" * 64)

        dashboard = SettingsDashboard(
            audio_router=AudioRouter(local_available=False),
            secret_store=secret_store,
            proposal_store=store,
            require_dashboard_login=True,
        )
        client = TestClient(dashboard.app)

        r = client.get("/api/proposals")
        assert r.status_code == 401
