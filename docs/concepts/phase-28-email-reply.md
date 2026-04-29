# Phase 28 – Email-Reply via Matrix (SMTP + Pending Confirmation)

## Übersicht

Saleria kann auf E-Mails antworten. Der Nutzer gibt per Matrix eine Anweisung
("antworte auf #123 positiv", "sag ab wegen Terminkonflikt"), Saleria generiert
einen Draft via Claude API, zeigt ihn zur Bestätigung, und sendet nach "ja" per SMTP.

### Neue Fähigkeiten

- **Email-Antworten**: Draft generieren (Claude Sonnet 4.6) → Bestätigung → SMTP-Versand
- **Pending Confirmation Pattern**: Generischer Mechanismus für Aktionen die Nutzer-Bestätigung erfordern (wiederverwendbar für andere Features)
- **SMTP-Client**: Eigene Klasse `EmailSender` (Strato SMTP, gleiche Credentials wie IMAP)

### User-Flow

```
Nutzer: "antworte auf mail #4523 positiv, bedanke dich für das Angebot"
                    │
                    ▼
        MailCommandHandler.execute("mail_reply", raw_text)
                    │
                    ▼
        IMAPEmailClient.get_by_uid("4523") → Original-Mail
                    │
                    ▼
        AnthropicClient.generate(system=EMAIL_SYSTEM_PROMPT,
                                 prompt=Original + Anweisung)
                    │
                    ▼
        → CommandResult(pending_confirmation=True, pending_data={...})
                    │
                    ▼
        Bridge zeigt Draft in Matrix:
        "📧 Entwurf für Antwort auf #4523:
         ---
         Betreff: Re: Angebot Dachsanierung
         An: info@firma.de

         Sehr geehrte Damen und Herren,
         vielen Dank für Ihr Angebot vom ...
         ---
         ✅ 'ja' zum Senden / ❌ 'nein' zum Verwerfen / 'ändern: ...' zum Anpassen"
                    │
                    ▼
Nutzer: "ja"  ──→  PendingConfirmation.confirm()
                    │
                    ▼
        EmailSender.send_reply(msg_id, draft_text, ...)
                    │
                    ▼
        "✅ Antwort auf #4523 gesendet."
```
---

## 1. EmailSender – SMTP-Client

**Datei**: `src/elder_berry/tools/email_sender.py`

Eigene Klasse, getrennt vom `IMAPEmailClient` (Single Responsibility).
Gleiche Credentials (email_user, email_password), anderer Server (SMTP statt IMAP).

### SecretStore-Keys

Bestehend (schon für IMAP konfiguriert):
- `email_user` → Absender-Adresse (z.B. `saleria@example.com`)
- `email_password` → Passwort

Neu:
- `email_smtp_host` → `smtp.strato.de` (Default wenn nicht gesetzt)
- `email_smtp_port` → `465` (Default: SSL)

### Klassen-Signatur

```python
"""EmailSender – E-Mails senden via SMTP (Strato, GMX, Gmail, etc.).

Sendet Antworten auf bestehende E-Mails mit korrekten Reply-Headern.
Keine extra Dependencies – nutzt Python-Standardbibliothek (smtplib, email).
"""
from __future__ import annotations

import email.message
import logging
import smtplib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SentEmail:
    """Ergebnis eines gesendeten Emails."""
    to: str
    subject: str
    success: bool
    error: str = ""

class EmailSender:
    """SMTP E-Mail Client – sendet Mails über beliebigen Provider.

    Verbindung wird pro Aufruf aufgebaut und geschlossen (kein Langzeit-Socket).
    """

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int = 465,
        use_ssl: bool = True,
        sender_name: str = "Saleria",
    ) -> None:
        self._host = host
        self._user = user
        self._password = password
        self._port = port
        self._use_ssl = use_ssl
        self._sender_name = sender_name

    @classmethod
    def from_secret_store(cls, store: SecretStore) -> EmailSender:
        """Erstellt Client aus SecretStore-Einträgen.

        Erwartet: email_user, email_password
        Optional: email_smtp_host (default smtp.strato.de),
                  email_smtp_port (default 465)
        """
        return cls(
            host=store.get_or_none("email_smtp_host") or "smtp.strato.de",
            user=store.get("email_user"),
            password=store.get("email_password"),
            port=int(store.get_or_none("email_smtp_port") or "465"),
        )

    def is_available(self) -> bool:
        """Prüft ob SMTP-Verbindung möglich ist."""
        try:
            conn = self._connect()
            conn.quit()
            return True
        except Exception as e:
            logger.debug("SMTP nicht verfügbar: %s", e)
            return False
```
### Methoden

```python
    def send_reply(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
        references: str = "",
        cc: str = "",
    ) -> SentEmail:
        """Sendet eine Antwort-Email mit korrekten Threading-Headern.

        Args:
            to: Empfänger-Adresse.
            subject: Betreff (sollte mit "Re: " beginnen).
            body: Klartext-Body der Antwort.
            in_reply_to: Message-ID der Original-Mail (für Threading).
            references: References-Header der Original-Mail (für Threading).
            cc: Optionale CC-Adresse(n), kommagetrennt.

        Returns:
            SentEmail mit Ergebnis.
        """
        ...

    def _connect(self) -> smtplib.SMTP_SSL | smtplib.SMTP:
        """Erstellt SMTP-Verbindung und loggt ein."""
        if self._use_ssl:
            conn = smtplib.SMTP_SSL(self._host, self._port)
        else:
            conn = smtplib.SMTP(self._host, self._port)
            conn.starttls()
        conn.login(self._user, self._password)
        return conn

    def _build_reply_message(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str,
        references: str,
        cc: str,
    ) -> email.message.EmailMessage:
        """Baut eine RFC-konforme Reply-Email zusammen.

        Setzt korrekte Header für Email-Threading:
        - In-Reply-To: Message-ID der Original-Mail
        - References: Message-ID-Kette für Thread-Ansicht
        - From: "Saleria <user@domain>"
        """
        ...
```
### Wichtig: Reply-Header aus Original-Mail extrahieren

Der `IMAPEmailClient` muss erweitert werden, um die Message-ID und References
aus einer Mail zu extrahieren. `EmailMessage` bekommt zwei neue Felder:

```python
# In email_client.py – EmailMessage erweitern:
@dataclass(frozen=True)
class EmailMessage:
    # ... bestehende Felder ...
    message_id: str = ""
    """RFC Message-ID Header (für In-Reply-To bei Replies)."""

    references: str = ""
    """References Header (Message-ID-Kette für Threading)."""
```

Die Felder werden in `_parse_email()` befüllt:

```python
# In _parse_email():
message_id = msg.get("Message-ID", "").strip()
references = msg.get("References", "").strip()
```

---

## 2. Pending Confirmation Pattern (generisch)

**Datei**: `src/elder_berry/comms/pending_confirmation.py`

Generischer Mechanismus für Aktionen die Nutzer-Bestätigung erfordern.
Wiederverwendbar für: Email-Reply, Email-Löschen, Datei-Löschen, etc.
### Architektur

```
Nachricht rein
    │
    ├─ Bridge prüft: gibt es ein PendingConfirmation für diesen User?
    │   ├─ JA + "ja"/"senden"  → pending.confirm() → Aktion ausführen
    │   ├─ JA + "nein"/"abbrechen" → pending.cancel() → verwerfen
    │   ├─ JA + "ändern: ..." → pending.modify(new_instruction) → neuer Draft
    │   └─ JA + anderer Text → "Du hast noch eine offene Bestätigung..."
    │
    └─ NEIN → normaler Command-Router / LLM Flow
```

### Klassen-Signatur

```python
"""PendingConfirmation – Generischer Bestätigungs-Mechanismus.

Speichert eine ausstehende Aktion pro User mit TTL.
Wird von der Bridge zwischen Command-Erkennung und LLM-Fallback geprüft.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Standard-TTL: 5 Minuten
DEFAULT_TTL_SECONDS = 300

# Regex für Bestätigungs-Antworten
CONFIRM_WORDS = frozenset({"ja", "yes", "senden", "send", "ok", "passt", "abschicken"})
CANCEL_WORDS = frozenset({"nein", "no", "abbrechen", "cancel", "verwerfen", "stopp"})
MODIFY_PREFIX = "ändern:"  # "ändern: mach es formeller"


@dataclass
class PendingAction:
    """Eine ausstehende Aktion die auf Bestätigung wartet."""

    action_type: str
    """Typ der Aktion (z.B. 'mail_reply', 'mail_delete')."""

    description: str
    """Menschenlesbare Beschreibung für den Nutzer."""

    data: dict[str, Any] = field(default_factory=dict)
    """Aktions-spezifische Daten (z.B. msg_id, draft_text, to, subject)."""

    created_at: float = field(default_factory=time.time)
    """Unix-Timestamp der Erstellung."""

    ttl: float = DEFAULT_TTL_SECONDS
    """Time-to-live in Sekunden."""

    @property
    def is_expired(self) -> bool:
        """True wenn die Aktion abgelaufen ist."""
        return (time.time() - self.created_at) > self.ttl

class PendingConfirmationStore:
    """Speichert ausstehende Aktionen pro User.

    Thread-safe: wird aus dem Bridge-Thread (async) und potentiell
    aus Worker-Threads aufgerufen.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingAction] = {}
        # Kein Lock nötig: Python GIL + dict-Operationen sind atomar

    def set(self, user_id: str, action: PendingAction) -> None:
        """Setzt eine ausstehende Aktion für einen User.

        Überschreibt eine eventuell bestehende Aktion (nur eine pro User).
        """
        self._pending[user_id] = action
        logger.info(
            "PendingAction gesetzt für %s: %s (TTL: %.0fs)",
            user_id, action.action_type, action.ttl,
        )

    def get(self, user_id: str) -> PendingAction | None:
        """Holt die ausstehende Aktion für einen User.

        Returns:
            PendingAction oder None (wenn keine oder abgelaufen).
        """
        action = self._pending.get(user_id)
        if action is None:
            return None
        if action.is_expired:
            logger.info(
                "PendingAction abgelaufen für %s: %s", user_id, action.action_type,
            )
            del self._pending[user_id]
            return None
        return action

    def clear(self, user_id: str) -> None:
        """Entfernt die ausstehende Aktion für einen User."""
        self._pending.pop(user_id, None)

    def check_response(self, user_id: str, text: str) -> tuple[str, PendingAction | None]:
        """Prüft ob ein Text eine Bestätigungs-Antwort ist.

        Args:
            user_id: Absender.
            text: Nachrichtentext (normalized lowercase).

        Returns:
            Tuple von (response_type, action):
            - ("confirm", action) → User hat bestätigt
            - ("cancel", action) → User hat abgebrochen
            - ("modify", action) → User will ändern (text ohne Prefix in action.data["modify_instruction"])
            - ("pending", action) → anderer Text, aber Aktion ist offen
            - ("none", None) → keine offene Aktion
        """
        action = self.get(user_id)
        if action is None:
            return ("none", None)

        normalized = text.strip().lower()

        if normalized in CONFIRM_WORDS:
            self.clear(user_id)
            return ("confirm", action)

        if normalized in CANCEL_WORDS:
            self.clear(user_id)
            return ("cancel", action)

        if normalized.startswith(MODIFY_PREFIX):
            instruction = text[len(MODIFY_PREFIX):].strip()
            action.data["modify_instruction"] = instruction
            return ("modify", action)

        return ("pending", action)
```
### Design-Entscheidungen

1. **Eine Aktion pro User**: Keine Queue, nur eine offene Bestätigung gleichzeitig.
   Begründung: Mehrere gleichzeitig offene Bestätigungen sind UX-Albtraum
   ("ja" bezieht sich worauf?).

2. **TTL statt Persistent**: 5 Minuten, dann verfällt der Draft automatisch.
   Kein SQLite, kein State-File. Bei Restart gehen offene Confirmations verloren
   — das ist akzeptabel, da es sich um kurzlebige Interaktionen handelt.

3. **"ändern:"-Prefix**: Erlaubt iteratives Verfeinern des Drafts ohne
   Abbrechen und Neuanfang. Nach "ändern: mach es formeller" wird ein neuer
   Draft generiert und die PendingAction aktualisiert.

4. **PendingAction.data ist ein dict**: Bewusst flexibel für verschiedene
   Aktionstypen. Für mail_reply enthält es:
   ```python
   data = {
       "msg_id": "4523",             # IMAP UID
       "to": "info@firma.de",        # Empfänger
       "subject": "Re: Angebot ...", # Betreff mit Re:
       "draft_text": "Sehr ...",     # Generierter Entwurf
       "in_reply_to": "<abc@mx>",    # Message-ID für Threading
       "references": "<abc@mx>",     # References für Threading
       "original_instruction": "positiv, bedanke dich",  # Nutzer-Anweisung
   }
   ```

---

## 3. Bridge-Integration

**Datei**: `src/elder_berry/comms/bridge.py`
### Änderungen in MatrixBridge

#### a) Neuer Konstruktor-Parameter

```python
def __init__(
    self,
    # ... bestehende Parameter ...
    email_sender: EmailSender | None = None,      # NEU
    pending_store: PendingConfirmationStore | None = None,  # NEU
) -> None:
    # ...
    self._email_sender = email_sender
    self._pending = pending_store or PendingConfirmationStore()
```

#### b) Confirmation-Intercept in _handle_message()

Der Intercept wird **vor** dem Command-Router eingefügt. Wichtig: vor
`parse_command()`, denn "ja" würde sonst nie als Bestätigung erkannt,
weil es kein registrierter Command ist (und ans LLM gehen würde).

```python
async def _handle_message(self, msg: IncomingMessage) -> None:
    # ... bestehende Checks (alte Nachrichten, Sender-Whitelist, Audio, Datei) ...

    # --- NEU: Pending Confirmation Intercept ---
    response_type, action = self._pending.check_response(
        msg.sender, msg.body,
    )
    if response_type == "confirm":
        await self._handle_pending_confirm(msg, action)
        return
    if response_type == "cancel":
        await self._channel.send_text(
            msg.room_id, "❌ Verworfen.",
        )
        return
    if response_type == "modify":
        await self._handle_pending_modify(msg, action)
        return
    if response_type == "pending":
        # User hat offene Bestätigung, aber keinen ja/nein Text geschickt
        await self._channel.send_text(
            msg.room_id,
            f"⏳ Du hast noch eine offene Aktion ({action.action_type}).\n"
            f"Antworte mit 'ja' zum Bestätigen, 'nein' zum Verwerfen, "
            f"oder 'ändern: <Anweisung>' zum Anpassen.",
        )
        return

    # --- Command-Router (bestehend, unverändert) ---
    if self._remote_commands:
        command = self._remote_commands.parse_command(msg.body)
        # ...
```
#### c) Confirm- und Modify-Handler

```python
async def _handle_pending_confirm(
    self, msg: IncomingMessage, action: PendingAction,
) -> None:
    """Führt eine bestätigte PendingAction aus."""
    if action.action_type == "mail_reply":
        await self._execute_mail_send(msg, action)
    # Zukünftig: elif action.action_type == "mail_delete": ...
    else:
        logger.warning("Unbekannter PendingAction-Typ: %s", action.action_type)
        await self._channel.send_text(
            msg.room_id, f"Unbekannte Aktion: {action.action_type}",
        )

async def _execute_mail_send(
    self, msg: IncomingMessage, action: PendingAction,
) -> None:
    """Sendet eine bestätigte Email-Antwort via SMTP."""
    if not self._email_sender:
        await self._channel.send_text(
            msg.room_id, "SMTP nicht konfiguriert.",
        )
        return

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            self._email_sender.send_reply,
            action.data["to"],
            action.data["subject"],
            action.data["draft_text"],
            action.data.get("in_reply_to", ""),
            action.data.get("references", ""),
        )

        if result.success:
            await self._channel.send_text(
                msg.room_id,
                f"✅ Antwort auf #{action.data['msg_id']} gesendet "
                f"an {result.to}.",
            )
            # In Chat-History speichern
            self._chat_history.add(msg.sender, "user", "ja")
            self._chat_history.add(
                msg.sender, "assistant",
                f"Email-Antwort gesendet an {result.to}: {action.data['subject']}",
            )
        else:
            await self._channel.send_text(
                msg.room_id,
                f"❌ Senden fehlgeschlagen: {result.error}",
            )
    except Exception as e:
        logger.error("Email senden fehlgeschlagen: %s", e)
        await self._channel.send_text(
            msg.room_id, f"❌ Fehler beim Senden: {type(e).__name__}",
        )
```
```python
async def _handle_pending_modify(
    self, msg: IncomingMessage, action: PendingAction,
) -> None:
    """Generiert einen neuen Draft basierend auf der Änderungsanweisung."""
    if action.action_type != "mail_reply":
        await self._channel.send_text(
            msg.room_id, "Ändern wird für diesen Aktionstyp nicht unterstützt.",
        )
        return

    modify_instruction = action.data.get("modify_instruction", "")
    if not modify_instruction:
        await self._channel.send_text(
            msg.room_id, "Format: ändern: <was soll anders sein>",
        )
        return

    # Neuen Draft generieren (über MailCommandHandler)
    # Die Bridge delegiert an den MailCommandHandler._generate_draft()
    # mit der kombinierten Anweisung (original + Änderung)
    try:
        loop = asyncio.get_running_loop()
        new_result = await loop.run_in_executor(
            None,
            self._remote_commands.execute,
            "mail_reply_modify",
            f"#{action.data['msg_id']} {modify_instruction}",
        )
        if new_result.success and new_result.pending_data:
            # Neue PendingAction mit aktualisiertem Draft
            new_action = PendingAction(
                action_type="mail_reply",
                description=new_result.text or "",
                data=new_result.pending_data,
            )
            self._pending.set(msg.sender, new_action)
            await self._channel.send_text(msg.room_id, new_result.text)
        else:
            await self._channel.send_text(
                msg.room_id,
                new_result.text or "Draft-Änderung fehlgeschlagen.",
            )
    except Exception as e:
        logger.error("Draft-Änderung fehlgeschlagen: %s", e)
        await self._channel.send_text(
            msg.room_id, f"❌ Änderung fehlgeschlagen: {type(e).__name__}",
        )
```
### d) CommandResult erweitern

**Datei**: `src/elder_berry/comms/commands/base.py`

```python
@dataclass
class CommandResult:
    # ... bestehende Felder ...

    pending_confirmation: bool = False
    """True wenn diese Aktion eine Nutzer-Bestätigung erfordert.
    Die Bridge erstellt dann eine PendingAction aus pending_data."""

    pending_data: dict[str, Any] | None = None
    """Daten für die PendingAction (z.B. Draft-Text, Empfänger).
    Nur relevant wenn pending_confirmation=True."""
```

**Import-Anpassung**: `from typing import Any` hinzufügen.

#### e) Bridge: CommandResult mit pending_confirmation verarbeiten

In `_handle_remote_command()`, **nach** dem bestehenden `mail_by_id`-Check:

```python
    # NEU: Pending Confirmation Commands
    if result.pending_confirmation and result.pending_data:
        action = PendingAction(
            action_type=result.command,
            description=result.text or "",
            data=result.pending_data,
        )
        self._pending.set(msg.sender, action)
        # Draft-Text an User senden
        if result.text:
            await self._channel.send_text(msg.room_id, result.text)
        # In Chat-History speichern
        self._chat_history.add(msg.sender, "user", msg.body)
        self._chat_history.add(msg.sender, "assistant", result.text or "")
        return
```

---

## 4. MailCommandHandler – mail_reply Command

**Datei**: `src/elder_berry/comms/commands/mail_commands.py`
### Neues Pattern

```python
# Regex für Mail-Antwort:
# "antworte auf #123 positiv"
# "antworte auf mail 456 dass es nicht geht"
# "gib auf mail #789 eine positive antwort"
# "beantworte mail #123 mit einer zusage"
# "mail #123 antworten: wir können am Montag"
MAIL_REPLY_PATTERN = re.compile(
    r"(?:antworte?\s+(?:auf\s+)?(?:mail\s*)?#?(\d+)\s+(.*)"
    r"|(?:gib|schreib)\s+(?:auf\s+)?(?:die\s+)?mail\s*#?(\d+)\s+(?:eine?\s+)?(.*)"
    r"|(?:beantworte?)\s+(?:die\s+)?mail\s*#?(\d+)\s+(?:mit\s+)?(.*)"
    r"|mail\s*#?(\d+)\s+(?:antworten|beantworten)(?::\s*|\s+)(.*)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

# Regex für Draft-Änderung (wird intern von Bridge genutzt):
# "mail_reply_modify" Command — Bridge schickt "#<id> <neue anweisung>"
MAIL_REPLY_MODIFY_PATTERN = re.compile(
    r"^#(\d+)\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
```

### Neue Keywords

```python
@property
def keywords(self) -> dict[str, list[str]]:
    return {
        # ... bestehende keywords ...
        "mail_reply": [
            "antworte auf mail", "beantworte mail",
            "antwort auf die mail", "mail beantworten",
            "gib auf die mail", "schreib auf die mail",
        ],
    }
```
### Konstruktor-Erweiterung

```python
class MailCommandHandler(CommandHandler):
    def __init__(
        self,
        email_client: IMAPEmailClient | None = None,
        anthropic_client: AnthropicClient | None = None,  # NEU
    ) -> None:
        self._email_client = email_client
        self._anthropic = anthropic_client
```

### _cmd_mail_reply() Implementierung

```python
def _cmd_mail_reply(self, raw_text: str) -> CommandResult:
    """Generiert einen Email-Antwort-Draft via Claude API.

    Gibt CommandResult mit pending_confirmation=True zurück.
    Die Bridge zeigt den Draft und wartet auf Bestätigung.
    """
    if not self._email_client:
        return CommandResult(
            command="mail_reply", success=False,
            text="E-Mail nicht konfiguriert.",
        )
    if not self._anthropic:
        return CommandResult(
            command="mail_reply", success=False,
            text="Claude API nicht konfiguriert (ANTHROPIC_API_KEY fehlt).",
        )

    # ID + Anweisung extrahieren
    msg_id, instruction = self._parse_reply_args(raw_text)
    if not msg_id:
        return CommandResult(
            command="mail_reply", success=False,
            text="Format: antworte auf #<ID> <Anweisung>\n"
                 "Beispiel: antworte auf #4523 positiv, bedanke dich",
        )

    # Original-Mail holen
    original = self._email_client.get_by_uid(msg_id)
    if not original:
        return CommandResult(
            command="mail_reply", success=False,
            text=f"Mail #{msg_id} nicht gefunden.",
        )

    # Draft generieren via Claude API
    draft = self._generate_draft(original, instruction)

    # Reply-Subject
    subject = original.subject
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    # Absender-Adresse extrahieren (für "An:")
    # Aus "Max Mustermann <max@example.com>" → "max@example.com"
    reply_to = self._extract_email_address(original.sender)

    # Draft-Text für Matrix-Anzeige formatieren
    display_text = (
        f"📧 Entwurf für Antwort auf #{msg_id}:\n"
        f"An: {reply_to}\n"
        f"Betreff: {subject}\n"
        f"---\n"
        f"{draft}\n"
        f"---\n"
        f"✅ 'ja' zum Senden / ❌ 'nein' zum Verwerfen / "
        f"'ändern: <Anweisung>' zum Anpassen"
    )

    return CommandResult(
        command="mail_reply",
        success=True,
        text=display_text,
        pending_confirmation=True,
        pending_data={
            "msg_id": msg_id,
            "to": reply_to,
            "subject": subject,
            "draft_text": draft,
            "in_reply_to": original.message_id,
            "references": original.references or original.message_id,
            "original_instruction": instruction,
        },
    )
```
### Draft-Generierung via Claude API

```python
# System-Prompt für Email-Draft-Generierung
EMAIL_SYSTEM_PROMPT = """Du bist Saleria, eine virtuelle Assistentin.
Du schreibst E-Mail-Antworten im Auftrag deines Nutzers.

Regeln:
- Schreibe auf Deutsch, es sei denn die Original-Mail ist auf Englisch
- Passe den Formalitätsgrad an die Original-Mail an
  (förmlich → förmlich, locker → locker)
- Keine Signatur einfügen (wird vom Mail-Client ergänzt)
- Keine Betreffzeile generieren (wird automatisch gesetzt)
- Halte die Antwort knapp und auf den Punkt
- Beginne NICHT mit "Betreff:" oder "An:" — nur den reinen Antworttext
- Wenn der Nutzer "positiv" sagt: freundliche Zusage
- Wenn der Nutzer "negativ" oder "absagen" sagt: höfliche Absage
- Wenn der Nutzer spezifische Formulierungen vorgibt: nutze diese
"""

def _generate_draft(
    self, original: EmailMessage, instruction: str,
) -> str:
    """Generiert einen Email-Draft via Claude Sonnet 4.6.

    Args:
        original: Die Original-Mail auf die geantwortet wird.
        instruction: Anweisung des Nutzers (z.B. "positiv, bedanke dich").

    Returns:
        Generierter Antworttext.

    Raises:
        RuntimeError: Bei API-Fehlern.
    """
    date_str = original.date.strftime("%d.%m.%Y %H:%M") if original.date else "?"
    prompt = (
        f"Original-Mail:\n"
        f"Von: {original.sender}\n"
        f"Datum: {date_str}\n"
        f"Betreff: {original.subject}\n"
        f"Inhalt:\n{original.body_preview}\n\n"
        f"---\n"
        f"Anweisung des Nutzers: {instruction}\n\n"
        f"Schreibe jetzt die Antwort-Mail (nur den Body, keine Header)."
    )
    return self._anthropic.generate(prompt, system=EMAIL_SYSTEM_PROMPT)
```
### Hilfsmethoden

```python
def _parse_reply_args(self, raw_text: str) -> tuple[str, str]:
    """Extrahiert Mail-ID und Anweisung aus dem Command-Text.

    Returns:
        Tuple (msg_id, instruction) oder ("", "") wenn nicht parsebar.
    """
    match = MAIL_REPLY_PATTERN.search(raw_text.strip())
    if not match:
        return ("", "")

    # 4 alternative Gruppen im Pattern (je 2: id + instruction)
    for i in range(1, 8, 2):
        msg_id = match.group(i)
        instruction = match.group(i + 1)
        if msg_id and instruction:
            return (msg_id.strip(), instruction.strip())

    return ("", "")

@staticmethod
def _extract_email_address(sender: str) -> str:
    """Extrahiert die Email-Adresse aus einem Sender-String.

    "Max Mustermann <max@example.com>" → "max@example.com"
    "max@example.com" → "max@example.com"
    """
    match = re.search(r"<([^>]+)>", sender)
    if match:
        return match.group(1)
    # Fallback: ganzer String wenn keine Klammern
    return sender.strip()
```

### mail_reply_modify Command (für "ändern: ...")

Wird intern von der Bridge genutzt, nicht direkt vom User:

```python
def _cmd_mail_reply_modify(self, raw_text: str) -> CommandResult:
    """Generiert einen neuen Draft mit geänderter Anweisung.

    raw_text kommt von der Bridge als "#<id> <neue anweisung>".
    """
    match = MAIL_REPLY_MODIFY_PATTERN.match(raw_text.strip())
    if not match:
        return CommandResult(
            command="mail_reply_modify", success=False,
            text="Ungültiges Format für Änderung.",
        )

    msg_id = match.group(1)
    new_instruction = match.group(2)

    # Original-Mail erneut holen + neuen Draft generieren
    # (identisch zu _cmd_mail_reply, nur mit anderer Anweisung)
    original = self._email_client.get_by_uid(msg_id)
    if not original:
        return CommandResult(
            command="mail_reply_modify", success=False,
            text=f"Mail #{msg_id} nicht gefunden.",
        )

    draft = self._generate_draft(original, new_instruction)
    # ... (gleiche pending_data Struktur wie _cmd_mail_reply)
```
---

## 5. RemoteCommandHandler – Änderungen

**Datei**: `src/elder_berry/comms/remote_commands.py`

### Neue DI-Parameter

```python
class RemoteCommandHandler:
    def __init__(
        self,
        # ... bestehende Parameter ...
        anthropic_client: AnthropicClient | None = None,  # BESTEHT SCHON
        email_sender: EmailSender | None = None,           # NEU (nur für Type-Hint, wird nicht direkt genutzt)
    ) -> None:
        # ...
        # MailCommandHandler bekommt jetzt auch den AnthropicClient:
        self._mail = MailCommandHandler(
            email_client=email_client,
            anthropic_client=anthropic_client,  # NEU
        )
```

**Achtung**: `anthropic_client` wird bereits an `CameraCommandHandler` übergeben.
Er muss jetzt auch an `MailCommandHandler` durchgereicht werden. Kein neuer
Parameter nötig — nur die interne Verdrahtung ändern.

### HELP_TEXT Erweiterung

Im E-Mail-Block ergänzen:

```
E-Mail:
  mails – Ungelesene E-Mails
  mails 5 – Letzte 5 Tage
  mail suche <Begriff> – Mails nach Betreff/Absender durchsuchen
  mail <ID> / mail #<ID> – Mail anzeigen
  mail anhang <ID> – Anhänge einer Mail senden
  mail zusammenfassung – LLM-Zusammenfassung ungelesener Mails
  antworte auf #<ID> <Anweisung> – Email-Antwort generieren    ← NEU
    Beispiele:
    antworte auf #4523 positiv, bedanke dich für das Angebot
    antworte auf #4523 sag ab wegen Terminkonflikt
    antworte auf #4523 frag nach einem Termin nächste Woche
    → Saleria zeigt Entwurf, du bestätigst mit 'ja'
```

### Handler-Liste: Reihenfolge

`_mail` bleibt an der bestehenden Position in `self._handlers`. Keine
Reihenfolgen-Änderung nötig — MAIL_REPLY_PATTERN kollidiert nicht mit
bestehenden Patterns (einzigartiges "antworte auf" Prefix).

### patterns-Erweiterung in MailCommandHandler

```python
@property
def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
    return [
        (MAIL_REPLY_PATTERN, "mail_reply", False, True),         # NEU – VOR mail_by_id
        (MAIL_REPLY_MODIFY_PATTERN, "mail_reply_modify", False, False),  # NEU (intern)
        (MAIL_ID_PATTERN, "mail_by_id", False, False),
        (MAIL_ATTACHMENT_PATTERN, "mail_attachment", False, True),
        (MAIL_SEARCH_PATTERN, "mail_search", False, True),
        (MAILS_DAYS_PATTERN, "mails", False, False),
    ]
```

**Wichtig**: `MAIL_REPLY_PATTERN` muss **vor** `MAIL_ID_PATTERN` stehen,
da "antworte auf mail #123 ..." sonst als "mail #123" gematcht wird
(MAIL_ID_PATTERN nutzt `search=False` / match, aber die Keyword-Erkennung
könnte kollidieren).

---

## 6. Start-Script Änderungen

**Datei**: `scripts/start.py` (Tower)

EmailSender wird beim Start erstellt und durchgereicht:

```python
# In start.py – nach IMAPEmailClient-Erstellung:
from elder_berry.tools.email_sender import EmailSender

email_sender = None
try:
    email_sender = EmailSender.from_secret_store(secret_store)
    if email_sender.is_available():
        logger.info("SMTP (EmailSender) verfügbar")
    else:
        logger.warning("SMTP nicht erreichbar")
        email_sender = None
except Exception as e:
    logger.warning("EmailSender nicht verfügbar: %s", e)
```

Durchreichen an Bridge:

```python
bridge = MatrixBridge(
    # ... bestehende Parameter ...
    email_sender=email_sender,     # NEU
    # pending_store wird intern erstellt (Default)
)
```

**Kein neuer SecretStore-Key für den Normalfall**: `email_smtp_host` hat
Default `smtp.strato.de`, Port Default `465`. Wer Strato nutzt, braucht
nichts zu konfigurieren. `from_secret_store()` nutzt dieselben `email_user`
und `email_password` Keys wie der IMAP-Client.

---

## 7. Edge Cases und Fehlerbehandlung

### 7.1 Abgelaufene PendingAction

Wenn der Nutzer nach 5 Minuten "ja" schreibt, ist die Aktion expired.
`PendingConfirmationStore.get()` gibt `None` zurück → `check_response()`
liefert `("none", None)` → normaler Command-Flow (kein Match → geht ans LLM).

Das LLM bekommt "ja" als Input und antwortet vermutlich verwirrt.
**Lösung**: Keine spezielle Behandlung nötig. Der 5-Min-TTL ist großzügig
genug. Wenn jemand nach 5 Min "ja" schreibt, ist das sein Problem.

### 7.2 Mehrere Nutzer gleichzeitig

`PendingConfirmationStore` ist per-User (dict[str, PendingAction]).
User A kann eine offene Confirmation haben, während User B normal
interagiert. Kein Konflikt.

### 7.3 Original-Mail nicht mehr vorhanden

Wenn zwischen "antworte auf #123" und dem eigentlichen Senden die Mail
vom Server gelöscht wird: `send_reply()` schlägt nicht fehl, da die
IMAP-UID nur für den Draft gebraucht wird. Der Draft ist in `pending_data`
gespeichert. Das Senden nutzt nur SMTP + die gespeicherten Header.

### 7.4 SMTP-Fehler beim Senden

`_execute_mail_send()` fängt Exceptions und sendet eine Fehlermeldung.
Die PendingAction ist bereits gelöscht (bei "confirm" wird `.clear()`
aufgerufen bevor die Aktion ausgeführt wird).
**Korrektur**: `.clear()` sollte erst NACH erfolgreichem Senden erfolgen.

→ Änderung: In `check_response()` bei "confirm" die Action NICHT sofort
löschen. Stattdessen gibt `check_response()` die Action zurück, und
`_handle_pending_confirm()` löscht erst nach erfolgreicher Ausführung.

```python
def check_response(self, user_id: str, text: str) -> tuple[str, PendingAction | None]:
    # ...
    if normalized in CONFIRM_WORDS:
        # NICHT self.clear(user_id) hier!
        # Bridge löscht nach erfolgreicher Ausführung.
        return ("confirm", action)

    if normalized in CANCEL_WORDS:
        self.clear(user_id)  # Bei Cancel sofort löschen (nichts zum Rückgängig machen)
        return ("cancel", action)
    # ...
```

Und in der Bridge:

```python
async def _execute_mail_send(self, msg, action):
    # ...
    if result.success:
        self._pending.clear(msg.sender)  # Erst nach Erfolg löschen
        await self._channel.send_text(...)
    else:
        # Bei Fehler: Action bleibt offen → User kann erneut "ja" sagen
        await self._channel.send_text(
            msg.room_id,
            f"❌ Senden fehlgeschlagen: {result.error}\n"
            f"Versuche es mit 'ja' erneut oder 'nein' zum Verwerfen.",
        )
```
### 7.5 "ändern:" Loop verhindern

Jeder "ändern:"-Aufruf generiert einen neuen Draft (Claude API Call).
Kein explizites Limit nötig — der TTL (5 Min) begrenzt die Interaktion
natürlich. Jeder API-Call kostet ~$0.01-0.03, also sind 10 Iterationen
noch unter $0.30. Akzeptabel.

### 7.6 SecretStore hat get_or_none

Prüfen ob `SecretStore.get_or_none()` existiert. Falls nicht: in
`EmailSender.from_secret_store()` stattdessen try/except auf
`SecretNotFoundError` nutzen.

---

## 8. Neue und geänderte Dateien (Zusammenfassung)

### Neue Dateien

| Datei | Beschreibung |
|-------|-------------|
| `src/elder_berry/tools/email_sender.py` | EmailSender – SMTP-Client (Strato) |
| `src/elder_berry/comms/pending_confirmation.py` | PendingConfirmationStore + PendingAction |
| `tests/test_email_sender.py` | Tests für EmailSender |
| `tests/test_pending_confirmation.py` | Tests für PendingConfirmationStore |
| `tests/test_mail_reply_commands.py` | Tests für mail_reply Pattern + Command |

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/elder_berry/tools/email_client.py` | `EmailMessage`: +message_id, +references Felder; `_parse_email()`: Header extrahieren |
| `src/elder_berry/comms/commands/base.py` | `CommandResult`: +pending_confirmation, +pending_data Felder |
| `src/elder_berry/comms/commands/mail_commands.py` | +MAIL_REPLY_PATTERN, +anthropic_client DI, +_cmd_mail_reply(), +_generate_draft() |
| `src/elder_berry/comms/bridge.py` | +email_sender DI, +PendingConfirmationStore, Confirmation-Intercept in _handle_message(), +_handle_pending_confirm/modify/execute |
| `src/elder_berry/comms/remote_commands.py` | anthropic_client an MailCommandHandler durchreichen, HELP_TEXT ergänzen |
| `scripts/start.py` | EmailSender erstellen + an Bridge übergeben |

---

## 9. Tests

### test_email_sender.py

```
TestEmailSender:
  test_from_secret_store_defaults        – smtp.strato.de:465 wenn keine Keys gesetzt
  test_from_secret_store_custom          – Eigene Host/Port-Werte
  test_build_reply_message_headers       – In-Reply-To, References, From korrekt
  test_build_reply_message_subject       – "Re:" Prefix korrekt
  test_build_reply_message_cc            – CC-Header wenn gesetzt
  test_build_reply_message_encoding      – UTF-8 Body (Umlaute)
  test_send_reply_success                – Mock SMTP, SentEmail.success=True
  test_send_reply_connection_error       – SentEmail.success=False, error gesetzt
  test_send_reply_auth_error             – Login-Fehler → SentEmail.error
  test_is_available_success              – Mock SMTP connect + quit
  test_is_available_failure              – Connection refused → False
```

### test_pending_confirmation.py

```
TestPendingAction:
  test_not_expired_within_ttl            – Frische Action → is_expired=False
  test_expired_after_ttl                 – time.sleep/mock → is_expired=True

TestPendingConfirmationStore:
  test_set_and_get                       – Action setzen + abrufen
  test_get_none_when_empty               – Kein User → None
  test_get_none_when_expired             – Abgelaufene Action → None, auto-cleanup
  test_clear                             – clear() → get() gibt None
  test_overwrite_existing                – Zweite Action überschreibt erste
  test_check_response_confirm            – "ja"/"senden"/"ok" → ("confirm", action)
  test_check_response_cancel             – "nein"/"abbrechen" → ("cancel", action)
  test_check_response_modify             – "ändern: formeller" → ("modify", action)
  test_check_response_modify_data        – modify_instruction in action.data
  test_check_response_pending            – "hallo" bei offener Action → ("pending", action)
  test_check_response_none               – Kein pending → ("none", None)
  test_check_response_expired            – Abgelaufene Action → ("none", None)
  test_confirm_does_not_clear            – "ja" löscht NICHT (Bridge macht das)
  test_cancel_clears                     – "nein" löscht sofort
  test_multiple_users_independent        – User A pending, User B frei
```
### test_mail_reply_commands.py

```
TestMailReplyPattern:
  test_antworte_auf_id_instruction       – "antworte auf #123 positiv" → match
  test_antworte_auf_mail_id              – "antworte auf mail 456 absagen" → match
  test_gib_auf_mail_antwort              – "gib auf mail #789 eine positive antwort" → match
  test_beantworte_mail_mit               – "beantworte mail #123 mit einer zusage" → match
  test_mail_id_antworten_colon           – "mail #123 antworten: text hier" → match
  test_no_match_plain_mail               – "mail #123" → kein Match (ist mail_by_id)
  test_no_match_mails                    – "mails" → kein Match
  test_no_match_mail_suche               – "mail suche xyz" → kein Match

TestMailReplyModifyPattern:
  test_modify_pattern_match              – "#123 mach es formeller" → match
  test_modify_pattern_no_match           – "mach es formeller" → kein Match

TestParseReplyArgs:
  test_parse_id_and_instruction          – Korrektes Tuple (id, instruction)
  test_parse_empty_instruction           – Leere Anweisung → ("", "")
  test_parse_no_match                    – Ungültiger Text → ("", "")

TestExtractEmailAddress:
  test_with_angle_brackets               – "Max <max@ex.com>" → "max@ex.com"
  test_plain_address                     – "max@ex.com" → "max@ex.com"
  test_with_quoted_name                  – '"Max M" <max@ex.com>' → "max@ex.com"

TestCmdMailReply:
  test_no_email_client                   – Fehlermeldung "nicht konfiguriert"
  test_no_anthropic_client               – Fehlermeldung "API nicht konfiguriert"
  test_mail_not_found                    – UID existiert nicht → Fehler
  test_success_returns_pending           – pending_confirmation=True, pending_data korrekt
  test_draft_text_in_display             – Draft-Text erscheint in result.text
  test_reply_to_correct                  – Empfänger korrekt extrahiert
  test_subject_re_prefix                 – "Re:" wird ergänzt wenn fehlt
  test_subject_re_already                – "Re:" wird nicht doppelt ergänzt
  test_message_id_in_pending_data        – in_reply_to korrekt gesetzt
  test_references_in_pending_data        – references korrekt gesetzt
  test_anthropic_error_handled           – RuntimeError → CommandResult.success=False

TestCmdMailReplyModify:
  test_modify_success                    – Neuer Draft mit geänderter Anweisung
  test_modify_mail_not_found             – UID nicht mehr da → Fehler

TestMailReplyKeywords:
  test_keyword_registration              – "antworte auf mail" ist registriert
  test_command_descriptions              – Neuer Command in Beschreibung
```
### Bestehende Test-Dateien erweitern

**tests/test_email_client.py** (bestehend):
```
TestEmailMessageExtensions:
  test_message_id_parsed                 – Message-ID Header wird extrahiert
  test_references_parsed                 – References Header wird extrahiert
  test_message_id_missing                – Fehlender Header → leerer String
  test_references_missing                – Fehlender Header → leerer String
```

**tests/test_mail_commands.py** (bestehend):
```
TestMailReplyPatternRegistration:
  test_mail_reply_in_patterns            – Pattern ist registriert
  test_mail_reply_priority               – mail_reply VOR mail_by_id in patterns-Liste
  test_no_collision_with_mail_by_id      – "mail #123" → mail_by_id, nicht mail_reply
  test_no_collision_with_mail_search     – "mail suche X" → mail_search, nicht mail_reply
```

### Bridge-Integration Tests (optional, falls Testinfrastruktur vorhanden)

**tests/test_bridge_confirmation.py** (neu, optional):
```
TestBridgeConfirmationIntercept:
  test_pending_intercept_before_commands – "ja" bei offener Action → confirm, nicht LLM
  test_pending_cancel                    – "nein" → cancel + Nachricht
  test_pending_modify                    – "ändern: ..." → neuer Draft
  test_pending_other_text                – "hallo" → Hinweis auf offene Action
  test_no_pending_normal_flow            – Kein pending → normaler Command-Router
  test_mail_reply_creates_pending        – mail_reply Command → PendingAction erstellt
  test_confirm_sends_email               – "ja" → EmailSender.send_reply() aufgerufen
  test_confirm_clears_after_success      – Nach Senden: pending gelöscht
  test_confirm_keeps_on_failure          – SMTP-Fehler: pending bleibt offen
```

---

## 10. Implementierungsreihenfolge für Claude Code

### Schritt 1: Grundlagen (keine Abhängigkeiten)

1. **`EmailMessage` erweitern** (`email_client.py`): +message_id, +references
   + Tests in bestehender `test_email_client.py`
2. **`CommandResult` erweitern** (`base.py`): +pending_confirmation, +pending_data
   (Import `Any` hinzufügen)
3. **`PendingConfirmationStore`** (`pending_confirmation.py`): Neue Datei
   + `test_pending_confirmation.py`

### Schritt 2: EmailSender

4. **`EmailSender`** (`email_sender.py`): Neue Datei
   + `test_email_sender.py`
   Prüfe zuerst ob `SecretStore.get_or_none()` existiert. Falls nicht:
   nutze try/except `SecretNotFoundError` in `from_secret_store()`.

### Schritt 3: MailCommandHandler Erweiterung

5. **MAIL_REPLY_PATTERN** + **mail_reply** Command in `mail_commands.py`
   + anthropic_client DI im Konstruktor
   + _generate_draft(), _parse_reply_args(), _extract_email_address()
   + patterns/keywords/command_descriptions erweitern
   + execute() erweitern (mail_reply + mail_reply_modify)
   + `test_mail_reply_commands.py`

### Schritt 4: RemoteCommandHandler Verdrahtung

6. **`remote_commands.py`**: anthropic_client an MailCommandHandler durchreichen
   + HELP_TEXT ergänzen
   + Tests in bestehender `test_mail_commands.py` (Pattern-Priorität)

### Schritt 5: Bridge Integration

7. **`bridge.py`**: email_sender + PendingConfirmationStore DI
   + Confirmation-Intercept in `_handle_message()`
   + `_handle_pending_confirm()`, `_handle_pending_modify()`, `_execute_mail_send()`
   + pending_confirmation-Block in `_handle_remote_command()`
   + Optional: `test_bridge_confirmation.py`

### Schritt 6: Start-Script

8. **`scripts/start.py`**: EmailSender erstellen + an Bridge übergeben

---

## 11. Offene Fragen / Hinweise für Claude Code

1. **SecretStore.get_or_none()**: Prüfe ob diese Methode existiert bevor du
   sie nutzt. Falls nicht: `try: store.get("key") except SecretNotFoundError: None`.

2. **Bestehende Tests nicht brechen**: `EmailMessage` bekommt neue Felder mit
   Default-Werten (`message_id: str = ""`, `references: str = ""`). Da `frozen=True`
   und neue Felder Defaults haben, sollten bestehende Instanziierungen weiterhin
   funktionieren. Trotzdem alle bestehenden `test_email_client.py` Tests laufen lassen.

3. **CommandResult**: Neue Felder `pending_confirmation: bool = False` und
   `pending_data: dict[str, Any] | None = None` haben Defaults → bestehender Code
   bricht nicht. Aber `from typing import Any` muss importiert werden.

4. **Bridge-Komplexität**: Die Bridge (`bridge.py`) ist bereits 1420 Zeilen lang.
   Der Confirmation-Intercept fügt ~100 Zeilen hinzu. Wenn es zu unübersichtlich
   wird, kann man einen `ConfirmationHandler` als eigene Klasse extrahieren, der
   die Bridge als Callback nutzt. Aber: erstmal einfach halten.

5. **Email-Signatur**: Der EMAIL_SYSTEM_PROMPT sagt "keine Signatur einfügen".
   Falls der Nutzer später eine Signatur möchte: eigene SecretStore-Key
   `email_signature` und an den Draft anhängen. Nicht im Scope dieser Phase.

6. **HTML-Emails**: Der `EmailSender` sendet nur Plain-Text. Für HTML-Emails
   müsste `_build_reply_message()` einen multipart/alternative MIME-Body bauen.
   Nicht im Scope — Plain-Text ist für automatische Antworten angemessen.

7. **Antwort-Sprache**: Der EMAIL_SYSTEM_PROMPT sagt "Deutsch, es sei denn
   Original ist Englisch". Das ist eine Heuristik — Claude erkennt die Sprache
   der Original-Mail zuverlässig.

8. **Tests mit Anthropic API**: `_generate_draft()` Tests sollten den
   `AnthropicClient` mocken (Mock return_value auf generate()). Keine echten
   API-Calls in Tests.

9. **Plattformhinweis**: Alles hier ist plattformunabhängig (smtplib, email
   sind Python-Standardbibliothek). Kein RPi5-spezifischer Code.

10. **Branch**: `feature/phase-28-email-reply`
