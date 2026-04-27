# Phase 6 – Matrix-Integration (Konzept)

> **Status:** Planung abgeschlossen – bereit zur Umsetzung
> **Erstellt:** 2026-03-15 (Claude App – Konzeptplanung)
> **Umsetzung:** VS Code / Claude Code
> **Branch:** `feature/phase-6-matrix-integration`

---

## 1. Ziel

Saleria soll über einen selbst gehosteten Matrix-Server erreichbar sein.
Der Nutzer schreibt über Element (Handy/Desktop) eine Nachricht → Saleria
empfängt sie, verarbeitet sie über das LLM (Ollama auf Tower), generiert
Text + Audio (TTS) und antwortet über Matrix.

## 2. Architektur-Übersicht

```
[Element Client]          [Plesk-Server]              [Tower / Laptop]
  (Handy/PC)                                         (Elder-Berry)
      │                        │                          │
      │── Nachricht ──────────>│  Synapse                 │
      │                        │  (Matrix-Server)         │
      │                        │<──── /sync (long-poll) ──│ MatrixChannel
      │                        │                          │
      │                        │                          │── Message an Assistant
      │                        │                          │── Assistant → LLMRouter → Ollama
      │                        │                          │── TTS → Audio (.ogg)
      │                        │                          │── MatrixChannel.send_text()
      │                        │                          │── MatrixChannel.send_audio()
      │                        │                          │
      │<── Antwort (Text) ─────│<─────────────────────────│
      │<── Sprachnachricht ────│<─────────────────────────│
```

## 3. Komponenten

### 3.1 Server-Seite (Plesk-Server – manuelles Setup)

- **Matrix-Server:** Synapse (Docker)
  - Grund: Referenz-Implementierung, beste Kompatibilität mit matrix-nio
  - RAM-Verbrauch ~300-500MB – bei 27GB frei irrelevant
  - Speicher: ~390GB frei – mehr als genug
- **Domain:** `matrix.example.com`
- **SSL:** Let's Encrypt über Plesk
- **Accounts:** 1× Bot-Account (`@saleria:matrix.example.com`), 1× User-Account
  - Hinweis: server_name = `matrix.example.com` → User-IDs enthalten `matrix.`
  - Kürzere IDs (`@saleria:example.com`) wären möglich mit .well-known Delegation,
    aber unnötig da Federation deaktiviert ist
- **Federation:** DEAKTIVIERT (privater Server, kein Grund nach außen zu föderieren)
- **E2EE:** Phase 1 OHNE Verschlüsselung (vereinfacht Bot-Entwicklung massiv)
  - Begründung: Privater Server, nur 2 Accounts, kein Dritter hat Zugang
  - E2EE als optionale Erweiterung in Phase 6b denkbar

### 3.2 Elder-Berry-Seite (Tower / Laptop)

#### Neue Dateien:
| Datei | Klasse / Zweck |
|-------|---------------|
| `src/elder_berry/comms/__init__.py` | Package-Init |
| `src/elder_berry/comms/message_channel.py` | `MessageChannel` (ABC) |
| `src/elder_berry/comms/matrix_channel.py` | `MatrixChannel(MessageChannel)` |
| `tests/test_matrix_channel.py` | Unit-Tests mit Mock |
| `docs/matrix_setup.md` | Server-Setup-Anleitung |
| `scripts/demo_matrix_bot.py` | Standalone-Testscript |

#### Bestehende Dateien (Änderungen):
| Datei | Änderung |
|-------|----------|
| `src/elder_berry/core/assistant.py` | Neuer DI-Parameter `message_channel: MessageChannel \| None` |
| `pyproject.toml` | Dependencies: `matrix-nio`, `pydub` oder `ffmpeg-python` |

## 4. Klassen-Design

### 4.1 MessageChannel (ABC)

```python
# src/elder_berry/comms/message_channel.py
from abc import ABC, abstractmethod
from pathlib import Path

class IncomingMessage:
    """DTO für eingehende Nachrichten."""
    sender: str          # Matrix User-ID (@user:domain)
    room_id: str         # Matrix Room-ID
    body: str            # Nachrichtentext
    timestamp: float     # Unix-Timestamp

class MessageChannel(ABC):
    """Interface für bidirektionale Nachrichtenkanäle."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send_text(self, room_id: str, text: str) -> None: ...

    @abstractmethod
    async def send_audio(self, room_id: str, audio_path: Path) -> None: ...

    @abstractmethod
    async def on_message(self, callback) -> None:
        """Registriert Callback für eingehende Nachrichten."""
        ...

    @abstractmethod
    async def sync_loop(self) -> None:
        """Startet den Sync-Loop (blockierend, in eigener Task)."""
        ...
```

### 4.2 MatrixChannel

```python
# src/elder_berry/comms/matrix_channel.py
from nio import AsyncClient, RoomMessageText
from elder_berry.comms.message_channel import MessageChannel, IncomingMessage

class MatrixChannel(MessageChannel):
    """Matrix-Implementierung des MessageChannel."""

    def __init__(
        self,
        homeserver: str,       # "https://matrix.example.com"
        user_id: str,          # "@saleria:matrix.example.com"
        password: str,         # oder access_token
        allowed_rooms: list[str] | None = None,  # Whitelist
    ): ...

    async def connect(self) -> None:
        """Login + initialer Sync."""

    async def send_text(self, room_id: str, text: str) -> None:
        """Sendet m.room.message (msgtype: m.text)."""

    async def send_audio(self, room_id: str, audio_path: Path) -> None:
        """Konvertiert zu OGG/Opus, Upload, sendet als Sprachnachricht.
        Matrix-Event: m.room.message, msgtype: m.audio
        + org.matrix.msc3245.voice Flag für Element-Darstellung."""

    async def sync_loop(self) -> None:
        """nio.AsyncClient.sync_forever() Wrapper."""
```

### 4.3 Assistant-Integration

```python
# Erweiterung in src/elder_berry/core/assistant.py
class Assistant:
    def __init__(
        self,
        llm_router: LLMRouter,
        action_controller: ActionController,
        character_engine: CharacterEngine | None = None,
        robot_client: RobotClient | None = None,
        message_channel: MessageChannel | None = None,  # NEU
    ): ...

    async def handle_matrix_message(self, msg: IncomingMessage) -> None:
        """Verarbeitet Matrix-Nachricht: LLM → TTS → Antwort."""
        response_text = await self.process(msg.body)
        audio_path = await self.tts.synthesize(response_text)
        ogg_path = convert_to_ogg(audio_path)

        await self.message_channel.send_text(msg.room_id, response_text)
        await self.message_channel.send_audio(msg.room_id, ogg_path)
```

## 5. Audio-Pipeline (Text → Sprachnachricht)

```
TTS-Output (WAV/MP3) → Konvertierung → OGG/Opus → Matrix Upload → Element zeigt Sprachnachricht
```

- **Konvertierung:** `pydub` + `ffmpeg` (muss auf Tower/Laptop installiert sein)
- **Format:** OGG mit Opus-Codec – Element erwartet das für Sprachnachrichten
- **Matrix-Event Metadata:**
  ```json
  {
    "msgtype": "m.audio",
    "body": "voice_message.ogg",
    "info": {
      "mimetype": "audio/ogg",
      "duration": 3200
    },
    "org.matrix.msc3245.voice": {}
  }
  ```
- **Wichtig:** Der `org.matrix.msc3245.voice` Key ist nötig, damit Element
  die Datei als Sprachnachricht (Waveform-Player) anzeigt statt als Download-Link
- **ffmpeg Verfügbarkeit prüfen:** MatrixChannel.__init__ sollte beim Start
  prüfen ob ffmpeg installiert ist und warnen wenn nicht

## 6. Plattform-Handling (Tower vs. Laptop)

Saleria soll auf beiden laufen können. Kritischer Unterschied:

| Aspekt | Tower | Laptop |
|--------|-------|--------|
| Ollama | lokal (localhost:11434) | lokal (localhost:11434) |
| VRAM | 16GB – phi4:14b voll in VRAM | 8GB – phi4:14b mit RAM-Auslagerung |
| Matrix-Bot | verbindet sich zum Plesk-Server | identisch |
| TTS | lokal | lokal |

**Kein Architektur-Unterschied.** Beide haben Ollama lokal, beide verbinden
sich ausgehend zum Matrix-Server. Der LLMRouter entscheidet bereits jetzt
anhand der Config welchen Endpoint er nutzt. Kein Extra-Code nötig.

**Config-Ansatz:** `config.yaml` oder `.env` mit:
```yaml
matrix:
  homeserver: "https://matrix.example.com"
  user_id: "@saleria:matrix.example.com"
  password: "${MATRIX_BOT_PASSWORD}"  # oder access_token
  allowed_rooms:
    - "!roomid:matrix.example.com"
```

## 7. Teilschritte (Umsetzungsreihenfolge)

### TS1 – Synapse Server-Setup
- **Wer:** Nutzer manuell (SSH auf Plesk-Server)
- **Anleitung:** `docs/matrix_setup.md` (erstellt, bereit zur Ausführung)
- **Inhalt:**
  1. Docker + Docker Compose installieren (falls nicht vorhanden)
  2. Synapse Container starten (+ PostgreSQL)
  3. Subdomain in Plesk anlegen + SSL
  4. Nginx Reverse Proxy konfigurieren (Plesk oder manuell)
  5. Bot-Account registrieren: `@saleria:matrix.example.com`
  6. User-Account registrieren
  7. Raum erstellen, beide Accounts einladen
  8. Element-Client auf Handy einrichten + einloggen
  9. Testmeldung senden → Empfang verifizieren
- **Ergebnis:** Matrix-Server läuft, Element funktioniert, Bot-Account existiert
- **Keine Code-Änderungen an Elder-Berry**

### TS2 – MessageChannel ABC + MatrixChannel
- **Branch:** `feature/phase-6-matrix-integration`
- **Neue Dateien:**
  - `src/elder_berry/comms/__init__.py`
  - `src/elder_berry/comms/message_channel.py` (ABC + DTOs)
  - `src/elder_berry/comms/matrix_channel.py` (Implementierung)
  - `tests/test_matrix_channel.py`
- **Dependencies:** `matrix-nio[e2e]` (e2e optional, aber Library braucht es für Import)
- **Tests:** Mock-basiert (kein echter Server nötig)
- **Ergebnis:** MatrixChannel kann connect/send_text/send_audio, getestet

### TS3 – Audio-Pipeline (WAV → OGG/Opus)
- **Neue Datei:** `src/elder_berry/comms/audio_converter.py`
  - Klasse `AudioConverter` – konvertiert WAV/MP3 → OGG/Opus
  - Prüft ffmpeg-Verfügbarkeit bei Init
  - Berechnet Duration für Matrix-Metadata
- **Dependency:** `pydub` (nutzt ffmpeg unter der Haube)
- **Tests:** `tests/test_audio_converter.py` (mit Test-WAV-Datei)
- **Ergebnis:** Zuverlässige Audio-Konvertierung, plattformübergreifend

### TS4 – Assistant-Integration + Demo
- **Bestehende Datei:** `src/elder_berry/core/assistant.py`
  - Neuer DI-Parameter: `message_channel: MessageChannel | None`
  - Neue Methode: `handle_matrix_message(IncomingMessage)`
  - Nachrichtenfluss: Message → LLM → TTS → Audio-Convert → Matrix-Antwort
- **Neue Datei:** `scripts/demo_matrix_bot.py`
  - Standalone: startet MatrixChannel + Assistant, wartet auf Nachrichten
  - Für Live-Test mit echtem Server
- **Tests:** `tests/test_assistant_matrix.py`
- **Ergebnis:** Ende-zu-Ende funktionsfähig

## 8. Dependencies (neu)

```toml
# In pyproject.toml [project.optional-dependencies]
matrix = [
    "matrix-nio>=0.24",
    "pydub>=0.25",
]
```

- `matrix-nio`: Async Matrix-Client (Python, gut gepflegt)
- `pydub`: Audio-Konvertierung (benötigt ffmpeg als System-Dependency)
- **ffmpeg:** Muss separat installiert sein (Windows: `choco install ffmpeg` oder manuell)

## 9. Risiken & offene Punkte

| Risiko | Schwere | Mitigation |
|--------|---------|------------|
| Synapse Docker + Plesk Nginx Konflikt | Mittel | Port-Mapping prüfen, Plesk Proxy nutzen |
| matrix-nio API-Änderungen | Gering | Version pinnen, nio ist stabil |
| ffmpeg nicht installiert auf Laptop | Gering | Check bei Init, klare Fehlermeldung |
| Audio-Format von Element nicht erkannt | Mittel | MSC3245-Flag testen, Fallback: normaler Audio-Upload |
| Long-Poll Abbrüche bei instabilem WLAN | Mittel | Reconnect-Logic in sync_loop |
| Bot antwortet in falschem Raum | Gering | allowed_rooms Whitelist |
| Credential-Leak (Passwort in Config) | Mittel | .env + .gitignore, NICHT in Config-Datei |

## 10. Bewusst NICHT in Phase 6

- **E2EE:** Zu komplex für v1 (Device Verification, Key Backup, Olm-Sessions)
- **Multi-User:** Nur 1 Nutzer + 1 Bot. Kein Gruppen-Support.
- **Media-Empfang:** Saleria empfängt nur Text. Bilder/Dateien vom User → ignoriert (für jetzt)
- **Slash-Commands:** Keine `/status`, `/battery` etc. – Saleria behandelt alles als natürliche Sprache
- **Read-Receipts / Typing-Indicator:** Nice-to-have, nicht für v1

## 11. Referenz für Claude Code

Dieses Dokument liegt unter `docs/concepts/phase-6-matrix-integration.md`.
Claude Code soll es zu Beginn der Phase lesen und als Vorgabe nutzen.

**Workflow:**
1. Claude Code liest `docs/journal.txt` (aktueller Stand)
2. Claude Code liest `docs/concepts/phase-6-matrix-integration.md` (dieser Plan)
3. Umsetzung gemäß Teilschritten (TS1–TS4)
4. Fortschritt wird in `journal.txt` dokumentiert (nicht in diesem Dokument)
