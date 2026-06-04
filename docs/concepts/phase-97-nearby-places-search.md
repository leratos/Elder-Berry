# Phase 97 — Nearby Place Search (distanz-korrekt + gefiltert)

> Status: Konzept (greenlit, paralleler Ideen-Track). Branch bei Umsetzung:
> `feature/phase-97-nearby-places-search`. Umsetzung durch Claude Code.

## 0. Ziel

Saleria beantwortet „ich bin an Ort X und brauche/suche Y hier in der Nähe" mit
konkreten Orten und liefert nach Auswahl einen Google-Maps-Link.

Zwei Trigger-Formen:
- **Kaufen:** „ich bin Straße XY in Leipzig und brauche einen Shisha-Kopf — wo
  kaufe ich den hier?"
- **Ort/Venue:** „ich bin mit Lisa in XY, kannst du mir eine Rockerbar nennen?"

## 0.1 Was die Funktion rechtfertigt (Wertversprechen, scharf)

Der Wert ist NICHT „Orte suchen" — das kann Google. Der Wert sind die zwei Dinge,
die Googles Consumer-Oberfläche bei Lera nachweislich verbockt:

1. **Nah-zuerst-Ranking.** Google schlägt teils Orte 100 km weg vor und vergräbt
   die 12 km nahen. Text Search rankt per Default nach Relevanz, nicht nach Distanz.
2. **Kategorie-Filterung.** „Shisha-Zubehör" liefert zuerst Shisha-*Bars*; die
   echten Läden muss man manuell raussuchen.

Beides MUSS das Tool besser machen, sonst hat es keine Daseinsberechtigung ->
distanz-korrektes Ranking (§4.2) + Kategorie-Filter (§4.1) sind Kern, nicht Beiwerk.

## 0.2 Abgrenzung zu Phase 92

Phase 92 nutzt Places als **Search Along Route** (braucht Route/Polyline). Phase 97
hat KEINE Route — Umkreissuche um einen Punkt. Wiederverwendet werden
Infrastruktur + Muster (§2), nicht der Routen-Pfad.

## 1. Leitprinzipien

- **Ein Such-Endpoint: `places:searchText`, vom LLM angereichert.** Der LLM
  bereitet die Anfrage auf und gibt `searchText` eine bessere Grundlage:
  Freitext-Query + (falls ein sauberer Google-Typ existiert) `includedType` +
  `strictTypeFiltering` + eine Ausschlussliste. KEIN zweiter Endpoint.
  `searchNearby` ist bewusst Plan B (§8).
- **Arbeitsteilung LLM/Code.** Der LLM *urteilt* (Item->Kategorie, optionaler
  `includedType`, Ausschlussliste, Reisemodus); der Code *erzwingt garantiert*
  (Radius-Cap clientseitig, Typ-Ausschluss clientseitig, Distanz-Sort). Keine
  LLM-Varianz im sicherheitsrelevanten Filter.
- **YAGNI.** Keine statische Item->Kategorie-Tabelle (der LLM generalisiert).
  Keine Empfehlung/Kuratierung (kein Gastro-Kritiker; nur „nah + offen + Rating").
- **Single source of truth.** Reisemodus-Vokabular = `MapsLinkBuilder`-Whitelist
  (`driving/walking/bicycling/transit`). Derselbe `google_maps_api_key`, dasselbe
  sync-`httpx.Client`-Muster wie `GoogleMapsRoutePlanner`. Alle Maps-URLs im
  `MapsLinkBuilder`.
- **Standort = Freitext** -> Geocoding (§4.2, Koordinaten als Distanz-Bezugspunkt
  nötig). `m.location`/Geo-URI = optionale Etappe E5, nicht MVP.
- **OOP-Konvention.** Eine Klasse pro Datei, Constructor-DI, Plugin-Pattern.

## 2. Wiederverwendung

| Bedarf | Bestehende Struktur | Phase |
|---|---|---|
| „N Treffer, wähl einen" | `_maybe_register_command_list` / `list_pick` | 80 |
| Maps-URL bauen | `tools/maps_link_builder.py` | 92 |
| Reisemodus-Vokabular | `MapsLinkBuilder`-Whitelist | 92 |
| Intent via Sonnet-Tool-Call | Muster `tools/route_intent_parser.py` | 92 E2 |
| Sequenzielle Rückfrage (1 Frage) | Disambiguierungs-Flow | 92/43 |
| sync httpx + eigene Error-Klasse | Muster `GoogleMapsRoutePlanner` | 92 E1 |
| Wiring bei vorhandenem Key | `start_saleria.py`, `remote_commands.py` | 92 E4 |

## 3. Betroffene Dateien

### Neu
- `tools/nearby_place_search.py` — `NearbyPlaceSearch` (sync `httpx.Client`).
  EIN `searchText`-Aufruf (optional `includedType`+`strictTypeFiltering`), danach
  clientseitiger Radius-Cap, Typ-Ausschluss, Distanz-Sort. DTOs `NearbyQuery`,
  `PlaceCandidate`. `NearbyPlaceError`.
- `tools/google_geocoder.py` — `GoogleGeocoder.geocode(location_text) -> LatLng |
  None` (Geocoding API). Eigene Datei.
- `tools/nearby_intent_parser.py` — `is_nearby_candidate(text)` + `NearbyIntentParser`
  (Sonnet-Tool-Call `extract_nearby_search`).
- `comms/commands/nearby_place_commands.py` — `NearbyPlaceCommandHandler`.
- Tests: `tests/test_nearby_place_search.py`, `tests/test_google_geocoder.py`,
  `tests/test_nearby_intent_parser.py`, `tests/test_nearby_place_commands.py`.

### Geändert
- `comms/commands/base.py` — `HandlerContext` += `nearby_place_search`,
  `nearby_intent_parser`, `google_geocoder` (alle `| None`).
- `comms/remote_commands.py` — Bauplan + Kwargs (nur wenn `google_maps_api_key`).
- `scripts/start_saleria.py` — bei vorhandenem Key die drei Services instanziieren.
- `comms/message_handlers.py` — `_handle_list_pick` += Branch `nearby_place_pick`
  -> `MapsLinkBuilder.build_place_link(...)`.
- `tools/maps_link_builder.py` — `build_place_link(name, place_id)` ergänzen.
- `tests/test_plugin_registry.py` / `tests/test_assistant_plugin_inventory.py` —
  Plugin-Zahl +1; `EXPECTED_PLUGIN_NAMES += "nearby_place"`.
- `tests/test_maps_link_builder.py` — Tests für `build_place_link`.

## 4. Klassen-Skizzen

```python
# tools/nearby_place_search.py
@dataclass(frozen=True)
class NearbyQueryDraft:
    # Zwischenstand bis Disambiguierung fertig (Codex #4). location_text/travel_mode
    # optional, weil sie per Rueckfrage nachkommen koennen. Behaelt subject/
    # search_query/included_type/exclude_types, geht NICHT verloren.
    subject: str
    search_query: str
    included_type: str | None
    exclude_types: tuple[str, ...]
    location_text: str | None
    travel_mode: str | None
    open_now: bool = True
    def to_query(self) -> "NearbyQuery | None": ...  # None solange Pflichtfelder fehlen

@dataclass(frozen=True)
class NearbyQuery:
    # Vollstaendig aufgeloest -> alle Felder Pflicht. search() nimmt NUR das.
    subject: str
    search_query: str
    included_type: str | None
    exclude_types: tuple[str, ...]
    location_text: str
    travel_mode: str                # driving|walking|bicycling|transit (-> Radius §4.2)
    open_now: bool = True           # CLIENT-Flag (NICHT als openNow an die API, Codex #1)

@dataclass(frozen=True)
class PlaceCandidate:
    name: str
    address: str
    place_id: str
    rating: float | None
    open_now: bool | None       # None = unbekannt -> NICHT hart filtern
    distance_m: int             # Luftlinie vom Geocode-Punkt
    types: tuple[str, ...]
    primary_type: str | None

class NearbyPlaceSearch:
    def __init__(self, api_key: str, geocoder: GoogleGeocoder,
                 client: httpx.Client | None = None) -> None: ...
    def search(self, query: NearbyQuery, *, max_results: int = 20) -> list[PlaceCandidate]:
        # 1. geocoder.geocode(location_text) -> center (sonst leer + Hinweis)
        # 2. radius = RADIUS_BY_MODE[travel_mode]   (Cap/Weitung: §4.2)
        # 3. searchText:
        #      textQuery       = search_query
        #      pageSize        = 20                 # Puffer fuer Client-Filter (Codex #6)
        #      locationBias    = circle(center, radius)   # weich; harter Cap clientseitig
        #      rankPreference  = DISTANCE
        #      KEIN openNow an die API (Codex #1: serverseitig wuerde es Laeden ohne
        #        hinterlegte Zeiten ganz entfernen)
        #      if included_type: includedType=included_type, strictTypeFiltering=True
        #      FieldMask (vollstaendig, Codex #5):
        #        places.id, places.displayName, places.formattedAddress,
        #        places.location, places.types, places.primaryType,
        #        places.currentOpeningHours, places.rating   # -> Enterprise-SKU (akzeptiert)
        # 4. clientseitig (PFLICHT, da Bias nur weich ist):
        #      distance_m > radius                          -> raus  (Haversine)
        #      primary_type/types in exclude_types          -> raus
        #      open_now=True UND Ort ist BEKANNT geschlossen -> raus
        #        (unbekannte Oeffnungszeiten BLEIBEN, Codex #1)
        # 5. sort by distance_m, top max_results
```


```python
# tools/google_geocoder.py
@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float

class GoogleGeocoder:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None: ...
    def geocode(self, location_text: str) -> LatLng | None: ...
```

```python
# tools/nearby_intent_parser.py
def is_nearby_candidate(text: str) -> bool: ...   # Pattern-Vorfilter

class NearbyIntentParser:
    def __init__(self, anthropic_client: AnthropicClient) -> None: ...
    def parse(self, text: str) -> NearbyQueryDraft | None: ...
    # Tool "extract_nearby_search" liefert: subject, search_query,
    # included_type|null, exclude_types[], location_text|null, travel_mode|null,
    # open_now. Rueckgabe = NearbyQueryDraft (Codex #4): fehlt location_text/
    # travel_mode -> Handler fragt EINE Rueckfrage, das schon Geparste bleibt
    # erhalten. Nur wenn gar kein Nearby-Intent erkannt -> None.
    # Fallback Ollama: ggf. included_type=null + schwaechere exclude_types
    # (akzeptierte Degradierung; Freitext-Query traegt trotzdem).
```


## 4.1 Item -> Kategorie + Falsches ausklammern (Kernproblem 1)

Zwei Teilprobleme, bewusst getrennt:

1. **Item -> Kategorie** ("Shisha-Kopf" -> Tabak/Zubehoer; "Tomatensauce" ->
   Supermarkt; "Rockerbar" -> bar). Weltwissen -> LLM, im vorhandenen Tool-Call.
   Kein zusaetzlicher API-Call, keine Tabelle. Marginalkosten = 0.
2. **Falsches raus.** Zwei Hebel, vom LLM gesetzt, vom Code angewandt:
   - *Positiv-Narrow:* `included_type` (+`strictTypeFiltering`) im searchText —
     z.B. „Rockerbar" -> `textQuery="Rockerbar"` + `includedType="bar"`: behaelt
     die „Rocker"-Nuance im Freitext, narrowt aber serverseitig auf Bars.
   - *Negativ-Filter:* `exclude_types` clientseitig auf `types`/`primary_type` —
     fuer typlose Faelle („Shisha-Zubehoer", kein sauberer Typ): bar/restaurant
     o.ae. rauswerfen.

UX-Sicherheitsnetz gegen Fehldeutung: Saleria spiegelt zurueck, wonach sie sucht
("Ich suche *{subject}* in der Naehe von …"), damit korrigierbar.

Ehrliche Grenze: Googles `types` ist unscharf — kein `shisha_shop`-Typ; eine Bar
ist manchmal nur `store`. `strictTypeFiltering` kann zudem legitime Treffer mit
abweichendem `primaryType` wegfiltern (Knopf: bei Ueber-Narrowing strict
abschalten). Der Ausschluss ist gute Heuristik, keine Garantie. Bei Durchrutschen
im Smoketest -> Plan B (§8).

## 4.2 Reisemodus -> Radius (Kernproblem 2: Distanz)

Distanz-Disziplin ist Pflicht (sonst die 100-km-Bar). `searchText` kann KEINEN
harten Kreis (nur weichen `locationBias`-Kreis), daher: `rankPreference=DISTANCE`
+ clientseitiger Haversine-Cap auf den Radius. Saleria fragt den Modus, falls
nicht angegeben (eine Frage, wie Phase 92). Radius = grobe „in ~1 h erreichbar":

```python
RADIUS_BY_MODE: dict[str, int] = {  # Meter, Luftlinie
    "walking":   6_000,   # ~1 h Fussweg
    "transit":  15_000,   # grob; Luftlinie ist fuer OEPNV der schwaechste Proxy
    "bicycling":15_000,   # optional, Modus ist bereits im Vokabular
    "driving":  40_000,   # 1 h @ ~40 km/h; Luftlinie -> per Strasse am Rand >1 h
}
```

Bei 0 Treffern innerhalb Radius: einmal weiten (Faktor ~2) + Retry, dann Hinweis.
**Cap (Codex #2):** der `locationBias`-Kreis von `searchText` akzeptiert max.
50.000 m. Die Weitung MUSS auf 50.000 geclampt werden — sonst wird aus Auto
40 km -> 80 km ein INVALID_REQUEST. Praktisch weitet Auto also nur 40 -> 50 km.

Ehrliche Grenze: Cap ist Luftlinie, „1 h" ist Fahrzeit -> am Rand leichte
Ueberdeckung; OEPNV der wackligste Fall. Bewusst Pauschalschaetzung (Lera).
Praezise Fahrzeit -> Plan B (§8).

## 5. Ablauf (State)

1. **Turn 1.** `is_nearby_candidate` -> sonst Fallthrough. Bei Treffer
   `NearbyIntentParser.parse` -> `NearbyQueryDraft` (Codex #4).
   - `location_text` fehlt -> Rueckfrage „Wo bist du gerade?" (Draft bleibt erhalten).
   - `travel_mode` fehlt -> Rueckfrage „Wie willst du hin — zu Fuss, ÖPNV, Auto?".
   - Erst wenn `draft.to_query()` vollstaendig ist -> `NearbyQuery` -> Suche.
   - Echo der verstandenen Absicht (korrigierbar).
2. **Geocode + Suche.** `NearbyPlaceSearch.search(query)` (§4): Geocode -> Radius
   -> ein searchText (mit/ohne `includedType`) -> Client-Cap/Filter -> Distanz-Sort.
   - 0 Treffer -> Hinweis + Angebot (weiter weg / ohne `open_now`).
   - >=1 -> Pick-Liste (Name, Adresse, Entfernung, ggf. „offen bis …" / Rating),
     registriert als `nearby_place_pick`.
3. **Pick (Turn N).** `_handle_list_pick` -> `MapsLinkBuilder.build_place_link(
   name, place_id)`. Antwort = gewaehlter Ort + Maps-Link.

YAGNI beim Link: Nutzer ist vor Ort; Maps routet ab „Dein Standort". Daher
Place-Link, kein zweiter Routing-Call. Navigation mit echtem Origin = E5.

## 6. Tests

- `test_google_geocoder.py`: Request/Parse, Treffer -> LatLng, 0/Fehler -> None,
  429/403.
- `test_nearby_place_search.py`:
  - searchText-Body: mit `included_type` -> `includedType`+`strictTypeFiltering`
    gesetzt; ohne -> nur `textQuery`; `locationBias`-Kreis + `rankPreference=DISTANCE`
    + `pageSize=20` immer; **KEIN `openNow` im Body** (Codex #1); FieldMask enthaelt
    explizit `places.id`, `places.displayName`, `places.formattedAddress`,
    `places.location`, `places.types`, `places.primaryType`,
    `places.currentOpeningHours`, `places.rating` (Codex #5).
  - Client-Radius-Cap (`distance_m > radius` -> raus), Weitung auf 50.000 geclampt
    (Codex #2), Client-Typ-Filter (`primary_type="bar"` raus, `store` bleibt),
    `open_now`-Client-Filter: **bekannt geschlossen -> raus, unbekannt -> BLEIBT**
    (Codex #1), Distanz-Sort, Top-N, 0-Treffer-Weiten-Retry, leerer Geocode ->
    Guard, 429/403.
- `test_nearby_intent_parser.py`: Vorfilter true (Shisha/Rockerbar) / false
  (Routen-Text **muss** false), Schema liefert search_query/included_type/
  exclude_types/travel_mode (gemockter LLM, KEIN echter Call); Rueckgabe ist
  `NearbyQueryDraft`; fehlender Ort/Modus -> Draft behaelt Geparstes,
  `to_query()` -> None (Codex #4). **Negativtest „mit Lisa"**: „ich bin mit Lisa
  in XY" -> „Lisa" NICHT als Ziel/Kontakt. Qualitaet der LLM-Zuordnung nicht
  unit-testbar -> §9.
- `test_nearby_place_commands.py`: Fallthrough, Turn 1 (+ Echo), Ask-Ort,
  Ask-Modus, 0-Treffer-Fallback, Pick -> Link, kein Key -> `_factory` None,
  Plugin-Manifest (priority, factory).
- `test_maps_link_builder.py`: `build_place_link` (Encoding, place_id, ValueError).
- Registry/Inventory: Plugin-Zahl +1.

## 7. Risiken

- **Prefilter-Kollision mit Route-Handlern.** Breiter Trigger („nenne mir / wo
  gibt es / wo kaufe ich"), darf Routen nicht stehlen. „mit <Kontaktname>"
  (Lisa/Andrea, Phase 92) NICHT als Adresse deuten. -> Negativtests + priority
  gegen Registry verifizieren.
- **`types` unzuverlaessig.** Kein `shisha_shop`; `strictTypeFiltering` kann
  ueber-narrowen. Ausschluss = Heuristik. -> Plan B + strict-Knopf.
- **LLM-Fehlklassifikation** (`included_type` falsch). -> Echo + korrigierbar;
  Freitext-Query traegt als Sicherheitsnetz mit.
- **OEPNV-Radius = Luftlinie** schwaechster Proxy. Bewusst grob; Plan B = Fahrzeit.
- **Geocode-Mehrdeutigkeit** (Straße/Stadt doppelt). -> bei 0 Treffern Rueckfrage.
- **Vorbedingung Cloud:** Places API (New) + Geocoding API aktiviert UND auf der
  API-Key-Restriction-Liste. (Lera-Check; Enterprise selbst = kein Schalter.)
- **`open_now`-Serverfilter-Falle.** `openNow` NICHT an die API (entfernt Laeden
  ohne hinterlegte Zeiten serverseitig, Codex #1) -> Client-Filter, unbekannt bleibt.
- **Retry-Radius-Cap.** Weitung > 50.000 m = INVALID_REQUEST -> clampen (Codex #2).
- **Kosten / SKU.** FieldMask enthaelt `rating` + `currentOpeningHours` ->
  **Text Search Enterprise-SKU** (NICHT Pro — Korrektur, Codex #3). Pro Anfrage
  1 Geocode (Essentials) + 1 searchText (Enterprise). Enterprise-Frei-Kontingent =
  1.000/Monat; bei ~104/Jahr (~9/Monat) -> **0 EUR**. Hoeherer 1k-Preis greift erst
  > 1.000/Monat (faellt nicht an). Enterprise ist KEIN Schalter — wird automatisch
  per Field-Mask ausgeloest.
- **Privacy.** Standort + Anliegen -> Google (US-Routing, EEA-Terms). Benannt.

## 8. Plan B

- **Distanz/OEPNV-Praezision:** `searchNearby` mit `routingParameters` +
  `routingSummaries` (echte Fahrzeit pro Modus statt Luftlinie), falls
  Pauschalradius zu grob. Kostet Routes-SKU pro Treffer -> nicht MVP.
- **Ausschluss zu lossy / harter Kreis noetig:** `searchNearby` bietet
  serverseitige `excludedTypes` + native Kreis-`locationRestriction`. Bewusst nur
  als Eskalation, falls der searchText-Client-Filter im Smoketest versagt.
- **Erste Seite komplett ausgefiltert (Codex #6):** MVP loest das NICHT per
  Pagination (jede Folgeseite = eigener billbarer Call, gegen YAGNI), sondern per
  `pageSize=20`-Puffer. Falls der Smoketest beim typlosen Dichtefall
  („Shisha-Zubehoer", erste Seite voll Bars) trotzdem „nichts gefunden" zeigt ->
  genau diesen Fall auf `searchNearby` + `excludedTypes` eskalieren (loest es an
  der Wurzel, da serverseitig vorgefiltert wird).

## 9. Abnahmekriterien

- Alle neuen Tests gruen; `ruff` + `mypy --strict` gruen auf geaenderten Dateien;
  volle Suite ohne Regression.
- Plugin-Inventar +1, Registry-Test gruen.
- **Live-Smoketests (Lera, quota-bewusst)** — pruefen LLM-Zuordnung + Distanz:
  - „Rockerbar in der Naehe von <Straße>, mit Auto" -> nahe Bars zuerst, **keine**
    100-km-Treffer; valider Maps-Link.
  - „Shisha-Kopf, wo kaufen, zu Fuss" -> ≥1 Treffer im 6-km-Umkreis, **keine
    Shisha-Bar**.
  - „Tomatensauce" -> Supermaerkte, **keine Restaurants**.
  - „ich bin mit Lisa in XY" -> Lisa ignoriert, nicht geroutet.

## 10. Etappen

- **E0** — `GoogleGeocoder` + Tests.
- **E1** — `NearbyPlaceSearch` (searchText + Client-Cap/Filter/Sort) + Tests.
- **E2** — `is_nearby_candidate` + `NearbyIntentParser` (Schema inkl. included_type/
  travel_mode) + Tests.
- **E3** — `MapsLinkBuilder.build_place_link` + Tests.
- **E4** — `NearbyPlaceCommandHandler` + Wiring (`base`, `remote_commands`,
  `start_saleria`, `message_handlers`) + Ask-Ort/Modus-Flow + Tests + Registry.
- **E5 (optional/spaeter)** — Matrix `m.location`/Geo-URI als Standort;
  Navigations-Link mit echtem Origin.

## 11. Korrekturen (Codex Review PR #285)

Sechs P2-Anmerkungen, alle gegen das Konzept verifiziert + valide; eingearbeitet
(Lera-Entscheidungen: Enterprise-SKU akzeptiert; #6 ohne Pagination).

1. **openNow nicht serverseitig.** `openNow` wurde aus dem searchText-Body
   entfernt; Filter rein clientseitig (bekannt geschlossen raus, unbekannt bleibt).
   Loest den Selbstwiderspruch zu §7 „unbekannt nicht hart filtern".
2. **Retry-Radius geclampt** auf 50.000 m (searchText-Kreis-Max). Auto weitet nur
   40 -> 50 km statt 40 -> 80 km (waere INVALID_REQUEST).
3. **SKU-Korrektur:** `rating` + Oeffnungszeiten loesen die Text-Search-**Enterprise**-
   SKU aus (nicht Pro). Akzeptiert; Kosten-Abschnitt entsprechend korrigiert
   (Frei-Kontingent 1.000/Monat, bei ~9/Monat weiterhin 0 EUR).
4. **NearbyQueryDraft** eingefuehrt (optionale location_text/travel_mode) fuer die
   Disambiguierungs-Phase; `NearbyQuery` bleibt all-required; Parser gibt Draft
   zurueck statt None -> Geparstes geht bei Rueckfrage nicht verloren, kein KeyError
   in `RADIUS_BY_MODE`.
5. **FieldMask vollstaendig** gemacht: `places.id`, `places.displayName`,
   `places.formattedAddress`, `places.location`, `places.types`,
   `places.primaryType`, `places.currentOpeningHours`, `places.rating`.
6. **Erste-Seite-ausgefiltert:** keine Pagination (YAGNI/Kosten); stattdessen
   `pageSize=20`-Puffer + Eskalation des typlosen Dichtefalls auf `searchNearby`
   (Plan B), falls der Smoketest es zeigt.
