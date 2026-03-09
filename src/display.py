"""
display.py

Renders portfolio P&L to the terminal using the `rich` library.

Produces two tables:
  1. Per-position breakdown (symbol, broker, qty, avg cost, price, market value, unrealized P&L)
  2. Portfolio summary (total value, cost basis, unrealized/realized P&L, overall return)
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from src.pnl_engine import PortfolioSummary, PositionPnL

console = Console()


def render(summary: PortfolioSummary) -> None:
    """Print the full portfolio view to the terminal."""
    console.print()
    _render_positions_table(summary.positions)
    console.print()
    _render_summary_table(summary)
    console.print()


# ---------------------------------------------------------------------------
# Internal renderers
# ---------------------------------------------------------------------------

def _render_positions_table(positions: list[PositionPnL]) -> None:
    table = Table(
        title="Open Positions",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold white",
    )

    table.add_column("Symbol",         style="bold white",  justify="left",  no_wrap=True)
    table.add_column("Broker",         style="dim",          justify="left",  no_wrap=True)
    table.add_column("Qty",            justify="right",      no_wrap=True)
    table.add_column("Avg Cost",       justify="right",      no_wrap=True)
    table.add_column("Price",          justify="right",      no_wrap=True)
    table.add_column("Mkt Value",      justify="right",      no_wrap=True)
    table.add_column("Unr P&L ($)",    justify="right",      no_wrap=True)
    table.add_column("Unr P&L (%)",    justify="right",      no_wrap=True)

    for p in sorted(positions, key=lambda x: x.symbol):
        table.add_row(
            p.symbol,
            p.broker,
            f"{p.quantity:,.4f}".rstrip("0").rstrip("."),
            f"${p.avg_cost:,.2f}",
            f"${p.current_price:,.2f}",
            f"${p.market_value:,.2f}",
            _pnl_text(p.unrealized_pnl, dollar=True),
            _pnl_text(p.unrealized_pnl_pct, dollar=False),
        )

    console.print(table)


def _render_summary_table(summary: PortfolioSummary) -> None:
    table = Table(
        title="Portfolio Summary",
        box=box.SIMPLE_HEAVY,
        show_header=False,
        title_style="bold white",
        min_width=40,
    )

    table.add_column("Metric", style="dim",        justify="left")
    table.add_column("Value",  style="bold white",  justify="right")

    table.add_row("Market Value",     f"${summary.total_market_value:>12,.2f}")
    table.add_row("Cost Basis",       f"${summary.total_cost_basis:>12,.2f}")
    table.add_row("Unrealized P&L",   _pnl_text(summary.total_unrealized_pnl, dollar=True))
    table.add_row("Realized P&L",     _pnl_text(summary.total_realized_pnl,   dollar=True))
    table.add_row("Overall Return",   _pnl_text(summary.overall_return_pct,   dollar=False))

    console.print(table)


def _pnl_text(value: float, dollar: bool) -> Text:
    if value > 0:
        color = "green"
        prefix = "+"
    elif value < 0:
        color = "red"
        prefix = ""
    else:
        color = "white"
        prefix = ""

    if dollar:
        formatted = f"{prefix}${value:,.2f}"
    else:
        formatted = f"{prefix}{value:.2f}%"

    return Text(formatted, style=color)
