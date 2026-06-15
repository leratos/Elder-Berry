# Phase 100 – Mail 2.0 (Konzept)

> Reifegrad-Sprung der Mail-Funktion: erst die Korrektheits-/Sicherheits-
> Schulden des heutigen Lese-/Antwort-Bots schließen (Tier 0, **Phase 100**),
> dann den Posteingang aktiv machen (Tier 1: Triage + proaktive
> Benachrichtigung, **Phase 101**). Lera-Scope-Entscheid 2026-06-14:
> **Tier 0 + Tier 1 (Triage + Notification)**; Tier 2/3 bewusst zurückgestellt.
>
> Grundlage: Multi-Agent-Validierung (26 Agenten, jede Lücke mit `file:line`
> adversarial am echten Code geprüft). Journal: #771 (Bezug #758).

## Ziel

Heute ist Mail ein **Lese-/Antwort-Bot** (anzeigen, suchen, Einzelmail,
Anhänge empfangen, LLM-Zusammenfassung, Reply mit Draft→`ja`/`ändern`/senden,
löschen). Solide, aber mit drei **echten, live Defekten** und mehreren
Korrektheits-„Lügen", die in jeder „2.0"-Diskussion zuerst gehören. „Mail 2.0"
ist deshalb primär ein Reifegrad-Sprung, kein Feature-Feuerwerk:

1. **Tier 0 (Phase 100) – Härtung:** drei Defekte + Signatur + ehrlicher
   `\Seen`-Status + Silent-Swallows + Testlücken. Reiner Korrektheits-/
   Sicherheits-Schnitt, kein Architektur-Risiko.
2. **Tier 1 (Phase 101) – Posteingang aktiv:** LLM-**Triage/Priorisierung**
   und **proaktive Neue-Mail-Benachrichtigung**. Die eigentlichen
   „Assistentin"-Features.

Explizit **nicht** in diesem Konzept (YAGNI bzw. später, s. u.): compose-new,
forward, reply-all, CC-aus-Original, Anhänge senden, Multi-Account,
persistentes IMAP-IDLE/Pool, HTML-Send, semantische/Vektor-Mailsuche,
Draft-Persistenz, mark-read-Write, Archiv/Move.

## Leitprinzipien

- **Erst Korrektheit, dann Features.** Ein stiller Datenpfad-Bug (SMTP-Host
  wird ignoriert) wiegt schwerer als jedes neue Kommando. Tier 0 zuerst.
- **Empfänger-Invariante (nicht verhandelbar).** Outbound-Empfänger/CC/BCC
  kommen **nur** aus explizitem User-Input oder einem geparsten Header –
  **nie** aus LLM-Output oder Mail-Body. Das `ja`-Gate bleibt; die volle
  finale Empfängerliste wird im Confirm angezeigt. Heute strukturell erfüllt
  (Reply-To = `From`-Header); jedes künftige Sende-Feature muss sie halten.
- **Untrusted by default.** Betreff/Absender/Body eingehender Mails sind
  angreiferkontrolliert. Sie laufen ungescrubbt weder in Protokoll-Header
  (SMTP/IMAP) noch ungelabelt in den LLM-Hauptkontext.
- **Privacy = lokal, nicht Cloud.** Jeder neue LLM-Pfad (Triage) läuft über
  den `LLMRouter` (im Privacy-Modus hart Ollama), **nicht** über den
  Anthropic-Direktpfad. Den Direktpfad-Fehler des Reply-Drafts nicht
  wiederholen.
- **Composition/DI bleibt.** Eine Klasse pro Datei (`snake_case`),
  Abhängigkeiten explizit per Konstruktor, kein neuer globaler Singleton.
- **Klein & testbar.** Jede Etappe ist für sich committbar und getestet.

## Problemanalyse (am echten Code verifiziert, 2026-06-14)

### D1 – SMTP-Key-Mismatch (Schwere: hoch, live Bug)

- UI/Wizard/Setup/Registry speichern **`smtp_host` / `smtp_port`**:
  `web/secrets_registry.py:204-219`, `scripts/setup_email.py:182-183`,
  `web/setup_wizard.py:458-459`.
- `EmailSender.from_secret_store` liest aber **`email_smtp_host` /
  `email_smtp_port`** (`tools/email_sender.py:63,66`) – Keys, die **nirgends**
  geschrieben werden.
- Folge: Jeder **Nicht-Strato-Nutzer**, der per Oberfläche konfiguriert, wird
  still ignoriert und landet im hartcodierten Fallback `smtp.strato.de:465`.
- Maskiert durch falsche Tests (`tests/test_email_sender.py:37-38,62-63`
  setzen die Phantom-Keys). IMAP-Keys (`email_imap_host/_port`) sind dagegen
  konsistent.

### D2 – IMAP ohne Socket-Timeout (Schwere: mittel)

- `tools/email_client.py:516-519`: `IMAP4_SSL(host, port)` ohne `timeout`.
- SMTP setzt `timeout=30` (`tools/email_sender.py:149,151`); IMAP gar keins →
  ein hängender/halb-toter IMAP-Server blockiert den Aufruf unbegrenzt
  (jede Mail-Abfrage, auch der spätere Notification-Poller).

### D3 – Keine Empfänger-/Betreff-/Suche-Validierung (Schwere: mittel)

- **Empfänger:** `_extract_email_address` (`comms/commands/mail_commands.py:766-776`)
  macht nur `re.search(r"<([^>]+)>", …)` bzw. gibt den Rohstring zurück –
  **kein `parseaddr`, kein `@`-Check**. Kaputtes `From` → Rohstring geht an
  SMTP; ein `a@x, b@y`-`From` fächert ungewollt auf.
- **Betreff:** `subject = "Re: " + original.subject` (angreiferkontrolliert)
  geht ungescrubbt in `msg["Subject"]` (`tools/email_sender.py:175`). Stdlib
  foldet zwar, aber CR/LF-Scrub als Belt-and-Suspenders fehlt + kein Test.
- **IMAP-Suche:** Query wird per f-String in das Kriterium interpoliert
  **ohne Quote-Escape** (`tools/email_client.py:215,222`) → ein `"` in der
  Suche bricht den IMAP-Befehl (Breakage/Injection).

### Korrektheits-„Lügen" (Schwere: niedrig, aber billig zu fixen)

- **Signatur-Lüge:** `EMAIL_SYSTEM_PROMPT` (`mail_commands.py:90`) sagt
  „Keine Signatur einfügen (wird vom Mail-Client ergänzt)" – aber **Saleria
  ist der versendende Client.** Kein nachgelagerter Client, kein
  Signatur-Key → jede Antwort geht **ohne** Signatur raus. Auch der
  Anzeigename ist hart `"Saleria"` (`email_sender.py:45,173`), kein Key.
- **`is_unread` ist eine Anzeige-Lüge:** der `●/○`-Status ist ein
  Caller-Literal (`email_client.py:165` True, sonst False), **nie** vom echten
  `\Seen`-Flag gelesen. Alle Fetches sind `readonly=True`, mutieren also nicht.
- **Zwei echte Silent-Swallows** (`except: pass`/`continue`, kein Log):
  Datum-Parse `email_client.py:617-618`, Sent-Ordner-Loop
  `email_client.py:504-505`. (Validiert S3 der Sicherheitsanalyse vom 09.06.)
- **Reply nutzt `body_preview` (≤ 8020 Zeichen):** bei sehr langen Mails wird
  aus einem gekürzten Original geantwortet (`mail_commands.py:727`). Für den
  Normalfall unkritisch; nur dokumentiert.

### Befunde, die Tier 1 prägen

- **Kein proaktiver Pfad:** kein IMAP-IDLE/Watcher; neue Mail erscheint nur
  on-demand oder als **Zähler** im Morgenbriefing
  (`comms/briefing_scheduler.py:422-432`). Es existiert ein bewährtes
  Daemon-Thread-Pattern (`briefing_scheduler.py:446-483`), das ein
  Mail-Poller wiederverwenden kann.
- **Keine Triage:** Listing ist rein chronologisch
  (`email_client.py:560-562`); kein Importance-/Kategorie-Scoring. Der einzige
  LLM-Klassifikator im Mail-Umfeld klassifiziert PDF-**Anhänge** fürs Ablegen
  (`confirmation_handlers.py:944-975`), nicht den Posteingang.
- **Privacy heute gespalten:** Reply-Draft ist **hart geblockt**
  (`mail_commands.py:549-550`, Anthropic-Direktpfad), per-Mail-Summary läuft
  dagegen über den `LLMRouter` → lokal (`llm/router.py:132-133`). Neue
  LLM-Pfade müssen den Router-Weg nehmen.
- **Second-Order-Injection:** Mail-Body fließt via `history_text` in den
  LLM-Hauptkontext (`mail_commands.py:452-458`). Sobald Triage/Notification
  mehr Inhalt einspeisen, ist die Untrusted-Markierung Pflicht (s. Risiken).

---

## Lösung / Architektur

### Phase 100 – Tier 0: Härtung

#### 100-A · D1 SMTP-Key-Mismatch + D2 IMAP-Timeout

- `EmailSender.from_secret_store` liest **`smtp_host` / `smtp_port`** (die
  tatsächlich geschriebenen, in der UI sichtbaren Keys); Fallback
  `smtp.strato.de` / `465` bleibt. Kein Migrationsschritt nötig (die alten
  `email_smtp_*` wurden nie geschrieben). Für Leras Strato-Setup bleibt das
  Verhalten unverändert.
- `IMAP4_SSL(host, port, timeout=30)` bzw. `IMAP4(..., timeout=30)` in
  `email_client._connect` (Param ab Python 3.9, auf Tower/Laptop 3.12 + RPi
  3.13 vorhanden).
- Tests: `test_email_sender.py` auf `smtp_host/_port` korrigieren (deckt D1
  ehrlich ab); IMAP-Timeout im `_connect`-Konstruktoraufruf asserten.

#### 100-B · D3 Eingabe-/Header-Härtung

- Neuer reiner Helfer (Funktion, kein Sanitizer-State) zur Empfänger-Prüfung:
  `email.utils.parseaddr` + Pflicht-`@`; leere/ungültige Adresse → klare
  Ablehnung **bevor** ein `PendingAction`/Draft entsteht.
- Betreff-Scrub: `.replace("\r"," ").replace("\n"," ")` + `Re:`-Doppelung
  vermeiden, im `_build_reply_message` bzw. beim Subject-Bau.
- IMAP-Suche: Quote-/Backslash-Escape (oder Quote-Strip) in
  `email_client.search`, damit ein `"` das Kriterium nicht bricht.
- Tests: ungültiges/leeres `From` → Ablehnung; `From` mit CR/LF im
  Betreff → gescrubbt; Suchquery mit `"` → kein Breakage.

#### 100-C · Signatur + Anzeigename (konfigurierbar)

- Neue Secret-Keys `email_signature` (mehrzeilig, optional) und optional
  `email_sender_name` (Default `"Saleria"`) in `secrets_registry.py` (+ Wizard
  optional). Beide **nicht** `requires_restart`-kritisch über das, was die
  übrigen Mail-Keys schon sind.
- `EmailSender.from_secret_store` reicht `sender_name` durch; Anzeigename wird
  **CR/LF-gescrubbt** in den `From`-Header gesetzt (A1-Härtung: konfigurierbarer
  Name = neue Header-Interpolation).
- Signatur wird nach der LLM-Generierung an den Body angehängt (statischer
  Config-Text, **nicht** vom LLM erzeugt → keine neue Injection-Fläche).
- `EMAIL_SYSTEM_PROMPT`-Zeile 90 korrigieren („wird vom Mail-Client ergänzt"
  ist faktisch falsch).
- Tests: Signatur angehängt / leer = unverändert; Anzeigename gescrubbt.

#### 100-D · Ehrlicher `\Seen`-Status (read-only)

- Fetch von `(RFC822)` auf **`(FLAGS RFC822)`** umstellen, `\Seen` aus den
  FLAGS parsen und `EmailMessage.is_unread` daraus setzen (statt Literal).
  Bleibt `readonly=True` – **keine** Flag-Mutation, kein mark-read-Write
  (das ist Tier 2, hier bewusst nicht).
- Macht den `●/○`-Indikator in Liste/Suche/Detail ehrlich.
- Tests: gemischte FLAGS (gelesen/ungelesen) → korrekter `is_unread`.

#### 100-E · Silent-Swallows + Testlücken

- `logger.debug(...)` an `email_client.py:617-618` (Datum) und `:504-505`
  (Sent-Ordner) ergänzen; weiter degradieren wie bisher.
- Testlücken schließen: `EmailSender` `SMTPException`-Zweig;
  `_fetch_mails` `except → []`-Pfad; `get_unread_count` Fehler-Sentinel `-1`;
  Datum-Parse → `None`.

### Phase 101 – Tier 1: Posteingang aktiv

#### 101-T · LLM-Triage / Priorisierung

- Neue Klasse `tools/mail_triage.py` → `MailTriageClassifier`, DI mit dem
  **`LLMRouter`** (nicht `AnthropicClient`!), damit Privacy hart lokal greift.
- Eingabe: Liste der ungelesenen `EmailMessage`. **Ein** gebündelter
  LLM-Call (kostengünstiger als N Calls) liefert pro Mail
  `{prioritaet: hoch|mittel|niedrig, kategorie, grund}`.
- Prompt mit **Anti-Injection-Guard** (analog `_handle_mail_summary`,
  `message_handlers.py:752-754`): Mail-Inhalt explizit als untrusted Daten
  einrahmen, eingebettete Anweisungen ignorieren.
- Integration: `mails`/`mail zusammenfassung` sortiert nach Priorität bzw.
  neues Kommando „mails priorität". Listen-Ausgabe markiert Priorität.
- Privacy: läuft über Router → im Privacy-Modus Ollama, **kein** Hard-Block.
- Tests (`tests/test_mail_triage.py`): Parsing/Schema, Sortierung,
  Router-Pfad (Privacy → Fallback), Injection-Guard (Mail mit „ignoriere
  Anweisungen" ändert die Klassifikation nicht).

#### 101-N · Proaktive Neue-Mail-Benachrichtigung

- Neue Klasse `comms/mail_watcher.py` → `MailWatcher` (Daemon-Thread,
  Vorbild `BriefingScheduler`). Pollt `get_unread` alle `N` Minuten
  (Default konservativ, z. B. 5 min; Key `mail_poll_interval_min`),
  Dedup per **UID-Set** (nur neue UIDs melden).
- Meldung über den Matrix-Channel: „📧 Neue Mail von {Absender}: {Betreff}".
  Betreff/Absender werden **gescrubbt** (untrusted Header), kein Roh-HTML.
- Optionale Kopplung mit 101-T: ist Triage aktiv, lautet die Meldung
  „📧 **Wichtige** neue Mail von …" nur bei Priorität hoch (reduziert Lärm).
  Diese LLM-Stufe läuft ebenfalls über den Router.
- Profitiert direkt von 100-D (ehrlicher Unread) und 100-A (IMAP-Timeout im
  Dauerbetrieb).
- An/Aus per Key `mail_notify_enabled` (Default aus – „opt-in", wie Privacy).
- Tests (`tests/test_mail_watcher.py`): neue UID → genau eine Meldung;
  bekannte UID → keine; Poll-Fehler → geloggt, kein Crash; Dedup über Ticks.

## Empfänger-Invariante (geteilter Test, Pflicht für künftige Sende-Features)

Auch wenn Tier 2 hier nicht gebaut wird: die Invariante wird als ausführbarer
Vertrag verankert (ein Test, der bei jedem Sende-Pfad mitläuft), damit ein
späteres compose/forward/reply-all sie nicht still bricht:

> **Outbound `To`/`Cc`/`Bcc` stammen ausschließlich aus explizitem
> User-Input oder einem geparsten Mail-Header – niemals aus LLM-Ausgabe oder
> Mail-Body.** Der LLM-Draft fließt nur in den Body. Vor SMTP-Send steht
> immer das `ja`-Gate mit sichtbarer, vollständiger Empfängerliste.

## Betroffene Dateien / Klassen

| Datei | Etappe | Änderung |
|-------|--------|----------|
| `src/elder_berry/tools/email_sender.py` | 100-A,B,C | `smtp_host/_port` lesen; Betreff-Scrub; `sender_name` + Signatur (gescrubbt) |
| `src/elder_berry/tools/email_client.py` | 100-A,B,D,E | IMAP-`timeout=30`; Suche Quote-Escape; `(FLAGS RFC822)` + `\Seen`-Parse; Swallows loggen |
| `src/elder_berry/comms/commands/mail_commands.py` | 100-B,C | `parseaddr`-Empfängervalidierung; Prompt-Zeile 90 korrigieren |
| `src/elder_berry/web/secrets_registry.py` | 100-C, 101 | `email_signature`, `email_sender_name`, `mail_poll_interval_min`, `mail_notify_enabled` |
| `scripts/start_saleria.py` | 100-C, 101 | Signatur/Name verdrahten; `MailWatcher` + Triage-Router erzeugen/starten |
| `src/elder_berry/tools/mail_triage.py` *(neu)* | 101-T | `MailTriageClassifier` (DI: `LLMRouter`) |
| `src/elder_berry/comms/mail_watcher.py` *(neu)* | 101-N | `MailWatcher` (Daemon-Thread, Dedup) |

## Tests

- `tests/test_email_sender.py` (korrigieren+erweitern): D1-Keys, Betreff-Scrub,
  Signatur, Anzeigename, `SMTPException`-Zweig.
- `tests/test_email_client.py` (erweitern): IMAP-Timeout, Suche-Quote,
  `\Seen`-Parsing, Swallows-Logging, `_fetch_mails`-[]-Pfad,
  `get_unread_count`-Sentinel, Datum→`None`.
- `tests/test_mail_reply_commands.py` (erweitern): ungültiger/leerer Empfänger
  → Ablehnung; Empfänger-Invariante (Body-Inhalt ändert `to` nicht).
- `tests/test_mail_triage.py` *(neu)*, `tests/test_mail_watcher.py` *(neu)*.
- Runner Windows: `.\.venv\Scripts\python.exe -m pytest`; `asyncio_mode=auto`;
  eine Testklasse pro Datei.

## Offene Entscheidungen (durch Lera entschieden)

- **Scope:** Tier 0 + Tier 1 (Triage + Notification). ✅
- **Konzept-Doc vor Code:** ja (dieses Dokument), dann OK abwarten. ✅
- **Phasen:** Tier 0 = **Phase 100**, Tier 1 = **Phase 101** (Roadmap endet
  bei 99). Branches `feature/phase-100-mail-haertung` bzw.
  `feature/phase-101-mail-triage-notify`. *(Vorschlag, bei OK so umgesetzt.)*

## YAGNI-Grenzen (bewusst nicht gebaut)

- **Multi-Account** (XL, ein Nutzer/eine Persona).
- **Persistentes IMAP-IDLE / Connection-Pool** (XL; Poll-Modell genügt bei
  diesem Volumen; nur der billige Timeout-Fix wird gemacht).
- **HTML-Send** (Plain-Text ist hier ein Feature: keine Tracking-Pixel, keine
  reflektierte Angreifer-HTML).
- **Semantische/Vektor-Mailsuche** (L-Daten-Pipeline; IMAP-Suche genügt;
  vergrößert die Injection-Fläche).
- **Draft-Persistenz** (verlorener 5-Min-Draft trivial neu erzeugbar).
- **mark-read-Write / Archiv / Move / compose / forward / reply-all / CC /
  Anhänge-senden** – Tier 2, nur auf konkreten Bedarf und dann unter der
  Empfänger-Invariante.

## Bekannte Risiken

- **Triage-Kosten/Latenz:** N ungelesene Mails = ein gebündelter LLM-Call;
  bei großen Posteingängen Batch-Größe begrenzen. Im Privacy-Modus läuft das
  auf dem langsameren Ollama – akzeptiert, weil opt-in/seltener.
- **Second-Order-Injection wächst:** Triage + Notification ziehen mehr
  angreiferkontrollierten Mail-Inhalt ins LLM/in den Chat. → Anti-Injection-
  Guard im Triage-Prompt **und** untrusted-Einrahmung beim Einspeisen in
  History; Betreff/Absender der Notification gescrubbt.
- **Notification-Lärm:** zu kurzes Poll-Intervall / jede Mail melden nervt. →
  Default aus (opt-in), konservatives Intervall, optional nur Priorität „hoch".
- **`MailWatcher`-Dauerverbindung:** ohne D2-Timeout würde ein hängender
  IMAP-Server den Thread blockieren → D2 ist Voraussetzung für 101-N.

## Definition of Done

1. Code committed (Branch je Phase), **kein PR** (macht Lera).
2. Voller `pytest` grün; `ruff` + (für getouchte strict-Tiers) `mypy` sauber.
3. **D1-Akzeptanz:** `smtp_host` = Nicht-Strato-Host gesetzt → `EmailSender`
   verbindet zu diesem Host (nicht zum Strato-Fallback).
4. **D2/D3-Akzeptanz:** IMAP-Connect mit Timeout; ungültiger Empfänger wird
   vor jedem Send abgelehnt; Suchquery mit `"` bricht nicht.
5. **Tier-1-Akzeptanz:** Triage sortiert ungelesene Mails nach Priorität und
   läuft im Privacy-Modus lokal; neue Mail erzeugt genau eine
   Benachrichtigung (Dedup), Betreff gescrubbt.
6. Append-only Journal-Eintrag je Phase mit ausgeführten Tests + nächstem
   Schritt; `resolves`-Link auf das jeweilige `in_arbeit`.
