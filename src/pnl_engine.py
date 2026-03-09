"""
pnl_engine.py

Core P&L calculation module. Accepts:
  - positions:       list of Position dicts/objects (from firstrade_parser or schwab_fetcher)
  - prices:          dict of {symbol: current_price}
  - realized_trades: list of RealizedTrade dicts/objects

Produces:
  - PositionPnL per open position (unrealized P&L)
  - PortfolioSummary (aggregated metrics)

All monetary values are in USD, rounded to 2 decimal places in output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocols — so this module works with dicts OR dataclass objects
# ---------------------------------------------------------------------------

@runtime_checkable
class PositionLike(Protocol):
    symbol: str
    quantity: float
    avg_cost: float
    cost_basis: float
    broker: str


@runtime_checkable
class RealizedTradeLike(Protocol):
    symbol: str
    quantity: float
    buy_price: float
    sell_price: float
    realized_pnl: float
    broker: str


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------

@dataclass
class PositionPnL:
    symbol: str
    broker: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    cost_basis: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


@dataclass
class PortfolioSummary:
    total_market_value: float
    total_cost_basis: float
    total_unrealized_pnl: float
    total_realized_pnl: float
    overall_return_pct: float
    positions: List[PositionPnL]

    def display(self) -> str:
        lines = [
            "=" * 60,
            "PORTFOLIO SUMMARY",
            "=" * 60,
            f"  Market Value:      ${self.total_market_value:>12,.2f}",
            f"  Cost Basis:        ${self.total_cost_basis:>12,.2f}",
            f"  Unrealized P&L:    ${self.total_unrealized_pnl:>12,.2f}",
            f"  Realized P&L:      ${self.total_realized_pnl:>12,.2f}",
            f"  Overall Return:    {self.overall_return_pct:>11.2f}%",
            "-" * 60,
            f"  {'Symbol':<8} {'Broker':<12} {'Qty':>6}  {'AvgCost':>8}  {'Price':>8}  "
            f"{'MktVal':>10}  {'UnrPnL$':>10}  {'UnrPnL%':>8}",
            "-" * 60,
        ]
        for p in sorted(self.positions, key=lambda x: x.symbol):
            pnl_sign = "+" if p.unrealized_pnl >= 0 else ""
            lines.append(
                f"  {p.symbol:<8} {p.broker:<12} {p.quantity:>6.2f}  "
                f"${p.avg_cost:>7.2f}  ${p.current_price:>7.2f}  "
                f"${p.market_value:>9,.2f}  "
                f"{pnl_sign}${p.unrealized_pnl:>9,.2f}  "
                f"{pnl_sign}{p.unrealized_pnl_pct:>7.2f}%"
            )
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def calculate(
    positions: List,
    prices: Dict[str, float],
    realized_trades: List,
) -> PortfolioSummary:
    """
    Compute full portfolio P&L.

    Args:
        positions:       Open positions (Position objects or compatible dicts).
        prices:          Current market prices keyed by symbol.
        realized_trades: Closed trade records for realized P&L.

    Returns:
        PortfolioSummary with per-position and aggregate metrics.
    """
    position_pnls = []

    for pos in positions:
        symbol, qty, avg_cost, cost_basis, broker = _unpack_position(pos)

        price = prices.get(symbol)
        if price is None:
            import warnings
            warnings.warn(f"No price found for {symbol} — skipping from unrealized P&L.")
            continue

        market_value = qty * price
        unrealized_pnl = (price - avg_cost) * qty
        unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis != 0 else 0.0

        position_pnls.append(
            PositionPnL(
                symbol=symbol,
                broker=broker,
                quantity=qty,
                avg_cost=round(avg_cost, 4),
                current_price=round(price, 4),
                market_value=round(market_value, 2),
                cost_basis=round(cost_basis, 2),
                unrealized_pnl=round(unrealized_pnl, 2),
                unrealized_pnl_pct=round(unrealized_pnl_pct, 4),
            )
        )

    total_market_value = sum(p.market_value for p in position_pnls)
    total_cost_basis = sum(p.cost_basis for p in position_pnls)
    total_unrealized_pnl = sum(p.unrealized_pnl for p in position_pnls)
    total_realized_pnl = sum(_unpack_realized_pnl(t) for t in realized_trades)

    overall_return_pct = (
        (total_unrealized_pnl + total_realized_pnl) / total_cost_basis * 100
        if total_cost_basis != 0
        else 0.0
    )

    return PortfolioSummary(
        total_market_value=round(total_market_value, 2),
        total_cost_basis=round(total_cost_basis, 2),
        total_unrealized_pnl=round(total_unrealized_pnl, 2),
        total_realized_pnl=round(total_realized_pnl, 2),
        overall_return_pct=round(overall_return_pct, 4),
        positions=position_pnls,
    )


# ---------------------------------------------------------------------------
# Internal helpers — support both dataclass objects and plain dicts
# ---------------------------------------------------------------------------

def _unpack_position(pos) -> tuple:
    if isinstance(pos, dict):
        return (
            pos["symbol"],
            float(pos["quantity"]),
            float(pos["avg_cost"]),
            float(pos["cost_basis"]),
            pos.get("broker", "unknown"),
        )
    return pos.symbol, pos.quantity, pos.avg_cost, pos.cost_basis, pos.broker


def _unpack_realized_pnl(trade) -> float:
    if isinstance(trade, dict):
        return float(trade["realized_pnl"])
    return float(trade.realized_pnl)
