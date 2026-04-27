# Branch-Protection Rulesets

Zwei Varianten für den `main`-Branch. Die Files sind nicht
auto-applied — GitHub-Rulesets müssen manuell über die UI importiert
werden. Die Files hier dienen als versionierte Referenz und Backup.

## Welche Variante nehmen?

### `main-protection.json` (Standard) — Empfehlung

Die balancierte Variante für ein Solo-Maintainer-Repo:

- ❌ `main` darf nicht gelöscht werden
- ❌ Kein force-push, keine History-Rewrites
- ❌ Keine Merge-Commits (nur Squash/Rebase, lineare History)
- ✅ CI muss grün sein vor Merge: `test (ubuntu-latest, 3.12)`,
  `test (windows-latest, 3.12)`, `lint`, `security`
- ✅ PR muss up-to-date mit `main` sein vor Merge
  (`strict_required_status_checks_policy`)
- ✅ CodeQL: High/Critical-Findings blocken den Merge
- ✅ Maintainer (Admin/RepositoryRole 5) kann im Notfall bypassen

**Empfohlen für die meisten Fälle.** Verhindert die häufigsten Unfälle
(force-push, kaputtes CI mergen) und lässt dem Maintainer trotzdem
Notfall-Wege offen.

### `main-protection-strict.json` (Hart) — für später, wenn das Repo viel Verkehr hat

Zusätzlich zu allem oben:

- ✅ **Signed Commits Pflicht** (`required_signatures`)
  → Du brauchst einen GPG- oder SSH-Signing-Key + lokale Konfiguration:
  ```bash
  git config --global user.signingkey <YOUR_KEY>
  git config --global commit.gpgsign true
  ```
- ✅ **CodeQL-Threshold auf `medium_or_higher`** statt `high_or_higher`
- ❌ **Kein Bypass für Admins** — auch du musst durch den ganzen
  Prozess. Direkt-Push auf `main` nicht mehr möglich.

**Nur empfehlenswert wenn:**
- Du sowieso schon mit Signed Commits arbeitest.
- Du das Repo nicht nur als Personal-Project siehst, sondern
  ernsthaft externen Verkehr erwartest.
- Du bereit bist, jede Änderung über einen PR laufen zu lassen
  (auch Tippfehler-Fixes).

## Wie importieren?

1. **Vorbereitung:** Stelle sicher, dass alle referenzierten
   Status-Checks mindestens einmal erfolgreich gelaufen sind:
   - CI: muss bei vorigen PRs durchgelaufen sein → ✅ schon der Fall.
   - CodeQL: erst aktivieren! Siehe
     `Settings → Code security and analysis → Code scanning → Set up`.
     Erst nach erfolgreichem CodeQL-Run das Ruleset importieren,
     sonst blockt die `code_scanning`-Rule jeden Merge bis zum
     ersten Erfolg.

2. **Import:**
   - Geh auf
     `https://github.com/leratos/Elder-Berry/settings/rules`
   - Klick **"New ruleset"** → **"Import a ruleset"**
   - Datei hochladen: `main-protection.json` (oder `-strict.json`)
   - Aktiviere via **"Active"** im Enforcement-Status.
   - Speichern.

3. **Test:** Mache einen Test-PR mit absichtlich kaputtem Test
   und versuch zu mergen. Der Merge-Button sollte gesperrt sein.

## Wenn du was am Ruleset änderst

GitHub UI ist die Wahrheitsquelle, die JSON-Files hier sind die
Doku/Backup-Kopie. Nach Änderungen in der UI:

1. UI-Export: `Settings → Rules → Rulesets → <Name> → Export`
2. Die heruntergeladene JSON committen (Pfad in diesem Verzeichnis).
3. Reviewer-PR aufmachen, damit sichtbar wird was sich änderte.

## Bypass-Actor-IDs (zur Erinnerung)

- `1` = Maintain (selten)
- `4` = Admin
- `5` = Repository Owner / inherited Admin

Standard-Variante hat `5` mit `bypass_mode: "always"`.
