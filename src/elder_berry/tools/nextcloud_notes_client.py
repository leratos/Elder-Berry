"""NextcloudNotesClient -- Nextcloud Notes API v1 als Notizen-Backend.

Reiner HTTP-API-Wrapper ohne State und ohne lokalen Cache, analog
``google_calendar.py`` / ``caldav_calendar.py``. Single Source of Truth
fuer Notizen ist die Nextcloud-Instanz.

Credentials kommen aus dem SecretStore (nextcloud_url, nextcloud_user,
nextcloud_app_password -- identisch mit CalDAV/CardDAV, kein eigener Key).

Endpoints relativ zu ``<base>/index.php/apps/notes/api/v1/``:
    GET    notes            -- alle Notizen (optional ?category=)
    GET    notes/<id>       -- einzelne Notiz
    POST   notes            -- neue Notiz
    PUT    notes/<id>       -- Notiz aktualisieren
    DELETE notes/<id>       -- Notiz loeschen

Verwendung:
    client = NextcloudNotesClient(secret_store=store)
    notes = client.list_notes(category="Einkauf", limit=20)
    note = client.create_note("Milch kaufen", category="Einkauf")
    client.delete_note(note.id)

Konzept: docs/concepts/note-nextcloud-replace.md Paragraph 3.1 / 3.3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

# API-Pfad relativ zur Nextcloud-Basis-URL. Endet ohne Slash; _api_base
# haengt den Trenner an, damit httpx den Request-Pfad sauber anjoint.
_API_PATH = "index.php/apps/notes/api/v1"

_EPOCH_UTC = datetime.fromtimestamp(0, tz=timezone.utc)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class NextcloudNotesError(Exception):
    """Fehler bei einem Nextcloud-Notes-API-Aufruf.

    ``status_code`` ist gesetzt, wenn der Server mit einem HTTP-Fehler
    geantwortet hat (401/404/500 ...); bei Transport-/Parsing-Fehlern
    bleibt es ``None``.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NextcloudNote:
    """Eine Notiz aus der Nextcloud Notes API.

    ``title`` wird vom Server aus der ersten Content-Zeile abgeleitet und
    beim Schreiben (POST/PUT) NICHT mitgeschickt. ``etag`` und ``favorite``
    werden bewusst nicht abgebildet -- der Single-User-Use-Case braucht sie
    nicht (Konzept Paragraph 3.1).
    """

    id: int
    content: str
    category: str
    modified: datetime
    title: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class NextcloudNotesClient:
    """HTTP-Client fuer die Nextcloud Notes API v1.

    Zustandslos: jeder Aufruf oeffnet einen eigenen ``httpx.Client``.
    Bei Transport-Fehlern wird der Request einmal wiederholt (analog
    CalDAVTaskClient, CLAUDE.md-Regel zu externen API-Aufrufen).
    """

    # Transport-Level-Fehler (Connect/Timeout/Network/Protocol) sind
    # retry-faehig; HTTP-Status-Fehler (httpx.HTTPStatusError) NICHT --
    # die behandelt _request ueber den status_code-Check.
    _RETRIABLE_ERRORS = (httpx.TransportError,)

    def __init__(self, secret_store: SecretStore, timeout: float = 10.0) -> None:
        """
        Args:
            secret_store: Quelle fuer nextcloud_url / _user / _app_password.
            timeout: HTTP-Timeout in Sekunden pro Request.
        """
        self._url = secret_store.get_or_none("nextcloud_url")
        self._user = secret_store.get_or_none("nextcloud_user")
        self._password = secret_store.get_or_none("nextcloud_app_password")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Verbindung
    # ------------------------------------------------------------------

    @property
    def _has_credentials(self) -> bool:
        return bool(self._url and self._user and self._password)

    @property
    def _api_base(self) -> str:
        """Basis-URL der Notes-API, mit abschliessendem Slash."""
        url = (self._url or "").rstrip("/")
        return f"{url}/{_API_PATH}/"

    @property
    def _auth(self) -> tuple[str, str]:
        return (self._user or "", self._password or "")

    def is_available(self) -> bool:
        """Prueft, ob Credentials vorhanden und der Server erreichbar ist.

        Wird vom Selfcheck-Handler genutzt. Schluckt jeden Fehler und
        gibt nur ``True``/``False`` zurueck.
        """
        if not self._has_credentials:
            return False
        try:
            self._request("GET", "notes")
            return True
        except NextcloudNotesError:
            return False

    def _send(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None,
        json_body: dict[str, str] | None,
    ) -> httpx.Response:
        """Ein einzelner HTTP-Request mit frischem Client."""
        with httpx.Client(
            base_url=self._api_base,
            auth=self._auth,
            timeout=self._timeout,
        ) as client:
            return client.request(method, path, params=params, json=json_body)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Fuehrt einen API-Request aus -- mit 1x Retry + Status-Pruefung.

        Raises:
            NextcloudNotesError: Credentials fehlen, Server nicht erreichbar
                (nach Retry) oder HTTP-Status >= 400.
        """
        if not self._has_credentials:
            raise NextcloudNotesError("Nextcloud-Zugangsdaten nicht konfiguriert")

        try:
            resp = self._send(method, path, params, json_body)
        except self._RETRIABLE_ERRORS as exc:
            logger.warning(
                "Nextcloud Notes Transport-Fehler, Retry mit neuer Verbindung: %s",
                exc,
            )
            try:
                resp = self._send(method, path, params, json_body)
            except self._RETRIABLE_ERRORS as exc2:
                raise NextcloudNotesError(
                    "Nextcloud Notes nicht erreichbar: %s" % exc2
                ) from exc2

        if resp.status_code >= 400:
            logger.error(
                "Nextcloud Notes API-Fehler: %s %s -> HTTP %d",
                method,
                path,
                resp.status_code,
            )
            raise NextcloudNotesError(
                "Nextcloud Notes API-Fehler (HTTP %d)" % resp.status_code,
                status_code=resp.status_code,
            )
        return resp

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _json(resp: httpx.Response) -> Any:
        """Dekodiert den JSON-Body, wandelt Parse-Fehler in Domain-Error."""
        try:
            return resp.json()
        except ValueError as exc:
            raise NextcloudNotesError(
                "Nextcloud Notes lieferte ungueltiges JSON: %s" % exc
            ) from exc

    @staticmethod
    def _parse_note(data: Any) -> NextcloudNote:
        """Baut ein NextcloudNote aus einem API-Notiz-Objekt.

        Raises:
            NextcloudNotesError: Unerwartetes Format (R5 -- Exception statt
                Crash bei kaputtem Response).
        """
        if not isinstance(data, dict):
            raise NextcloudNotesError(
                "Unerwartetes Notiz-Format: %s" % type(data).__name__
            )
        try:
            note_id = int(data["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NextcloudNotesError("Notiz ohne gueltige id: %s" % exc) from exc

        try:
            modified = datetime.fromtimestamp(
                int(data.get("modified", 0)),
                tz=timezone.utc,
            )
        except (TypeError, ValueError, OSError, OverflowError):
            modified = _EPOCH_UTC

        return NextcloudNote(
            id=note_id,
            content=str(data.get("content", "")),
            category=str(data.get("category", "")),
            modified=modified,
            title=str(data.get("title", "")),
        )

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def list_notes(
        self,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[NextcloudNote]:
        """Alle Notizen, optional serverseitig nach Kategorie gefiltert.

        Sortiert nach ``modified`` absteigend (neueste zuerst).

        Args:
            category: Wenn gesetzt, ``?category=`` am Request (Server-Filter).
            limit: Maximale Anzahl Notizen nach der Sortierung.
        """
        params: dict[str, str] = {}
        if category:
            params["category"] = category

        resp = self._request("GET", "notes", params=params or None)
        raw = self._json(resp)
        if not isinstance(raw, list):
            raise NextcloudNotesError("GET /notes lieferte keine Liste")

        notes = [self._parse_note(item) for item in raw]
        notes.sort(key=lambda n: n.modified, reverse=True)
        if limit is not None:
            notes = notes[:limit]
        return notes

    def get_note(self, note_id: int) -> NextcloudNote:
        """Eine einzelne Notiz per ID."""
        resp = self._request("GET", f"notes/{int(note_id)}")
        return self._parse_note(self._json(resp))

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[NextcloudNote]:
        """Volltextsuche per Python-Substring-Filter (case-insensitive).

        Die Notes-API hat keinen Search-Endpoint -- es wird GET /notes
        (optional mit category-Filter) geholt und der Content lokal
        gefiltert. Akzeptiert fuer <1000 Notizen (Konzept Paragraph 2).

        Args:
            query: Such-Substring (case-insensitive auf dem Content).
            category: Optionaler serverseitiger Kategorie-Vorfilter.
            limit: Maximale Anzahl Treffer.
        """
        notes = self.list_notes(category=category)
        needle = query.casefold()
        matched = [n for n in notes if needle in n.content.casefold()]
        if limit is not None:
            matched = matched[:limit]
        return matched

    def list_categories(self) -> list[str]:
        """Aktuell genutzte Kategorien aus dem Server-Bestand.

        Dedupliziert und alphabetisch sortiert. Leere Kategorie ("") wird
        ausgelassen. Die Notes-API hat keinen Kategorie-Endpoint -- der
        Bestand wird ueber GET /notes aggregiert.
        """
        notes = self.list_notes()
        categories = {n.category for n in notes if n.category}
        return sorted(categories)

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def create_note(
        self,
        content: str,
        category: str | None = None,
    ) -> NextcloudNote:
        """Erstellt eine neue Notiz.

        ``title`` wird NICHT mitgeschickt -- der Server leitet ihn aus der
        ersten Content-Zeile ab. Ohne ``category`` bleibt die Server-Default-
        Kategorie leer (Default ``Allgemein`` setzt der Handler in Etappe 3).
        """
        body: dict[str, str] = {"content": content}
        if category:
            body["category"] = category
        resp = self._request("POST", "notes", json_body=body)
        return self._parse_note(self._json(resp))

    def update_note(
        self,
        note_id: int,
        content: str | None = None,
        category: str | None = None,
    ) -> NextcloudNote:
        """Aktualisiert eine Notiz (partielles Update).

        Es werden nur die uebergebenen Felder geschickt. Mindestens eines
        von ``content`` / ``category`` muss gesetzt sein.

        Raises:
            ValueError: Weder content noch category uebergeben.
        """
        body: dict[str, str] = {}
        if content is not None:
            body["content"] = content
        if category is not None:
            body["category"] = category
        if not body:
            raise ValueError("update_note braucht content oder category")

        resp = self._request("PUT", f"notes/{int(note_id)}", json_body=body)
        return self._parse_note(self._json(resp))

    def delete_note(self, note_id: int) -> None:
        """Loescht eine Notiz per ID."""
        self._request("DELETE", f"notes/{int(note_id)}")
        logger.info("Notiz geloescht: #%d", int(note_id))
