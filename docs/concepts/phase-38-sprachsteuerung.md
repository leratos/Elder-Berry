# Phase 37 – Sprachsteuerung / Alexa-Ablösung

## Übersicht

Saleria erhält eine eigene Sprachschnittstelle. Ziel ist vollständige
Unabhängigkeit von Amazon — aber ohne harten Cut. Beide Modi laufen
parallel, der Nutzer entscheidet welchen er gerade verwendet.

### Warum zwei Modi

| | Alexa Proxy (37.1) | Natives Wake Word (37.2) |
|---|---|---|
| Hardware | Echo (vorhanden) | ReSpeaker ~60€ |
| Neue Hardware | keine | ja |
| STT-Qualität | Amazon-Cloud (sehr gut) | faster-whisper GPU (sehr gut) |
| Datenschutz | Amazon hört Wake Word + STT | vollständig lokal |
| Latenz | ~2–3s | ~3–5s |
| Reichweite | Echo-Array (exzellent) | ReSpeaker-Array (sehr gut) |
| Offline | nein | ja |

**Empfohlene Reihenfolge**: 37.1 zuerst (sofort nutzbar, keine Kosten),
37.2 wenn Datenschutz wichtiger wird oder Echo defekt ist.

---

# Phase 37.1 – Alexa Skill "Saleria" (Proxy-Modus)

## Wie es funktioniert

```
Nutzer: "Alexa, frag Saleria mach den Fernseher an"
         │
         ▼
Echo-Mikrofon-Array (7 Mics, Beamforming)
  → Amazon STT (Cloud)
  → Text: "mach den Fernseher an"
         │
         ▼
Custom Alexa Skill Endpoint (Rootserver HTTPS)
  → POST https://rootserver/alexa/saleria
  → {"intent": "SaleriaCommand", "text": "mach den Fernseher an"}
         │
         ▼
Saleria Command Pipeline (Tower)
  → gleicher Fluss wie Matrix-Nachricht
  → HarmonyAdapter → Hub → IR → TV
         │
         ▼
Antwort-Text → zurück an Alexa Skill
  → Alexa spricht Antwort ("Fernseher wurde eingeschaltet")
```

## Was Amazon dabei sieht

Wake Word ("Alexa") + den gesprochenen Text — das gleiche wie heute.
Der Befehl selbst wird lokal bei Saleria ausgeführt, Amazon sieht
nur die Transkription. Kein Unterschied zur heutigen Alexa-Nutzung,
aber die Intelligenz liegt bei Saleria statt bei Amazons Skills.

## Implementierung

### Alexa Skill Konfiguration (Amazon Developer Console)

```
Skill-Name: Saleria
Invocation Name: "saleria"
Intent: SaleriaCommand
  Slot: CommandText (AMAZON.SearchQuery)
  Utterances:
    "{CommandText}"
    "sag {CommandText}"
    "frag {CommandText}"
Endpoint: https://rootserver.com/alexa/saleria (HTTPS, eigenes Cert)
```

### AlexaSkillHandler

**Datei**: `src/elder_berry/server/alexa_skill_handler.py`
**Deployment**: Rootserver (öffentlich erreichbar, HTTPS Pflicht für Alexa)

```python
"""AlexaSkillHandler – Alexa Custom Skill Endpoint für Saleria.

Empfängt Intents von Amazon Alexa, leitet Text an Salerias
Command-Pipeline weiter und gibt Antwort-Text zurück.

Sicherheit:
  - Alexa-Request-Signatur-Validierung (ask-sdk oder manuell)
  - Nur POST von Amazon-IPs (optional, da Signatur ausreicht)

Deployment: Rootserver, eingebunden in bestehenden Nginx vhost.
"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/alexa", tags=["alexa"])


class AlexaRequest(BaseModel):
    """Vereinfachtes Alexa Request-Schema (relevante Felder)."""
    version: str
    session: dict
    request: dict  # type, intent, slots


@router.post("/saleria")
async def saleria_skill(request: Request) -> dict:
    """Alexa Skill Endpoint.

    Validiert Alexa-Signatur, extrahiert Command-Text,
    leitet an Saleria weiter, gibt Alexa-Response zurück.
    """
    ...
```

### Saleria-seitige Änderungen (minimal)

Der Command-Text von Alexa wird genauso behandelt wie eine
Matrix-Nachricht — derselbe CommandDispatcher, dieselben Handler.

Einziger Unterschied: Antwort geht zurück an Alexa als JSON,
nicht als Matrix-Message. XTTS wird nicht getriggert
(Alexa spricht selbst).

```python
# Antwort-Format für Alexa:
{
    "version": "1.0",
    "response": {
        "outputSpeech": {
            "type": "PlainText",
            "text": "Fernseher wurde eingeschaltet."
        },
        "shouldEndSession": True
    }
}
```

### Nginx (Rootserver)

```nginx
# Bestehender vhost, neue location:
location /alexa/ {
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
}
```

## Nutzungs-Pattern

```
Kurze Befehle (ohne Wartezeit):
  "Alexa, frag Saleria fernsehen an"
  "Alexa, frag Saleria mach lauter"
  "Alexa, frag Saleria licht an"

Fragen (Saleria antwortet, Alexa spricht):
  "Alexa, frag Saleria was steht morgen an"
  "Alexa, frag Saleria wie wird das Wetter"
```

## Testliste (~15 Tests)

```
test_alexa_skill_handler.py:
  valid_launch_request, valid_saleria_command_intent,
  missing_command_slot_graceful, empty_command_slot_graceful,
  signature_validation_rejects_invalid, signature_validation_accepts_valid,
  command_dispatched_to_pipeline, response_format_correct,
  should_end_session_true, error_returns_alexa_error_response,
  alexa_request_forwarded_as_matrix_equivalent
```

---

# Phase 37.2 – Natives Wake Word + Mic Array

## Übersicht

Vollständige Ablösung von Alexa. "Hey Saleria" als Wake Word,
faster-whisper auf Tower-GPU für STT. Kein Amazon, keine Cloud.

## Hardware-Optionen

**Option A: ReSpeaker USB Mic Array v2** (~60€)
- 4 Mikrofone, 360° Beamforming, Noise-Cancellation
- USB, plug-and-play am RPi5
- Reichweite: ~5m in normaler Umgebung
- Bewährt in Community für genau diesen Use Case

**Option B: Echo als Rohes Mikrofon**
- Technisch nicht möglich. Amazon sperrt den Audio-Stream.
- Kein offizieller API-Zugang zum Mikrofon-Array.
- Workarounds (MITM, Firmware-Mod) fragil und nicht supportet.
- **Fazit: nicht umsetzbar.**

**Option C: USB-Kondensatormikrofon + Software-Beamforming**
- Günstiger (~20€), aber deutlich geringere Reichweite
- Für Schreibtisch-Nutzung ausreichend

## Softwarestack

```
RPi5 (24/7):
  OpenWakeWord  → lauscht permanent auf "Hey Saleria"
                  (CPU-Last: ~5-8% auf RPi5, akzeptabel)
  Bei Erkennung → nimmt Audio auf → sendet an Tower

Tower:
  faster-whisper (GPU) → STT in ~0.5s
  → Text an CommandDispatcher (gleicher Fluss)
  → Antwort → XTTS → Audio zurück an RPi5 → Lautsprecher
```

### Latenz-Realität

```
Wake Word erkannt → STT → LLM → XTTS → Ausgabe
     0.1s           0.5s   2-4s   1-2s
= 3.6 – 6.6 Sekunden gesamt

Zum Vergleich Alexa: ~1.5–2.5s
```

Das ist spürbar langsamer als Alexa bei kurzen Befehlen.
Für komplexe Anfragen ("was steht diese Woche an?") fällt
der Unterschied weniger ins Gewicht.

## Wechsel-Mechanismus (Flexibilität)

```json
// elder_berry.json
{
  "voice_mode": "alexa_proxy",  // oder "native" oder "both"
  "wake_word": "hey saleria",
  "alexa_skill_active": true
}
```

Im `both`-Modus laufen 37.1 und 37.2 parallel:
- Alexa-Skill antwortet wenn via Echo gesprochen
- OpenWakeWord antwortet wenn "Hey Saleria" erkannt

## Neue Dateien Phase 37

```
Rootserver:
  src/elder_berry/server/alexa_skill_handler.py    (37.1)

RPi5:
  src/elder_berry/robot/wake_word_listener.py      (37.2)
  src/elder_berry/robot/audio_streamer.py          (37.2)

Tower:
  src/elder_berry/stt/faster_whisper_client.py     (37.2, falls nicht vorhanden)
  src/elder_berry/comms/voice_gateway.py           (37.2, Routing Audio→Text→Pipeline)

Konfiguration:
  elder_berry.json: voice_mode, wake_word, alexa_skill_active
```

## Offene Entscheidungen (für eigenen Chat)

| Punkt | Optionen | Klärung wann |
|-------|---------|--------------|
| Hardware 37.2 | ReSpeaker vs. USB-Kondensator | Bei Hardware-Kauf |
| Latenz 37.2 akzeptabel? | Testen mit faster-whisper | Nach 37.1-Deployment |
| voice_mode Default | alexa_proxy / native / both | Persönliche Präferenz |
| Alexa komplett abschalten | Nach 37.2 stabil | Eigene Entscheidung |

## Hinweis

Phase 37.2 wird in einem eigenen Chat vollständig ausgearbeitet
wenn 37.1 deployed und getestet ist. Hardware-Entscheidung
hängt von Latenz-Tests ab.
