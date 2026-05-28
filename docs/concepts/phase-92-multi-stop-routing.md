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

## Umsetzungsstand (Stand 2026-05-28)

Der Konzeptkern von Phase 92 ist inzwischen weitgehend umgesetzt:

- **E0 abgeschlossen**: Resolver-Logik aus Phase 43 in
    `tools/contact_address_resolver.py` ausgegliedert.
- **E1 abgeschlossen**: `GoogleMapsRoutePlanner` und `MapsLinkBuilder`
    existieren samt Unit-Tests.
- **E2 abgeschlossen**: `RouteIntentParser` und der Anthropic-Tool-Call-
    Pfad sind implementiert.
- **E3 abgeschlossen**: Persistenter `RouteSessionStore` (SQLite) ist
    vorhanden.
- **E4 abgeschlossen**: `MultiStopRouteCommandHandler`, Plugin-Wiring,
    Listen-Picks (`route_contact_pick`, `route_poi_pick`) und
    Integrationstests sind implementiert.
- **E5 offen**: Live-Smoketest mit echtem API-Key, Prompt-Tuning und
    eventuelle letzte Bugfixes stehen noch aus.

Die Phase ist damit **code-seitig implementiert und testgrün**, aber noch
nicht final live abgenommen.

## Bezug zu Phase 43 – was bleibt, was kommt neu

| Komponente | Status in Phase 92 |
|------------|---------------------|
| `RoutePlanner` (Single-Stop, Google Directions) | **unverändert** – wird weiter genutzt |
| `RouteCommandHandler` (Single-Stop) | **unverändert** – fängt 1-Ziel-Anfragen ab |
| `ContactStore` + `_resolve_address()` | **wiederverwendet** – Logik in Util ausgliedern |
| `parse_arrival_time()` | **wiederverwendet** – aus `route_commands.py` |
| `GoogleMapsRoutePlanner` | **neu** – Multi-Waypoint + Optimierung + POI-Search via Google APIs |
| `MapsLinkBuilder` | **neu** – baut den Google-Maps-Deep-Link (provider-unabhängige Util-Klasse) |
| `RouteIntentParser` | **neu** – NLU-Schicht (Pattern + Sonnet-Tool-Call) |
| `MultiStopRouteCommandHandler` | **neu** – Orchestrator + Disambiguierung |

**Wichtig**: Phase 92 fasst `RoutePlanner` (aus Phase 43) **nicht** an. Wenn
sich später herausstellt, dass Single- und Multi-Stop denselben Provider
nutzen sollten, ist das ein eigener Refactor-Schritt.

## Hinweis zum früheren Single-Stop-Bug

Der ursprünglich hier dokumentierte Phase-43-Bug bei Mehrdeutigkeiten im
Single-Stop-Handler wurde inzwischen **separat in Phase 43 gefixt**.

Für Phase 92 bleibt die Architekturentscheidung trotzdem gültig: Multi-Stop
nutzt eine eigene Disambiguierungsstrecke über `RouteIntentParser`, Listen-
Picks und `RouteSessionStore`, statt den Single-Stop-Flow mitzubenutzen.

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
   │ RouteIntentParser  │ │ ContactStore     │ │ GoogleMapsRoute    │
   │ (tools/)           │ │ (bestehend)      │ │ Planner (tools/)   │
   │  Pattern + Sonnet  │ │                  │ │  Directions + POI  │
   └────────────────────┘ └──────────────────┘ └──────────┬─────────┘
                                                          │
                                                          ▼ liefert
                                              ┌────────────────────┐
                                              │ MapsLinkBuilder    │
                                              │ (tools/) Util      │
                                              │ baut Deep-Link     │
                                              └────────────────────┘
```

### Dateien (Konzeptkern / Ist-Stand)

| Datei | Klasse | Zeilen (Schätzung) |
|-------|--------|---------------------|
| `tools/google_maps_route_planner.py` | `GoogleMapsRoutePlanner` | ~300 |
| `tools/maps_link_builder.py` | `MapsLinkBuilder` | ~60 |
| `tools/route_intent_parser.py` | `RouteIntentParser` | ~250 |
| `tools/route_session_store.py` | `RouteSessionStore` | ~300 |
| `comms/commands/multi_stop_route_commands.py` | `MultiStopRouteCommandHandler` | ~300 |

Vorarbeit aus E0:
- `tools/contact_address_resolver.py` – ausgegliederte Resolver-Util aus
    Phase 43, von Single-Stop und Multi-Stop gemeinsam genutzt.

Plus Tests: ~4 neue `tests/test_*.py`-Dateien, geschätzt 60–70 Tests gesamt.

## GoogleMapsRoutePlanner (`tools/google_maps_route_planner.py`)

Konkrete Klasse — kein ABC. Begründung im Abschnitt "Warum kein
RouteProvider-Interface" weiter unten.

Kapselt zwei Google-APIs und liefert ein fertiges Routenergebnis inkl.
POI-Kandidaten zurück.

### Dataclasses

```python
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

@dataclass(frozen=True)
class POICandidate:
    """Ein POI-Kandidat entlang einer Route."""
    name: str                      # "Kaufland Grünau"
    address: str
    place_id: str
    detour_seconds: int            # Umweg gegenüber Direktroute
    rating: float | None

@dataclass(frozen=True)
class POIRequest:
    category: str                  # "supermarket", "fuel", "pharmacy"
    name_hint: str | None          # "Kaufland" (Filterung)
    max_results: int = 10
    max_detour_seconds: int = 600  # 10 Min Default

@dataclass(frozen=True)
class PlannedRoute:
    route: MultiStopRouteResult
    poi_candidates: list[POICandidate]   # Leer wenn kein POI gefragt
```

Anmerkung: `maps_link` ist absichtlich **nicht** Teil von
`MultiStopRouteResult`. Link-Bau passiert über `MapsLinkBuilder`, weil der
Link UI-Concern ist und nicht zur Routing-Logik gehört.

### Methoden

```python
class GoogleMapsRoutePlanner:
    """Multi-Stop-Routing via Google Directions API + POI via Places API v1."""

    DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
    PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=10.0)

    def plan(
        self,
        origin: Stop,
        people_stops: list[Stop],
        destination: Stop,
        poi_request: POIRequest | None = None,
    ) -> PlannedRoute:
        """Zwei-Phasen-Routing.

        Schritt 1: Basis-Route (Origin -> people_stops -> Destination),
                   optimiert via Directions API (waypoints=optimize:true).
        Schritt 2 (nur wenn poi_request): POI-Suche entlang der Basis-
                   Route (Places API v1, searchAlongRouteParameters).
                   Detour-Filter <= max_detour_seconds, sortiert aufsteigend,
                   max 5 Kandidaten.

        Final-Routing mit gewähltem POI: separate Methode finalize_with_poi.
        """

    def finalize_with_poi(
        self,
        origin: Stop,
        people_stops: list[Stop],
        destination: Stop,
        chosen_poi: POICandidate,
    ) -> MultiStopRouteResult:
        """Finale Route mit POI als zusätzlichem Waypoint."""

    def close(self) -> None:
        """HTTP-Client schließen."""

    # --- Private Helfer (provider-spezifisch) ---
    def _call_directions(self, ...) -> MultiStopRouteResult: ...
    def _call_places_along_route(self, ...) -> list[POICandidate]: ...
    def _parse_waypoint_order(self, response: dict) -> list[int]: ...
```

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

### Fehlerfälle

| API-Response | Verhalten |
|---|---|
| `status=ZERO_RESULTS` | `RouteError("Keine Route gefunden")` |
| `status=OVER_QUERY_LIMIT` | `RouteError("API-Limit erreicht")` |
| `status=REQUEST_DENIED` | `RouteError("API-Key ungültig/blockiert")` |
| HTTP 5xx | `httpx.HTTPStatusError` durchreichen |
| Timeout (>10s) | `httpx.TimeoutException` durchreichen |
| Places-Antwort leer | leere Liste zurückgeben, kein Fehler |

## MapsLinkBuilder (`tools/maps_link_builder.py`)

Eigene Util-Klasse — provider-unabhängig. Baut den Google-Maps-Deep-Link
aus einer fertigen Stop-Reihenfolge. Bewusst von `GoogleMapsRoutePlanner`
getrennt: der Link funktioniert auch dann, wenn die Routenberechnung in
Zukunft mal aus einer anderen Quelle käme (Cache, persistierte Route,
externe Anfrage).

```python
class MapsLinkBuilder:
    """Baut Google-Maps-Deep-Links für die Anzeige in Android Auto."""

    BASE = "https://www.google.com/maps/dir/?api=1"

    def build_multi_stop_link(
        self,
        origin: Stop,
        waypoints: list[Stop],     # in finaler Reihenfolge
        destination: Stop,
        travel_mode: str = "driving",
    ) -> str:
        """
        Erzeugt:
        https://www.google.com/maps/dir/?api=1
          &origin=<encoded>
          &destination=<encoded>
          &waypoints=<encoded>|<encoded>|...
          &travelmode=driving

        Detail: urlencode mit quote_via=quote_plus für origin/destination.
        Pipes (|) zwischen Waypoints NICHT URL-encoden -- das macht Google
        selbst, sonst funktioniert der Link nicht.
        """
```

### Warum kein RouteProvider-Interface

Anfangs war ein abstraktes `RouteProvider`-Interface geplant, um später
OSRM/Valhalla als zweite Implementierung neben Google zu erlauben. Nach
Diskussion verworfen, weil für diesen Use Case **drei Argumente
gleichzeitig** gegen OSM sprechen:

1. **Datenschutz fällt weg**: Endformat ist ein Google-Maps-Deep-Link für
   Android Auto. Alle Adressen wandern so oder so an Google. OSM davor zu
   schalten ändert daran nichts.

2. **Kosten sind irrelevant**: Bei realistischer Nutzung (1–2 Anfragen/Monat)
   liegen die Google-API-Kosten bei ~$1 pro Jahr. Drei Sessions OSM-
   Implementierung würden sich nie amortisieren.

3. **Sicherheits-Kosten**: Self-hosted OSM-Stack (Overpass, OSRM/Valhalla,
   Planet-Updates) bedeutet drei zusätzliche Dienste mit Patch-Pflicht.
   Bei dem ansonsten gepflegten Sicherheits-Standard (Fail2Ban, ModSecurity,
   2FA, SSH-Keys) wären das offene Lücken — nicht verwaltete Systeme bleiben
   unsicher.

**Konsequenz**: `GoogleMapsRoutePlanner` ist eine konkrete Klasse. Wenn in
mehreren Jahren ein Wechsel nötig wird (z.B. Google-Account aufgegeben),
ist der Refactor zu einem ABC eine Ein-Session-Aufgabe — die HTTP-Schicht
ist gekapselt, die Datacontracts (`Stop`, `MultiStopRouteResult`,
`POICandidate`, `PlannedRoute`) sind provider-agnostisch.

YAGNI-Argument: Keine konkrete Anforderung für einen zweiten Provider
existiert. Abstraktion ohne zweite Implementierung sorgt für höhere
Komplexität bei gleicher Funktionalität.

### Offene Designentscheidung

`POIRequest.max_detour_seconds` als Konfig-Wert oder hartkodiert. Vorschlag:
Default 600s (10 Min), via Konstruktor des Handlers überschreibbar, nicht im
Saleria-Settings sichtbar. Wenn häufig zu eng → später ins Dashboard.

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
(76)**, damit Multi-Stop zuerst geprüft wird. Implementiert ist
`priority=75` (niedrigere Zahl = frühere Prüfung), also weiterhin vor dem
Single-Stop-Handler.
Bei `is_multi_stop_candidate(text) == False` macht der Handler einen
`fallthrough=True`, damit der Single-Stop-Handler ihn übernehmen kann.

### Lebenszyklus einer Anfrage

Zwei oder mehr Saleria-Turns pro Routenplan. Im implementierten Stand liegt
der persistente Routenstatus in `RouteSessionStore` (SQLite). Die konkrete
Auswahl durch den User läuft über `ConversationListStore` + `list_pick`
(`route_contact_pick`, `route_poi_pick`) statt über `PendingConfirmationStore`.

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
      b) `RouteSessionStore` schreiben und Liste im
        `ConversationListStore` registrieren
       c) RETURN — auf User-Antwort warten
  5. Sonst: weiter zu Routing (siehe TURN N+1)

TURN 2..N (User: Listen-Pick / "Treffer 1" / "1")
  1. Bridge löst den Pick über `ConversationListStore` auf.
  2. `message_handlers.py` dispatcht an
      `MultiStopRouteCommandHandler.continue_with_pick(...)`.
  3. Auswahl in den Route-Status übernehmen, nächste offene
      Disambiguierung suchen.
  4. Weiter offene → erneut Liste registrieren, RETURN.
  5. Keine weiteren → Routing-Phase (siehe unten).

TURN ROUTING (alle Kontakte/Adressen aufgelöst)
  1. GoogleMapsRoutePlanner.plan(origin, people_stops, destination, poi_request)
     → liefert PlannedRoute + ggf. POI-Kandidaten.
  2. Wenn poi_candidates nicht leer: Liste senden ("Welcher Hornbach?")
      und zusammen mit der Session registrieren, RETURN.
  3. Wenn genau 1 POI-Kandidat: im aktuellen Implementierungsstand trotzdem
      als Liste anzeigen, damit der User Adresse und Umweg sieht.
  4. Wenn 0 POI-Kandidaten innerhalb max_detour: Hinweis "keinen X auf dem
     Weg gefunden" + Frage "trotzdem die Route ohne Stop?" (Confirm/Cancel).

TURN POI-WAHL (User: "2" auf POI-Liste)
  1. Wahl übernehmen, GoogleMapsRoutePlanner.finalize_with_poi(...)
  2. MapsLinkBuilder.build_multi_stop_link(...) für Antwort-Link
    3. Antwort formatieren, Session/Listeneintrag bereinigen
```

### Disambiguierung – Datenstruktur

```python
@dataclass
class RouteSession:
    """Persistenter Zustand zwischen Turns. Liegt im RouteSessionStore."""
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

`RouteSession` wird serialisiert (asdict + JSON) im `RouteSessionStore`
gespeichert. Bei jedem Turn wird sie geladen, modifiziert, zurückgeschrieben.

**Wichtig**: Bei `chosen_poi` ist `POICandidate` ein dataclass — bei
JSON-Serialisierung über `dataclasses.asdict()` + manuellem Reconstruct.
Hilfsfunktion `RouteSession.to_dict()` / `from_dict()` ergänzen.

### Listen-Picks erkennen

Im implementierten Stand muss `PendingConfirmationStore` dafür nicht erweitert
werden. Zahlen- oder "Treffer N"-Antworten laufen über den bestehenden
Phase-80-Listenpfad:

- `ConversationListStore` hält die aktive Kontakt- oder POI-Liste.
- Die Bridge löst den Pick auf das konkrete Item auf.
- `message_handlers.py` dispatcht das Item an
    `MultiStopRouteCommandHandler.continue_with_pick(...)`.

Vorteil: kein Eingriff in den zentralen Bestätigungsmechanismus, und das
Verhalten bleibt konsistent mit Such-, Mail- und Notizlisten.

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

## Etappen

| Etappe | Inhalt | Status |
|--------|--------|--------|
| E0 | Resolver-Refactor (`contact_address_resolver.py`) als Vorarbeit | abgeschlossen |
| E1 | `GoogleMapsRoutePlanner` + `MapsLinkBuilder` + Unit-Tests | abgeschlossen |
| E2 | `RouteIntentParser` + Sonnet-Tool-Schema + Tests | abgeschlossen |
| E3 | `RouteSessionStore` (SQLite) + Tests | abgeschlossen |
| E4 | `MultiStopRouteCommandHandler` + Disambiguierung + Plugin-/Bridge-Wiring + Integration-Tests | abgeschlossen |
| E5 | Live-Smoketest mit echtem API-Key + Prompt-Tuning + letzte Bugfixes | offen |

Status heute: **E0 bis E4 fertig**, **E5 offen**.

## Test-Plan

### `tests/test_google_maps_route_planner.py` (~22 Tests)

```
# Directions-API-Aufrufe
- test_plan_optimize_true_default: waypoints=optimize:true wird gesetzt
- test_plan_waypoint_order_applied: API-Response [1,0,2] → ordered_stops
- test_plan_zero_results: status=ZERO_RESULTS → RouteError
- test_plan_over_query_limit: → RouteError
- test_plan_request_denied: → RouteError
- test_plan_url_encoding_umlauts: Adressen mit Umlauten korrekt encoded
- test_plan_origin_destination_not_in_waypoint_order: nur Mittel-Stops werden sortiert

# POI-Search
- test_search_poi_along_route_with_polyline: Body enthält encodedPolyline
- test_search_poi_along_route_field_mask: X-Goog-FieldMask gesetzt
- test_search_poi_along_route_detour_mapping: routingSummaries → detour_seconds
- test_search_poi_empty_results: leere Liste, kein Fehler
- test_search_poi_api_error: RouteError mit Status

# Plan-Orchestrierung (ehemals MultiStopRoutePlanner)
- test_plan_without_poi_request: nur Basis-Route, poi_candidates=[]
- test_plan_with_poi_filters_by_detour: max_detour_seconds wird respektiert
- test_plan_with_poi_sorts_by_detour_asc: kleinster Umweg zuerst
- test_plan_with_poi_limits_to_5: maximal 5 Kandidaten
- test_finalize_with_poi_appends_waypoint: chosen_poi als zusätzlicher Stop

# Sonstige
- test_api_key_missing_at_init: ValueError
- test_close_releases_client: httpx.Client.close() aufgerufen
- ... + Edge-Cases für jedes Statuswort
```

### `tests/test_maps_link_builder.py` (~8 Tests)

```
- test_build_basic_link: Format und Parameter korrekt
- test_build_with_umlauts: quote_plus für Umlaute
- test_build_pipe_separator_unencoded: | bleibt als | in waypoints
- test_build_no_waypoints: nur origin + destination, kein waypoints-Param
- test_build_travel_mode_driving_default: travelmode=driving wenn nicht gesetzt
- test_build_special_chars_in_address: Komma, Punkt, &-Zeichen
- test_build_lat_lng_input: "52.5,13.4" als Koordinaten-Stop
- test_build_empty_origin_raises: ValueError oder klarer Fehler
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
- test_handler_uses_maps_link_builder: Antwort enthält gebauten Link
- ...
```

## Risiken & offene Punkte

| Risiko | Mitigation |
|--------|------------|
| Places API v1 "Search Along Route" nicht im Google-Cloud-Projekt aktiviert | Setup-Hinweis in dieser Doku, Lera aktiviert selbst |
| Kosten – Search Along Route ist relativ teuer (~$0.03/Call) | Caching auf Polyline-Hash für 5 Min in `GoogleMapsRoutePlanner` (optional, Etappe E2) |
| Latenz – 1 Sonnet-Call + bis zu 2 API-Calls + ggf. Disambig-Roundtrips | Akzeptiert; Disambiguierung sequenziell ist explizit gewollt (UX-Robustheit > Geschwindigkeit) |
| Pattern-Match-Reihenfolge – Multi-Stop muss vor Single-Stop matchen | Implementiert mit `priority=75` vor `priority=76`. Test `test_plugin_pattern_conflicts.py` prüft das automatisch (Phase 77-CI-Gate) |
| Disambiguierung: Zahl-Antworten kollidieren mit anderen Handlern, die auch Zahlen erwarten | Handler-eigener Vorcheck nur wenn `PendingAction.action_type == "route_disambig"` exists. Andere Handler bleiben unberührt |
| Sonnet kann Schema verfehlen (z.B. waypoints fehlt) | Validierung + Fallback: bei Schema-Fehler → "Ich hab das nicht ganz verstanden, kannst du es anders formulieren?" |
| Google API-Quota überschritten | RouteError mit klarer User-Meldung; Fallback NICHT zu OSM (bewusste Entscheidung – Provider-Wechsel ist Architektur-Aufgabe, kein Runtime-Fallback) |

### Bekannte Limitierungen (akzeptiert)

- **Keine Öffnungszeiten-Prüfung**: Kaufland um 22:30 erreicht, schließt 22:00 — Saleria warnt nicht. Out-of-Scope für Phase 92.
- **Keine semantische Reihenfolge-Heuristik**: "Einkauf zuletzt damit Lebensmittel nicht im Auto verderben" wird **nicht** erzwungen. Reine Fahrzeit-Optimierung. Die im Konzept skizzierte Erkennung per optionalem `preserve_order: bool` ist **noch offen** und gehört als Folgearbeit nach E5 in eine kleine Phase 92.x.
- **Keine ÖPNV-/Fahrrad-Modi**: Nur `travelmode=driving`.
- **Keine Hin-und-Rückweg-Optimierung**: Wenn User später zurück will, ist das eine zweite Anfrage.

## Voraussetzungen (Status 2026-05-13: erfüllt)

### Google Cloud APIs

Beide für Phase 92 benötigten APIs sind im verwendeten Cloud-Projekt
aktiviert:

| API | Status | Verwendung |
|-----|--------|------------|
| `Directions API` | aktiv (seit Phase 43) | Multi-Stop-Routing mit `waypoints=optimize:true` |
| `Places API (New)` | aktiv | Search-Along-Route mit `searchAlongRouteParameters` |

### API-Key-Restrictions

Der existierende Maps-API-Key (`google_maps_api_key` im SecretStore) hat
beide APIs in seiner Restriction-Liste. Kein Anpassen nötig für Phase 92.

### Falls je ein neuer API-Key angelegt werden muss

Diese APIs müssen mindestens in den Restrictions erlaubt sein, damit das
Konzept funktioniert:
- `Directions API`
- `Places API (New)` (nicht zu verwechseln mit `Places API` (Legacy)
  oder `Places SDK for Android/iOS`)

Aktivierung über: Cloud Console → APIs & Services → Library → API suchen
→ Aktivieren. Restrictions am Key in: APIs & Services → Credentials →
Key wählen → API restrictions.

### Hygiene-Hinweise (nicht Teil dieser Phase)

Beim Setup-Check fielen zwei Punkte auf — getrennt zu behandeln, nicht
in Phase 92:

1. **API-Restriction-Liste ist breit**: Der Key erlaubt aktuell ~30 APIs
   (Aerial View, Pollen, Solar, Map Tiles, ...). Bei Key-Leak wäre die
   Angriffsfläche unnötig groß. Empfehlung: Liste auf tatsächlich
   verwendete APIs reduzieren (Phase 43: Directions; Phase 92: zusätzlich
   Places API New). Falls weitere Apps gegen denselben Key laufen, dort
   ebenfalls Bedarf erheben.
2. **Doppelte Places API aktiviert**: Sowohl `Places API` (Legacy) als
   auch `Places API (New)` sind im Projekt aktiv. Saleria nutzt nur die
   neue. Wenn keine andere App die alte braucht, kann sie deaktiviert
   werden.

Beide Punkte sind reine Hardening-Aufgaben ohne funktionalen Einfluss
auf Phase 92. Kandidat für eine separate Mini-Phase oder für die
nächste Security-Review (Phase 57 hat das Thema generell adressiert).

### Abhängigkeiten

Keine neuen Pakete. `httpx`, `urllib.parse`, `dataclasses`, `re` reichen.
Für Sonnet-Tool-Calls wird der bestehende Anthropic-Client genutzt
(vermutlich `core.llm_client` o.ä. — in Etappe E4 prüfen).

### Kosten-Schätzung

Realistische Nutzung: 1–2 Multi-Stop-Anfragen pro Monat. Plus Reserve für
gelegentliche Spitzen.

| Posten | Annahme | Monatskosten |
|--------|---------|--------------|
| Directions API (Multi-Stop) | 2 Calls × $0.005 | ~$0.01 |
| Places API (Search Along Route) | 2 Calls × $0.032 | ~$0.06 |
| Claude Sonnet Tool-Call | ~500 Tokens × 2 | <$0.01 |
| **Summe** | | **~$0.08/Monat (~$1/Jahr)** |

Liegt bei jeder vernünftigen Nutzungsintensität deutlich unter dem $200
Google Free Tier. Selbst bei 10× höherer Nutzung (20 Anfragen/Monat) bleibt
es bei ~$1/Monat.

## Out-of-Scope (explizit)

- Weitere UX-/Heuristik-Arbeit an Single-Stop und Multi-Stop bleibt von
    Phase 92 getrennt; der frühere Single-Stop-Mehrdeutigkeits-Bug ist bereits
    separat in Phase 43 behoben.
- Öffnungszeiten-Check (Phase 92.x oder eigene Phase).
- Reihenfolge-Heuristiken über Kategorien (Einkauf zuletzt etc.).
- ÖPNV-Modus (Phase 43 nennt das als Phase-X-Erweiterung).
- **OSM-Provider** – bewusst verworfen, **nicht** vorbereitet als Interface.
  Begründung: Datenschutz-Gewinn = null (Endformat ist Google-Maps-Deep-Link
  für Android Auto, Adressen wandern so oder so an Google). Kosten ~$1/Jahr
  amortisieren keine 3 Sessions OSM-Implementierung. Self-hosted OSM-Stack
  (Overpass + OSRM/Valhalla + Planet-Updates) = 3 zusätzliche Dienste mit
  Patch-Pflicht und entsprechendem Sicherheitsrisiko. Falls je relevant:
  Refactor zu ABC ist ~1 Session, Datacontracts sind heute schon provider-
  agnostisch.
- Proaktive Routenplanung aus Kalender-Terminen (Phase 17/Briefing-Integration).
- Disambiguierung gebündelt statt sequenziell (mögliche Folgephase wenn UX-Bedarf).

## Mögliche Folge-Phasen

- **Phase 92.1** – Öffnungszeiten-Check für POI-Kandidaten (Places API liefert `regularOpeningHours`).
- **Phase 92.2** – Reihenfolge-Constraints im Tool-Schema (`preserve_order`, `must_be_last`).
- **Phase 92.3** – Routing-Backend austauschen (z.B. OSM). Trigger:
  Google-Account aufgegeben ODER >50 Anfragen/Monat. Refactor:
  `GoogleMapsRoutePlanner` → ABC + zweite Implementierung. Heute kein
  Trigger erfüllt — bei dem ersten gemeldeten Trigger Phase aktivieren.
- **Phase 93** – Kalender-Integration: Termin mit Adresse → automatischer Routenvorschlag im Briefing.
