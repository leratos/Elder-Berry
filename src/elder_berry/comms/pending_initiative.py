"""PendingInitiative – Deterministische Bestätigung von Saleria-Initiativ-Vorschlägen.

Phase 89 (Pfad C): Wenn Saleria proaktiv eine Aktion vorschlägt
("Soll ich den Termin eintragen?"), legt der Handler den konkreten
Folge-Command als ``PendingInitiative`` ab. Die nächste kurze Bestätigung
des Users ("ja", "ja bitte", "mach") führt den Command deterministisch aus –
ohne dass das LLM die Bestätigung interpretieren muss.

Abgrenzung zu PendingConfirmation (Phase 18,
``pending_confirmation.py``):

* PendingConfirmation: code-erkannte destruktive Aktionen, die der User
  bestätigen MUSS. Blockiert den Flow bis ja/nein/ändern.
* PendingInitiative: LLM-erkannte, optionale Vorschläge. Eine Nicht-
  Bestätigung verwirft den Vorschlag und lässt die Nachricht normal
  weiterlaufen (kein Blockieren).

Beide Pipelines koexistieren: der ausgeführte ``proposed_command`` läuft
durch den normalen Command-Pfad. Ist er selbst destruktiv, greift dahinter
weiterhin PendingConfirmation – die Bestätigung ist dann doppelt.

Verwendung:
    store = PendingInitiativeStore()
    store.set("@user:matrix.org", PendingInitiative(
        proposed_command="kalender erstelle 15.08. Urlaub",
        question="Soll ich den Termin eintragen?",
    ))
    response_type, initiative = store.check_response("@user:matrix.org", "ja bitte")
    # response_type == "confirm", initiative.proposed_command == "kalender ..."
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Standard-TTL: 5 Minuten (konsistent mit PendingConfirmation).
DEFAULT_TTL_SECONDS = 300

# Bewusst ENGE Bestätigungs-Erkennung. Begründung: Bei Nicht-Match wird der
# Vorschlag verworfen und die Nachricht normal weiterverarbeitet (Lera-
# Entscheidung Phase 89). Unter-Erkennung ist damit der sichere Fehlerfall
# (das LLM fragt im Zweifel nochmal), Über-Erkennung (= ungewollte Aktion)
# der gefährliche. Darum kein nacktes "bitte", keine Volltext-Heuristik.
INITIATIVE_CONFIRM_WORDS = frozenset(
    {
        "ja",
        "jo",
        "joa",
        "jup",
        "jep",
        "jap",
        "yes",
        "yep",
        "klar",
        "gerne",
        "gern",
        "ok",
        "okay",
        "okey",
        "mach",
        "machs",
        "mach das",
        "jawohl",
        "jawoll",
        "ja bitte",
        "ja gerne",
        "ja gern",
        "ja klar",
        "ja mach",
        "ja mach das",
        "ja unbedingt",
        "unbedingt",
        "passt",
        "perfekt",
        "auf jeden fall",
    }
)

# Phase 89 Sicherheit (PR #276, Codex P1): Default-deny-Allowlist fuer
# Commands, die ein bestaetigter Initiativ-Vorschlag automatisch ausfuehren
# darf. Bewusst NUR reversible / nicht-destruktive Aktionen. Hintergrund:
# 1) propose_action kann aus untrusted Mail-/Web-/Doku-Enrichment stammen
#    (Prompt-Injection-Vektor) -- ein kurzes "ja" darf keine beliebige
#    Aktion ausloesen.
# 2) Einige destruktive Commands (z.B. contact_delete, einzelne
#    termin_delete) loeschen sofort OHNE eigene PendingConfirmation -- sie
#    duerfen daher nie ueber den Initiativ-Pfad laufen.
# Alles, was nicht hier steht, wird abgelehnt ("tipp den Befehl direkt").
# Erweitern nur um nachweislich umkehrbare/harmlose Commands.
SAFE_PROPOSABLE_COMMANDS = frozenset(
    {
        "termin_create",
        "note_add",
        "todo_add",
        "reminder",
        "reminder_date",
        "recurring_reminder",
        "contact_add",
        "contact_add_natural",
    }
)

INITIATIVE_CANCEL_WORDS = frozenset(
    {
        "nein",
        "ne",
        "nee",
        "nö",
        "no",
        "nope",
        "lass",
        "lass es",
        "lass mal",
        "nicht",
        "nicht nötig",
        "abbrechen",
        "stopp",
        "stop",
        "vergiss es",
        "lieber nicht",
    }
)

# Satz-Endzeichen, die vor dem Set-Vergleich entfernt werden, damit
# "ja bitte!" / "ja, bitte." auf "ja bitte" normalisiert.
_PUNCT_RE = re.compile(r"[.,!?;:…\"'`´]+")


def _normalize(text: str) -> str:
    """Normalisiert einen Antworttext für den Wortschatz-Vergleich.

    Lowercase, Satzzeichen zu Leerzeichen, Mehrfach-Whitespace kollabiert.
    """
    lowered = text.strip().lower()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    return " ".join(no_punct.split())


@dataclass
class PendingInitiative:
    """Ein vom LLM vorgeschlagener Folge-Command, der auf Bestätigung wartet."""

    proposed_command: str
    """Konkreter Folge-Command (z.B. 'kalender erstelle 15.08. Urlaub')."""

    question: str = ""
    """Menschenlesbare Frage, die Saleria gestellt hat (für Logging/Audit)."""

    created_at: float = field(default_factory=time.time)
    """Unix-Timestamp der Erstellung."""

    ttl: float = DEFAULT_TTL_SECONDS
    """Time-to-live in Sekunden."""

    @property
    def is_expired(self) -> bool:
        """True wenn der Vorschlag abgelaufen ist."""
        return (time.time() - self.created_at) > self.ttl


class PendingInitiativeStore:
    """Speichert einen ausstehenden Initiativ-Vorschlag pro User.

    Thread-safe genug für den Bridge-Einsatz: Python-GIL + atomare
    dict-Operationen (gleiches Modell wie PendingConfirmationStore).
    Ein Vorschlag pro User (keine Queue) – mehrere offene Vorschläge sind
    laut Phase-89-Konzept Out-of-Scope.

    Lifecycle-Kontrakt: ``check_response`` mutiert den Store NICHT (außer der
    Lazy-Expiry in ``get``). Der Aufrufer (Bridge) entscheidet anhand des
    Ergebnis-Typs und ruft ``clear`` explizit auf. So bleibt das Verwerfen-
    bei-Nicht-Match-Verhalten an einer Stelle steuerbar.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingInitiative] = {}

    def set(self, user_id: str, initiative: PendingInitiative) -> None:
        """Setzt einen ausstehenden Vorschlag für einen User.

        Überschreibt einen eventuell bestehenden Vorschlag (nur einer pro User).
        """
        self._pending[user_id] = initiative
        logger.info(
            "PendingInitiative gesetzt für %s: %r (TTL: %.0fs)",
            user_id,
            initiative.proposed_command,
            initiative.ttl,
        )

    def get(self, user_id: str) -> PendingInitiative | None:
        """Holt den ausstehenden Vorschlag für einen User.

        Returns:
            PendingInitiative oder None (keiner oder abgelaufen).
        """
        initiative = self._pending.get(user_id)
        if initiative is None:
            return None
        if initiative.is_expired:
            logger.info(
                "PendingInitiative abgelaufen für %s: %r",
                user_id,
                initiative.proposed_command,
            )
            del self._pending[user_id]
            return None
        return initiative

    def clear(self, user_id: str) -> None:
        """Entfernt den ausstehenden Vorschlag für einen User."""
        self._pending.pop(user_id, None)

    def check_response(
        self,
        user_id: str,
        text: str,
    ) -> tuple[str, PendingInitiative | None]:
        """Klassifiziert einen Text gegen einen offenen Vorschlag.

        Mutiert den Store nicht (Lazy-Expiry in ``get`` ausgenommen).

        Returns:
            Tuple von (response_type, initiative):
            - ("confirm", initiative) → kurze Bestätigung ("ja", "ja bitte", ...)
            - ("cancel", initiative) → Absage ("nein", "lass es", ...)
            - ("other", initiative) → Vorschlag offen, aber Text ist weder
              Bestätigung noch Absage (Aufrufer verwirft + verarbeitet normal)
            - ("none", None) → kein offener Vorschlag
        """
        initiative = self.get(user_id)
        if initiative is None:
            return ("none", None)

        normalized = _normalize(text)

        if normalized in INITIATIVE_CONFIRM_WORDS:
            return ("confirm", initiative)

        if normalized in INITIATIVE_CANCEL_WORDS:
            return ("cancel", initiative)

        return ("other", initiative)
