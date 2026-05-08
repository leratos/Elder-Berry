"""Plugin-Vorschlaege-API -- Read+Write fuer ProposalStore (Phase 78 Etappe 3).

Wird von SettingsDashboard eingebunden via ``register_proposals_routes()``.

Routen (alle hinter ``DashboardAuthMiddleware`` aus Phase 58 -- siehe
Konzept §6 R5):
- ``GET  /api/proposals?status=...``      Liste, optional nach Status
- ``GET  /api/proposals/{id}``            Detail (incl. gerendertes
                                          HTML, Trigger-History,
                                          Status-History)
- ``POST /api/proposals/{id}/status``     Status-Wechsel
- ``POST /api/proposals/{id}/implementation``  ``implemented_in`` setzen

Markdown-Body wird server-side ueber ``MarkdownRenderer`` gerendert
und mit ``bleach.clean()`` gegen die Allowlist gesaeubert (Konzept R3).
DOMPurify im Browser ist nur Defense-in-Depth.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

from elder_berry.tools.proposal_store import (
    InvalidStatusError,
    Proposal,
    ProposalHistoryEntry,
    ProposalNotFoundError,
    ProposalStore,
    ProposalTrigger,
)
from elder_berry.web.markdown_renderer import MarkdownRenderer

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _serialize_proposal(proposal: Proposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "title": proposal.title,
        "status": proposal.status,
        "description_md": proposal.description_md,
        "suggested_category": proposal.suggested_category,
        "suggested_priority": proposal.suggested_priority,
        "created_at": proposal.created_at.isoformat(),
        "updated_at": proposal.updated_at.isoformat(),
        "trigger_count": proposal.trigger_count,
        "last_triggered_at": proposal.last_triggered_at.isoformat(),
        "notified_at": (
            proposal.notified_at.isoformat() if proposal.notified_at else None
        ),
        "last_confidence": proposal.last_confidence,
        "rejected_reason": proposal.rejected_reason,
        "implemented_in": proposal.implemented_in,
        "related_proposals": list(proposal.related_proposals),
    }


def _serialize_trigger(trigger: ProposalTrigger) -> dict[str, Any]:
    return {
        "triggered_at": trigger.triggered_at.isoformat(),
        "sample_message": trigger.sample_message,
        "sender_hash": trigger.sender_hash,
        "confidence": trigger.confidence,
    }


def _serialize_history(entry: ProposalHistoryEntry) -> dict[str, Any]:
    return {
        "timestamp": entry.timestamp.isoformat(),
        "old_status": entry.old_status,
        "new_status": entry.new_status,
        "changed_by": entry.changed_by,
        "note": entry.note,
    }


def register_proposals_routes(
    app: FastAPI,
    store: ProposalStore,
    renderer: MarkdownRenderer | None = None,
) -> None:
    """Registriert die ``/api/proposals``-Routen auf der FastAPI-App.

    Args:
        app: FastAPI-Instanz aus dem SettingsDashboard.
        store: aktiver ProposalStore (DI aus run_matrix).
        renderer: optionaler MarkdownRenderer. Default: frische Instanz
            mit Standard-Allowlist.
    """
    md_renderer = renderer or MarkdownRenderer()

    @app.get("/api/proposals")
    async def list_proposals(status: str | None = None) -> JSONResponse:
        try:
            proposals = store.list_by_status(status)  # type: ignore[arg-type]
        except InvalidStatusError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"proposals": [_serialize_proposal(p) for p in proposals]})

    @app.get("/api/proposals/{proposal_id}")
    async def get_proposal(proposal_id: str) -> JSONResponse:
        proposal = store.get_by_id(proposal_id)
        if proposal is None:
            return JSONResponse(
                {"error": f"proposal '{proposal_id}' not found"},
                status_code=404,
            )
        triggers = store.get_triggers(proposal_id, limit=20)
        history = store.get_history(proposal_id)
        return JSONResponse(
            {
                "proposal": _serialize_proposal(proposal),
                "description_html": md_renderer.render(proposal.description_md),
                "triggers": [_serialize_trigger(t) for t in triggers],
                "history": [_serialize_history(h) for h in history],
            }
        )

    @app.post("/api/proposals/{proposal_id}/status")
    async def update_proposal_status(
        proposal_id: str,
        body: dict[str, Any] | None = None,
    ) -> JSONResponse:
        if not body or "new_status" not in body:
            return JSONResponse(
                {"error": "field 'new_status' required"}, status_code=422
            )
        try:
            store.update_status(
                proposal_id,
                body["new_status"],
                changed_by="lera",
                note=body.get("note"),
                rejected_reason=body.get("rejected_reason"),
            )
        except ProposalNotFoundError:
            return JSONResponse(
                {"error": f"proposal '{proposal_id}' not found"},
                status_code=404,
            )
        except InvalidStatusError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        proposal = store.get_by_id(proposal_id)
        assert proposal is not None  # gerade aktualisiert
        return JSONResponse({"proposal": _serialize_proposal(proposal)})

    @app.post("/api/proposals/{proposal_id}/implementation")
    async def set_proposal_implementation(
        proposal_id: str,
        body: dict[str, Any] | None = None,
    ) -> JSONResponse:
        if not body or "path" not in body:
            return JSONResponse({"error": "field 'path' required"}, status_code=422)
        path = body["path"]
        if not isinstance(path, str) or not path.strip():
            return JSONResponse(
                {"error": "field 'path' must be a non-empty string"},
                status_code=422,
            )
        try:
            store.set_implementation(proposal_id, path.strip())
        except ProposalNotFoundError:
            return JSONResponse(
                {"error": f"proposal '{proposal_id}' not found"},
                status_code=404,
            )
        proposal = store.get_by_id(proposal_id)
        assert proposal is not None
        return JSONResponse({"proposal": _serialize_proposal(proposal)})
