#!/usr/bin/env python3
"""Run full Polymarket strategy research pipeline."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from polymarket_research.api_client import fetch_leaderboard, fetch_all_trades, fetch_closed_positions
from polymarket_research.backtest import run_all_backtests, results_table, backtest_copy_trades
from polymarket_research.fees import fee_table_sample, TAKER_FEE_RATES
from polymarket_research.forward_test import ForwardTester
from polymarket_research.wallet_analyzer import screen_copy_candidates, save_profiles


DATA_DIR = Path(__file__).resolve().parent / "data"
STARTING_BALANCE = 1000.0


def collect_leaderboard_snapshot() -> dict:
    snapshot = {"generated_at": datetime.now(timezone.utc).isoformat(), "boards": {}}
    for period in ["DAY", "WEEK", "MONTH"]:
        for order in ["PNL", "VOL"]:
            key = f"{period}_{order}"
            snapshot["boards"][key] = fetch_leaderboard(
                time_period=period, order_by=order, limit=50
            )
    for cat in ["SPORTS", "POLITICS", "CRYPTO", "FINANCE"]:
        snapshot["boards"][f"MONTH_PNL_{cat}"] = fetch_leaderboard(
            category=cat, time_period="MONTH", order_by="PNL", limit=25
        )
    out = DATA_DIR / "leaderboard_snapshot.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2))
    return snapshot


def analyze_leaderboard_roi(snapshot: dict) -> list[dict]:
    """Compute ROI stats from leaderboard — key finding for strategy selection."""
    rows = []
    month_pnl = snapshot["boards"].get("MONTH_PNL", [])
    month_vol = snapshot["boards"].get("MONTH_VOL", [])
    vol_map = {e["proxyWallet"]: float(e["vol"]) for e in month_vol}

    for e in month_pnl:
        vol = float(e["vol"])
        pnl = float(e["pnl"])
        roi = pnl / vol * 100 if vol > 0 else 0
        rows.append(
            {
                "rank": e["rank"],
                "username": e.get("userName", ""),
                "address": e["proxyWallet"],
                "pnl": pnl,
                "vol": vol,
                "roi_pct": round(roi, 2),
            }
        )

    # Volume leaders often have terrible ROI
    vol_leaders = sorted(rows, key=lambda x: -x["vol"])[:10]
    pnl_leaders = sorted(rows, key=lambda x: -x["pnl"])[:10]
    mid_tier = [r for r in rows if 100_000 <= r["vol"] <= 5_000_000 and r["roi_pct"] >= 10]

    stats = {
        "pnl_leader_avg_roi": round(sum(r["roi_pct"] for r in pnl_leaders) / len(pnl_leaders), 2),
        "vol_leader_avg_roi": round(sum(r["roi_pct"] for r in vol_leaders) / len(vol_leaders), 2),
        "mid_tier_count": len(mid_tier),
        "mid_tier_avg_roi": round(sum(r["roi_pct"] for r in mid_tier) / len(mid_tier), 2) if mid_tier else 0,
    }
    result = {"stats": stats, "pnl_leaders": pnl_leaders[:10], "vol_leaders": vol_leaders, "mid_tier": mid_tier[:15]}
    (DATA_DIR / "leaderboard_roi_analysis.json").write_text(json.dumps(result, indent=2))
    return rows


def main():
    print("=" * 60)
    print("POLYMARKET STRATEGY RESEARCH — $1000 Starting Balance")
    print("=" * 60)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Fee analysis
    print("\n[1/5] Fee structure analysis (official docs)...")
    fee_report = {cat: fee_table_sample(cat) for cat in ["SPORTS", "POLITICS", "CRYPTO", "GEOPOLITICS"]}
    (DATA_DIR / "fee_analysis.json").write_text(json.dumps(fee_report, indent=2))
    print(f"  Taker fee rates: {TAKER_FEE_RATES}")
    print(f"  Sports 100sh @ 50c fee: ${fee_report['SPORTS'][4]['taker_fee']:.2f}")
    print(f"  Sports 100sh @ 90c fee: ${fee_report['SPORTS'][6]['taker_fee']:.2f}")

    # 2. Leaderboard
    print("\n[2/5] Collecting leaderboard data...")
    snapshot = collect_leaderboard_snapshot()
    roi_rows = analyze_leaderboard_roi(snapshot)
    month = snapshot["boards"]["MONTH_PNL"]
    print(f"  Top monthly PnL: {month[0].get('userName','')} ${float(month[0]['pnl']):,.0f}")
    vol_board = snapshot["boards"]["MONTH_VOL"]
    top_vol = vol_board[0]
    vol_roi = float(top_vol["pnl"]) / float(top_vol["vol"]) * 100
    print(f"  Top volume trader ROI: {vol_roi:.2f}% (volume ≠ skill)")

    # 3. Wallet analysis
    print("\n[3/5] Screening copy-trade candidates (analyzing wallets)...")
    candidates = screen_copy_candidates(top_n=8)
    save_profiles(candidates, DATA_DIR / "wallet_profiles.json")
    for c in candidates[:5]:
        print(
            f"  {c.username[:20]:20} ROI={c.roi_pct:>5.1f}% "
            f"score={c.copy_score:>5.1f} strategy={c.strategy_label}"
        )

    # 4. Backtests
    print("\n[4/5] Running backtests on closed markets (this takes ~2-3 min)...")
    results = run_all_backtests(STARTING_BALANCE, closed_market_limit=30, output_dir=DATA_DIR)
    print(results_table(results))

    # Copy-trade backtest on best candidate
    if candidates:
        best = candidates[0]
        print(f"\n  Copy-trade backtest mirroring {best.username}...")
        trades = fetch_all_trades(best.address, max_trades=500)
        closed = fetch_closed_positions(best.address, limit=100)
        copy_result = backtest_copy_trades(trades, closed, STARTING_BALANCE)
        print(
            f"  Copy result: {copy_result.total_return_pct:.1f}% return, "
            f"{copy_result.win_rate:.1%} win rate, ${copy_result.total_fees:.2f} fees"
        )
        copy_data = {
            "wallet": best.address,
            "username": best.username,
            "return_pct": copy_result.total_return_pct,
            "win_rate": copy_result.win_rate,
            "fees": copy_result.total_fees,
            "trades": copy_result.trade_count,
        }
        (DATA_DIR / "copy_backtest.json").write_text(json.dumps(copy_data, indent=2))

    # 5. Forward test
    print("\n[5/5] Running forward (paper) test scan...")
    ft = ForwardTester(starting_balance=STARTING_BALANCE, state_path=DATA_DIR / "forward_test_state.json")
    ft.state.watchlist_wallets = [c.address for c in candidates[:5]]
    cycle = ft.run_scan_cycle()
    print(f"  Paper balance: ${cycle['balance']:.2f}")
    print(f"  Copy signals: {cycle['copy_signals_found']}, Conviction signals: {cycle['conviction_signals_found']}")
    print(f"  Positions opened: {len(cycle['opened_this_cycle'])}")

    # Summary
    best_bt = max(results, key=lambda r: r.sharpe if r.trade_count > 0 else -999)
    print("\n" + "=" * 60)
    print("RECOMMENDED STRATEGY: Skilled Copy + Fee-Aware Conviction Yield")
    print("=" * 60)
    print(f"  Best backtest by Sharpe: {best_bt.strategy} ({best_bt.total_return_pct:.1f}%)")
    print(f"  Data saved to: {DATA_DIR}")
    print("  Full report: polymarket_research/RESEARCH.md")
    print("  Run bot: python -m polymarket_research.bot --cycles 1")


if __name__ == "__main__":
    main()
