"""Tests für Memory-System: MemoryEntry, MemoryContext, EmbeddingClient, ChromaMemoryStore."""
import importlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.memory.base import MemoryContext, MemoryEntry, MemoryStore
from elder_berry.memory.embedding import EmbeddingClient, OllamaEmbeddingClient

_chroma_installed = importlib.util.find_spec("chromadb") is not None
requires_chroma = pytest.mark.skipif(
    not _chroma_installed, reason="chromadb-Paket nicht installiert"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_entry(
    role: str = "user",
    content: str = "Hallo",
    session_id: str = "s1",
    ts: datetime | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        id="test-id",
        role=role,
        content=content,
        timestamp=ts or datetime.now(timezone.utc),
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# MemoryEntry
# ---------------------------------------------------------------------------

class TestMemoryEntry:
    def test_create_generates_id(self):
        entry = MemoryEntry.create("user", "Hallo", "s1")
        assert len(entry.id) > 0

    def test_create_sets_timestamp(self):
        before = datetime.now(timezone.utc)
        entry = MemoryEntry.create("user", "Hallo", "s1")
        after = datetime.now(timezone.utc)
        assert before <= entry.timestamp <= after

    def test_create_unique_ids(self):
        e1 = MemoryEntry.create("user", "a", "s1")
        e2 = MemoryEntry.create("user", "b", "s1")
        assert e1.id != e2.id

    def test_frozen(self):
        entry = make_entry()
        with pytest.raises((AttributeError, TypeError)):
            entry.role = "assistant"  # type: ignore[misc]

    def test_metadata_defaults_empty(self):
        entry = MemoryEntry.create("user", "Hallo", "s1")
        assert entry.metadata == {}

    def test_create_with_metadata(self):
        entry = MemoryEntry.create("assistant", "Hi", "s1", metadata={"emotion": "cheerful"})
        assert entry.metadata["emotion"] == "cheerful"


# ---------------------------------------------------------------------------
# MemoryContext
# ---------------------------------------------------------------------------

class TestMemoryContext:
    def test_is_empty_both_empty(self):
        ctx = MemoryContext(recent=[], relevant=[])
        assert ctx.is_empty() is True

    def test_is_empty_with_recent(self):
        ctx = MemoryContext(recent=[make_entry()], relevant=[])
        assert ctx.is_empty() is False

    def test_to_prompt_text_empty(self):
        ctx = MemoryContext(recent=[], relevant=[])
        assert ctx.to_prompt_text() == ""

    def test_to_prompt_text_recent(self):
        entry = make_entry(role="user", content="Was ist das Wetter?")
        ctx = MemoryContext(recent=[entry], relevant=[])
        text = ctx.to_prompt_text()
        assert "Letzte Nachrichten" in text
        assert "Was ist das Wetter?" in text
        assert "user" in text

    def test_to_prompt_text_relevant(self):
        recent = make_entry(content="Aktuelle Frage", session_id="s2")
        relevant = make_entry(content="Frühere Erinnerung", session_id="s1")
        # Verschiedene IDs damit relevant nicht gefiltert wird
        relevant = MemoryEntry(
            id="other-id", role="user", content="Frühere Erinnerung",
            timestamp=relevant.timestamp, session_id="s1"
        )
        ctx = MemoryContext(recent=[recent], relevant=[relevant])
        text = ctx.to_prompt_text()
        assert "Relevante Erinnerungen" in text
        assert "Frühere Erinnerung" in text

    def test_to_prompt_text_deduplicates(self):
        """Einträge die schon in recent sind, nicht nochmal in relevant."""
        entry = make_entry(content="Doppelt")
        ctx = MemoryContext(recent=[entry], relevant=[entry])
        text = ctx.to_prompt_text()
        assert text.count("Doppelt") == 1

    def test_to_prompt_text_respects_max_chars(self):
        entry = make_entry(content="x" * 1000)
        ctx = MemoryContext(recent=[entry], relevant=[])
        text = ctx.to_prompt_text(max_chars=100)
        assert len(text) <= 100


# ---------------------------------------------------------------------------
# OllamaEmbeddingClient
# ---------------------------------------------------------------------------

class TestOllamaEmbeddingClient:
    def test_is_available_true(self):
        client = OllamaEmbeddingClient()
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            assert client.is_available() is True

    def test_is_available_false_on_error(self):
        import httpx
        client = OllamaEmbeddingClient()
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            assert client.is_available() is False

    def test_embed_returns_vector(self):
        client = OllamaEmbeddingClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
        with patch("httpx.post", return_value=mock_resp):
            result = client.embed("Hallo Welt")
        assert result == [0.1, 0.2, 0.3]

    def test_embed_truncates_long_text(self):
        client = OllamaEmbeddingClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embeddings": [[0.1]]}
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.embed("a" * 10000)
        call_json = mock_post.call_args.kwargs["json"]
        assert len(call_json["input"]) == 8000

    def test_embed_raises_on_http_error(self):
        import httpx
        client = OllamaEmbeddingClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RuntimeError, match="Ollama nicht erreichbar"):
                client.embed("test")


# ---------------------------------------------------------------------------
# ChromaMemoryStore – mit Mock-Collection
# ---------------------------------------------------------------------------

@requires_chroma
class TestChromaMemoryStore:
    """Tests für ChromaMemoryStore mit gemockter ChromaDB-Collection."""

    def _make_store_with_mock(self, tmp_path: Path):
        """Erstellt einen ChromaMemoryStore mit gemockter Collection."""
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        store = ChromaMemoryStore(db_path=tmp_path)
        mock_col = MagicMock()
        store._collection = mock_col
        return store, mock_col

    def test_init_requires_chromadb(self):
        """Import-Fehler wenn chromadb nicht installiert."""
        from elder_berry.memory.chroma_memory import ChromaMemoryStore, _CHROMA_AVAILABLE
        assert _CHROMA_AVAILABLE is True  # Sonst wäre der Test geskippt

    def test_new_session_returns_uuid(self, tmp_path):
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        store = ChromaMemoryStore(db_path=tmp_path)
        sid = store.new_session()
        assert len(sid) == 36  # UUID4-Format

    def test_new_session_unique(self, tmp_path):
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        store = ChromaMemoryStore(db_path=tmp_path)
        assert store.new_session() != store.new_session()

    def test_add_calls_collection(self, tmp_path):
        store, mock_col = self._make_store_with_mock(tmp_path)
        entry = MemoryEntry.create("user", "Hallo", "s1")
        store.add(entry)
        mock_col.add.assert_called_once()
        call_kwargs = mock_col.add.call_args.kwargs
        assert call_kwargs["ids"] == [entry.id]
        assert call_kwargs["documents"] == [entry.content]
        assert call_kwargs["metadatas"][0]["role"] == "user"
        assert call_kwargs["metadatas"][0]["session_id"] == "s1"

    def test_add_stores_timestamp(self, tmp_path):
        store, mock_col = self._make_store_with_mock(tmp_path)
        entry = MemoryEntry.create("user", "Hallo", "s1")
        store.add(entry)
        meta = mock_col.add.call_args.kwargs["metadatas"][0]
        assert "timestamp_iso" in meta
        assert "timestamp_unix" in meta

    def test_get_recent_returns_entries_sorted(self, tmp_path):
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        store = ChromaMemoryStore(db_path=tmp_path)
        mock_col = MagicMock()
        store._collection = mock_col

        ts1 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc)

        mock_col.get.return_value = {
            "ids": ["id2", "id1"],
            "documents": ["Zweite", "Erste"],
            "metadatas": [
                {"role": "user", "session_id": "s1", "timestamp_iso": ts2.isoformat(), "timestamp_unix": ts2.timestamp()},
                {"role": "user", "session_id": "s1", "timestamp_iso": ts1.isoformat(), "timestamp_unix": ts1.timestamp()},
            ],
        }

        entries = store.get_recent(n=10)
        assert len(entries) == 2
        # Älteste zuerst (ts1 < ts2)
        assert entries[0].content == "Erste"
        assert entries[1].content == "Zweite"

    def test_get_recent_limits_results(self, tmp_path):
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        store = ChromaMemoryStore(db_path=tmp_path)
        mock_col = MagicMock()
        store._collection = mock_col

        # 5 Einträge, aber n=2
        ts_base = datetime(2026, 3, 1, tzinfo=timezone.utc)
        mock_col.get.return_value = {
            "ids": [f"id{i}" for i in range(5)],
            "documents": [f"Nachricht {i}" for i in range(5)],
            "metadatas": [
                {
                    "role": "user", "session_id": "s1",
                    "timestamp_iso": ts_base.replace(hour=i).isoformat(),
                    "timestamp_unix": ts_base.replace(hour=i).timestamp(),
                }
                for i in range(5)
            ],
        }

        entries = store.get_recent(n=2)
        assert len(entries) == 2
        # Letzten 2 (Stunde 3 und 4)
        assert "3" in entries[0].content or "4" in entries[0].content

    def test_get_recent_with_session_filter(self, tmp_path):
        store, mock_col = self._make_store_with_mock(tmp_path)
        mock_col.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        store.get_recent(n=5, session_id="s42")
        call_kwargs = mock_col.get.call_args.kwargs
        assert call_kwargs.get("where") == {"session_id": "s42"}

    def test_search_returns_empty_when_collection_empty(self, tmp_path):
        store, mock_col = self._make_store_with_mock(tmp_path)
        mock_col.count.return_value = 0
        result = store.search("test")
        assert result == []

    def test_search_calls_query(self, tmp_path):
        store, mock_col = self._make_store_with_mock(tmp_path)
        mock_col.count.return_value = 10
        ts = datetime(2026, 3, 1, tzinfo=timezone.utc)
        mock_col.query.return_value = {
            "ids": [["id1"]],
            "documents": [["Relevante Erinnerung"]],
            "metadatas": [[{
                "role": "user", "session_id": "s1",
                "timestamp_iso": ts.isoformat(), "timestamp_unix": ts.timestamp(),
            }]],
            "distances": [[0.1]],
        }

        entries = store.search("Suche nach etwas", k=3)
        mock_col.query.assert_called_once()
        assert len(entries) == 1
        assert entries[0].content == "Relevante Erinnerung"

    def test_clear_deletes_all(self, tmp_path):
        store, mock_col = self._make_store_with_mock(tmp_path)
        mock_col.get.return_value = {"ids": ["id1", "id2"]}
        store.clear()
        mock_col.delete.assert_called_once_with(ids=["id1", "id2"])

    def test_clear_empty_collection(self, tmp_path):
        store, mock_col = self._make_store_with_mock(tmp_path)
        mock_col.get.return_value = {"ids": []}
        store.clear()
        mock_col.delete.assert_not_called()

    def test_validate_dimension_match_ok(self, tmp_path):
        """Kein Fehler wenn Probe-Dimension mit Collection übereinstimmt."""
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        mock_embed = MagicMock()
        mock_embed.embed.return_value = [0.1] * 768
        store = ChromaMemoryStore(db_path=tmp_path, embedding_client=mock_embed)
        mock_col = MagicMock()
        mock_col.count.return_value = 5
        mock_col.peek.return_value = {"embeddings": [[0.2] * 768]}
        store._collection = mock_col
        # Sollte keinen Fehler werfen
        store._validate_embedding_dimension()

    def test_validate_dimension_mismatch_raises(self, tmp_path):
        """RuntimeError wenn Probe-Dimension nicht zur Collection passt."""
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        mock_embed = MagicMock()
        mock_embed.embed.return_value = [0.1] * 384  # falsches Modell
        store = ChromaMemoryStore(db_path=tmp_path, embedding_client=mock_embed)
        mock_col = MagicMock()
        mock_col.count.return_value = 5
        mock_col.peek.return_value = {"embeddings": [[0.2] * 768]}
        store._collection = mock_col
        with pytest.raises(RuntimeError, match="Embedding-Dimension Mismatch"):
            store._validate_embedding_dimension()

    def test_validate_dimension_skips_empty_collection(self, tmp_path):
        """Kein Check wenn Collection leer ist."""
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        mock_embed = MagicMock()
        store = ChromaMemoryStore(db_path=tmp_path, embedding_client=mock_embed)
        mock_col = MagicMock()
        mock_col.count.return_value = 0
        store._collection = mock_col
        # Sollte keinen Fehler werfen und embed() nicht aufrufen
        store._validate_embedding_dimension()
        mock_embed.embed.assert_not_called()

    def test_validate_dimension_skips_without_client(self, tmp_path):
        """Kein Check wenn kein EmbeddingClient gesetzt."""
        from elder_berry.memory.chroma_memory import ChromaMemoryStore
        store = ChromaMemoryStore(db_path=tmp_path, embedding_client=None)
        mock_col = MagicMock()
        mock_col.count.return_value = 5
        store._collection = mock_col
        # Sollte keinen Fehler werfen
        store._validate_embedding_dimension()
        mock_col.peek.assert_not_called()


# ---------------------------------------------------------------------------
# Assistant + Memory Integration
# ---------------------------------------------------------------------------

class TestAssistantMemory:
    """Testet dass Assistant Memory korrekt nutzt."""

    def _make_assistant(self, memory=None):
        from elder_berry.actions.db import ActionsDB
        from elder_berry.core.assistant import Assistant

        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"action": null, "params": {}, "response": "Hallo!"}'
        mock_db = MagicMock(spec=ActionsDB)
        mock_db.list_all.return_value = []
        mock_controller = MagicMock()

        return Assistant(
            llm=mock_llm,
            actions_db=mock_db,
            controller=mock_controller,
            memory=memory,
        )

    def test_without_memory_works(self):
        assistant = self._make_assistant(memory=None)
        result = assistant.process("Hallo")
        assert result.response == "Hallo!"

    def test_with_memory_saves_entries(self):
        mock_memory = MagicMock()
        mock_memory.new_session.return_value = "test-session"
        mock_memory.get_context.return_value = MemoryContext(recent=[], relevant=[])
        assistant = self._make_assistant(memory=mock_memory)
        assistant.process("Hallo")
        # add() sollte 2x aufgerufen worden sein (user + assistant)
        assert mock_memory.add.call_count == 2

    def test_memory_context_in_prompt(self):
        mock_memory = MagicMock()
        mock_memory.new_session.return_value = "s1"
        entry = make_entry(content="Ältere Erinnerung", session_id="s0")
        mock_memory.get_context.return_value = MemoryContext(recent=[entry], relevant=[])

        mock_llm = MagicMock()
        captured_prompts = []
        def capture_generate(prompt, system=""):
            captured_prompts.append(system)
            return '{"action": null, "params": {}, "response": "ok"}'
        mock_llm.generate.side_effect = capture_generate

        from elder_berry.actions.db import ActionsDB
        from elder_berry.core.assistant import Assistant
        mock_db = MagicMock(spec=ActionsDB)
        mock_db.list_all.return_value = []
        assistant = Assistant(
            llm=mock_llm,
            actions_db=mock_db,
            controller=MagicMock(),
            memory=mock_memory,
        )
        assistant.process("Neue Frage")
        assert len(captured_prompts) == 1
        assert "Ältere Erinnerung" in captured_prompts[0]

    def test_new_session_resets_session_id(self):
        mock_memory = MagicMock()
        mock_memory.new_session.side_effect = ["s1", "s2"]
        assistant = self._make_assistant(memory=mock_memory)
        old_sid = assistant._session_id
        assistant.new_session()
        assert assistant._session_id != old_sid

    def test_memory_error_does_not_crash_assistant(self):
        mock_memory = MagicMock()
        mock_memory.new_session.return_value = "s1"
        mock_memory.get_context.side_effect = RuntimeError("DB kaputt")
        mock_memory.add.side_effect = RuntimeError("DB kaputt")
        assistant = self._make_assistant(memory=mock_memory)
        # Kein Crash trotz Fehler
        result = assistant.process("Hallo")
        assert result.response == "Hallo!"
