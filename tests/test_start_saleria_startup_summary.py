"""Tests für Startup-Summary in scripts/start_saleria.py (#1418 E1, #1422 E2-neu).

- ``_init_productivity_services`` vermerkt Dienste, deren Startprüfung bei
  vollständigen Zugangsdaten fehlschlug, in ``probe_failed``.
- ``_build_startup_summary`` zeigt diese als "fail", alle anderen fehlenden
  Dienste unverändert als "warn"/"nicht konfiguriert".
- ``_hand_summary_to_bridge`` übergibt die Meldung an die Bridge statt sie
  vor ``bridge.start()`` selbst zu senden.
"""

from __future__ import annotations

import inspect
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from start_saleria import (  # noqa: E402
    _PROBE_FAILED_DETAIL,
    _build_startup_summary,
    _hand_summary_to_bridge,
    _init_productivity_services,
    run_matrix,
)

# Module, deren Klassen _init_productivity_services ohne Bedingung oder per
# Kalender-Fallback konstruiert. Ersetzt durch Fake-Module, damit der Test
# keine echten DBs anlegt und keine optionalen Libraries braucht.
_STUBBED_MODULES = {
    "elder_berry.tools.caldav_calendar": "CalDAVCalendarClient",
    "elder_berry.tools.google_calendar": "GoogleCalendarClient",
    "elder_berry.tools.contact_store": "ContactStore",
    "elder_berry.tools.caldav_tasks": "CalDAVTaskClient",
    "elder_berry.tools.weather_client": "WeatherClient",
    "elder_berry.tools.fact_store": "FactStore",
    "elder_berry.tools.reminder_store": "ReminderStore",
    "elder_berry.comms.reminder_scheduler": "ReminderScheduler",
    "elder_berry.comms.briefing_scheduler": "BriefingScheduler",
    "elder_berry.tools.email_client": "IMAPEmailClient",
    "elder_berry.tools.email_sender": "EmailSender",
    "elder_berry.tools.gym_data": "GymDataClient",
    "elder_berry.tools.nextcloud_notes_client": "NextcloudNotesClient",
    "elder_berry.tools.nextcloud_files": "NextcloudFilesClient",
    "elder_berry.tools.stirling_pdf": "StirlingPDFClient",
    "elder_berry.tools.carddav_sync": "CardDAVSyncClient",
}

# Probe-Dienste: (Modul, Klasse, svc-Schlüssel, Summary-Label, Konfig-Schlüssel, Log-Name)
_PROBED = [
    (
        "elder_berry.tools.nextcloud_files",
        "NextcloudFilesClient",
        "nextcloud_files",
        "Nextcloud Files",
        "nextcloud_url",
        "Nextcloud Files",
    ),
    (
        "elder_berry.tools.nextcloud_notes_client",
        "NextcloudNotesClient",
        "nextcloud_notes",
        "Notizen (Nextcloud)",
        "nextcloud_url",
        "Nextcloud Notes",
    ),
    (
        "elder_berry.tools.carddav_sync",
        "CardDAVSyncClient",
        "carddav_sync",
        "CardDAV-Sync",
        "nextcloud_url",
        "CardDAV Sync",
    ),
    (
        "elder_berry.tools.stirling_pdf",
        "StirlingPDFClient",
        "stirling_pdf",
        "Stirling-PDF",
        "stirling_pdf_url",
        "Stirling-PDF",
    ),
]


def _make_secrets(values: dict[str, str]) -> MagicMock:
    secrets = MagicMock()
    secrets.get_or_none.side_effect = values.get
    secrets.get.side_effect = values.__getitem__
    return secrets


def _fake_modules() -> dict[str, types.ModuleType]:
    """Je Modul ein Fake mit MagicMock-Klasse; Instanzen sind standardmäßig
    nicht verfügbar (Kalender/Fallbacks greifen damit nicht)."""
    mods = {}
    for mod_name, cls_name in _STUBBED_MODULES.items():
        mod = types.ModuleType(mod_name)
        cls = MagicMock(name=cls_name)
        cls.return_value.is_available.return_value = False
        setattr(mod, cls_name, cls)
        mods[mod_name] = mod
    return mods


def _client(available: bool, has_credentials: bool) -> MagicMock:
    inst = MagicMock()
    inst.is_available.return_value = available
    inst.has_credentials = has_credentials
    return inst


def _run_init(values: dict[str, str], mods: dict[str, types.ModuleType]):
    probe_failed: set[str] = set()
    with patch.dict(sys.modules, mods):
        svc = _init_productivity_services(
            _make_secrets(values), "@user:x", probe_failed=probe_failed
        )
    return svc, probe_failed


def _summary(svc, probe_failed):
    return _build_startup_summary(
        assistant=MagicMock(),
        stt=None,
        robot=None,
        robot_state="unreachable",
        secrets=MagicMock(),
        svc=svc,
        tools={},
        tower_agent=None,
        matrix_user_id="@bot:x",
        matrix_room_id="!room:x",
        allowed_senders=frozenset({"@user:x"}),
        claude_agent=None,
        probe_failed=probe_failed,
    )


def _entry(summary, label):
    matches = [e for e in summary.entries if e.component == label]
    assert len(matches) == 1, f"{label}: {matches}"
    return matches[0]


# ===========================================================================
# Probe-Dienste: Files / Notes / CardDAV / Stirling
# ===========================================================================


@pytest.mark.parametrize("mod_name,cls_name,svc_key,label,cfg_key,log_name", _PROBED)
class TestProbedServices:
    def test_probe_failed_with_credentials_is_fail(
        self, mod_name, cls_name, svc_key, label, cfg_key, log_name
    ):
        mods = _fake_modules()
        getattr(mods[mod_name], cls_name).return_value = _client(False, True)

        svc, probe_failed = _run_init({cfg_key: "https://x"}, mods)

        assert svc_key not in svc
        assert svc_key in probe_failed
        entry = _entry(_summary(svc, probe_failed), label)
        assert entry.status == "fail"
        assert entry.detail == _PROBE_FAILED_DETAIL
        assert "Startprüfung fehlgeschlagen" in entry.detail

    def test_incomplete_credentials_is_warn_and_logged(
        self, mod_name, cls_name, svc_key, label, cfg_key, log_name, caplog
    ):
        mods = _fake_modules()
        getattr(mods[mod_name], cls_name).return_value = _client(False, False)

        with caplog.at_level(logging.WARNING, logger="saleria"):
            svc, probe_failed = _run_init({cfg_key: "https://x"}, mods)

        assert svc_key not in probe_failed
        entry = _entry(_summary(svc, probe_failed), label)
        assert (entry.status, entry.detail) == ("warn", "nicht konfiguriert")
        messages = [r.getMessage() for r in caplog.records]
        assert f"{log_name}: Zugangsdaten unvollständig" in messages
        assert f"{log_name}: nicht erreichbar" not in messages

    def test_available_is_ok(
        self, mod_name, cls_name, svc_key, label, cfg_key, log_name
    ):
        mods = _fake_modules()
        inst = _client(True, True)
        getattr(mods[mod_name], cls_name).return_value = inst

        svc, probe_failed = _run_init({cfg_key: "https://x"}, mods)

        assert svc[svc_key] is inst
        assert svc_key not in probe_failed
        assert _entry(_summary(svc, probe_failed), label).status == "ok"

    def test_not_configured_is_warn(
        self, mod_name, cls_name, svc_key, label, cfg_key, log_name
    ):
        svc, probe_failed = _run_init({}, _fake_modules())

        assert svc_key not in probe_failed
        entry = _entry(_summary(svc, probe_failed), label)
        assert (entry.status, entry.detail) == ("warn", "nicht konfiguriert")


# ===========================================================================
# SMTP / IMAP / Berry-Gym
# ===========================================================================

_MAIL_CFG = {"email_imap_host": "imap.x", "email_user": "u"}


def _sender_cls(mods: dict[str, types.ModuleType]) -> MagicMock:
    return mods["elder_berry.tools.email_sender"].EmailSender


class TestSmtp:
    def test_sender_probe_failed_is_fail(self):
        mods = _fake_modules()
        sender = MagicMock()
        sender.is_available.return_value = False
        _sender_cls(mods).from_secret_store.return_value = sender

        svc, probe_failed = _run_init(_MAIL_CFG, mods)

        assert "email_client" in svc
        assert "email_sender" in probe_failed
        entry = _entry(_summary(svc, probe_failed), "E-Mail (SMTP)")
        assert (entry.status, entry.detail) == ("fail", _PROBE_FAILED_DETAIL)

    def test_imap_missing_smtp_is_warn(self):
        mods = _fake_modules()
        imap_cls = mods["elder_berry.tools.email_client"].IMAPEmailClient
        imap_cls.from_secret_store.side_effect = KeyError("email_password")

        svc, probe_failed = _run_init(_MAIL_CFG, mods)

        assert "email_sender" not in probe_failed
        _sender_cls(mods).from_secret_store.assert_not_called()
        summary = _summary(svc, probe_failed)
        smtp = _entry(summary, "E-Mail (SMTP)")
        assert (smtp.status, smtp.detail) == ("warn", "nicht konfiguriert")

    def test_sender_available_is_ok(self):
        mods = _fake_modules()
        sender = MagicMock()
        sender.is_available.return_value = True
        _sender_cls(mods).from_secret_store.return_value = sender

        svc, probe_failed = _run_init(_MAIL_CFG, mods)

        assert svc["email_sender"] is sender
        assert _entry(_summary(svc, probe_failed), "E-Mail (SMTP)").status == "ok"


class TestNoProbeServices:
    """IMAP und Berry-Gym haben keinen Start-Probe -> nie "fail"."""

    def test_imap_constructor_error_is_warn_never_fail(self):
        mods = _fake_modules()
        imap_cls = mods["elder_berry.tools.email_client"].IMAPEmailClient
        imap_cls.from_secret_store.side_effect = KeyError("email_password")

        svc, probe_failed = _run_init(_MAIL_CFG, mods)

        entry = _entry(_summary(svc, probe_failed), "E-Mail (IMAP)")
        assert (entry.status, entry.detail) == ("warn", "nicht konfiguriert")

    def test_gym_token_without_url_is_warn_never_fail(self):
        svc, probe_failed = _run_init({"berry_gym_api_token": "t"}, _fake_modules())

        assert "gym_client" not in svc
        entry = _entry(_summary(svc, probe_failed), "Berry-Gym")
        assert (entry.status, entry.detail) == ("warn", "nicht konfiguriert")

    def test_gym_constructor_error_is_warn_never_fail(self):
        mods = _fake_modules()
        mods["elder_berry.tools.gym_data"].GymDataClient.side_effect = ValueError("x")

        svc, probe_failed = _run_init(
            {"berry_gym_api_token": "t", "berry_gym_url": "https://gym"}, mods
        )

        entry = _entry(_summary(svc, probe_failed), "Berry-Gym")
        assert entry.status == "warn"


# ===========================================================================
# _build_startup_summary direkt
# ===========================================================================


class TestBuildStartupSummary:
    def test_carddav_entry_present(self):
        summary = _summary({}, set())
        assert _entry(summary, "CardDAV-Sync").status == "warn"

    def test_default_probe_failed_is_empty(self):
        """Ohne probe_failed-Argument bleibt das Alt-Verhalten (warn)."""
        summary = _build_startup_summary(
            assistant=MagicMock(),
            stt=None,
            robot=None,
            robot_state="unreachable",
            secrets=MagicMock(),
            svc={},
            tools={},
            tower_agent=None,
            matrix_user_id="@bot:x",
            matrix_room_id="!room:x",
            allowed_senders=frozenset({"@user:x"}),
            claude_agent=None,
        )
        assert _entry(summary, "Nextcloud Files").status == "warn"

    def test_robot_unreachable_does_not_crash(self):
        """Abnahme 3 (Unit-Anteil): RPi5 aus -> Status aus _robot_summary_status."""
        entry = _entry(_summary({}, set()), "RPi5 (Robot)")
        assert (entry.status, entry.detail) == (
            "warn",
            "nicht erreichbar (Netz/Tunnel)",
        )

    def test_probe_failed_ignored_when_instance_present(self):
        svc = {"nextcloud_files": MagicMock()}
        entry = _entry(_summary(svc, {"nextcloud_files"}), "Nextcloud Files")
        assert entry.status == "ok"


# ===========================================================================
# Übergabe an die Bridge (#1418 E1)
# ===========================================================================


class TestHandSummaryToBridge:
    def test_hands_message_to_bridge_without_sending(self):
        summary = MagicMock()
        summary.to_matrix_message.return_value = "Saleria – Startup Summary"
        bridge = MagicMock()
        channel = MagicMock()

        _hand_summary_to_bridge(summary, bridge, "!room:x")

        bridge.set_startup_message.assert_called_once_with(
            "!room:x", "Saleria – Startup Summary"
        )
        channel.send_text.assert_not_called()

    def test_no_room_id_does_nothing(self):
        bridge = MagicMock()
        _hand_summary_to_bridge(MagicMock(), bridge, None)
        bridge.set_startup_message.assert_not_called()

    def test_run_matrix_hands_summary_before_bridge_start(self):
        """Quelltext-Check (Muster wie test_start_saleria): Übergabe vor
        bridge.start(), kein direkter Send-Pfad mehr."""
        source = inspect.getsource(run_matrix)
        assert "_maybe_send_summary_to_matrix" not in source
        assert "send_text" not in source
        assert source.index("_hand_summary_to_bridge(") < source.index("bridge.start()")
        assert "probe_failed=probe_failed" in source

    def test_old_sender_removed(self):
        import start_saleria

        assert not hasattr(start_saleria, "_maybe_send_summary_to_matrix")
