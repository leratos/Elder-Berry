# Elder-Berry – Einkaufsliste

> Legende: ✅ Vorhanden · 🛒 Bestellen · 📋 Definiert (Typ noch offen)

---

## Rechner & Controller

| Status | Artikel | Details | Quelle |
|---|---|---|---|
| ✅ | Tower PC | RTX 4070 Ti Super 16GB · Ollama phi4:14b | – |
| ✅ | Laptop | RTX 4070 Laptop 8GB · Testplattform · Ollama phi4:14b | – |
| 🛒 | Raspberry Pi 5 | I/O-Controller · Sensoren · Kommunikation | berrybase.de |
| 🛒 | Raspberry Pi Pico 2W | Motorsteuerung Echtzeit · Akku-Monitoring · MicroPython | berrybase.de · ~8,50€ |

---

## Display & Kamera

| Status | Artikel | Details | Quelle |
|---|---|---|---|
| 🛒 | RPi Touch Display 2 · 5" Portrait | 720×1280px · DSI · 91,46×143,4mm · Pepper's Ghost | berrybase.de · 43,50€ · Art.-Nr. RPI-5LCD2 |
| 🛒 | RPi Camera Module 3 | 12MP · CSI · für Kamera-Input ans LLM | berrybase.de · ~28,90€ · Art.-Nr. RPI-CAM3 |

---

## Roboter & Antrieb

| Status | Artikel | Details | Quelle |
|---|---|---|---|
| ⚠️ | Mecanum Chassis | ALTES Chassis (TT-Motoren) nicht kompatibel mit JGB37 · Redesign nötig | – |
| 🛒 | 4× JGB37-520 Encoder Motor | 12V · 100-150 RPM · Hall-Encoder · Ø37mm · 6mm D-Shaft | AliExpress/Amazon · ~25-40€ |
| 🛒 | 4× Mecanum-Räder 60/80mm | 6mm D-Shaft Aufnahme · passend für JGB37 | AliExpress · ~15-25€ |
| ✅ | 2× 18650 Akkus + 2S BMS | 7,4V · Schutzschaltung · Ladefunktion vorhanden | – |
| 📋 | 3S Akku-Option | 11,1V für JGB37 volle Drehzahl · BMS/PCB-Kompatibilität prüfen | – |
| ⚠️ | Adafruit DC Motor HAT | I²C · evtl. zu schwach für JGB37 (1.2A/Kanal, Stall 2.8A) → Alternative prüfen | adafruit.com |
| 📋 | Motor-Driver Alternative | L298N / BTS7960 / Custom auf PCB · wird in Phase 4 definiert | – |

---

## Stromversorgung

| Status | Artikel | Details | Quelle |
|---|---|---|---|
| 🛒 | USB-C BMS Lademodul 2S · 18W · 3A | Buck-Boost · 4,5-15V Eingang · USB-C PD · 3-farbige LED | roboter-bausatz.de · 7,35€ · Art.-Nr. RBS18584 |
| ✅ | D36V50F5 Spannungsregler | 5V · 5A · VOUT1 → Motor HAT · VOUT2 → RPi + Pico | – |
| ✅ | Widerstände R1/R2 · 100kΩ | Spannungsteiler Akku-Monitoring → Pico ADC | – |

---

## Sensoren

| Status | Artikel | Details | Quelle |
|---|---|---|---|
| 📋 | IR Sensor | Typ noch offen · wird in Phase 2 definiert · an RPi 5 | – |
| 📋 | Temperatursensor | Typ noch offen · wird in Phase 2 definiert · an RPi 5 | – |

---

## Gehäuse & Material

| Status | Artikel | Details | Quelle |
|---|---|---|---|
| ✅ | Acrylplatten · 1mm · 250×200mm | 30 Stück · Pepper's Ghost · 45° im Gehäuse | – |
| ✅ | Alu Rohr · Ø165mm | Biegeform für Acryl · nicht Teil des Gehäuses | – |
| 📋 | Resin-Druck · Baumstamm-Gehäuse | Segmentiert · Kern+Rinde · Ø220mm · ~190mm hoch · Spec: docs/concepts/gehaeuse-baumstamm-spec.md | – |
| 🛒 | Einschmelzgewinde M2 | Außen-Ø 3,5mm · Druckrahmen Display · mind. 6 Stück | – |
| 🛒 | Mattlack schwarz | Gehäuse-Innenwand · Reflexionsreduktion Pepper's Ghost | – |
| 🛒 | Epoxidharz 2K oder Loctite 480 | Einschmelzgewinde in Resin kleben | – |
| 📋 | Neodym-Magnete Ø3×2mm | Optional: Rinden-Befestigung am Kern · nach Prototyp entscheiden | – |

---

## Software & Charakter

| Status | Artikel | Details | Quelle |
|---|---|---|---|
| ✅ | Charakter-Assets | Basis · 6 Expressions · Layer-Views · Body-Posen | – |
| ✅ | GitHub Repo Elder-Berry | CLAUDE.md · Roadmap · Codespace eingerichtet | – |
| ✅ | Ollama · phi4:14b | Tower + Laptop · lokal · keine API-Kosten | – |

---

## Noch offen / Phase 4

| Status | Artikel | Details |
|---|---|---|
| 📋 | Ladestation autonomes Laden | Qi-Coil · wird in Phase 4 definiert |
| 📋 | IR/Kamera Docking | Für autonome Rückkehr zur Ladestation · Phase 4 |

---

## Priorität erste Bestellung

```
1. RPi Touch Display 2 · 5"    → kritischer Pfad für Sockel-Konstruktion
2. Raspberry Pi 5              → kritischer Pfad für Phase 2
3. USB-C BMS Lademodul 2S      → Schaltplan bereits fertig
4. RPi Camera Module 3         → Phase 2
5. Raspberry Pi Pico 2W        → Phase 2
6. Adafruit DC Motor HAT       → Phase 4
```

---

*Zuletzt aktualisiert: 2026-03-15*
