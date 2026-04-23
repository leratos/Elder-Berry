# Konzept: CSP unsafe-inline entfernen (Security H-2)

**Status:** Konzept – noch nicht implementiert  
**Priorität:** Hoch  
**Betroffene Dateien:**
- `src/elder_berry/web/security_middleware.py`
- `src/elder_berry/web/templates/setup_wizard.html` (872 Zeilen, 27 Treffer)
- `src/elder_berry/web/templates/avatar_editor.html` (910 Zeilen, 9 Treffer)
- `src/elder_berry/web/templates/audio_dashboard.html` (557 Zeilen, 9 Treffer)
- `src/elder_berry/web/templates/settings_panel.html` (621 Zeilen, 2 Treffer)
- `src/elder_berry/web/` (neues `static/`-Verzeichnis für JS/CSS)

---

## Problem

Die aktuelle CSP erlaubt `'unsafe-inline'` für `script-src` und `style-src`:

```python
"script-src 'self' 'unsafe-inline'; "
"style-src 'self' 'unsafe-inline';"
```

Das bedeutet: inline `<script>`-Blöcke, `onclick=`/`onchange=`-Handler und
inline `<style>`-Blöcke werden vom Browser ausgeführt – ohne Herkunftsprüfung.
Gelangt irgendwo User-Input ungefiltert in ein Template (jetzt oder künftig),
ist XSS möglich. `'unsafe-inline'` neutralisiert den zentralen XSS-Schutz der CSP.

---

## Ziel

```python
"script-src 'self'; "
"style-src 'self';"
```

Keine Ausnahmen. Alle JS und CSS kommen aus `static/`, der Browser validiert
die Herkunft. Inline-Angriffe sind strukturell ausgeschlossen.

---

## Umsetzungsplan

### Schritt 1 – Static-File-Serving einrichten

FastAPI liefert bisher keine statischen Dateien für das Dashboard aus.
Einzufügen in `src/elder_berry/web/settings_dashboard.py` (oder wo `setup_security`
aufgerufen wird):

```python
from fastapi.staticfiles import StaticFiles

app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)
```

Verzeichnisstruktur anlegen:
```
src/elder_berry/web/static/
  css/
    dashboard.css
    setup_wizard.css
    avatar_editor.css
    audio_dashboard.css
  js/
    dashboard.js
    setup_wizard.js
    avatar_editor.js
    audio_dashboard.js
```

### Schritt 2 – `<style>`-Blöcke auslagern (pro Template)

Jedes `<style>...</style>` im `<head>` der Templates wird in die passende
`.css`-Datei verschoben. Im Template:

```html
<!-- vorher -->
<style>
  .container { ... }
</style>

<!-- nachher -->
<link rel="stylesheet" href="/static/css/setup_wizard.css">
```

### Schritt 3 – Inline-Event-Handler ersetzen

Alle `onclick=`, `onchange=`, `oninput=`, `onsubmit=` aus den HTML-Tags entfernen.
Stattdessen `id` oder `data-*`-Attribute setzen und im externen JS per
`addEventListener` verdrahten.

Beispiel aus `setup_wizard.html`:
```html
<!-- vorher -->
<button onclick="submitPassword()">Weiter</button>

<!-- nachher -->
<button id="btn-submit-password">Weiter</button>
```

```js
// setup_wizard.js
document.getElementById("btn-submit-password")
  .addEventListener("click", submitPassword);
```

### Schritt 4 – `<script>`-Blöcke auslagern

Alle `<script>...</script>`-Blöcke am Ende der Templates werden in die
passenden `.js`-Dateien verschoben. Im Template:

```html
<!-- vorher -->
<script>
  function submitPassword() { ... }
</script>

<!-- nachher -->
<script src="/static/js/setup_wizard.js" defer></script>
```

`defer` stellt sicher dass das DOM fertig ist wenn das JS läuft – kein
`DOMContentLoaded`-Wrapper nötig.

### Schritt 5 – CSP verschärfen

Nach erfolgreichem Testen aller Templates in `security_middleware.py`:

```python
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; "
    "script-src 'self'; "        # unsafe-inline weg
    "style-src 'self'; "         # unsafe-inline weg
    "img-src 'self' data:; "     # data: für Avatar-Vorschauen
    "connect-src 'self';"        # fetch()/XHR nur zum eigenen Server
)
```

---

## Reihenfolge und Abhängigkeiten

```
Schritt 1 (Static-Serving) → muss zuerst fertig sein
    ↓
Schritt 2+3+4 parallel pro Template (jeweils unabhängig):
  - setup_wizard.html   (größter Aufwand: 27 Treffer)
  - avatar_editor.html  (9 Treffer)
  - audio_dashboard.html (9 Treffer)
  - settings_panel.html  (2 Treffer, einfachster Start)
    ↓
Schritt 5 (CSP schärfen) → erst wenn ALLE Templates migriert + getestet
```

---

## Teststrategie

- Pro Template: manuelle Sichtprüfung im Browser (alle Buttons/Formulare klicken)
- Automatisch: CSP-Header-Test in `tests/test_security.py` auf `unsafe-inline`
  prüfen → Test schlägt fehl bis alle Templates migriert sind (TDD-Ansatz möglich)
- Browser-Konsole: keine CSP-Violations dürfen auftreten

---

## Risiken

| Risiko | Mitigation |
|--------|-----------|
| Template-Funktionen brechen durch fehlende Event-Handler | Schritt für Schritt pro Template, Browser-Test vor nächstem Template |
| `data:`-URIs für Avatar-Bilder werden von `default-src 'self'` blockiert | `img-src 'self' data:` explizit erlauben (Schritt 5) |
| fetch()-Aufrufe an externe APIs (Wetter, LLM) via Dashboard-JS | `connect-src` ggf. erweitern; prüfen ob solche Calls existieren |

---

## Aufwandschätzung

| Schritt | Aufwand |
|---------|---------|
| Static-Serving einrichten | 30 min |
| settings_panel.html (2 Treffer) | 1 h |
| audio_dashboard.html (9 Treffer) | 2 h |
| avatar_editor.html (9 Treffer) | 2–3 h |
| setup_wizard.html (27 Treffer) | 4–5 h |
| CSP-Update + Tests | 30 min |
| **Gesamt** | **~10–12 h** |

Empfehlung: Als eigene Phase anlegen (z.B. Phase 63 – CSP-Hardening).
