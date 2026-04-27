# Visual Assets für Public-Repo

Slot-Liste für Tranche B (Phase 68.2: README-Refactor + Quickstart).
Diese Bilder erzeugst du selbst und legst sie in diesem Verzeichnis ab,
**bevor** Tranche B mergebar ist — die README wird sie referenzieren.

## Benötigte Bilder

### 1. `hero.png` — Hero-Bild oben in der README

- **Was**: ein einzelnes, repräsentatives Bild ganz oben in der
  README (die "Visitenkarte" des Repos).
- **Vorschläge**, was zu zeigen wäre, eines davon reicht:
  - Saleria-Avatar im Pepper's-Ghost-Display in Aktion
  - Avatar-Sprite mit einer charakteristischen Emotion (z.B. cheerful)
    auf transparentem Hintergrund
  - Foto vom physischen Setup (RPi5 + Display + Drehteller)
- **Format**: PNG, **min. 1280×640 px**, idealerweise quadratisch
  oder breiter.
- **Tipp**: Ein gutes Foto schlägt einen mittelmäßigen Screenshot.

### 2. `screenshot-dashboard.png` — Settings-Dashboard

- **Was**: Saleria-Settings-Dashboard, Browser-Vollbild.
- **Empfohlene Ansicht**: "Dienste"- oder "Matrix"-Tab, weil dort am
  meisten passiert.
- **Achtung Privacy**: Vor dem Screenshot **alle Token-Felder
  blanken** (`••••••`-Display nutzt das Dashboard ja schon, aber
  Domain-Felder ggf. mit `example.com` mocken).
- **Format**: PNG, min. 1280px Breite. Querformat.

### 3. `screenshot-element-chat.png` — Matrix-Konversation mit Saleria

- **Was**: Element-Web-Client mit einer typischen
  Saleria-Konversation:
  - User-Frage
  - Saleria-Antwort mit Emotion-Tag oder Sprachnachrichten-Icon
  - Optional: ein Befehl wie "/wetter morgen" + Antwort
- **Privacy**: User-ID auf `@user:matrix.example.com` zensieren
  (Element zeigt sie oben, einfach in einem Bildbearbeitungs-Tool
  mit Rechteck überdecken). Avatar-Profilbild auch unkenntlich
  machen, falls es ein echtes Foto ist.
- **Format**: PNG, ca. 800–1000 px Breite (Element-typisch
  Hochformat).

### 4. `screenshot-setup-wizard.png` — Setup-Wizard

- **Was**: Setup-Wizard auf Schritt 7 ("Optionale Dienste") oder
  Schritt 1 ("Willkommen"), je nach Bevorzugung.
- **Privacy**: Alle Felder leer oder mit `example.com`-Werten.
- **Format**: PNG, min. 1024 px Breite.

### 5. `architecture-diagram.svg` — Architektur-Diagramm (optional)

Wenn du Lust hast, ein klares 4-Tier-Diagramm zu zeichnen
(Rootserver/Tower/Laptop/RPi5 + Pfeile zwischen den Komponenten):
gerne. Die ASCII-Variante in der aktuellen README ist OK, aber ein
SVG ist hübscher.

- **Format**: SVG (skaliert sauber) oder PNG ≥ 1600 px Breite.
- **Tools**: draw.io, Excalidraw, Figma — alles ok.
- **Privacy**: keine konkreten Domains/IPs, nur Rollen.

## Wenn Bilder fehlen

Tranche B kann auch mit **nur dem Hero-Bild** released werden — die
anderen Slots sind im README dann auskommentiert oder durch
Text-Beschreibungen ersetzt. Nicht alle auf einmal nötig.

## Was definitiv **nicht** in dieses Verzeichnis gehört

- Foto-Material aus `src/elder_berry/avatar/assets/` —
  das sind die Sprite-Sheets zur Laufzeit, gehören nicht zur Doku.
- Voice-Samples (`src/elder_berry/tts/voices/`) — gleiches Argument.
- Test-Outputs / Screenshots aus dem Dev-Workflow — gehören in
  `tests/fixtures/` oder werden gar nicht eingecheckt.

## Lizenz

Bilder, die du hier ablegst, stehen automatisch unter der gleichen
MIT-Lizenz wie der Rest des Repos. Wenn du fremde Inhalte einbaust
(z.B. ein Element-Screenshot), achte auf deren Lizenzbedingungen —
bei Element/Matrix.org sind Screenshots in Software-Doku üblich und
unkritisch.
