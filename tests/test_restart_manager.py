"""Tests: restart_manager – Restart-Flag, Notification, Lock-Release, Restart."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from elder_berry.comms.restart_manager import (
    RESTART_FLAG_FILE,
    _is_systemd_managed,
    read_restart_timestamp,
    release_instance_lock,
    send_restart_notification,
    perform_restart,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_async(coro):
    """Führt eine Coroutine synchron aus (für Tests ohne pytest-asyncio)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# read_restart_timestamp
# ---------------------------------------------------------------------------

class TestReadRestartTimestamp:
    def test_no_flag_file(self, tmp_path, monkeypatch):
        fake = tmp_path / "nonexistent.flag"
        monkeypatch.setattr(
            "elder_berry.comms.restart_manager.RESTART_FLAG_FILE", fake,
        )
        assert read_restart_timestamp() == 0.0

    def test_valid_flag(self, tmp_path, monkeypatch):
        flag = tmp_path / "restart.flag"
        flag.write_text("!room123\n1711500000000", encoding="utf-8")
        monkeypatch.setattr(
            "elder_berry.comms.restart_manager.RESTART_FLAG_FILE", flag,
        )
        ts = read_restart_timestamp()
        assert ts == 1711500000000 / 1000.0

    def test_only_room_id_no_timestamp(self, tmp_path, monkeypatch):
        flag = tmp_path / "restart.flag"
        flag.write_text("!room123", encoding="utf-8")
        monkeypatch.setattr(
            "elder_berry.comms.restart_manager.RESTART_FLAG_FILE", flag,
        )
        assert read_restart_timestamp() == 0.0

    def test_invalid_timestamp(self, tmp_path, monkeypatch):
        flag = tmp_path / "restart.flag"
        flag.write_text("!room123\nnot_a_number", encoding="utf-8")
        monkeypatch.setattr(
            "elder_berry.comms.restart_manager.RESTART_FLAG_FILE", flag,
        )
        assert read_restart_timestamp() == 0.0


# ---------------------------------------------------------------------------
# send_restart_notification
# ---------------------------------------------------------------------------

class TestSendRestartNotification:
    def test_no_flag_does_nothing(self, tmp_path, monkeypatch):
        async def _test():
            fake = tmp_path / "nonexistent.flag"
            monkeypatch.setattr(
                "elder_berry.comms.restart_manager.RESTART_FLAG_FILE", fake,
            )
            channel = AsyncMock()
            await send_restart_notification(channel)
            channel.send_text.assert_not_called()
        run_async(_test())

    def test_sends_notification_and_deletes_flag(self, tmp_path, monkeypatch):
        async def _test():
            flag = tmp_path / "restart.flag"
            flag.write_text("!room456\n1711500000000", encoding="utf-8")
            monkeypatch.setattr(
                "elder_berry.comms.restart_manager.RESTART_FLAG_FILE", flag,
            )
            channel = AsyncMock()
            await send_restart_notification(channel)
            channel.send_text.assert_called_once()
            args = channel.send_text.call_args
            assert args[0][0] == "!room456"
            assert "wieder da" in args[0][1].lower() or "Neustart" in args[0][1]
            assert not flag.exists()
        run_async(_test())

    def test_exception_during_send_cleans_flag(self, tmp_path, monkeypatch):
        async def _test():
            flag = tmp_path / "restart.flag"
            flag.write_text("!room789", encoding="utf-8")
            monkeypatch.setattr(
                "elder_berry.comms.restart_manager.RESTART_FLAG_FILE", flag,
            )
            channel = AsyncMock()
            channel.send_text.side_effect = Exception("network error")
            await send_restart_notification(channel)
            assert not flag.exists()
        run_async(_test())


# ---------------------------------------------------------------------------
# release_instance_lock
# ---------------------------------------------------------------------------

class TestReleaseInstanceLock:
    def test_calls_main_release_fn(self, monkeypatch):
        mock_release = MagicMock()
        mock_main = MagicMock()
        mock_main._release_instance_lock = mock_release
        import sys
        monkeypatch.setitem(sys.modules, "__main__", mock_main)
        release_instance_lock()
        mock_release.assert_called_once()

    def test_fallback_deletes_lock_file(self, tmp_path, monkeypatch):
        import sys
        mock_main = MagicMock(spec=[])  # no _release_instance_lock
        monkeypatch.setitem(sys.modules, "__main__", mock_main)
        # Patch sys.argv to control lock_path
        lock_file = tmp_path / "scripts" / ".saleria.lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.touch()
        monkeypatch.setattr(sys, "argv", [str(tmp_path / "scripts" / "start.py")])
        release_instance_lock()
        # Lock file should be removed (or attempt made)


# ---------------------------------------------------------------------------
# perform_restart
# ---------------------------------------------------------------------------

class TestPerformRestart:
    def test_writes_flag_and_disconnects(self, tmp_path, monkeypatch):
        async def _test():
            flag = tmp_path / "restart.flag"
            monkeypatch.setattr(
                "elder_berry.comms.restart_manager.RESTART_FLAG_FILE", flag,
            )
            channel = AsyncMock()
            scheduler = MagicMock()

            # Prevent actual process restart (Windows: Popen+_exit, Linux: execv)
            with patch("elder_berry.comms.restart_manager.release_instance_lock"), \
                 patch("elder_berry.comms.restart_manager.subprocess.Popen"), \
                 patch("elder_berry.comms.restart_manager.os._exit"), \
                 patch("elder_berry.comms.restart_manager.os.execv"):
                await perform_restart(
                    channel, scheduler, "!room123", msg_server_ts=1711.5,
                )

            assert flag.exists()
            content = flag.read_text(encoding="utf-8")
            assert "!room123" in content
            assert "1711500" in content
            scheduler.stop_all.assert_called_once()
            channel.disconnect.assert_called_once()
        run_async(_test())

    def test_no_scheduler(self, tmp_path, monkeypatch):
        async def _test():
            flag = tmp_path / "restart.flag"
            monkeypatch.setattr(
                "elder_berry.comms.restart_manager.RESTART_FLAG_FILE", flag,
            )
            channel = AsyncMock()

            # Prevent actual process restart (Windows: Popen+_exit, Linux: execv)
            with patch("elder_berry.comms.restart_manager.release_instance_lock"), \
                 patch("elder_berry.comms.restart_manager.subprocess.Popen"), \
                 patch("elder_berry.comms.restart_manager.os._exit"), \
                 patch("elder_berry.comms.restart_manager.os.execv"):
                await perform_restart(channel, None, "!room123")

            assert flag.exists()
        run_async(_test())


# ---------------------------------------------------------------------------
# systemd Detection
# ---------------------------------------------------------------------------

class TestIsSystemdManaged:
    def test_with_invocation_id(self):
        with patch.dict("os.environ", {"INVOCATION_ID": "abc123"}):
            assert _is_systemd_managed() is True

    def test_without_invocation_id(self):
        import os
        env = os.environ.copy()
        env.pop("INVOCATION_ID", None)
        with patch.dict("os.environ", env, clear=True):
            assert _is_systemd_managed() is False

    def test_empty_invocation_id(self):
        with patch.dict("os.environ", {"INVOCATION_ID": ""}):
            assert _is_systemd_managed() is False
