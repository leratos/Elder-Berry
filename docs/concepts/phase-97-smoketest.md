# Phase 97 — Live-Smoketest (Lera, quota-bewusst)

> Voraussetzung: Phase 97 vollständig (bis E4) gemergt, Saleria neu gestartet,
> sodass `NearbyPlaceSearch`/`GoogleGeocoder`/`NearbyPlaceCommandHandler`
> verdrahtet sind. Vorher ist die Funktion nicht über den Chat erreichbar.

## 0. Cloud-Vorbedingung (einmalig prüfen)

In der Google Cloud Console für den verwendeten `google_maps_api_key`:

- [ ] **Places API (New)** aktiviert.
- [ ] **Geocoding API** aktiviert.
- [ ] Beide APIs stehen auf der **API-Restriction-Liste** des Keys
      (sonst `REQUEST_DENIED` trotz aktivierter API).

Schneller Negativ-Check: Wenn Saleria bei einer Suche „Geocoding ist falsch
konfiguriert / Dienst nicht verfügbar" o. ä. meldet (statt „Ort nicht
gefunden"), ist genau diese Liste das Problem (R2-C3 macht den Unterschied
sichtbar).

## 1. Der eine offene technische Punkt: `pageSize` vs. `maxResultCount`

`tools/nearby_place_search.py` sendet an `places:searchText` aktuell
`pageSize: 20` (so spezifiziert das Konzept §4/§6, Codex #6). Der ältere
`GoogleMapsRoutePlanner` nutzt für searchText noch `maxResultCount`. Beide
Feldnamen existier(t)en in der New-API-Historie; `pageSize` ist die aktuelle
Form. **Dieser Smoketest bestätigt das Feld.**

**So erkennst du, dass das Feld falsch ist:**
- Saleria meldet bei JEDER Suche sofort „ungültige Anfrage (400)" bzw.
  einen Places-Fehler, obwohl Geocoding klappt (Ort wird erkannt).
- In dem Fall: in `nearby_place_search.py` `"pageSize": _PAGE_SIZE` →
  `"maxResultCount": _PAGE_SIZE` ändern, neu deployen, Szenario 2 erneut.

Wenn die Szenarien 2–5 plausible Treffer liefern, ist `pageSize` korrekt.

## 2. Kernszenario A — Kaufen, distanzkorrekt (Auto)

**Eingabe (eine Nachricht):**
> „Ich bin <eine reale Straße + Stadt, wo du die Umgebung kennst> und brauche
> einen Shisha-Kopf — wo kaufe ich den hier? Mit dem Auto."

**Erwartet:**
- [ ] Saleria spiegelt die Absicht („Ich suche … in der Nähe von …").
- [ ] Trefferliste mit **nahen** Läden zuerst, **keine** 100-km-Treffer.
- [ ] **Keine Shisha-*Bar*** in der Liste (Kategorie-Filter greift; ggf. nur
      teilweise — siehe „Bekannte Grenze" unten).
- [ ] Jeder Treffer mit Name, Adresse, **Entfernung**, ggf. „offen bis …".
- [ ] **Google-Attribution** wird angezeigt (Pflicht, R2-C4).
- [ ] „Treffer 2" o. ä. → ausgewählter Ort + **valider Google-Maps-Link**
      (öffnet den Ort, nicht eine Route).

## 3. Kernszenario B — Kaufen, zu Fuß (enger Radius)

**Eingabe:**
> „Ich bin <Straße, Stadt> und brauche eine Tomatensauce — wo zu Fuß?"

**Erwartet:**
- [ ] ≥1 Treffer im ~6-km-Umkreis (Fuß-Radius).
- [ ] **Supermärkte**, **keine Restaurants** (Kategorie-Trennung).
- [ ] Distanzen plausibel klein (Fußweg).

## 4. Kernszenario C — Venue (Rockerbar)

**Eingabe:**
> „Ich bin mit Lisa in <Stadtteil>, kannst du mir eine Rockerbar nennen?"

**Erwartet:**
- [ ] **Lisa wird ignoriert** (kein Routing, nicht als Standort/Adresse
      gedeutet) — der Standort ist <Stadtteil>.
- [ ] Liste mit **Bars** in der Nähe, distanzsortiert.
- [ ] Maps-Link beim Pick valide.

## 5. Negativszenario D — Route darf nicht gestohlen werden

**Eingabe:**
> „Fahr mich nach <Stadt> Hbf, vorher Lisa abholen."

**Erwartet:**
- [ ] Das ist eine **Routenanfrage** → der normale Multi-Stop-Route-Handler
      übernimmt, **nicht** die Umkreissuche. (Prüft den Handler-Priority-
      Konflikt aus §7 / B4.)

## 6. Rückfrage-Flow (Draft-Persistenz, B1/R2-C5)

**Eingabe 1:**
> „Ich brauche einen Baumarkt in <Stadt>."  *(kein Reisemodus genannt)*

**Erwartet:**
- [ ] Saleria fragt **einmal** nach dem Reisemodus.

**Eingabe 2 (frische Nachricht):**
> „Mit dem Auto."

**Erwartet:**
- [ ] Saleria führt die Suche fort, **ohne** „wonach suchst du nochmal?" —
      Subject/Query aus Eingabe 1 sind erhalten (Draft-Store, B1). Wenn hier
      der Kontext verloren geht, ist der Session-Key falsch gewählt (B1).

## 7. Bekannte Grenzen (kein Bug, sondern Designentscheidung)

- Googles `types` ist unscharf — es gibt keinen `shisha_shop`-Typ; eine echte
  Bar ist manchmal nur `store`. Der Ausschluss ist gute Heuristik, **keine
  Garantie**. Wenn im typlosen Dichtefall („Shisha-Zubehör", erste Seite voll
  Bars) trotz Puffer „nichts gefunden" erscheint → das ist der dokumentierte
  Eskalationsfall auf `searchNearby` + `excludedTypes` (Plan B, §8).
- ÖPNV-Radius ist Luftlinie (schwächster Proxy). Bewusst grob.
- Cap ist Luftlinie, „1 h" ist Fahrzeit → am Rand leichte Überdeckung.

## 8. Quota / Kosten (zur Beruhigung)

Pro Anfrage: 1 Geocode (Essentials) + **1–2** searchText (Enterprise; 2 nur
beim 0-Treffer-Weitungs-Retry). Enterprise-Frei-Kontingent = 1.000/Monat; bei
~9/Monat → **0 EUR**. Du kannst also alle Szenarien gefahrlos durchspielen.
