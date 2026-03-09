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

    for row in rows:
        action = row["Action"].strip().lower()
        if action not in TRADE_ACTIONS:
            continue

        symbol = row["Symbol"].strip().upper()
        quantity = float(row["Quantity"])
        price = float(row["Price"])
        date_str = row["Date"].strip()

        if action == "buy":
            if symbol not in open_lots:
                open_lots[symbol] = deque()
            open_lots[symbol].append([quantity, price, date_str])

        elif action == "sell":
            trades = _match_sell_fifo(symbol, quantity, price, date_str, open_lots)
            realized_trades.extend(trades)

    open_positions = _build_positions(open_lots)
    return open_positions, realized_trades


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_rows(path: Path) -> List[dict]:
    """Read CSV and return rows sorted by date ascending."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip rows with no Symbol (e.g. blank lines, totals rows)
            if not row.get("Symbol", "").strip():
                continue
            row["_date"] = _parse_date(row["Date"].strip())
            rows.append(row)
    rows.sort(key=lambda r: r["_date"])
    return rows


def _parse_date(date_str: str) -> datetime:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {date_str!r}")


def _match_sell_fifo(
    symbol: str,
    sell_qty: float,
    sell_price: float,
    sell_date: str,
    open_lots: Dict[str, deque],
) -> List[RealizedTrade]:
    """Consume buy lots FIFO and return one RealizedTrade per lot consumed."""
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

    if remaining > 0:
        # Sold more than we have on record — warn but don't crash
        import warnings
        warnings.warn(
            f"Oversell detected for {symbol}: {remaining} shares sold with no matching buy lots. "
            "Check your CSV for missing history."
        )

    return trades


def _build_positions(open_lots: Dict[str, deque]) -> List[Position]:
    positions = []
    for symbol, lots in open_lots.items():
        if not lots:
            continue
        total_qty = sum(lot[0] for lot in lots)
        if total_qty <= 0:
            continue
        total_cost = sum(lot[0] * lot[1] for lot in lots)
        avg_cost = total_cost / total_qty
        positions.append(
            Position(
                symbol=symbol,
                quantity=round(total_qty, 6),
                avg_cost=round(avg_cost, 6),
                cost_basis=round(total_cost, 4),
            )
        )
    return positions
