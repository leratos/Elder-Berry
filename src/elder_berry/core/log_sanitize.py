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
    """Ersetzt CR/LF in ``value`` durch literale ``\\r``/``\\n``-Tokens.

    Akzeptiert beliebige Objekte und konvertiert sie via ``str()``. ``None``
    wird zu ``"None"``. Unicode bleibt erhalten -- nur die beiden
    Zeilenumbruch-Codepunkte werden ersetzt, weil nur sie das Log-Format
    aufbrechen.
    """
    return str(value).replace("\r", "\\r").replace("\n", "\\n")
