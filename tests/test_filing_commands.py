"""Tests für FilingCommandHandler – Aufräumen des Nextcloud-Eingangs."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.filing_commands import (
    FILING_CONFIRM,
    FILING_PATTERN,
    FILING_SKIP,
    FilingCommandHandler,
)
from elder_berry.comms.pending_confirmation import PendingAction
from elder_berry.tools.document_classifier import FilingSuggestion


# ── Fixtures ──────────────────────────────────────────────────────────────


def _make_nc_file(name: str, is_dir: bool = False):
    f = MagicMock()
    f.name = name
    f.is_dir = is_dir
    return f


def _make_suggestion(**kwargs) -> FilingSuggestion:
    defaults = dict(
        date="2026-04-02",
        category="Haus",
        description="RK-Bedachung-Angebot",
        target_folder="Dokumente/Haus",
        filename="2026-04-02_Haus_RK-Bedachung-Angebot.pdf",
        confidence="high",
        manual_subfolder="",
    )
    defaults.update(kwargs)
    return FilingSuggestion(**defaults)


@pytest.fixture()
def nc():
    mock = MagicMock()
    mock.download.return_value = Path("C:/tmp/filing_abc/Scan_001.pdf")
    return mock


@pytest.fixture()
def classifier():
    mock = MagicMock()
    mock.classify.return_value = _make_suggestion()
    mock.classify_with_hint.return_value = _make_suggestion(
        category="Rechnung",
        target_folder="Dokumente/Rechnungen",
        filename="2026-04-02_Rechnung_Korrektur.pdf",
    )
    return mock


@pytest.fixture()
def pending():
    return MagicMock()


@pytest.fixture()
def handler(nc, classifier, pending):
    return FilingCommandHandler(
        nextcloud_files=nc,
        document_classifier=classifier,
        pending_store=pending,
    )


# ── Pattern-Matching ──────────────────────────────────────────────────────


def test_aufräumen_pattern():
    assert FILING_PATTERN.match("cloud aufräumen")


def test_räum_cloud_auf_pattern():
    assert FILING_PATTERN.match("räum cloud auf")


def test_eingang_aufräumen_pattern():
    assert FILING_PATTERN.match("eingang aufräumen")


def test_cloud_aufraumen_ascii():
    """Auch ohne Umlaut (aufraumen statt aufräumen)."""
    assert FILING_PATTERN.match("cloud aufraumen")


def test_no_collision_cloud_upload():
    assert not FILING_PATTERN.match("cloud upload test.pdf")


def test_no_collision_cloud_suche():
    assert not FILING_PATTERN.match("cloud suche report")


# ── Execute ──────────────────────────────────────────────────────────────


def test_eingang_empty(handler, nc):
    nc.list_dir.return_value = []

    result = handler.execute("cloud_aufräumen", "cloud aufräumen")

    assert result.success
    assert "leer" in result.text


def test_eingang_one_file(handler, nc):
    nc.list_dir.return_value = [_make_nc_file("Scan_001.pdf")]

    result = handler.execute("cloud_aufräumen", "cloud aufräumen")

    assert result.success
    assert "Scan_001.pdf" in result.text
    assert result.pending_confirmation
    assert result.pending_data["source_path"] == "Eingang/Scan_001.pdf"


def test_eingang_skips_directories(handler, nc):
    nc.list_dir.return_value = [
        _make_nc_file("Unterordner", is_dir=True),
        _make_nc_file("Scan.pdf"),
    ]

    result = handler.execute("cloud_aufräumen", "cloud aufräumen")

    assert result.success
    assert "Scan.pdf" in result.text


def test_eingang_multiple_files(handler, nc):
    nc.list_dir.return_value = [
        _make_nc_file("Scan_001.pdf"),
        _make_nc_file("Scan_002.pdf"),
        _make_nc_file("IMG_001.jpg"),
    ]

    result = handler.execute("cloud_aufräumen", "cloud aufräumen")

    assert result.success
    assert "1/3" in result.text
    assert result.pending_data["remaining_files"] == ["Scan_002.pdf", "IMG_001.jpg"]


# ── Confirm ──────────────────────────────────────────────────────────────


def test_confirm_moves_file(handler, nc):
    action = PendingAction(
        action_type="filing",
        description="test",
        data={
            "source_path": "Eingang/Scan.pdf",
            "local_temp": "C:/tmp/filing_abc/Scan.pdf",
            "suggestion": {
                "filename": "2026-04-02_Haus_Angebot.pdf",
                "target_folder": "Dokumente/Haus",
            },
            "remaining_files": [],
            "confidence": "high",
        },
    )

    with patch("pathlib.Path.exists", return_value=False):
        result = handler.handle_confirm(action, "@user:matrix")

    nc.move.assert_called_once_with(
        "Eingang/Scan.pdf", "Dokumente/Haus/2026-04-02_Haus_Angebot.pdf",
    )
    assert result.success
    assert "Eingang ist leer" in result.text


def test_confirm_next_file(handler, nc):
    """Nach MOVE → nächste Datei wird vorgeschlagen."""
    action = PendingAction(
        action_type="filing",
        description="test",
        data={
            "source_path": "Eingang/Scan_001.pdf",
            "local_temp": "C:/tmp/filing_abc/Scan_001.pdf",
            "suggestion": {
                "filename": "2026-04-02_Haus_Angebot.pdf",
                "target_folder": "Dokumente/Haus",
            },
            "remaining_files": ["Scan_002.pdf"],
            "confidence": "high",
        },
    )

    # list_dir nach MOVE gibt noch Scan_002.pdf zurück
    nc.list_dir.return_value = [_make_nc_file("Scan_002.pdf")]

    with patch("pathlib.Path.exists", return_value=False):
        result = handler.handle_confirm(action, "@user:matrix")

    assert result.success
    assert "Abgelegt" in result.text
    assert "Scan_002.pdf" in result.text
    assert result.pending_confirmation


def test_confirm_last_file(handler, nc):
    """Letzte Datei → Eingang ist leer."""
    action = PendingAction(
        action_type="filing",
        description="test",
        data={
            "source_path": "Eingang/Scan.pdf",
            "local_temp": "C:/tmp/filing_abc/Scan.pdf",
            "suggestion": {
                "filename": "2026-04-02_Haus_Angebot.pdf",
                "target_folder": "Dokumente/Haus",
            },
            "remaining_files": [],
            "confidence": "high",
        },
    )

    with patch("pathlib.Path.exists", return_value=False):
        result = handler.handle_confirm(action, "@user:matrix")

    assert result.success
    assert "Eingang ist leer" in result.text


# ── Skip ─────────────────────────────────────────────────────────────────


def test_skip_next_file(handler, nc):
    action = PendingAction(
        action_type="filing",
        description="test",
        data={
            "source_path": "Eingang/Scan_001.pdf",
            "local_temp": "C:/tmp/filing_abc/Scan_001.pdf",
            "suggestion": {"filename": "x.pdf", "target_folder": "Sonstiges"},
            "remaining_files": ["Scan_002.pdf"],
            "confidence": "high",
        },
    )

    nc.list_dir.return_value = [_make_nc_file("Scan_002.pdf")]

    with patch("pathlib.Path.exists", return_value=False):
        result = handler.handle_skip(action, "@user:matrix")

    nc.move.assert_not_called()
    assert result.success
    assert "Scan_002.pdf" in result.text


def test_skip_last_file(handler, nc):
    action = PendingAction(
        action_type="filing",
        description="test",
        data={
            "source_path": "Eingang/Scan.pdf",
            "local_temp": "C:/tmp/filing_abc/Scan.pdf",
            "suggestion": {"filename": "x.pdf", "target_folder": "Sonstiges"},
            "remaining_files": [],
            "confidence": "high",
        },
    )

    with patch("pathlib.Path.exists", return_value=False):
        result = handler.handle_skip(action, "@user:matrix")

    assert result.success
    assert "abgearbeitet" in result.text


# ── Correction ───────────────────────────────────────────────────────────


def test_correction_hint(handler, classifier):
    action = PendingAction(
        action_type="filing",
        description="test",
        data={
            "source_path": "Eingang/Scan.pdf",
            "local_temp": "C:/tmp/filing_abc/Scan.pdf",
            "suggestion": {"filename": "x.pdf", "target_folder": "Sonstiges"},
            "remaining_files": [],
            "confidence": "low",
        },
    )

    result = handler.handle_correction(action, "ist eine Rechnung", "@user:matrix")

    classifier.classify_with_hint.assert_called_once()
    assert result.success
    assert result.pending_confirmation


def test_correction_direct_name(handler, classifier):
    """'Haus Angebot-Dach' → classify_with_hint baut direkt."""
    classifier.classify_with_hint.return_value = _make_suggestion(
        category="Haus",
        description="Angebot-Dach",
        filename="2026-04-02_Haus_Angebot-Dach.pdf",
        target_folder="Dokumente/Haus",
    )

    action = PendingAction(
        action_type="filing",
        description="test",
        data={
            "source_path": "Eingang/Scan.pdf",
            "local_temp": "C:/tmp/filing_abc/Scan.pdf",
            "suggestion": {"filename": "x.pdf", "target_folder": "Sonstiges"},
            "remaining_files": [],
            "confidence": "low",
        },
    )

    result = handler.handle_correction(action, "Haus Angebot-Dach", "@user:matrix")

    assert result.success
    assert "Angebot-Dach" in result.text


# ── Error Cases ──────────────────────────────────────────────────────────


def test_move_error(handler, nc):
    nc.move.side_effect = Exception("412 Precondition Failed")

    action = PendingAction(
        action_type="filing",
        description="test",
        data={
            "source_path": "Eingang/Scan.pdf",
            "local_temp": "C:/tmp/filing_abc/Scan.pdf",
            "suggestion": {
                "filename": "2026-04-02_Haus_Angebot.pdf",
                "target_folder": "Dokumente/Haus",
            },
            "remaining_files": [],
            "confidence": "high",
        },
    )

    result = handler.handle_confirm(action, "@user:matrix")

    assert not result.success
    assert "fehlgeschlagen" in result.text


def test_no_nextcloud():
    h = FilingCommandHandler(nextcloud_files=None)
    result = h.execute("cloud_aufräumen", "cloud aufräumen")

    assert not result.success
    assert "Nextcloud" in result.text


def test_no_classifier(nc):
    h = FilingCommandHandler(nextcloud_files=nc, document_classifier=None)
    result = h.execute("cloud_aufräumen", "cloud aufräumen")

    assert not result.success
    assert "Analyse" in result.text or "verfügbar" in result.text


def test_help_text():
    h = FilingCommandHandler()
    descriptions = h.command_descriptions

    assert any("aufräumen" in d for d in descriptions)
