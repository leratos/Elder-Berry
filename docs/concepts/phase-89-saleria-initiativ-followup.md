# Phase 89 – Saleria-Initiativ-Vorschlag-Followup

**Status:** Konzept abgeschaerft am Code-Stand (2026-06-01); Diagnose 89.1
weitgehend statisch geklaert, Fix-Pfad-Entscheidung offen.
**Branch:** `feature/phase-89-saleria-initiativ-followup` (angelegt 2026-06-01)
**Aufwand:** ~1 Konzept-Session + 1-2 Implementierungs-Sessions
**Vorgaenger:** Phase 18+ (Pending-Confirmation-Pipeline), Phase 23 (Rolling-Summary in ChatHistory)

> **WICHTIG (Abschaerfung 2026-06-01):** Die urspruengliche Diagnose von
> 2026-05-13 (Abschnitt "Ausgangslage" + H1/H2/H3) wurde teils gegen einen
> **gedrifteten/falsch angenommenen** Code-Stand geschrieben. Der real
> verifizierte Stand steht im neuen Abschnitt
> [Code-Verifikation (2026-06-01)](#code-verifikation-2026-06-01). Lies diesen
> ZUERST. Kernkorrektur: **H1 (zwei aufeinanderfolgende Assistant-Turns brechen
> die Claude-Rollen-Konvention) ist strukturell unmoeglich** — der Code baut
> nie ein Multi-Turn-Messages-Array. Die Original-Hypothesen bleiben unten als
> Denkweg stehen, jeweils mit Verdikt markiert.

## Trigger

Realwelt-Beobachtung Lera-Smoketest 2026-05-13 (direkt nach Phase 88
+ 88.1-Production-Deploy mit der Fewo-Direkt-Reservierungs-Mail):

```
saleria> Kurz gesagt: Marcus fährt Mitte August 6 Nächte weg.
         Soll ich den Termin gleich in den Kalender eintragen?

lera>    ja bitte

saleria> Hmm, ich bin nicht ganz sicher was du meinst – worauf
         beziehst du dich mit 'ja bitte'? Die Zusammenfassung hast
         du ja schon. Soll ich den Termin eintragen, eine
         Erinnerung setzen oder noch was anderes damit machen?
```

Saleria hat eine **Initiativ-Frage** gestellt ("Soll ich den Termin
gleich eintragen?") und die direkte Bestaetigung ("ja bitte") nicht
mit der eigenen vorherigen Frage verknuepft. Stattdessen behandelt
sie das "ja bitte" als isolierten Input ohne Kontext.

Konsequenz: Saleria's proaktive Vorschlaege koennen vom User nicht
mit minimalem Aufwand bestaetigt werden. Jede Initiativ-Frage
zwingt den User, die Aktion in eigenen Worten neu zu formulieren
("ja, trag den Termin ein"), sonst kommt eine Rueckfrage.

## Abgrenzung zur Pending-Confirmation-Pipeline

Phase 18+ (Pending-Confirmation, ``confirmation_handlers.py``) deckt
destruktive Aktionen ab, die der User explizit bestaetigen MUSS,
bevor sie ausgefuehrt werden: Mail senden, Termin loeschen,
Schreibzugriff auf Files, Restart. Pattern:

* Command-Handler erkennt eine destruktive Aktion.
* Setzt ``PendingAction`` mit Action-Type + Data.
* Sendet Bestaetigungsfrage an User.
* Naechstes "ja"/"ok"/"bestaetigen" wird vom PendingConfirmation-
  Handler **vor** dem normalen Message-Pfad abgefangen und fuehrt
  die Aktion aus.

Phase 89 ist **kein** destruktives-Aktion-Bestaetigungs-Problem.
Es geht um **Initiativ-Vorschlaege** vom LLM, die nicht durch
einen Command-Handler vorab als kritisch markiert wurden. Saleria
hat die Frage im LLM-Output formuliert -- der Code-Pfad hat keine
Information ueber die offene Frage.

Beide Pipelines sollen koexistieren: PendingConfirmation fuer
"Code-erkannte destruktive Aktionen", neu "Initiativ-Followup"
fuer "LLM-erkannte Vorschlaege".

## Ziel

Saleria's eigene Initiativ-Fragen koennen vom User mit minimalen
Folgeantworten ("ja", "ja bitte", "ok", "mach") akzeptiert werden,
ohne dass die Bestaetigung vergessen oder als isolierter Input
behandelt wird.

## Out of Scope

* **Code-getriggerte Pending-Confirmation** (Phase 18+) bleibt
  unveraendert -- destruktive Aktionen werden weiter ueber den
  bestehenden Pfad bestaetigt.
* **Multi-Turn-Followups mit komplexer State-Machine** (z.B. "Welche
  Variante moechtest du?" mit Listen-Auswahl): explizite Auswahl-
  Pipeline ist eigenes Thema, Phase 80 hat das schon teilweise mit
  ConversationListStore.
* **Mehrfache offene Fragen gleichzeitig**: Saleria stellt
  typischerweise eine Frage am Ende ihrer Antwort, nicht mehrere
  Vorschlaege in einer Antwort. Wenn das Problem auftaucht, ist
  das eine Folge-Phase.
* **Echte Initiative von Saleria selbst** (z.B. Mail-kommt-rein-
  Notification mit Bestaetigungsfrage): ist im Briefing-Scheduler
  und Reminder-Scheduler-Bereich, eigene Pipeline.

## Code-Verifikation (2026-06-01)

Statische Verifikation gegen den realen Code-Stand auf `main` (Stand
2026-06-01), bevor irgendein Fix gebaut wird ("nicht kaputt reparieren").

### Verifizierte Architektur (das aendert die ganze Diagnose)

Der LLM-Call ist **single-turn mit History im System-Prompt** — es gibt
**kein rollengetaggtes Multi-Turn-Messages-Array**:

* [chat_history.py:176-209](../../src/elder_berry/comms/chat_history.py)
  `format_for_prompt()` serialisiert die History als **einen Textblock**
  mit "User:"/"Saleria:"-Praefixen unter der Ueberschrift
  "Letzte Nachrichten:" (`"\n".join(parts)`). Jede Einzelnachricht wird
  dabei auf **500 Zeichen** gekuerzt (Z. 205-206).
* [assistant.py:127-134](../../src/elder_berry/core/assistant.py)
  `process()` baut den System-Prompt und ruft
  `self._llm.generate(user_input, system=system_prompt)`. Die `chat_history`
  wird in `_build_system_prompt` **ans Ende des System-Prompts angehaengt**
  ([assistant.py:364-365 / 384-385](../../src/elder_berry/core/assistant.py)).
* Alle LLM-Clients bauen `messages=[{"role": "user", "content": prompt}]` —
  genau **ein** User-Turn, History nur im `system`-Feld:
  [anthropic_client.py](../../src/elder_berry/llm/anthropic_client.py),
  [ollama_client.py](../../src/elder_berry/llm/ollama_client.py),
  [openrouter_client.py](../../src/elder_berry/llm/openrouter_client.py).
* Live-Backend ist [router.py](../../src/elder_berry/llm/router.py):
  **Claude Sonnet 4.6 primaer**, **Ollama phi4:14b Offline-Fallback**, beide
  ueber dasselbe single-turn `generate(prompt, system)`.

### Verdikt zu den Original-Hypothesen

* **H1 — WIDERLEGT (strukturell unmoeglich).** H1 nahm an, dass zwei
  aufeinanderfolgende `assistant`-Eintraege ein Claude-Messages-Array mit
  Rollen-Alternation brechen. Ein solches Array existiert nicht: der API-Call
  sieht immer nur **einen** User-Turn. Die zwei `_chat_history.add(..., "assistant", ...)`
  in [message_handlers.py:489-491+523](../../src/elder_berry/comms/message_handlers.py)
  erzeugen hoechstens **zwei aufeinanderfolgende "Saleria:"-Zeilen im
  Fliesstext-Block** des System-Prompts — eine Text-Serialisierungs-Nuance,
  kein API-Rollen-Verstoss. Restproblem-Anteil von H1: gering und anders
  geartet (siehe Wurzel-Kandidat).
* **H2 — BESTAETIGT und konkretisiert.** Der System-Prompt enthaelt keine
  Followup-Regel. **Schaerfer noch:** [saleria.yaml:95-96](../../src/elder_berry/character/saleria.yaml)
  instruiert aktiv das Gegenteil: *"Fuehre nur dann eine Aktion aus, wenn der
  Nutzer explizit danach fragt. Bei normalen Fragen oder Gespraechen setze
  action auf null."* Ein blankes "ja bitte" liest das LLM nicht als explizite
  Aktionsanfrage → es ist angewiesen, `action=null` zu setzen und nur zu
  antworten. Das ist die **wahrscheinlichste Wurzel** und ein *aktiv
  widersprechendes* Signal, nicht nur eine Luecke.
* **H3 — BESTAETIGT unwahrscheinlich (im Direkt-Flow).** Frage und "ja bitte"
  liegen im selben 10-Slot-Window; die Rolling-Summary greift erst bei
  Eviction. Nebenbefund: die 500-Zeichen-Kuerzung in `format_for_prompt`
  trifft Saleria's kurze Frage nicht, nur lange Mail-Bodies.

### Konkreter Wurzel-Kandidat (statt H1)

Bei "ja bitte" laeuft folgender Pfad:
[bridge.py:380](../../src/elder_berry/comms/bridge.py) PendingConfirmation-
Intercept greift nicht (keine offene `PendingAction`) →
[bridge.py:419](../../src/elder_berry/comms/bridge.py) `parse_command("ja bitte")`
findet keinen Command → Fallback in
[message_handlers.py:1153](../../src/elder_berry/comms/message_handlers.py)
`handle_assistant_message` → LLM mit Fliesstext-History im System-Prompt.

Das LLM sieht seine eigene Frage zwar (im History-Block), bekommt aber per
[saleria.yaml:95-96](../../src/elder_berry/character/saleria.yaml) die Anweisung,
ohne explizite Aktionsanfrage `action=null` zu setzen. Ergebnis: Rueckfrage
statt Aktion. **Fix-Pfad B (System-Prompt) zielt damit direkt auf die Wurzel.**

### Reframing der Fix-Pfade am echten Code

* **Pfad A (Mail-Body-Serialisierung) — umdeuten.** Es gibt kein
  "Tool-Result-Format im Messages-Array", weil es kein Messages-Array gibt.
  Sinnvolle A-Variante: in `format_for_prompt` den externen Mail-Body als
  klar markierten Nicht-Saleria-Block ausweisen (statt als "Saleria:"-Zeile),
  damit das LLM ihn nicht als eigene fruehere Aeusserung verwechselt.
  Niedrige Prioritaet — adressiert nicht die Wurzel.
* **Pfad B (System-Prompt-Followup-Regel) — empfohlener Primaer-Fix.**
  Ergaenzt den bestehenden Block in
  [saleria.yaml:67-71](../../src/elder_berry/character/saleria.yaml) (das ist
  die **Phase-90-B-"ANKUENDIGUNG, kein Vollzugs-Statement"-Regel** — Phase 89
  und 90-B teilen sich dieselbe Prompt-Stelle, Abgleich noetig). Muss die
  Z.95-96-Regel explizit relativieren ("eine kurze Bestaetigung auf deine
  eigene vorherige Rueckfrage IST eine explizite Aktionsanfrage").
* **Pfad C (Pending-Initiative-Pipeline) — Namens- und Einhaengepunkt
  geklaert.** Der im Konzept vorgeschlagene Name "PendingProposalStore"
  **kollidiert** mit dem bereits existierenden
  [proposal_store.py `ProposalStore`](../../src/elder_berry/tools/proposal_store.py)
  (Phase-78 Plugin-Vorschlaege, schon in den Assistant injiziert — `Assistant`-
  Ctor-Param `proposal_store`). Fuer Pfad C anderer Name (z.B.
  `PendingInitiativeStore`). Einhaengepunkt: in
  [bridge.py](../../src/elder_berry/comms/bridge.py) **zwischen** dem
  PendingConfirmation-Intercept (Z. 380) und dem Command-Router (Z. 419).

### Konsequenz fuer Etappe 89.1

Die Diagnostik ist durch diese statische Verifikation **weitgehend erledigt**.
Das urspruenglich geplante "Messages-Array-Role-Sequenz-Logging" ist
gegenstandslos (kein Array). Sinnvoller Rest-Diagnostik-Schritt, falls
ueberhaupt: einmalig den **fertig zusammengebauten System-Prompt** (inkl.
History-Block) plus `user_input` und `router.active_backend` loggen, um den
Wurzel-Kandidaten am Live-Fall zu bestaetigen — dann direkt Pfad B.

## Ausgangslage (Diagnose-Befunde aus dem Code-Stand)

> **Hinweis:** Dieser Abschnitt ist die Original-Diagnose vom 2026-05-13 und
> teils ueberholt — siehe [Code-Verifikation (2026-06-01)](#code-verifikation-2026-06-01).
> `_run_llm_enrichment` heisst heute `_handle_llm_enrichment`
> ([message_handlers.py:476](../../src/elder_berry/comms/message_handlers.py)).

### Aktueller Mail-Zusammenfass-Flow

[message_handlers.py:480-540](src/elder_berry/comms/message_handlers.py)
``_run_llm_enrichment`` (gemeinsame Logik fuer Command + LLM-Anreicherung):

```python
self._chat_history.add(msg.sender, "user", msg.body)               # "fasse die mail zusammen"
history_text = result.history_text or ""
self._chat_history.add(msg.sender, "assistant", history_text)      # Mail-Body sanitized

summary_prompt = (
    f"{prompt_intro}\n\n"
    f"--- BEGINN EXTERNER INHALT (nicht vertrauenswürdig) ---\n"
    f"{history_text}\n"
    f"--- ENDE EXTERNER INHALT ---\n\n"
    f"{prompt_instruction}"
)
chat_context = self._chat_history.format_for_prompt(msg.sender)
llm_result = await ... self._assistant.process(summary_prompt, tmp_wav, chat_context) ...

if llm_result.response:
    response = f"{result.text}\n\n{llm_result.response}"
    self._chat_history.add(msg.sender, "assistant", llm_result.response)   # "Soll ich eintragen?"
    await self._channel.send_text(msg.room_id, response)
```

Die ChatHistory nach diesem Flow:

```
user:      fasse die mail zusammen
assistant: [Mail-Body sanitized – 1746 chars Reservierungstext]
assistant: Kurz gesagt: Marcus fährt 6 Nächte weg.
           Soll ich den Termin gleich in den Kalender eintragen?
user:      ja bitte
```

### Was vermutlich schiefgeht

Drei Hypothesen, in absteigender Wahrscheinlichkeit:

#### H1 – Zwei aufeinanderfolgende Assistant-Turns brechen den LLM-Pattern-Match

> **VERDIKT 2026-06-01: WIDERLEGT (strukturell unmoeglich).** Kein
> Multi-Turn-Messages-Array vorhanden. Details:
> [Code-Verifikation](#code-verifikation-2026-06-01).

Claude-API-Konvention: ``role`` wechselt strikt zwischen ``user``
und ``assistant``. Zwei Assistant-Turns hintereinander sind
ungewoehnlich. Der API-Provider akzeptiert sie oft (mit Warning),
aber das Modell-Verhalten leidet:

* Modell sieht ``assistant: [Mail-Body]`` UND
  ``assistant: [Zusammenfassung mit Frage]`` als zwei verkettete
  Ausgaben.
* Der Mail-Body landet als "assistant geschrieben" im Kontext,
  obwohl er Sanitizer-Output ist (externes Material).
* Der LLM verliert dann die klare Frage-Antwort-Struktur und
  interpretiert das ``user: ja bitte`` als isolierten Turn.

**Indiz fuer H1:** dass Saleria's Rueckfrage konkret nach dem
Bezug fragt ("worauf beziehst du dich mit 'ja bitte'?"), nicht
einfach blind agiert -- der Kontext IST teilweise da, aber die
Zuordnung Frage→Antwort ist gestoert.

#### H2 – System-Prompt unterstuetzt Followup-Pattern nicht

> **VERDIKT 2026-06-01: BESTAETIGT + konkretisiert.** Wahrscheinlichste
> Wurzel; sogar aktiv widersprechende Regel in saleria.yaml:95-96. Details:
> [Code-Verifikation](#code-verifikation-2026-06-01).

Selbst wenn die History sauber waere, koennte der System-Prompt
keine explizite Instruktion enthalten, die Saleria sagt: "Wenn
deine letzte Antwort eine Frage war und der User antwortet mit
einer kurzen Bestaetigung, fuehre die in der Frage angebotene
Aktion aus."

Default-LLM-Verhalten ist dort vorsichtig: lieber nochmal nachfragen
als eine unklare Bestaetigung falsch interpretieren.

**Indiz fuer H2:** Saleria's Rueckfrage ist hoeflich und detailliert,
aber kommt durch -- sie weiss, dass es um die Mail-Zusammenfassung
geht, will nur die konkrete Aktion klargestellt haben.

#### H3 – Rolling-Summary loescht die Frage aus dem Kontext

> **VERDIKT 2026-06-01: BESTAETIGT unwahrscheinlich (im Direkt-Flow).** Frage
> und "ja bitte" liegen im selben Window. Details:
> [Code-Verifikation](#code-verifikation-2026-06-01).

Phase 23: wenn Nachrichten aus dem 10-Slot-Sliding-Window fallen,
werden sie zu einer kompakten Summary komprimiert. Falls Saleria's
Frage und Lera's "ja bitte" durch dazwischenliegende Turns aus dem
Fenster gerutscht sind, koennte die Summary die Frage verloren haben.

**Indiz gegen H3:** Realwelt-Lera-Smoketest war direkt nacheinander
(Saleria-Frage gefolgt von "ja bitte"), kein Sliding-Window-Eviction-
Risiko in dem Flow.

### Welche Hypothese stimmt -- braucht Verifikation

> **UEBERHOLT 2026-06-01.** Die statische Code-Verifikation hat die Frage
> weitgehend beantwortet: H2 (saleria.yaml:95-96) ist die wahrscheinlichste
> Wurzel, H1 ist widerlegt. Ein "Role-Sequenz-Logging" ist gegenstandslos
> (kein Messages-Array). Siehe [Code-Verifikation](#code-verifikation-2026-06-01).
> Der Hinweis auf `claude_agent.py` war zudem falsch: das ist die Stufe-2-
> JSON-Action-Whitelist, **nicht** der Saleria-Konversationspfad
> ([assistant.py](../../src/elder_berry/core/assistant.py)).

Ohne Live-Debug ist Implementation-Pfad nicht eindeutig. Etappe
89.1 ist daher eine **Diagnostik-Phase**: tatsaechliche Request-
Logs an Claude-API einsehen (Logging im claude_agent.py oder im
Assistant-Wrapper), pruefen wie ``format_for_prompt`` die History
serialisiert, sehen welche Role-Sequenz im LLM-Call landet.

## Architektur

Abhaengig von Diagnose-Ergebnis ergibt sich Fix-Strategie. Drei
moegliche Pfade, die parallel oder sequentiell umgesetzt werden
koennen:

### Pfad A – User-Role fuer Mail-Body

Statt den Mail-Body mit ``role="assistant"`` in die History zu
schreiben, mit einem expliziten **Tool-Result-Format** oder als
User-Turn-Anhang serialisieren:

```python
self._chat_history.add(msg.sender, "user", msg.body)
self._chat_history.add(
    msg.sender,
    "assistant",
    f"[Mail-Body geladen]\n\n{summary_response}",
)
```

oder eleganter: Tool-Use-Pattern in Claude-API, das macht den
Mail-Body als "tool result" klar erkennbar. Aufwand mittel, weil
die ChatHistory-DTOs erweitert werden muessen.

### Pfad B – Initiative-Marker im System-Prompt

System-Prompt um eine Instruktion erweitern:

> Wenn deine letzte Antwort eine Frage zur Bestaetigung einer
> Aktion enthielt und der User kurz antwortet ("ja", "ok", "mach",
> "bitte"), interpretier das als Bestaetigung und fuehre die in
> deiner Frage angebotene Aktion aus, ohne nochmal rueckzufragen.

Aufwand klein, aber Wirkung verlaessbar nur mit guten Test-Cases
abzuschaetzen. Risk: LLM ueberinterpretiert kurze Bestaetigungen,
wenn der Kontext nicht klar ist.

### Pfad C – Initiative-Confirmation-Pipeline

Saleria's LLM-Antwort wird durch ein Post-Processing-Filter
geschickt, der **offene Vorschlaege erkennt** und als
``PendingProposal`` registriert. Pattern: erkennt am Antwort-
Ende "Soll ich..."-Phrasen, extrahiert die vorgeschlagene Aktion
("Termin eintragen") und legt ein PendingProposal-Objekt ab.

Naechste User-Antwort wird durch einen PendingProposal-Handler
gefiltert (analog PendingConfirmation), der "ja"/"ok"/"mach" als
Bestaetigung der Aktion erkennt und die Aktion ausfuehrt.

Aufwand hoch -- braucht:

* ``PendingProposalStore`` analog zu ``PendingConfirmationStore``
* LLM-Output-Parser, der Vorschlaege erkennt (NLP-leichter
  Klassifizierer oder Regex-basiert)
* Action-Mapper, der vorgeschlagene Aktionen auf existierende
  Command-Handler zurueckfuehrt

Vorteil: deterministisch und ohne LLM-Interpretation-Risk.

### Empfohlene Kombination

> **PRAEZISIERT 2026-06-01 nach Code-Verifikation:** Empfehlung jetzt
> **Pfad B zuerst (Primaer-Fix, trifft die Wurzel an saleria.yaml:95-96)**,
> Pfad A optional und niedrigpriorisiert (Mail-Body-Markierung in
> `format_for_prompt`, adressiert die Wurzel nicht). Pfad C bleibt Phase 90+
> und nur, falls B nicht reicht — mit anderem Store-Namen wegen Kollision mit
> dem bestehenden `ProposalStore`. Reihenfolge-Begruendung:
> [Code-Verifikation](#code-verifikation-2026-06-01).

Pfad A + Pfad B als Etappe 89.2 (mittelfristig, ~1 Session).
Pfad C als Phase 90+ falls A+B nicht ausreichen oder weitere
Initiativ-Patterns auftauchen.

## Etappenplan

### Etappe 89.1 – Diagnostik

> **STATUS 2026-06-01: weitgehend erledigt durch statische Code-Verifikation.**
> Das geplante "messages-Array-Logging" ist gegenstandslos (kein Array; alles
> single-turn + System-Prompt). Wurzel-Kandidat steht: saleria.yaml:95-96 +
> fehlende Followup-Regel. Optionaler Rest-Schritt zur Live-Bestaetigung
> unten. Details: [Code-Verifikation](#code-verifikation-2026-06-01).

* ~~Logging im claude_agent.py~~ (falscher Pfad) → falls Live-Bestaetigung
  gewuenscht: den fertigen System-Prompt + `user_input` +
  `LLMRouter.active_backend` einmalig in
  [assistant.py:132](../../src/elder_berry/core/assistant.py) (dort wird schon
  die Laenge geloggt) auf DEBUG ausgeben.
* Manueller Smoketest: ``mail suche fewo-direkt`` →
  ``fasse die mail zusammen`` → ``ja bitte``. Logs einsehen.
* ~~Klaeren welche Hypothese zutrifft~~ → erledigt: H2 (konkretisiert), H1
  widerlegt, H3 unwahrscheinlich.
* Acceptance: konkrete Beobachtung dokumentiert, Fix-Pfad gewaehlt.

**Aufwand:** ~halbe Session (jetzt: nur noch optionaler Live-Log + Pfad-B-Fix).

### Etappe 89.2 – Fix-Implementation

> **UMGESETZT 2026-06-01 als Pfad C (Lera-Entscheidung, statt der
> urspruenglich empfohlenen Kombination A+B).** Begruendung der Wahl:
> deterministisch, kein LLM-Interpretations-Risiko. Variante: **strukturierte
> ``propose_action``** (kein Regex auf Freitext). Verhalten bei Nicht-
> Bestaetigung: **Vorschlag verwerfen + normal weiterverarbeiten** (nicht
> blockieren).

Umgesetzte Bausteine:

* **Neu** ``src/elder_berry/comms/pending_initiative.py``:
  ``PendingInitiative``-DTO + ``PendingInitiativeStore`` (Spiegel von
  ``PendingConfirmationStore``; TTL 300s, einer pro User). Eigener,
  bewusst enger Bestaetigungs-Wortschatz inkl. mehrwortigem "ja bitte";
  ``check_response`` liefert ``confirm`` / ``cancel`` / ``other`` / ``none``
  und mutiert nicht (Lifecycle steuert die Bridge).
* ``core/assistant.py``: ``propose_action`` als Pass-through-Action
  (Assistant fuehrt sie nicht lokal aus).
* ``comms/message_handlers.py``: ``_handle_propose_action`` legt den Vorschlag
  ab und sendet die Frage; Branch im Standard-LLM-Pfad
  (``handle_assistant_message``) UND im Enrichment-Pfad
  (``_handle_llm_enrichment`` -- der wertete Aktionen vorher NICHT aus, war
  also die eigentliche Trigger-Luecke). Store via DI.
* ``comms/bridge.py``: Intercept zwischen PendingConfirmation und
  Command-Router. Bei Bestaetigung fuehrt ``_execute_confirmed_initiative``
  den ``proposed_command`` ueber den normalen ``parse_command`` ->
  ``handle_remote_command``-Pfad aus (frozen DTO -> ``dataclasses.replace``).
  Destruktive Commands setzen dort weiterhin ihre eigene PendingConfirmation
  (Doppel-Bestaetigung bleibt erhalten).
* ``character/saleria.yaml``: ``propose_action`` dokumentiert (mit Kalender-
  Beispiel) + Direktive bei der "nur bei expliziter Anfrage"-Regel, dass
  Eigen-Vorschlaege ``propose_action`` statt ``action:null`` nutzen. Die
  Bestaetigung selbst interpretiert das LLM NICHT -- das macht der Intercept.

Tests:

* ``tests/test_pending_initiative.py`` (30): Store, TTL, Wortschatz,
  Normalisierung, Schutz gegen Ueber-Erkennung (nacktes "bitte" ist kein
  Confirm).
* ``tests/test_pending_initiative_flow.py`` (8): Vorschlag ablegen (beide
  Pfade), Bestaetigung -> Command-Ausfuehrung, Absage, Nicht-Match-Verwerfen,
  Round-Trip propose->confirm.

Verifikation: ruff clean, ``mypy src/elder_berry`` clean (178 Dateien),
voller pytest **6415 passed, 3 skipped**.

**Offen:** Realwelt-Smoketest mit Lera (Mail-Zusammenfassung -> "ja bitte")
am Live-System -- nur Lera kann den fahren. Commit steht noch aus (wartet auf
Lera-Freigabe).

**Aufwand (real):** ~1 Session inkl. Code-Verifikation + Tests.

#### PR #276 Review-Hardening (2026-06-01)

Aus dem PR-Review (github-advanced-security CodeQL + chatgpt-codex)
nachgezogen:

* **Sicherheits-Gate (Codex P1, kritisch):** ``_execute_confirmed_initiative``
  fuehrt einen bestaetigten Vorschlag nur aus, wenn der geparste Command in
  ``SAFE_PROPOSABLE_COMMANDS`` (``pending_initiative.py``, default-deny) liegt.
  Grund: (1) ``propose_action`` kann aus untrusted Mail-/Web-/Doku-Enrichment
  stammen (Injection-Vektor); (2) verifiziert, dass einige destruktive
  Commands (``contact_delete``, einzelne ``termin_delete``) SOFORT ohne eigene
  PendingConfirmation loeschen -- die zuvor dokumentierte "Doppel-Bestaetigung
  fuer destruktive Commands" galt also NICHT durchgaengig. Allowlist enthaelt
  nur reversible Creates (termin/notiz/reminder/todo/contact_add). Kein
  LLM-Fallback fuer abgelehnte Vorschlaege (kein attacker-Text ans LLM).
* **Param-Typ-Guard (Codex P2):** ``_handle_propose_action`` behandelt
  ``action_params`` nur als dict (isinstance), sonst ungueltiger Vorschlag --
  kein Crash bei LLM-Drift.
* **Parsebares Prompt-Beispiel (Codex P2):** ``proposed_command``-Beispiel in
  ``saleria.yaml`` von ``kalender erstelle ...`` (matcht ``parse_command``
  NICHT) auf ``termin: Urlaub 15.08`` (matcht ``TERMIN_CREATE_PATTERN``)
  geaendert -- sonst waere das Headline-Szenario nach "ja" still im
  LLM-Fallback gelandet.
* **Rekursions-Guard (Codex P2):** Ausfuehrung wird mit ``_in_llm_command``
  geklammert (try/finally), analog ``_handle_llm_remote_command`` -- ein
  fallthrough-Command laeuft nicht erneut ins LLM.
* **CodeQL (7x "Statement has no effect"):** ``...``-Stubs im Test-MockChannel
  durch echte No-op-Bodies ersetzt.

Tests ergaenzt: Allowlist-Inhalt (Creates erlaubt, Deletes/Send/Write
abgelehnt), destruktiver Vorschlag wird abgewiesen, unparsebarer Vorschlag
wird abgewiesen (kein LLM-Fallback). Store+Flow jetzt 53 Tests.

### Etappe 89.3 – Doku

* CLAUDE.md-Abschnitt "SALERIA-INTERAKTION" mit Hinweis auf
  Followup-Pattern.
* Journal: "Abgeschlossen Phase 89" mit Diagnose-Befunden und
  finalem Fix-Pfad.

**Aufwand:** ~Viertel-Session.

## Test-Strategie

Drei Test-Klassen:

### TestChatHistorySerialisation

Sicherstellen, dass die ChatHistory keine zwei aufeinanderfolgenden
Assistant-Turns produziert. Nach jedem ``add`` mit ``role=assistant``,
der einem vorigen ``assistant``-Turn folgt: Merge oder Marker-Insert.

### TestInitiativeFollowupDetection

LLM-Output-Pattern-Match testen. Beispiel-Antworten mit "Soll ich...
einrichten?", "Möchtest du, dass ich...?", "Trage ich es ein?" am
Ende. User-Folge-Antwort: "ja"/"ok"/"klar"/"mach"/"bitte". Pruefen:
LLM (oder Pre-Filter) erkennt den Followup-Kontext.

### TestRealwelt

Synthetischer Test des kompletten Flows: Mail-Body → LLM-Summary mit
Initiativ-Frage → User-Bestaetigung → Aktion ausgefuehrt. Mit
gemockter Claude-API + assertbarer Action-Aufruf.

## Definition of Done

> **Status 2026-06-01: ABGESCHLOSSEN (Lera-Entscheidung).** (1) erledigt --
> Diagnose statisch geklaert (H1 widerlegt, Wurzel H2). (2) erledigt -- Pfad C
> implementiert + PR-Review-Hardening, ruff/mypy/pytest clean (6430 passed),
> committed (fa0483b + f1b9bea), PR #276. (3) pragmatisch geschlossen --
> Live-Smoketest: Mail-Zusammenfassung + expliziter Termin-Befehl laufen sauber
> (Saleria rechnete 17.08.-7=10.08., direkte Ausfuehrung -- korrekt, KEIN
> propose_action-Over-Trigger). Der **proaktive** Vorschlag-Fall
> (Saleria fragt von sich aus -> "ja bitte" -> Ausfuehrung) wurde nicht
> erzwungen; durch 54 Unit-/Integrationstests abgedeckt und im Alltag zu
> beobachten. (4) Konzept + Journal aktuell; CLAUDE.md-Abschnitt (89.3)
> bleibt optional. (5) entfaellt -- Pfad C umgesetzt. Journal-Abschluss:
> elder-berry#676 (resolves #669, #672).
>
> **Backlog (niedrig):** proaktiven Vorschlag im Betrieb bestaetigen; falls
> Saleria ``propose_action`` nicht zuverlaessig emittiert, ``saleria.yaml``-
> Direktive nachschaerfen.

Phase 89 gilt als abgeschlossen, wenn:

1. Diagnose-Etappe 89.1 hat eindeutig identifiziert, welche
   Hypothese (H1/H2/H3) oder Kombination zutrifft -- mit
   Request-Log-Auszug im Journal.
2. Fix-Implementation (89.2) ist mergebereit, mypy/ruff/pytest
   clean.
3. Realwelt-Smoketest mit Lera-Mail-Zusammenfassung-+-"ja bitte"
   liefert direkt die folgende Aktion (Termin eintragen), ohne
   Rueckfrage.
4. CLAUDE.md + Journal sind aktualisiert.
5. Optional: PendingProposalStore-Design fuer Phase 90+ in
   docs/concepts skizziert, falls Etappe 89.2 das Problem nicht
   vollstaendig loest.

## Restrisiken

* **LLM-Verhaltens-Aenderungen ueber Modell-Versionen:** Fix-Pfad B
  (System-Prompt-Erweiterung) ist anfaellig fuer Aenderungen, wenn
  Claude-Modell-Versionen wechseln. Test-Suite muss bei Modell-
  Upgrade gegen reale Realwelt-Patterns rebroadgepruefft werden.
* **Over-Confirmation-Risiko:** wenn der LLM "ja" zu schnell als
  Bestaetigung interpretiert, koennten unbeabsichtigte Aktionen
  ausgeloest werden. Defense: Initiativ-Aktionen, die destruktiv
  sind, sollten weiterhin durch die Phase-18-PendingConfirmation
  laufen -- also doppelt bestaetigt werden. Mit
  ``calendar create``-Beispiel ist das praktisch unkritisch
  (Termine sind reversibel), aber die Pipeline soll konsistent
  bleiben.
* **Stille Erweiterung des LLM-Action-Surface:** wenn Saleria im
  Output beliebige Aktionen vorschlaegt, koennte das ueber den
  Followup-Mechanismus zu Aktionen fuehren, die der User nicht
  bewusst angefragt hat. Mitigation: Action-Mapper sollte nur die
  in der vorletzten Saleria-Antwort genannten Aktionen
  akzeptieren, nicht beliebige Folge-Aktionen.
* **Interaktion mit dem Briefing-Scheduler:** wenn Saleria proaktiv
  einen Briefing-Vorschlag macht ("um 9 Uhr morgens lese ich dir
  die Nachrichten vor, ok?"), greift derselbe Mechanismus. Tests
  muessen dafuer Eintraege haben.
