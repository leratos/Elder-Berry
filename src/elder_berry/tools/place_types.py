"""place_types -- Validierung/Normalisierung von Google-Place-Typen und
Reisemodi fuer die Umkreissuche (Phase 97, R2-C1/C2).

Single source of truth fuer zwei Garantien, die der Code (nicht der LLM)
durchsetzt:

1. ``normalize_included_type()`` -- der vom LLM vorgeschlagene
   ``includedType`` darf NUR ein echter Table-A-Typ der Places API (New)
   sein. Erfundene/Table-B-Werte (``shisha_shop``) wuerden bei
   ``strictTypeFiltering=True`` zu API-Fehler oder leerem Ergebnis fuehren,
   noch BEVOR der Freitext-Fallback greift. Unbekannt -> ``None`` (reiner
   Freitext + ``exclude_types``).

2. ``normalize_travel_mode()`` -- Synonyme/Lokalisiertes (``car``, ``auto``,
   ``foot``, ``zu fuss``, ``Fahrrad``) auf das kanonische Vokabular mappen.
   Das Vokabular ist ``MapsLinkBuilder.VALID_TRAVEL_MODES`` (B3, keine
   Duplikation). Unbekannt -> ``None`` (Handler stellt Rueckfrage); KEIN
   ``KeyError`` spaeter im ``RADIUS_BY_MODE``-Lookup.
"""

from __future__ import annotations

from elder_berry.tools.maps_link_builder import VALID_TRAVEL_MODES

# ---------------------------------------------------------------------------
# Table A (includedType) -- kuratierte Teilmenge der Places-API-(New)-Typen.
# ---------------------------------------------------------------------------
#
# BEWUSST kuratiert, nicht vollstaendig: nur Typen, die fuer die Nearby-
# Suche (Laeden, Gastro, Services) realistisch vom LLM vorgeschlagen werden
# UND echte Table-A-Werte sind. Erweiterbar bei Bedarf. Was NICHT drin ist
# (z.B. ein "shisha_shop"), wird zu included_type=None -> Freitext-Pfad --
# genau der typlose Dichtefall aus Konzept §4.1.
SUPPORTED_INCLUDED_TYPES: frozenset[str] = frozenset(
    {
        # Gastronomie / Ausgehen
        "restaurant",
        "bar",
        "cafe",
        "bakery",
        "meal_takeaway",
        "meal_delivery",
        "night_club",
        # Lebensmittel / Drogerie / Apotheke
        "supermarket",
        "grocery_store",
        "convenience_store",
        "liquor_store",
        "pharmacy",
        "drugstore",
        # Fach- und Einzelhandel
        "store",
        "department_store",
        "shopping_mall",
        "clothing_store",
        "shoe_store",
        "electronics_store",
        "hardware_store",
        "home_goods_store",
        "furniture_store",
        "book_store",
        "pet_store",
        "sporting_goods_store",
        "florist",
        "jewelry_store",
        # Services
        "gas_station",
        "bank",
        "atm",
    }
)


# Bekannte Unter-/Geschwistertypen, die ein generischer Ausschluss MIT-meinen
# sollte. Places liefert z.B. Shisha-Lokale teils als spezifisches
# ``hookah_bar`` OHNE den generischen ``bar``-Typ -- ein exakter String-
# Vergleich auf ``exclude_types=("bar",)`` wuerde sie sonst durchlassen
# (Codex-Review PR #302). Bewusst kuratiert, erweiterbar.
_EXCLUDE_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "bar": ("hookah_bar", "wine_bar", "pub", "bar_and_grill"),
    "restaurant": ("fine_dining_restaurant", "fast_food_restaurant"),
}


def expand_exclude_types(types: tuple[str, ...]) -> frozenset[str]:
    """Erweitert eine Ausschlussliste um bekannte Unter-/Geschwistertypen.

    Lowercase-normalisiert. Garantiert clientseitig (kein LLM-Verlass), dass
    z.B. ``bar`` auch ``hookah_bar`` faengt -- der Kern-Wert des Kategorie-
    Filters (Konzept §4.1).
    """
    out: set[str] = set()
    for raw in types:
        base = raw.strip().lower()
        if not base:
            continue
        out.add(base)
        out.update(_EXCLUDE_EXPANSIONS.get(base, ()))
    return frozenset(out)


def normalize_included_type(value: str | None) -> str | None:
    """``includedType``-Vorschlag gegen die Table-A-Whitelist pruefen.

    Args:
        value: vom LLM vorgeschlagener Typ (oder ``None``).

    Returns:
        Den lowercase-normalisierten Typ, wenn er in
        ``SUPPORTED_INCLUDED_TYPES`` liegt; sonst ``None``.
    """
    if not value:
        return None
    candidate = value.strip().lower()
    if candidate in SUPPORTED_INCLUDED_TYPES:
        return candidate
    return None


# ---------------------------------------------------------------------------
# Reisemodus-Synonyme -> kanonisches Vokabular (VALID_TRAVEL_MODES)
# ---------------------------------------------------------------------------
#
# Keys lowercase + Leerzeichen als "_" (Eingabe wird so normalisiert).
# Die Werte MUESSEN in VALID_TRAVEL_MODES liegen -- per Test abgesichert.
_TRAVEL_MODE_SYNONYMS: dict[str, str] = {
    # driving
    "driving": "driving",
    "drive": "driving",
    "car": "driving",
    "auto": "driving",
    "pkw": "driving",
    "wagen": "driving",
    "mit_dem_auto": "driving",
    # walking
    "walking": "walking",
    "walk": "walking",
    "foot": "walking",
    "on_foot": "walking",
    "zu_fuss": "walking",
    "zufuss": "walking",
    "fuss": "walking",
    "laufen": "walking",
    # bicycling
    "bicycling": "bicycling",
    "bicycle": "bicycling",
    "bike": "bicycling",
    "biking": "bicycling",
    "cycling": "bicycling",
    "fahrrad": "bicycling",
    "rad": "bicycling",
    "mit_dem_rad": "bicycling",
    # transit
    "transit": "transit",
    "public_transit": "transit",
    "oepnv": "transit",
    "öpnv": "transit",
    "bahn": "transit",
    "bus": "transit",
    "zug": "transit",
    "tram": "transit",
}


def normalize_travel_mode(value: str | None) -> str | None:
    """Reisemodus (inkl. Synonyme/Lokalisiertes) auf das Vokabular mappen.

    Args:
        value: vom LLM gelieferter Modus (``"car"``, ``"zu fuss"``,
            ``"driving"`` ...) oder ``None``.

    Returns:
        Einen Wert aus ``VALID_TRAVEL_MODES`` oder ``None``, wenn der
        Modus unbekannt ist (-> Handler fragt nach, kein KeyError).
    """
    if not value:
        return None
    # ``ß`` -> ``ss`` normalisieren, damit die normale deutsche Schreibung
    # "zu Fuß" denselben Key wie "zu fuss" ergibt (sonst bliebe to_query()
    # in der Rueckfrage haengen).
    key = (
        value.strip()
        .lower()
        .replace("ß", "ss")
        .replace(" ", "_")
        .replace("-", "_")
    )
    mapped = _TRAVEL_MODE_SYNONYMS.get(key)
    if mapped is not None and mapped in VALID_TRAVEL_MODES:
        return mapped
    # Direkter kanonischer Treffer (falls jemand das Vokabular erweitert,
    # ohne ein Synonym zu hinterlegen).
    if key in VALID_TRAVEL_MODES:
        return key
    return None
