# Phase 92 – Multi-Stop-Routing (Konzept)

## Ziel

Saleria erweitern um Routen mit **mehreren Stops**, **Reihenfolge-Optimierung**
und **POI-Suche entlang der Route**. Die heutige Single-Stop-Routenplanung
(Phase 43) bleibt unverändert; ein neuer Handler übernimmt Multi-Stop-Fälle.

**Beispiel-Dialog:**

```
User:    "Ich muss nach Leipzig Hauptbahnhof, vorher muss ich noch Lisa
          und Andrea abholen. Auf dem Weg möchte ich noch bei Kaufland
          einkaufen."

Saleria: "Mehrere Lisas im Kontaktbuch. Welche?
          1) Lisa Müller (Hauptstr. 12, Leipzig)
          2) Lisa Schmidt (Mozartweg 4, Markranstädt)"

User:    "1"

Saleria: "Drei Kauflände entlang der Route. Welcher?
          1) Markranstädt – Umweg +2 Min
          2) Leipzig-Grünau – Umweg +5 Min
          3) Leipzig-Lindenau – Umweg +8 Min"

User:    "2"

Saleria: "Route geplant:
          Home → Lisa Müller → Andrea → Kaufland Grünau → Leipzig Hbf
          Gesamt: 48 km, ca. 1h 12min
          → [Google Maps öffnen]"
```

## Bezug zu Phase 43 – was bleibt, was kommt neu

| Komponente | Status in Phase 92 |
|------------|---------------------|
| `RoutePlanner` (Single-Stop, Google Directions) | **unverändert** – wird weiter genutzt |
| `RouteCommandHandler` (Single-Stop) | **unverändert** – fängt 1-Ziel-Anfragen ab |
| `ContactStore` + `_resolve_address()` | **wiederverwendet** – Logik in Util ausgliedern |
| `parse_arrival_time()` | **wiederverwendet** – aus `route_commands.py` |
| `RouteProvider`-Interface | **neu** (abstrakte Basisklasse) |
| `GoogleMapsRouteProvider` | **neu** – kapselt Google-spezifische API-Calls |
| `MultiStopRoutePlanner` | **neu** – Multi-Waypoint + Optimierung + POI-Search |
| `RouteIntentParser` | **neu** – NLU-Schicht (Pattern + Sonnet-Tool-Call) |
| `MultiStopRouteCommandHandler` | **neu** – Orchestrator + Disambiguierung |

**Wichtig**: Phase 92 fasst `RoutePlanner` (aus Phase 43) **nicht** an. Wenn
sich später herausstellt, dass Single- und Multi-Stop denselben Provider
nutzen sollten, ist das ein eigener Refactor-Schritt.

## Kritischer Bugfix-Hinweis (NICHT Teil dieser Phase)

`RouteCommandHandler._resolve_address()` nimmt aus `contact_store.search()`
**immer `results[0]`**, ohne Mehrdeutigkeit zu prüfen. Bei mehreren
gleichnamigen Kontakten fährt Saleria heute still zum falschen.

Für Single-Stop ist das ein Bug; für Multi-Stop wäre es gefährlicher (mehrere
falsche Stops in einer Route). Phase 92 löst das Problem **nur für den neuen
Handler** über `RouteIntentParser` und Listen-Disambiguierung. Der existierende
Single-Stop-Handler bleibt mit dem Bug — Fix dort gehört in einen separaten
Bugfix-Branch.

## Architektur

### Klassen-Übersicht

```
                  ┌───────────────────────────────┐
                  │ MultiStopRouteCommandHandler  │
                  │  (comms/commands)             │
                  └───────────────┬───────────────┘
                                  │ orchestriert
              ┌───────────────────┼──────────────────────┐
              ▼                   ▼                      ▼
   ┌────────────────────┐ ┌──────────────────┐ ┌────────────────────┐
   │ RouteIntentParser  │ │ ContactStore     │ │ MultiStopRoute     │
   │ (tools/)           │ │ (bestehend)      │ │ Planner (tools/)   │
   │  Pattern + Sonnet  │ │                  │ │                    │
   └────────────────────┘ └──────────────────┘ └──────────┬─────────┘
                                                          │
                                                          ▼
                                              ┌────────────────────┐
                                              │ RouteProvider      │
                                              │ (abstrakt)         │
                                              └──────────┬─────────┘
                                                         ▼
                                              ┌────────────────────┐
                                              │ GoogleMapsRoute    │
                                              │ Provider           │
                                              └────────────────────┘
```

### Dateien (alle neu)

| Datei | Klasse | Zeilen (Schätzung) |
|-------|--------|---------------------|
| `tools/route_provider.py` | `RouteProvider` (ABC) | ~80 |
| `tools/google_maps_route_provider.py` | `GoogleMapsRouteProvider` | ~250 |
| `tools/multi_stop_route_planner.py` | `MultiStopRoutePlanner` | ~150 |
| `tools/route_intent_parser.py` | `RouteIntentParser` | ~250 |
| `comms/commands/multi_stop_route_commands.py` | `MultiStopRouteCommandHandler` | ~300 |

Plus Tests: ~5 neue `tests/test_*.py`-Dateien, geschätzt 60–80 Tests gesamt.

## RouteProvider-Interface (`tools/route_provider.py`)

Abstrakte Basisklasse, die alle Operationen beschreibt, die ein Routing-
Backend (Google, OSM, ...) erfüllen muss. Ziel: spätere OSM-Implementierung
ohne Code-Änderung an Handler / Parser / Planner.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class Stop:
    """Ein Stop in der Route."""
    address: str            # Auflösbare Adresse oder "lat,lng"
    label: str              # Anzeigename ("Lisa Müller", "Kaufland Grünau")

@dataclass(frozen=True)
class MultiStopRouteResult:
    """Ergebnis einer Multi-Stop-Routenabfrage."""
    ordered_stops: list[Stop]      # Reihenfolge nach Optimierung
    total_duration_seconds: int
    total_duration_text: str       # "1 Stunde 12 Minuten"
    total_distance_text: str       # "48,2 km"
    leg_durations_seconds: list[int]   # Pro Leg eine Dauer
    encoded_polyline: str          # Für POI-Search-Along-Route
    maps_link: str

@dataclass(frozen=True)
class POICandidate:
    """Ein POI-Kandidat entlang einer Route."""
    name: str                      # "Kaufland Grünau"
    address: str
    place_id: str
    detour_seconds: int            # Umweg gegenüber Direktroute
    rating: float | None

class RouteProvider(ABC):
    """Interface für Routing-Backends."""

    @abstractmethod
    def compute_multi_stop_route(
        self,
        origin: Stop,
        waypoints: list[Stop],
        destination: Stop,
        optimize_order: bool = True,
    ) -> MultiStopRouteResult:
        """Routet Origin → Waypoints (ggf. neu sortiert) → Destination."""

    @abstractmethod
    def search_poi_along_route(
        self,
        encoded_polyline: str,
        category: str,           # "supermarket", "fuel", "pharmacy"
        name_hint: str | None,   # "Kaufland" (für Filterung)
        max_results: int = 5,
    ) -> list[POICandidate]:
        """Findet POIs in einem Korridor um eine bestehende Route."""

    @abstractmethod
    def close(self) -> None:
        """Ressourcen freigeben (HTTP-Client schließen)."""
```

**Begründung**: `compute_multi_stop_route()` braucht eine bestehende Route,
um `search_poi_along_route()` aufrufen zu können. Das macht die Reihenfolge
in der Orchestrierung deterministisch: erst Kontakte → erste Route → POIs
suchen → zweite Route mit POIs.

## GoogleMapsRouteProvider (`tools/google_maps_route_provider.py`)

Implementiert `RouteProvider` über zwei Google-APIs:

| Operation | API | Endpoint |
|-----------|-----|----------|
| Multi-Stop-Routing | Directions API v1 (Legacy, JSON) | `/maps/api/directions/json` |
| POI-Search-Along-Route | Places API v1 (REST) | `/v1/places:searchText` |

### Directions-API-Aufruf

```
GET https://maps.googleapis.com/maps/api/directions/json?
    origin=Musterstr. 5, Berlin
    &destination=Leipzig Hauptbahnhof
    &waypoints=optimize:true|Lisa-Adr|Andrea-Adr|Kaufland-Adr
    &mode=driving
    &language=de
    &units=metric
    &key=<API_KEY>
```

**Wichtig**: `optimize:true` ist explizit gesetzt. Die API liefert in der
Response `waypoint_order` zurück (z.B. `[1, 0, 2]`) — daraus die neue
Reihenfolge ableiten. **Origin und Destination werden NICHT vertauscht**,
nur die Waypoints dazwischen.

### Places-API-Aufruf (Search Along Route)

```
POST https://places.googleapis.com/v1/places:searchText
Headers:
  X-Goog-Api-Key: <API_KEY>
  X-Goog-FieldMask: places.id,places.displayName,places.formattedAddress,
                    places.rating,places.routingSummaries
Body:
  {
    "textQuery": "Kaufland",
    "searchAlongRouteParameters": {
      "polyline": { "encodedPolyline": "<polyline>" }
    },
    "maxResultCount": 10
  }
```

Die `routingSummaries`-Antwort enthält pro POI einen Umweg-Wert (Detour in
Sekunden), den wir direkt in `POICandidate.detour_seconds` mappen.

### Maps-Link-Generierung (Multi-Stop)

```
https://www.google.com/maps/dir/?
    api=1
    &origin=<Origin>
    &destination=<Destination>
    &waypoints=<Stop1>|<Stop2>|<Stop3>
    &travelmode=driving
```

**Detail**: URL-Encoding mit `urlencode(quote_via=quote_plus)`, sonst brechen
Umlaute und Sonderzeichen. Pipes (`|`) zwischen Waypoints **nicht**
URL-encoden (das macht Google selbst, sonst funktioniert der Link nicht).

### Fehlerfälle

| API-Response | Verhalten |
|---|---|
| `status=ZERO_RESULTS` | `RouteError("Keine Route gefunden")` |
| `status=OVER_QUERY_LIMIT` | `RouteError("API-Limit erreicht")` |
| `status=REQUEST_DENIED` | `RouteError("API-Key ungültig/blockiert")` |
| HTTP 5xx | `httpx.HTTPStatusError` durchreichen |
| Timeout (>10s) | `httpx.TimeoutException` durchreichen |
| Places-Antwort leer | leere Liste zurückgeben, kein Fehler |

## MultiStopRoutePlanner (`tools/multi_stop_route_planner.py`)

Thin Wrapper um `RouteProvider`. Hier liegt Logik, die **nicht**
provider-spezifisch ist (z.B. Detour-Filtering, Antwort-Formatierung).

```python
class MultiStopRoutePlanner:
    def __init__(self, provider: RouteProvider):
        self._provider = provider

    def plan(
        self,
        origin: Stop,
        people_stops: list[Stop],   # Kontakte/Adressen, vom User vorgegeben
        destination: Stop,
        poi_request: POIRequest | None = None,
    ) -> PlannedRoute:
        """
        Zwei-Phasen-Routing:
          1) Vor-Route ohne POI (zur Polyline-Gewinnung)
          2) POI-Suche entlang der Vor-Route (wenn poi_request gesetzt)
          3) Final-Route mit POI als zusätzlichem Waypoint
        Wenn kein poi_request: nur Schritt 1, mit optimize_order=True.
        """
        # Schritt 1: Basis-Route
        base = self._provider.compute_multi_stop_route(
            origin, people_stops, destination, optimize_order=True
        )
        if poi_request is None:
            return PlannedRoute(route=base, poi_candidates=[])

        # Schritt 2: POI-Suche entlang der Basis-Route
        candidates = self._provider.search_poi_along_route(
            base.encoded_polyline,
            poi_request.category,
            poi_request.name_hint,
            max_results=poi_request.max_results,
        )
        # Filtern: nur Kandidaten mit Detour < max_detour_seconds
        filtered = [c for c in candidates
                    if c.detour_seconds <= poi_request.max_detour_seconds]
        # Sortieren: nach Detour aufsteigend
        filtered.sort(key=lambda c: c.detour_seconds)

        return PlannedRoute(route=base, poi_candidates=filtered[:5])

    def finalize_with_poi(
        self, origin, people_stops, destination, chosen_poi: POICandidate
    ) -> MultiStopRouteResult:
        """Nach POI-Auswahl: finale Route mit POI als Waypoint berechnen."""
        all_waypoints = people_stops + [
            Stop(address=chosen_poi.address, label=chosen_poi.name)
        ]
        return self._provider.compute_multi_stop_route(
            origin, all_waypoints, destination, optimize_order=True,
        )
```

```python
@dataclass(frozen=True)
class POIRequest:
    category: str
    name_hint: str | None
    max_results: int = 10
    max_detour_seconds: int = 600   # 10 Min Default

@dataclass(frozen=True)
class PlannedRoute:
    route: MultiStopRouteResult
    poi_candidates: list[POICandidate]   # Leer wenn kein POI gefragt
```

**Offene Designentscheidung**: `max_detour_seconds` als Konfig-Wert oder
hartkodiert. Vorschlag: Default 600s (10 Min), via Constructor überschreibbar,
nicht im Saleria-Settings sichtbar. Wenn häufig zu eng → später ins Dashboard.

## RouteIntentParser (`tools/route_intent_parser.py`)

Zweistufige NLU-Pipeline:

1. **Pattern-Vorfilter** (Regex) — schnell, billig, deterministisch.
   Erkennt: gibt es überhaupt einen Multi-Stop-Hinweis? Trigger sind
   Indikatoren wie "vorher", "auf dem weg", "unterwegs", mehrere Personen,
   "über X", "via X".
2. **Claude Sonnet Tool-Call** — strukturierte Extraktion mit JSON-Schema.
   Nur wenn Pattern-Vorfilter Multi-Stop-Verdacht hat.

### Pattern-Vorfilter

```python
# Multi-Stop-Indikatoren (Disjunktion)
MULTI_STOP_HINTS = re.compile(
    r"\b(vorher|danach|auf dem weg|unterwegs|über|via|"
    r"abholen|einkaufen|tanken|holen)\b",
    re.IGNORECASE,
)
# Mindest-Trigger: "fahrt/route/...nach/zu X"
ROUTE_INTRO = re.compile(
    r"\b(fahrt|fahren|fahre|route|navig\w+|muss nach|zu fahren|nach\b)",
    re.IGNORECASE,
)

def is_multi_stop_candidate(text: str) -> bool:
    return bool(ROUTE_INTRO.search(text) and MULTI_STOP_HINTS.search(text))
```

Wenn `is_multi_stop_candidate(text)` → True ist, übernimmt der
MultiStopHandler. Sonst Fallthrough zum bestehenden Single-Stop-Handler.

### Tool-Schema für Claude Sonnet

Wird per `tools=[...]` und `tool_choice={"type": "tool", "name": ...}`
erzwungen — kein Freitext-Roundtrip.

```python
ROUTE_EXTRACT_TOOL = {
    "name": "extract_multi_stop_route",
    "description": (
        "Extrahiert strukturiert die Stops einer Multi-Stop-Routenanfrage."
        " Reihenfolge bewahren wie im Text genannt; type='poi' nur wenn"
        " der User klar nach einer Kategorie/Marke sucht (z.B. Kaufland,"
        " Tankstelle), nicht bei konkreten Adressen."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "origin": {
                "type": "object",
                "properties": {
                    "type": {"enum": ["home", "contact", "address"]},
                    "value": {"type": "string"},  # "" wenn home
                },
                "required": ["type"],
            },
            "destination": {
                "type": "object",
                "properties": {
                    "type": {"enum": ["contact", "address"]},
                    "value": {"type": "string"},
                },
                "required": ["type", "value"],
            },
            "waypoints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"enum": ["contact", "address", "poi"]},
                        "value": {"type": "string"},
                        "poi_category": {
                            "type": "string",
                            "description": (
                                "Nur wenn type=poi. Werte: supermarket,"
                                " fuel, pharmacy, restaurant, atm, other."
                            ),
                        },
                        "constraint": {
                            "enum": ["before_destination", "along_route"],
                            "description": (
                                "before_destination = vorher abholen;"
                                " along_route = irgendwo unterwegs (POIs)."
                            ),
                        },
                    },
                    "required": ["type", "value"],
                },
            },
            "arrival_time_text": {
                "type": "string",
                "description": (
                    "Wörtliche Zeitangabe falls vorhanden, z.B."
                    " 'morgen um 16 uhr'. Sonst leerer String."
                ),
            },
        },
        "required": ["destination", "waypoints"],
    },
}
```

**Eigenschaften**:
- `origin.type=home` ist Default wenn der User keinen Start nennt.
- `arrival_time_text` wird **wörtlich** extrahiert und an die existierende
  `parse_arrival_time()` aus `route_commands.py` übergeben (Wiederverwendung
  statt Sonnet das Datumsrechnen zu überlassen — deterministisch besser).
- Sonnet entscheidet **nicht** über die Reihenfolge der Optimierung. Es
  liefert nur was im Text steht. Optimierung übernimmt die Directions API.

## MultiStopRouteCommandHandler (`comms/commands/multi_stop_route_commands.py`)

Orchestrator. Eigene Klasse (eigene Datei) statt Funktion in `route_commands.py`,
weil die Logik substantiell anders ist (Sonnet-Call, Multi-Stage-Pending-Action).

### Plugin-Registrierung

Folgt dem Phase-77-Plugin-Pattern (`CommandPlugin`, `_factory`,
`HandlerContext`). **Priority muss höher sein als die des Single-Stop-Handlers
(76)**, damit Multi-Stop zuerst geprüft wird. Vorschlag: `priority=80`.
Bei `is_multi_stop_candidate(text) == False` macht der Handler einen
`fallthrough=True`, damit der Single-Stop-Handler ihn übernehmen kann.

### Lebenszyklus einer Anfrage

Zwei oder mehr Saleria-Turns pro Routenplan. Zustand zwischen Turns liegt
in `PendingConfirmationStore` als `PendingAction(action_type="route_disambig")`.

```
TURN 1 (User: vollständige Routenanfrage)
  1. Pattern-Vorfilter → Multi-Stop?  (nein → fallthrough)
  2. Sonnet-Tool-Call → RouteRequest (strukturiert)
  3. Adressen auflösen:
     a) origin (home oder Kontakt oder direkte Adresse)
     b) destination
     c) für jeden contact-Waypoint: contact_store.search()
       → bei mehreren Treffern: Liste der Kandidaten merken
  4. Wenn Mehrdeutigkeiten existieren:
       a) erste offene Disambiguierung als Liste senden ("Welche Lisa?")
       b) PendingAction mit FULL ROUTE STATE setzen, action_type="route_disambig"
       c) RETURN — auf User-Antwort warten
  5. Sonst: weiter zu Routing (siehe TURN N+1)

TURN 2..N (User: "1" oder "2" als Antwort)
  1. Handler-Vorcheck: gibt es eine PendingAction(action_type="route_disambig")
     für diesen user_id? Wenn ja: ZAHL parsen.
  2. Auswahl in route state übernehmen, nächste offene Disambiguierung suchen.
  3. Weiter offene → erneut Liste + PendingAction-Update, RETURN.
  4. Keine weiteren → Routing-Phase (siehe unten).

TURN ROUTING (alle Kontakte/Adressen aufgelöst)
  1. MultiStopRoutePlanner.plan(origin, people_stops, destination, poi_request)
     → liefert PlannedRoute + ggf. POI-Kandidaten.
  2. Wenn poi_candidates nicht leer und >1: Liste senden ("Welcher Kaufland?")
     PendingAction mit FULL ROUTE STATE + poi_candidates speichern, RETURN.
  3. Wenn genau 1 POI-Kandidat: automatisch wählen, weiter.
  4. Wenn 0 POI-Kandidaten innerhalb max_detour: Hinweis "keinen X auf dem
     Weg gefunden" + Frage "trotzdem die Route ohne Stop?" (Confirm/Cancel).

TURN POI-WAHL (User: "2" auf POI-Liste)
  1. Wahl übernehmen, MultiStopRoutePlanner.finalize_with_poi(...)
  2. Antwort formatieren, PendingAction.clear()
```

### Disambiguierung – Datenstruktur

```python
@dataclass
class RouteSession:
    """Persistenter Zustand zwischen Turns. Liegt in PendingAction.data."""
    raw_text: str
    origin_addr: str | None
    destination_addr: str | None
    # Pro Waypoint-Index: aufgelöste Adresse ODER Liste von Kandidaten
    waypoint_specs: list[WaypointSpec]
    poi_request: POIRequest | None
    poi_candidates: list[POICandidate]   # gefüllt nach erster Routenphase
    chosen_poi: POICandidate | None
    arrival_time_text: str

    def next_open_disambiguation(self) -> tuple[str, list] | None:
        """Liefert (kind, candidates) oder None wenn alles aufgelöst."""
        # kind ∈ {"origin", "destination", "waypoint_N", "poi"}
```

`RouteSession` wird serialisiert (asdict + JSON) in `PendingAction.data`
gespeichert. Bei jedem Turn wird sie geladen, modifiziert, zurückgeschrieben.

**Wichtig**: Bei `chosen_poi` ist `POICandidate` ein dataclass — bei
JSON-Serialisierung über `dataclasses.asdict()` + manuellem Reconstruct.
Hilfsfunktion `RouteSession.to_dict()` / `from_dict()` ergänzen.

### Zahl-Antworten erkennen

Heute kennt `PendingConfirmationStore.check_response()` nur ja/nein/ändern:,
**keine Zahlen**. Zwei saubere Wege:

**Variante A: Handler-eigener Vorcheck** (empfohlen)
Der MultiStopRouteCommandHandler ruft im `execute()` zuerst
`store.get(user_id)` und prüft selbst, ob die Antwort eine Zahl ist und
ob `action_type=="route_disambig"`. Erst wenn nicht, geht er den normalen
Pattern-Match-Pfad.

Vorteil: Keine Änderung an `PendingConfirmationStore`. Andere Handler bleiben
unberührt. Nachteil: Pattern-Match-Reihenfolge muss garantieren, dass dieser
Handler *vor* dem Standard-Bestätigungs-Hook der Bridge angefragt wird.

**Variante B: PendingConfirmationStore erweitern**
Neue `check_response()`-Variante: gibt zusätzlich `("number", n, action)`
zurück, wenn Text eine reine Zahl ist UND der `action_type` in einer Liste
"number-aware action types" steht.

Vorteil: Generisch wiederverwendbar (z.B. für künftige Listen-Picks).
Nachteil: Eingriff in zentralen Mechanismus, der bisher stabil läuft.

**Empfehlung**: Variante A für Phase 92. Wenn sich das Muster (Zahlen-Pick
auf gespeicherter Liste) wiederholt, später auf Variante B refactorn.

### Antwort-Format

```
Route geplant:
1. Home → Lisa Müller
2. Lisa Müller → Andrea Schulz
3. Andrea Schulz → Kaufland Grünau (+5 Min Umweg)
4. Kaufland Grünau → Leipzig Hauptbahnhof

Gesamt: 48,2 km, ca. 1 Stunde 12 Minuten
Abfahrt: spätestens 14:35 (15 Min Puffer für Ankunft 16:00)

→ https://www.google.com/maps/dir/?api=1&...
```

Bei `arrival_time_text` leer entfällt die Abfahrt-Zeile.

## Etappen (Implementierung – nicht Teil dieser Konzept-Phase)

| Etappe | Inhalt | Aufwand-Schätzung |
|--------|--------|--------------------|
| E1 | **Konzept-Doku** (DIESE Phase, nur dieses Dokument) | abgeschlossen |
| E2 | `RouteProvider` (ABC) + `GoogleMapsRouteProvider` + Unit-Tests mit gemockten Responses | ~1 Session |
| E3 | `MultiStopRoutePlanner` + Unit-Tests (Mock-Provider) | ~½ Session |
| E4 | `RouteIntentParser` + Sonnet-Tool-Schema + Tests (Pattern-Tests + Sonnet-Mock) | ~1 Session |
| E5 | `MultiStopRouteCommandHandler` + Disambiguierung + Plugin-Registrierung + Integration-Tests | ~1–1½ Sessions |
| E6 | Live-Smoketest mit echtem API-Key + Prompt-Tuning + Bugfixes | ~½ Session |

**Gesamt: ~4–5 Sessions**, jede in einem eigenen Chat (Workflow-Regel:
neue Phase = neuer Chat, hier interpretiert als neuer Chat pro Etappe).

## Test-Plan

### `tests/test_google_maps_route_provider.py` (~18 Tests)

```
- test_multi_stop_optimize_true: waypoint_order aus Response → ordered_stops
- test_multi_stop_optimize_false: Reihenfolge bleibt wie übergeben
- test_multi_stop_zero_results: RouteError
- test_multi_stop_url_encoding_umlauts: Adressen mit Umlauten korrekt encoded
- test_multi_stop_link_pipe_not_encoded: | in waypoints bleibt unenkodiert
- test_search_poi_along_route_with_polyline: Body enthält encodedPolyline
- test_search_poi_along_route_field_mask: X-Goog-FieldMask gesetzt
- test_search_poi_along_route_detour_mapping: routingSummaries → detour_seconds
- test_search_poi_empty_results: leere Liste, kein Fehler
- test_search_poi_api_error: RouteError mit Status
- test_api_key_missing_at_init: ValueError
- test_close_releases_client: httpx.Client.close() aufgerufen
- ... + Edge-Cases für jedes Statuswort (ZERO_RESULTS, OVER_QUERY_LIMIT, ...)
```

### `tests/test_multi_stop_route_planner.py` (~10 Tests)

```
- test_plan_without_poi: nur Schritt 1
- test_plan_with_poi_filters_by_detour: max_detour_seconds wird respektiert
- test_plan_with_poi_sorts_by_detour_asc: kleinster Umweg zuerst
- test_plan_with_poi_limits_to_5: maximal 5 Kandidaten
- test_finalize_with_poi: chosen_poi wird als Waypoint angehängt
- test_planner_uses_provider_optimize_true: optimize_order=True durchgereicht
- ...
```

### `tests/test_route_intent_parser.py` (~15 Tests)

```
- test_is_multi_stop_candidate_true_vorher: "vorher Lisa abholen" → True
- test_is_multi_stop_candidate_true_auf_dem_weg: True
- test_is_multi_stop_candidate_false_single_stop: "fahrt zu Lisa" → False
- test_extract_basic_two_waypoints: Sonnet-Mock → 2 contact-Waypoints
- test_extract_with_poi_along_route: type=poi, constraint=along_route
- test_extract_with_arrival_time: arrival_time_text wörtlich
- test_extract_origin_default_home: kein expliziter Origin → home
- test_extract_origin_explicit_contact: "von Mama aus" → contact
- ...
```

### `tests/test_multi_stop_route_commands.py` (~20 Tests)

```
- test_turn1_no_ambiguity_full_route: Single-Pass-Erfolgsfall
- test_turn1_contact_ambiguity_creates_pending: 2 Lisas → Liste + PendingAction
- test_turn2_number_response_resolves: "1" → konkrete Lisa gewählt
- test_turn2_invalid_number_reprompts: "5" bei 3 Optionen → Fehlermeldung
- test_turn_cancel_clears_pending: "abbrechen" → clear()
- test_poi_phase_creates_pending: nach erster Route → POI-Liste
- test_poi_zero_candidates: "kein Kaufland in Reichweite, trotzdem?"
- test_poi_single_candidate_autoselect: 1 Kandidat → keine Frage
- test_fallthrough_when_not_multi_stop: gibt fallthrough=True zurück
- test_arrival_time_in_final_response: Abfahrt-Zeile erscheint
- test_session_serialization_roundtrip: RouteSession.from_dict(to_dict(x)) == x
- ...
```

### `tests/test_route_provider.py` (~5 Tests, Interface-Compliance)

Sicherstellen, dass jede `RouteProvider`-Implementierung die abstrakten
Methoden implementiert (für künftigen OSM-Provider relevant).

## Risiken & offene Punkte

| Risiko | Mitigation |
|--------|------------|
| Places API v1 "Search Along Route" nicht im Google-Cloud-Projekt aktiviert | Setup-Hinweis in dieser Doku, Lera aktiviert selbst |
| Kosten – Search Along Route ist relativ teuer (~$0.03/Call) | Caching auf Polyline-Hash für 5 Min in `GoogleMapsRouteProvider` (optional, Etappe E2) |
| Latenz – 1 Sonnet-Call + bis zu 2 API-Calls + ggf. Disambig-Roundtrips | Akzeptiert; Disambiguierung sequenziell ist explizit gewollt (UX-Robustheit > Geschwindigkeit) |
| Pattern-Match-Reihenfolge – Multi-Stop muss vor Single-Stop matchen | `priority=80` > `priority=76`. Test `test_plugin_pattern_conflicts.py` prüft das automatisch (Phase 77-CI-Gate) |
| Disambiguierung: Zahl-Antworten kollidieren mit anderen Handlern, die auch Zahlen erwarten | Handler-eigener Vorcheck nur wenn `PendingAction.action_type == "route_disambig"` exists. Andere Handler bleiben unberührt |
| Sonnet kann Schema verfehlen (z.B. waypoints fehlt) | Validierung + Fallback: bei Schema-Fehler → "Ich hab das nicht ganz verstanden, kannst du es anders formulieren?" |
| Google API-Quota überschritten | RouteError mit klarer User-Meldung; Fallback NICHT zu OSM (bewusste Entscheidung – Provider-Wechsel ist Architektur-Aufgabe, kein Runtime-Fallback) |

### Bekannte Limitierungen (akzeptiert)

- **Keine Öffnungszeiten-Prüfung**: Kaufland um 22:30 erreicht, schließt 22:00 — Saleria warnt nicht. Out-of-Scope für Phase 92.
- **Keine semantische Reihenfolge-Heuristik**: "Einkauf zuletzt damit Lebensmittel nicht im Auto verderben" wird **nicht** erzwungen. Reine Fahrzeit-Optimierung. User kann durch explizite Formulierung ("zuletzt zu Kaufland") steuern — Sonnet bewahrt dann die Reihenfolge und `optimize_order=False` wird gesetzt. **Erkennung dieses Modus: TODO in Etappe E4** (Tool-Schema-Erweiterung um optionales `preserve_order: bool`).
- **Keine ÖPNV-/Fahrrad-Modi**: Nur `travelmode=driving`.
- **Keine Hin-und-Rückweg-Optimierung**: Wenn User später zurück will, ist das eine zweite Anfrage.

## Setup (für Lera, vor Etappe E2)

### Google Cloud APIs aktivieren

1. Cloud Console → APIs & Services → Library
2. **Places API (New)** suchen → Aktivieren (heißt jetzt einfach "Places API")
3. **Directions API** ist seit Phase 43 bereits aktiv → keine Aktion nötig.
4. API-Key (existierend aus Phase 43) prüfen: Restrictions sollen beide APIs zulassen.

### Abhängigkeiten

Keine neuen Pakete. `httpx`, `urllib.parse`, `dataclasses`, `re` reichen.
Für Sonnet-Tool-Calls wird der bestehende Anthropic-Client genutzt
(vermutlich `core.llm_client` o.ä. — in Etappe E4 prüfen).

### Kosten-Schätzung

| Posten | Annahme | Monatskosten |
|--------|---------|--------------|
| Directions API (Multi-Stop) | 30 Calls/Monat | $0.15 |
| Places API (Search Along Route) | 30 Calls/Monat | $0.90 |
| Claude Sonnet Tool-Call | ~500 Tokens/Call, 30/Monat | <$0.10 |
| **Summe** | | **~$1.15/Monat** |

Bleibt unter dem $200 Google Free Tier. Kein Schmerz.

## Out-of-Scope (explizit)

- Bugfix für `RouteCommandHandler._resolve_address()` (Mehrdeutigkeit in
  Single-Stop) – separater Bugfix-Branch.
- Öffnungszeiten-Check (Phase 92.x oder eigene Phase).
- Reihenfolge-Heuristiken über Kategorien (Einkauf zuletzt etc.).
- ÖPNV-Modus (Phase 43 nennt das als Phase-X-Erweiterung).
- OSM-Provider-Implementierung (`RouteProvider` schon vorbereitet, Code später).
- Proaktive Routenplanung aus Kalender-Terminen (Phase 17/Briefing-Integration).
- Disambiguierung gebündelt statt sequenziell (mögliche Folgephase wenn UX-Bedarf).

## Mögliche Folge-Phasen

- **Phase 92.1** – Öffnungszeiten-Check für POI-Kandidaten (Places API liefert `regularOpeningHours`).
- **Phase 92.2** – Reihenfolge-Constraints im Tool-Schema (`preserve_order`, `must_be_last`).
- **Phase 92.3** – OSM-Provider als zweite `RouteProvider`-Implementierung.
- **Phase 93** – Kalender-Integration: Termin mit Adresse → automatischer Routenvorschlag im Briefing.
