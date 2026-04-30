"""PathGuard -- Allow-List-basierte Pfad-Validierung gegen Path-Traversal.

Wird von Matrix-Commands genutzt, die lokale Dateipfade aus User-Eingaben
verarbeiten (Dokument-Zusammenfassung, PDF-Verarbeitung). Verhindert, dass
ein Matrix-Sender (auch allowlisted) beliebige Dateien lesen kann (id_rsa,
.env, SecretStore-Backups, ...).

Validierungs-Strategie:
1. Pfad mit ``resolve(strict=True)`` aufloesen (Symlinks folgen, FileNotFound
   bei nicht-existenten Dateien).
2. Gegen Liste erlaubter Basis-Verzeichnisse pruefen (``is_relative_to``).
3. Bei Verletzung: ``PermissionError`` und Audit-Log via
   ``elder_berry.security``-Logger (landet in ``logs/security.log``).

Verletzungen werden NICHT an den Matrix-Sender zurueckgegeben (kein
Pfad-Echo) -- der Caller liefert eine generische "Zugriff verweigert"-Antwort.

Konfiguration:
- Defaults via ``PathGuard.default()``: ~/Documents, ~/Downloads, ~/Desktop,
  tempfile.gettempdir() (fuer Nextcloud-Cache), aktuelles Arbeitsverzeichnis
  (fuer Tests + lokale Nutzung).
- Override via Env-Var ``EB_ALLOWED_PATHS`` (os.pathsep-getrennt:
  ``;`` auf Windows, ``:`` auf Unix). Wenn gesetzt, ersetzt die Defaults
  vollstaendig.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)
security_logger = logging.getLogger("elder_berry.security")

EB_ALLOWED_PATHS_ENV = "EB_ALLOWED_PATHS"


class PathGuard:
    """Validiert Pfade gegen eine Allow-Liste erlaubter Basis-Verzeichnisse.

    Eine PathGuard-Instanz haelt eine Liste vorab aufgeloester Basis-Pfade.
    ``validate(path)`` pruft, ob der uebergebene Pfad nach Symlink-Aufloesung
    in einem der erlaubten Verzeichnisse liegt.

    Beispiel::

        guard = PathGuard.default()
        try:
            real_path = guard.validate("C:\\Users\\me\\Documents\\report.pdf")
        except PermissionError:
            return "Zugriff verweigert."
        except FileNotFoundError:
            # Datei existiert nicht -- ggf. Fallback (z.B. Nextcloud)
            ...
    """

    def __init__(self, allowed_bases: Iterable[Path | str]) -> None:
        normalized: list[Path] = []
        for base in allowed_bases:
            try:
                resolved = Path(base).expanduser().resolve(strict=False)
            except (OSError, ValueError) as exc:
                logger.warning(
                    "PathGuard: Basis-Pfad konnte nicht aufgeloest werden (%s): %s",
                    base,
                    exc,
                )
                continue
            normalized.append(resolved)

        if not normalized:
            raise ValueError(
                "PathGuard: mindestens ein gueltiges Basis-Verzeichnis erforderlich."
            )

        self._allowed_bases: tuple[Path, ...] = tuple(normalized)

    @property
    def allowed_bases(self) -> tuple[Path, ...]:
        """Gibt die normalisierten Basis-Pfade zurueck (read-only)."""
        return self._allowed_bases

    def validate(self, path: Path | str) -> Path:
        """Validiert einen Pfad und gibt den aufgeloesten Pfad zurueck.

        Args:
            path: Zu pruefender Pfad (str oder Path).

        Returns:
            Aufgeloester ``Path`` (Symlinks aufgeloest), garantiert innerhalb
            eines erlaubten Basis-Verzeichnisses.

        Raises:
            PermissionError: Pfad liegt ausserhalb der erlaubten Bases ODER
                ist leer/None. Der konkrete Pfad wird intern via
                Security-Logger geloggt, aber nicht im Exception-Text echoed.
            FileNotFoundError: Datei existiert nicht. Caller darf das nutzen,
                um einen Remote-Fallback (z.B. Nextcloud) zu versuchen.
        """
        if not path:
            security_logger.warning(
                "PathGuard rejected empty path",
            )
            raise PermissionError("Pfad ist leer.")

        path_str = str(path)

        try:
            resolved = Path(path).expanduser().resolve(strict=True)
        except FileNotFoundError:
            # Bewusst durchreichen: Caller darf NC-Fallback versuchen.
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            # RuntimeError: Symlink-Loop. OSError: z.B. zu langer Pfad.
            security_logger.warning(
                "PathGuard rejected unresolvable path: %r (%s)",
                path_str,
                exc,
            )
            raise PermissionError("Pfad konnte nicht aufgeloest werden.") from exc

        for base in self._allowed_bases:
            try:
                if resolved.is_relative_to(base):
                    return resolved
            except ValueError:
                # is_relative_to wirft auf Win bei Drive-Mismatch ValueError.
                continue

        security_logger.warning(
            "PathGuard rejected path outside allowed bases: %r (resolved=%r, bases=%r)",
            path_str,
            str(resolved),
            [str(b) for b in self._allowed_bases],
        )
        raise PermissionError(
            "Pfad liegt ausserhalb erlaubter Verzeichnisse.",
        )

    @classmethod
    def default(cls) -> PathGuard:
        """Erzeugt einen PathGuard mit Standard-Allow-Liste.

        Reihenfolge:
        1. Wenn ``EB_ALLOWED_PATHS`` gesetzt ist -> ersetzt Defaults
           vollstaendig (os.pathsep-getrennt).
        2. Sonst: ~/Documents, ~/Downloads, ~/Desktop,
           tempfile.gettempdir(), CWD.

        Nicht-existente Pfade werden uebersprungen (mit Warning), damit
        z.B. ein fehlendes ~/Desktop nicht den ganzen Guard kippt.
        """
        env_value = os.environ.get(EB_ALLOWED_PATHS_ENV)
        if env_value:
            raw_paths = [p.strip() for p in env_value.split(os.pathsep) if p.strip()]
            return cls(raw_paths)

        home = Path.home()
        candidates: list[Path] = [
            home / "Documents",
            home / "Downloads",
            home / "Desktop",
            Path(tempfile.gettempdir()),
            Path.cwd(),
        ]

        # Nur existierende Pfade aufnehmen -- PathGuard.__init__ verlangt
        # mindestens einen gueltigen Pfad. tempfile.gettempdir() + CWD sind
        # praktisch immer vorhanden, also greift die ValueError-Sperre nicht.
        existing: list[Path] = []
        for candidate in candidates:
            try:
                if candidate.exists():
                    existing.append(candidate)
            except OSError:
                continue

        return cls(existing)
