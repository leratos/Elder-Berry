"""CommandHandler ABC – Basisklasse für domänenspezifische Command-Handler.

Jeder Handler registriert seine Patterns und Keywords und kann
Commands parsen und ausführen.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CommandResult:
    """Ergebnis eines ausgeführten Remote-Commands."""

    command: str
    """Name des erkannten Commands (z.B. 'status', 'screenshot')."""

    success: bool
    """True wenn der Command erfolgreich ausgeführt wurde."""

    text: str | None = None
    """Text-Antwort für den Nutzer (z.B. Systemstatus)."""

    history_text: str | None = None
    """Alternativer Text für die Chat-History (z.B. Mail-Body für LLM-Kontext).
    Wenn gesetzt, wird dieser statt `text` in der History gespeichert."""

    image_path: Path | None = None
    """Pfad zum generierten Bild (z.B. Screenshot-PNG)."""

    file_path: Path | None = None
    """Pfad zur Datei die gesendet werden soll (z.B. PDF)."""

    file_paths: list[Path] = field(default_factory=list)
    """Mehrere Dateien zum Senden (z.B. Mail-Anhänge)."""

    restart: bool = False
    """True wenn der Bot nach diesem Command neu starten soll."""

    pending_confirmation: bool = False
    """True wenn diese Aktion eine Nutzer-Bestätigung erfordert.
    Die Bridge erstellt dann eine PendingAction aus pending_data."""

    pending_data: dict[str, Any] | None = None
    """Daten für die PendingAction (z.B. Draft-Text, Empfänger).
    Nur relevant wenn pending_confirmation=True."""


@dataclass
class PatternMatch:
    """Ergebnis eines Pattern-Checks."""

    command: str
    """Normalisierter Command-Name."""

    use_original_text: bool = False
    """True wenn parse_command den Originaltext (case-sensitiv) statt
    normalisierten Text verwenden soll (z.B. bei Pfad-Erkennung)."""


class CommandHandler(ABC):
    """Basisklasse für domänenspezifische Command-Handler.

    Jeder Handler definiert:
    - simple_commands: Set von Commands ohne Parameter (exakter Match)
    - patterns: Liste von (Pattern, command_name, use_original) Tuples
    - keywords: Dict von command_name → Keyword-Liste
    - execute(): Führt einen erkannten Command aus
    """

    @property
    def simple_commands(self) -> set[str]:
        """Commands ohne Parameter (exakter Match auf normalized text)."""
        return set()

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        """Regex-Patterns für parametrierte Commands.

        Returns:
            Liste von (compiled_pattern, command_name, use_original_text, use_search).
            use_original_text=True wenn der Pattern auf den Originaltext
            (nicht normalisierten) geprüft werden soll.
            use_search=True für pattern.search() statt pattern.match().
        """
        return []

    @property
    def keywords(self) -> dict[str, list[str]]:
        """Keyword-Map für natürliche Sprache.

        Returns:
            Dict von command_name → Liste von Keywords.
        """
        return {}

    @property
    def command_descriptions(self) -> list[str]:
        """Kompakte Beschreibungen aller Commands dieses Handlers.

        Wird von RemoteCommandHandler.get_command_summary() genutzt um
        den dynamischen Command-Block im System-Prompt zu generieren.

        Returns:
            Liste von Beschreibungs-Strings, z.B.
            ["mails: Ungelesene E-Mails anzeigen",
             "mail suche <begriff>: E-Mails durchsuchen"]
        """
        return []

    @abstractmethod
    def execute(self, command: str, raw_text: str) -> CommandResult:
        """Führt einen erkannten Command aus.

        Args:
            command: Normalisierter Command-Name.
            raw_text: Originaler Nachrichtentext (für Parameter-Extraktion).

        Returns:
            CommandResult mit Ergebnis.
        """
