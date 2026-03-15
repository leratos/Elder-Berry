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
| ~~GESTRICHEN~~ | ~~Mecanum Chassis~~ | Mobilität gestrichen → stationär + drehbar | – |
| 🛒 | Servo SG90 oder MG996R | Drehteller-Antrieb · RPi5 GPIO | ~3-5€ |
| 🛒 | Lazy Susan Kugellager | Drehteller · Ø100-150mm | ~5€ |
| 📋 | Stromversorgung | USB-C Netzteil (Dauerbetrieb) oder Akku · wird entschieden wenn Standort klar | – |
| ~~GESTRICHEN~~ | ~~3S Akku-Option~~ | Mobilität gestrichen, kein 3S nötig | – |
| ~~GESTRICHEN~~ | ~~Adafruit DC Motor HAT~~ | Mobilität gestrichen | – |
| ~~GESTRICHEN~~ | ~~Motor-Driver Alternative~~ | Mobilität gestrichen | – |

---

## Stromversorgung

| Status | Artikel | Details | Quelle |
|---|---|---|---|
| 📋 | USB-C BMS Lademodul 2S · 18W · 3A | Nur nötig falls Akku-Betrieb gewünscht | roboter-bausatz.de · 7,35€ |
| 📋 | D36V50F5 Spannungsregler | Nur nötig falls Akku-Betrieb · sonst USB-C direkt | – |
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
| ~~GESTRICHEN~~ | ~~Ladestation autonomes Laden~~ | Mobilität gestrichen |
| ~~GESTRICHEN~~ | ~~IR/Kamera Docking~~ | Mobilität gestrichen |
| 📋 | USB-C Netzteil 5V/3A | Dauerbetrieb RPi5 + Display · je nach Standort |

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

*Zuletzt aktualisiert: 2026-03-15 (Mobilität gestrichen → stationär + drehbar)*
