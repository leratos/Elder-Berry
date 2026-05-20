"""Resolver fuer Kontakt-/Adress-Eingaben mit Mehrdeutigkeits-Check.

Phase 92 (E0): Ausgliederung aus RouteCommandHandler. Wird sowohl vom
Single-Stop-Handler (Phase 43) als auch vom Multi-Stop-Handler (Phase 92)
genutzt. Macht Mehrdeutigkeit explizit -- ohne diese Struktur wuerde
der Caller bei mehreren gleichnamigen Kontakten still ``results[0]``
nehmen und zum falschen Kontakt fahren.

Aufloesungspfade:
- ``None`` oder Home-Synonym -> Home-Kontakt (Gruppe 'home').
  Multi-Home-Setups sind nicht vorgesehen; der erste Treffer wird
  genutzt (Single-User-Konvention).
- Eingabe mit Ziffern (Hausnummer/PLZ) -> direkte Adresse.
- Kontaktname -> ContactStore-Suche. Bei mehreren Treffern ohne
  exakten Namensgleichstand: ``ambiguous_matches`` setzen statt
  blind ``results[0]`` zurueckzugeben.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.tools.contact_store import ContactStore


# Synonyme fuer "von mir" / "von zuhause" -> Home-Lookup.
HOME_SYNONYMS: frozenset[str] = frozenset(
    {"mir", "zuhause", "daheim", "home", "zu hause", "meiner"},
)

# Heuristik: enthaelt Ziffern + mindestens ein Wort -> wahrscheinlich
# eine direkte Adresse, kein Kontaktname.
_ADDRESS_PATTERN = re.compile(
    r"\d+.*[a-zA-ZäöüÄÖÜß]|[a-zA-ZäöüÄÖÜß].*\d+",
)

# Cap fuer die Kandidatenliste in der Rueckfrage -- die Matrix-Anzeige
# soll nicht in einen Roman ausarten.
_AMBIGUOUS_CAP = 5


@dataclass(frozen=True)
class AddressResolution:
    """Ergebnis einer Kontakt-/Adressauflösung.

    Macht Mehrdeutigkeit explizit. Bei eindeutigem Treffer ist ``address``
    gesetzt und ``ambiguous_matches`` leer. Bei Mehrdeutigkeit ist
    ``address`` ``None`` und ``ambiguous_matches`` enthaelt die Kandidaten-
    Namen fuer die Matrix-Rueckfrage.
    """

    address: str | None = None
    """Aufgeloeste Adresse, oder ``None`` wenn nicht eindeutig auflösbar
    (kein Treffer / kein Adressfeld / Mehrdeutigkeit)."""

    ambiguous_matches: tuple[str, ...] = ()
    """Bei mehreren Treffern: Namen der Kandidaten fuer die Matrix-
    Rueckfrage. Leer bei eindeutigem Treffer oder Miss."""

    candidate_addresses: tuple[str, ...] = ()
    """Bei mehreren Treffern: Adressen der Kandidaten in derselben
    Reihenfolge wie ``ambiguous_matches``. Phase 92 nutzt das, um aus
    der Listen-Disambiguation direkt die richtige Adresse zu ziehen --
    Phase 43 hat das Feld nicht gebraucht."""


def is_home_synonym(name: str | None) -> bool:
    """``True`` wenn ``name`` als 'Home' interpretiert werden soll."""
    if name is None:
        return True
    return name.lower() in HOME_SYNONYMS


def looks_like_address(text: str) -> bool:
    """``True`` wenn ``text`` eher eine Adresse als ein Kontaktname ist.

    Heuristik: Ziffern + Buchstaben (Hausnummer/PLZ).
    """
    return bool(_ADDRESS_PATTERN.search(text))


def resolve_contact_address(
    contact_store: ContactStore,
    user_id: str,
    name: str | None,
) -> AddressResolution:
    """Loest einen Kontaktnamen oder eine direkte Adresse auf.

    Args:
        contact_store: Quelle fuer Kontakt-Lookups (``find_by_group`` +
            ``search``).
        user_id: Eindeutige User-ID fuer Multi-Tenant-Lookups.
        name: Eingabe-Text. ``None`` oder Home-Synonym -> Home-Kontakt.

    Returns:
        ``AddressResolution`` mit eindeutig aufgeloester Adresse, mit
        Ambiguitaets-Kandidaten oder leer (kein Treffer).
    """
    if is_home_synonym(name):
        homes = contact_store.find_by_group(user_id, "home")
        if homes:
            return AddressResolution(address=homes[0].address or None)
        return AddressResolution()

    assert name is not None  # is_home_synonym fing None ab
    # Anfuehrungszeichen entfernen (User schreibt "Am Brendegraben 21")
    cleaned = name.strip().strip('"').strip("'").strip()

    # Direkte Adresse? (enthaelt Ziffern -> Hausnummer oder PLZ)
    if looks_like_address(cleaned):
        return AddressResolution(address=cleaned)

    # Kontaktname -> ContactStore
    results = contact_store.search(user_id, name)
    if not results:
        return AddressResolution()

    if len(results) > 1:
        # Mehrere Treffer -- nur eindeutig wenn GENAU EIN Kontakt
        # den eingegebenen Namen exakt traegt (case-insensitiv).
        # Sonst Rueckfrage statt zum falschen Kontakt fahren.
        query_folded = name.casefold()
        exact = [c for c in results if c.name.casefold() == query_folded]
        if len(exact) == 1:
            return AddressResolution(address=exact[0].address or None)
        capped = results[:_AMBIGUOUS_CAP]
        return AddressResolution(
            ambiguous_matches=tuple(c.name for c in capped),
            candidate_addresses=tuple(c.address or "" for c in capped),
        )

    contact = results[0]
    return AddressResolution(address=contact.address or None)
