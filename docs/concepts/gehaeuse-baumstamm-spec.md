# Gehäuse-Spec: Baumstamm (Phase 4)

> **Status:** Constraints definiert – bereit für CAD-Design
> **Erstellt:** 2026-03-15
> **Design-Tool:** Autodesk Inventor
> **Fertigung:** Resin-Druck (Anycubic Photon Mono M7 Pro)
> **Bauraum Drucker:** 223 × 126 × 230mm

---

## 1. Konzept

Holunder-Baumstamm (passend zu "Elder-Berry") als Gehäuse für Pepper's Ghost
Display + Elektronik. Segmentierter Aufbau: dünner Innenkern + aufgesetzte
Rinden-Segmente. Geschlossene Decke mit Moos/Rinde-Optik.

## 2. Harte Constraints

| Parameter | Wert | Grund |
|-----------|------|-------|
| Innendurchmesser | Ø204mm | Display 143mm + 45° Geometrie |
| Außendurchmesser | ~220-230mm | +Wandstärke +Rindentextur |
| Gesamthöhe | ~185-200mm | Kammer ~120mm + Sockel ~50mm + Deckel ~15-20mm |
| Gewichtsbudget Gehäuse | 1.138g (gewogen) | Kein Limit – stationär, Tisch trägt Gewicht |
| Gesamtgewicht (mit Elektronik) | ~1.9kg (ohne Motoren/Chassis) | Stationär → irrelevant |
| Wandstärke Kern (tragend) | 1.5-2mm | Strukturelle Integrität |
| Wandstärke Rinde (nicht tragend) | 0.8-1.5mm | Gewichtsersparnis |
| Innenwand Kammer | matt-schwarz | Pepper's Ghost Reflexionsreduktion |
| Material | Resin (~1.1-1.2 g/cm³) | Dünnere Wände möglich als FDM |

## 3. Segmentierung (Druckstrategie)

Bauraum 223×126×230mm → Ø220mm passt NICHT einteilig.
Aufbau in Schichten + Segmenten:

### 3.1 Kern (strukturell, dünnwandig)
| Teil | Maße (ca.) | Druckbarkeit |
|------|-----------|--------------|
| Kern oben – Halbschale A | ~110×110×120mm | Passt (Y=110 < 126) |
| Kern oben – Halbschale B | ~110×110×120mm | Passt |
| Kern unten – Halbschale A | ~110×110×50mm | Passt |
| Kern unten – Halbschale B | ~110×110×50mm | Passt |
| Deckel | ~220×110×15mm (2 Hälften) | Passt als Hälften |
| Bodenplatte | ~220×110×3mm (2 Hälften) | Passt als Hälften |

- Halbschalen vertikal geteilt (Schnittebene durch Mitte)
- Verbindung Halbschalen: Stecknasen + M2 Einschmelzgewinde
- Trennebene Kammer/Sockel: horizontal, Steck- oder Schraubverbindung
- Kern-Innenseite: matt-schwarz lackiert (oder schwarzes Resin)

### 3.2 Rinden-Segmente (dekorativ)
- 6-10 Segmente, je nach gewünschtem Detail
- Aufgesteckt auf Kern (Stecknasen) + optional M2 Schrauben
- Nicht tragend → 0.8-1.5mm Wandstärke möglich
- Jedes Segment passt einzeln in den Bauraum
- 1 Spezialsegment: Blickfenster-Ausschnitt (Baumhöhle)
- Alternative Befestigung: Neodym-Magnete (einfacher demontierbar)

### 3.3 Deckel
- Geschlossene Decke, Moos/Rinde/Pilz-Optik
- 2 Hälften (Ø220 > 126mm Bauraum)
- Abnehmbar für Zugang zur Kammer (Steck oder Magnet)

## 4. Pepper's Ghost Kammer

```
Querschnitt (Seitenansicht):
                    ┌──────────────────────┐ ← Deckel (Moos)
                    │   Luft (~15mm)        │
                    │        /              │
                    │  Acryl/ 45°           │
                    │      /    [Ghost-Bild]│──→ Blickfenster
                    │    /      [512×1024]  │
                    │  /                    │
                    │ [Display flach]       │
                    ├──────────────────────┤ ← Trennebene
                    │ [RPi5] [Pico] [PCB]  │
                    │ [Motor HAT] [BMS]    │
                    └──────────────────────┘ ← Bodenplatte → Chassis
```

- Display liegt horizontal auf Halterung, DSI-Kabel nach unten
- Acryl 45° über Display: 150×200×1mm Zuschnitt (aus Bestand: 30 Stk.)
- Acryl-Halterung: Nuten oder Clips im Kern (nicht geklebt, austauschbar)
- Blickfenster: Öffnung in Kern + Rinden-Segment, eine Seite
- Blickwinkel: ~90mm breit × ~130mm hoch (mindestens Ghost-Bild-Fläche)
- Kamera: oben in der Kammer, über dem Acryl, Blick durch Fenster nach außen

## 5. Elektronik-Fach (Sockel)

Unterhalb der Trennebene, ~50mm Höhe:

| Komponente | Maße (ca.) | Position |
|-----------|-----------|----------|
| RPi5 + Kühlkörper | 85×56×20mm | Links |
| Motor HAT (I²C) | 65×56×15mm | Auf RPi5 |
| Pico 2W | 51×21×5mm | Mitte |
| BMS 2S | 30×15×5mm | Rechts neben Pico |
| PCB (eigen) | ~60×40mm | Rechts |
| Kabel-Raum | -- | Verteilt |

- DSI-Kabel vom Display nach unten zum RPi5
- CSI-Kabel von Kamera nach unten zum RPi5
- Akku-Kabel (2× 18650) von unten/Chassis
- Motorstecker (4×) von unten/Chassis
- Zugang: Bodenplatte abnehmbar ODER Kern-Trennung öffnen

## 6. Gewichtsbudget (detailliert)

### Fix (Elektronik + Chassis)
| Komponente | Gewicht |
|-----------|---------|
| Mecanum-Chassis + 4× TT-Motor | ~400g |
| RPi5 + Kühlkörper | ~55g |
| Pico 2W | ~5g |
| RPi Touch Display 2 (5") | ~90g |
| Motor HAT | ~25g |
| 2× 18650 Akku | ~90g |
| BMS 2S | ~10g |
| PCB + Kabel + Stecker | ~60g |
| Acrylglas 45° | ~15g |
| Kamera-Modul | ~10g |
| **Summe Elektronik** | **~760g** |

### Variabel (Gehäuse) – Zielwert
| Teil | Geschätztes Gewicht |
|------|-------------------|
| Kern (4 Halbschalen, 1.5mm) | ~250-300g |
| Rinden-Segmente (8 Stk., 1mm) | ~120-180g |
| Deckel (2 Hälften) | ~40-60g |
| Bodenplatte (2 Hälften, 2mm) | ~30-40g |
| Schrauben/Magnete/Kleber | ~20g |
| **Summe Gehäuse** | **~460-600g** |

### Gesamtschätzung
| Szenario | Gewicht | Bewertung |
|---------|---------|-----------|
| Optimistisch | ~1.22kg | Gut machbar |
| Realistisch | ~1.35kg | Grenzwertig auf Teppich |
| Pessimistisch | ~1.50kg | Nur auf glattem Boden |

> **Risiko:** Falls >1.4kg → stärkere Motoren (N20/GA12) evaluieren
> oder Rindensegmente weiter ausdünnen.

## 7. Oberfläche + Finish

- Kern: matt-schwarz lackiert (Innenseite Kammer) oder schwarzes Resin
- Rinde: braun/grau bemalt oder naturbelassen (Resin-Farbe)
- Deckel: Moos/Pilz-Details modelliert, grün/braun bemalt
- Blickfenster-Kante: organisch, wie aufgebrochene Rinde
- Optional: UV-Resin-Klarlack für Witterungsschutz (bei Outdoor-Einsatz)

## 8. Montage-Reihenfolge

1. Kern-Halbschalen zusammenstecken + verschrauben (M2)
2. Display + Halterung in Kammer montieren
3. Acryl 45° in Nuten/Clips einsetzen
4. Kamera oben montieren
5. Elektronik im Sockel montieren (RPi5, HAT, Pico, BMS, PCB)
6. Kabel verbinden (DSI, CSI, Motor, Akku)
7. Bodenplatte aufsetzen, auf Chassis montieren
8. Rinden-Segmente aufstecken/schrauben
9. Deckel aufsetzen
10. Test: Display an, Pepper's Ghost prüfen, Blickwinkel justieren

## 9. Offene Punkte

| Punkt | Entscheidung nötig |
|-------|-------------------|
| Rinden-Befestigung | Stecknasen+Schrauben vs. Magnete – erst nach Prototyp |
| Acryl-Halterung | Nuten vs. Clips vs. Klebepunkte |
| Kabel-Durchführung Kammer→Sockel | Schlitz in Trennebene vs. Bohrung |
| Kamera-Position | Oben in Kammer vs. eigenes Loch in Rinde |
| Belüftung RPi5 | Schlitze im Sockel-Bereich nötig? (Kühlkörper + geschlossen = heiß) |
| Akkus: im Sockel oder im Chassis? | Gewichtsverteilung: tief = stabiler |
| Boden: Teppich-Tauglichkeit | Bei >1.4kg: Motorupgrade evaluieren |

## 10. Nächste Schritte

1. CAD-Design in Inventor (Kern zuerst, dann Segmente)
2. Prototyp Kern-Halbschale drucken → Gewicht wiegen
3. Display + Acryl einpassen → Pepper's Ghost testen
4. Falls Gewicht okay → Rindensegmente designen
5. Vollständiger Zusammenbau + Gewichtstest auf Chassis
