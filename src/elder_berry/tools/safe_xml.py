"""Gehaerteter XML-Parser fuer externe Server-Antworten (Phase 103, S2).

defusedxml blockt per Default Entity-Expansion (billion laughs) und externe
Entities (XXE), aber NICHT die DOCTYPE-/DTD-Deklaration selbst
(``forbid_dtd`` ist defaultmaessig False). WebDAV/CardDAV-Multistatus-Antworten
enthalten nie eine DTD, daher setzen wir ``forbid_dtd=True`` -- damit ist die in
Phase 103 zugesagte DTD-Haertung tatsaechlich wirksam.

Zentral, damit alle externen XML-Parses (carddav_sync, nextcloud_files) exakt
dieselbe Haertungs-Konfiguration nutzen und es nur eine Stelle zum Tunen gibt.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from defusedxml.ElementTree import fromstring as _defused_fromstring


def safe_fromstring(text: str) -> ET.Element:
    """Parst externes XML gehaertet (Entity-Expansion / XXE / DTD geblockt).

    Raises:
        defusedxml.common.DefusedXmlException: bei boesartigem Input
            (EntitiesForbidden / ExternalReferenceForbidden / DTDForbidden).
        xml.etree.ElementTree.ParseError: bei syntaktisch kaputtem XML.
    """
    element: ET.Element = _defused_fromstring(text, forbid_dtd=True)
    return element
