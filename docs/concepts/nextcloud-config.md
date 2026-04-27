# Nextcloud Konfiguration & Saleria-Integration

**Dokument:** `docs/concepts/nextcloud-config.md`  
**Stand:** 2026-03-31  
**Scope:** Nextcloud-Setup auf `cloud.example.com`, Saleria-Synergien, Sicherheit

---

## 1. Ziel

Ein professionelles, selbst-gehostetes Arbeitsumfeld auf Basis von Nextcloud 33, das:
- von unterwegs (Browser, Mobile App) und zuhause (Desktop-Client) vollständig nutzbar ist
- mit Saleria tief integriert ist
- minimale Angriffsfläche bietet (nur aktiv genutzte Apps laufen)
- Datensouveränität wahrt (keine Telemetrie, keine unnötigen externen API-Calls)

**Zugriffswege:**
- Browser: `https://cloud.example.com`
- Nextcloud Mobile App (iOS/Android)
- Nextcloud Desktop-Sync-Client (Tower, Windows)

---

## 2. App-Konfiguration

### 2.1 Sofort deaktivieren

| App | Begründung |
|-----|------------|
| **Federation** | Single-User-Instanz, kein Austausch mit anderen NC-Instanzen nötig. Unnötige Angriffsfläche. |
| **Full text search** | Ohne Elasticsearch/OpenSearch-Backend funktionslos — durchsucht nur Dateinamen, nicht Inhalte. Kostet CPU ohne Nutzen. |
| **Full text search – Files** | Gleicher Grund wie oben. |
| **Usage survey** | Sendet Nutzungstelemetrie an Nextcloud GmbH. Widerspricht dem Datensouveränitätsziel. |
| **Recommendations** | Wertet lokale Nutzungsmuster aus. Kein Mehrwert für Single-User mit Saleria. |
| **Nextcloud announcements** | Reine Marketing-Meldungen. Kein Informationswert. |

### 2.2 Prüfen / situativ deaktivieren

| App | Empfehlung |
|-----|------------|
| **Photos** | Deaktivieren, solange keine Fotoverwaltung geplant ist. Aktivierbar wenn Bedarf entsteht. |
| **Share by mail** | Nur aktiv lassen wenn externe Shares per E-Mail regelmäßig genutzt werden. |
| **Weather status** | Macht externe API-Calls zu wttr.in. Bewusste Entscheidung: deaktivieren für maximale Isolation. |
| **First run wizard** | Nie wieder nötig, schadet aber nicht. |

### 2.3 Aktiv behalten und konfigurieren

| App | Status | Notizen |
|-----|--------|---------|
| **Calendar** | ✅ Aktiv | CalDAV-Backend für Saleria (Phase 36.2). Tasks-App zusätzlich installieren. |
| **Contacts** | ✅ Aktiv | CardDAV bidirektional mit Saleria (Phase 36.3). |
| **Nextcloud Office (Collabora)** | ✅ Aktiv | Built-in CODE Server. WOPI Allow-List geleert (Single-User-Fix). Remote-Zugriff testen! |
| **Notes** | ✅ Aktiv | Markdown-Dateien in `/Notes/` — Saleria nutzt WebDAV-Zugriff (Phase 36.1). |
| **Deck** | ✅ Aktiv | Kanban-Board. Saleria-Integration über eigene REST-API — eigener DeckClient nötig (spätere Phase). |
| **Two-Factor TOTP** | ✅ Aktiv | Pflicht. Nie deaktivieren. |
| **Brute force settings** | ✅ Aktiv | Bereits konfiguriert. Login-Attempts regelmäßig im Log prüfen. |

### 2.4 Zusätzlich installieren

| App | Begründung |
|-----|------------|
| **Tasks** | Installieren für VTODO-Unterstützung im CalDAV-Feed. To-Dos erscheinen in Kalender-Clients und sind von Saleria über bestehenden CalDAV-Client lesbar/schreibbar. |

---

## 3. Dateiorganisation

### 3.1 Grundprinzip

Die Cloud ist aktuell leer — das ist der ideale Zeitpunkt, eine saubere Struktur festzulegen.  
**Regel:** Lieber jetzt 20 Minuten Struktur planen als später 200 Dateien umsortieren.

Volltextsuche (Elasticsearch) wird **nicht** eingerichtet bis mindestens ~200 Dokumente vorhanden sind.  
Salerias WebDAV-Suche über Dateinamen ist bis dahin vollständig ausreichend.

### 3.2 Ordnerstruktur

```
/                                    ← Nextcloud Root
├── 📁 Manuale/
│   ├── 📁 Elektronik/
│   ├── 📁 3D-Druck/
│   ├── 📁 Netzwerk/
│   ├── 📁 Smart-Home/
│   └── 📁 Sonstiges/
│
├── 📁 Projekte/
│   ├── 📁 Elder-Berry/              ← Projektdokumente (nicht der Code-Repo)
│   └── 📁 [weitere Projekte]/
│
├── 📁 Dokumente/
│   ├── 📁 Rechnungen/
│   ├── 📁 Vertraege/
│   └── 📁 Behoerden/
│
├── 📁 Saleria/                      ← Saleria hat Schreibzugriff, Mensch liest mit
│   ├── 📁 Notizen/                  ← von Saleria erstellte/verwaltete Notizen
│   └── 📁 Berichte/                 ← generierte Zusammenfassungen, Logs etc.
│
└── 📁 Archiv/                       ← abgeschlossene Projekte, alte Dokumente
```

### 3.3 Dateinamen-Konvention

**Allgemein:** `[Kategorie]_[Beschreibung]_[Datum-optional].ext`

**Manuale speziell:** `[Hersteller]_[Produkt]_[Dokumenttyp]_[Jahr].pdf`

Beispiele:
```
Anycubic_Photon-Mono-M5_Bedienungsanleitung_2023.pdf
Raspberry-Pi_Pi5_Quick-Start-Guide_2024.pdf
Denon_AVR-X3500H_Benutzerhandbuch_2019.pdf
```

**Warum das wichtig ist:** Salerias WebDAV-Suche arbeitet auf Dateinamen. Je konsistenter die Namen, desto besser die Trefferquote ohne Elasticsearch.

### 3.4 Wann Elasticsearch sinnvoll wird

Voraussetzungen müssen **beide** erfüllt sein:
1. Mehr als ~200 Dokumente vorhanden
2. Regelmäßige Suche nach **Inhalten** die nicht im Dateinamen stehen (z.B. "finde Manual wo 'Einstellschraube M4' erwähnt wird")

Bis dahin: Full Text Search Apps deaktiviert lassen.

---

## 4. App-Passwörter für Saleria

### 4.1 Prinzip

Saleria verwendet **niemals** das Hauptpasswort des Nextcloud-Accounts.  
Stattdessen: ein dediziertes App-Passwort für alle Saleria-Zugriffe.

**Warum ein Token statt mehrerer:** Alle Saleria-Clients laufen auf dem Tower. Bei einer Kompromittierung wären alle Tokens gleichzeitig exponiert (siehe 4.4). Separate Tokens pro Protokoll erhöhen nur die Verwaltungskomplexität ohne echten Sicherheitsgewinn für eine Single-User-Instanz.

### 4.2 App-Passwort anlegen

Unter: `cloud.example.com` → Einstellungen → Sicherheit → App-Passwörter

| Token-Name | Verwendet für |
|------------|---------------|
| `saleria` | Alle Saleria-Zugriffe (CalDAV, CardDAV, WebDAV, REST-APIs) |

### 4.3 Wo die Credentials gespeichert werden

Saleria verwendet den eigenen **SecretStore** (Fernet-Verschlüsselung) — keine Klartext-Credentials in Dateien, kein Git-Risiko.

```python
from elder_berry.core.secret_store import SecretStore
store = SecretStore()

# Credentials abrufen
url = store.get("nextcloud_url")
user = store.get("nextcloud_user")
pw = store.get("nextcloud_app_password")
```

Schlüssel-Namen im SecretStore (Konvention: `nextcloud_*`):

| Schlüssel | Inhalt |
|-----------|--------|
| `nextcloud_url` | `https://cloud.example.com` |
| `nextcloud_user` | `user` |
| `nextcloud_app_password` | App-Passwort (für alle Protokolle) |

**Hinweis für neue Clients:** Jeder neue Nextcloud-Client bezieht seine Credentials ausschließlich über `SecretStore` mit denselben drei Keys — nie hardcoded, nie als Konstruktor-Parameter.

### 4.4 Sicherheitsimplikation (bewusste Entscheidung)

> Saleria läuft auf dem Tower und hat Zugriff auf alle App-Tokens. Wenn der Tower kompromittiert wird, sind alle Nextcloud-Daten (Kalender, Kontakte, Dateien, Notizen, Deck) erreichbar.

Das ist als Risiko bekannt und akzeptiert. Mitigationsmaßnahmen:
- Tower-Festplattenverschlüsselung empfohlen (BitLocker)
- Saleria-Prozess läuft nicht als Admin
- Tokens regelmäßig rotieren (z.B. bei Verdacht oder nach großen System-Updates)

---

## 5. Sicherheits-Konfiguration Nextcloud

### 5.1 Admin → Übersicht (Security & setup warnings)

Nextcloud zeigt hier fehlende Konfigurationen an. Alle Warnungen beheben:
- HTTP Strict Transport Security (HSTS) Header setzen
- `X-Frame-Options: SAMEORIGIN` setzen
- `X-Content-Type-Options: nosniff` setzen
- Korrekter Caching-Header für statische Assets

Diese werden in Plesk über nginx-Direktiven in der vHost-Konfiguration gesetzt.

### 5.2 Shares

- Kein öffentlicher Share ohne Ablaufdatum
- Kein öffentlicher Share ohne Passwort
- Standard-Ablaufdauer für öffentliche Links setzen: 14 Tage

### 5.3 Login-Monitoring

- Admin → Logging regelmäßig prüfen auf fehlgeschlagene Login-Versuche
- Brute Force Protection ist aktiv ✓

### 5.4 Backup (aktuell offen)

**Noch nicht definiert.** Mindestanforderung:
- Nextcloud Datenbank (MariaDB `cloud`): tägliches Dump
- Dateiverzeichnis `/var/www/vhosts/example.com/nextcloud-data/`
- `config/config.php`

→ Separate Entscheidung: wo und wie gebackupt wird.

---

## 6. Saleria-Synergien — Priorisierung

| Priorität | Funktion | Technisch | Status |
|-----------|----------|-----------|--------|
| ✅ Fertig | Kalender lesen/schreiben | CalDAV | Phase 36.2 |
| ✅ Fertig | Dateien lesen/schreiben | WebDAV | Phase 36.1 |
| ✅ Fertig | Kontakte bidirektional | CardDAV | Phase 36.3 |
| 🟡 Einfach | Notizen lesen/schreiben | WebDAV (Dateien in /Notes/) | Erweiterung Phase 36.1 |
| 🟠 Mittel | Tasks (To-Dos) | CalDAV VTODO | Erweiterung Phase 36.2 |
| 🔴 Aufwand | Deck-Karten | eigener DeckClient, REST-API | neue Phase |

**Empfohlene Reihenfolge:**
1. **Notizen** — quasi gratis über bestehenden WebDAV-Client. Datei lesen/schreiben in `/Notes/`. Notes-Metadaten (Kategorie, Favorit) sind UI-Features für den Menschen — kein separater API-Client nötig.
2. **Tasks** — CalDAV VTODO, die Infrastruktur steht. Tasks-App installieren, dann CalDAV-Client um VTODO erweitern.
3. **Deck** — erst angehen wenn der Alltags-Workflow mit Deck etabliert ist und der Nutzen klar ist.

**Collabora/Nextcloud Office und Saleria:** Keine tiefe Integration geplant. Dokumente sind im OOXML-Format — schwer maschinenlesbar ohne extra Parser. Saleria kann Dokumente als Dateien ablegen und verlinken, aber nicht inhaltlich verarbeiten.

---

## 7. Offene Punkte / nächste Schritte

- [ ] Apps deaktivieren (Abschnitt 2.1)
- [ ] Tasks-App installieren
- [ ] Ordnerstruktur in Nextcloud anlegen (Abschnitt 3.2)
- [ ] App-Passwort anlegen und im SecretStore eintragen (Abschnitt 4.2)
- [ ] Nextcloud Security-Warnings in Admin → Übersicht abarbeiten
- [ ] Collabora Remote-Zugriff testen (WOPI-Fix + Browser von außen)
- [ ] Backup-Strategie definieren (Abschnitt 5.4)
- [ ] Desktop-Sync-Client konfigurieren: welche Ordner werden lokal gespiegelt?
