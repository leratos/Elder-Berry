"""Tests: SetupTests – Verbindungstests für den Setup-Wizard."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from elder_berry.web.setup_tests import (
    EMAIL_PROVIDERS,
    InvalidExternalURLError,
    SetupTests,
    _validate_external_url,
)


def _run(coro):
    """Helper: async Coroutine synchron ausführen."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

class TestAnthropic:
    def test_valid_key(self):
        mock_resp = MagicMock()
        mock_resp.model = "claude-sonnet-4-6-20250514"
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_mod = MagicMock()
        mock_mod.Anthropic.return_value = mock_client
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            result = _run(SetupTests.test_anthropic("sk-valid-key"))
        assert result["success"] is True
        assert result["model"] == "claude-sonnet-4-6-20250514"

    def test_invalid_key(self):
        mock_mod = MagicMock()
        mock_mod.Anthropic.return_value.messages.create.side_effect = Exception(
            "Invalid API key"
        )
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            result = _run(SetupTests.test_anthropic("sk-invalid"))
        assert result["success"] is False
        # Fehlerdetails werden nur geloggt, nicht in der Response (stack-trace-exposure)
        assert "error" in result
        assert result["error"]  # irgendeine generische Meldung


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------

class TestMatrix:
    def test_login_with_room(self):
        mock_client = AsyncMock()
        mock_whoami = MagicMock()
        mock_whoami.user_id = "@saleria:example.com"
        mock_client.whoami.return_value = mock_whoami
        mock_client.join = AsyncMock()
        mock_client.close = AsyncMock()

        mock_nio = MagicMock()
        mock_nio.AsyncClient = MagicMock(return_value=mock_client)
        with patch.dict("sys.modules", {"nio": mock_nio}):
            result = _run(SetupTests.test_matrix(
                "https://matrix.example.com",
                "@saleria:example.com",
                "syt_valid_token",
                "!room:example.com",
            ))
        assert result["success"] is True
        assert result["user_id"] == "@saleria:example.com"
        assert result.get("room_joined") is True

    def test_login_without_room(self):
        mock_client = AsyncMock()
        mock_whoami = MagicMock()
        mock_whoami.user_id = "@saleria:example.com"
        mock_client.whoami.return_value = mock_whoami
        mock_client.close = AsyncMock()

        mock_nio = MagicMock()
        mock_nio.AsyncClient = MagicMock(return_value=mock_client)
        with patch.dict("sys.modules", {"nio": mock_nio}):
            result = _run(SetupTests.test_matrix(
                "https://matrix.example.com",
                "@saleria:example.com",
                "syt_valid_token",
            ))
        assert result["success"] is True
        assert "room_joined" not in result

    def test_invalid_token(self):
        mock_client = AsyncMock()
        mock_client.whoami.side_effect = Exception("Invalid token")
        mock_client.close = AsyncMock()

        mock_nio = MagicMock()
        mock_nio.AsyncClient = MagicMock(return_value=mock_client)
        with patch.dict("sys.modules", {"nio": mock_nio}):
            result = _run(SetupTests.test_matrix(
                "https://matrix.example.com",
                "@saleria:example.com",
                "syt_invalid",
            ))
        assert result["success"] is False
        # Fehlerdetails werden nur geloggt, nicht in der Response (stack-trace-exposure)
        assert "error" in result
        assert result["error"]  # irgendeine generische Meldung


# ---------------------------------------------------------------------------
# Nextcloud
# ---------------------------------------------------------------------------

class TestNextcloud:
    def test_all_ok(self):
        """Alle drei DAV-Dienste erreichbar."""
        mock_response = MagicMock()
        mock_response.status_code = 207

        with patch("elder_berry.web.setup_tests.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = _run(SetupTests.test_nextcloud(
                "https://cloud.example.com", "user", "pass"
            ))
        assert result["success"] is True
        assert result["webdav"] is True
        assert result["caldav"] is True
        assert result["carddav"] is True

    def test_partial_failure(self):
        """Nur WebDAV OK, CalDAV und CardDAV nicht."""
        call_count = 0

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 207 if call_count == 1 else 403
            return resp

        with patch("elder_berry.web.setup_tests.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.request = mock_request
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = _run(SetupTests.test_nextcloud(
                "https://cloud.example.com", "user", "pass"
            ))
        assert result["success"] is False
        assert result["webdav"] is True

    def test_unreachable(self):
        """Server nicht erreichbar."""
        with patch("elder_berry.web.setup_tests.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = _run(SetupTests.test_nextcloud(
                "https://unreachable.example.com", "user", "pass"
            ))
        assert result["success"] is False
        assert result["webdav"] is False


# ---------------------------------------------------------------------------
# E-Mail
# ---------------------------------------------------------------------------

class TestEmail:
    def test_imap_and_smtp_ok(self):
        with patch("elder_berry.web.setup_tests.imaplib.IMAP4_SSL") as mock_imap, \
             patch("elder_berry.web.setup_tests.smtplib.SMTP_SSL") as mock_smtp:
            imap_inst = MagicMock()
            imap_inst.search.return_value = ("OK", [b"1 2 3"])
            mock_imap.return_value = imap_inst

            smtp_inst = MagicMock()
            mock_smtp.return_value = smtp_inst

            result = _run(SetupTests.test_email(
                "imap.example.com", 993,
                "smtp.example.com", 465,
                "user@example.com", "pass",
            ))
        assert result["success"] is True
        assert result["imap"] is True
        assert result["smtp"] is True
        assert result["unread"] == 3

    def test_imap_failure(self):
        with patch("elder_berry.web.setup_tests.imaplib.IMAP4_SSL") as mock_imap, \
             patch("elder_berry.web.setup_tests.smtplib.SMTP_SSL") as mock_smtp:
            mock_imap.side_effect = Exception("Auth failed")
            smtp_inst = MagicMock()
            mock_smtp.return_value = smtp_inst

            result = _run(SetupTests.test_email(
                "imap.example.com", 993,
                "smtp.example.com", 465,
                "user@example.com", "wrongpass",
            ))
        assert result["success"] is False
        assert result["imap"] is False
        assert result["smtp"] is True

    def test_smtp_starttls(self):
        """SMTP mit Port 587 (STARTTLS statt SSL)."""
        with patch("elder_berry.web.setup_tests.imaplib.IMAP4_SSL") as mock_imap, \
             patch("elder_berry.web.setup_tests.smtplib.SMTP") as mock_smtp:
            imap_inst = MagicMock()
            imap_inst.search.return_value = ("OK", [b""])
            mock_imap.return_value = imap_inst

            smtp_inst = MagicMock()
            mock_smtp.return_value = smtp_inst

            result = _run(SetupTests.test_email(
                "imap.example.com", 993,
                "smtp.example.com", 587,
                "user@example.com", "pass",
            ))
        assert result["success"] is True
        assert result["unread"] == 0
        smtp_inst.starttls.assert_called_once()

    def test_provider_defaults(self):
        """Provider-Lookup liefert richtige Defaults."""
        assert "strato" in EMAIL_PROVIDERS
        imap_host, imap_port, smtp_host, smtp_port = EMAIL_PROVIDERS["strato"]
        assert imap_host == "imap.strato.de"
        assert imap_port == 993
        assert smtp_host == "smtp.strato.de"
        assert smtp_port == 465


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

class TestOllama:
    def test_available(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [{"name": "phi4:14b"}, {"name": "llama3:8b"}]
        }
        with patch("elder_berry.web.setup_tests.httpx.get", return_value=mock_resp):
            result = SetupTests.test_ollama()
        assert result["success"] is True
        assert "phi4:14b" in result["models"]
        assert len(result["models"]) == 2

    def test_not_running(self):
        with patch(
            "elder_berry.web.setup_tests.httpx.get",
            side_effect=Exception("Connection refused"),
        ):
            result = SetupTests.test_ollama()
        assert result["success"] is False
        assert result["models"] == []


# ---------------------------------------------------------------------------
# Brave Search
# ---------------------------------------------------------------------------

class TestBrave:
    def test_valid_key(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("elder_berry.web.setup_tests.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = _run(SetupTests.test_brave("valid-key"))
        assert result["success"] is True

    def test_invalid_key(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("elder_berry.web.setup_tests.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = _run(SetupTests.test_brave("invalid-key"))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

class TestPrerequisites:
    def test_python_version(self):
        result = SetupTests.check_prerequisites()
        assert "python" in result
        assert "." in result["python"]

    def test_git_available(self):
        result = SetupTests.check_prerequisites()
        assert "git" in result
        assert isinstance(result["git"], bool)

    def test_ollama_status(self):
        with patch.object(
            SetupTests,
            "test_ollama",
            return_value={"success": False, "models": []},
        ):
            result = SetupTests.check_prerequisites()
        assert result["ollama"]["available"] is False
        assert result["ollama"]["models"] == []


# ---------------------------------------------------------------------------
# URL-Validator (SSRF-Schutz)
# ---------------------------------------------------------------------------

class TestValidateExternalURL:
    @pytest.mark.parametrize("url", [
        "https://cloud.example.com",
        "http://nextcloud.local",
        "https://192.168.1.10",
        "https://nc.example.com:8443/sub/path",
        "  https://example.com  ",  # wird getrimmt
    ])
    def test_accepts_valid_http_urls(self, url):
        result = _validate_external_url(url)
        assert result == url.strip()

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "gopher://internal:70/",
        "ftp://example.com",
        "javascript:alert(1)",
        "data:text/plain,hello",
    ])
    def test_rejects_non_http_schemes(self, url):
        with pytest.raises(InvalidExternalURLError):
            _validate_external_url(url)

    def test_rejects_userinfo(self):
        with pytest.raises(InvalidExternalURLError):
            _validate_external_url("https://attacker:x@cloud.example.com")

    @pytest.mark.parametrize("url", [
        "",
        "   ",
        "https://",
        "http:///path",
        "not-a-url",
    ])
    def test_rejects_empty_or_malformed(self, url):
        with pytest.raises(InvalidExternalURLError):
            _validate_external_url(url)

    def test_rejects_non_string(self):
        with pytest.raises(InvalidExternalURLError):
            _validate_external_url(None)  # type: ignore[arg-type]

    def test_rejects_invalid_hostname(self):
        # Underscore ist im Hostname laut RFC 1035 nicht zulaessig
        with pytest.raises(InvalidExternalURLError):
            _validate_external_url("https://bad_host.example.com")


class TestNextcloudRejectsBadURL:
    """test_nextcloud darf bei boesartigen URLs gar keinen Request machen."""

    def test_file_scheme_blocked_without_request(self):
        mock_client = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_ctx.__aexit__.return_value = False
        with patch(
            "elder_berry.web.setup_tests.httpx.AsyncClient",
            return_value=mock_ctx,
        ) as mocked:
            result = asyncio.new_event_loop().run_until_complete(
                SetupTests.test_nextcloud("file:///etc/passwd", "u", "p")
            )
        assert result["success"] is False
        assert "Schema" in result.get("error", "")
        # KEIN HTTP-Request darf abgesetzt worden sein
        mocked.assert_not_called()
        mock_client.request.assert_not_called()
