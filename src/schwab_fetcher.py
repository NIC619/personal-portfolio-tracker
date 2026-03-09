"""
schwab_fetcher.py

Fetches positions and transaction history from the Charles Schwab API
via the schwab-py library, and normalises the output into the same
Position / RealizedTrade types used by firstrade_parser.

Auth model:
  - schwab.auth.easy_client() handles OAuth2 + token file refresh
  - Access tokens expire every 30 min (auto-refreshed by the library)
  - Refresh tokens last 7 days — re-run auth if stale

Once you have your Schwab developer credentials, update config.yaml:
    schwab:
      app_key:    <your App Key>
      app_secret: <your App Secret>
      token_path: ./data/schwab_token.json
      callback_url: https://127.0.0.1:8182

Then run the one-time auth flow:
    python -c "from src.schwab_fetcher import authenticate; authenticate(cfg)"
"""

from __future__ import annotations

import warnings
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

# Re-use the same data types as firstrade_parser so aggregator.py gets a
# uniform interface regardless of which broker produced the data.
from src.firstrade_parser import Position, RealizedTrade

try:
    import schwab
    _SCHWAB_AVAILABLE = True
except ImportError:
    _SCHWAB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def authenticate(config: dict) -> None:
    """
    Run the one-time OAuth2 flow to generate a token file.
    Call this once from the command line before using fetch().
    """
    _require_schwab()
    cfg = _schwab_cfg(config)
    schwab.auth.easy_client(
        api_key=cfg["app_key"],
        app_secret=cfg["app_secret"],
        callback_url=cfg["callback_url"],
        token_path=cfg["token_path"],
    )
    print(f"Token saved to {cfg['token_path']}")


def fetch(config: dict) -> Tuple[List[Position], List[RealizedTrade]]:
    """
    Fetch open positions and realised trades from all linked Schwab accounts.

    Returns:
        (positions, realized_trades)  — same types as firstrade_parser.parse()
    """
    _require_schwab()
    cfg = _schwab_cfg(config)

    client = schwab.auth.easy_client(
        api_key=cfg["app_key"],
        app_secret=cfg["app_secret"],
        callback_url=cfg["callback_url"],
        token_path=cfg["token_path"],
    )

    account_hashes = _get_account_hashes(client)

    all_positions: List[Position] = []
    all_realized: List[RealizedTrade] = []

    for account_hash in account_hashes:
        positions = _fetch_positions(client, account_hash)
        realized = _fetch_realized_trades(client, account_hash)
        all_positions.extend(positions)
        all_realized.extend(realized)

    return all_positions, all_realized


def fetch_mock() -> Tuple[List[Position], List[RealizedTrade]]:
    """
    Return realistic mock Schwab data using the same types as fetch().
    Use this to test the aggregator and P&L engine before credentials arrive.

    Scenario:
      AAPL: 15 shares @ avg cost $170  (different lot from Firstrade position)
      NVDA: 10 shares @ avg cost $600  (same ticker as Firstrade — tests cross-broker)
      GOOGL: 5 shares @ avg cost $140
      AMZN: bought 8@$180, sold 3@$210 → realized $90, open 5@$180
    """
    positions = [
        Position(symbol="AAPL",  quantity=15.0, avg_cost=170.00, cost_basis=2550.00, broker="schwab"),
        Position(symbol="NVDA",  quantity=10.0, avg_cost=600.00, cost_basis=6000.00, broker="schwab"),
        Position(symbol="GOOGL", quantity=5.0,  avg_cost=140.00, cost_basis=700.00,  broker="schwab"),
        Position(symbol="AMZN",  quantity=5.0,  avg_cost=180.00, cost_basis=900.00,  broker="schwab"),
    ]

    realized = [
        RealizedTrade(
            symbol="AMZN",
            quantity=3.0,
            buy_price=180.00,
            sell_price=210.00,
            sell_date="2024-09-15",
            realized_pnl=90.00,
            broker="schwab",
        ),
        RealizedTrade(
            symbol="TSLA",
            quantity=5.0,
            buy_price=220.00,
            sell_price=195.00,
            sell_date="2024-11-03",
            realized_pnl=-125.00,
            broker="schwab",
        ),
    ]

    return positions, realized


# ---------------------------------------------------------------------------
# Internal — API calls
# ---------------------------------------------------------------------------

def _get_account_hashes(client) -> List[str]:
    """Return the accountHash for every linked account."""
    resp = client.get_account_numbers()
    _check_response(resp, "GET /accounts/accountNumbers")
    return [entry["hashValue"] for entry in resp.json()]


def _fetch_positions(client, account_hash: str) -> List[Position]:
    """Fetch open positions for one account and normalise to Position objects."""
    resp = client.get_account(account_hash, fields=[client.Account.Fields.POSITIONS])
    _check_response(resp, f"GET /accounts/{account_hash}")

    data = resp.json()
    raw_positions = (
        data.get("securitiesAccount", {}).get("positions", [])
    )

    positions = []
    for p in raw_positions:
        instrument = p.get("instrument", {})
        symbol = instrument.get("symbol", "").strip().upper()
        if not symbol:
            continue

        # Schwab returns longQuantity / shortQuantity separately
        qty = float(p.get("longQuantity", 0))
        if qty <= 0:
            continue

        avg_cost = float(p.get("averagePrice", 0))
        cost_basis = round(avg_cost * qty, 4)

        positions.append(
            Position(
                symbol=symbol,
                quantity=qty,
                avg_cost=avg_cost,
                cost_basis=cost_basis,
                broker="schwab",
            )
        )

    return positions


def _fetch_realized_trades(client, account_hash: str) -> List[RealizedTrade]:
    """
    Fetch YTD transaction history and reconstruct realized P&L via FIFO.

    Schwab's transaction API does not directly return per-lot P&L, so we
    re-run FIFO matching on the raw BUY/SELL transactions, same as we do
    for Firstrade. This keeps the P&L methodology consistent.
    """
    start = datetime(datetime.now().year, 1, 1)        # YTD
    end   = datetime.now() + timedelta(days=1)

    resp = client.get_transactions(
        account_hash,
        transaction_type=client.Transactions.TransactionType.TRADE,
        start_date=start,
        end_date=end,
    )
    _check_response(resp, f"GET /accounts/{account_hash}/transactions")

    raw_txns = resp.json()

    # Sort ascending by trade date before FIFO matching
    raw_txns.sort(key=lambda t: t.get("tradeDate", ""))

    open_lots: Dict[str, deque] = {}
    realized: List[RealizedTrade] = []

    for txn in raw_txns:
        item = txn.get("transactionItem", {})
        instrument = item.get("instrument", {})
        symbol = instrument.get("symbol", "").strip().upper()
        if not symbol:
            continue

        effect = item.get("positionEffect", "")
        qty    = abs(float(item.get("amount", 0)))
        price  = float(item.get("price", 0))
        date_str = txn.get("tradeDate", "")[:10]     # trim to YYYY-MM-DD

        if effect == "OPENING":
            if symbol not in open_lots:
                open_lots[symbol] = deque()
            open_lots[symbol].append([qty, price, date_str])

        elif effect == "CLOSING":
            realized.extend(
                _match_sell_fifo(symbol, qty, price, date_str, open_lots)
            )

    return realized


# ---------------------------------------------------------------------------
# Internal — FIFO (identical logic to firstrade_parser)
# ---------------------------------------------------------------------------

def _match_sell_fifo(
    symbol: str,
    sell_qty: float,
    sell_price: float,
    sell_date: str,
    open_lots: Dict[str, deque],
) -> List[RealizedTrade]:
    trades = []
    lots = open_lots.get(symbol, deque())
    remaining = sell_qty

    while remaining > 0 and lots:
        lot = lots[0]
        lot_qty, lot_price, _ = lot

        if lot_qty <= remaining:
            consumed = lot_qty
            lots.popleft()
        else:
            consumed = remaining
            lot[0] -= consumed

        pnl = (sell_price - lot_price) * consumed
        trades.append(
            RealizedTrade(
                symbol=symbol,
                quantity=consumed,
                buy_price=lot_price,
                sell_price=sell_price,
                sell_date=sell_date,
                realized_pnl=round(pnl, 4),
                broker="schwab",
            )
        )
        remaining -= consumed

    if remaining > 1e-9:
        warnings.warn(
            f"Oversell detected for {symbol} (Schwab): {remaining:.4f} shares "
            "sold with no matching buy lots in YTD history."
        )

    return trades


# ---------------------------------------------------------------------------
# Internal — helpers
# ---------------------------------------------------------------------------

def _schwab_cfg(config: dict) -> dict:
    cfg = config.get("schwab", {})
    for key in ("app_key", "app_secret", "token_path", "callback_url"):
        if not cfg.get(key) or cfg[key].startswith("YOUR_"):
            raise ValueError(
                f"Schwab config missing '{key}'. "
                "Fill in config.yaml with your developer credentials."
            )
    return cfg


def _require_schwab() -> None:
    if not _SCHWAB_AVAILABLE:
        raise ImportError(
            "schwab-py is not installed. Run: pip install schwab-py"
        )


def _check_response(resp, context: str) -> None:
    if resp.status_code != 200:
        raise RuntimeError(
            f"Schwab API error [{context}]: "
            f"HTTP {resp.status_code} — {resp.text[:200]}"
        )
