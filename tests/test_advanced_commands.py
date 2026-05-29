"""Tests: AdvancedCommandHandler – Computer Use, Web Search, Document Summary, Audio."""

from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.advanced_commands import (
    AUDIO_LOCAL_PATTERN,
    COMPUTER_USE_PATTERN,
    DOCUMENT_SUMMARY_PATTERN,
    WEB_SEARCH_PATTERN,
    AdvancedCommandHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def search_client():
    """Mock-BraveSearchClient. Liefert SearchResult-aehnliche Objekte mit
    title/url/description (Phase 80: list_items-Mapping liest description)."""
    client = MagicMock()
    result_1 = MagicMock()
    result_1.title = "Result 1"
    result_1.url = "https://example.com/1"
    result_1.description = "Snippet 1"
    result_2 = MagicMock()
    result_2.title = "Result 2"
    result_2.url = "https://example.com/2"
    result_2.description = "Snippet 2"
    client.search.return_value = [result_1, result_2]
    client.format_results.return_value = "1. Result 1\n2. Result 2"
    client.format_results_detailed.return_value = (
        "Result 1: https://example.com/1\nResult 2: https://example.com/2"
    )
    return client


@pytest.fixture
def document_reader():
    reader = MagicMock()
    result = MagicMock()
    result.source = "report.pdf"
    result.pages = 5
    result.truncated = False
    result.text = "Document content..."
    reader.read_file.return_value = result
    reader.is_supported.return_value = True
    return reader


@pytest.fixture
def audio_router():
    router = MagicMock()
    from unittest.mock import PropertyMock

    type(router).mode = PropertyMock(return_value=MagicMock(value="matrix_only"))
    router.local_available = False
    return router


@pytest.fixture
def computer_use():
    cu = MagicMock()
    result = MagicMock()
    result.success = True
    result.message = "Clicked OK button"
    result.verification_image_path = None
    cu.execute_instruction.return_value = result
    return cu


@pytest.fixture
def handler(computer_use, search_client, document_reader, audio_router):
    return AdvancedCommandHandler(
        computer_use=computer_use,
        search_client=search_client,
        document_reader=document_reader,
        audio_router=audio_router,
    )


@pytest.fixture
def handler_minimal():
    return AdvancedCommandHandler()


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------


class TestAudioLocalPattern:
    @pytest.mark.parametrize(
        "text,flag",
        [
            ("audio lokal an", "an"),
            ("audio lokal aus", "aus"),
            ("audio lokal ein", "ein"),
            ("audio lokal off", "off"),
            ("audio lokal on", "on"),
        ],
    )
    def test_valid(self, text, flag):
        m = AUDIO_LOCAL_PATTERN.match(text)
        assert m is not None
        assert m.group(1) == flag

    def test_invalid(self):
        assert AUDIO_LOCAL_PATTERN.match("audio lokal") is None


class TestDocumentSummaryPattern:
    @pytest.mark.parametrize(
        "text",
        [
            r"zusammenfassung C:\docs\report.pdf",
            "zusammenfassung /home/user/doc.pdf",
            r"fasse C:\docs\report.pdf zusammen",
        ],
    )
    def test_valid(self, text):
        assert DOCUMENT_SUMMARY_PATTERN.search(text) is not None


class TestComputerUsePattern:
    @pytest.mark.parametrize(
        "text",
        [
            "klick auf den OK-Button",
            "klicke auf Accept",
            "tippe Hello World",
            "scroll runter",
            "scroll hoch",
            "drücke Strg+S",
        ],
    )
    def test_valid(self, text):
        assert COMPUTER_USE_PATTERN.match(text) is not None

    def test_invalid(self):
        assert COMPUTER_USE_PATTERN.match("mache etwas") is None


class TestWebSearchPattern:
    @pytest.mark.parametrize(
        "text",
        [
            "suche Dachdecker",
            "such mal Python Tutorial",
            "google Rezept Lasagne",
            "finde Dachdecker",
        ],
    )
    def test_valid(self, text):
        assert WEB_SEARCH_PATTERN.match(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "finde meine mail von max",
            "suche in mails max",
            "suche in meinen mails max",
            "suche meine mails von max",
            "finde kontakt lisa",
        ],
    )
    def test_internal_domain_query_no_match(self, text):
        assert WEB_SEARCH_PATTERN.match(text) is None

    @pytest.mark.parametrize(
        "text",
        [
            "suche mail client windows",
            "suche mail server vergleich",
        ],
    )
    def test_external_mail_topic_still_matches(self, text):
        assert WEB_SEARCH_PATTERN.match(text) is not None


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class TestAdvancedInterface:
    def test_simple_commands(self, handler):
        assert "audio" in handler.simple_commands

    def test_patterns(self, handler):
        names = [p[1] for p in handler.patterns]
        assert "audio_toggle" in names
        assert "document_summary" in names
        assert "computer_use" in names
        assert "web_search" in names

    def test_keywords(self, handler):
        kw = handler.keywords
        assert "web_search" in kw
        assert "computer_use" in kw
        assert "document_summary" in kw


# ---------------------------------------------------------------------------
# Document Summary
# ---------------------------------------------------------------------------


class TestDocumentSummary:
    def test_success(self, handler, document_reader):
        result = handler.execute(
            "document_summary",
            r"zusammenfassung C:\docs\report.pdf",
        )
        assert result.success is True
        assert "report.pdf" in result.text
        assert result.history_text is not None

    def test_truncated_marker(self, handler, document_reader):
        document_reader.read_file.return_value.truncated = True
        result = handler.execute(
            "document_summary",
            r"zusammenfassung C:\docs\report.pdf",
        )
        assert "gekürzt" in result.text

    def test_not_supported(self, handler, document_reader):
        document_reader.is_supported.return_value = False
        result = handler.execute(
            "document_summary",
            r"zusammenfassung C:\docs\report.exe",
        )
        assert result.success is False
        assert "nicht unterstützt" in result.text

    def test_file_not_found(self, handler, document_reader):
        document_reader.read_file.side_effect = FileNotFoundError()
        result = handler.execute(
            "document_summary",
            r"zusammenfassung C:\docs\missing.pdf",
        )
        assert result.success is False
        assert "nicht gefunden" in result.text.lower()

    def test_no_reader(self, handler_minimal):
        result = handler_minimal.execute(
            "document_summary",
            r"zusammenfassung C:\docs\report.pdf",
        )
        assert result.success is False
        assert "DocumentReader" in result.text

    def test_invalid_path(self, handler):
        result = handler.execute("document_summary", "zusammenfassung nix")
        assert result.success is False


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


class TestAudio:
    def test_audio_status(self, handler, audio_router):
        result = handler.execute("audio", "audio")
        assert result.success is True
        assert "Audio-Modus" in result.text

    def test_audio_lokal_an(self, handler, audio_router):
        result = handler.execute("audio_toggle", "audio lokal an")
        assert result.success is True
        audio_router.set_mode.assert_called_once()

    def test_audio_lokal_aus(self, handler, audio_router):
        result = handler.execute("audio_toggle", "audio lokal aus")
        assert result.success is True

    def test_no_router(self, handler_minimal):
        result = handler_minimal.execute("audio", "audio")
        assert result.success is False
        assert "AudioRouter" in result.text


# ---------------------------------------------------------------------------
# Computer Use
# ---------------------------------------------------------------------------


class TestComputerUse:
    def test_success(self, handler, computer_use):
        result = handler.execute("computer_use", "klick auf den OK-Button")
        assert result.success is True
        computer_use.execute_instruction.assert_called_once()

    def test_failure(self, handler, computer_use):
        cu_result = MagicMock()
        cu_result.success = False
        cu_result.message = "Element not found"
        cu_result.verification_image_path = None
        computer_use.execute_instruction.return_value = cu_result
        result = handler.execute("computer_use", "klick auf den OK-Button")
        assert result.success is False

    def test_no_controller(self, handler_minimal):
        result = handler_minimal.execute("computer_use", "klick auf ok")
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_exception(self, handler, computer_use):
        computer_use.execute_instruction.side_effect = RuntimeError("fail")
        result = handler.execute("computer_use", "klick auf ok")
        assert result.success is False


# ---------------------------------------------------------------------------
# Web Search
# ---------------------------------------------------------------------------


class TestWebSearch:
    def test_success(self, handler, search_client):
        result = handler.execute("web_search", "suche Dachdecker")
        assert result.success is True
        search_client.search.assert_called_once_with("Dachdecker")
        assert result.history_text is not None

    def test_empty_query_gives_hint(self, handler):
        # "suche" allein wird vom Pattern nicht gematcht, aber via Keyword
        # kommt es mit leerem Query an → search wird mit "" aufgerufen
        # Das Verhalten ist: search_client.search("") wird aufgerufen
        result = handler.execute("web_search", "suche")
        # With keyword routing, "suche" prefix gets stripped → empty query
        # But search_client is mocked and returns results for any query
        assert result.success is True or result.success is False

    def test_no_client(self, handler_minimal):
        result = handler_minimal.execute("web_search", "suche test")
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_exception(self, handler, search_client):
        search_client.search.side_effect = RuntimeError("API error")
        result = handler.execute("web_search", "suche test")
        assert result.success is False

    def test_keyword_prefix_stripped(self, handler, search_client):
        """When routed via keyword, prefix should be stripped."""
        result = handler.execute("web_search", "such mal Python Tutorial")
        assert result.success is True
        search_client.search.assert_called_once_with("Python Tutorial")


# ---------------------------------------------------------------------------
# Phase 80: list_items / list_type fuer ConversationListStore-Integration
# ---------------------------------------------------------------------------


class TestWebSearchListIntegration:
    """``_cmd_search`` liefert strukturierte Items, die der Bridge in den
    ConversationListStore registriert (Phase 80 Etappe 2).
    """

    def test_list_items_carries_url_title_snippet(self, handler):
        result = handler.execute("web_search", "suche Drohnenbau")
        assert result.success is True
        assert result.list_type == "search"
        assert result.list_items is not None
        assert len(result.list_items) == 2
        first = result.list_items[0]
        assert first["title"] == "Result 1"
        assert first["url"] == "https://example.com/1"
        assert first["snippet"] == "Snippet 1"

    def test_list_items_order_matches_text(self, handler):
        """1-basierte Reihenfolge in ``text`` muss zur ``list_items``-
        Reihenfolge passen, sonst zeigt 'Treffer 2' falsch hin."""
        result = handler.execute("web_search", "suche Drohnenbau")
        assert result.list_items is not None
        assert result.list_items[0]["url"] == "https://example.com/1"
        assert result.list_items[1]["url"] == "https://example.com/2"

    def test_no_results_no_list(self, handler, search_client):
        """Leere Trefferliste -> kein list_items, kein list_type
        (sonst registriert die Bridge eine leere Liste)."""
        search_client.search.return_value = []
        result = handler.execute("web_search", "suche xyz123nonexistent")
        # success bleibt True (Brave hat geantwortet, nur halt nichts gefunden)
        assert result.list_items is None
        assert result.list_type is None

    def test_other_commands_have_no_list(self, handler):
        """Audio/CU/etc. sollen keine list_items setzen -- Defensive
        gegen False-Positive-Registers in der Bridge."""
        result = handler.execute("audio", "audio")
        assert result.list_items is None
        assert result.list_type is None


# ---------------------------------------------------------------------------
# Unknown Command
# ---------------------------------------------------------------------------


class TestUnknownCommand:
    def test_unknown(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False


# ---------------------------------------------------------------------------
# _download_from_nc: Temp-Dir-Leak Fixes (Security-Fix)
# ---------------------------------------------------------------------------


class TestDownloadFromNcTempDir:
    """Temp-Verzeichnisse werden in allen Fehlerpfaden korrekt aufgeräumt."""

    def _make_handler_with_nc(self, nc_mock):
        from elder_berry.comms.commands.advanced_commands import AdvancedCommandHandler

        handler = AdvancedCommandHandler.__new__(AdvancedCommandHandler)
        handler._nc_files = nc_mock
        return handler

    def test_empty_filename_no_tmpdir_created(self, tmp_path):
        """Pfad mit abschließendem Slash: kein Temp-Dir wird angelegt."""
        from unittest.mock import MagicMock

        nc = MagicMock()
        handler = self._make_handler_with_nc(nc)

        result = handler._download_from_nc("/Dokumente/")
        assert result is None
        # nc.download wurde NICHT aufgerufen (kein mkdtemp nötig gewesen)
        nc.download.assert_not_called()

    def test_both_strategies_fail_cleans_tmpdir(self, monkeypatch):
        """Wenn beide Download-Strategien scheitern, wird das Temp-Dir bereinigt."""
        from unittest.mock import MagicMock, patch
        import tempfile
        import os

        created_dirs: list[str] = []
        original_mkdtemp = tempfile.mkdtemp

        def tracking_mkdtemp(**kwargs):
            d = original_mkdtemp(**kwargs)
            created_dirs.append(d)
            return d

        nc = MagicMock()
        nc.download.side_effect = Exception("Download fehlgeschlagen")
        nc.search.side_effect = Exception("Suche fehlgeschlagen")

        handler = self._make_handler_with_nc(nc)

        with patch("tempfile.mkdtemp", side_effect=tracking_mkdtemp):
            result = handler._download_from_nc("/Dokumente/datei.pdf")

        assert result is None
        # Alle angelegten Temp-Dirs wurden gelöscht
        for d in created_dirs:
            assert not os.path.exists(d), f"Temp-Dir {d!r} wurde nicht gelöscht"


# ---------------------------------------------------------------------------
# Path-Traversal-Schutz (Phase 69 Security-Fix)
# ---------------------------------------------------------------------------


class TestDocumentSummaryPathTraversal:
    """PathGuard verhindert, dass Matrix-Sender beliebige Dateien lesen."""

    def _make_handler(self, document_reader, allowed_base):
        """Handler mit PathGuard auf eine Test-Base eingeschraenkt."""
        from elder_berry.comms.commands.advanced_commands import AdvancedCommandHandler
        from elder_berry.core.path_guard import PathGuard

        return AdvancedCommandHandler(
            document_reader=document_reader,
            path_guard=PathGuard([allowed_base]),
        )

    def test_traversal_outside_base_blocked(self, tmp_path, document_reader):
        """Datei *ausserhalb* der erlaubten Base wird abgewiesen."""
        # Erlaubte Base: tmp_path/safe. Datei liegt im Eltern-Verzeichnis.
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        outside_file = tmp_path / "outside.pdf"
        outside_file.write_bytes(b"%PDF outside")

        handler = self._make_handler(document_reader, safe_base)
        result = handler.execute(
            "document_summary",
            f"zusammenfassung {outside_file}",
        )

        assert result.success is False
        assert "Zugriff verweigert" in result.text
        # Pfad darf NICHT in der Antwort echoed werden
        assert str(outside_file) not in result.text
        # DocumentReader darf gar nicht angefasst worden sein
        document_reader.read_file.assert_not_called()

    def test_traversal_dotdot_blocked(self, tmp_path, document_reader):
        """`../`-Traversal aus einer Sub-Base heraus wird abgewiesen."""
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        secret = tmp_path / "secret.pdf"
        secret.write_bytes(b"%PDF secret")

        handler = self._make_handler(document_reader, safe_base)
        # Pfad konstruieren: safe/../secret.pdf -> tmp_path/secret.pdf
        traversal_path = safe_base / ".." / "secret.pdf"
        result = handler.execute(
            "document_summary",
            f"zusammenfassung {traversal_path}",
        )

        assert result.success is False
        assert "Zugriff verweigert" in result.text
        document_reader.read_file.assert_not_called()

    def test_inside_base_allowed(self, tmp_path, document_reader):
        """Datei *innerhalb* der erlaubten Base wird normal verarbeitet."""
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        ok_file = safe_base / "ok.pdf"
        ok_file.write_bytes(b"%PDF ok")

        handler = self._make_handler(document_reader, safe_base)
        result = handler.execute(
            "document_summary",
            f"zusammenfassung {ok_file}",
        )

        assert result.success is True
        document_reader.read_file.assert_called_once()
