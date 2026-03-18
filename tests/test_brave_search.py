"""Tests: BraveSearchClient – Brave Search API Integration."""
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.brave_search_client import (
    BraveSearchClient,
    SearchResult,
    _clean_description,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_store(with_key: bool = True):
    """Erstellt einen Mock-SecretStore mit oder ohne Brave API-Key."""
    store = MagicMock()
    if with_key:
        def get_or_none(key):
            return {"brave_api_key": "test-api-key-123"}.get(key)
        store.get_or_none.side_effect = get_or_none
    else:
        store.get_or_none.return_value = None
    return store


MOCK_SEARCH_RESPONSE = {
    "web": {
        "results": [
            {
                "title": "Dachdecker Müller",
                "url": "https://dachdecker-mueller.de",
                "description": "Ihr <strong>Dachdecker</strong> in Plattenburg. 20 Jahre Erfahrung.",
            },
            {
                "title": "Dachdeckerei Schmidt & Sohn",
                "url": "https://schmidt-dach.de",
                "description": "Meisterbetrieb für <em>Dacharbeiten</em> in Brandenburg.",
            },
            {
                "title": "Dachdecker-Verzeichnis",
                "url": "https://dachdecker-verzeichnis.de/plattenburg",
                "description": "Finden Sie Dachdecker in Ihrer Nähe.",
            },
        ]
    }
}

MOCK_EMPTY_RESPONSE = {"web": {"results": []}}

MOCK_NO_WEB_KEY_RESPONSE = {"query": {"original": "test"}}


# ---------------------------------------------------------------------------
# DTO Tests
# ---------------------------------------------------------------------------

class TestSearchResultDTO:
    """SearchResult Dataclass Tests."""

    def test_create(self):
        r = SearchResult(title="Test", url="https://example.com", description="Desc")
        assert r.title == "Test"
        assert r.url == "https://example.com"
        assert r.description == "Desc"

    def test_frozen(self):
        r = SearchResult(title="Test", url="https://example.com", description="Desc")
        with pytest.raises(AttributeError):
            r.title = "Other"

    def test_empty_fields(self):
        r = SearchResult(title="", url="", description="")
        assert r.title == ""


# ---------------------------------------------------------------------------
# Init Tests
# ---------------------------------------------------------------------------

class TestBraveSearchClientInit:
    """BraveSearchClient Initialisierung."""

    def test_init(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        assert client._client is None

    def test_api_key_missing(self):
        store = _make_store(with_key=False)
        client = BraveSearchClient(secret_store=store)
        with pytest.raises(ValueError, match="Brave Search API-Key nicht konfiguriert"):
            client._get_api_key()

    def test_api_key_present(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        assert client._get_api_key() == "test-api-key-123"


# ---------------------------------------------------------------------------
# Search Tests
# ---------------------------------------------------------------------------

class TestBraveSearchClientSearch:
    """BraveSearchClient.search() Tests."""

    @patch("elder_berry.tools.brave_search_client.BraveSearchClient._get_client")
    def test_search_basic(self, mock_get_client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_SEARCH_RESPONSE
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = client.search("Dachdecker Plattenburg")

        assert len(results) == 3
        assert results[0].title == "Dachdecker Müller"
        assert results[0].url == "https://dachdecker-mueller.de"
        assert "<strong>" in results[0].description  # Roh-HTML bleibt im DTO

    @patch("elder_berry.tools.brave_search_client.BraveSearchClient._get_client")
    def test_search_headers(self, mock_get_client):
        """API-Key wird im Header gesendet."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_EMPTY_RESPONSE
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        client.search("test")

        call_args = mock_client.get.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert headers["X-Subscription-Token"] == "test-api-key-123"

    @patch("elder_berry.tools.brave_search_client.BraveSearchClient._get_client")
    def test_search_params(self, mock_get_client):
        """Query und Count werden als Parameter gesendet."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_EMPTY_RESPONSE
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        client.search("test query", count=3)

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["q"] == "test query"
        assert params["count"] == "3"

    @patch("elder_berry.tools.brave_search_client.BraveSearchClient._get_client")
    def test_search_empty_results(self, mock_get_client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_EMPTY_RESPONSE
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = client.search("gibberish nonsense xyz")

        assert results == []

    @patch("elder_berry.tools.brave_search_client.BraveSearchClient._get_client")
    def test_search_no_web_key(self, mock_get_client):
        """API-Antwort ohne 'web'-Key → leere Liste."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_NO_WEB_KEY_RESPONSE
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = client.search("test")

        assert results == []

    def test_search_empty_query(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = client.search("")
        assert results == []

    def test_search_whitespace_query(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = client.search("   ")
        assert results == []

    @patch("elder_berry.tools.brave_search_client.BraveSearchClient._get_client")
    def test_search_count_clamped_min(self, mock_get_client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_EMPTY_RESPONSE
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        client.search("test", count=0)

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["count"] == "1"

    @patch("elder_berry.tools.brave_search_client.BraveSearchClient._get_client")
    def test_search_count_clamped_max(self, mock_get_client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_EMPTY_RESPONSE
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        client.search("test", count=50)

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["count"] == "20"

    @patch("elder_berry.tools.brave_search_client.BraveSearchClient._get_client")
    def test_search_strips_query(self, mock_get_client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_EMPTY_RESPONSE
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        client.search("  test query  ")

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["q"] == "test query"


# ---------------------------------------------------------------------------
# Format Tests
# ---------------------------------------------------------------------------

class TestFormatResults:
    """format_results() Tests."""

    def test_format_empty(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        text = client.format_results([])
        assert text == "Keine Ergebnisse gefunden."

    def test_format_single(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = [SearchResult("Test Titel", "https://test.de", "Beschreibung")]
        text = client.format_results(results)

        assert "1 Ergebnis:" in text
        assert "**Test Titel**" in text
        assert "https://test.de" in text
        assert "Beschreibung" in text

    def test_format_multiple(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = [
            SearchResult("Eins", "https://eins.de", "Erster"),
            SearchResult("Zwei", "https://zwei.de", "Zweiter"),
        ]
        text = client.format_results(results)

        assert "2 Ergebnisse:" in text
        assert "1. **Eins**" in text
        assert "2. **Zwei**" in text

    def test_format_cleans_html(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = [SearchResult("Test", "https://t.de", "Ein <strong>fetter</strong> Text")]
        text = client.format_results(results)

        assert "<strong>" not in text
        assert "Ein fetter Text" in text

    def test_format_empty_description(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = [SearchResult("Test", "https://t.de", "")]
        text = client.format_results(results)

        assert "**Test**" in text
        assert "https://t.de" in text


class TestFormatResultsDetailed:
    """format_results_detailed() Tests."""

    def test_detailed_empty(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        text = client.format_results_detailed([])
        assert text == "Keine Ergebnisse gefunden."

    def test_detailed_contains_all_fields(self):
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = [SearchResult("Titel", "https://url.de", "Beschreibung hier")]
        text = client.format_results_detailed(results)

        assert "Titel: Titel" in text
        assert "URL: https://url.de" in text
        assert "Beschreibung: Beschreibung hier" in text
        assert "1 Treffer" in text

    def test_detailed_raw_html_preserved(self):
        """Detailed-Format behält HTML (für LLM-Kontext)."""
        store = _make_store()
        client = BraveSearchClient(secret_store=store)
        results = [SearchResult("T", "https://t.de", "<b>bold</b>")]
        text = client.format_results_detailed(results)

        assert "<b>bold</b>" in text


# ---------------------------------------------------------------------------
# Helper Tests
# ---------------------------------------------------------------------------

class TestCleanDescription:
    """_clean_description() Tests."""

    def test_empty(self):
        assert _clean_description("") == ""

    def test_no_html(self):
        assert _clean_description("Normaler Text") == "Normaler Text"

    def test_strong_tags(self):
        assert _clean_description("Ein <strong>fetter</strong> Text") == "Ein fetter Text"

    def test_mixed_tags(self):
        assert _clean_description("<em>kursiv</em> und <b>fett</b>") == "kursiv und fett"

    def test_strips_whitespace(self):
        assert _clean_description("  Leerzeichen  ") == "Leerzeichen"
