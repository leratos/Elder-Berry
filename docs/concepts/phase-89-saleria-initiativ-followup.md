# Phase 89 – Saleria-Initiativ-Vorschlag-Followup

**Status:** Konzept (2026-05-13)
**Branch:** `feature/phase-89-saleria-initiativ-followup` (geplant)
**Aufwand:** ~1 Konzept-Session + 1-2 Implementierungs-Sessions
**Vorgaenger:** Phase 18+ (Pending-Confirmation-Pipeline), Phase 23 (Rolling-Summary in ChatHistory)

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

## Ausgangslage (Diagnose-Befunde aus dem Code-Stand)

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

Phase 23: wenn Nachrichten aus dem 10-Slot-Sliding-Window fallen,
werden sie zu einer kompakten Summary komprimiert. Falls Saleria's
Frage und Lera's "ja bitte" durch dazwischenliegende Turns aus dem
Fenster gerutscht sind, koennte die Summary die Frage verloren haben.

**Indiz gegen H3:** Realwelt-Lera-Smoketest war direkt nacheinander
(Saleria-Frage gefolgt von "ja bitte"), kein Sliding-Window-Eviction-
Risiko in dem Flow.

### Welche Hypothese stimmt -- braucht Verifikation

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

Pfad A + Pfad B als Etappe 89.2 (mittelfristig, ~1 Session).
Pfad C als Phase 90+ falls A+B nicht ausreichen oder weitere
Initiativ-Patterns auftauchen.

## Etappenplan

### Etappe 89.1 – Diagnostik

* Logging im claude_agent.py oder im Assistant-Wrapper erweitern:
  Request-Payload (messages-Array) wird strukturell geloggt
  (Role + Content-Preview), bevor an Claude-API.
* Manueller Smoketest: ``mail suche fewo-direkt`` →
  ``fasse die mail zusammen`` → ``ja bitte``. Logs einsehen.
* Klaeren welche Hypothese (H1/H2/H3) zutrifft -- oder ob
  Kombination.
* Acceptance: konkrete Beobachtung dokumentiert, Fix-Pfad gewaehlt.

**Aufwand:** ~halbe Session.

### Etappe 89.2 – Fix-Implementation

* Je nach Diagnose-Ergebnis: Pfad A, B oder beide.
* Tests fuer den Followup-Flow: synthetische ChatHistory mit
  Frage-am-Ende → "ja"-Antwort → erwartete Aktion oder Folge-LLM-
  Response.
* Realwelt-Smoketest erneut.

**Aufwand:** ~1 Session (Pfad B allein) bis ~2 Sessions (A + B).

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
