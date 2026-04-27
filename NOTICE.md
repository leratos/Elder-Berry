# NOTICE

Elder-Berry steht unter der **MIT-Lizenz** (siehe [`LICENSE`](LICENSE)).
Diese Datei dokumentiert ergaenzend, welche Komponenten welcher Herkunft
sind -- eigene Assets, eingebundene Drittanbieter-Modelle und genutzte
Cloud-APIs. Sie ersetzt keine vollstaendige juristische Pruefung, ist aber
der Stand des Maintainers zum Veroeffentlichungszeitpunkt.

Stand: April 2026.

---

## 1. Eigene Assets

Folgende Inhalte sind vom Maintainer selbst erstellt bzw. abgeleitete
Werke, stehen unter MIT (wie das uebrige Repo) und haben jeweils eine
eigene README mit Detail-Begruendung:

### Voice-Samples (Saleria)
- Pfad: [`src/elder_berry/tts/voices/`](src/elder_berry/tts/voices/README.md)
- 10 WAVs, eine pro Emotion (`saleria-<emotion>.wav`).
- **Synthetisch** ueber TTS-Tools erzeugt; **keine reale Person**, kein
  Voice-Cloning eines existierenden Menschen.
- Lizenz: MIT.

### Avatar-Sprites (Saleria)
- Pfad: [`src/elder_berry/avatar/assets/`](src/elder_berry/avatar/assets/README.md)
- 30+ PNGs in `body/`, `eye/`, `mouth/`.
- Vorlagen mit Google Gemini generiert, anschliessend vom Maintainer
  nachbearbeitet, korrigiert und erweitert. Die finalen Sprites gelten
  als eigenstaendiges, abgeleitetes Werk.
- Lizenz: MIT. Keine Gemini-spezifischen Einschraenkungen werden auf
  Forks weitergegeben.

### Charakter "Saleria Berry"
- Name, Persoenlichkeitsbeschreibung und Gesamtdesign sind Teil des
  [Last-Strawberry](https://last-strawberry.com) Universums.
- Code, Voice-Samples und Avatar-Sprites stehen unter MIT.
- Bei Wiederverwendung des Charakters bitte transparent kenntlich
  machen, dass es sich um einen Fork bzw. eine Adaption handelt --
  reine Hoeflichkeit, keine Lizenzauflage.

---

## 2. Eingebundene Drittanbieter-Modelle

Modelle, die auf der eigenen Hardware laufen. Lizenzen gelten fuer den
Modell-Output und beeinflussen ggf. die Nutzbarkeit (kommerziell ja/nein).

### XTTS v2 (Coqui TTS)
- Zweck: Voice-Cloning-TTS als Fallback, wenn ElevenLabs nicht verfuegbar.
- Verwendet ueber das Python-Paket `coqui-tts`.
- **Lizenz: Coqui Public Model License (CPML) -- non-commercial**.
- Konsequenz: Kommerzieller Einsatz von Saleria's XTTS-Stimme ist
  **nicht** durch diese Lizenz gedeckt. Wer Elder-Berry kommerziell
  einsetzen will, muss XTTS v2 ersetzen (z.B. nur ElevenLabs nutzen)
  oder eine separate Vereinbarung mit Coqui treffen.
- CPML-Volltext: <https://coqui.ai/cpml>

### Faster-Whisper
- Zweck: Lokale STT als Fallback.
- Lizenz: MIT.

### ChromaDB
- Zweck: Vektor-Datenbank fuer das RAG-Gedaechtnis.
- Lizenz: Apache 2.0.

### Ollama
- Zweck: Lokaler LLM-/Embedding-Runner (Modelle wie `nomic-embed-text`).
- Ollama selbst: MIT. Die einzelnen Modelle, die per `ollama pull`
  geladen werden, haben eigene Lizenzen (z.B. Llama Community License,
  Apache 2.0). Wer Modelle wechselt, prueft die jeweilige Lizenz.

---

## 3. Genutzte Drittanbieter-APIs (Cloud)

Cloud-Services, die per HTTP/HTTPS angesprochen werden. Es gelten die
jeweiligen Terms of Service des Anbieters; die hier genannten Punkte sind
nur eine Kurzuebersicht.

### Anthropic API (Claude)
- Zweck: LLM-Konversation, Vision/Computer-Use, Claude-Agent.
- Authentifizierung per API-Key (`anthropic_api_key`).
- ToS: <https://www.anthropic.com/legal/commercial-terms>.

### OpenRouter
- Zweck: LLM-Gateway (alternative Routing-Schicht).
- ToS: <https://openrouter.ai/terms>.

### ElevenLabs
- Zweck: Cloud-TTS (Saleria's Stimme im Normalbetrieb).
- ToS: <https://elevenlabs.io/terms>.
- Hinweis: Voice-Cloning ist kostenpflichtig; das Voice-ID-Setup liegt
  beim Maintainer und wird nicht ins Repo gecheckt.

### Groq (Whisper API)
- Zweck: Schnelle Cloud-STT als Primaerpfad.
- ToS: <https://groq.com/terms-of-use/>.

### Brave Search API
- Zweck: Web-Suche fuer den `web`-Command.
- ToS: <https://api.search.brave.com/app/legal/terms-of-service>.

### Open-Meteo
- Zweck: Wetterdaten (aktuell, Vorhersage, Briefing).
- Daten: CC BY 4.0; API ist fuer nicht-kommerzielle Nutzung kostenlos.
- Lizenzhinweis: <https://open-meteo.com/en/license>.

### Google APIs
- Calendar API + Maps Directions API (beide nur als Fallback bzw.
  fuer Routenplanung; Hauptpfad fuer Termine ist Nextcloud CalDAV).
- ToS: <https://developers.google.com/terms>.

### Nextcloud (CalDAV / CardDAV / Files)
- Selbstgehosteter Endpoint des Nutzers; Elder-Berry spricht ihn nur
  als Client an.
- Nextcloud Server: AGPLv3 (relevant, falls jemand selber hosten will).

### Logitech Harmony Hub
- Zweck: Smart-Home / IR-Steuerung ueber lokales Netz.
- Kein offizielles SDK; Anbindung via Community-Library `aioharmony`
  (Apache 2.0).

### Matrix (Synapse-Server)
- Zweck: Hauptkommunikationskanal (Element/Matrix).
- Synapse: Apache 2.0. Der Maintainer hostet selbst; Elder-Berry ist
  nur Client.

---

## 4. Hinweise zum Forken

Wer das Repo forkt, sollte beachten:

- **MIT bleibt MIT**: Code, Voice-Samples und Avatar-Sprites sind frei
  weiterverwendbar, solange Copyright-Hinweis und Lizenz mitgeliefert
  werden.
- **XTTS v2 ist non-commercial**: Wer Elder-Berry kommerziell deployen
  will, muss XTTS v2 ausbauen oder ersetzen.
- **API-Keys sind nicht im Repo**: Anthropic, ElevenLabs, Groq, Brave,
  Google, Matrix usw. muss jede Installation selber besorgen.
- **Charakter-Nutzung**: Saleria darf weiterverwendet werden (MIT auf
  den Assets), aber bitte transparent als Fork/Adaption kennzeichnen.
