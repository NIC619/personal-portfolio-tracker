"""
test_pnl.py

Validates firstrade_parser and pnl_engine using data/firstrade_mock.csv.

Run with:
    python tests/test_pnl.py

Expected mock CSV transactions:
  AAPL: Buy 10@150, Buy 5@160, Sell 8@180
    → FIFO: consumes 8 from lot1 (150), leaving 2@150 + 5@160
    → Realized PnL: (180-150)*8 = $240.00
    → Open: 7 shares, avg_cost = (2*150 + 5*160)/7 = 1100/7 ≈ $157.1429

  MSFT: Buy 5@380, Sell 2@400, Buy 3@390
    → FIFO: consumes 2 from lot1 (380), leaving 3@380, then adds 3@390
    → Realized PnL: (400-380)*2 = $40.00
    → Open: 6 shares, avg_cost = (3*380 + 3*390)/6 = 2310/6 = $385.00

  NVDA: Buy 3@800, never sold
    → Open: 3 shares, avg_cost = $800.00

Mock prices used for unrealized P&L:
  AAPL: $185.00  → unrealized = (185 - 157.1429) * 7 ≈ $195.00
  MSFT: $420.00  → unrealized = (420 - 385) * 6  = $210.00
  NVDA: $875.00  → unrealized = (875 - 800) * 3  = $225.00
"""

import sys
import os

# Allow running from project root or tests/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.firstrade_parser import parse
from src.pnl_engine import calculate

MOCK_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "firstrade_mock.csv")

MOCK_PRICES = {
    "AAPL": 185.00,
    "MSFT": 420.00,
    "NVDA": 875.00,
}

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def approx_equal(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def check(label: str, actual, expected, tol: float = 0.01) -> bool:
    ok = approx_equal(actual, expected, tol)
    status = PASS if ok else FAIL
    print(f"  [{status}] {label}: got {actual:.4f}, expected {expected:.4f}")
    return ok


def run_tests():
    print("\n=== Parsing firstrade_mock.csv ===")
    positions, realized_trades = parse(MOCK_CSV)

    # Index by symbol for easy lookup
    pos_by_symbol = {p.symbol: p for p in positions}
    realized_by_symbol: dict[str, float] = {}
    for t in realized_trades:
        realized_by_symbol[t.symbol] = realized_by_symbol.get(t.symbol, 0.0) + t.realized_pnl

    print(f"\n  Open positions found: {[p.symbol for p in positions]}")
    print(f"  Realized trade records: {len(realized_trades)}")
    print()

    failures = 0

    # -----------------------------------------------------------------------
    # AAPL position checks
    # -----------------------------------------------------------------------
    print("--- AAPL ---")
    aapl = pos_by_symbol.get("AAPL")
    if aapl is None:
        print(f"  [{FAIL}] AAPL not found in open positions")
        failures += 1
    else:
        if not check("quantity", aapl.quantity, 7.0):
            failures += 1
        if not check("avg_cost", aapl.avg_cost, 1100 / 7, tol=0.001):
            failures += 1
        if not check("cost_basis", aapl.cost_basis, 1100.0):
            failures += 1

    aapl_realized = realized_by_symbol.get("AAPL", 0.0)
    if not check("AAPL realized_pnl", aapl_realized, 240.0):
        failures += 1

    # -----------------------------------------------------------------------
    # MSFT position checks
    # -----------------------------------------------------------------------
    print("\n--- MSFT ---")
    msft = pos_by_symbol.get("MSFT")
    if msft is None:
        print(f"  [{FAIL}] MSFT not found in open positions")
        failures += 1
    else:
        if not check("quantity", msft.quantity, 6.0):
            failures += 1
        if not check("avg_cost", msft.avg_cost, 385.0):
            failures += 1
        if not check("cost_basis", msft.cost_basis, 2310.0):
            failures += 1

    msft_realized = realized_by_symbol.get("MSFT", 0.0)
    if not check("MSFT realized_pnl", msft_realized, 40.0):
        failures += 1

    # -----------------------------------------------------------------------
    # NVDA position checks
    # -----------------------------------------------------------------------
    print("\n--- NVDA ---")
    nvda = pos_by_symbol.get("NVDA")
    if nvda is None:
        print(f"  [{FAIL}] NVDA not found in open positions")
        failures += 1
    else:
        if not check("quantity", nvda.quantity, 3.0):
            failures += 1
        if not check("avg_cost", nvda.avg_cost, 800.0):
            failures += 1
        if not check("cost_basis", nvda.cost_basis, 2400.0):
            failures += 1

    nvda_realized = realized_by_symbol.get("NVDA", 0.0)
    if not check("NVDA realized_pnl (should be 0)", nvda_realized, 0.0):
        failures += 1

    # -----------------------------------------------------------------------
    # Dividend row should NOT have created a position or realized trade
    # -----------------------------------------------------------------------
    print("\n--- Dividend row ---")
    # Dividends are skipped — AAPL quantity should remain 7, not affected
    # (Already validated via AAPL quantity above)
    total_realized_count = len(realized_trades)
    # We expect exactly 2 trade records: AAPL (1 lot) + MSFT (1 lot)
    ok = total_realized_count == 2
    status = PASS if ok else FAIL
    print(f"  [{status}] realized trade record count: got {total_realized_count}, expected 2")
    if not ok:
        failures += 1

    # -----------------------------------------------------------------------
    # P&L engine
    # -----------------------------------------------------------------------
    print("\n=== P&L Engine ===")
    summary = calculate(positions, MOCK_PRICES, realized_trades)

    # AAPL unrealized: (185 - 1100/7) * 7 = 185*7 - 1100 = 1295 - 1100 = 195
    print("\n--- Per-position unrealized P&L ---")
    pnl_by_symbol = {p.symbol: p for p in summary.positions}

    aapl_pnl = pnl_by_symbol.get("AAPL")
    if aapl_pnl:
        if not check("AAPL unrealized_pnl", aapl_pnl.unrealized_pnl, 195.0):
            failures += 1
        if not check("AAPL market_value", aapl_pnl.market_value, 1295.0):
            failures += 1
        if not check("AAPL unrealized_pnl_pct", aapl_pnl.unrealized_pnl_pct, 195 / 1100 * 100, tol=0.01):
            failures += 1

    msft_pnl = pnl_by_symbol.get("MSFT")
    if msft_pnl:
        if not check("MSFT unrealized_pnl", msft_pnl.unrealized_pnl, 210.0):
            failures += 1
        if not check("MSFT market_value", msft_pnl.market_value, 2520.0):
            failures += 1

    nvda_pnl = pnl_by_symbol.get("NVDA")
    if nvda_pnl:
        if not check("NVDA unrealized_pnl", nvda_pnl.unrealized_pnl, 225.0):
            failures += 1
        if not check("NVDA market_value", nvda_pnl.market_value, 2625.0):
            failures += 1

    print("\n--- Portfolio summary ---")
    # total_cost_basis = 1100 + 2310 + 2400 = 5810
    if not check("total_cost_basis", summary.total_cost_basis, 5810.0):
        failures += 1
    # total_market_value = 1295 + 2520 + 2625 = 6440
    if not check("total_market_value", summary.total_market_value, 6440.0):
        failures += 1
    # total_unrealized_pnl = 195 + 210 + 225 = 630
    if not check("total_unrealized_pnl", summary.total_unrealized_pnl, 630.0):
        failures += 1
    # total_realized_pnl = 240 + 40 = 280
    if not check("total_realized_pnl", summary.total_realized_pnl, 280.0):
        failures += 1
    # overall_return_pct = (630 + 280) / 5810 * 100 = 910 / 5810 * 100 ≈ 15.6627%
    if not check("overall_return_pct", summary.overall_return_pct, 910 / 5810 * 100, tol=0.01):
        failures += 1

    # -----------------------------------------------------------------------
    # Print the formatted summary table
    # -----------------------------------------------------------------------
    print("\n" + summary.display())

    # -----------------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------------
    print()
    if failures == 0:
        print(f"  {PASS} All checks passed.\n")
    else:
        print(f"  {FAIL} {failures} check(s) failed.\n")
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
