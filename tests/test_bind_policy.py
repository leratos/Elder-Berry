"""Tests fuer Phase 103 (S1): elder_berry.core.bind_policy.

Die fail-closed-Bind-Policy lebt seit Phase 103 zentral im Package (vorher nur
in scripts/start_rpi5.py). Hier die kanonischen Unit-Tests; die RPi-Wrapper
werden zusaetzlich von tests/test_start_rpi5_token.py abgedeckt
(Re-Export-Vertrag).
"""

from __future__ import annotations

import logging

import pytest

from elder_berry.core import bind_policy


class TestIsLoopbackHost:
    @pytest.mark.parametrize(
        "host",
        ["localhost", "LOCALHOST", "127.0.0.1", "127.1.2.3", "::1", "[::1]"],
    )
    def test_loopback_hosts(self, host):
        assert bind_policy.is_loopback_host(host) is True

    @pytest.mark.parametrize(
        "host",
        ["0.0.0.0", "::", "192.168.1.42", "8.8.8.8", "not-an-ip", ""],
    )
    def test_non_loopback_hosts(self, host):
        assert bind_policy.is_loopback_host(host) is False


_LOG = logging.getLogger("test.bind_policy")


def _enforce(token, host, caplog=None):
    bind_policy.enforce_token_policy(
        token,
        host,
        token_env_name="ELDER_BERRY_ROBOT_TOKEN",
        server_label="Robot",
        logger=_LOG,
    )


class TestEnforceTokenPolicy:
    def test_token_set_non_loopback_ok(self):
        _enforce("abc123", "0.0.0.0")  # kein Abbruch

    def test_token_set_loopback_ok(self):
        _enforce("abc123", "127.0.0.1")

    def test_no_token_loopback_warns_but_passes(self, caplog):
        with caplog.at_level(logging.WARNING, logger="test.bind_policy"):
            _enforce(None, "127.0.0.1")
        assert any("NICHT konfiguriert" in r.message for r in caplog.records)

    def test_no_token_localhost_passes(self):
        _enforce(None, "localhost")

    def test_no_token_non_loopback_exits_code_2(self):
        with pytest.raises(SystemExit) as exc:
            _enforce(None, "0.0.0.0")
        assert exc.value.code == 2

    def test_no_token_lan_exits_code_2(self):
        with pytest.raises(SystemExit) as exc:
            _enforce(None, "192.168.1.42")
        assert exc.value.code == 2

    def test_error_log_names_env_and_loopback(self, caplog):
        with caplog.at_level(logging.ERROR, logger="test.bind_policy"):
            with pytest.raises(SystemExit):
                _enforce(None, "10.0.0.1")
        errors = " ".join(
            r.message for r in caplog.records if r.levelname == "ERROR"
        )
        assert "ELDER_BERRY_ROBOT_TOKEN" in errors
        assert "127.0.0.1" in errors

    def test_empty_token_treated_as_none(self):
        with pytest.raises(SystemExit):
            _enforce("", "0.0.0.0")
