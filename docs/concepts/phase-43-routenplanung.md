# Phase 43 – Routenplanung (Google Maps Directions)

## Ziel

Saleria kann auf natürliche Anfrage eine Fahrt planen: Adresse aus Kontakten
nachschlagen, Fahrtdauer via Google Maps Directions API berechnen, Abfahrtszeit
rückwärts ableiten und einen klickbaren Google-Maps-Link liefern.

**Beispiel-Dialog:**
```
User:  "Plane meine Fahrt zu Lisa, muss morgen um 16 Uhr da sein"
Saleria: "Fahrt zu Lisa Müller (Hauptstr. 12, 10115 Berlin) dauert ca. 1h 20min.
         Du solltest spätestens um 14:25 losfahren (15 Min Puffer).
         → [Google Maps Route starten]"
```

## Architektur

### Neue Klassen

| Klasse | Datei | Verantwortung |
|--------|-------|---------------|
| RoutePlanner | `tools/route_planner.py` | Google Maps Directions API, Fahrtdauer, Link-Generierung |
| RouteCommandHandler | `comms/commands/route_commands.py` | Intent-Parsing, Kontakt-Lookup, Antwort-Formatierung |

### Bestehende Klassen (Änderungen)

| Klasse | Änderung |
|--------|----------|
| ContactStore | Keine – `address`-Feld existiert seit Phase 38 |
| SecretStore | Neuer Key: `google_maps_api_key` |
| RemoteCommandHandler | RouteCommandHandler registrieren |
| start_saleria.py | RoutePlanner instanziieren + DI |

## Home-Adresse (Option A: Kontakt)

Die Home-Adresse des Nutzers wird als normaler Kontakt gespeichert, markiert
über die Gruppe `home`. Damit funktioniert jede Adresse als Start oder Ziel.

```
kontakt: Zuhause, adresse=Musterstr. 5 12345 Berlin, gruppe=home
```

**Lookup-Logik:**
1. Kein expliziter Startpunkt → ContactStore: `find_by_group("home")` → erste Adresse
2. Expliziter Start: "von Mama zu Lisa" → beide aus Kontakten
3. Kein Kontakt mit `home`-Gruppe → Fehler: "Bitte hinterlege deine Adresse als Kontakt mit Gruppe 'home'"

**ContactStore-Erweiterung:**
```python
def find_by_group(self, group: str) -> list[dict]:
    """Kontakte filtern deren 'groups' das Keyword enthält."""
    # groups ist bereits ein Textfeld, LIKE-Suche reicht
    sql = "SELECT * FROM contacts WHERE groups LIKE ?"
    return self._fetchall(sql, (f"%{group}%",))
```

## RoutePlanner (`tools/route_planner.py`)

```python
class RoutePlanner:
    """Google Maps Directions API – Fahrtdauer + Link-Generierung."""

    BASE_URL = "https://maps.googleapis.com/maps/api/directions/json"
    MAPS_LINK = "https://www.google.com/maps/dir/?api=1"

    def __init__(self, api_key: str, default_buffer_minutes: int = 15):
        self._api_key = api_key
        self._buffer = default_buffer_minutes
        self._client = httpx.AsyncClient(timeout=10.0)

    async def get_route(
        self, origin: str, destination: str,
        departure_time: datetime | None = None
    ) -> RouteResult:
        """
        Fragt die Directions API ab.

        Args:
            origin: Startadresse (Freitext oder Koordinaten)
            destination: Zieladresse
            departure_time: Abfahrtszeit (für Verkehrsprognose).
                            Wenn None → jetzt.

        Returns:
            RouteResult mit duration_seconds, duration_text,
            distance_text, summary (Routenname)
        """
        params = {
            "origin": origin,
            "destination": destination,
            "key": self._api_key,
            "language": "de",
            "units": "metric",
        }
        if departure_time and departure_time > datetime.now():
            params["departure_time"] = str(int(departure_time.timestamp()))
            params["traffic_model"] = "best_guess"
        resp = await self._client.get(self.BASE_URL, params=params)
        resp.raise_for_status()
        return self._parse_response(resp.json())

    def calculate_departure(
        self, arrival_time: datetime, duration_seconds: int
    ) -> datetime:
        """Abfahrtszeit = Ankunft - Fahrtdauer - Puffer."""
        return arrival_time - timedelta(
            seconds=duration_seconds
        ) - timedelta(minutes=self._buffer)

    def generate_maps_link(self, origin: str, destination: str) -> str:
        """Google Maps Deep-Link (öffnet App auf Android)."""
        params = urlencode({
            "api": "1",
            "origin": origin,
            "destination": destination,
            "travelmode": "driving",
        })
        return f"{self.MAPS_LINK}&{params}"

    def _parse_response(self, data: dict) -> "RouteResult":
        """Parst die Directions API Response."""
        if data["status"] != "OK":
            raise RouteError(f"Directions API: {data['status']}")
        leg = data["routes"][0]["legs"][0]
        # duration_in_traffic wenn verfügbar (genauer), sonst duration
        duration = leg.get("duration_in_traffic", leg["duration"])
        return RouteResult(
            duration_seconds=duration["value"],
            duration_text=duration["text"],
            distance_text=leg["distance"]["text"],
            summary=data["routes"][0].get("summary", ""),
            start_address=leg["start_address"],
            end_address=leg["end_address"],
        )

    async def close(self):
        await self._client.aclose()


@dataclass
class RouteResult:
    duration_seconds: int
    duration_text: str
    distance_text: str
    summary: str
    start_address: str
    end_address: str


class RouteError(Exception):
    pass
```

### Wichtig: `departure_time` vs `arrival_time`

Die Google Directions API unterstützt `arrival_time` **nur für Transit** (ÖPNV),
nicht für `driving`. Deshalb der Zwei-Schritt-Ansatz:

1. **Erste Abfrage**: `get_route(origin, dest)` ohne `departure_time` → Basis-Dauer
2. **Rückwärtsrechnung**: `arrival - duration - buffer = departure`
3. **Optionale zweite Abfrage**: `get_route(origin, dest, departure_time=departure)`
   → Verfeinerte Dauer mit Verkehrsprognose für die berechnete Abfahrtszeit
4. Wenn sich die Dauer signifikant ändert (>10 Min Differenz): nochmal korrigieren

In der Praxis reicht Schritt 1+2 für die meisten Fälle. Schritt 3 nur wenn
`departure_time` in der Zukunft liegt (Verkehrsprognose macht nur dann Sinn).

## RouteCommandHandler (`comms/commands/route_commands.py`)

### Patterns

```python
# "plane (meine) fahrt/reise/route zu Lisa"
# "wie komme ich zu Lisa"
# "navigation zu Lisa"
# "fahrt zu Lisa, morgen um 16 uhr"
ROUTE_PLAN_PATTERN = re.compile(
    r"(?:plane|planen|berechne|navigation|navigiere|"
    r"wie (?:komme|fahre) ich)\s+"
    r"(?:meine\s+)?(?:fahrt|reise|route|weg)?\s*"
    r"(?:zu|nach|richtung)\s+(.+)",
    re.IGNORECASE
)

# "fahrt von Mama zu Lisa, morgen 16 uhr"
ROUTE_FROM_TO_PATTERN = re.compile(
    r"(?:plane|berechne|navigation)?\s*"
    r"(?:meine\s+)?(?:fahrt|reise|route|weg)?\s*"
    r"von\s+(.+?)\s+(?:zu|nach|richtung)\s+(.+)",
    re.IGNORECASE
)
```

### Zeitextraktion

Die Ankunftszeit wird aus dem Freitext extrahiert. Muster:

| Input | Parsing |
|-------|---------|
| "morgen um 16 uhr" | morgen + 16:00 |
| "um 14:30" | heute + 14:30 |
| "übermorgen 10 uhr" | übermorgen + 10:00 |
| "Freitag um 9" | nächster Freitag + 09:00 |
| kein Zeitangabe | → Abfahrt jetzt, keine Rückwärtsrechnung |

```python
# Zeitparser – extrahiert Ankunftszeit aus Freitext
TIME_PATTERN = re.compile(
    r"(?:um\s+)?(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?",
    re.IGNORECASE
)
DATE_KEYWORDS = {
    "morgen": 1, "übermorgen": 2,
    "montag": None, "dienstag": None, "mittwoch": None,
    "donnerstag": None, "freitag": None, "samstag": None, "sonntag": None,
}

def parse_arrival_time(text: str) -> datetime | None:
    """Extrahiert Ankunftszeit aus Freitext. None wenn keine Zeitangabe."""
    # Implementation: Datum-Keywords + Uhrzeit kombinieren
    ...
```

### Handler-Klasse

```python
class RouteCommandHandler(BaseCommandHandler):
    """Routenplanung via Google Maps Directions API."""

    KEYWORDS = [
        "plane", "fahrt", "reise", "route", "navigation",
        "navigiere", "wie komme ich", "wie fahre ich",
    ]

    def __init__(
        self,
        route_planner: RoutePlanner,
        contact_store: ContactStore,
    ):
        self._planner = route_planner
        self._contacts = contact_store

    async def handle(self, message: str, user_id: str) -> CommandResult:
        """Haupteinsprung – prüft Patterns, delegiert."""
        # 1) "von X zu Y" Pattern (expliziter Start)
        m = ROUTE_FROM_TO_PATTERN.search(message)
        if m:
            return await self._plan_route(
                origin_name=m.group(1).strip(),
                dest_name=m.group(2).strip(),
                raw_text=message,
            )
        # 2) "fahrt zu Y" Pattern (Start = Home)
        m = ROUTE_PLAN_PATTERN.search(message)
        if m:
            return await self._plan_route(
                origin_name=None,  # → Home-Kontakt
                dest_name=m.group(1).strip(),
                raw_text=message,
            )
        return CommandResult(success=False)

    async def _plan_route(
        self, origin_name: str | None, dest_name: str, raw_text: str
    ) -> CommandResult:
        """Kernlogik: Adressen auflösen → API → Antwort formatieren."""
        # 1. Adressen auflösen
        origin_addr = self._resolve_address(origin_name)
        dest_addr = self._resolve_address(dest_name)
        if not origin_addr or not dest_addr:
            missing = dest_name if not dest_addr else (origin_name or "Zuhause")
            return CommandResult(
                success=True,
                response=f"Ich konnte keine Adresse für '{missing}' finden. "
                         f"Ist eine Adresse im Kontakt hinterlegt?"
            )

        # 2. Ankunftszeit parsen
        arrival = parse_arrival_time(raw_text)

        # 3. Route abfragen
        try:
            result = await self._planner.get_route(origin_addr, dest_addr)
        except RouteError as e:
            return CommandResult(success=True, response=f"Routenfehler: {e}")

        # 4. Abfahrtszeit berechnen (wenn Ankunftszeit angegeben)
        departure_info = ""
        if arrival:
            departure = self._planner.calculate_departure(
                arrival, result.duration_seconds
            )
            departure_info = (
                f"Du solltest spätestens um {departure.strftime('%H:%M')} "
                f"losfahren ({self._planner._buffer} Min Puffer).\n"
            )

        # 5. Google Maps Link
        link = self._planner.generate_maps_link(origin_addr, dest_addr)

        # 6. Antwort zusammenbauen
        response = (
            f"🚗 Route zu {dest_name}:\n"
            f"📍 {result.end_address}\n"
            f"⏱️ Fahrtdauer: {result.duration_text} ({result.distance_text})\n"
            f"{departure_info}"
            f"🗺️ {link}"
        )
        return CommandResult(success=True, response=response)

    def _resolve_address(self, name: str | None) -> str | None:
        """
        Kontaktname → Adresse auflösen.

        None → Home-Kontakt (Gruppe "home")
        "Lisa" → ContactStore fuzzy search → address-Feld
        """
        if name is None:
            homes = self._contacts.find_by_group("home")
            if homes:
                return homes[0].get("address")
            return None

        # Fuzzy-Suche im ContactStore (wie bei contact_commands)
        results = self._contacts.search(name)
        if not results:
            return None
        # Bester Match: erster Treffer
        contact = results[0]
        return contact.get("address")
```

### command_descriptions (für LLM-Routing)

```python
COMMAND_DESCRIPTIONS = """
Route/Navigation:
- "plane meine fahrt zu <Name>" → Route von Zuhause zu Kontakt
- "fahrt von <Name> zu <Name>" → Route zwischen zwei Kontakten
- "wie komme ich zu <Name>" → Route von Zuhause
- Optionale Ankunftszeit: "morgen um 16 uhr", "übermorgen 10 uhr"
- Liefert: Fahrtdauer, Abfahrtszeit, Google Maps Link
"""
```

## Setup

### Google Maps Directions API aktivieren

1. Google Cloud Console → APIs & Services → Library
2. "Directions API" suchen → aktivieren
3. API Key erstellen (oder bestehenden verwenden) → Restrictions:
   - Application restriction: **keine** (Home-IP ist dynamisch → IP-Restriction unpraktisch)
   - API-Einschränkung: nur **"Directions API"** (begrenzt Schaden bei Key-Leak)
4. Key in SecretStore: `python -c "from elder_berry.core.secret_store import SecretStore; s = SecretStore(); s.store('google_maps_api_key', 'AIza...')"`

### Home-Kontakt anlegen

```
kontakt: Zuhause, adresse=Musterstr. 5 12345 Berlin, gruppe=home
```

Oder direkt in Nextcloud: Kontakt "Zuhause" mit Adresse + Gruppe "home" anlegen
→ CardDAV-Sync holt ihn automatisch.

## Kosten

| Posten | Kosten |
|--------|--------|
| Directions API | $5 / 1000 Requests |
| Google Free Tier | $200/Monat gratis |
| Realistisch | 1-5 Routen/Woche → ~$0.02/Monat |

Praktisch kostenlos im Free Tier.

## Abhängigkeiten

| Abhängigkeit | Status |
|-------------|--------|
| ContactStore mit address-Feld | ✅ Phase 38 |
| Google Cloud Account + Billing | ✅ vorhanden |
| httpx (async HTTP) | ✅ vorhanden |
| SecretStore | ✅ vorhanden |

### Neue Dependency

Keine – `httpx` und `urllib.parse` reichen. Kein Google-SDK nötig.

## Tests (~35 geplant)

### test_route_planner.py (~18 Tests)

```
- test_get_route_success: Mock-API → RouteResult korrekt geparsed
- test_get_route_with_departure_time: departure_time als Timestamp in Params
- test_get_route_with_traffic: duration_in_traffic bevorzugt über duration
- test_get_route_api_error: Status != OK → RouteError
- test_get_route_no_routes: Leere routes-Liste → RouteError
- test_get_route_network_error: httpx.RequestError → sauberer Fehler
- test_calculate_departure_simple: 16:00 Ankunft, 60min Dauer, 15min Puffer → 13:45
- test_calculate_departure_custom_buffer: Buffer-Override
- test_calculate_departure_midnight_wrap: Fahrt über Mitternacht
- test_generate_maps_link: URL-Format korrekt, Sonderzeichen encoded
- test_generate_maps_link_umlauts: Straße mit Umlauten korrekt encoded
- test_parse_response_minimal: Nur Pflichtfelder
- test_parse_response_full: Alle Felder inkl. summary
- test_parse_response_traffic_preferred: duration_in_traffic > duration
- test_close: Client wird geschlossen
- test_init_defaults: Default buffer = 15
- test_init_custom_buffer: Custom buffer
- test_departure_time_in_past_ignored: Vergangene departure_time → ohne Traffic
```

### test_route_commands.py (~17 Tests)

```
- test_plan_route_to_contact: "plane fahrt zu Lisa" → Route von Home zu Lisa
- test_plan_route_from_to: "fahrt von Mama zu Lisa" → Route Mama→Lisa
- test_plan_route_with_arrival_time: "morgen um 16 uhr" → Abfahrtszeit berechnet
- test_plan_route_no_time: Ohne Zeitangabe → nur Dauer + Link, keine Abfahrtszeit
- test_plan_route_contact_not_found: Unbekannter Kontakt → hilfreiche Fehlermeldung
- test_plan_route_no_address: Kontakt ohne Adresse → Hinweis
- test_plan_route_no_home: Kein Home-Kontakt → Hinweis "Gruppe home fehlt"
- test_plan_route_api_error: RouteError → Fehlermeldung
- test_resolve_address_home: None → Home-Kontakt Adresse
- test_resolve_address_by_name: "Lisa" → Fuzzy-Match → Adresse
- test_resolve_address_not_found: Unbekannt → None
- test_parse_arrival_morgen_16: "morgen um 16 uhr" → morgen 16:00
- test_parse_arrival_uebermorgen: "übermorgen 10 uhr" → übermorgen 10:00
- test_parse_arrival_heute: "um 14:30" → heute 14:30
- test_parse_arrival_no_time: "zu Lisa" → None
- test_maps_link_in_response: Antwort enthält Google Maps Link
- test_keywords_match: Alle KEYWORDS triggern Handler
```

## Implementierungsschritte

1. **ContactStore**: `find_by_group()` Methode ergänzen + Tests
2. **RoutePlanner**: Klasse + alle Methoden + Tests (Mock-API)
3. **parse_arrival_time()**: Zeitparser + Tests
4. **RouteCommandHandler**: Handler + Tests
5. **Integration**: RemoteCommandHandler registrieren, start_saleria.py DI
6. **Setup-Hinweis**: SecretStore Key + Home-Kontakt Anleitung in CLAUDE.md
7. **Commit**: `feature/phase-43-routenplanung`

## Edge Cases & Einschränkungen

| Fall | Handling |
|------|----------|
| Kontakt ohne Adresse | Klare Fehlermeldung: "Lisa hat keine Adresse hinterlegt" |
| Kein Home-Kontakt | "Bitte lege einen Kontakt mit Gruppe 'home' an" |
| Adresse nicht auflösbar (Tippfehler) | Google API gibt Status ZERO_RESULTS → "Adresse konnte nicht gefunden werden" |
| Verkehrslage ändert sich | Hinweis: "Geschätzte Abfahrtszeit – plane bei Stoßzeiten etwas mehr ein" |
| `departure_time` in Vergangenheit | Wird ignoriert (API gibt Basis-Dauer ohne Traffic) |
| Mehrere Kontakte mit gleichem Namen | Erster Treffer (wie bei contact_commands) |
| Sehr lange Fahrten (>6h) | Funktioniert, aber Verkehrsprognose wird ungenauer → Hinweis |

## Mögliche Erweiterungen (nicht in Phase 43)

- **ÖPNV-Modus**: `travelmode=transit` – Google unterstützt dann `arrival_time` direkt
- **Zwischenstopps**: "fahrt zu Lisa über Tankstelle" → `waypoints` Parameter
- **Mehrere Verkehrsmittel**: "mit dem Fahrrad zu Lisa" → `travelmode=bicycling`
- **Proaktiv**: CalendarWatcher erkennt Termin mit Adresse → automatischer Routenvorschlag
- **ETA-Updates**: Regelmäßig Fahrtdauer neu abfragen wenn Abfahrt näher rückt
- **Favoriten-Routen**: Häufige Strecken cachen (Arbeit ↔ Zuhause)
