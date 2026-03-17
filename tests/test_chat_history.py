"""Tests: ChatHistory – Kurzzeit-Konversationsgedächtnis pro User."""
import time

import pytest

from elder_berry.comms.chat_history import ChatHistory, ChatMessage


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
# ChatHistory
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
        assert "Bisheriger Gesprächsverlauf:" in result
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
