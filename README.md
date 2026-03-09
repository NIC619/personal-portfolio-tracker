# Personal Portfolio Tracker

A self-hosted CLI tool that aggregates positions and transactions from **Charles Schwab** and **Firstrade** into a single P&L view. Runs fully locally — no cloud subscriptions, no recurring cost.

## Features

- Realized and unrealized P&L across both brokers
- FIFO cost basis calculation from Firstrade CSV exports
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

Edit `config.yaml` with your paths. The Schwab fields can be left as placeholders until you have API access.

### 3. Add your Firstrade export

1. Log in at [invest.firstrade.com](https://invest.firstrade.com)
2. Go to **Accounts → History → Transaction History**
3. Select the maximum available date range
4. Click **Download CSV** and save to `data/firstrade_export.csv`

## Usage

```bash
# Firstrade only (default while Schwab access is pending)
python main.py --firstrade

# Use cached prices instead of fetching live
python main.py --firstrade --no-prices

# Filter by date range
python main.py --firstrade --from 2024-01-01 --to 2024-12-31

# Portfolio state as of a specific date
python main.py --firstrade --to 2025-05-31

# Schwab mock data (test without credentials)
python main.py --schwab-mock

# Both brokers (once Schwab credentials are set up)
python main.py
```

### All flags

| Flag | Description |
|------|-------------|
| `--firstrade` | Firstrade CSV only |
| `--schwab` | Schwab API only (requires credentials) |
| `--schwab-mock` | Schwab mock data for testing |
| `--from YYYY-MM-DD` | Realized P&L start date (inclusive) |
| `--to YYYY-MM-DD` | Portfolio snapshot and P&L end date (inclusive) |
| `--no-prices` | Skip yfinance fetch, use cached prices |
| `--config PATH` | Path to config file (default: `config.yaml`) |

## Schwab Setup

Schwab requires a one-time developer account and OAuth flow.

1. Apply at [developer.schwab.com](https://developer.schwab.com) — approval takes 1–3 days
2. Create an app with **"Accounts and Trading Production"** as the API product
3. Set callback URL to `https://127.0.0.1:8182`
4. Fill in `app_key`, `app_secret`, and `callback_url` in `config.yaml`
5. Run the one-time auth flow:
   ```bash
   python -c "
   import yaml
   from src.schwab_fetcher import authenticate
   authenticate(yaml.safe_load(open('config.yaml')))
   "
   ```
6. A token file will be saved to `data/schwab_token.json` and auto-refreshed on future runs

> **Note:** Schwab refresh tokens expire after 7 days. Re-run the auth flow if you haven't used the tracker in a week.

## Project Structure

```
portfolio-tracker/
├── main.py                  # Entry point
├── config.yaml              # Your credentials and paths (gitignored)
├── config.yaml.template     # Safe-to-commit config template
├── data/
│   ├── firstrade_export.csv # Drop your Firstrade CSV here (gitignored)
│   ├── firstrade_mock.csv   # Mock data for testing
│   └── cache.json           # Local price cache (gitignored)
├── src/
│   ├── firstrade_parser.py  # Parses Firstrade CSV, FIFO cost basis
│   ├── schwab_fetcher.py    # Schwab API client + mock
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

Tests validate FIFO matching, partial lot consumption, dividend skipping, and all portfolio-level metrics against hand-calculated expected values.

## Known Limitations

- **Firstrade CSV ordering:** The export does not include timestamps. Same-day trades are assumed to be buy-then-sell. If you had genuine same-day sell-then-buy sequences, cost basis may differ slightly.
- **Firstrade CSV history:** If your export doesn't cover the full history for a position, the symbol will be flagged with `*` and the cost basis will be understated. Re-export with the maximum date range to fix.
- **Schwab cost basis:** Reflects what Schwab records — may differ for positions transferred in from another broker.
- **Prices:** Yahoo Finance data is delayed and occasionally unavailable for thinly traded symbols.
