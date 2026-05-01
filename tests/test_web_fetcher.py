"""Tests: WebFetcher + WEB_SUMMARY_PATTERN + _cmd_web_summary."""

from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.advanced_commands import (
    DOCUMENT_SUMMARY_PATTERN,
    WEB_SUMMARY_PATTERN,
    AdvancedCommandHandler,
)
from elder_berry.core.url_validator import UnsafeUrlError
from elder_berry.tools.web_fetcher import WebContent, WebFetcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_dns_to_public(monkeypatch):
    """Mockt socket.getaddrinfo so, dass Hostnames in Tests auf eine
    oeffentliche IP (93.184.216.34 == example.com) aufgeloest werden.

    Phase 64: WebFetcher.fetch() ruft jetzt ensure_public_url(), das
    echte DNS-Resolution nutzt. Ohne Mock waeren alle Tests von DNS
    abhaengig (langsam, offline-CI-feindlich). Tests, die explizit
    private IPs testen wollen, ueberschreiben diesen Mock lokal.
    """

    def resolver(host, *args, **kwargs):
        return [(None, None, None, None, ("93.184.216.34", 0))]

    monkeypatch.setattr(
        "elder_berry.core.url_validator.socket.getaddrinfo",
        resolver,
    )


@pytest.fixture
def fetcher():
    """Standard-WebFetcher."""
    return WebFetcher(max_chars=8000)


@pytest.fixture
def small_fetcher():
    """WebFetcher mit niedrigem max_chars fuer Truncation-Tests."""
    return WebFetcher(max_chars=50)


@pytest.fixture
def mock_fetcher():
    """Mock-WebFetcher fuer Handler-Tests."""
    return MagicMock(spec=WebFetcher)


@pytest.fixture
def handler(mock_fetcher):
    """AdvancedCommandHandler mit gemocktem WebFetcher."""
    return AdvancedCommandHandler(web_fetcher=mock_fetcher)


# ---------------------------------------------------------------------------
# Pattern-Tests (kein HTTP)
# ---------------------------------------------------------------------------


class TestWebSummaryPattern:
    def test_pattern_simple_url(self):
        m = WEB_SUMMARY_PATTERN.match("https://example.com")
        assert m is not None
        assert m.group(1) == "https://example.com"

    def test_pattern_url_with_zusammen_suffix(self):
        m = WEB_SUMMARY_PATTERN.match("fasse https://example.com/page zusammen")
        assert m is not None
        assert m.group(1) == "https://example.com/page"

    def test_pattern_fasse_mal(self):
        m = WEB_SUMMARY_PATTERN.match("fasse mal https://example.com zusammen")
        assert m is not None
        assert m.group(1) == "https://example.com"

    def test_pattern_zusammenfassung_von_url(self):
        m = WEB_SUMMARY_PATTERN.match("zusammenfassung von https://example.com")
        assert m is not None
        assert m.group(2) == "https://example.com"

    def test_pattern_seite_url(self):
        m = WEB_SUMMARY_PATTERN.match("fasse die seite https://example.com zusammen")
        assert m is not None
        assert m.group(3) == "https://example.com"

    def test_pattern_seite_url_without_fasse(self):
        m = WEB_SUMMARY_PATTERN.match("seite https://example.com zusammen")
        assert m is not None
        assert m.group(3) == "https://example.com"

    def test_pattern_no_match_local_path(self):
        m = WEB_SUMMARY_PATTERN.match("fasse C:\\Docs\\report.pdf zusammen")
        assert m is None

    def test_pattern_no_match_bare_text(self):
        m = WEB_SUMMARY_PATTERN.match("fasse den Bericht zusammen")
        assert m is None

    def test_no_collision_with_document_summary_pattern(self):
        """WEB_SUMMARY_PATTERN matcht URLs, DOCUMENT_SUMMARY_PATTERN matcht Pfade."""
        url_text = "fasse https://example.com zusammen"
        path_text = "fasse C:\\Docs\\report.pdf zusammen"

        assert WEB_SUMMARY_PATTERN.search(url_text) is not None
        assert DOCUMENT_SUMMARY_PATTERN.search(url_text) is None

        assert WEB_SUMMARY_PATTERN.search(path_text) is None
        assert DOCUMENT_SUMMARY_PATTERN.search(path_text) is not None


# ---------------------------------------------------------------------------
# WebContent DTO
# ---------------------------------------------------------------------------


class TestWebContent:
    def test_frozen(self):
        wc = WebContent(url="https://x.com", title="X", text="hello", truncated=False)
        with pytest.raises(AttributeError):
            wc.text = "changed"

    def test_source_default(self):
        wc = WebContent(url="https://x.com", title="X", text="hello", truncated=False)
        assert wc.source == "web"


# ---------------------------------------------------------------------------
# WebFetcher Unit Tests (mit unittest.mock)
# ---------------------------------------------------------------------------


class TestWebFetcherFetch:
    def test_fetch_success_returns_web_content(self, fetcher):
        html = "<html><title>Test Page</title><body><p>Hello world</p></body></html>"
        with (
            patch.object(fetcher, "_download", return_value=html),
            patch.object(
                fetcher, "_extract", return_value=("Test Page", "Hello world")
            ),
        ):
            result = fetcher.fetch("https://example.com")
        assert isinstance(result, WebContent)
        assert result.url == "https://example.com"
        assert result.title == "Test Page"
        assert result.text == "Hello world"
        assert result.truncated is False

    def test_fetch_uses_trafilatura_extraction(self, fetcher):
        html = "<html><title>T</title><body><p>Content</p></body></html>"
        with (
            patch.object(fetcher, "_download", return_value=html),
            patch(
                "elder_berry.tools.web_fetcher.WebFetcher._extract_trafilatura",
                return_value=("T", "Content"),
            ),
        ):
            result = fetcher.fetch("https://example.com")
        assert result.text == "Content"
        assert result.title == "T"

    def test_fetch_fallback_beautifulsoup_when_trafilatura_none(self, fetcher):
        html = "<html><title>BS Title</title><body><p>Fallback text</p></body></html>"
        with (
            patch.object(fetcher, "_download", return_value=html),
            patch(
                "elder_berry.tools.web_fetcher.WebFetcher._extract_trafilatura",
                return_value=("", ""),
            ),
            patch(
                "elder_berry.tools.web_fetcher.WebFetcher._extract_beautifulsoup",
                return_value=("BS Title", "Fallback text"),
            ),
        ):
            result = fetcher.fetch("https://example.com")
        assert result.title == "BS Title"
        assert result.text == "Fallback text"

    def test_fetch_truncates_at_max_chars(self, small_fetcher):
        long_text = "A" * 100
        with (
            patch.object(small_fetcher, "_download", return_value="<html></html>"),
            patch.object(small_fetcher, "_extract", return_value=("Title", long_text)),
        ):
            result = small_fetcher.fetch("https://example.com")
        assert len(result.text) == 50
        assert result.truncated is True

    def test_fetch_sets_truncated_true_when_cut(self, small_fetcher):
        text_exact = "A" * 51  # 1 char over limit
        with (
            patch.object(small_fetcher, "_download", return_value="<html></html>"),
            patch.object(small_fetcher, "_extract", return_value=("T", text_exact)),
        ):
            result = small_fetcher.fetch("https://example.com")
        assert result.truncated is True

    def test_fetch_not_truncated_when_under_limit(self, small_fetcher):
        text_short = "A" * 50  # exactly at limit
        with (
            patch.object(small_fetcher, "_download", return_value="<html></html>"),
            patch.object(small_fetcher, "_extract", return_value=("T", text_short)),
        ):
            result = small_fetcher.fetch("https://example.com")
        assert result.truncated is False

    def test_fetch_timeout_raises_meaningful_error(self, fetcher):
        import httpx

        with patch.object(
            fetcher, "_download", side_effect=httpx.TimeoutException("timeout")
        ):
            with pytest.raises(httpx.TimeoutException):
                fetcher.fetch("https://example.com")

    def test_fetch_connection_error_raises_meaningful_error(self, fetcher):
        import httpx

        with patch.object(
            fetcher, "_download", side_effect=httpx.ConnectError("refused")
        ):
            with pytest.raises(httpx.ConnectError):
                fetcher.fetch("https://example.com")

    def test_fetch_invalid_url_raises_value_error(self, fetcher):
        # "not-a-url" hat kein Schema --> UnsafeUrlError("Schema ... nicht erlaubt.")
        # UnsafeUrlError ist ValueError-Subklasse.
        with pytest.raises(ValueError, match="Schema"):
            fetcher.fetch("not-a-url")

    def test_fetch_empty_url_raises_value_error(self, fetcher):
        with pytest.raises(ValueError, match="Keine URL"):
            fetcher.fetch("")

    def test_fetch_empty_extraction_raises_error(self, fetcher):
        with (
            patch.object(fetcher, "_download", return_value="<html></html>"),
            patch.object(fetcher, "_extract", return_value=("Title", "")),
        ):
            with pytest.raises(RuntimeError, match="Kein Text"):
                fetcher.fetch("https://example.com")


class TestWebFetcherSSRFProtection:
    """Phase 64 (H-3): SSRF-Schutz ueber ensure_public_url."""

    def test_fetch_blocks_loopback(self, fetcher, monkeypatch):
        monkeypatch.setattr(
            "elder_berry.core.url_validator.socket.getaddrinfo",
            lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 0))],
        )
        with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
            fetcher.fetch("http://localhost/")

    def test_fetch_blocks_aws_metadata(self, fetcher, monkeypatch):
        monkeypatch.setattr(
            "elder_berry.core.url_validator.socket.getaddrinfo",
            lambda *a, **kw: [(None, None, None, None, ("169.254.169.254", 0))],
        )
        with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
            fetcher.fetch("http://169.254.169.254/latest/meta-data/")

    def test_fetch_blocks_private_10(self, fetcher, monkeypatch):
        monkeypatch.setattr(
            "elder_berry.core.url_validator.socket.getaddrinfo",
            lambda *a, **kw: [(None, None, None, None, ("10.0.0.1", 0))],
        )
        with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
            fetcher.fetch("http://internal-service.lan/")

    def test_fetch_blocks_private_192_168(self, fetcher, monkeypatch):
        monkeypatch.setattr(
            "elder_berry.core.url_validator.socket.getaddrinfo",
            lambda *a, **kw: [(None, None, None, None, ("192.168.1.1", 0))],
        )
        with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
            fetcher.fetch("http://router.home/")

    def test_fetch_blocks_file_scheme(self, fetcher):
        with pytest.raises(UnsafeUrlError, match="Schema"):
            fetcher.fetch("file:///etc/passwd")

    def test_fetch_blocks_gopher_scheme(self, fetcher):
        with pytest.raises(UnsafeUrlError, match="Schema"):
            fetcher.fetch("gopher://example.com/")

    def test_fetch_dns_rebinding_any_private_blocks(self, fetcher, monkeypatch):
        # Public + private gemischt --> blockieren (TOCTOU/rebinding-Schutz).
        monkeypatch.setattr(
            "elder_berry.core.url_validator.socket.getaddrinfo",
            lambda *a, **kw: [
                (None, None, None, None, ("8.8.8.8", 0)),
                (None, None, None, None, ("10.0.0.1", 0)),
            ],
        )
        with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
            fetcher.fetch("http://rebinding.example/")

    def test_fetch_blocks_ssrf_via_open_redirect(self, fetcher, monkeypatch):
        """SSRF via Open-Redirect: Location-Header auf private IP muss blockiert werden.

        Szenario: oeffentliche URL leitet auf interne Adresse um. Ohne
        manuelle Redirect-Validierung wuerde follow_redirects=True den
        SSRF-Check umgehen.
        """

        def selective_resolver(host, *args, **kwargs):
            if host == "trusted.example.com":
                return [(None, None, None, None, ("93.184.216.34", 0))]
            return [(None, None, None, None, ("10.0.0.1", 0))]

        monkeypatch.setattr(
            "elder_berry.core.url_validator.socket.getaddrinfo",
            selective_resolver,
        )

        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"location": "http://internal.corp/secret"}

        # httpx.stream() ist ein Context-Manager -- mocken via __enter__
        stream_cm = MagicMock()
        stream_cm.__enter__ = MagicMock(return_value=redirect_response)
        stream_cm.__exit__ = MagicMock(return_value=False)
        with patch("httpx.stream", return_value=stream_cm):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                fetcher.fetch("https://trusted.example.com/page")


# ---------------------------------------------------------------------------
# Phase 70 (H-3): Stream-Download mit Hard-Cap
# ---------------------------------------------------------------------------


def _make_stream_response(
    *,
    body_chunks: list[bytes] | None = None,
    headers: dict[str, str] | None = None,
    is_redirect: bool = False,
    status_code: int = 200,
):
    """Erzeugt einen Mock fuer ``httpx.Response`` im Stream-Modus."""
    response = MagicMock()
    response.is_redirect = is_redirect
    response.status_code = status_code
    response.headers = headers or {}
    response.encoding = "utf-8"
    response.iter_bytes = MagicMock(return_value=iter(body_chunks or []))
    response.raise_for_status = MagicMock()
    return response


def _stream_cm(response):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=response)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


class TestWebFetcherSizeLimit:
    """Phase 70 (H-3): WebFetcher.fetch() darf den Speicher nicht fluten."""

    def test_default_max_response_bytes_is_5mb(self, fetcher):
        from elder_berry.tools.web_fetcher import DEFAULT_MAX_RESPONSE_BYTES

        assert fetcher._max_response_bytes == DEFAULT_MAX_RESPONSE_BYTES
        assert DEFAULT_MAX_RESPONSE_BYTES == 5 * 1024 * 1024

    def test_invalid_limit_raises(self):
        with pytest.raises(ValueError):
            WebFetcher(max_response_bytes=10)

    def test_content_length_over_limit_rejected(self):
        from elder_berry.tools.web_fetcher import ResponseTooLargeError

        fetcher = WebFetcher(max_response_bytes=1024)
        big_response = _make_stream_response(
            headers={"content-length": str(10 * 1024 * 1024)},
            body_chunks=[b"<html>"],
        )
        with patch("httpx.stream", return_value=_stream_cm(big_response)):
            with pytest.raises(ResponseTooLargeError, match="signalisiert"):
                fetcher.fetch("https://example.com")

    def test_streamed_body_over_limit_rejected(self):
        """Server schickt keine Content-Length, streamt mehr als limit."""
        from elder_berry.tools.web_fetcher import ResponseTooLargeError

        fetcher = WebFetcher(max_response_bytes=1024)
        # 10 chunks * 200 bytes = 2 KB > 1 KB Limit
        chunks = [b"a" * 200] * 10
        streamed_response = _make_stream_response(body_chunks=chunks)
        with patch("httpx.stream", return_value=_stream_cm(streamed_response)):
            with pytest.raises(ResponseTooLargeError, match="ueberschreitet"):
                fetcher.fetch("https://example.com")

    def test_small_response_passes(self):
        """Antwort innerhalb des Limits liefert den vollen Body zurueck.

        Wir testen ``_download()`` direkt, nicht ``fetch()`` -- der
        Extraktor (trafilatura/bs4) ist optional und in CI nicht
        immer installiert. Der Size-Cap lebt in ``_read_capped`` /
        ``_download``, vor dem Extraktor; das ist hier das Subject.
        """
        fetcher = WebFetcher(max_response_bytes=1024 * 1024)
        html = (
            b"<html><head><title>Test</title></head>"
            b"<body><p>Hello world</p></body></html>"
        )
        ok_response = _make_stream_response(body_chunks=[html])
        with patch("httpx.stream", return_value=_stream_cm(ok_response)):
            body = fetcher._download("https://example.com")
        assert "Hello world" in body
        assert body == html.decode("utf-8")

    def test_invalid_content_length_header_ignored(self):
        """``Content-Length: garbage`` fuehrt nicht zum Crash, sondern
        faellt in den Streaming-Pfad mit Cap zurueck."""
        fetcher = WebFetcher(max_response_bytes=1024 * 1024)
        html = b"<html><body><p>fine</p></body></html>"
        response = _make_stream_response(
            headers={"content-length": "not-a-number"},
            body_chunks=[html],
        )
        with patch("httpx.stream", return_value=_stream_cm(response)):
            body = fetcher._download("https://example.com")
        assert "fine" in body

    def test_unknown_encoding_falls_back_to_utf8(self):
        fetcher = WebFetcher(max_response_bytes=1024 * 1024)
        html = "<html><body><p>Hällo</p></body></html>".encode("utf-8")
        response = _make_stream_response(body_chunks=[html])
        response.encoding = "definitely-not-a-real-encoding"
        with patch("httpx.stream", return_value=_stream_cm(response)):
            body = fetcher._download("https://example.com")
        assert "Hällo" in body


# ---------------------------------------------------------------------------
# Handler Tests (mock WebFetcher)
# ---------------------------------------------------------------------------


class TestCmdWebSummary:
    def test_cmd_web_summary_success(self, handler, mock_fetcher):
        mock_fetcher.fetch.return_value = WebContent(
            url="https://example.com",
            title="Example",
            text="Some content",
            truncated=False,
        )
        result = handler.execute("web_summary", "fasse https://example.com zusammen")
        assert result.success is True
        assert "Example" in result.text
        assert "https://example.com" in result.text
        assert result.history_text is not None
        assert "Some content" in result.history_text

    def test_cmd_web_summary_truncated_note_in_text(self, handler, mock_fetcher):
        mock_fetcher.fetch.return_value = WebContent(
            url="https://example.com",
            title="Example",
            text="Truncated content",
            truncated=True,
        )
        result = handler.execute("web_summary", "fasse https://example.com zusammen")
        assert result.success is True
        assert "gekuerzt" in result.text

    def test_cmd_web_summary_fetcher_not_configured(self):
        handler = AdvancedCommandHandler(web_fetcher=None)
        result = handler.execute("web_summary", "fasse https://example.com zusammen")
        assert result.success is False
        assert "nicht verfuegbar" in result.text

    def test_cmd_web_summary_fetch_error_graceful(self, handler, mock_fetcher):
        mock_fetcher.fetch.side_effect = RuntimeError("Kein Text extrahierbar")
        result = handler.execute("web_summary", "fasse https://example.com zusammen")
        assert result.success is False
        assert "nicht gelesen" in result.text

    def test_cmd_web_summary_fetch_error_brave_fallback(self, mock_fetcher):
        """Bei Fetch-Fehler wird Brave Search als Fallback verwendet."""
        mock_search = MagicMock()
        mock_search.search.return_value = [{"title": "R", "snippet": "Snippet text"}]
        mock_search.format_results.return_value = "Formatted snippet"

        handler = AdvancedCommandHandler(
            web_fetcher=mock_fetcher,
            search_client=mock_search,
        )
        mock_fetcher.fetch.side_effect = RuntimeError("JS-only")

        result = handler.execute("web_summary", "fasse https://example.com zusammen")
        assert result.success is True
        assert "Snippet" in (result.history_text or "")
        assert "Volltext nicht verfuegbar" in result.text

    def test_cmd_web_summary_no_url_match(self, handler):
        result = handler.execute("web_summary", "fasse das dokument zusammen")
        assert result.success is False
        assert "URL nicht erkannt" in result.text
