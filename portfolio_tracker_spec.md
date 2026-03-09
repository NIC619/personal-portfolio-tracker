# Personal Portfolio P&L Tracker — Build Specification

**Charles Schwab + Firstrade | Version 1.0 | CLI Tool Handoff**

---

## 1. Project Overview

A self-hosted, personal portfolio tracker that aggregates positions and transactions from Charles Schwab and Firstrade into a single view, focused on realized and unrealized P&L. Runs fully locally — no cloud subscriptions required.

### Goals
- Know exactly how much you have earned or lost across both brokers
- Track both realized P&L (closed positions) and unrealized P&L (open positions)
- Single unified view across Schwab + Firstrade
- Zero recurring cost — free APIs and CSV imports only
- Simple to run: one command refreshes everything

### Non-Goals
- Not a trading bot — read-only data, no order placement
- Not a multi-user app — local personal use only
- Not a real-time dashboard — polling on demand is sufficient

---

## 2. Architecture

### Data Sources

| Broker | Method | Data Available | Cost |
|--------|--------|----------------|------|
| Charles Schwab | Official API via `schwab-py` | Positions, balances, transaction history, real-time quotes | Free |
| Firstrade | Manual CSV export | Transaction history, positions snapshot | Free |
| Market Prices | `yfinance` (Yahoo Finance) | Real-time & historical prices for P&L calculation | Free |

### Component Diagram

```
schwab-py (OAuth2)  ──►  schwab_fetcher.py  ──►┐
                                                ├──►  aggregator.py  ──►  pnl_engine.py  ──►  display.py
firstrade CSV       ──►  firstrade_parser.py ──►┘
                                                              ▲
                                             yfinance (price quotes)
```

### Folder Structure

```
portfolio-tracker/
├── main.py                  # Entry point: run this to refresh
├── config.yaml              # API credentials, file paths
├── data/
│   ├── firstrade_export.csv # Drop Firstrade CSV here
│   └── cache.json           # Local price + position cache
├── src/
│   ├── schwab_fetcher.py    # Pulls data from Schwab API
│   ├── firstrade_parser.py  # Parses Firstrade CSV exports
│   ├── price_fetcher.py     # Fetches current prices via yfinance
│   ├── aggregator.py        # Merges all sources into unified positions
│   ├── pnl_engine.py        # Calculates realized + unrealized P&L
│   └── display.py           # Renders output table in terminal
├── requirements.txt
└── README.md
```

---

## 3. Data Source Details

### 3.1 Charles Schwab — schwab-py

Use the official Schwab Trader API via the `schwab-py` wrapper. Provides live account data without any manual export steps.

**Setup Steps:**
1. Create a developer account at [developer.schwab.com](https://developer.schwab.com) (separate from your brokerage login)
2. Register a new app, select **"Accounts and Trading Production"** as API Product
3. Set callback URL to `https://127.0.0.1:8182`
4. Wait for approval (typically 1–3 business days), then note your App Key and App Secret
5. Install: `pip install schwab-py`
6. Run the auth flow once to generate a token file (stored locally)

**Key API Calls Needed:**
- `GET /accounts` — balances per account
- `GET /accounts/{accountNumber}/positions` — open positions with cost basis
- `GET /accounts/{accountNumber}/transactions` — full trade history for realized P&L

**Token Refresh:**
Access tokens expire every 30 minutes. `schwab-py` handles refresh automatically when you pass a token file path. Refresh tokens last 7 days — re-authenticate if you haven't run the tracker in a week.

---

### 3.2 Firstrade — CSV Export

Firstrade has no official API. Export transaction history manually from the web UI and drop the file into `data/firstrade_export.csv`.

**Export Instructions:**
1. Log in at [invest.firstrade.com](https://invest.firstrade.com)
2. Go to **Accounts > History > Transaction History**
3. Select date range (export max range for full history)
4. Click **Download CSV** and save to `data/firstrade_export.csv`

**CSV Schema:**

| Column | Description |
|--------|-------------|
| Date | Trade date (MM/DD/YYYY) |
| Action | Buy, Sell, Dividend, etc. |
| Symbol | Ticker symbol |
| Description | Full name of security |
| Quantity | Number of shares |
| Price | Price per share at execution |
| Amount | Total value of transaction (negative = debit) |

---

### 3.3 Market Prices — yfinance

Use the `yfinance` Python library to fetch current prices for all held positions. Free, no API key required.

```python
import yfinance as yf
price = yf.Ticker('AAPL').fast_info['last_price']

# Batch fetch (preferred to avoid rate limits)
data = yf.download(['AAPL', 'MSFT', 'NVDA'], period='1d')
```

---

## 4. P&L Calculation Logic

### Unrealized P&L

For each open position:

```
unrealized_pnl     = (current_price - avg_cost_basis) * quantity
unrealized_pnl_pct = (unrealized_pnl / (avg_cost_basis * quantity)) * 100
```

- **Schwab**: avg cost basis comes directly from the positions API endpoint
- **Firstrade**: computed from CSV buy transactions using FIFO matching

### Realized P&L

Match sell transactions against buy lots using FIFO:

```
realized_pnl = (sell_price - buy_price) * quantity_sold   # per lot
```

For Schwab, use transaction history from the API. For Firstrade, parse all `Buy` and `Sell` rows from the CSV and match chronologically.

### Aggregated Summary Metrics

| Metric | Calculation | Scope |
|--------|-------------|-------|
| Total Portfolio Value | Sum of (current_price × quantity) | Both brokers |
| Total Cost Basis | Sum of (avg_cost × quantity) for open positions | Both brokers |
| Total Unrealized P&L | Total Portfolio Value − Total Cost Basis | Both brokers |
| Total Realized P&L | Sum of all closed trade gains/losses (YTD) | Both brokers |
| Overall Return % | (Unrealized + Realized) / Total Cost Basis × 100 | Both brokers |

---

## 5. Implementation Guide

### 5.1 Dependencies

```
# requirements.txt
schwab-py>=1.0.0
yfinance>=0.2.0
pandas>=2.0.0
pyyaml>=6.0
rich>=13.0.0          # pretty terminal output
python-dotenv>=1.0.0  # optional: for .env credential management
```

### 5.2 config.yaml

```yaml
schwab:
  app_key: YOUR_APP_KEY
  app_secret: YOUR_APP_SECRET
  token_path: ./data/schwab_token.json
  callback_url: https://127.0.0.1:8182

firstrade:
  csv_path: ./data/firstrade_export.csv

display:
  currency: USD
  show_zero_positions: false
```

### 5.3 schwab_fetcher.py

Authenticates with Schwab and returns normalized position and transaction data.

- Use `schwab.auth.easy_client()` for token-based auth with auto-refresh
- Fetch all linked account numbers first, then loop to get positions + transactions
- Normalize output to a standard dict: `{ symbol, quantity, avg_cost, current_value, broker }`

### 5.4 firstrade_parser.py

Parses the Firstrade CSV and reconstructs current positions + FIFO cost basis.

- Read CSV using pandas, parse `Date` column to datetime
- Filter rows where `Action` is `"Buy"` or `"Sell"` (skip dividends, fees, etc. for P&L)
- Use a FIFO queue per symbol to match sells against buy lots
- Return: open positions with computed `avg_cost`, and list of realized trades

### 5.5 aggregator.py

Merges positions from both brokers, de-duplicates symbols (same ticker may exist in both), and prepares a unified position list for the P&L engine.

### 5.6 pnl_engine.py

Core calculation module. Takes aggregated positions + current prices and computes:
- Per-position unrealized P&L and % return
- Total realized P&L from closed trades (YTD by default)
- Portfolio-level summary metrics

### 5.7 display.py

Uses the `rich` library to render a formatted terminal table.

| Column | Source |
|--------|--------|
| Symbol | aggregator |
| Broker | schwab / firstrade |
| Qty | positions data |
| Avg Cost | API or FIFO computation |
| Current Price | yfinance |
| Market Value | qty × current_price |
| Unrealized P&L ($) | pnl_engine |
| Unrealized P&L (%) | pnl_engine |
| Realized P&L (YTD) | pnl_engine |

### 5.8 main.py

Entry point — runs the full pipeline end to end.

```bash
python main.py             # Full refresh
python main.py --schwab    # Schwab only
python main.py --no-prices # Skip price fetch (use cached)
```

---

## 6. Suggested Build Order

1. Set up project structure, `requirements.txt`, `config.yaml`
2. Build `firstrade_parser.py` with a sample CSV (no API needed to test)
3. Build `price_fetcher.py` using yfinance
4. Build `pnl_engine.py` with mock data and validate calculations manually
5. Build `display.py` to render terminal output
6. Set up Schwab developer account + OAuth, build `schwab_fetcher.py`
7. Build `aggregator.py` to merge both sources
8. Wire everything together in `main.py`
9. Test against real data from both brokers, validate P&L vs broker UI

---

## 7. Known Gotchas & Tips

### Schwab
- App approval can take 1–3 days — apply before you start coding
- Refresh token expires in 7 days — run the tracker at least weekly or it requires full re-auth
- Cost basis from the API reflects what Schwab records — may differ if positions were transferred in
- Schwab returns positions with both long and short lots; filter for `longQuantity` for most use cases

### Firstrade
- CSV export does not include a current positions snapshot — you must reconstruct positions from trade history
- Dividend rows should be tracked separately (not part of cost basis), but can be included in overall returns
- Watch for stock splits in history — they affect FIFO cost basis calculation
- Re-export CSV periodically (e.g., weekly) to capture new trades

### General
- yfinance can be rate-limited with many symbols — batch with `yf.download(['AAPL','MSFT'], period='1d')`
- Cache prices locally in `cache.json` to avoid hitting yfinance on every run
- For FIFO matching, sort buy transactions by date ascending before processing sells

---

## 8. Optional Future Enhancements

- Export to CSV or Excel for spreadsheet analysis
- Streamlit web UI for a browser-based dashboard
- Email or Telegram daily P&L summary notification
- Historical P&L chart using `matplotlib` or `plotly`
- Dividend tracking as part of total return calculation
- Automatic Firstrade CSV fetch if Plaid becomes cost-effective in future
