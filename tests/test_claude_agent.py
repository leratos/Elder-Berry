"""Tests: ClaudeAgent – Anthropic API Client für komplexe Anfragen.

Alle Tests Mock-basiert (kein echter API-Call).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.claude_agent import (
    ALLOWED_ACTIONS,
    AgentResult,
    ClaudeAgent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_root(tmp_path):
    """Erstellt eine Projekt-Struktur für Tests."""
    # CLAUDE.md
    (tmp_path / "CLAUDE.md").write_text(
        "# Test CLAUDE.md\nTest-Projekt", encoding="utf-8"
    )

    # docs/journal.txt
    docs = tmp_path / "docs"
    docs.mkdir()
    journal_lines = [f"Zeile {i}" for i in range(1, 101)]
    (docs / "journal.txt").write_text("\n".join(journal_lines), encoding="utf-8")

    # docs/concepts/
    (docs / "concepts").mkdir()

    # src/ (nicht beschreibbar)
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.py").write_text("# test", encoding="utf-8")

    # tests/
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_example.py").write_text("def test_ok(): pass", encoding="utf-8")

    return tmp_path


@pytest.fixture
def agent(project_root):
    """ClaudeAgent mit Mock-API-Key."""
    return ClaudeAgent(
        api_key="sk-ant-test-key",
        project_root=project_root,
    )


def _make_api_response(action: str, params: dict = None, summary: str = "OK"):
    """Erstellt eine Mock-API-Antwort."""
    payload = {
        "action": action,
        "params": params or {},
        "summary": summary,
        "reasoning": "Test",
    }
    mock_block = MagicMock()
    mock_block.text = json.dumps(payload)
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    return mock_response


# ---------------------------------------------------------------------------
# AgentResult DTO
# ---------------------------------------------------------------------------


class TestAgentResult:
    def test_creation(self):
        result = AgentResult(
            success=True,
            action_taken="read_file",
            summary="Datei gelesen",
            details="Inhalt",
        )
        assert result.success is True
        assert result.action_taken == "read_file"
        assert result.summary == "Datei gelesen"
        assert result.details == "Inhalt"

    def test_default_details_none(self):
        result = AgentResult(success=True, action_taken="answer_only", summary="OK")
        assert result.details is None

    def test_frozen(self):
        result = AgentResult(success=True, action_taken="answer_only", summary="OK")
        with pytest.raises(AttributeError):
            result.success = False


# ---------------------------------------------------------------------------
# ClaudeAgent – Initialisierung
# ---------------------------------------------------------------------------


class TestClaudeAgentInit:
    def test_creation(self, agent, project_root):
        assert agent.model == "claude-sonnet-4-6"
        assert agent.project_root == project_root.resolve()
        assert agent.allowed_actions == ALLOWED_ACTIONS

    def test_custom_model(self, project_root):
        agent = ClaudeAgent(
            api_key="test",
            project_root=project_root,
            model="claude-haiku-4-5-20251001",
        )
        assert agent.model == "claude-haiku-4-5-20251001"

    def test_custom_allowed_actions(self, project_root):
        custom = frozenset({"answer_only", "read_file"})
        agent = ClaudeAgent(
            api_key="test",
            project_root=project_root,
            allowed_actions=custom,
        )
        assert agent.allowed_actions == custom


# ---------------------------------------------------------------------------
# Kontext-Laden
# ---------------------------------------------------------------------------


class TestContextLoading:
    def test_load_claude_md(self, agent):
        content = agent._load_claude_md()
        assert "Test CLAUDE.md" in content

    def test_load_claude_md_missing(self, tmp_path):
        agent = ClaudeAgent(api_key="test", project_root=tmp_path)
        content = agent._load_claude_md()
        assert "nicht gefunden" in content

    def test_load_journal_tail(self, agent):
        tail = agent._load_journal_tail()
        # Sollte die letzten 80 Zeilen enthalten (von 100 Zeilen)
        assert "Zeile 21" in tail
        assert "Zeile 100" in tail
        # Zeile 1-20 sollten nicht drin sein (weil >80 Zeilen)
        assert "Zeile 1\n" not in tail

    def test_load_journal_missing(self, tmp_path):
        agent = ClaudeAgent(api_key="test", project_root=tmp_path)
        tail = agent._load_journal_tail()
        assert "nicht gefunden" in tail

    def test_build_system_prompt(self, agent):
        prompt = agent._build_system_prompt()
        assert "Saleria" in prompt
        assert "Test CLAUDE.md" in prompt
        assert "Zeile 100" in prompt
        assert "answer_only" in prompt


# ---------------------------------------------------------------------------
# JSON-Parsing
# ---------------------------------------------------------------------------


class TestResponseParsing:
    def test_direct_json(self, agent):
        raw = '{"action": "answer_only", "params": {}, "summary": "OK"}'
        parsed = agent._parse_response(raw)
        assert parsed["action"] == "answer_only"

    def test_json_in_codeblock(self, agent):
        raw = '```json\n{"action": "read_file", "params": {"path": "docs/x.md"}, "summary": "OK"}\n```'
        parsed = agent._parse_response(raw)
        assert parsed["action"] == "read_file"

    def test_json_with_surrounding_text(self, agent):
        raw = 'Hier ist meine Antwort: {"action": "answer_only", "params": {}, "summary": "Test"} fertig.'
        parsed = agent._parse_response(raw)
        assert parsed["action"] == "answer_only"

    def test_invalid_json_raises(self, agent):
        with pytest.raises(ValueError, match="kein gültiges JSON"):
            agent._parse_response("das ist kein json überhaupt")

    def test_json_with_whitespace(self, agent):
        raw = '  \n  {"action": "git_status", "params": {}, "summary": "Status"}  \n  '
        parsed = agent._parse_response(raw)
        assert parsed["action"] == "git_status"


# ---------------------------------------------------------------------------
# Aktions-Validierung
# ---------------------------------------------------------------------------


class TestActionValidation:
    def test_valid_action(self, agent):
        parsed = {
            "action": "read_file",
            "params": {"path": "docs/x.md"},
            "summary": "OK",
        }
        action, params, summary = agent._validate_action(parsed)
        assert action == "read_file"
        assert params == {"path": "docs/x.md"}
        assert summary == "OK"

    def test_missing_action(self, agent):
        with pytest.raises(ValueError, match="kein 'action'-Feld"):
            agent._validate_action({"params": {}, "summary": "X"})

    def test_disallowed_action(self, agent):
        with pytest.raises(ValueError, match="nicht erlaubt"):
            agent._validate_action(
                {"action": "shell_exec", "params": {}, "summary": "X"}
            )

    def test_empty_summary_gets_default(self, agent):
        parsed = {"action": "answer_only", "params": {}, "summary": ""}
        _, _, summary = agent._validate_action(parsed)
        assert "answer_only" in summary

    def test_all_allowed_actions_pass(self, agent):
        for action in ALLOWED_ACTIONS:
            parsed = {"action": action, "params": {}, "summary": "OK"}
            a, _, _ = agent._validate_action(parsed)
            assert a == action


# ---------------------------------------------------------------------------
# Pfad-Validierung
# ---------------------------------------------------------------------------


class TestPathValidation:
    def test_valid_path(self, agent, project_root):
        resolved = agent._validate_path("docs/journal.txt")
        assert resolved == (project_root / "docs" / "journal.txt").resolve()

    def test_path_traversal_blocked(self, agent):
        with pytest.raises(ValueError, match="außerhalb des Projekts"):
            agent._validate_path("../../etc/passwd")

    def test_writable_path_in_docs(self, agent, project_root):
        resolved = agent._validate_writable_path("docs/new_file.md")
        assert str(resolved).startswith(str(project_root.resolve()))

    def test_writable_path_outside_docs_blocked(self, agent):
        with pytest.raises(ValueError, match="nicht erlaubt"):
            agent._validate_writable_path("src/hack.py")

    def test_appendable_path_journal(self, agent, project_root):
        resolved = agent._validate_appendable_path("docs/journal.txt")
        assert resolved.name == "journal.txt"

    def test_appendable_path_other_blocked(self, agent):
        with pytest.raises(ValueError, match="nicht erlaubt"):
            agent._validate_appendable_path("docs/other.txt")

    def test_leading_slashes_stripped(self, agent, project_root):
        resolved = agent._validate_path("/docs/journal.txt")
        assert resolved == (project_root / "docs" / "journal.txt").resolve()


# ---------------------------------------------------------------------------
# Aktions-Ausführung: read_file
# ---------------------------------------------------------------------------


class TestExecReadFile:
    def test_read_existing_file(self, agent, project_root):
        result = agent._exec_read_file({"path": "CLAUDE.md"})
        assert result.success is True
        assert result.action_taken == "read_file"
        assert "Test CLAUDE.md" in result.details

    def test_read_missing_file(self, agent):
        result = agent._exec_read_file({"path": "nope.txt"})
        assert result.success is False
        assert "nicht gefunden" in result.summary

    def test_read_no_path(self, agent):
        result = agent._exec_read_file({})
        assert result.success is False
        assert "Kein Pfad" in result.summary

    def test_read_directory_fails(self, agent):
        result = agent._exec_read_file({"path": "docs"})
        assert result.success is False

    def test_read_long_file_truncated(self, agent, project_root):
        big_file = project_root / "docs" / "big.txt"
        big_file.write_text("x" * 10000, encoding="utf-8")
        result = agent._exec_read_file({"path": "docs/big.txt"})
        assert result.success is True
        assert "gekürzt" in result.details

    def test_read_path_traversal(self, agent):
        result = agent._exec_read_file({"path": "../../etc/passwd"})
        assert result.success is False
        assert "außerhalb" in result.summary


# ---------------------------------------------------------------------------
# Aktions-Ausführung: write_file
# ---------------------------------------------------------------------------


class TestExecWriteFile:
    def test_write_in_docs(self, agent, project_root):
        result = agent._exec_write_file(
            {
                "path": "docs/test_write.md",
                "content": "# Test\nInhalt",
            }
        )
        assert result.success is True
        written = (project_root / "docs" / "test_write.md").read_text(encoding="utf-8")
        assert written == "# Test\nInhalt"

    def test_write_outside_docs_blocked(self, agent):
        result = agent._exec_write_file(
            {
                "path": "src/evil.py",
                "content": "import os; os.system('rm -rf /')",
            }
        )
        assert result.success is False
        assert "nicht erlaubt" in result.summary

    def test_write_no_path(self, agent):
        result = agent._exec_write_file({"content": "test"})
        assert result.success is False

    def test_write_creates_subdirectory(self, agent, project_root):
        result = agent._exec_write_file(
            {
                "path": "docs/sub/deep/file.md",
                "content": "nested",
            }
        )
        assert result.success is True
        assert (project_root / "docs" / "sub" / "deep" / "file.md").exists()


# ---------------------------------------------------------------------------
# Aktions-Ausführung: append_file
# ---------------------------------------------------------------------------


class TestExecAppendFile:
    def test_append_to_journal(self, agent, project_root):
        result = agent._exec_append_file(
            {
                "path": "docs/journal.txt",
                "content": "## Neuer Eintrag",
            }
        )
        assert result.success is True
        content = (project_root / "docs" / "journal.txt").read_text(encoding="utf-8")
        assert "Neuer Eintrag" in content

    def test_append_to_other_file_blocked(self, agent):
        result = agent._exec_append_file(
            {
                "path": "docs/other.txt",
                "content": "nope",
            }
        )
        assert result.success is False
        assert "nicht erlaubt" in result.summary

    def test_append_no_path(self, agent):
        result = agent._exec_append_file({"content": "test"})
        assert result.success is False


# ---------------------------------------------------------------------------
# Aktions-Ausführung: list_directory
# ---------------------------------------------------------------------------


class TestExecListDirectory:
    def test_list_root(self, agent, project_root):
        result = agent._exec_list_directory({"path": "."})
        assert result.success is True
        assert "docs/" in result.details

    def test_list_docs(self, agent):
        result = agent._exec_list_directory({"path": "docs"})
        assert result.success is True
        assert "journal.txt" in result.details

    def test_list_nonexistent(self, agent):
        result = agent._exec_list_directory({"path": "nope"})
        assert result.success is False
        assert "nicht gefunden" in result.summary

    def test_list_file_not_dir(self, agent):
        result = agent._exec_list_directory({"path": "CLAUDE.md"})
        assert result.success is False
        assert "Kein Verzeichnis" in result.summary


# ---------------------------------------------------------------------------
# Aktions-Ausführung: search_files
# ---------------------------------------------------------------------------


class TestExecSearchFiles:
    def test_search_md_files(self, agent):
        result = agent._exec_search_files({"pattern": "*.md", "path": "."})
        assert result.success is True
        assert "CLAUDE.md" in result.details

    def test_search_no_pattern(self, agent):
        result = agent._exec_search_files({})
        assert result.success is False
        assert "Kein Suchmuster" in result.summary

    def test_search_no_results(self, agent):
        result = agent._exec_search_files({"pattern": "*.xyz"})
        assert result.success is True
        assert "0 Treffer" in result.summary


# ---------------------------------------------------------------------------
# Aktions-Ausführung: answer_only
# ---------------------------------------------------------------------------


class TestExecAnswerOnly:
    def test_answer_only(self, agent):
        result = agent._execute_action("answer_only", {}, "Die nächste Phase ist 8.")
        assert result.success is True
        assert result.action_taken == "answer_only"
        assert result.summary == "Die nächste Phase ist 8."


# ---------------------------------------------------------------------------
# Aktions-Ausführung: git_status
# ---------------------------------------------------------------------------


class TestExecGitStatus:
    def test_git_status(self, agent, project_root):
        # Initialisiere ein git repo im tmp_path
        import subprocess

        subprocess.run(
            ["git", "init"],
            cwd=str(project_root),
            capture_output=True,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=str(project_root),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init", "--allow-empty"],
            cwd=str(project_root),
            capture_output=True,
            env={
                **__import__("os").environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )
        result = agent._exec_git_status()
        assert result.success is True
        assert "git status" in result.details


# ---------------------------------------------------------------------------
# process() – End-to-End (Mock-API)
# ---------------------------------------------------------------------------


class TestProcess:
    def test_empty_message(self, agent):
        result = agent.process("")
        assert result.success is False
        assert "Leere Nachricht" in result.summary

    def test_whitespace_message(self, agent):
        result = agent.process("   ")
        assert result.success is False
        assert "Leere Nachricht" in result.summary

    @patch("elder_berry.comms.claude_agent.ClaudeAgent._get_client")
    def test_answer_only(self, mock_get_client, agent):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(
            "answer_only",
            summary="Die nächste Phase ist Phase 8.",
        )
        mock_get_client.return_value = mock_client

        result = agent.process("Welche Phase kommt als nächstes?")
        assert result.success is True
        assert result.action_taken == "answer_only"
        assert "Phase 8" in result.summary

    @patch("elder_berry.comms.claude_agent.ClaudeAgent._get_client")
    def test_read_file_action(self, mock_get_client, agent):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(
            "read_file",
            params={"path": "CLAUDE.md"},
            summary="CLAUDE.md gelesen",
        )
        mock_get_client.return_value = mock_client

        result = agent.process("Zeig mir die CLAUDE.md")
        assert result.success is True
        assert result.action_taken == "read_file"
        assert "Test CLAUDE.md" in result.details

    @patch("elder_berry.comms.claude_agent.ClaudeAgent._get_client")
    def test_write_file_action(self, mock_get_client, agent, project_root):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(
            "write_file",
            params={"path": "docs/notiz.md", "content": "# Notiz\nWichtig!"},
            summary="Notiz erstellt",
        )
        mock_get_client.return_value = mock_client

        result = agent.process("Erstelle eine Notiz in docs")
        assert result.success is True
        assert (project_root / "docs" / "notiz.md").exists()

    @patch("elder_berry.comms.claude_agent.ClaudeAgent._get_client")
    def test_disallowed_action_rejected(self, mock_get_client, agent):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(
            "shell_exec",
            params={"cmd": "rm -rf /"},
            summary="Böse",
        )
        mock_get_client.return_value = mock_client

        result = agent.process("Lösch alles")
        assert result.success is False
        assert "nicht erlaubt" in result.summary

    @patch("elder_berry.comms.claude_agent.ClaudeAgent._get_client")
    def test_api_error_handled(self, mock_get_client, agent):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API down")
        mock_get_client.return_value = mock_client

        result = agent.process("Test")
        assert result.success is False
        assert "API Fehler" in result.summary

    @patch("elder_berry.comms.claude_agent.ClaudeAgent._get_client")
    def test_invalid_json_fallback_answer_only(self, mock_get_client, agent):
        """Wenn Claude kein JSON zurückgibt, wird der Rohtext als answer_only behandelt."""
        mock_block = MagicMock()
        mock_block.text = "Ich bin mir nicht sicher, lass mich nachfragen."
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = agent.process("Hmm?")
        assert result.success is True
        assert result.action_taken == "answer_only"
        assert "nicht sicher" in result.summary

    @patch("elder_berry.comms.claude_agent.ClaudeAgent._get_client")
    def test_empty_api_response(self, mock_get_client, agent):
        mock_block = MagicMock()
        mock_block.text = ""
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = agent.process("Test")
        assert result.success is False
        assert "Leere Antwort" in result.summary

    @patch("elder_berry.comms.claude_agent.ClaudeAgent._get_client")
    def test_append_journal(self, mock_get_client, agent, project_root):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(
            "append_file",
            params={"path": "docs/journal.txt", "content": "## Test-Eintrag"},
            summary="Journal aktualisiert",
        )
        mock_get_client.return_value = mock_client

        result = agent.process("Dokumentiere Test im Journal")
        assert result.success is True
        content = (project_root / "docs" / "journal.txt").read_text(encoding="utf-8")
        assert "Test-Eintrag" in content

    @patch("elder_berry.comms.claude_agent.ClaudeAgent._get_client")
    def test_list_directory_action(self, mock_get_client, agent):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(
            "list_directory",
            params={"path": "docs"},
            summary="Verzeichnis aufgelistet",
        )
        mock_get_client.return_value = mock_client

        result = agent.process("Zeig mir den docs Ordner")
        assert result.success is True
        assert "journal.txt" in result.details


# ---------------------------------------------------------------------------
# Import-Fehler (anthropic nicht installiert)
# ---------------------------------------------------------------------------


class TestImportError:
    def test_anthropic_not_installed(self, project_root):
        agent = ClaudeAgent(api_key="test", project_root=project_root)
        agent._client = None  # Reset

        with patch.dict("sys.modules", {"anthropic": None}):
            result = agent.process("Test")
            assert result.success is False
            assert (
                "anthropic" in result.summary.lower()
                or "nicht installiert" in result.summary
            )
