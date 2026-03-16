"""
schwab_parser.py

Parses a Schwab transaction history CSV export and produces:
  - open_positions: list of Position objects (symbol, quantity, avg_cost, broker)
  - realized_trades: list of RealizedTrade objects (one entry per FIFO lot match)

Export instructions:
  schwab.com → Accounts → History → Export (select max date range)

CSV schema:
  "Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"

  - Date:      MM/DD/YYYY
  - Action:    Buy / Sell / Qualified Dividend / MoneyLink Deposit / etc.
  - Quantity:  Always positive; direction determined by Action
  - Price:     Dollar-prefixed string, e.g. "$71.23" (empty for non-trades)
  - Amount:    Dollar-prefixed string, e.g. "-$997.24"

FIFO matching: same logic as firstrade_parser — buys consumed oldest-first.
Same-day sort: BUYs processed before SELLs within each date (Schwab CSV
is newest-first and does not preserve intraday order).
"""

from __future__ import annotations

import csv
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from src.firstrade_parser import Position, RealizedTrade

TRADE_ACTIONS = {"buy", "sell"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(
    csv_path: str | Path,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> tuple[List[Position], List[RealizedTrade]]:
    """
    Parse a Schwab CSV export.

    Args:
        csv_path:   Path to the exported CSV file.
        start_date: If given, realized trades with sell_date < start_date are
                    excluded (but still used for FIFO so cost basis stays accurate).
        end_date:   If given, only transactions on or before this date are
                    processed. Open positions reflect portfolio state at end_date.

    Returns:
        (open_positions, realized_trades)
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Schwab CSV not found: {path}")

    rows = _load_rows(path)

    if end_date:
        rows = [r for r in rows if r["_date"] <= end_date]

    open_lots: Dict[str, deque] = {}
    all_realized: List[RealizedTrade] = []
    incomplete_symbols: set = set()

    for row in rows:
        action = row["Action"].strip().lower()
        if action not in TRADE_ACTIONS:
            continue

        symbol = row["Symbol"].strip().upper()
        if not symbol:
            continue

        quantity = float(row["Quantity"].strip())
        price = _parse_money(row["Price"])
        date_str = row["_date"].strftime("%Y-%m-%d")

        if action == "buy":
            if symbol not in open_lots:
                open_lots[symbol] = deque()
            open_lots[symbol].append([quantity, price, date_str])

        elif action == "sell":
            trades, had_oversell = _match_sell_fifo(symbol, quantity, price, date_str, open_lots)
            all_realized.extend(trades)
            if had_oversell:
                incomplete_symbols.add(symbol)

    realized_trades = [
        t for t in all_realized
        if (start_date is None or datetime.strptime(t.sell_date, "%Y-%m-%d") >= start_date)
    ]

    open_positions = _build_positions(open_lots, incomplete_symbols)
    return open_positions, realized_trades


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_rows(path: Path) -> List[dict]:
    """Read CSV, parse dates, and sort ascending with BUYs before SELLs per day."""
    ACTION_ORDER = {"buy": 0, "sell": 1}

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("Symbol", "").strip() and row.get("Action", "").strip().lower() not in TRADE_ACTIONS:
                continue
            date_str = row.get("Date", "").strip()
            if not date_str:
                continue
            row["_date"] = _parse_date(date_str)
            rows.append(row)

    rows.sort(key=lambda r: (r["_date"], ACTION_ORDER.get(r["Action"].strip().lower(), 99)))
    return rows


def _parse_date(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError:
        raise ValueError(f"Unrecognized date format: {date_str!r} (expected MM/DD/YYYY)")


def _parse_money(value: str) -> float:
    """Strip dollar signs, commas and parse to float. Returns 0.0 for empty."""
    cleaned = value.strip().replace("$", "").replace(",", "")
    return float(cleaned) if cleaned else 0.0


def _match_sell_fifo(
    symbol: str,
    sell_qty: float,
    sell_price: float,
    sell_date: str,
    open_lots: Dict[str, deque],
) -> tuple[List[RealizedTrade], bool]:
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

    had_oversell = remaining > 1e-9
    return trades, had_oversell


def _build_positions(open_lots: Dict[str, deque], incomplete_symbols: set) -> List[Position]:
    positions = []
    for symbol, lots in open_lots.items():
        if not lots:
            continue
        total_qty = sum(lot[0] for lot in lots)
        if total_qty < 1e-9:
            continue
        total_cost = sum(lot[0] * lot[1] for lot in lots)
        avg_cost = total_cost / total_qty
        positions.append(
            Position(
                symbol=symbol,
                quantity=round(total_qty, 6),
                avg_cost=round(avg_cost, 6),
                cost_basis=round(total_cost, 4),
                broker="schwab",
                incomplete_history=symbol in incomplete_symbols,
            )
        )
    return positions
