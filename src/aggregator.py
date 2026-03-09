"""
aggregator.py

Merges positions and realized trades from multiple brokers into a single
unified list for the P&L engine.

Design decisions:
  - Same symbol held at different brokers is kept as separate rows (broker
    field distinguishes them). This preserves per-broker visibility.
  - Realized trades are concatenated as-is; the P&L engine sums them all.
"""

from __future__ import annotations

from typing import List, Tuple

from src.firstrade_parser import Position, RealizedTrade


def merge(
    *sources: Tuple[List[Position], List[RealizedTrade]],
) -> Tuple[List[Position], List[RealizedTrade]]:
    """
    Merge any number of (positions, realized_trades) tuples from different
    brokers into a single unified pair.

    Usage:
        ft_data     = firstrade_parser.parse(csv_path)
        schwab_data = schwab_fetcher.fetch(config)
        positions, realized = aggregator.merge(ft_data, schwab_data)
    """
    all_positions: List[Position] = []
    all_realized: List[RealizedTrade] = []

    for positions, realized in sources:
        all_positions.extend(positions)
        all_realized.extend(realized)

    return all_positions, all_realized
