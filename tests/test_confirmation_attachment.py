"""Flow-Tests für ConfirmationAttachmentMixin (Backlog #834).

Deckt die Anhang-Aktionen ab: ``_attachment_summarize`` (PDF →
``_handle_llm_enrichment``), ``_attachment_file`` (Klassifikation →
Filing-PendingAction), ``_attachment_delete`` und das statische
``_attachment_cleanup_temp``.

Der Code nutzt echtes ``pathlib.Path`` (``exists()`` / ``unlink()``), darum
werden reale Temp-Dateien (``tmp_path``) angelegt. Muster sonst wie Journal
#839; Timeout über Patch von ``confirmation_attachment.asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from elder_berry.comms.commands.base import CommandResult
from elder_berry.comms.confirmation_handlers import ConfirmationHandler
from elder_berry.comms.pending_confirmation import PendingAction

_WAIT_FOR = "elder_berry.comms.handlers.confirmation_attachment.asyncio.wait_for"


def _make_parent() -> MagicMock:
    parent = MagicMock()
    parent._channel = MagicMock()
    parent._channel.send_text = AsyncMock()
    parent._pending = MagicMock()
    parent._chat_history = MagicMock()
    parent._remote_commands = MagicMock()
    parent._nc_files = MagicMock()
    parent._email_sender = MagicMock()
    parent._email_client = MagicMock()
    parent._scheduler_mgr = MagicMock()
    parent.restart_cooldown_until = 0.0
    parent._handle_llm_enrichment = AsyncMock()
    return parent


def _make_msg(
    body: str = "zusammenfassen",
    sender: str = "@user:matrix.org",
    room_id: str = "!room:matrix.org",
) -> MagicMock:
    msg = MagicMock()
    msg.body = body
    msg.sender = sender
    msg.room_id = room_id
    msg.timestamp = time.time()
    return msg


def _payloads(parent: MagicMock) -> list[str]:
    return [c.args[1] for c in parent._channel.send_text.call_args_list]


def _make_pdf(tmp_path: Path, name: str) -> str:
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4 fake")
    return str(p)


# ---------------------------------------------------------------------------
# _attachment_summarize
# ---------------------------------------------------------------------------


class TestAttachmentSummarize:
    async def test_reader_not_available(self, tmp_path):
        parent = _make_parent()
        parent._remote_commands._advanced._document_reader = None
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [pdf]},
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._attachment_summarize(msg, action)

        assert any("Dokument-Analyse nicht verfügbar" in p for p in _payloads(parent))
        parent._pending.clear.assert_called_once_with(msg.sender)
        parent._handle_llm_enrichment.assert_not_called()
        assert not Path(pdf).exists()  # cleanup

    async def test_success_routes_to_llm_enrichment(self, tmp_path):
        parent = _make_parent()
        reader = parent._remote_commands._advanced._document_reader
        reader.read_file.return_value = MagicMock(text="Inhalt der Rechnung")
        pdf = _make_pdf(tmp_path, "rechnung.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [pdf]},
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._attachment_summarize(msg, action)

        parent._pending.clear.assert_called_once_with(msg.sender)
        parent._handle_llm_enrichment.assert_called_once()
        kwargs = parent._handle_llm_enrichment.call_args.kwargs
        result = kwargs["result"]
        assert isinstance(result, CommandResult)
        assert result.command == "attachment_summary"
        assert "Inhalt der Rechnung" in (result.history_text or "")
        assert not Path(pdf).exists()  # cleanup

    async def test_no_extractable_text(self, tmp_path):
        parent = _make_parent()
        reader = parent._remote_commands._advanced._document_reader
        reader.read_file.return_value = MagicMock(text="")
        pdf = _make_pdf(tmp_path, "leer.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [pdf]},
        )

        handler = ConfirmationHandler(parent)
        await handler._attachment_summarize(_make_msg(), action)

        assert any("Kein Text" in p for p in _payloads(parent))
        parent._handle_llm_enrichment.assert_not_called()
        assert not Path(pdf).exists()

    async def test_timeout_falls_into_exception_path(self, tmp_path):
        parent = _make_parent()
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [pdf]},
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        with patch(_WAIT_FOR, side_effect=asyncio.TimeoutError):
            await handler._attachment_summarize(msg, action)

        assert any("Zusammenfassung fehlgeschlagen" in p for p in _payloads(parent))
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert not Path(pdf).exists()

    async def test_reader_exception(self, tmp_path):
        parent = _make_parent()
        reader = parent._remote_commands._advanced._document_reader
        reader.read_file.side_effect = RuntimeError("read boom")
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [pdf]},
        )

        handler = ConfirmationHandler(parent)
        await handler._attachment_summarize(_make_msg(), action)

        assert any(
            "Zusammenfassung fehlgeschlagen: RuntimeError" in p
            for p in _payloads(parent)
        )
        assert not Path(pdf).exists()


# ---------------------------------------------------------------------------
# _attachment_file
# ---------------------------------------------------------------------------


class TestAttachmentFile:
    async def test_classifier_not_available(self, tmp_path):
        parent = _make_parent()
        parent._remote_commands._filing._classifier = None
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [pdf], "nc_remote_paths": ["/Eingang/doc.pdf"]},
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="ablegen")
        await handler._attachment_file(msg, action)

        assert any(
            "Dokument-Klassifikation nicht verfügbar" in p for p in _payloads(parent)
        )
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert not Path(pdf).exists()  # cleanup

    async def test_no_pdf_left(self, tmp_path):
        parent = _make_parent()
        # Pfad zeigt auf nicht-existente Datei.
        missing = str(tmp_path / "weg.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [missing], "nc_remote_paths": ["/Eingang/weg.pdf"]},
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="ablegen")
        await handler._attachment_file(msg, action)

        assert any("Keine PDF-Dateien mehr vorhanden" in p for p in _payloads(parent))
        parent._pending.clear.assert_called_once_with(msg.sender)

    async def test_success_switches_to_filing_action(self, tmp_path):
        parent = _make_parent()
        classifier = parent._remote_commands._filing._classifier
        classifier.classify.return_value = MagicMock(
            confidence="high",
            filename="Rechnung_2026.pdf",
            target_folder="Belege",
        )
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [pdf], "nc_remote_paths": ["/Eingang/doc.pdf"]},
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="ablegen")
        await handler._attachment_file(msg, action)

        parent._pending.set.assert_called_once()
        new_action = parent._pending.set.call_args.args[1]
        assert isinstance(new_action, PendingAction)
        assert new_action.action_type == "filing"
        assert new_action.data["source_type"] == "nc_attachment"
        assert new_action.data["source_path"] == "/Eingang/doc.pdf"
        assert new_action.data["suggestion"]["filename"] == "Rechnung_2026.pdf"
        assert new_action.data["suggestion"]["target_folder"] == "Belege"
        joined = "\n".join(_payloads(parent))
        assert "Rechnung_2026.pdf" in joined
        assert "Belege" in joined
        assert parent._chat_history.add.call_count == 2

    async def test_low_confidence_hint(self, tmp_path):
        parent = _make_parent()
        classifier = parent._remote_commands._filing._classifier
        classifier.classify.return_value = MagicMock(
            confidence="low",
            filename="Unklar.pdf",
            target_folder="Sonstiges",
        )
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [pdf], "nc_remote_paths": ["/Eingang/doc.pdf"]},
        )

        handler = ConfirmationHandler(parent)
        await handler._attachment_file(_make_msg(body="ablegen"), action)

        assert any("Unsicher" in p for p in _payloads(parent))

    async def test_classify_exception(self, tmp_path):
        parent = _make_parent()
        classifier = parent._remote_commands._filing._classifier
        classifier.classify.side_effect = RuntimeError("class boom")
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [pdf], "nc_remote_paths": ["/Eingang/doc.pdf"]},
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="ablegen")
        await handler._attachment_file(msg, action)

        assert any(
            "Klassifikation fehlgeschlagen: RuntimeError" in p
            for p in _payloads(parent)
        )
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert not Path(pdf).exists()  # cleanup


# ---------------------------------------------------------------------------
# _attachment_delete
# ---------------------------------------------------------------------------


class TestAttachmentDelete:
    async def test_nextcloud_not_available(self, tmp_path):
        parent = _make_parent()
        parent._nc_files = None
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={
                "pdf_local_paths": [pdf],
                "nc_remote_paths": ["/Eingang/doc.pdf"],
            },
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="löschen")
        await handler._attachment_delete(msg, action)

        assert any("Nextcloud nicht verfügbar" in p for p in _payloads(parent))
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert not Path(pdf).exists()  # cleanup

    async def test_success(self, tmp_path):
        parent = _make_parent()
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={
                "pdf_local_paths": [pdf],
                "nc_remote_paths": ["/Eingang/a.pdf", "/Eingang/b.pdf"],
            },
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="löschen")
        await handler._attachment_delete(msg, action)

        assert parent._nc_files.delete.call_count == 2
        joined = "\n".join(_payloads(parent))
        assert "Gelöscht: a.pdf, b.pdf" in joined
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert not Path(pdf).exists()

    async def test_partial_errors(self, tmp_path):
        parent = _make_parent()
        parent._nc_files.delete.side_effect = [None, RuntimeError("nope")]
        pdf = _make_pdf(tmp_path, "doc.pdf")
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={
                "pdf_local_paths": [pdf],
                "nc_remote_paths": ["/Eingang/a.pdf", "/Eingang/b.pdf"],
            },
        )

        handler = ConfirmationHandler(parent)
        await handler._attachment_delete(_make_msg(body="löschen"), action)

        joined = "\n".join(_payloads(parent))
        assert "Gelöscht: a.pdf" in joined
        assert "Fehler" in joined
        assert "/Eingang/b.pdf: nope" in joined

    async def test_no_paths(self):
        parent = _make_parent()
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"nc_remote_paths": []},
        )

        handler = ConfirmationHandler(parent)
        await handler._attachment_delete(_make_msg(body="löschen"), action)

        assert any("Keine Dateien zum Löschen" in p for p in _payloads(parent))


# ---------------------------------------------------------------------------
# _attachment_cleanup_temp (statisch)
# ---------------------------------------------------------------------------


class TestAttachmentCleanupTemp:
    def test_removes_existing_ignores_missing(self, tmp_path):
        existing = tmp_path / "da.pdf"
        existing.write_bytes(b"x")
        missing = tmp_path / "weg.pdf"  # existiert nie
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={"pdf_local_paths": [str(existing), str(missing)]},
        )

        # missing_ok=True -> kein Fehler trotz fehlender Datei.
        ConfirmationHandler._attachment_cleanup_temp(action)

        assert not existing.exists()
        assert not missing.exists()

    def test_no_paths_is_noop(self):
        action = PendingAction(
            action_type="attachment_menu",
            description="menu",
            data={},
        )
        # Darf nicht werfen.
        ConfirmationHandler._attachment_cleanup_temp(action)
