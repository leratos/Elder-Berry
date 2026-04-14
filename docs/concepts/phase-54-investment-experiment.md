# Phase 54 – Bull-Berry: Autonomes Investment-Experiment

**Projektname:** Bull-Berry (eigenständiges Projekt, Schnittstelle zu Saleria geplant)
**Repository:** separat von Elder-Berry, eigenes Projekt

## Ziel

Eine KI erhält ein virtuelles Startkapital und ein reales API-Guthaben.
Sie entscheidet autonom über Kauf/Verkauf von Wertpapieren.
Das System führt Trades aus, trackt Kurse und berechnet P&L unabhängig.
Die KI muss mit ihrem begrenzten API-Budget haushalten – verbraucht sie es,
ist das Experiment gescheitert. Erzielt sie nach 1 Monat Gewinn, ist es erfolgreich.

## Phasen

### Phase 1 – Virtueller Handel (dieses Konzept)
- Startkapital: 100€ virtuell
- API-Guthaben: 5€ real (Anthropic API)
- Tägliche Grundgebühr: 0,50€ (simuliert Serverkosten, erzeugt Zeitdruck)
- Handel: automatisch über System mit echten Kursdaten
- Assets: Aktien, ETFs (was Trade Republic bietet)
- Kursdaten: Yahoo Finance API (kostenlos, `yfinance` Python-Library)
- Laufzeit: 1 Monat
- Erfolg: Portfolio > 100€ UND Guthaben > 0€

### Phase 2 – Live-Handel (zukünftig)
- KI kontaktiert Nutzer via Matrix in aktiver Zeit
- Nutzer führt Orders auf Trade Republic manuell aus
- Alternativ: automatischer Handel via `pytr` (inoffizielle API, ToS-Risiko)

## Architektur

```
┌─────────────────────────────────────────────────────┐
│                   InvestmentEngine                    │
│  (Orchestrator – Cron oder Dauerprozess)             │
├─────────────────────────────────────────────────────┤
│                                                       │
│  ┌─────────────┐    ┌──────────────┐                 │
│  │  AIAdvisor   │    │ BudgetTracker │                │
│  │              │    │               │                │
│  │ - wählt      │    │ - API-Kosten  │                │
│  │   Modell     │    │ - Grundgebühr │                │
│  │ - analysiert │    │ - Guthaben    │                │
│  │ - entscheidet│    │ - Formel      │                │
│  └──────┬───────┘    └──────┬────────┘                │
│         │                   │                         │
│  ┌──────▼───────────────────▼────────┐               │
│  │         TradeExecutor              │               │
│  │                                    │               │
│  │ - empfängt Order von AIAdvisor     │               │
│  │ - holt aktuellen Kurs (yfinance)   │               │
│  │ - bucht ins Portfolio              │               │
│  │ - loggt Timestamp + Kurs           │               │
│  └──────┬─────────────────────────────┘              │
│         │                                             │
│  ┌──────▼─────────────────────────────┐              │
│  │         PortfolioTracker            │              │
│  │                                     │              │
│  │ - Positionen + Einstandskurse       │              │
│  │ - aktuelle Bewertung (live Kurse)   │              │
│  │ - P&L-Berechnung (unrealisiert)     │              │
│  │ - Trade-Historie mit Timestamps     │              │
│  └──────┬──────────────────────────────┘             │
│         │                                             │
│  ┌──────▼──────────────────────────────┐             │
│  │      DailySettlement (Cron 22:00)    │             │
│  │                                      │             │
│  │ - berechnet Guthaben-Formel          │             │
│  │ - loggt Tagesbericht                 │             │
│  │ - prüft Abbruchbedingungen           │             │
│  └──────────────────────────────────────┘            │
│                                                       │
└─────────────────────────────────────────────────────┘
```

## Klassen

### InvestmentEngine
- Orchestrator, startet als Dauerprozess oder per Cron
- Konfigurierbare Intervalle (z.B. alle 30 Min während Börsenzeiten)
- Prüft vor jedem Zyklus: Guthaben > 0? Börse offen?
- Ruft AIAdvisor auf, leitet Entscheidung an TradeExecutor weiter

### AIAdvisor
- Einzige Komponente die die Anthropic API aufruft
- Wählt selbst das Modell pro Anfrage:
  - Haiku: günstige Routine-Checks ("hat sich was geändert?")
  - Sonnet: Standardanalysen, Kauf/Verkauf-Entscheidungen
  - Opus: komplexe Situationen, Strategie-Überprüfung
- Bekommt als Context: Portfolio-Stand, verfügbares Cash, Kursdaten,
  eigenes verbleibendes API-Guthaben, Trade-Historie
- Gibt strukturierte Entscheidung zurück:
  ```json
  {
    "action": "buy|sell|hold",
    "symbol": "AAPL",
    "amount_eur": 25.00,
    "reasoning": "...",
    "model_used": "claude-haiku-4-5-20251001",
    "urgency": "low|medium|high"
  }
  ```
- Muss Modellkosten pro Call selbst tracken und an BudgetTracker melden

### BudgetTracker
- Verwaltet das reale API-Guthaben
- Startwert: 5,00€
- Täglicher Abzug: 0,50€ (Grundgebühr, abgezogen bei DailySettlement)
- Addiert Guthaben-Erhöhung aus der Formel
- Loggt jeden API-Call mit Modell, Token-Count, Kosten
- Stellt `can_afford(model, estimated_tokens) -> bool` bereit
- Blockiert Calls wenn Guthaben nicht ausreicht

### TradeExecutor
- Empfängt Orders von AIAdvisor
- Holt aktuellen Kurs via `yfinance` zum Zeitpunkt der Ausführung
- Validiert: genug Cash im Portfolio? Symbol gültig?
- Bucht Trade ins Portfolio (PortfolioTracker)
- Erstellt unveränderlichen Log-Eintrag:
  ```json
  {
    "timestamp": "2026-04-10T14:32:05Z",
    "action": "buy",
    "symbol": "AAPL",
    "price": 187.32,
    "amount_eur": 25.00,
    "shares": 0.1334,
    "source": "yfinance"
  }
  ```
- Phase 2: ersetzt durch Matrix-Nachricht an Nutzer oder `pytr`-Call

### PortfolioTracker
- Speichert: Cash-Bestand, Positionen (Symbol, Shares, Einstandskurs)
- Berechnet aktuellen Portfoliowert (Cash + Positionen zu Live-Kursen)
- Berechnet unrealisierten P&L pro Position und gesamt
- Trade-Historie (append-only, nicht editierbar)
- Persistenz: SQLite-Datenbank `data/investment/portfolio.db`

### DailySettlement
- Läuft täglich um 22:00 (nach US-Börsenschluss)
- Berechnet Guthaben-Formel (siehe unten)
- Zieht Grundgebühr ab
- Erstellt Tagesbericht (JSON + menschenlesbar)
- Prüft Abbruchbedingungen:
  - Guthaben ≤ 0 → Experiment gescheitert
  - Tag 30 erreicht UND Portfolio > 100€ → Experiment erfolgreich

## Guthaben-Formel (DailySettlement)

Variablen:
- `portfolio_value` = aktueller Portfoliowert (Cash + Positionen)
- `start_capital` = 100€ (konstant)
- `prev_portfolio_value` = Portfoliowert des Vortages
- `daily_fee` = 0,50€
- `max_daily_reward` = 20€

Berechnung:
```
gesamt_gewinn = portfolio_value - start_capital
tages_gewinn  = portfolio_value - prev_portfolio_value

# Grunderhöhung: 10% vom Gesamtgewinn (nur wenn im Plus)
grund = max(0, gesamt_gewinn * 0.1)

# Bonus: 20% vom Tagesgewinn (nur wenn positiv)
bonus = max(0, tages_gewinn * 0.2)

# Cap bei 20€ pro Tag
reward = min(grund + bonus, max_daily_reward)

# Neues Guthaben
guthaben_neu = guthaben_alt - daily_fee + reward
```

Beispielrechnung Tag 1 (guter Tag):
- Portfolio: 110€ → gesamt_gewinn=10, tages_gewinn=10
- grund=1.00, bonus=2.00, reward=3.00
- guthaben: 5.00 - 0.50 + 3.00 = 7.50€

Beispielrechnung Tag 1 (schlechter Tag):
- Portfolio: 95€ → gesamt_gewinn=-5, tages_gewinn=-5
- grund=0, bonus=0, reward=0
- guthaben: 5.00 - 0.50 + 0 = 4.50€

Beispielrechnung Tag 10 (Stagnation bei 100€):
- guthaben: 5.00 - (10 × 0.50) + 0 = 0€ → GESCHEITERT

→ Die KI hat ohne jegliche Performance genau 10 Tage zum Überleben.

## Modellkosten (Stand April 2026, Anthropic API)

| Modell | Input/1M Token | Output/1M Token | ~Kosten pro Call |
|--------|----------------|-----------------|------------------|
| Haiku 4.5  | $1.00  | $5.00  | ~0,005€ |
| Sonnet 4.6 | $3.00  | $15.00 | ~0,02€  |
| Opus 4.6   | $15.00 | $75.00 | ~0,10€  |

Die KI muss diese Kosten kennen und in ihre Entscheidung einbeziehen.
Bei 5€ Start und 0,50€/Tag Grundgebühr:
- ~1000 Haiku-Calls möglich (bei 0 Performance)
- ~250 Sonnet-Calls möglich
- ~50 Opus-Calls möglich
- Realistischer Mix: ~200-400 Calls über 30 Tage

## AI-System-Prompt (Kern)

Die KI bekommt folgenden Kontext bei jedem Call:
1. Ihre Rolle: autonomer Investment-Advisor mit begrenztem Budget
2. Aktuelles Portfolio (Positionen, Cash, Gesamtwert)
3. Aktuelles API-Guthaben + verbleibende Tage
4. Letzte N Trades + deren Performance
5. Angeforderte Kursdaten (die KI kann spezifische Symbole anfragen)
6. Tageszeit + Börsenstatus (offen/geschlossen)
7. Modellkosten-Tabelle

Die KI antwortet mit strukturierter Entscheidung (siehe AIAdvisor).
Sie darf auch "hold" antworten und begründen warum.
Sie darf ein günstigeres Modell für den nächsten Check empfehlen.

## Sicherheitsmechanismen

- **Kein Margin/Hebel**: nur Cash-Trades, kein Kredit
- **Positionslimit**: max. 50% des Portfolios in einem Symbol
- **Trade-Log immutable**: append-only SQLite, kein UPDATE/DELETE
- **API-Budget hardcoded**: BudgetTracker blockiert bei ≤ 0, kein Override
- **Kill-Switch**: manueller Stopp jederzeit möglich
- **Kein Internet-Zugriff für KI**: nur strukturierte Kursdaten als Input,
  kein eigenständiges Web-Browsing

## Datenbank-Schema (SQLite)

```sql
CREATE TABLE portfolio (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    shares REAL NOT NULL,
    avg_entry_price REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    action TEXT NOT NULL CHECK(action IN ('buy', 'sell')),
    symbol TEXT NOT NULL,
    shares REAL NOT NULL,
    price REAL NOT NULL,
    amount_eur REAL NOT NULL,
    model_used TEXT NOT NULL,
    reasoning TEXT
);

CREATE TABLE budget_log (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    event_type TEXT NOT NULL, -- 'api_call', 'daily_fee', 'reward'
    model TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_eur REAL NOT NULL,
    balance_after REAL NOT NULL
);

CREATE TABLE daily_settlement (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL UNIQUE,
    portfolio_value REAL NOT NULL,
    cash REAL NOT NULL,
    gesamt_gewinn REAL NOT NULL,
    tages_gewinn REAL NOT NULL,
    reward REAL NOT NULL,
    daily_fee REAL NOT NULL,
    budget_before REAL NOT NULL,
    budget_after REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'success', 'failed'))
);
```

## Dateien

```
src/elder_berry/investment/
├── __init__.py
├── investment_engine.py    # InvestmentEngine
├── ai_advisor.py           # AIAdvisor
├── budget_tracker.py       # BudgetTracker
├── trade_executor.py       # TradeExecutor
├── portfolio_tracker.py    # PortfolioTracker
├── daily_settlement.py     # DailySettlement
└── models.py               # Dataclasses für Trade, Position, etc.

data/investment/
├── portfolio.db            # SQLite
└── daily_reports/          # JSON-Tagesberichte
    └── 2026-04-10.json

scripts/
└── start_investment.py     # Entry-Point
```

## Wo läuft das System?

- **Phase 1**: Tower (Windows) – lokaler Dauerprozess, yfinance für Kurse
- **Post-Phase 44**: potenziell auf Strato-Server (24/7 ohne Tower)
- Börsendaten nur während Handelszeiten relevant:
  - Xetra: 09:00–17:30 MEZ
  - NYSE/NASDAQ: 15:30–22:00 MEZ
  - → System aktiv: 09:00–22:00, danach nur DailySettlement

## Entscheidungen

### 1. Watchlist: Feste Liste, von KI erweiterbar
- Startliste: ~30 liquide Titel (DAX-30 + große US-Werte + 3-4 ETFs:
  MSCI World, S&P 500, Nasdaq-100)
- KI darf neue Symbole vorschlagen
- System validiert: Ticker bei yfinance verfügbar? Kursdaten der letzten 30 Tage?
- Wenn ja → automatisch zur Watchlist hinzugefügt

### 2. Frequenz-Limit: Keins (Selbstregulierung)
- Kein hartes Limit für API-Calls pro Tag
- KI kennt ihre Kosten und ihr Guthaben
- `BudgetTracker.can_afford()` blockt wenn Guthaben nicht reicht
- Unkontrolliertes Verhalten (z.B. 200 Opus-Calls an Tag 1) ist ein
  valides Ergebnis, kein Bug

### 3. Input: Nur Kursdaten, keine News
- Phase 1: ausschließlich Kursdaten via yfinance
- Keine News-Feeds, kein Web-Browsing
- Ziel: testen ob KI mit reiner Technischer Analyse arbeiten kann
- Phase 2: News als Upgrade möglich → A/B-Vergleich gegen Phase 1

## Abbruchbedingungen

| Bedingung | Ergebnis |
|-----------|----------|
| Guthaben ≤ 0 | GESCHEITERT |
| Tag 30 + Portfolio > 100€ | ERFOLGREICH |
| Tag 30 + Portfolio ≤ 100€ | GESCHEITERT |
| Manueller Stopp | ABGEBROCHEN |

## Beobachtungspunkte (was wollen wir lernen?)

1. Wie aggressiv/konservativ handelt die KI?
2. Wie wählt sie Modelle? Spart sie bei Routine, investiert bei Unsicherheit?
3. Wie reagiert sie wenn das Guthaben knapp wird? Panik oder Sparsamkeit?
4. Handelt sie rational oder zeigt sie Bias (z.B. Verlustaversion)?
5. Wie oft wählt sie "hold" vs. aktives Trading?
6. Wie verändert sich ihr Verhalten über die 30 Tage?
