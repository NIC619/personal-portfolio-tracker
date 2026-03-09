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


def render(summary: PortfolioSummary, date_from: str | None = None, date_to: str | None = None) -> None:
    """Print the full portfolio view to the terminal."""
    console.print()
    _render_positions_table(summary.positions)
    console.print()
    _render_summary_table(summary, date_from=date_from, date_to=date_to)
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

    has_incomplete = any(p.incomplete_history for p in positions)

    for p in sorted(positions, key=lambda x: x.symbol):
        symbol_cell = Text()
        symbol_cell.append(p.symbol, style="bold white")
        if p.incomplete_history:
            symbol_cell.append(" *", style="bold yellow")

        avg_cost_cell = Text()
        avg_cost_cell.append(f"${p.avg_cost:,.2f}", style="yellow" if p.incomplete_history else "")

        table.add_row(
            symbol_cell,
            p.broker,
            f"{p.quantity:,.4f}".rstrip("0").rstrip("."),
            avg_cost_cell,
            f"${p.current_price:,.2f}",
            f"${p.market_value:,.2f}",
            _pnl_text(p.unrealized_pnl, dollar=True),
            _pnl_text(p.unrealized_pnl_pct, dollar=False),
        )

    console.print(table)

    if has_incomplete:
        console.print(
            "  [yellow]*[/yellow] Cost basis incomplete — CSV missing earlier buy history. "
            "Re-export with a wider date range to fix.",
            highlight=False,
        )


def _render_summary_table(summary: PortfolioSummary, date_from: str | None = None, date_to: str | None = None) -> None:
    if date_from or date_to:
        range_parts = []
        if date_from:
            range_parts.append(f"from {date_from}")
        if date_to:
            range_parts.append(f"to {date_to}")
        title = f"Portfolio Summary ({', '.join(range_parts)})"
    else:
        title = "Portfolio Summary"

    table = Table(
        title=title,
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
