"""BriefingModeProvider – schmaler Stub für den formellen Briefing-Modus (83.6).

ARCHITEKTUR-FALLE (bewusst dokumentiert): Die
:class:`~elder_berry.avatar.idle_policy.IdleBehaviorPolicy` lebt auf dem **RPi5**,
der :class:`~elder_berry.comms.briefing_scheduler.BriefingScheduler` im **Bot**
(``comms/``). Der Scheduler hält keinen „mode"-State, sondern sendet nur zur
konfigurierten Uhrzeit einen Text – es gibt heute **keinen** Bot→RPi5-Kanal für
„formell". Dieser Provider friert die Schnittstelle ein; der Default
(:class:`CasualBriefingModeProvider`) liefert immer ``casual`` → das Verhalten
bleibt unverändert. Das echte Bot→RPi5-Briefing-Mode-Wiring (z. B. ein
zusätzliches REST-Signal) ist eine **Folgephase** und hier bewusst out-of-scope.

Im formellen Modus dämpft die Policy das Idle-Verhalten (§3.6): Frequenz −50 %,
nur ``soft_close`` als Idle-Aktion (``surprise``/``smile`` ausgeblendet).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BriefingModeProvider(ABC):
    """Sagt, ob gerade ein formelles Briefing läuft (Frame-genauer Lese-Zugriff)."""

    @abstractmethod
    def is_formal(self) -> bool:
        """``True`` während eines formellen Briefings, sonst ``False`` (casual)."""


class CasualBriefingModeProvider(BriefingModeProvider):
    """Default-Provider: immer casual.

    Das echte Bot→RPi5-Briefing-Signal ist eine Folgephase (siehe Modul-Docstring);
    bis dahin verhält sich die Idle-Policy unverändert (kein formeller Modus).
    """

    def is_formal(self) -> bool:
        return False
