#!/usr/bin/env python3
"""Smoke tests for paper portfolio engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from polymarket_research.paper_portfolio import PaperPortfolio, DATA_DIR


def test_portfolio_lifecycle():
    test_path = DATA_DIR / "_test_portfolio.json"
    if test_path.exists():
        test_path.unlink()

    p = PaperPortfolio(starting_balance=1000.0, state_path=test_path)
    p.reset(1000.0)

    assert p.state.cash_balance == 1000.0
    assert p._open_count() == 0

    snap = p.get_snapshot()
    assert "totals" in snap
    assert snap["totals"]["equity"] == 1000.0
    assert "watchlist" in snap
    assert "open_positions" in snap
    assert "config" in snap

    # Fast watchlist from cache if available
    p.refresh_watchlist(fast=True)
    assert isinstance(p.state.watchlist, list)

    # Price update should not crash with no positions
    p.update_prices()
    p.check_exits()

    # Cycle should not crash
    result = p.run_cycle(max_opens=0)
    assert "copy_signals" in result or "paused" in result

    test_path.unlink(missing_ok=True)
    print("OK: portfolio lifecycle")


def test_fee_and_signal_dedup():
    test_path = DATA_DIR / "_test_portfolio2.json"
    p = PaperPortfolio(starting_balance=1000.0, state_path=test_path)
    p.reset(1000.0)

    key = "0xabc:0xcond2"
    assert not p._already_seen(key)

    fake_signal = {
        "slug": "test-market-smoke",
        "title": "Smoke Test Market",
        "price": 0.50,
        "token_id": "12345",
        "condition_id": "0xcond2",
        "category": "SPORTS",
        "source": "manual",
        "signal_key": key,
    }
    pos = p.open_from_signal(fake_signal)
    assert pos is not None
    assert p.state.cash_balance < 1000.0
    assert p._open_count() == 1
    assert p._already_seen(key)
    # Duplicate blocked
    pos2 = p.open_from_signal(fake_signal)
    assert pos2 is None

    test_path.unlink(missing_ok=True)
    print("OK: fee and dedup")


if __name__ == "__main__":
    test_portfolio_lifecycle()
    test_fee_and_signal_dedup()
    print("\nAll smoke tests passed.")
