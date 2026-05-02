"""GymDataClient – Trainingsdaten von Berry-Gym abrufen.

Liest Trainings-Zusammenfassungen, letzte Sessions, Wochen-Übersicht und
Personal Records über die Berry-Gym REST-API (Token-Auth).

Verwendung:
    client = GymDataClient(
        secret_store=store,
        base_url="https://gym.example.com",
    )
    summary = client.get_summary()
    last = client.get_last_training()
    week = client.get_week()
    prs = client.get_prs()

Phase 67 (M-Fix): ``base_url`` ist Pflicht-Argument. Frueher gab es
einen hardcoded Default auf die eigene Berry-Gym-Instanz; das war fuer
ein Public-Repo problematisch und unter ``gym.example.com`` nicht
erreichbar. Aufrufer muessen ``base_url`` explizit setzen (in der
Regel aus ``SecretStore.get_or_none("berry_gym_url")``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx

    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10


class GymDataClient:
    """Berry-Gym API Client (read-only, Token-Auth).

    Lazy-Init: httpx.Client wird erst beim ersten Request erstellt.
    Token aus SecretStore: ``berry_gym_api_token``.
    URL muss vom Aufrufer kommen (z.B. SecretStore-Key
    ``berry_gym_url``) -- es gibt absichtlich keinen Default mehr.
    """

    def __init__(
        self,
        secret_store: SecretStore,
        base_url: str,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError(
                "GymDataClient: base_url ist leer. "
                "Setze 'berry_gym_url' im SecretStore oder uebergib base_url "
                "explizit (z.B. 'https://gym.example.com')."
            )
        self._store = secret_store
        self._base_url = base_url.strip().rstrip("/")
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Lazy-Init: httpx.Client mit Bearer-Token + base_url."""
        if self._client is not None:
            return self._client

        import httpx

        token = self._store.get("berry_gym_api_token")
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
        )
        return self._client

    def is_available(self) -> bool:
        """Prüft ob Berry-Gym Token konfiguriert ist."""
        try:
            token = self._store.get_or_none("berry_gym_api_token")
            return bool(token)
        except Exception:
            return False

    def get_summary(self) -> dict[str, Any] | None:
        """Trainings-Zusammenfassung: letztes Training, Woche, Gewicht."""
        return self._get("/api/saleria/summary/")

    def get_last_training(self) -> dict[str, Any] | None:
        """Letztes Training mit allen Sätzen."""
        data = self._get("/api/saleria/last-training/")
        if data:
            training = data.get("training")
            return cast("dict[str, Any] | None", training)
        return None

    def get_week(self) -> list[dict[str, Any]]:
        """Trainings der letzten 7 Tage."""
        data = self._get("/api/saleria/week/")
        if data:
            return cast("list[dict[str, Any]]", data.get("trainings", []))
        return []

    def get_prs(self) -> list[dict[str, Any]]:
        """Personal Records (Top 1RM pro Übung, letzte 30 Tage)."""
        data = self._get("/api/saleria/prs/")
        if data:
            return cast("list[dict[str, Any]]", data.get("prs", []))
        return []

    def format_summary(self, summary: dict[str, Any]) -> str:
        """Formatiert die Zusammenfassung als lesbaren Text."""
        lines = []

        last = summary.get("letztes_training")
        if last:
            datum = last.get("datum", "?")[:10]
            dauer = last.get("dauer_minuten", "?")
            uebungen = last.get("uebungen_anzahl", "?")
            lines.append(f"Letztes Training: {datum} ({dauer} Min, {uebungen} Übungen)")
        else:
            lines.append("Letztes Training: keins gefunden")

        woche = summary.get("trainings_diese_woche", 0)
        lines.append(f"Diese Woche: {woche} Training{'s' if woche != 1 else ''}")

        gewicht = summary.get("aktuelles_gewicht")
        if gewicht:
            kg = gewicht.get("gewicht_kg", "?")
            datum = gewicht.get("datum", "?")[:10]
            lines.append(f"Gewicht: {kg} kg ({datum})")

        return "\n".join(lines)

    def format_last_training(self, training: dict[str, Any]) -> str:
        """Formatiert das letzte Training mit Sätzen."""
        datum = training.get("datum", "?")[:10]
        dauer = training.get("dauer_minuten", "?")
        kommentar = training.get("kommentar", "")
        deload = " (Deload)" if training.get("ist_deload") else ""

        lines = [f"Training {datum}{deload} – {dauer} Min"]
        if kommentar:
            lines.append(f"Kommentar: {kommentar}")

        saetze = training.get("saetze", [])
        current_exercise = None
        for satz in saetze:
            uebung = satz.get("uebung", "?")
            if uebung != current_exercise:
                current_exercise = uebung
                lines.append(f"\n{uebung}:")

            gewicht = satz.get("gewicht_kg", 0)
            wdh = satz.get("wiederholungen", 0)
            rpe = satz.get("rpe")
            warmup = " (Aufwärmsatz)" if satz.get("ist_aufwaermsatz") else ""
            rpe_str = f" @RPE {rpe}" if rpe else ""
            lines.append(
                f"  Satz {satz.get('satz_nr', '?')}: {gewicht}kg × {wdh}{rpe_str}{warmup}"
            )

        return "\n".join(lines)

    def format_week(self, trainings: list[dict[str, Any]]) -> str:
        """Formatiert die Wochenübersicht."""
        if not trainings:
            return "Diese Woche: keine Trainings."

        lines = [f"Trainings diese Woche ({len(trainings)}):"]
        for t in trainings:
            datum = t.get("datum", "?")[:10]
            dauer = t.get("dauer_minuten", "?")
            uebungen = t.get("uebungen_anzahl", "?")
            lines.append(f"  {datum} – {dauer} Min, {uebungen} Übungen")

        return "\n".join(lines)

    def format_prs(self, prs: list[dict[str, Any]]) -> str:
        """Formatiert Personal Records."""
        if not prs:
            return "Keine Personal Records in den letzten 30 Tagen."

        lines = ["Personal Records (letzte 30 Tage):"]
        for pr in prs:
            uebung = pr.get("uebung", "?")
            e1rm = pr.get("estimated_1rm", 0)
            gewicht = pr.get("gewicht_kg", 0)
            wdh = pr.get("wiederholungen", 0)
            datum = pr.get("datum", "?")[:10]
            lines.append(f"  {uebung}: {e1rm:.1f}kg 1RM ({gewicht}kg × {wdh}, {datum})")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _get(self, path: str) -> dict[str, Any] | None:
        """GET-Request mit Fehlerbehandlung."""
        try:
            client = self._get_client()
            resp = client.get(path)
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json())
        except Exception as e:
            logger.error("Berry-Gym API Fehler (%s): %s", path, e)
            return None
