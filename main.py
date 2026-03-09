"""
main.py

Entry point for the portfolio tracker.

Usage:
    python main.py                              # Firstrade + Schwab (when credentials ready)
    python main.py --firstrade                  # Firstrade CSV only
    python main.py --schwab                     # Schwab API only
    python main.py --schwab-mock                # Schwab mock data (no credentials needed)
    python main.py --no-prices                  # Use cached prices, skip yfinance fetch
    python main.py --from 2023-03-09            # Realized P&L from this date onward
    python main.py --to 2025-05-31              # Portfolio state and P&L up to this date
    python main.py --from 2024-01-01 --to 2024-12-31  # Full year range
"""

from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Personal portfolio P&L tracker — Schwab + Firstrade"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--firstrade",   action="store_true", help="Firstrade CSV only")
    source.add_argument("--schwab",      action="store_true", help="Schwab API only (requires credentials)")
    source.add_argument("--schwab-mock", action="store_true", help="Schwab mock data — test without credentials")
    parser.add_argument("--no-prices",   action="store_true", help="Use cached prices, skip yfinance")
    parser.add_argument("--config",      default="config.yaml", help="Path to config file")
    parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD",
                        help="Realized P&L start date (inclusive)")
    parser.add_argument("--to",   dest="date_to",   metavar="YYYY-MM-DD",
                        help="Portfolio snapshot and P&L end date (inclusive)")
    return parser.parse_args()


def _parse_date_arg(value: str | None, label: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        sys.exit(f"Invalid {label} date '{value}' — expected format: YYYY-MM-DD")


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        template = Path("config.yaml.template")
        hint = " Copy config.yaml.template to config.yaml and fill in your values." if template.exists() else ""
        sys.exit(f"Error: config file not found at '{path}'.{hint}")
    with open(p) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    config = _load_config(args.config)

    date_from = _parse_date_arg(args.date_from, "--from")
    date_to   = _parse_date_arg(args.date_to,   "--to")

    if date_from and date_to and date_from > date_to:
        sys.exit(f"--from ({args.date_from}) must be before --to ({args.date_to})")

    sources = []

    # -----------------------------------------------------------------------
    # Firstrade
    # -----------------------------------------------------------------------
    if not args.schwab and not args.schwab_mock:
        from src.firstrade_parser import parse as parse_firstrade

        csv_path = config.get("firstrade", {}).get("csv_path", "./data/firstrade_export.csv")
        ft_csv = Path(csv_path)

        if ft_csv.exists():
            print(f"Parsing Firstrade CSV: {ft_csv}")
            ft_data = parse_firstrade(ft_csv, start_date=date_from, end_date=date_to)
            sources.append(ft_data)
            print(f"  {len(ft_data[0])} open position(s), {len(ft_data[1])} realized trade(s)")
        else:
            warnings.warn(
                f"Firstrade CSV not found at '{ft_csv}'. "
                "Export from invest.firstrade.com and place it there, or update config.yaml."
            )

    # -----------------------------------------------------------------------
    # Schwab — live API
    # -----------------------------------------------------------------------
    if args.schwab:
        from src.schwab_fetcher import fetch as fetch_schwab

        print("Fetching Schwab positions and transactions...")
        schwab_data = fetch_schwab(config)
        sources.append(schwab_data)
        print(f"  {len(schwab_data[0])} open position(s), {len(schwab_data[1])} realized trade(s)")

    # -----------------------------------------------------------------------
    # Schwab — mock (for testing before credentials arrive)
    # -----------------------------------------------------------------------
    if args.schwab_mock:
        from src.schwab_fetcher import fetch_mock as fetch_schwab_mock

        print("Loading Schwab mock data...")
        schwab_data = fetch_schwab_mock()
        sources.append(schwab_data)
        print(f"  {len(schwab_data[0])} open position(s), {len(schwab_data[1])} realized trade(s)")

    if not sources:
        sys.exit("No positions loaded — nothing to display.")

    # -----------------------------------------------------------------------
    # Aggregate
    # -----------------------------------------------------------------------
    from src.aggregator import merge

    all_positions, all_realized = merge(*sources)

    # -----------------------------------------------------------------------
    # Price fetch
    # -----------------------------------------------------------------------
    from src.price_fetcher import fetch as fetch_prices

    symbols = list({p.symbol for p in all_positions})
    force_refresh = not args.no_prices

    print(f"Fetching prices for: {', '.join(sorted(symbols))}" + (" (from cache)" if args.no_prices else ""))
    prices = fetch_prices(symbols, force_refresh=force_refresh)

    # -----------------------------------------------------------------------
    # P&L calculation + display
    # -----------------------------------------------------------------------
    from src.pnl_engine import calculate
    from src.display import render

    summary = calculate(all_positions, prices, all_realized)
    render(summary, date_from=args.date_from, date_to=args.date_to)


if __name__ == "__main__":
    main()
