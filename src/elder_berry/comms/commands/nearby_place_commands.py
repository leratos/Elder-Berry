"""NearbyPlaceCommandHandler -- Umkreis-/Ortssuche (Phase 97, E4).

Orchestriert den Nearby-Flow:

- Turn 1: ``is_nearby_candidate`` (sonst Fallthrough) -> ``NearbyIntentParser``
  liefert ``NearbyQueryDraft``. Vollstaendig+valide -> Suche; sonst Draft im
  ``NearbyDraftStore`` persistieren (Key = default_user_id, B1) + EINE Rueckfrage.
- Folge-Turn (Freitext-Antwort "zu Fuss"/"Leipzig Hbf"): kommt als frische
  Nachricht und wird vom Early-Intercept in ``message_handlers`` an
  ``continue_with_answer()`` gereicht -> fehlendes Feld fuellen, ``to_query()``
  erneut. Subject/Query/exclude bleiben erhalten (R2-C5).
- Suche -> Pick-Liste (``list_type="nearby_place_pick"``) inkl. Google-
  Attribution (R2-C4). Der finale Pick -> Maps-Link laeuft ueber
  ``message_handlers._dispatch_nearby_pick`` (wie route_*_pick).

Der Code ERZWINGT (place_types/Radius/Filter); der LLM URTEILT nur. Geocoder-
Auth/Quota (``GeocoderConfigError``) wird als Dienstfehler gemeldet, NICHT als
"Ort nicht gefunden" (R2-C3).
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
    user_friendly_error,
)
from elder_berry.tools.google_geocoder import GeocoderConfigError
from elder_berry.tools.nearby_intent_parser import (
    NEARBY_TRIGGER_PATTERNS,
    NearbyIntentParser,
    is_nearby_candidate,
)
from elder_berry.tools.nearby_place_search import (
    LocationNotFoundError,
    NearbyPlaceError,
    NearbyQuery,
    NearbyQueryDraft,
    PlaceCandidate,
)
from elder_berry.tools.place_types import normalize_travel_mode

if TYPE_CHECKING:
    from elder_berry.tools.nearby_draft_store import NearbyDraftStore
    from elder_berry.tools.nearby_place_search import NearbyPlaceSearch

logger = logging.getLogger(__name__)


# Folge-Turn-Heuristik: sieht die Antwort eher nach einer NEUEN Frage/Command
# aus, nicht nach einem Ort? Dann nicht als Standort hijacken (Early-Intercept).
_UNRELATED_ANSWER = re.compile(
    r"\?|^\s*(?:wie|was|wann|warum|wieso|wer|welche|zeig|lies|mach|spiel|"
    r"erzähl|erkläre?|hilfe|hallo|hi|danke|stop|stopp)\b",
    re.IGNORECASE,
)

HELP_SECTION_NEARBY_PLACE = """Umkreissuche (Orte in der Nähe):
  "Ich bin <Straße, Stadt> und brauche <X> -- wo kaufe ich das hier?"
  "Kannst du mir eine <Venue> in der Nähe nennen?"
    -- nahe Treffer zuerst, gefiltert; dann Pick aus Liste -> Maps-Link.
  Fehlt Standort oder Reisemodus, frage ich einmal nach."""


class NearbyPlaceCommandHandler(CommandHandler):
    """Distanz-korrekte, gefilterte Umkreissuche mit Pick-Liste."""

    def __init__(
        self,
        intent_parser: NearbyIntentParser,
        place_search: NearbyPlaceSearch,
        draft_store: NearbyDraftStore,
        default_user_id: str = "",
    ) -> None:
        self._parser = intent_parser
        self._search = place_search
        self._drafts = draft_store
        self._user_id = default_user_id

    # ------------------------------------------------------------------
    # CommandHandler-Schnittstelle
    # ------------------------------------------------------------------

    @property
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        # Praezise Patterns (NICHT die generischen Verben allein) -- sonst
        # schlaegt der Catch-All Keyword-Commands wie Hilfe/Mail (Codex
        # PR #302). is_nearby_candidate macht im execute() die Endpruefung.
        return [(p, "nearby_place", False, True) for p in NEARBY_TRIGGER_PATTERNS]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "nearby_place": [
                "in der naehe",
                "wo kaufe ich",
                "wo gibt es",
                "hier in der naehe",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "wo kaufe ich <X> hier: naheliegende Läden, distanzsortiert",
            "nenne mir eine <Venue> in der Nähe: nahe Orte + Maps-Link",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command != "nearby_place":
            return CommandResult(command=command, success=False, fallthrough=True)
        return self._handle_turn1(raw_text)

    # ------------------------------------------------------------------
    # Early-Intercept-Schnittstelle (message_handlers)
    # ------------------------------------------------------------------

    def has_pending_draft(self) -> bool:
        """``True`` wenn ein offener Draft (default_user_id) wartet."""
        return self._drafts.get(self._user_id) is not None

    def continue_with_answer(self, text: str) -> CommandResult:
        """Folge-Turn: Freitext-Antwort auf die Rueckfrage verarbeiten.

        Wird vom Early-Intercept aufgerufen, wenn ein Draft pending ist.
        Eine NEUE Nearby-Anfrage ersetzt den Draft; eine unpassende Antwort
        wird NICHT als Standort gekapert (Fallthrough), der Draft bleibt.
        """
        if is_nearby_candidate(text):
            self._drafts.clear(self._user_id)
            return self._handle_turn1(text)

        draft = self._drafts.get(self._user_id)
        if draft is None:
            return CommandResult(
                command="nearby_place", success=False, fallthrough=True
            )

        field = self._missing_field(draft)
        if field == "mode":
            mode = normalize_travel_mode(text)
            if mode is None:
                # Keine Modus-Antwort -> nicht hijacken, Draft behalten.
                return CommandResult(
                    command="nearby_place", success=False, fallthrough=True
                )
            draft = replace(draft, travel_mode=mode)
        elif field == "location":
            if _UNRELATED_ANSWER.search(text):
                return CommandResult(
                    command="nearby_place", success=False, fallthrough=True
                )
            draft = replace(draft, location_text=text.strip())

        query = draft.to_query()
        if query is None:
            return self._ask_missing(draft)
        self._drafts.clear(self._user_id)
        return self._run_search(query, draft.subject)

    # ------------------------------------------------------------------
    # Turn 1
    # ------------------------------------------------------------------

    def _handle_turn1(self, raw_text: str) -> CommandResult:
        if not is_nearby_candidate(raw_text):
            return CommandResult(
                command="nearby_place", success=False, fallthrough=True
            )
        try:
            draft = self._parser.parse(raw_text)
        except RuntimeError as exc:
            logger.error("NearbyIntent-Parsing (LLM) kaputt: %s", exc)
            return CommandResult(
                command="nearby_place",
                success=True,
                text=user_friendly_error(exc, "Ortssuche"),
            )
        if draft is None:
            # False-Positive des Vorfilters -> andere Handler lassen.
            return CommandResult(
                command="nearby_place", success=False, fallthrough=True
            )

        query = draft.to_query()
        if query is None:
            return self._ask_missing(draft)
        # Komplette neue Suche -> evtl. alten Pending-Draft raeumen, sonst
        # kapert der Early-Intercept das naechste "Treffer N" als Antwort auf
        # den veralteten Draft statt als Pick aus der neuen Liste (Codex
        # PR #302).
        self._drafts.clear(self._user_id)
        return self._run_search(query, draft.subject)

    # ------------------------------------------------------------------
    # Rueckfrage + Suche
    # ------------------------------------------------------------------

    @staticmethod
    def _missing_field(draft: NearbyQueryDraft) -> str | None:
        """Welches Pflichtfeld fehlt (Reihenfolge: Standort, dann Modus)?"""
        if not draft.location_text or not draft.location_text.strip():
            return "location"
        if normalize_travel_mode(draft.travel_mode) is None:
            return "mode"
        return None

    def _ask_missing(self, draft: NearbyQueryDraft) -> CommandResult:
        """Persistiert den Draft + stellt EINE Rueckfrage zum fehlenden Feld."""
        self._drafts.set(self._user_id, draft)
        if self._missing_field(draft) == "location":
            text = (
                f"Ich suche {draft.subject} in der Nähe. Wo bist du gerade "
                f"ungefähr? (Straße + Stadt)"
            )
        else:
            text = (
                f"Womit bist du unterwegs -- zu Fuß, Rad, Auto oder ÖPNV? "
                f"(für {draft.subject})"
            )
        return CommandResult(command="nearby_place", success=True, text=text)

    def _run_search(self, query: NearbyQuery, subject: str) -> CommandResult:
        try:
            candidates = self._search.search(query)
        except LocationNotFoundError as exc:
            # Standort selbst nicht geocodebar -- NICHT mit "keine Orte
            # gefunden" verwechseln (kein Zentrum -> Weiten hilft nicht,
            # Codex PR #302). Nach korrigiertem Ort fragen.
            logger.info("Nearby: Standort nicht gefunden: %s", exc)
            return CommandResult(
                command="nearby_place",
                success=True,
                text=(
                    f"Ich konnte den Ort '{exc.location_text}' nicht finden. "
                    f"Sag ihn mir nochmal genauer (Straße + Stadt)."
                ),
            )
        except GeocoderConfigError as exc:
            logger.error("Nearby: Geocoder-Config/-Quota: %s", exc)
            return CommandResult(
                command="nearby_place",
                success=True,
                text=(
                    "Der Standort-Dienst (Geocoding) ist gerade nicht "
                    "verfügbar oder falsch konfiguriert -- das ist KEIN "
                    "'Ort nicht gefunden'. Schau bitte den API-Key/Quota an."
                ),
            )
        except NearbyPlaceError as exc:
            logger.error("Nearby: Places-Fehler: %s", exc)
            return CommandResult(
                command="nearby_place",
                success=True,
                text=f"Die Ortssuche hat gerade ein Problem: {exc}",
            )

        if not candidates:
            # Kein interaktives Retry versprechen -- _run_search haelt keinen
            # State, und der Folge-Intercept kennt nur Missing-Field-Drafts
            # (Codex PR #302). Stattdessen konkret zum Neu-Formulieren leiten.
            return CommandResult(
                command="nearby_place",
                success=True,
                text=(
                    f"Ich hab nichts für {subject} in der Nähe von "
                    f"{query.location_text} gefunden. Frag nochmal mit einem "
                    f"anderen Suchbegriff oder größerem Radius (z.B. mit dem "
                    f"Auto statt zu Fuß)."
                ),
            )
        return self._present_candidates(query, subject, candidates)

    @staticmethod
    def _present_candidates(
        query: NearbyQuery,
        subject: str,
        candidates: list[PlaceCandidate],
    ) -> CommandResult:
        """Baut die Pick-Liste + list_items (name/place_id) + Attribution."""
        lines = [f"Ich suche {subject} in der Nähe von {query.location_text}:"]
        items: list[dict[str, Any]] = []
        attributions: set[str] = set()
        for idx, cand in enumerate(candidates, start=1):
            lines.append(f"  {idx}. {cand.name} -- {_format_meta(cand)}")
            items.append(
                {
                    "name": cand.name,
                    "place_id": cand.place_id,
                    "address": cand.address,
                },
            )
            attributions.update(cand.attributions)
        lines.append('Welcher? Sag mir "Treffer 1" oder die Nummer.')
        # Pflicht-Attribution (R2-C4): Anzeige ohne Karte.
        attr = "Orte via Google Maps"
        if attributions:
            attr += " - " + ", ".join(sorted(attributions))
        lines.append(attr)
        return CommandResult(
            command="nearby_place",
            success=True,
            text="\n".join(lines),
            list_items=items,
            list_type="nearby_place_pick",
        )


def _format_meta(cand: PlaceCandidate) -> str:
    """Adresse + Entfernung + ggf. Rating + Offen-Status, einzeilig."""
    if cand.distance_m < 1000:
        dist = f"{cand.distance_m} m"
    else:
        dist = f"{cand.distance_m / 1000:.1f} km"
    parts = [cand.address or "(keine Adresse)", dist]
    if cand.rating is not None:
        parts.append(f"★{cand.rating:.1f}")
    if cand.open_now is True:
        parts.append("offen")
    elif cand.open_now is False:
        parts.append("geschlossen")
    return f"{parts[0]} ({', '.join(parts[1:])})"


# ---------------------------------------------------------------------------
# Plugin-Manifest
# ---------------------------------------------------------------------------


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    # Nur wenn die key-gebundenen Services verdrahtet sind (start_saleria
    # baut sie bei vorhandenem google_maps_api_key). Der Parser wird -- wie
    # RouteIntentParser im Multi-Stop-Handler -- hier aus dem Client gebaut.
    if ctx.nearby_place_search is None or ctx.nearby_draft_store is None:
        return None
    return NearbyPlaceCommandHandler(
        intent_parser=NearbyIntentParser(ctx.anthropic_client),
        place_search=ctx.nearby_place_search,
        draft_store=ctx.nearby_draft_store,
        default_user_id=ctx.default_user_id,
    )


PLUGIN = CommandPlugin(
    name="nearby_place",
    priority=74,  # vor multi_stop_route (75); Nearby-Trigger sind distinkt.
    category="web",
    help_section=HELP_SECTION_NEARBY_PLACE,
    factory=_factory,
)
