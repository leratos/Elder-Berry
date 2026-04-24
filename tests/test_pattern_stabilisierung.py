"""Tests fuer Phase 47: Befehlsmuster-Stabilisierung.

Reine Pattern-Tests (keine Mocks, kein Netzwerk).
Prueft sowohl neue Varianten als auch Rueckwaertskompatibilitaet.
"""


# ---------------------------------------------------------------------------
# system_commands – VOLUME_PATTERN
# ---------------------------------------------------------------------------
from elder_berry.comms.commands.system_commands import VOLUME_PATTERN


class TestVolumePattern:
    """VOLUME_PATTERN: Anker + 'auf'-Syntax."""

    # --- bestehende Eingaben (Regression) ---
    def test_volume_50(self):
        assert VOLUME_PATTERN.match("volume 50")

    def test_vol_75(self):
        assert VOLUME_PATTERN.match("vol 75")

    def test_lautstaerke_30(self):
        assert VOLUME_PATTERN.match("lautstärke 30")

    def test_lautstarke_30(self):
        assert VOLUME_PATTERN.match("lautstarke 30")

    # --- neue Varianten ---
    def test_lautstaerke_auf_70(self):
        m = VOLUME_PATTERN.match("lautstärke auf 70")
        assert m
        assert m.group(1) == "70"

    def test_stell_lautstaerke_auf_50(self):
        m = VOLUME_PATTERN.match("stell lautstärke auf 50")
        assert m
        assert m.group(1) == "50"

    def test_stell_die_lautstaerke_auf_80(self):
        m = VOLUME_PATTERN.match("stell die lautstärke auf 80")
        assert m
        assert m.group(1) == "80"

    # --- darf NICHT matchen (Risiko-Fix) ---
    def test_no_match_in_sentence(self):
        """Satz der zufaellig 'volume 50' enthaelt darf nicht matchen."""
        assert not VOLUME_PATTERN.match("bitte stell volume 50 ein danke")

    def test_no_match_random_text(self):
        assert not VOLUME_PATTERN.match("ich brauche volume 50 dB")


# ---------------------------------------------------------------------------
# mail_commands – MAIL_DELETE_PATTERN
# ---------------------------------------------------------------------------
from elder_berry.comms.commands.mail_commands import MAIL_DELETE_PATTERN


class TestMailDeletePattern:
    """MAIL_DELETE_PATTERN: neue Varianten + Regression."""

    # --- bestehende Eingaben ---
    def test_mail_loeschen_5(self):
        m = MAIL_DELETE_PATTERN.match("mail löschen #5")
        assert m
        assert m.group(1) == "5"

    def test_mails_loeschen_3(self):
        m = MAIL_DELETE_PATTERN.match("mails löschen #3")
        assert m

    def test_loesche_mail_123(self):
        m = MAIL_DELETE_PATTERN.match("lösche mail #123")
        assert m
        assert m.group(2) == "123"

    def test_loesche_die_mail(self):
        assert MAIL_DELETE_PATTERN.match("lösche die mail")

    def test_loesche_die_letzte_mail(self):
        assert MAIL_DELETE_PATTERN.match("lösche die letzte mail")

    # --- neue Varianten ---
    def test_mail_5_loeschen(self):
        """'mail #5 löschen' (ID dann Verb) war eine Luecke."""
        m = MAIL_DELETE_PATTERN.match("mail #5 löschen")
        assert m
        assert m.group(3) == "5"

    def test_mail_5_loeschen_ohne_hash(self):
        m = MAIL_DELETE_PATTERN.match("mail 5 löschen")
        assert m
        assert m.group(3) == "5"

    def test_mail_42_entfernen(self):
        m = MAIL_DELETE_PATTERN.match("mail 42 entfernen")
        assert m
        assert m.group(3) == "42"

    def test_loesche_mail_ohne_hash(self):
        m = MAIL_DELETE_PATTERN.match("lösche mail 5")
        assert m
        assert m.group(2) == "5"


# ---------------------------------------------------------------------------
# harmony_commands – ACTIVITY_ON, ALL_OFF, VOLUME
# ---------------------------------------------------------------------------
from elder_berry.comms.commands.harmony_commands import (
    ACTIVITY_ON_PATTERN,
    ALL_OFF_PATTERN,
    VOLUME_DOWN_PATTERN,
    VOLUME_UP_PATTERN,
)


class TestActivityOnPattern:
    """ACTIVITY_ON_PATTERN: neue 'schalte ... ein' Varianten."""

    # --- bestehende Eingaben ---
    def test_tv_an(self):
        assert ACTIVITY_ON_PATTERN.match("tv an")

    def test_fernsehen_an(self):
        assert ACTIVITY_ON_PATTERN.match("fernsehen an")

    def test_starte_musik_an(self):
        assert ACTIVITY_ON_PATTERN.match("starte musik an")

    # --- neue Varianten ---
    def test_schalte_tv_ein(self):
        m = ACTIVITY_ON_PATTERN.match("schalte tv ein")
        assert m

    def test_schalte_den_tv_an(self):
        m = ACTIVITY_ON_PATTERN.match("schalte den tv an")
        assert m

    def test_mach_musik_an(self):
        m = ACTIVITY_ON_PATTERN.match("mach musik an")
        assert m

    def test_starte_tv(self):
        """'starte tv' ohne 'an' soll auch funktionieren."""
        m = ACTIVITY_ON_PATTERN.match("starte tv")
        assert m

    def test_bitte_tv_an(self):
        assert ACTIVITY_ON_PATTERN.match("bitte tv an")

    # --- darf NICHT matchen ---
    def test_starte_chrome_no_match(self):
        """Nicht-Aktivitaeten duerfen nicht matchen."""
        assert not ACTIVITY_ON_PATTERN.match("starte chrome")


class TestAllOffPattern:
    """ALL_OFF_PATTERN: neue Synonyme."""

    # --- bestehende Eingaben ---
    def test_alles_aus(self):
        assert ALL_OFF_PATTERN.match("alles aus")

    def test_harmony_aus(self):
        assert ALL_OFF_PATTERN.match("harmony aus")

    def test_schalte_alles_aus(self):
        assert ALL_OFF_PATTERN.match("schalte alles aus")

    # --- neue Varianten ---
    def test_mach_alles_aus(self):
        assert ALL_OFF_PATTERN.match("mach alles aus")

    def test_ausschalten(self):
        assert ALL_OFF_PATTERN.match("ausschalten")

    def test_alles_ausschalten(self):
        assert ALL_OFF_PATTERN.match("alles ausschalten")

    def test_bitte_alles_aus(self):
        assert ALL_OFF_PATTERN.match("bitte alles aus")


class TestHarmonyVolumePattern:
    """Harmony Volume: 'bitte'-Prefix."""

    def test_bitte_lauter(self):
        assert VOLUME_UP_PATTERN.match("bitte lauter")

    def test_bitte_leiser(self):
        assert VOLUME_DOWN_PATTERN.match("bitte leiser")

    def test_bitte_mach_lauter(self):
        assert VOLUME_UP_PATTERN.match("bitte mach lauter")

    # --- bestehende Eingaben ---
    def test_lauter(self):
        assert VOLUME_UP_PATTERN.match("lauter")

    def test_mach_leiser(self):
        assert VOLUME_DOWN_PATTERN.match("mach leiser")


# ---------------------------------------------------------------------------
# weather_commands – WEATHER_PATTERN, WEATHER_LOCATION_PATTERN
# ---------------------------------------------------------------------------
from elder_berry.comms.commands.weather_commands import (
    WEATHER_LOCATION_PATTERN,
    WEATHER_PATTERN,
)


class TestWeatherPattern:
    """WEATHER_PATTERN: uebermorgen + Regression."""

    # --- bestehende Eingaben ---
    def test_wetter_morgen(self):
        assert WEATHER_PATTERN.match("wetter morgen")

    def test_wetter_heute(self):
        assert WEATHER_PATTERN.match("wetter heute")

    def test_wetter_woche(self):
        assert WEATHER_PATTERN.match("wetter woche")

    def test_wetter_3(self):
        m = WEATHER_PATTERN.match("wetter 3")
        assert m
        assert m.group(2) == "3"

    # --- neue Varianten ---
    def test_wetter_uebermorgen(self):
        m = WEATHER_PATTERN.match("wetter übermorgen")
        assert m
        assert m.group(1) == "übermorgen"

    def test_wetter_uebermorgen_ascii(self):
        m = WEATHER_PATTERN.match("wetter uebermorgen")
        assert m


class TestWeatherLocationPattern:
    """WEATHER_LOCATION_PATTERN: Ort ohne 'in'."""

    # --- bestehende Eingaben ---
    def test_wetter_in_leipzig(self):
        m = WEATHER_LOCATION_PATTERN.search("wetter in Leipzig")
        assert m
        assert m.group(1) == "Leipzig"

    def test_wetter_in_berlin_morgen(self):
        m = WEATHER_LOCATION_PATTERN.search("wetter in Berlin morgen")
        assert m
        assert m.group(1) == "Berlin"

    # --- neue Varianten ---
    def test_wetter_berlin(self):
        """'wetter Berlin' ohne 'in' soll matchen."""
        m = WEATHER_LOCATION_PATTERN.search("wetter Berlin")
        assert m
        city = m.group(1) or m.group(2)
        assert city and "Berlin" in city

    def test_wetter_new_york(self):
        """Ortsname mit Leerzeichen."""
        m = WEATHER_LOCATION_PATTERN.search("wetter New York")
        assert m
        city = m.group(1) or m.group(2)
        assert city and "New York" in city

    # --- darf NICHT matchen ---
    def test_wetter_morgen_no_location(self):
        """'wetter morgen' darf nicht als Ort 'morgen' erkannt werden."""
        m = WEATHER_LOCATION_PATTERN.search("wetter morgen")
        # Wenn match: Gruppe muss leer sein oder darf nicht 'morgen' enthalten
        if m:
            city = m.group(1) or m.group(2) or ""
            assert city.lower() != "morgen"


# ---------------------------------------------------------------------------
# process_commands – START_PROCESS_PATTERN
# ---------------------------------------------------------------------------
from elder_berry.comms.commands.process_commands import (
    KILL_PROCESS_PATTERN,
    START_PROCESS_PATTERN,
)


class TestStartProcessPattern:
    """START_PROCESS_PATTERN: Leerzeichen im Namen + Harmony-Schutz."""

    # --- bestehende Eingaben ---
    def test_starte_chrome(self):
        m = START_PROCESS_PATTERN.match("starte chrome")
        assert m
        assert m.group(1).strip() == "chrome"

    def test_open_firefox(self):
        assert START_PROCESS_PATTERN.match("open firefox")

    # --- neue Varianten ---
    def test_starte_visual_studio_code(self):
        m = START_PROCESS_PATTERN.match("starte Visual Studio Code")
        assert m
        assert m.group(1).strip() == "Visual Studio Code"

    def test_oeffne_notepad_plus_plus(self):
        m = START_PROCESS_PATTERN.match("öffne notepad++")
        assert m

    # --- Harmony-Schutz: darf NICHT matchen ---
    def test_starte_tv_no_match(self):
        """'starte tv' muss an Harmony gehen, nicht an Process."""
        assert not START_PROCESS_PATTERN.match("starte tv")

    def test_starte_fernsehen_no_match(self):
        assert not START_PROCESS_PATTERN.match("starte fernsehen")

    def test_starte_musik_no_match(self):
        assert not START_PROCESS_PATTERN.match("starte musik")

    def test_starte_tv_an_no_match(self):
        assert not START_PROCESS_PATTERN.match("starte tv an")


class TestKillProcessPattern:
    """KILL_PROCESS_PATTERN: Leerzeichen im Namen."""

    def test_kill_blender(self):
        assert KILL_PROCESS_PATTERN.match("kill blender")

    def test_beende_visual_studio(self):
        m = KILL_PROCESS_PATTERN.match("beende Visual Studio")
        assert m
        assert m.group(1).strip() == "Visual Studio"


# ---------------------------------------------------------------------------
# contact_commands – CONTACT_FIELD_QUERY_PATTERN
# ---------------------------------------------------------------------------
from elder_berry.comms.commands.contact_commands import CONTACT_FIELD_QUERY_PATTERN


class TestContactFieldQueryPattern:
    """CONTACT_FIELD_QUERY_PATTERN: Geburtstag-Varianten."""

    # --- bestehende Eingaben ---
    def test_wann_hat_lisa_geburtstag(self):
        m = CONTACT_FIELD_QUERY_PATTERN.match("wann hat Lisa geburtstag")
        assert m
        assert m.group(1) == "Lisa"

    def test_was_ist_die_adresse_von_max(self):
        m = CONTACT_FIELD_QUERY_PATTERN.match("was ist die adresse von Max")
        assert m

    # --- neue Varianten ---
    def test_geburtstag_von_max(self):
        """'geburtstag von Max' als Kurzform."""
        m = CONTACT_FIELD_QUERY_PATTERN.match("geburtstag von Max")
        assert m
        name = None
        for g in m.groups():
            if g:
                name = g.strip()
                break
        assert name == "Max"

    def test_wann_ist_annas_geburtstag(self):
        """Genitiv-s: 'wann ist Annas geburtstag'."""
        m = CONTACT_FIELD_QUERY_PATTERN.match("wann ist Annas geburtstag")
        assert m
        name = None
        for g in m.groups():
            if g:
                name = g.strip()
                break
        assert name is not None
        assert "Anna" in name

    def test_wann_ist_lisa_geburtstag(self):
        """Ohne Genitiv-s: 'wann ist Lisa geburtstag'."""
        m = CONTACT_FIELD_QUERY_PATTERN.match("wann ist Lisa geburtstag")
        assert m

    def test_geburtstag_max(self):
        """'geburtstag Max' ohne 'von'."""
        m = CONTACT_FIELD_QUERY_PATTERN.match("geburtstag Max")
        assert m


# ---------------------------------------------------------------------------
# calendar_commands – TERMIN_CREATE_PATTERN
# ---------------------------------------------------------------------------
from elder_berry.comms.commands.calendar_commands import TERMIN_CREATE_PATTERN


class TestTerminCreatePattern:
    """TERMIN_CREATE_PATTERN: 'neuer termin' Synonym."""

    # --- bestehende Eingaben ---
    def test_termin_zahnarzt_morgen(self):
        m = TERMIN_CREATE_PATTERN.match("termin: Zahnarzt morgen 14:00")
        assert m
        assert m.group(1).strip() == "Zahnarzt"

    def test_erstelle_termin(self):
        m = TERMIN_CREATE_PATTERN.match("erstelle termin Zahnarzt morgen")
        assert m

    # --- neue Variante ---
    def test_neuer_termin(self):
        m = TERMIN_CREATE_PATTERN.match("neuer termin: Lunch morgen 12:00")
        assert m
        assert m.group(1).strip() == "Lunch"

    def test_neuer_termin_ohne_doppelpunkt(self):
        m = TERMIN_CREATE_PATTERN.match("neuer termin Lunch morgen 12:00")
        assert m


# ---------------------------------------------------------------------------
# note_commands – NOTE_GET_FACT_PATTERN
# ---------------------------------------------------------------------------
from elder_berry.comms.commands.note_commands import NOTE_GET_FACT_PATTERN


class TestNoteGetFactPattern:
    """NOTE_GET_FACT_PATTERN: 'wie lautet' + Domain-Schutz."""

    # --- bestehende Eingaben ---
    def test_was_ist_wlan_passwort(self):
        m = NOTE_GET_FACT_PATTERN.match("was ist das WLAN Passwort?")
        assert m
        key = m.group(1) or m.group(2)
        assert key and "WLAN" in key

    def test_was_ist_meine_iban(self):
        m = NOTE_GET_FACT_PATTERN.match("was ist meine IBAN")
        assert m

    # --- neue Varianten ---
    def test_wie_lautet_das_passwort(self):
        m = NOTE_GET_FACT_PATTERN.match("wie lautet das Passwort?")
        assert m
        key = m.group(1) or m.group(2)
        assert key and "Passwort" in key

    def test_wie_lautet_mein_pin(self):
        m = NOTE_GET_FACT_PATTERN.match("wie lautet mein PIN")
        assert m

    # --- Domain-Schutz: darf NICHT matchen ---
    def test_was_ist_wetter_no_match(self):
        """'was ist wetter' soll nicht als Fakt-Abfrage gelten."""
        assert not NOTE_GET_FACT_PATTERN.match("was ist wetter?")

    def test_was_ist_das_wetter_no_match(self):
        assert not NOTE_GET_FACT_PATTERN.match("was ist das wetter?")

    def test_was_ist_termin_no_match(self):
        assert not NOTE_GET_FACT_PATTERN.match("was ist termin morgen?")

    def test_was_ist_mail_no_match(self):
        assert not NOTE_GET_FACT_PATTERN.match("was ist mail?")

    def test_wie_lautet_erinnerung_no_match(self):
        assert not NOTE_GET_FACT_PATTERN.match("wie lautet erinnerung?")

    # --- legitime Fakten mit Domain-aehnlichen Woertern ---
    def test_was_ist_wlan_passwort_ok(self):
        """'WLAN Passwort' darf matchen (Domain-Wort nicht am Anfang)."""
        m = NOTE_GET_FACT_PATTERN.match("was ist das WLAN Passwort")
        assert m


# ---------------------------------------------------------------------------
# todo_commands – TODO_COMPLETE_PATTERN
# ---------------------------------------------------------------------------
from elder_berry.comms.commands.todo_commands import TODO_COMPLETE_PATTERN


class TestTodoCompletePattern:
    """TODO_COMPLETE_PATTERN: 'aufgabe erledigt' Synonym."""

    # --- bestehende Eingaben ---
    def test_todo_erledigt_5(self):
        m = TODO_COMPLETE_PATTERN.search("todo erledigt #5")
        assert m
        assert (m.group(1) or m.group(2)) == "5"

    def test_todo_5_erledigt(self):
        m = TODO_COMPLETE_PATTERN.search("todo #5 erledigt")
        assert m

    # --- neue Varianten ---
    def test_aufgabe_erledigt_2(self):
        m = TODO_COMPLETE_PATTERN.search("aufgabe erledigt #2")
        assert m
        assert (m.group(1) or m.group(2)) == "2"

    def test_aufgabe_3_erledigt(self):
        m = TODO_COMPLETE_PATTERN.search("aufgabe 3 erledigt")
        assert m

    def test_aufgabe_erledigt_ohne_hash(self):
        m = TODO_COMPLETE_PATTERN.search("aufgabe erledigt 7")
        assert m
        assert (m.group(1) or m.group(2)) == "7"


# ---------------------------------------------------------------------------
# Cross-Handler Konflikt-Tests
# ---------------------------------------------------------------------------


class TestCrossHandlerConflicts:
    """Prueft dass erweiterte Patterns keine Cross-Handler-Konflikte erzeugen."""

    def test_starte_chrome_not_harmony(self):
        """'starte chrome' darf NUR bei Process matchen, NICHT bei Harmony."""
        assert START_PROCESS_PATTERN.match("starte chrome")
        assert not ACTIVITY_ON_PATTERN.match("starte chrome")

    def test_starte_tv_not_process(self):
        """'starte tv' darf NUR bei Harmony matchen, NICHT bei Process."""
        assert ACTIVITY_ON_PATTERN.match("starte tv")
        assert not START_PROCESS_PATTERN.match("starte tv")

    def test_loesche_mail_not_todo(self):
        """'lösche mail #5' matcht Mail, nicht Todo."""
        from elder_berry.comms.commands.todo_commands import TODO_DELETE_PATTERN
        assert MAIL_DELETE_PATTERN.match("lösche mail #5")
        assert not TODO_DELETE_PATTERN.match("lösche mail #5")

    def test_volume_vs_harmony_lauter(self):
        """'lauter' matcht Harmony Volume, nicht System Volume."""
        assert not VOLUME_PATTERN.match("lauter")
        assert VOLUME_UP_PATTERN.match("lauter")

    def test_was_ist_passwort_not_wetter(self):
        """'was ist das Passwort' matcht Note, nicht Weather."""
        assert NOTE_GET_FACT_PATTERN.match("was ist das Passwort?")
        assert not WEATHER_PATTERN.match("was ist das Passwort?")
