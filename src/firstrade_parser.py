"""
firstrade_parser.py

Parses a Firstrade CSV transaction export and produces:
  - open_positions: list of Position dicts (symbol, quantity, avg_cost, broker)
  - realized_trades: list of RealizedTrade dicts (one entry per FIFO lot match)

FIFO matching: buys are consumed oldest-first against each sell.
Dividends, fees, and other non-trade rows are skipped for cost-basis purposes.
"""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Position:
    symbol: str
    quantity: float
    avg_cost: float        # average cost per share of remaining open lots
    cost_basis: float      # total cost of remaining open lots (avg_cost * quantity)
    broker: str = "firstrade"
    incomplete_history: bool = False   # True if CSV missing earlier buy lots for this symbol


@dataclass
class RealizedTrade:
    symbol: str
    quantity: float
    buy_price: float
    sell_price: float
    sell_date: str
    realized_pnl: float
    broker: str = "firstrade"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

TRADE_ACTIONS = {"buy", "sell"}


def parse(csv_path: str | Path) -> tuple[List[Position], List[RealizedTrade]]:
    """
    Parse a Firstrade CSV export.

    Returns:
        (open_positions, realized_trades)
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Firstrade CSV not found: {path}")

    rows = _load_rows(path)
    open_lots: Dict[str, deque] = {}       # symbol -> deque of [qty, price, date]
    realized_trades: List[RealizedTrade] = []
    incomplete_symbols: set = set()        # symbols that had unmatched sell lots

    for row in rows:
        action = row["Action"].strip().lower()
        if action not in TRADE_ACTIONS:
            continue

        symbol = row["Symbol"].strip().upper()
        quantity = abs(float(row["Quantity"]))   # real export uses negative qty for sells
        price = float(row["Price"])
        date_str = row["TradeDate"].strip()

        if action == "buy":
            if symbol not in open_lots:
                open_lots[symbol] = deque()
            open_lots[symbol].append([quantity, price, date_str])

        elif action == "sell":
            trades, had_oversell = _match_sell_fifo(symbol, quantity, price, date_str, open_lots)
            realized_trades.extend(trades)
            if had_oversell:
                incomplete_symbols.add(symbol)

    open_positions = _build_positions(open_lots, incomplete_symbols)
    return open_positions, realized_trades


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_rows(path: Path) -> List[dict]:
    """Read CSV and return rows sorted by date ascending.

    Secondary sort: within the same date, BUYs before SELLs.
    Firstrade CSV exports do not preserve intraday order and sometimes
    lists a SELL before the BUY that preceded it on the same day.
    Sorting BUYs first ensures same-day buy-then-sell sequences are
    processed correctly and avoids false oversell detections.
    """
    ACTION_ORDER = {"BUY": 0, "SELL": 1}

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip rows with no Symbol (e.g. blank lines, totals rows)
            if not row.get("Symbol", "").strip():
                continue
            row["_date"] = _parse_date(row["TradeDate"].strip())
            rows.append(row)
    rows.sort(key=lambda r: (r["_date"], ACTION_ORDER.get(r["Action"].strip().upper(), 99)))
    return rows


def _parse_date(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Unrecognized date format: {date_str!r} (expected YYYY-MM-DD)")


def _match_sell_fifo(
    symbol: str,
    sell_qty: float,
    sell_price: float,
    sell_date: str,
    open_lots: Dict[str, deque],
) -> tuple[List[RealizedTrade], bool]:
    """
    Consume buy lots FIFO and return (realized_trades, had_oversell).
    had_oversell is True if the sell exceeded available buy lots, meaning
    the CSV is missing earlier purchase history for this symbol.
    """
    trades = []
    lots = open_lots.get(symbol, deque())
    remaining = sell_qty

    while remaining > 0 and lots:
        lot = lots[0]          # [qty, price, date]
        lot_qty, lot_price, _ = lot

        if lot_qty <= remaining:
            # Entire lot consumed
            consumed = lot_qty
            lots.popleft()
        else:
            # Partial lot consumed
            consumed = remaining
            lot[0] -= consumed  # mutate in place

        pnl = (sell_price - lot_price) * consumed
        trades.append(
            RealizedTrade(
                symbol=symbol,
                quantity=consumed,
                buy_price=lot_price,
                sell_price=sell_price,
                sell_date=sell_date,
                realized_pnl=round(pnl, 4),
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
                incomplete_history=symbol in incomplete_symbols,
            )
        )
    return positions
