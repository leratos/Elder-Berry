"""Mixin-Subpaket für den WeatherCommandHandler (Phase 106).

Die ``_cmd_*``-Implementierung ist nach Verantwortung in Mixins geschnitten
(Core-Wetter / Reminder / Recurring / Misc). Der eigentliche Plugin-Handler
``WeatherCommandHandler`` bleibt in ``comms/commands/weather_commands.py`` und
erbt diese Mixins – der Plugin-Name, die ``patterns``-Tabelle, ``priority`` und
``source_path`` bleiben dadurch unverändert (dieses Subpaket wird vom
Registry-Glob ``*_commands.py`` bewusst NICHT erfasst).
"""
