"""Assistant-Mixin: System-Prompt-Aufbau (Phase 106).

Phase 106 (Modul-Entflechtung): aus ``assistant.py`` ausgelagert. Baut den
System-Prompt (Character-/Template-Pfad) inkl. Plugin-Inventar, aktiver
Vorschläge, action_sequence-Hint, plugin-candidate-Hint und Robot-Status.
``_build_system_prompt`` u.a. werden in Tests direkt auf ``Assistant``
aufgerufen (bleiben via Vererbung auflösbar).
"""

from __future__ import annotations

import logging
from datetime import datetime

from elder_berry.core._assistant_base import AssistantMixinBase
from elder_berry.core.prompts import SYSTEM_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class PromptBuilderMixin(AssistantMixinBase):
    """Konstruiert den System-Prompt aus DB-Aktionen, Robot-Status, Plugins."""

    def _build_system_prompt(
        self,
        memory_context: str = "",
        chat_history: str = "",
        smart_context: str = "",
    ) -> str:
        """Generiert System-Prompt – aus CharacterEngine oder Fallback-Template."""
        db_actions = self._actions_db.list_all()
        if db_actions:
            lines = ["Registrierte Aktionen in der Datenbank:"]
            for a in db_actions:
                lines.append(f'- Trigger: "{a.trigger}" → Typ: {a.action_type}')
            action_list = "\n".join(lines)
        else:
            action_list = "Keine zusätzlichen Aktionen in der Datenbank registriert."

        robot_status = self._build_robot_status()
        current_dt = datetime.now().strftime("%A, %d.%m.%Y %H:%M Uhr")

        # Dynamischer Command-Block aus den Handler-Definitionen
        remote_commands = ""
        if self._remote_commands:
            remote_commands = self._remote_commands.get_command_summary()

        # Phase 77.5: Plugin-Inventar-Block fuer Phase-78-Dedupe-Check.
        plugin_inventory = self._build_plugin_inventory_block()

        # Phase 78: aktive Plugin-Vorschlaege + Anweisung fuer den
        # <plugin-candidate>-Block am Antwortende.
        active_proposals = self._build_active_proposals_block()
        candidate_hint = self._build_plugin_candidate_hint()

        # Phase 82 Etappe 2: action_sequence-Hint mit Few-Shots.
        action_sequence_hint = self._build_action_sequence_hint()

        if self._character:
            prompt = self._character.build_system_prompt(
                available_actions=action_list,
                memory_context=memory_context,
                remote_commands=remote_commands,
            )
            prompt = f"Aktuelles Datum und Uhrzeit: {current_dt}\n\n{prompt}"
            mood_context = self._character.get_mood_context()
            if mood_context:
                prompt += f"\n\n{mood_context}"
            if robot_status:
                prompt += f"\n\n{robot_status}"
            if smart_context:
                prompt += f"\n\n{smart_context}"
            if plugin_inventory:
                prompt += f"\n\n{plugin_inventory}"
            if active_proposals:
                prompt += f"\n\n{active_proposals}"
            if action_sequence_hint:
                prompt += f"\n\n{action_sequence_hint}"
            if candidate_hint:
                prompt += f"\n\n{candidate_hint}"
            if chat_history:
                prompt += f"\n\n{chat_history}"
            return prompt

        full_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            action_list=action_list,
            robot_status=robot_status,
            current_datetime=current_dt,
            memory_context=memory_context,
            remote_commands=remote_commands,
            smart_context=smart_context,
        )
        if plugin_inventory:
            full_prompt += f"\n\n{plugin_inventory}"
        if active_proposals:
            full_prompt += f"\n\n{active_proposals}"
        if action_sequence_hint:
            full_prompt += f"\n\n{action_sequence_hint}"
        if candidate_hint:
            full_prompt += f"\n\n{candidate_hint}"
        if chat_history:
            full_prompt += f"\n\n{chat_history}"
        return full_prompt

    # Phase 77.5: Maximalzahl Zeilen im Plugin-Inventar-Block. Bei mehr
    # Plugins wird auf "...(N weitere)" getrimmt -- 30 Zeilen entsprechen
    # heute 24 Plugins + 6 Reserve fuer User-Plugins ohne Promptlaengen-
    # Explosion (Konzept §3.4 / Risiko R2).
    _PLUGIN_INVENTORY_MAX_LINES: int = 30

    def _build_plugin_inventory_block(self) -> str:
        """Baut den "Bereits geladene Plugins"-Block fuer den System-Prompt.

        Phase-78-Voraussetzung: Saleria soll im Dedupe-Check (Self-
        Suggestion) sehen, welche Capabilities bereits implementiert
        sind, damit sie keine Vorschlaege fuer Builtins erzeugt.

        Format:

            [Bereits geladene Plugins (kein Vorschlag wenn Match):
            - <name>: <category>
            ...
            - <name>: <category>]

        Trim: bei mehr als ``_PLUGIN_INVENTORY_MAX_LINES - 1`` Plugin-
        Zeilen wird auf den Header + Top-N + ``... (M weitere)`` gekuerzt
        (Sortierung kommt aus ``load_plugins_with_sources`` -> Priority).
        """
        try:
            from elder_berry.comms.commands.registry import (
                load_plugins_with_sources,
            )

            loaded = load_plugins_with_sources()
        except Exception as exc:
            # Plugin-Registry darf den System-Prompt-Build nicht killen.
            logger.warning("Plugin-Inventar-Block uebersprungen: %s", exc)
            return ""

        if not loaded:
            return ""

        header = "[Bereits geladene Plugins (kein Vorschlag wenn Match):"
        # Header zaehlt mit -- darum -1 fuer die Plugin-Zeilen.
        max_plugin_lines = self._PLUGIN_INVENTORY_MAX_LINES - 1

        plugin_lines = [
            f"- {entry.plugin.name}: {entry.plugin.category}" for entry in loaded
        ]
        if len(plugin_lines) > max_plugin_lines:
            kept = plugin_lines[: max_plugin_lines - 1]
            remaining = len(plugin_lines) - len(kept)
            kept.append(f"- … ({remaining} weitere)")
            plugin_lines = kept

        # Schluss-Klammer ueber die letzte Zeile -- Block bleibt einzeilig
        # parsebar fuer kuenftige Phase-78-Heuristik.
        if plugin_lines:
            plugin_lines[-1] = plugin_lines[-1] + "]"
        return header + "\n" + "\n".join(plugin_lines)

    # Phase 78: Cap auf 10-15 aktive Vorschlaege im System-Prompt.
    # Bei mehr aktiven Vorschlaegen ist die Heuristik selbst das Problem
    # (Threshold zu lasch, Halluzinationen) -- dann nachjustieren statt
    # Cap erhoehen. Siehe Konzept §3.6.
    _ACTIVE_PROPOSALS_MAX_LINES: int = 15

    def _build_active_proposals_block(self) -> str:
        """Baut den "Aktive Plugin-Vorschlaege"-Block fuer den System-Prompt.

        Saleria nutzt diese Liste vor der Erstellung eines neuen
        <plugin-candidate>-Blocks: Wenn die Anfrage zu einem bereits
        offenen Vorschlag passt, soll sie KEINEN neuen Block emittieren
        (Konzept §3.6).

        Format:

            [Aktive Plugin-Vorschlaege (kein neuer Vorschlag wenn Match):
            - <intent>: <title> (<status>)
            ...
            - <intent>: <title> (<status>)]

        Liefert "" wenn kein ProposalStore gesetzt ist oder keine
        aktiven Vorschlaege existieren.
        """
        if self._proposal_store is None:
            return ""
        try:
            active = self._proposal_store.list_active(
                limit=self._ACTIVE_PROPOSALS_MAX_LINES
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Active-Proposals-Block uebersprungen: %s", exc)
            return ""

        if not active:
            return ""

        header = "[Aktive Plugin-Vorschlaege (kein neuer Vorschlag wenn Match):"
        lines = [f"- {p.id}: {p.title} ({p.status})" for p in active]
        if lines:
            lines[-1] = lines[-1] + "]"
        return header + "\n" + "\n".join(lines)

    @staticmethod
    def _build_action_sequence_hint() -> str:
        """Erklaert action_sequence + on_failure-Strategien (Phase 82 Etappe 2).

        Wird unkonditional in den System-Prompt eingefuegt (analog
        ``_build_plugin_candidate_hint``). Saleria entscheidet pro
        Anfrage, ob action_sequence der richtige Action-Typ ist.

        Pflicht laut Konzept ``§5.2``:
          - mindestens ein Few-Shot mit ``on_failure: stop`` und logischer
            Step-Abhaengigkeit (sonst lernt Saleria die ``stop``-Strategie
            nie -- der Pfad ist sonst tot).
          - ein Few-Shot mit ``on_failure: continue`` (heterogene Sequenz).
          - Negativ-Hinweis: nicht fuer 5x denselben Command nutzen --
            dafuer reicht ``remote_command`` mit Newline-separiertem
            ``command``-String, der Quick-Fix splittet automatisch.
        """
        return (
            "Wenn der Nutzer mehrere UNABHAENGIGE Aktionen in einer Anfrage "
            "verlangt ('mach X UND Y UND Z'), bundele sie in EINE Antwort "
            "vom Typ action_sequence:\n"
            '{"action": "action_sequence", "params": {'
            '"steps": [{"action": "remote_command", "params": '
            '{"command": "..."}}, ...], "on_failure": "continue"}, '
            '"response": "Ich erledige das in 3 Schritten."}\n'
            "\n"
            "on_failure-Strategie:\n"
            "- 'continue' (Default): bei einem Step-Fehler laufen die "
            "anderen Steps weiter. Nutze das fuer heterogene Sequenzen, "
            "deren Steps logisch unabhaengig sind.\n"
            "- 'stop': beim ersten Fehler werden die restlichen Steps "
            "uebersprungen. Nutze das, wenn Step N+1 logisch von Step N "
            "abhaengt (sonst macht Step N+1 ohne Step N keinen Sinn).\n"
            "\n"
            "Beispiel (continue, heterogen):\n"
            'User: \'schreib Notiz "Pizza-Rezept Link XY" UND setz '
            'Reminder Samstag 10 Uhr UND erstell Todo "Hefe kaufen"\'\n'
            '{"action": "action_sequence", "params": {"steps": ['
            '{"action": "remote_command", "params": '
            '{"command": "notiz: Pizza-Rezept Link XY"}}, '
            '{"action": "remote_command", "params": '
            '{"command": "erinnere mich am Samstag um 10:00: Pizza"}}, '
            '{"action": "remote_command", "params": '
            '{"command": "todo: Hefe kaufen"}}'
            '], "on_failure": "continue"}, '
            '"response": "Mach ich -- Notiz, Reminder und Todo."}\n'
            "\n"
            "Beispiel (stop, logisch abhaengig):\n"
            'User: \'Trag Termin Mittwoch 14:00 "Zahnarzt" ein UND '
            "erinner mich Mittwoch 13:00 daran'\n"
            '{"action": "action_sequence", "params": {"steps": ['
            '{"action": "remote_command", "params": '
            '{"command": "termin: Zahnarzt Mittwoch 14:00"}}, '
            '{"action": "remote_command", "params": '
            '{"command": "erinnere mich am Mittwoch um 13:00: Zahnarzt"}}'
            '], "on_failure": "stop"}, '
            '"response": "Termin und Reminder zusammen -- wenn der Termin '
            'nicht klappt, lass ich den Reminder weg."}\n'
            "\n"
            "Nutze action_sequence NICHT fuer 5x denselben Command (z.B. "
            "'5 Todos fuer Pizza'). Dafuer reicht EIN remote_command mit "
            "Newline-separiertem command-String -- das System splittet "
            "das automatisch in Einzel-Calls und sammelt die Bilanz.\n"
            "\n"
            "Phase 82.1 -- gleichartige Items innerhalb einer heterogenen "
            "Sequenz: Wenn der Nutzer mehrere gleichartige Items zusammen "
            "mit anderen Aktionen verlangt (z.B. '3 Todos fuer Pizza UND "
            "Notiz UND Reminder'), kannst du wahlweise (a) die Items als "
            "EINZELNE Steps in der Sequenz emittieren, oder (b) die Items "
            "als EINEN Step mit Newline-separiertem command-String "
            "emittieren -- BEIDES funktioniert (das System splittet Multi-"
            "Line auch innerhalb von Steps).\n"
            "\n"
            "Beispiel (Multi-Line in einem Step, kompakter):\n"
            'User: \'3 Todos fuer Pizza UND schreib Notiz "Rezept-Link" '
            "UND setz Reminder Samstag 10 Uhr'\n"
            '{"action": "action_sequence", "params": {"steps": ['
            '{"action": "remote_command", "params": '
            '{"command": "todo: Zutaten kaufen, mittel, Einkauf\\n'
            "todo: Pizzateig vorbereiten, mittel, Kochen\\n"
            'todo: Pizza backen, mittel, Kochen"}}, '
            '{"action": "remote_command", "params": '
            '{"command": "notiz: Rezept-Link"}}, '
            '{"action": "remote_command", "params": '
            '{"command": "erinnere mich am Samstag um 10:00: Pizza"}}'
            '], "on_failure": "continue"}, '
            '"response": "Mach ich -- 3 Todos, Notiz, Reminder."}'
        )

    @staticmethod
    def _build_plugin_candidate_hint() -> str:
        """Anweisung an den LLM zum Erkennen von Plugin-Kandidaten (Konzept §3.4).

        Wird unkonditional in den System-Prompt eingefuegt. Saleria
        entscheidet pro Anfrage, ob der Block sinnvoll ist; der
        Aggregator filtert per Confidence- und Smalltalk-Negativliste
        erneut nach.
        """
        return (
            "Pruefe am Ende deiner Antwort, ob die Anfrage eine wiederkehrende, "
            "automatisierbare Aufgabe sein koennte, die als Plugin sinnvoll waere. "
            "Wenn ja, haenge GENAU EINEN solchen Block ans Antwortende:\n"
            '<plugin-candidate>{"intent":"snake_case_id","title":"Kurzer Titel",'
            '"description":"2-3 Saetze, was die Capability tun wuerde.",'
            '"category":"medien|system|productivity|...","confidence":0.0-1.0}'
            "</plugin-candidate>\n"
            "Wenn nein, lass den Block weg. Smalltalk, Witze, Komplimente, "
            "Wetter-Plauderei sind KEINE Plugin-Kandidaten. Pruefe vorher die "
            "Listen 'Bereits geladene Plugins' und 'Aktive Plugin-Vorschlaege' "
            "-- bei Match keinen neuen Block emittieren."
        )

    def _build_robot_status(self) -> str:
        """Baut Robot-Status-Info für den System-Prompt. Leer wenn kein Robot."""
        if not self._robot:
            return ""
        try:
            if not self._robot.is_online():
                return "Roboter-Status: OFFLINE (nicht erreichbar)"
            parts = ["Roboter-Status: ONLINE"]
            # Phase 102 (#739): Akku-Zeile nur bei aktiver Capability-Flag. Aus
            # (Default) -> kein get_battery()-Call und kein (simulierter)
            # Akku-Stand im System-Prompt.
            if self._robot_battery_enabled:
                battery = self._robot.get_battery()
                parts.append(f"  Akku: {battery.percentage}% ({battery.voltage}V)")
                if battery.is_low:
                    parts.append("  WARNUNG: Akku niedrig! Zur Ladestation fahren.")
                if battery.is_charging:
                    parts.append("  Akku wird geladen.")
            return "\n".join(parts)
        except Exception as e:
            logger.debug("Robot-Status Abfrage fehlgeschlagen: %s", e)
            return "Roboter-Status: OFFLINE (Abfrage fehlgeschlagen)"
