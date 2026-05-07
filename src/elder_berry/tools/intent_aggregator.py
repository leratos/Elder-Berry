"""ProposalIntentAggregator -- Heuristik fuer Plugin-Vorschlaege (Phase 78).

Wird von der MatrixBridge nach jedem LLM-Fallback aufgerufen, wenn
Saleria im Output einen `<plugin-candidate>`-Block geliefert hat.

Aufgaben (Konzept §3.5):
- Filter: Confidence-Threshold, Smalltalk-Negativliste.
- Sender-Hash: SHA256(sender + Salt) -- Salt aus SecretStore (auto-
  generiert beim ersten Lauf).
- Sample-Trim: 200 Zeichen Limit.
- Routing zu `ProposalStore.create_pending` (neuer Intent) oder
  `add_trigger` (bekannter Intent).
- Threshold-Check ueber 7-Tage-Window-Query (NICHT lifetime counter)
  und einmalige Notification ueber `ProposalNotifier`.
"""

from __future__ import annotations

import hashlib
import logging
import secrets

from elder_berry.comms.proposal_notifier import ProposalNotifier
from elder_berry.core.secret_store import SecretStore
from elder_berry.tools.proposal_store import (
    ProposalNotFoundError,
    ProposalStore,
)

logger = logging.getLogger(__name__)


class ProposalIntentAggregator:
    """Reaktive Heuristik fuer Plugin-Vorschlaege.

    Threshold und Filter sind Konstanten -- spaetere Tuning-Werte
    landen ueber SecretStore (siehe Konzept R7).
    """

    THRESHOLD_COUNT = 3
    THRESHOLD_DAYS = 7
    MIN_CONFIDENCE = 0.7
    SAMPLE_MAX_CHARS = 200
    SALT_KEY = "proposal_sender_salt"

    SMALLTALK_INTENTS: frozenset[str] = frozenset(
        {
            "jokes",
            "compliments",
            "philosophy",
            "smalltalk",
            "greeting",
            "thanks",
            "weather_chat",
        }
    )

    def __init__(
        self,
        store: ProposalStore,
        notifier: ProposalNotifier,
        secret_store: SecretStore,
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._secret_store = secret_store
        self._salt = self._load_or_generate_salt()

    def _load_or_generate_salt(self) -> str:
        existing = self._secret_store.get_or_none(self.SALT_KEY)
        if existing:
            return existing
        new_salt = secrets.token_hex(32)
        self._secret_store.set(self.SALT_KEY, new_salt)
        logger.info(
            "ProposalIntentAggregator: neuer Sender-Salt generiert und in "
            "SecretStore unter %r abgelegt.",
            self.SALT_KEY,
        )
        return new_salt

    async def record(
        self,
        intent: str,
        title: str,
        description: str,
        sample: str,
        sender: str,
        confidence: float,
        category: str | None = None,
    ) -> None:
        """Verarbeitet einen Plugin-Kandidaten aus dem LLM-Output.

        Args:
            intent: Normalisierter snake_case-Bezeichner vom LLM.
            title: Kurzer Titel vom LLM.
            description: 2-3 Saetze vom LLM, was die Capability tun wuerde.
            sample: Original-Anfrage (wird auf SAMPLE_MAX_CHARS getrimmt).
            sender: Klartext-User-ID -- wird intern gehasht, NICHT
                persistiert.
            confidence: LLM-Confidence (0..1).
            category: Optionaler Kategorievorschlag (z.B. "medien").
        """
        if not intent:
            logger.debug("Aggregator: leerer Intent verworfen")
            return
        if intent in self.SMALLTALK_INTENTS:
            logger.debug("Aggregator: Smalltalk-Intent %r ignoriert", intent)
            return
        if confidence < self.MIN_CONFIDENCE:
            logger.debug(
                "Aggregator: Confidence %.2f unter Schwelle %.2f fuer %r",
                confidence,
                self.MIN_CONFIDENCE,
                intent,
            )
            return

        sample_trimmed = self._trim_sample(sample)
        sender_hash = self._hash_sender(sender)

        existing = self._store.get_by_id(intent)
        if existing is None:
            description_md = self._build_initial_description(
                description, sample_trimmed
            )
            self._store.create_pending(
                intent=intent,
                title=title,
                description_md=description_md,
                sample_message=sample_trimmed,
                sender_hash=sender_hash,
                confidence=confidence,
                suggested_category=category,
            )
            logger.info(
                "Aggregator: neuer Plugin-Vorschlag angelegt: %s (%s)",
                intent,
                title,
            )
            return

        if existing.status in ("abgelehnt", "fertiggestellt"):
            try:
                self._store.add_trigger(
                    existing.id, sample_trimmed, sender_hash, confidence
                )
            except ProposalNotFoundError:
                logger.warning(
                    "Aggregator: Proposal %s zwischen Lookup und Update geloescht",
                    existing.id,
                )
            return

        # in_pruefung oder in_bearbeitung
        try:
            self._store.add_trigger(
                existing.id, sample_trimmed, sender_hash, confidence
            )
        except ProposalNotFoundError:
            logger.warning(
                "Aggregator: Proposal %s zwischen Lookup und Update geloescht",
                existing.id,
            )
            return

        if existing.status != "in_pruefung":
            return  # in_bearbeitung -> kein Re-Notify

        # Threshold-Check ueber 7-Tage-Fenster
        if existing.notified_at is not None:
            return  # Bereits gemeldet

        recent = self._store.count_triggers_since(existing.id, days=self.THRESHOLD_DAYS)
        if recent < self.THRESHOLD_COUNT:
            return

        # Notification + mark_notified
        # Re-Fetch fuer aktuellen State (trigger_count, last_triggered_at)
        current = self._store.get_by_id(existing.id)
        if current is None:
            return
        sent = await self._notifier.notify(
            current, recent_count=recent, days=self.THRESHOLD_DAYS
        )
        if not sent:
            # Send fehlgeschlagen -- mark_notified wird NICHT gesetzt,
            # damit der naechste Trigger einen Retry ausloest. Sonst
            # wuerde die Nachricht permanent verloren gehen (GitHub-
            # Review P2 vom 2026-05-07).
            logger.warning(
                "Aggregator: Notify fuer %s fehlgeschlagen -- "
                "naechster Trigger versucht erneut zu benachrichtigen.",
                existing.id,
            )
            return
        self._store.mark_notified(existing.id)
        logger.info(
            "Aggregator: Threshold erreicht fuer %s (%dx/%dT) -- benachrichtigt",
            existing.id,
            recent,
            self.THRESHOLD_DAYS,
        )

    def _trim_sample(self, sample: str) -> str:
        if len(sample) <= self.SAMPLE_MAX_CHARS:
            return sample
        return sample[: self.SAMPLE_MAX_CHARS - 1] + "…"

    def _hash_sender(self, sender: str) -> str:
        return hashlib.sha256((sender + self._salt).encode("utf-8")).hexdigest()

    @staticmethod
    def _build_initial_description(description: str, first_sample: str) -> str:
        body = description.strip() if description else ""
        if not body:
            body = "_Beschreibung folgt nach manuellem Review._"
        return f'{body}\n\n## Erste Beispielanfrage\n\n- "{first_sample}"'
