# Avatar-Sprites Saleria

Layered Sprite-Set fuer den Pepper's Ghost-Avatar. Aufgeteilt in drei
Ebenen, die zur Laufzeit kombiniert werden:

- `body/` -- Koerper-Pose pro Stimmung (8 PNGs)
- `eye/` -- Augenpaar (left/right) pro Emotion und Zustand (22 PNGs)
- `mouth/` -- Mundform pro Emotion und Lip-Sync-Frame (15 PNGs)

Konfiguration und Mapping Emotion -> Sprite siehe `avatar_config.yaml`
in diesem Verzeichnis.

## Herkunft

Die **Vorlagen** wurden vom Maintainer (Lera) mit **Google Gemini**
generiert (Charakter-Design Saleria Berry, eigene Prompts) und
anschliessend manuell **nachbearbeitet, korrigiert und erweitert**:
- Inkonsistenzen zwischen Frames retuschiert (Augen-Position,
  Koerper-Proportion, Farben),
- fehlende Emotion-/Mund-Frames neu gezeichnet bzw. zusammengesetzt,
- Hintergrund freigestellt (transparent), Schwarzpegel auf das
  Pepper's Ghost-Setup abgestimmt.

Die im Repo eingecheckten PNGs sind also abgeleitete Werke -- nicht
die Roh-Outputs des Modells, sondern das Ergebnis manueller
Bearbeitung durch den Maintainer.

## Lizenz

MIT, identisch zum Rest des Repositorys (siehe
[`LICENSE`](../../../../LICENSE)).

Begruendung: Google Gemini erhebt nach den aktuellen Nutzungs-
bedingungen keinen Eigentumsanspruch auf die generierten Bilder
(nicht-exklusive Nutzung beim Anwender). In Verbindung mit der
manuellen Nachbearbeitung gelten die finalen PNGs hier als
**eigenstaendiges, abgeleitetes Werk** des Maintainers und stehen
unter MIT.

Das heisst:
- Die fertigen Sprites in diesem Verzeichnis duerfen unter den
  MIT-Bedingungen weiterverwendet werden.
- Wer die Sprites in einem eigenen Projekt einsetzt, muss
  Copyright-Hinweis und Lizenztext mitliefern (Standard-MIT).
- **Keine** Gemini-spezifischen Einschraenkungen werden mit
  weitergegeben -- die haben sich mit der manuellen Bearbeitung
  und der MIT-Veroeffentlichung erledigt.

Hinweis: Wer Saleria als Charakter (Name, Persoenlichkeit,
Gesamterscheinung) verwendet, sollte das transparent kenntlich
machen -- der Charakter selbst ist Teil des
[Last-Strawberry](https://last-strawberry.com) Universums und
wird hier aktiv weiterentwickelt.

## Aenderungen / Neue Frames

Wer einen Frame ersetzt oder hinzufuegt, sollte:

- Naming-Schema beibehalten (`mouth_<emotion>_<state>.png`,
  `eye_<side>_<emotion>_<state>.png`, `<pose>.png` fuer body),
- transparenten Hintergrund liefern (PNG mit Alpha),
- ggf. `avatar_config.yaml` erweitern, falls eine neue Emotion
  oder ein neuer Zustand dazukommt.
