"""
price_fetcher.py

Fetches current market prices for a list of symbols via yfinance.
Caches results locally in data/cache.json to avoid redundant API calls.

Cache TTL: 15 minutes by default. Prices older than that are re-fetched.
Pass force_refresh=True to bypass the cache entirely.
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import yfinance as yf

DEFAULT_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache.json"
DEFAULT_TTL_MINUTES = 15


def fetch(
    symbols: List[str],
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    force_refresh: bool = False,
) -> Dict[str, float]:
    """
    Return {symbol: current_price} for all requested symbols.

    Prices are served from cache if fresh enough; stale or missing
    symbols are fetched from yfinance in a single batch request.
    """
    cache_path = Path(cache_path)
    cache = _load_cache(cache_path)
    cutoff = datetime.utcnow() - timedelta(minutes=ttl_minutes)

    stale = [
        s for s in symbols
        if force_refresh or _is_stale(cache, s, cutoff)
    ]

    if stale:
        fresh = _fetch_from_yfinance(stale)
        now_str = datetime.utcnow().isoformat()
        for symbol, price in fresh.items():
            cache[symbol] = {"price": price, "fetched_at": now_str}
        _save_cache(cache_path, cache)

    prices = {}
    for symbol in symbols:
        entry = cache.get(symbol)
        if entry and entry.get("price") is not None:
            prices[symbol] = entry["price"]
        else:
            warnings.warn(f"Could not get price for {symbol} — excluded from results.")

    return prices


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_stale(cache: dict, symbol: str, cutoff: datetime) -> bool:
    entry = cache.get(symbol)
    if not entry:
        return True
    try:
        fetched_at = datetime.fromisoformat(entry["fetched_at"])
        return fetched_at < cutoff
    except (KeyError, ValueError):
        return True


def _fetch_from_yfinance(symbols: List[str]) -> Dict[str, float]:
    """Batch-fetch latest prices. Falls back to per-ticker if batch fails."""
    prices: Dict[str, float] = {}

    try:
        # Batch download: period='1d' returns one row per symbol
        data = yf.download(symbols, period="1d", auto_adjust=True, progress=False)
        if not data.empty:
            close = data["Close"] if "Close" in data.columns else data.iloc[:, 0]
            # When multiple symbols, close is a DataFrame; single symbol is a Series
            if hasattr(close, "columns"):
                for sym in symbols:
                    sym_upper = sym.upper()
                    # yfinance may return the symbol as-is or uppercased
                    col = next((c for c in close.columns if str(c).upper() == sym_upper), None)
                    if col is not None:
                        val = close[col].dropna()
                        if not val.empty:
                            prices[sym_upper] = float(val.iloc[-1])
            else:
                # Single-symbol Series
                val = close.dropna()
                if not val.empty and symbols:
                    prices[symbols[0].upper()] = float(val.iloc[-1])
    except Exception as e:
        warnings.warn(f"Batch yfinance fetch failed ({e}); falling back to per-ticker.")

    # Fall back for any that weren't captured by the batch
    missing = [s for s in symbols if s.upper() not in prices]
    for symbol in missing:
        try:
            ticker = yf.Ticker(symbol)
            price = ticker.fast_info.get("last_price") or ticker.fast_info.get("lastPrice")
            if price:
                prices[symbol.upper()] = float(price)
        except Exception as e:
            warnings.warn(f"Could not fetch price for {symbol}: {e}")

    return prices


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return data.get("prices", {})
        except (json.JSONDecodeError, KeyError):
            return {}
    return {}


def _save_cache(path: Path, prices: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve any other top-level keys in the cache file
    existing = {}
    if path.exists():
        try:
            with open(path, "r") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    existing["prices"] = prices
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)
