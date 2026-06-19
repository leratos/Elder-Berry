"""comms/handlers – Mixin-Module für die comms-Handler-Familie (Phase 106).

Enthält die nach Verantwortung geschnittenen Mixins für den
``ConfirmationHandler`` (und in späteren Etappen für den
``BridgeMessageHandler``). Die öffentlichen Klassen bleiben in ihren
Ursprungsmodulen (``confirmation_handlers.py`` / ``message_handlers.py``) und
erben die Mixins von hier – die öffentlichen Importpfade ändern sich nicht.
"""
