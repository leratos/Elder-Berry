"""GymDataClient – Trainingsdaten von Berry-Gym abrufen.

Liest Trainings-Zusammenfassungen, letzte Sessions, Wochen-Übersicht und
Personal Records über die Berry-Gym REST-API (Token-Auth).

Verwendung:
    client = GymDataClient(secret_store=store)
    summary = client.get_summary()
    last = client.get_last_training()
    week = client.get_week()
    prs = client.get_prs()
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://gym.example.com"
REQUEST_TIMEOUT = 10


class GymDataClient:
    """Berry-Gym API Client (read-only, Token-Auth).

    Lazy-Init: httpx.Client wird erst beim ersten Request erstellt.
    Token aus SecretStore: "berry_gym_api_token".
    """

    def __init__(
        self,
        secret_store: SecretStore,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._store = secret_store
        self._base_url = base_url.rstrip("/")
        self._client = None

    def _get_client(self):
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

    def get_summary(self) -> dict | None:
        """Trainings-Zusammenfassung: letztes Training, Woche, Gewicht."""
        return self._get("/api/saleria/summary/")

    def get_last_training(self) -> dict | None:
        """Letztes Training mit allen Sätzen."""
        data = self._get("/api/saleria/last-training/")
        if data:
            return data.get("training")
        return None

    def get_week(self) -> list[dict]:
        """Trainings der letzten 7 Tage."""
        data = self._get("/api/saleria/week/")
        if data:
            return data.get("trainings", [])
        return []

    def get_prs(self) -> list[dict]:
        """Personal Records (Top 1RM pro Übung, letzte 30 Tage)."""
        data = self._get("/api/saleria/prs/")
        if data:
            return data.get("prs", [])
        return []

    def format_summary(self, summary: dict) -> str:
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

    def format_last_training(self, training: dict) -> str:
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
            lines.append(f"  Satz {satz.get('satz_nr', '?')}: {gewicht}kg × {wdh}{rpe_str}{warmup}")

        return "\n".join(lines)

    def format_week(self, trainings: list[dict]) -> str:
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

    def format_prs(self, prs: list[dict]) -> str:
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

    def _get(self, path: str) -> dict | None:
        """GET-Request mit Fehlerbehandlung."""
        try:
            client = self._get_client()
            resp = client.get(path)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("Berry-Gym API Fehler (%s): %s", path, e)
            return None
