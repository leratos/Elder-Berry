"""Notiz-Kategorien -- Whitelist + Default fuer Nextcloud Notes (Phase 91-B).

Categories sind die strukturelle Hauptschublade einer Notiz (single-valued).
Die Whitelist ist bewusst eine Soft-Convention, kein Hard-Block: der
NoteCommandHandler (Etappe 3) akzeptiert auch unbekannte Categories und
loggt dazu lediglich eine Warning. Damit wird Tippfehler-Schutz zu einer
Hilfe statt zu einer Wartungslast.

Konzept: docs/concepts/note-nextcloud-replace.md Paragraph 3.4.
"""

from __future__ import annotations

DEFAULT_CATEGORY = "Allgemein"
"""Category fuer ``notiz: ...`` ohne explizite Kategorie-Angabe."""

KNOWN_CATEGORIES: frozenset[str] = frozenset(
    {
        "Allgemein",
        "Einkauf",
        "Projekt",
        "Arbeit",
        "Privat",
    }
)
"""Bekannte Categories (Whitelist). Single-Word-Begriffe -- der
Command-Pattern-Trenner (``notiz <Kategorie>: ...``) erlaubt keine
Mehr-Wort-Categories. Override mit unbekannter Category ist erlaubt
(Warning statt Fehler)."""


def canonical_category(raw: str) -> tuple[str, bool]:
    """Bringt eine Kategorie-Eingabe auf die kanonische Schreibweise.

    Der Command-Pattern liefert die Kategorie so, wie der Nutzer sie
    getippt hat (``einkauf``, ``EINKAUF``, ``Einkauf``). Nextcloud
    behandelt Kategorien case-sensitiv -- ohne Normalisierung landet
    ``einkauf`` als eigene Schublade neben ``Einkauf``.

    Args:
        raw: Rohe Kategorie-Eingabe aus dem Command (wird gestrippt).

    Returns:
        ``(category, is_known)``. Bei case-insensitivem Treffer in
        :data:`KNOWN_CATEGORIES` die kanonische Schreibweise + ``True``.
        Sonst die gestrippte Eingabe unveraendert + ``False`` -- das ist
        der erlaubte Override-Fall (Handler loggt dann eine Warning).
    """
    cleaned = raw.strip()
    folded = cleaned.casefold()
    for known in KNOWN_CATEGORIES:
        if known.casefold() == folded:
            return known, True
    return cleaned, False
