"""
main.py

Entry point for the portfolio tracker.

Usage:
    python main.py                  # Full refresh (all sources)
    python main.py --firstrade      # Firstrade only
    python main.py --no-prices      # Use cached prices, skip yfinance fetch

Planned (not yet implemented):
    python main.py --schwab         # Schwab only
"""

from __future__ import annotations

import argparse
import sys
import warnings
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
    source.add_argument("--firstrade", action="store_true", help="Firstrade CSV only")
    source.add_argument("--schwab",    action="store_true", help="Schwab API only (not yet implemented)")
    parser.add_argument("--no-prices", action="store_true", help="Use cached prices, skip yfinance")
    parser.add_argument("--config",    default="config.yaml", help="Path to config file")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        template = Path("config.yaml.template")
        hint = f" Copy config.yaml.template to config.yaml and fill in your values." if template.exists() else ""
        sys.exit(f"Error: config file not found at '{path}'.{hint}")
    with open(p) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    config = _load_config(args.config)

    all_positions = []
    all_realized  = []

    # -----------------------------------------------------------------------
    # Firstrade
    # -----------------------------------------------------------------------
    if not args.schwab:   # run firstrade unless --schwab-only
        from src.firstrade_parser import parse as parse_firstrade

        csv_path = config.get("firstrade", {}).get("csv_path", "./data/firstrade_export.csv")
        ft_csv = Path(csv_path)

        if ft_csv.exists():
            print(f"Parsing Firstrade CSV: {ft_csv}")
            positions, realized = parse_firstrade(ft_csv)
            all_positions.extend(positions)
            all_realized.extend(realized)
            print(f"  {len(positions)} open position(s), {len(realized)} realized trade(s)")
        else:
            warnings.warn(
                f"Firstrade CSV not found at '{ft_csv}'. "
                "Export from invest.firstrade.com and place it there, or update config.yaml."
            )

    # -----------------------------------------------------------------------
    # Schwab (placeholder — requires dev account + OAuth setup)
    # -----------------------------------------------------------------------
    if args.schwab or not args.firstrade:
        # TODO: import and call schwab_fetcher once implemented
        if args.schwab:
            sys.exit("Schwab integration is not yet implemented. Coming soon.")

    if not all_positions:
        sys.exit("No positions loaded — nothing to display.")

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
    render(summary)


if __name__ == "__main__":
    main()
