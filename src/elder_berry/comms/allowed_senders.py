"""Lade- und Parse-Logik für ``matrix_allowed_senders`` (Phase 57.4).

Die Funktion ``load_allowed_senders`` liest den SecretStore-Key
``matrix_allowed_senders``, parst die komma-getrennte Sender-Liste und
gibt ein ``frozenset[str]`` zurück. Fehlt der Eintrag, ist er leer oder
enthält nur Trennzeichen, wirft die Funktion ``ValueError``.

**Phase 57.4 – strikt fail-closed.** Die frühere Design-Entscheidung
aus Phase 32 („leere Liste = kein Filter") ist bewusst zurückgenommen,
weil ein Single-User-Matrix-Bot ohne Sender-Whitelist jede Person im
Matrix-Raum als steuerungsberechtigt einstuft. Der Caller (Start-Skript
oder Setup-Prüfung) fängt die Exception ab und bricht den Bridge-Start
ab.

Dieses Modul hält keine Logging-Config-Side-Effects und ist deshalb
frei importierbar aus Tests, die den Root-Logger sauber halten müssen.
"""
from __future__ import annotations

from typing import Protocol


class _SecretStoreLike(Protocol):
    """Minimales Interface – SecretStore oder Mock."""

    def get_or_none(self, key: str) -> str | None: ...


def load_allowed_senders(secret_store: _SecretStoreLike) -> frozenset[str]:
    """Lädt ``matrix_allowed_senders`` aus dem SecretStore.

    Parameters
    ----------
    secret_store:
        Objekt mit ``get_or_none(key) -> str | None``.

    Returns
    -------
    frozenset[str]
        Nicht-leere, bereinigte Menge der Matrix-User-IDs.

    Raises
    ------
    ValueError
        Wenn der Eintrag fehlt, leer ist, nur Whitespace oder nur
        Trennzeichen enthält.
    """
    raw_senders = secret_store.get_or_none("matrix_allowed_senders")
    if raw_senders:
        sender_list = [s.strip() for s in raw_senders.split(",") if s.strip()]
        if sender_list:
            return frozenset(sender_list)
    raise ValueError(
        "matrix_allowed_senders ist nicht gesetzt, leer oder enthält "
        "nur Trennzeichen",
    )
