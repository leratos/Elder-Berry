"""Tests fuer OriginCheckMiddleware (Phase 64, H-1)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elder_berry.web.origin_check_middleware import OriginCheckMiddleware

# Dieses Testfile testet die Middleware direkt. Der globale
# conftest-Patch, der jedem Request einen Default-Origin hinzufuegt,
# wuerde die "ohne Origin"-Tests unbrauchbar machen -> hier deaktivieren.
pytestmark = pytest.mark.no_default_origin


def _build_app(allowed_origins: list[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(OriginCheckMiddleware, allowed_origins=allowed_origins)

    @app.get("/read")
    async def read():
        return {"ok": True}

    @app.post("/write")
    async def write():
        return {"ok": True}

    @app.put("/put")
    async def put():
        return {"ok": True}

    @app.patch("/patch")
    async def patch():
        return {"ok": True}

    @app.delete("/item/{item_id}")
    async def delete(item_id: int):
        return {"deleted": item_id}

    return app


# ---------------------------------------------------------------------------
# Safe methods passieren unabhaengig vom Origin
# ---------------------------------------------------------------------------

class TestSafeMethodsPassThrough:
    def test_get_without_any_header_ok(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        assert client.get("/read").status_code == 200

    def test_get_with_foreign_origin_ok(self):
        # GET ist nicht state-changing --> Origin ignoriert.
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.get("/read", headers={"origin": "http://evil.com"})
        assert r.status_code == 200

    def test_options_preflight_not_blocked(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        # OPTIONS ohne Origin -- kein 403 erwartet.
        r = client.options("/write")
        # FastAPI liefert 405 Method Not Allowed (kein OPTIONS-Handler),
        # NICHT 403 -- die Middleware laesst OPTIONS durch.
        assert r.status_code != 403


# ---------------------------------------------------------------------------
# State-changing Methoden: Origin muss matchen
# ---------------------------------------------------------------------------

class TestOriginHeaderEnforcement:
    def test_post_with_matching_origin_passes(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.post(
            "/write",
            headers={"origin": "http://localhost:8090"},
        )
        assert r.status_code == 200

    def test_post_with_foreign_origin_blocked(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.post("/write", headers={"origin": "http://evil.com"})
        assert r.status_code == 403
        body = r.json()
        assert body["code"] == "origin_forbidden"

    def test_post_without_origin_or_referer_blocked(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        # Starlette TestClient setzt per default einen Host-Header, aber
        # keinen Origin/Referer. Ohne diese --> 403.
        r = client.post("/write")
        assert r.status_code == 403

    def test_put_foreign_origin_blocked(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.put("/put", headers={"origin": "http://attacker.site"})
        assert r.status_code == 403

    def test_patch_foreign_origin_blocked(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.patch("/patch", headers={"origin": "http://attacker.site"})
        assert r.status_code == 403

    def test_delete_foreign_origin_blocked(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.delete(
            "/item/42",
            headers={"origin": "http://attacker.site"},
        )
        assert r.status_code == 403

    def test_port_mismatch_blocked(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.post(
            "/write",
            headers={"origin": "http://localhost:9999"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Referer-Fallback (wenn Origin fehlt, aber Referer da ist)
# ---------------------------------------------------------------------------

class TestRefererFallback:
    def test_referer_matching_allowed(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.post(
            "/write",
            headers={"referer": "http://localhost:8090/settings"},
        )
        assert r.status_code == 200

    def test_referer_with_path_is_normalized(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.post(
            "/write",
            headers={"referer": "http://localhost:8090/any/deep/path?x=1"},
        )
        assert r.status_code == 200

    def test_referer_foreign_blocked(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.post(
            "/write",
            headers={"referer": "http://evil.com/attack"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Multi-Origin-Support
# ---------------------------------------------------------------------------

class TestMultipleOrigins:
    def test_each_allowed_origin_passes(self):
        allowed = [
            "http://localhost:8090",
            "http://127.0.0.1:8090",
            "https://dashboard.example.com",
        ]
        client = TestClient(_build_app(allowed))
        for origin in allowed:
            r = client.post("/write", headers={"origin": origin})
            assert r.status_code == 200, f"Origin {origin} sollte akzeptiert werden"

    def test_non_listed_origin_blocked_even_with_similar_allowed(self):
        allowed = ["https://dashboard.example.com"]
        client = TestClient(_build_app(allowed))
        r = client.post(
            "/write",
            headers={"origin": "https://dashboard.example.com.evil.com"},
        )
        assert r.status_code == 403

    def test_empty_allowed_origins_blocks_everything_state_changing(self):
        client = TestClient(_build_app([]))
        r = client.post(
            "/write",
            headers={"origin": "http://localhost:8090"},
        )
        assert r.status_code == 403

    def test_empty_strings_in_allowed_are_ignored(self):
        # Defensive: Leere Strings in der Liste duerfen nicht als
        # "matches no-origin" missgedeutet werden.
        client = TestClient(_build_app(["", "http://localhost:8090"]))
        r = client.post("/write")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Scheme-Case-Insensitivity (urlparse lowercased Scheme)
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_scheme_uppercase_matches_lowercase_allowed(self):
        client = TestClient(_build_app(["http://localhost:8090"]))
        r = client.post(
            "/write",
            headers={"origin": "HTTP://localhost:8090"},
        )
        # urlparse("HTTP://...") liefert scheme="http" -- also Match.
        assert r.status_code == 200

    def test_trailing_slash_in_allowed_ignored(self):
        client = TestClient(_build_app(["http://localhost:8090/"]))
        r = client.post(
            "/write",
            headers={"origin": "http://localhost:8090"},
        )
        assert r.status_code == 200
