"""Tests: ChatHistory – Kurzzeit-Konversationsgedächtnis pro User.

Inkl. Rolling Summary (Phase 23).
"""
import time

import pytest

from elder_berry.comms.chat_history import (
    ChatHistory,
    ChatMessage,
    EVICTION_BATCH_SIZE,
)


# ---------------------------------------------------------------------------
# ChatMessage DTO
# ---------------------------------------------------------------------------

class TestChatMessage:
    def test_frozen(self):
        msg = ChatMessage(role="user", text="Hallo", timestamp=1.0)
        with pytest.raises(AttributeError):
            msg.text = "Welt"

    def test_fields(self):
        msg = ChatMessage(role="assistant", text="Hi", timestamp=42.0)
        assert msg.role == "assistant"
        assert msg.text == "Hi"
        assert msg.timestamp == 42.0


# ---------------------------------------------------------------------------
# ChatHistory – Basis
# ---------------------------------------------------------------------------

class TestChatHistoryBasic:
    def test_empty_history(self):
        history = ChatHistory()
        assert history.get("@user:matrix.org") == []

    def test_add_and_get(self):
        history = ChatHistory()
        history.add("@user:matrix.org", "user", "Hallo")
        history.add("@user:matrix.org", "assistant", "Hi!")

        msgs = history.get("@user:matrix.org")
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].text == "Hallo"
        assert msgs[1].role == "assistant"
        assert msgs[1].text == "Hi!"

    def test_add_strips_whitespace(self):
        history = ChatHistory()
        history.add("@u:m", "user", "  Hallo  ")
        msgs = history.get("@u:m")
        assert msgs[0].text == "Hallo"

    def test_add_ignores_empty(self):
        history = ChatHistory()
        history.add("@u:m", "user", "")
        history.add("@u:m", "user", "   ")
        history.add("@u:m", "user", None)
        assert history.get("@u:m") == []

    def test_timestamp_set(self):
        before = time.time()
        history = ChatHistory()
        history.add("@u:m", "user", "Test")
        after = time.time()

        msg = history.get("@u:m")[0]
        assert before <= msg.timestamp <= after

    def test_max_messages_property(self):
        history = ChatHistory(max_messages=5)
        assert history.max_messages == 5


class TestChatHistorySlidingWindow:
    def test_sliding_window(self):
        history = ChatHistory(max_messages=3)
        history.add("@u:m", "user", "Msg 1")
        history.add("@u:m", "assistant", "Resp 1")
        history.add("@u:m", "user", "Msg 2")
        history.add("@u:m", "assistant", "Resp 2")  # 4th, oldest removed

        msgs = history.get("@u:m")
        assert len(msgs) == 3
        # Älteste (Msg 1) ist weg
        assert msgs[0].text == "Resp 1"
        assert msgs[1].text == "Msg 2"
        assert msgs[2].text == "Resp 2"

    def test_sliding_window_exact_limit(self):
        history = ChatHistory(max_messages=2)
        history.add("@u:m", "user", "A")
        history.add("@u:m", "user", "B")
        assert len(history.get("@u:m")) == 2

        history.add("@u:m", "user", "C")
        msgs = history.get("@u:m")
        assert len(msgs) == 2
        assert msgs[0].text == "B"
        assert msgs[1].text == "C"


class TestChatHistoryMultiUser:
    def test_separate_histories(self):
        history = ChatHistory()
        history.add("@alice:m", "user", "Alice msg")
        history.add("@bob:m", "user", "Bob msg")

        assert len(history.get("@alice:m")) == 1
        assert len(history.get("@bob:m")) == 1
        assert history.get("@alice:m")[0].text == "Alice msg"
        assert history.get("@bob:m")[0].text == "Bob msg"

    def test_clear_single_user(self):
        history = ChatHistory()
        history.add("@alice:m", "user", "Msg")
        history.add("@bob:m", "user", "Msg")

        history.clear("@alice:m")
        assert history.get("@alice:m") == []
        assert len(history.get("@bob:m")) == 1

    def test_clear_all(self):
        history = ChatHistory()
        history.add("@alice:m", "user", "Msg")
        history.add("@bob:m", "user", "Msg")

        history.clear()
        assert history.get("@alice:m") == []
        assert history.get("@bob:m") == []

    def test_clear_nonexistent_user(self):
        history = ChatHistory()
        history.clear("@nobody:m")  # Kein Fehler


class TestChatHistoryFormat:
    def test_format_empty(self):
        history = ChatHistory()
        assert history.format_for_prompt("@u:m") == ""

    def test_format_basic(self):
        history = ChatHistory()
        history.add("@u:m", "user", "Suche mail von RK Bedachung")
        history.add("@u:m", "assistant", "3 Mails gefunden: ...")

        result = history.format_for_prompt("@u:m")
        assert "Letzte Nachrichten:" in result
        assert "User: Suche mail von RK Bedachung" in result
        assert "Saleria: 3 Mails gefunden" in result

    def test_format_long_text_truncated(self):
        history = ChatHistory()
        long_text = "x" * 600
        history.add("@u:m", "assistant", long_text)

        result = history.format_for_prompt("@u:m")
        assert "... (gekürzt)" in result
        assert len(result) < 700

    def test_format_only_target_user(self):
        history = ChatHistory()
        history.add("@alice:m", "user", "Alice msg")
        history.add("@bob:m", "user", "Bob msg")

        result = history.format_for_prompt("@alice:m")
        assert "Alice msg" in result
        assert "Bob msg" not in result

    def test_get_returns_copy(self):
        """get() gibt eine Kopie zurück, Änderungen beeinflussen nicht das Original."""
        history = ChatHistory()
        history.add("@u:m", "user", "Test")

        msgs = history.get("@u:m")
        msgs.clear()

        assert len(history.get("@u:m")) == 1


# ---------------------------------------------------------------------------
# Rolling Summary (Phase 23)
# ---------------------------------------------------------------------------

def _sync_summarizer(old_summary: str, evicted: list[ChatMessage]) -> str:
    """Test-Summarizer: gibt deterministisches Ergebnis zurück."""
    evicted_texts = [m.text for m in evicted]
    parts = []
    if old_summary:
        parts.append(f"Vorher: {old_summary}")
    parts.append(f"Evicted: {', '.join(evicted_texts)}")
    return " | ".join(parts)


class TestRollingSummaryTrigger:
    """Tests: Wann wird der Summarizer aufgerufen?"""

    def test_no_summary_without_summarizer(self):
        """Ohne Summarizer: kein Summary, auch wenn Nachrichten evicted werden."""
        history = ChatHistory(max_messages=2)
        for i in range(10):
            history.add("@u:m", "user", f"Msg {i}")
        assert history.get_summary("@u:m") == ""

    def test_no_summary_before_eviction(self):
        """Vor Eviction: kein Summary."""
        history = ChatHistory(max_messages=10, summarizer=_sync_summarizer)
        history.add("@u:m", "user", "Msg 1")
        assert history.get_summary("@u:m") == ""

    def test_summary_after_batch_eviction(self):
        """Summary wird erst nach EVICTION_BATCH_SIZE evicted Messages erstellt."""
        history = ChatHistory(max_messages=3, summarizer=_sync_summarizer)
        sender = "@u:m"

        # 3 Messages füllen das Window
        history.add(sender, "user", "Msg 1")
        history.add(sender, "assistant", "Resp 1")
        history.add(sender, "user", "Msg 2")
        assert history.get_summary(sender) == ""

        # Nächste Messages evicten, aber noch unter Batch-Grenze
        for i in range(EVICTION_BATCH_SIZE - 1):
            history.add(sender, "assistant", f"Fill {i}")
        # Eviction-Buffer hat BATCH_SIZE-1 Einträge → noch kein Summary

        # Eine weitere Message → Batch voll → Summary wird getriggert
        history.add(sender, "user", "Trigger")

        # Background-Thread kurz abwarten
        time.sleep(0.2)

        summary = history.get_summary(sender)
        assert summary != ""
        assert "Msg 1" in summary

    def test_summary_updates_rolling(self):
        """Summary wird bei jedem vollen Batch aktualisiert."""
        history = ChatHistory(max_messages=2, summarizer=_sync_summarizer)
        sender = "@u:m"

        # Window = 2, EVICTION_BATCH_SIZE = 3
        # Wir brauchen 2 + 3 = 5 Messages für ersten Summary
        for i in range(5):
            history.add(sender, "user", f"Msg {i}")
        time.sleep(0.2)

        first_summary = history.get_summary(sender)
        assert first_summary != ""

        # 3 weitere evicten → zweiter Summary-Update
        for i in range(3):
            history.add(sender, "user", f"Second {i}")
        time.sleep(0.2)

        second_summary = history.get_summary(sender)
        assert second_summary != first_summary
        assert "Vorher:" in second_summary  # Enthält alten Summary


class TestRollingSummaryFormat:
    """Tests: Wie wird die Summary im Prompt formatiert?"""

    def test_format_with_summary(self):
        """format_for_prompt() zeigt Summary + letzte Nachrichten."""
        history = ChatHistory(max_messages=2, summarizer=_sync_summarizer)
        sender = "@u:m"

        # Genug Messages für Summary
        for i in range(2 + EVICTION_BATCH_SIZE):
            history.add(sender, "user", f"Msg {i}")
        time.sleep(0.2)

        result = history.format_for_prompt(sender)
        assert "Zusammenfassung bisheriges Gespräch:" in result
        assert "Letzte Nachrichten:" in result

    def test_format_without_summary(self):
        """Ohne Summary: nur 'Letzte Nachrichten:' Header."""
        history = ChatHistory(max_messages=10, summarizer=_sync_summarizer)
        history.add("@u:m", "user", "Hallo")

        result = history.format_for_prompt("@u:m")
        assert "Zusammenfassung" not in result
        assert "Letzte Nachrichten:" in result

    def test_format_summary_before_messages(self):
        """Summary kommt VOR den letzten Nachrichten."""
        history = ChatHistory(max_messages=2, summarizer=_sync_summarizer)
        sender = "@u:m"

        for i in range(2 + EVICTION_BATCH_SIZE):
            history.add(sender, "user", f"Msg {i}")
        time.sleep(0.2)

        result = history.format_for_prompt(sender)
        summary_pos = result.index("Zusammenfassung")
        messages_pos = result.index("Letzte Nachrichten:")
        assert summary_pos < messages_pos


class TestRollingSummaryClear:
    """Tests: Clear löscht auch Summary und Eviction-Buffer."""

    def test_clear_user_removes_summary(self):
        history = ChatHistory(max_messages=2, summarizer=_sync_summarizer)
        sender = "@u:m"

        for i in range(2 + EVICTION_BATCH_SIZE):
            history.add(sender, "user", f"Msg {i}")
        time.sleep(0.2)
        assert history.get_summary(sender) != ""

        history.clear(sender)
        assert history.get_summary(sender) == ""

    def test_clear_all_removes_summaries(self):
        history = ChatHistory(max_messages=2, summarizer=_sync_summarizer)

        for sender in ["@a:m", "@b:m"]:
            for i in range(2 + EVICTION_BATCH_SIZE):
                history.add(sender, "user", f"Msg {i}")
        time.sleep(0.2)

        history.clear()
        assert history.get_summary("@a:m") == ""
        assert history.get_summary("@b:m") == ""


class TestRollingSummaryMultiUser:
    """Tests: Summaries sind pro User getrennt."""

    def test_separate_summaries(self):
        history = ChatHistory(max_messages=2, summarizer=_sync_summarizer)

        for i in range(2 + EVICTION_BATCH_SIZE):
            history.add("@alice:m", "user", f"Alice {i}")
            history.add("@bob:m", "user", f"Bob {i}")
        time.sleep(0.2)

        alice_summary = history.get_summary("@alice:m")
        bob_summary = history.get_summary("@bob:m")

        assert "Alice" in alice_summary
        assert "Bob" not in alice_summary
        assert "Bob" in bob_summary
        assert "Alice" not in bob_summary


class TestRollingSummaryErrorHandling:
    """Tests: Summarizer-Fehler crashen nicht die ChatHistory."""

    def test_summarizer_exception_is_caught(self):
        def failing_summarizer(old: str, evicted: list[ChatMessage]) -> str:
            raise RuntimeError("LLM nicht verfügbar")

        history = ChatHistory(max_messages=2, summarizer=failing_summarizer)
        sender = "@u:m"

        # Sollte nicht crashen
        for i in range(2 + EVICTION_BATCH_SIZE):
            history.add(sender, "user", f"Msg {i}")
        time.sleep(0.2)

        # Kein Summary, aber kein Crash
        assert history.get_summary(sender) == ""
        # History funktioniert weiterhin
        assert len(history.get(sender)) == 2

    def test_summarizer_returns_empty(self):
        def empty_summarizer(old: str, evicted: list[ChatMessage]) -> str:
            return ""

        history = ChatHistory(max_messages=2, summarizer=empty_summarizer)
        sender = "@u:m"

        for i in range(2 + EVICTION_BATCH_SIZE):
            history.add(sender, "user", f"Msg {i}")
        time.sleep(0.2)

        assert history.get_summary(sender) == ""

    def test_summarizer_returns_none(self):
        def none_summarizer(old: str, evicted: list[ChatMessage]) -> str:
            return None

        history = ChatHistory(max_messages=2, summarizer=none_summarizer)
        sender = "@u:m"

        for i in range(2 + EVICTION_BATCH_SIZE):
            history.add(sender, "user", f"Msg {i}")
        time.sleep(0.2)

        assert history.get_summary(sender) == ""


class TestRollingSummaryBackwardCompat:
    """Tests: Rückwärtskompatibilität – altes Verhalten ohne Summarizer."""

    def test_no_summarizer_default(self):
        """ChatHistory ohne Summarizer verhält sich wie vorher."""
        history = ChatHistory(max_messages=3)
        for i in range(5):
            history.add("@u:m", "user", f"Msg {i}")

        msgs = history.get("@u:m")
        assert len(msgs) == 3
        assert msgs[0].text == "Msg 2"

        result = history.format_for_prompt("@u:m")
        assert "Zusammenfassung" not in result
        assert "Letzte Nachrichten:" in result

    def test_format_header_changed(self):
        """Header ist jetzt 'Letzte Nachrichten:' statt 'Bisheriger Gesprächsverlauf:'."""
        history = ChatHistory()
        history.add("@u:m", "user", "Test")
        result = history.format_for_prompt("@u:m")
        assert "Letzte Nachrichten:" in result
