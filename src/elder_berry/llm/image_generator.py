"""ImageGenerator -- austauschbare Bildgenerierung (Phase 111, E1).

Die ABC trennt den Portrait-Modus vom konkreten Anbieter: Heute erzeugt der
Rahmen-Pi die Bilder selbst ueber OpenRouter
(:class:`~elder_berry.llm.openrouter_image_generator.OpenRouterImageGenerator`),
spaeter soll der Bot das uebernehmen (Variante B, #1461). Der Wechsel aendert
nur das Wiring.

Ergebniskategorien nach Konzept Phase 111, Ae1 (#1474):

* ``OK``               -- ein Bild ist da.
* ``REFUSED``          -- der Anbieter lehnt den Inhalt ab (Moderation).
* ``ERROR``            -- alles andere: Parameter, Netz, Provider, 200 ohne Bild.
* ``TIMEOUT``          -- der Client hat das Warten abgebrochen.
* ``CREDIT_EXHAUSTED`` -- das Kreditlimit ist erreicht (HTTP 402). Die Sperre
  "keine weiteren Aufrufe bis zum Neustart" liegt bewusst NICHT im Generator,
  sondern im aufrufenden Modus (E5). Der Generator ist zustandslos.

Datenschutz: ``ImageRequest`` enthaelt Gaestefotos, ``ImageResult`` das
generierte Bild. Beide blenden die Bytes aus ``repr()`` aus, damit ein
versehentliches ``logger.debug("%s", request)`` keine Bilddaten ins Log
schreibt (Konzept §4.6, Ae2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class ImageStatus(Enum):
    """Ergebniskategorie einer Bildgenerierung (Ae1, #1474)."""

    OK = "ok"
    REFUSED = "refused"
    ERROR = "error"
    TIMEOUT = "timeout"
    CREDIT_EXHAUSTED = "credit_exhausted"


@dataclass(frozen=True)
class ImageRequest:
    """Eine Generierungsanfrage.

    Attributes:
        prompt: Vollstaendiger Prompt (Szene + fester Kern), nicht leer.
        input_images: Referenzbilder als kodierte Bytes (z.B. JPEG). Werden
            nie geloggt und tauchen nicht in ``repr()`` auf.
        input_media_type: MIME-Typ aller ``input_images``.
    """

    prompt: str
    input_images: tuple[bytes, ...] = field(default=(), repr=False)
    input_media_type: str = "image/jpeg"

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("ImageRequest.prompt darf nicht leer sein.")
        if any(not image for image in self.input_images):
            raise ValueError("ImageRequest.input_images enthaelt ein leeres Bild.")


@dataclass(frozen=True)
class ImageResult:
    """Ergebnis einer Generierung.

    Attributes:
        status: Ergebniskategorie.
        duration_s: Wanduhrdauer des Aufrufs in Sekunden.
        image_bytes: Dekodiertes Bild bei ``OK``, sonst ``None``. Nicht in
            ``repr()``.
        media_type: MIME-Typ des Bildes, falls bekannt.
        cost_usd: Kosten laut Anbieter (``usage.cost``), falls geliefert.
        http_status: HTTP-Status, falls eine Antwort kam.
        error_code: Fehlercode des Anbieters (``error.code``) als String.
        detail: Kurze, bereinigte Beschreibung fuer Diagnose (ohne
            Request-/Response-Body, ohne ``flagged_input``).
    """

    status: ImageStatus
    duration_s: float
    image_bytes: bytes | None = field(default=None, repr=False)
    media_type: str | None = None
    cost_usd: float | None = None
    http_status: int | None = None
    error_code: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        """True genau dann, wenn ein Bild vorliegt."""
        return self.status is ImageStatus.OK and self.image_bytes is not None


class ImageGenerator(ABC):
    """Erzeugt ein Bild aus Prompt und Referenzbildern.

    Implementierungen werfen bei Anbieter- oder Netzfehlern KEINE Exception,
    sondern liefern ein :class:`ImageResult` mit passender Kategorie. Nur
    Programmierfehler (z.B. falsche Konfiguration im Konstruktor) duerfen
    werfen.
    """

    @abstractmethod
    def generate(self, request: ImageRequest) -> ImageResult:
        """Fuehrt genau eine Generierung aus (blockierend)."""
