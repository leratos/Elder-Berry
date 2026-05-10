# Phase 79 – Reichere Pseudocode-Anhänge in Plugin-Vorschlägen 📝

**Status:** ON HOLD (2026-05-10) — wird **nicht jetzt** umgesetzt.
**Branch (geplant):** `feature/phase-79-richer-pseudocode`
**Aufwand-Schätzung:** ~1 Session
**Voraussetzung:** Phase 78 abgeschlossen ✅ + **harter Trigger erfüllt** (siehe §2)
**Roadmap-Referenz:** Folge-Phase aus
[`docs/concepts/phase-78-plugin-self-suggestion.md`](phase-78-plugin-self-suggestion.md)
§9.

## 1. Ausgangslage

Phase 78 (Plugin Self-Suggestion) ist seit 2026-05-08 produktiv. Saleria
generiert pro Plugin-Vorschlag ein `description_md`-Feld nach dem
Template aus Phase 78 §4. Das Template enthält bereits:

- Beschreibung (2–4 Sätze)
- Beispielanfragen
- Vorgeschlagene Regex-Patterns
- Benötigte Services
- **Vollständiges `CommandPlugin`-Manifest in Python** (also schon ein
  Pseudocode-Block)
- Bemerkungen / Implementierungs-Hinweise

Phase 79 wäre eine **Erweiterung dieses Markdown-Bodys** um:

- `execute()`-Skizze als Pseudocode (Body-Logik, nicht nur Manifest)
- Beispiel-Tests als Pseudocode (Happy Path + Edge Cases)
- Gegebenenfalls Hinweise auf bestehende Helper im Codebase
  (`user_friendly_error`, `ContactStore`, etc.), die wiederverwendet
  werden könnten.

**Ablage-Mechanismus bleibt identisch:** alles im selben
`description_md`-Feld, server-side via `markdown-it-py` + `bleach`
gerendert, Login-geschützt. Keine neuen DB-Spalten, keine neuen Tabellen,
**keine** ladbaren `.py`-Dateien (R1-Guard aus Phase 78 bleibt zwingend
erhalten).

## 2. Ziel & Trigger-Bedingung

### 2.1 Ziel

Lera bekommt beim manuellen Implementieren eines Saleria-Vorschlags
einen **konkreteren Startpunkt** als heute. Statt nur die Plugin-
Manifest-Skizze hat sie eine grobe Body-Skizze und Test-Hinweise.
Implementierungs-Zeit pro Vorschlag soll dadurch sinken.

### 2.2 Wann diese Phase umgesetzt wird (harter Trigger)

Phase 79 wird **erst dann** umgesetzt, wenn **alle drei** folgenden
Bedingungen erfüllt sind. Wenn auch nur eine davon nicht zutrifft, bleibt
diese Phase auf Eis und wird nicht angefasst.

1. **Mindestens 5 Saleria-Vorschläge** (Status `in_pruefung`,
   `in_bearbeitung` oder `fertiggestellt`) sind in der DB. Solange
   weniger als fünf existieren, gibt es zu wenig Datenbasis für eine
   informierte Entscheidung.
2. **Mindestens 3 davon** wurden von Lera tatsächlich auf
   `fertiggestellt` (bzw. `abgelehnt` mit explizitem „zu dünn"-Reason)
   gesetzt. Das stellt sicher, dass Lera die Specs überhaupt durch den
   Implementierungs-Prozess geführt hat.
3. **Lera dokumentiert pro Vorschlag** (im Journal oder als Review-Notiz
   am Proposal) eine konkrete Lücke der heutigen Spec, die Phase 79
   geschlossen hätte. Beispiel-Formate, die zählen:
   - „Habe execute()-Body von Grund auf neu geschrieben, weil das
     Manifest keine Hinweise auf den Datenfluss gab — Pseudocode-Skizze
     hätte mir 20 min gespart."
   - „Hatte beim Test-Schreiben unklar, welche Edge-Cases Saleria sich
     vorgestellt hat — Test-Pseudocode hätte das geklärt."
   - „Habe die falsche Helper-Funktion benutzt; Saleria hätte mir
     `user_friendly_error` empfehlen können."

   Bauchgefühl-Aussagen wie *„Spec war ein bisschen knapp"* zählen
   ausdrücklich **nicht**. Es muss konkret werden, sonst riskieren wir,
   eine Erweiterung zu bauen, die eine eingebildete statt einer realen
   Lücke schließt.

### 2.3 Warum dieser strenge Trigger

Phase 79 ist eine **Erweiterung an der LLM-Halluzinations-Front** (siehe
§4 R1+R2). Das Risiko, dass Saleria mehr falschen Code emittiert, ist
real. Den Aufwand und das Risiko nehmen wir nur in Kauf, wenn
empirisch belegt ist, dass der Status quo (Phase 78 §4-Template) zu
dünn ist. Heute (2026-05-10) ist Phase 78 erst zwei Tage live, der
erste Vorschlag entsteht frühestens nach `THRESHOLD_DAYS = 7`. Eine
Implementation jetzt wäre **Premature Optimization gegen einen
imaginären Bedarf**.

**Selbst-Verpflichtung des Konzept-Autors:** Wenn diese Trigger-Bedingung
in 6 Monaten nicht erfüllt ist, wird Phase 79 endgültig **verworfen**
(`STATUS: VERWORFEN` in dieser Datei) statt weiter offen zu halten.
Open-Phases-on-Verdacht sind technische Schulden im Konzept-Bestand.

## 3. Was würde gebaut (wenn Trigger erfüllt)

Nur dokumentiert, damit der Aufwand abschätzbar ist — implementiert
wird das alles erst nach §2.2.

### 3.1 Erweiterung des System-Prompts

Saleria's Generator-Prompt (heute aus Phase 78 §4) bekommt zwei
zusätzliche Markdown-Sektionen:

```markdown
## Skizze für execute() (Pseudo-Code, nicht 1:1 kopieren)

```python
def execute(self, command: str, raw_text: str) -> CommandResult:
    if command == "<intent>":
        # 1. Input-Parsing
        match = <PATTERN>.match(raw_text)
        if not match:
            return CommandResult(command, success=False, text="...")
        # 2. Service-Call
        result = self._<service>.<action>(match.group(1))
        # 3. CommandResult bauen
        return CommandResult(command, success=True, text=...)
```

## Beispiel-Tests (Pseudo-Code)

- Happy Path: <konkrete Eingabe> → <konkrete Ausgabe>
- Service-Down: <Mock raise> → success=False mit user_friendly_error
- Pattern-Miss: <Eingabe ohne Match> → success=False
```

### 3.2 Length-Caps

- `execute()`-Skizze: **max. 25 Zeilen Pseudocode**. Längere Bodies
  zerlegt Saleria in mehrere Schritte oder lässt sie weg.
- Test-Hinweise: **max. 5 Bullet-Points**. Keine vollständigen
  Test-Funktionen.
- Hard-Cap im System-Prompt explizit nennen, damit das LLM nicht in
  Versuchung kommt, einen kompletten Module-Body zu emittieren.

### 3.3 Visueller Disclaimer im Dashboard

Pseudocode-Sektionen werden im PWA-Modul `proposals.js` mit einem
orangen Banner gerendert:

> ⚠️ LLM-generierter Pseudocode — als Inspiration nutzen, **nicht 1:1
> kopieren**. APIs/Helper-Namen können halluziniert sein.

Das ist Verhaltens-Nudge, nicht technischer Schutz. Trotzdem wichtig:
ohne diesen Banner ist die Phase nicht abgeschlossen.

### 3.4 Tests

- `test_assistant.py`: System-Prompt-Erweiterung passt durch, Plugin-
  Candidate-JSON-Block bleibt sauber extrahiert.
- `test_proposal_renderer.py` (oder Erweiterung von
  `test_markdown_renderer.py`): Neue Sektionen werden gerendert,
  Pseudocode-Blöcke kriegen die richtige CSS-Klasse für den Banner.
- Smoketest: Lera lässt Saleria einen Vorschlag generieren, prüft
  Markdown-Output gegen die Length-Caps.

## 4. Risiken / aktive Hinweise

- **R1 – Auto-Load-Verlockung (geerbt aus Phase 78).** Mehr realistisch
  aussehender Pseudocode → mehr Versuchung, irgendwann „die guten 80 %
  automatisch zu laden". **R1-Guard bleibt zwingend.** Saleria emittiert
  niemals ladbare `.py`-Dateien, niemals Filesystem-Drops, niemals
  Sandbox-Lint-Pipelines. Alles Markdown, alles Pseudocode, alles
  manuell-implementiert.

- **R2 – Halluzinations-Oberfläche skaliert.** Saleria muss heute ~5–10
  Zeilen Manifest emittieren. Mit Phase 79 kommen ~25 Zeilen
  `execute()`-Pseudocode + 5 Test-Bullets dazu. Jede zusätzliche Zeile
  ist eine Gelegenheit für eine plausibel-falsche Methodensignatur,
  einen halluzinierten Helper-Aufruf, eine erfundene API-Form.
  Mitigation:
  - Length-Caps (§3.2)
  - Visueller Disclaimer (§3.3)
  - Lera-Review-Disziplin: **niemals Codeblöcke 1:1 kopieren**, immer
    gegen das echte Codebase (`grep`/IDE) abgleichen.

- **R3 – Copy-Paste-Risiko in den Echt-Code.** Phase 78 §6 R3 hat das
  Risiko schon: Lera könnte aus Bequemlichkeit halluzinierten Code
  übernehmen. Phase 79 verschärft das. Mitigation: §3.3-Banner +
  bewusste Selbst-Verpflichtung.

- **R4 – Prompt-Komplexität wächst.** Mehr Anforderungen an Saleria
  bedeuten mehr Token, längere Iterationen, höheres Risiko, dass das
  LLM die Strukturvorgabe „verliert". Mitigation: System-Prompt
  bleibt strikt strukturiert (Sections benannt, Length-Caps explizit,
  „weglassen wenn unsicher"-Hinweis).

- **R5 – Token-Kosten in `description_md`.** Längere Specs = mehr
  Bytes in der DB und mehr LLM-Output-Tokens pro Trigger. Bei 1–3
  Vorschlägen pro Monat (heutige Schätzung) ist das vernachlässigbar.
  Falls Phase 79 auf einer Multi-User-Saleria läuft (Forks), könnte
  das relevant werden — dann Length-Caps strenger setzen.

- **R6 – Trigger-Bedingung wird schleichend aufgeweicht.** Wenn Phase 79
  nach 3 statt 5 Vorschlägen umgesetzt wird, weil sich Lera „gerade
  gelangweilt hat" — exakt das Anti-Pattern. Mitigation: §2.2-Trigger
  ist hart formuliert. Wenn er aufgeweicht wird, **Begründung in
  diese Datei eintragen**, damit es keine stillschweigende Verschiebung
  gibt.

## 5. Out of Scope (auch im Trigger-Fall)

- **Ladbare `.py`-Dateien als Anhang.** Bleibt verboten — R1.
- **Sandbox-Pipeline für Vorschläge** (z. B. „Saleria erzeugt ein
  Skelett, CI lintet es"). Eigene Sicherheits-Bewertung erforderlich,
  steht aktuell nicht zur Debatte.
- **Auto-PR-Erstellung aus Vorschlägen.** Nicht in dieser Roadmap-Linie.
- **Erweiterung der DB-Schema.** `description_md` reicht. Keine neuen
  Tabellen für „Pseudocode-Sektionen".
- **Saleria emittiert Inline-CSS oder JS in Markdown.** Wird vom
  bestehenden `bleach`-Filter ohnehin gestrippt; nicht versuchen, das
  zu umgehen.

## 6. Folge-Phasen / Querverweise

- **Phase 78** (Plugin Self-Suggestion): Voraussetzung. Phase 79 ist
  eine reine Markdown-Erweiterung, keine Architektur-Änderung.
- **Phase 80** (laut Phase-78-§9): Proaktive Vorschläge ohne konkreten
  Fail-Trigger. **Hinweis:** „Phase 80" in der Phase-78-Datei meint
  diese proaktive-Vorschläge-Idee, nicht den ConversationListStore aus
  `phase-80-conversation-list-store.md`. Die Nummerierung ist im Repo
  doppelt belegt — bei späterer Klärung im Konzept-Bestand mit
  bereinigen.
- **Phase 81** (laut Phase-78-§9): Vorschlags-Statistiken.

## 7. Entscheidungs-Audit

| Datum | Status | Begründung |
|---|---|---|
| 2026-04-29 | offen, unter Vorbehalt R1 | Phase 78 §9-Eintrag |
| 2026-05-10 | **ON HOLD** | Phase 78 erst 2 Tage live, kein einziger Live-Vorschlag in der DB. Trigger-Bedingung §2.2 formalisiert. Ohne empirische Lücke aus dem Realbetrieb wäre Phase 79 Premature Optimization mit echtem Halluzinations-Risiko. |

Folge-Updates dieser Tabelle: bei jeder Status-Änderung Datum +
Begründung eintragen. Wenn sich der Status nicht ändert, kein Eintrag.
