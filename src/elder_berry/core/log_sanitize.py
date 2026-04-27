"""Log-Injection-Schutz: CR/LF aus User-Input strippen vor dem Logging.

Verhindert Log-Forgery -- ein Angreifer schmuggelt ``\\n`` in ein Feld
(Hostname, Key-Name, URL), das spaeter geloggt wird, und faelscht so
zusaetzliche Log-Zeilen, um Audit-Logs zu manipulieren oder Monitoring-
Alerts zu verwirren.

Verwendung an JEDER Stelle, wo User-Input direkt oder indirekt in einen
``logger.*``-Call fliesst (z.B. via ``%s``-Format, f-String, oder
formatierte Exception-Message).
"""

from __future__ import annotations


def safe_log(value: object) -> str:
    """Entfernt CR/LF in ``value`` vor dem Logging.

    Akzeptiert beliebige Objekte und konvertiert sie via ``str()``. ``None``
    wird zu ``"None"``. Unicode bleibt erhalten -- nur die beiden
    Zeilenumbruch-Codepunkte werden komplett entfernt.

    Hinweis: Wir loeschen die Zeilenumbrueche (statt sie als ``\\r``/``\\n``
    zu escapen), weil CodeQL diesen Delete-Pattern als log-injection
    Sanitizer erkennt. Forensisch leichter Verlust (man sieht nicht mehr,
    dass der Input urspruenglich Newlines hatte), dafuer schliesst
    CodeQL die log-injection Alerts automatisch.
    """
    return str(value).replace("\r", "").replace("\n", "")
