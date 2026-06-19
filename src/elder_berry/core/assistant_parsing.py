"""Assistant-Mixin: Parsing der LLM-Antwort (Phase 106).

Phase 106 (Modul-Entflechtung): aus ``assistant.py`` ausgelagert. Extrahiert
den ``<plugin-candidate>``-Block und parst das Action-JSON. Reine
Text-Verarbeitung; ``_find_last_json_object``/``_extract_plugin_candidate``
werden in Tests direkt auf ``Assistant`` aufgerufen (bleiben via Vererbung
auflösbar).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, cast

from elder_berry.core._assistant_base import AssistantMixinBase

logger = logging.getLogger(__name__)


class ResponseParserMixin(AssistantMixinBase):
    """Parsen von Plugin-Candidate-Block und Action-JSON aus dem LLM-Output."""

    # Phase 78: Regex zum Extrahieren des <plugin-candidate>-JSON-Blocks.
    # Greedy-Stop am ersten </plugin-candidate>; ein Block pro Antwort.
    _PLUGIN_CANDIDATE_RE = re.compile(
        r"<plugin-candidate>\s*(\{.*?\})\s*</plugin-candidate>",
        re.DOTALL,
    )

    @classmethod
    def _extract_plugin_candidate(cls, text: str) -> tuple[str, dict[str, Any] | None]:
        """Schneidet einen <plugin-candidate>-Block aus dem LLM-Output.

        Returns:
            (bereinigter_text, candidate_dict_oder_None).
            candidate_dict enthaelt mindestens "intent", "title",
            "confidence" und (sofern vom LLM geliefert) "description"
            sowie "category". None wenn kein Block gefunden, JSON kaputt
            oder Pflichtfelder fehlen.
        """
        match = cls._PLUGIN_CANDIDATE_RE.search(text)
        if match is None:
            return text, None

        cleaned = (text[: match.start()] + text[match.end() :]).rstrip()
        raw_json = match.group(1)
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.warning("plugin-candidate JSON kaputt: %s -- %r", exc, raw_json)
            return cleaned, None

        if not isinstance(data, dict):
            logger.warning("plugin-candidate kein dict: %r", data)
            return cleaned, None

        intent = data.get("intent")
        title = data.get("title")
        confidence = data.get("confidence")
        if not isinstance(intent, str) or not intent.strip():
            logger.debug("plugin-candidate ohne intent verworfen")
            return cleaned, None
        if not isinstance(title, str) or not title.strip():
            logger.debug("plugin-candidate ohne title verworfen")
            return cleaned, None
        if not isinstance(confidence, (int, float)):
            logger.debug("plugin-candidate ohne numerische confidence verworfen")
            return cleaned, None

        return cleaned, data

    def _parse_llm_response(self, raw: str) -> dict[str, Any]:
        """
        Parst JSON aus der LLM-Antwort.

        Drei Versuche, in dieser Reihenfolge:

        1. Der gesamte String als JSON (cleaner LLM-Output).
        2. Das *letzte* vollstaendige top-level JSON-Object im String.
           LLMs reflektieren manchmal laut nach -- Klartext und mehrere
           JSON-Objects gemischt ('Wait, ich sollte das anders machen...
           {neue-Antwort}'). Die letzte JSON ist typischerweise die
           endgueltige Antwort.
        3. Erstes ``{`` bis letztes ``}`` (alter Fallback, fuer Faelle
           wo das einzige JSON von Klartext umschlossen ist).

        ``strict=False`` toleriert Tab/LF/CR innerhalb von JSON-string-
        values -- LLMs liefern Markdown-Antworten oft mit echten
        Newlines statt ``\\n``-Escape-Sequences.
        """
        # Versuch 1: Gesamter String
        try:
            return cast(dict[str, Any], json.loads(raw, strict=False))
        except json.JSONDecodeError:
            pass

        # Versuch 2: letztes top-level JSON-Object (LLM-Reflexionsfall)
        last_obj = self._find_last_json_object(raw)
        if last_obj is not None:
            return last_obj

        # Versuch 3: erstes { bis letztes } (legacy fallback)
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return cast(
                    dict[str, Any],
                    json.loads(raw[start : end + 1], strict=False),
                )
            except json.JSONDecodeError:
                pass

        # Fallback: Rohe Antwort als Text. raw[:500] ins Log, damit man
        # sieht WARUM der Parser kapituliert (Trailing-Plugin-Block,
        # exotische Escapes, ueberhaupt kein JSON, ...).
        logger.warning(
            "LLM-Antwort konnte nicht als JSON geparst werden: %r",
            raw[:500],
        )
        return {"action": None, "params": {}, "response": raw}

    @staticmethod
    def _find_last_json_object(raw: str) -> dict[str, Any] | None:
        """Sucht das letzte vollstaendige top-level JSON-Object im String.

        Scannt von vorne mit ``json.JSONDecoder.raw_decode``, sammelt
        alle erfolgreich geparsten JSON-Objects, gibt das letzte
        zurueck. O(n) durch den String.

        Hintergrund (Live-Befund 2026-05-08): Saleria emittierte zwei
        JSON-Antworten mit einer ``Wait, ich sollte...``-Reflexion
        dazwischen. ``rfind('}')`` greift dann ueber beide JSONs UND
        den Klartext und scheitert. Diese Methode liefert die zweite
        (finale) JSON.
        """
        decoder = json.JSONDecoder(strict=False)
        last: dict[str, Any] | None = None
        pos = 0
        n = len(raw)
        while pos < n:
            brace = raw.find("{", pos)
            if brace == -1:
                break
            try:
                obj, consumed = decoder.raw_decode(raw[brace:])
            except json.JSONDecodeError:
                pos = brace + 1
                continue
            if isinstance(obj, dict):
                last = cast(dict[str, Any], obj)
            pos = brace + consumed
        return last
