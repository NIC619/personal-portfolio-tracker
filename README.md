# Personal Portfolio Tracker

A self-hosted CLI tool that aggregates positions and transactions from **Charles Schwab** and **Firstrade** into a single P&L view. Runs fully locally — no cloud subscriptions, no recurring cost.

## Features

- Realized and unrealized P&L across both brokers in one table
- FIFO cost basis from CSV exports (both Firstrade and Schwab)
- Live prices via Yahoo Finance (free, no API key)
- Local price cache (15-min TTL) to avoid redundant fetches
- Date range filtering — snapshot your portfolio at any point in time
- Flags positions where CSV history is incomplete

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp config.yaml.template config.yaml
```

The defaults work out of the box if you place your exports in `data/`. No credentials needed.

### 3. Export your transaction history

**Firstrade:**
1. Log in at [invest.firstrade.com](https://invest.firstrade.com)
2. Go to **Accounts → History → Transaction History**
3. Select the **maximum available date range**
4. Click **Download CSV** → save to `data/firstrade_export.csv`

**Schwab:**
1. Log in at [schwab.com](https://schwab.com)
2. Go to **Accounts → History → Export**
3. Select the **maximum available date range**
4. Save to `data/schwab_export.csv`

> Export the maximum date range each time — FIFO cost basis requires the full trade history from your first purchase in each symbol.

## Usage

```bash
# Both brokers (default)
python main.py

# Single broker
python main.py --firstrade
python main.py --schwab-csv

# Use cached prices instead of fetching live
python main.py --no-prices

# Filter by date range
python main.py --from 2024-01-01 --to 2024-12-31

# Portfolio state as of a specific date
python main.py --to 2025-05-31

# Realized P&L from a start date onward
python main.py --from 2025-01-01
```

### All flags

| Flag | Description |
|------|-------------|
| *(none)* | Both Firstrade and Schwab CSVs |
| `--firstrade` | Firstrade CSV only |
| `--schwab-csv` | Schwab CSV only |
| `--from YYYY-MM-DD` | Realized P&L start date (inclusive) |
| `--to YYYY-MM-DD` | Portfolio snapshot and P&L end date (inclusive) |
| `--no-prices` | Skip yfinance fetch, use cached prices |
| `--config PATH` | Path to config file (default: `config.yaml`) |

## Project Structure

```
portfolio-tracker/
├── main.py                  # Entry point
├── config.yaml              # Your paths (gitignored)
├── config.yaml.template     # Safe-to-commit config template
├── data/
│   ├── firstrade_export.csv # Firstrade CSV export (gitignored)
│   ├── schwab_export.csv    # Schwab CSV export (gitignored)
│   ├── firstrade_mock.csv   # Mock data for tests
│   └── cache.json           # Local price cache (gitignored)
├── src/
│   ├── firstrade_parser.py  # Parses Firstrade CSV, FIFO cost basis
│   ├── schwab_parser.py     # Parses Schwab CSV, FIFO cost basis
│   ├── schwab_fetcher.py    # Schwab API client (for future use)
│   ├── price_fetcher.py     # Yahoo Finance prices with local cache
│   ├── aggregator.py        # Merges positions from multiple brokers
│   ├── pnl_engine.py        # Unrealized + realized P&L calculations
│   └── display.py           # Rich terminal table rendering
└── tests/
    └── test_pnl.py          # P&L validation against known mock data
```

## Running Tests

```bash
python tests/test_pnl.py
```

Validates FIFO matching, partial lot consumption, dividend skipping, and all portfolio-level metrics against hand-calculated expected values.

## Known Limitations

- **CSV ordering:** Neither Firstrade nor Schwab exports include timestamps. Same-day trades are assumed buy-then-sell. Genuine same-day sell-then-buy sequences may produce slightly different cost basis.
- **CSV history:** If your export doesn't go back to your first trade in a symbol, that position is flagged with `*` and the cost basis will be understated. Re-export with the maximum date range to fix.
- **Schwab cost basis:** Reflects what Schwab records — may differ for positions transferred in from another broker.
- **Prices:** Yahoo Finance data is delayed ~15 min and occasionally unavailable for thinly traded symbols. Those positions are excluded from the unrealized P&L calculation with a warning.
