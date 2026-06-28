"""Backtest engine for Polymarket strategies using historical CLOB prices."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from .api_client import fetch_markets, fetch_price_history, parse_outcome_prices, parse_token_ids
from .fees import compute_trade_fees, TAKER_FEE_RATES


@dataclass
class Trade:
    ts: int
    side: str
    price: float
    shares: float
    fee: float
    market_slug: str
    reason: str


@dataclass
class BacktestResult:
    strategy: str
    starting_balance: float
    ending_balance: float
    total_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    trade_count: int
    win_rate: float
    total_fees: float
    markets_tested: int
    params: dict
    equity_curve: list[float]
    trades: list[Trade]


def _infer_category_from_slug(slug: str) -> str:
    s = slug.lower()
    if any(x in s for x in ["fifwc", "nba", "nfl", "mlb", "vs-"]):
        return "SPORTS"
    if any(x in s for x in ["trump", "election", "president"]):
        return "POLITICS"
    if any(x in s for x in ["btc", "bitcoin", "eth", "crypto"]):
        return "CRYPTO"
    return "OTHER"


def _max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    return max_dd * 100


def _sharpe(daily_returns: list[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mu = statistics.mean(daily_returns)
    sd = statistics.stdev(daily_returns)
    if sd == 0:
        return 0.0
    return (mu / sd) * (252**0.5)


def simulate_buy_hold_resolve(
    history: list[dict],
    start_price: float,
    shares: float,
    category: str,
    resolve_yes: bool,
) -> tuple[float, float, list[Trade]]:
    """Buy at first price, hold to resolution."""
    if not history:
        return 0.0, 0.0, []
    entry_p = float(history[0]["p"])
    fee_in = compute_trade_fees(shares, entry_p, category, is_taker=True).taker_fee
    cost = shares * entry_p + fee_in
    payout = shares * (1.0 if resolve_yes else 0.0)
    pnl = payout - cost
    trade = Trade(
        ts=int(history[0]["t"]),
        side="BUY",
        price=entry_p,
        shares=shares,
        fee=fee_in,
        market_slug="",
        reason="buy_hold",
    )
    return pnl, fee_in, [trade]


def backtest_high_conviction_yield(
    markets: list[dict],
    starting_balance: float = 1000.0,
    min_price: float = 0.90,
    max_price: float = 0.97,
    position_pct: float = 0.04,
    category_filter: str | None = "SPORTS",
) -> BacktestResult:
    """
    Buy near-certain outcomes (90-97c), hold to resolution.
    Uses closed markets where final price reveals outcome.
    """
    balance = starting_balance
    equity = [balance]
    all_trades: list[Trade] = []
    total_fees = 0.0
    wins = 0
    tested = 0
    daily_rets: list[float] = []

    for m in markets:
        prices = parse_outcome_prices(m)
        if len(prices) < 2:
            continue
        yes_final = float(prices[0])
        if yes_final not in (0.0, 1.0):
            continue  # must be resolved

        tokens = parse_token_ids(m)
        if not tokens:
            continue
        slug = m.get("slug", "")
        cat = _infer_category_from_slug(slug)
        if category_filter and cat != category_filter:
            continue

        history = fetch_price_history(tokens[0], interval="max", fidelity=1440)
        if len(history) < 5:
            continue

        # Find entry when price in band
        entry = None
        for pt in history:
            p = float(pt["p"])
            if min_price <= p <= max_price:
                entry = pt
                break
        if not entry:
            continue

        entry_p = float(entry["p"])
        alloc = balance * position_pct
        if alloc < 5:
            continue
        shares = alloc / entry_p
        fee = compute_trade_fees(shares, entry_p, cat, is_taker=True).taker_fee
        cost = shares * entry_p + fee
        if cost > balance:
            continue

        resolved_yes = yes_final >= 0.99
        bought_yes = True
        payout = shares * (1.0 if resolved_yes else 0.0)
        pnl = payout - cost
        balance += pnl
        total_fees += fee
        tested += 1
        if pnl > 0:
            wins += 1
        prev = equity[-1]
        daily_rets.append((balance - prev) / prev if prev > 0 else 0)
        equity.append(balance)
        all_trades.append(
            Trade(
                ts=int(entry["t"]),
                side="BUY",
                price=entry_p,
                shares=shares,
                fee=fee,
                market_slug=slug,
                reason=f"high_conviction_yes@{entry_p:.2f}",
            )
        )

    ret = (balance - starting_balance) / starting_balance * 100
    return BacktestResult(
        strategy="high_conviction_yield",
        starting_balance=starting_balance,
        ending_balance=round(balance, 2),
        total_return_pct=round(ret, 2),
        sharpe=round(_sharpe(daily_rets), 2),
        max_drawdown_pct=round(_max_drawdown(equity), 2),
        trade_count=len(all_trades),
        win_rate=round(wins / tested, 3) if tested else 0,
        total_fees=round(total_fees, 2),
        markets_tested=tested,
        params={
            "min_price": min_price,
            "max_price": max_price,
            "position_pct": position_pct,
            "category": category_filter,
        },
        equity_curve=[round(x, 2) for x in equity],
        trades=all_trades,
    )


def backtest_momentum(
    markets: list[dict],
    starting_balance: float = 1000.0,
    lookback_points: int = 24,
    momentum_threshold: float = 0.05,
    hold_points: int = 48,
    position_pct: float = 0.04,
) -> BacktestResult:
    """Buy YES when price rises >= threshold over lookback; exit after hold or resolution."""
    balance = starting_balance
    equity = [balance]
    all_trades: list[Trade] = []
    total_fees = 0.0
    wins = 0
    tested = 0
    daily_rets: list[float] = []

    for m in markets:
        if not m.get("closed"):
            continue
        tokens = parse_token_ids(m)
        prices = parse_outcome_prices(m)
        if not tokens or len(prices) < 2:
            continue
        yes_final = float(prices[0])
        if yes_final not in (0.0, 1.0):
            continue

        history = fetch_price_history(tokens[0], interval="max", fidelity=60)
        if len(history) < lookback_points + hold_points + 5:
            continue

        slug = m.get("slug", "")
        cat = _infer_category_from_slug(slug)

        for i in range(lookback_points, len(history) - hold_points):
            p_now = float(history[i]["p"])
            p_prev = float(history[i - lookback_points]["p"])
            if p_prev <= 0:
                continue
            mom = (p_now - p_prev) / p_prev
            if mom < momentum_threshold:
                continue
            if p_now < 0.20 or p_now > 0.80:
                continue  # avoid extremes for fee efficiency

            alloc = balance * position_pct
            shares = alloc / p_now
            fee_in = compute_trade_fees(shares, p_now, cat, is_taker=True).taker_fee
            cost = shares * p_now + fee_in
            if cost > balance:
                continue

            exit_p = float(history[min(i + hold_points, len(history) - 1)]["p"])
            # If market resolved, use final
            if yes_final >= 0.99:
                exit_p = 1.0
            elif yes_final <= 0.01:
                exit_p = 0.0

            fee_out = compute_trade_fees(shares, exit_p, cat, is_taker=True).taker_fee
            proceeds = shares * exit_p - fee_out
            pnl = proceeds - cost
            balance += pnl
            total_fees += fee_in + fee_out
            tested += 1
            if pnl > 0:
                wins += 1
            prev = equity[-1]
            daily_rets.append((balance - prev) / prev if prev > 0 else 0)
            equity.append(balance)
            all_trades.append(
                Trade(int(history[i]["t"]), "BUY", p_now, shares, fee_in, slug, f"mom={mom:.2f}")
            )
            break  # one trade per market

    ret = (balance - starting_balance) / starting_balance * 100
    return BacktestResult(
        strategy="momentum",
        starting_balance=starting_balance,
        ending_balance=round(balance, 2),
        total_return_pct=round(ret, 2),
        sharpe=round(_sharpe(daily_rets), 2),
        max_drawdown_pct=round(_max_drawdown(equity), 2),
        trade_count=len(all_trades),
        win_rate=round(wins / tested, 3) if tested else 0,
        total_fees=round(total_fees, 2),
        markets_tested=tested,
        params={
            "lookback": lookback_points,
            "threshold": momentum_threshold,
            "hold": hold_points,
            "position_pct": position_pct,
        },
        equity_curve=[round(x, 2) for x in equity],
        trades=all_trades,
    )


def backtest_mean_reversion(
    markets: list[dict],
    starting_balance: float = 1000.0,
    deviation: float = 0.08,
    position_pct: float = 0.04,
) -> BacktestResult:
    """Fade moves away from 0.5 — buy when price drops below 0.5-dev."""
    balance = starting_balance
    equity = [balance]
    all_trades: list[Trade] = []
    total_fees = 0.0
    wins = 0
    tested = 0
    daily_rets: list[float] = []

    for m in markets:
        if not m.get("closed"):
            continue
        tokens = parse_token_ids(m)
        prices = parse_outcome_prices(m)
        if not tokens or len(prices) < 2:
            continue
        yes_final = float(prices[0])
        if yes_final not in (0.0, 1.0):
            continue

        history = fetch_price_history(tokens[0], interval="max", fidelity=60)
        if len(history) < 20:
            continue
        slug = m.get("slug", "")
        cat = _infer_category_from_slug(slug)

        entry = None
        for pt in history:
            p = float(pt["p"])
            if p <= 0.5 - deviation:
                entry = pt
                break
        if not entry:
            continue

        entry_p = float(entry["p"])
        alloc = balance * position_pct
        shares = alloc / entry_p
        fee_in = compute_trade_fees(shares, entry_p, cat, is_taker=True).taker_fee
        cost = shares * entry_p + fee_in
        if cost > balance:
            continue

        exit_p = yes_final if yes_final in (0.0, 1.0) else float(history[-1]["p"])
        fee_out = compute_trade_fees(shares, exit_p, cat, is_taker=True).taker_fee
        proceeds = shares * exit_p - fee_out
        pnl = proceeds - cost
        balance += pnl
        total_fees += fee_in + fee_out
        tested += 1
        if pnl > 0:
            wins += 1
        prev = equity[-1]
        daily_rets.append((balance - prev) / prev if prev > 0 else 0)
        equity.append(balance)
        all_trades.append(
            Trade(int(entry["t"]), "BUY", entry_p, shares, fee_in, slug, "mean_reversion")
        )

    ret = (balance - starting_balance) / starting_balance * 100
    return BacktestResult(
        strategy="mean_reversion",
        starting_balance=starting_balance,
        ending_balance=round(balance, 2),
        total_return_pct=round(ret, 2),
        sharpe=round(_sharpe(daily_rets), 2),
        max_drawdown_pct=round(_max_drawdown(equity), 2),
        trade_count=len(all_trades),
        win_rate=round(wins / tested, 3) if tested else 0,
        total_fees=round(total_fees, 2),
        markets_tested=tested,
        params={"deviation": deviation, "position_pct": position_pct},
        equity_curve=[round(x, 2) for x in equity],
        trades=all_trades,
    )


def backtest_maker_sim(
    markets: list[dict],
    starting_balance: float = 1000.0,
    target_spread_capture: float = 0.02,
    position_pct: float = 0.03,
    fills_per_market: int = 3,
) -> BacktestResult:
    """
    Simulate maker strategy: post at mid-spread, earn spread + rebate.
    Conservative: only profitable if spread > 2x fees.
    """
    balance = starting_balance
    equity = [balance]
    all_trades: list[Trade] = []
    total_fees = 0.0
    wins = 0
    tested = 0
    daily_rets: list[float] = []

    for m in markets:
        if not m.get("closed"):
            continue
        tokens = parse_token_ids(m)
        if not tokens:
            continue
        slug = m.get("slug", "")
        cat = _infer_category_from_slug(slug)
        history = fetch_price_history(tokens[0], interval="max", fidelity=60)
        if len(history) < 30:
            continue

        fills = 0
        for i in range(5, len(history) - 5):
            p = float(history[i]["p"])
            if p < 0.15 or p > 0.85:
                continue  # avoid high-fee zone for taker hedge
            alloc = balance * position_pct
            shares = alloc / p
            # Maker: no taker fee; earn rebate on hypothetical counterparty flow
            rebate = compute_trade_fees(shares, p, cat, is_taker=False).maker_rebate
            # Capture half-spread per round trip
            gross_edge = shares * target_spread_capture
            pnl = gross_edge + rebate
            balance += pnl
            total_fees -= rebate  # negative fees = rebate income
            tested += 1
            wins += 1 if pnl > 0 else 0
            fills += 1
            prev = equity[-1]
            daily_rets.append((balance - prev) / prev if prev > 0 else 0)
            equity.append(balance)
            all_trades.append(
                Trade(int(history[i]["t"]), "MAKER", p, shares, -rebate, slug, "spread_capture")
            )
            if fills >= fills_per_market:
                break

    ret = (balance - starting_balance) / starting_balance * 100
    return BacktestResult(
        strategy="maker_spread_sim",
        starting_balance=starting_balance,
        ending_balance=round(balance, 2),
        total_return_pct=round(ret, 2),
        sharpe=round(_sharpe(daily_rets), 2),
        max_drawdown_pct=round(_max_drawdown(equity), 2),
        trade_count=len(all_trades),
        win_rate=round(wins / tested, 3) if tested else 0,
        total_fees=round(total_fees, 2),
        markets_tested=tested,
        params={
            "spread_capture": target_spread_capture,
            "position_pct": position_pct,
            "fills_per_market": fills_per_market,
        },
        equity_curve=[round(x, 2) for x in equity],
        trades=all_trades,
    )


def backtest_copy_trades(
    wallet_trades: list[dict],
    closed_positions: list[dict],
    starting_balance: float = 1000.0,
    position_pct: float = 0.04,
    scale_factor: float = 0.001,
    category: str = "SPORTS",
) -> BacktestResult:
    """
    Mirror historical trades from a skilled wallet at scaled size.
    Uses closed positions to validate outcomes.
    """
    balance = starting_balance
    equity = [balance]
    all_trades: list[Trade] = []
    total_fees = 0.0
    wins = 0
    tested = 0
    daily_rets: list[float] = []

    # Map conditionId -> outcome from closed positions
    outcomes: dict[str, float] = {}
    for cp in closed_positions:
        cid = cp.get("conditionId", "")
        outcomes[cid] = float(cp.get("curPrice", 0))

    seen_conditions: set[str] = set()
    for t in sorted(wallet_trades, key=lambda x: x.get("timestamp", 0)):
        cid = t.get("conditionId", "")
        if cid in seen_conditions:
            continue
        if t.get("side") != "BUY":
            continue
        if cid not in outcomes:
            continue

        entry_p = float(t.get("price", 0))
        if entry_p <= 0:
            continue
        alloc = balance * position_pct
        shares = alloc / entry_p
        fee = compute_trade_fees(shares, entry_p, category, is_taker=True).taker_fee
        cost = shares * entry_p + fee
        if cost > balance:
            continue

        final = outcomes[cid]
        payout = shares * final
        pnl = payout - cost
        balance += pnl
        total_fees += fee
        tested += 1
        if pnl > 0:
            wins += 1
        seen_conditions.add(cid)
        prev = equity[-1]
        daily_rets.append((balance - prev) / prev if prev > 0 else 0)
        equity.append(balance)
        all_trades.append(
            Trade(
                int(t.get("timestamp", 0)),
                "BUY",
                entry_p,
                shares,
                fee,
                t.get("slug", ""),
                "copy_trade",
            )
        )

    ret = (balance - starting_balance) / starting_balance * 100
    return BacktestResult(
        strategy="copy_skilled_wallet",
        starting_balance=starting_balance,
        ending_balance=round(balance, 2),
        total_return_pct=round(ret, 2),
        sharpe=round(_sharpe(daily_rets), 2),
        max_drawdown_pct=round(_max_drawdown(equity), 2),
        trade_count=len(all_trades),
        win_rate=round(wins / tested, 3) if tested else 0,
        total_fees=round(total_fees, 2),
        markets_tested=tested,
        params={"position_pct": position_pct, "category": category},
        equity_curve=[round(x, 2) for x in equity],
        trades=all_trades,
    )


def run_all_backtests(
    starting_balance: float = 1000.0,
    closed_market_limit: int = 40,
    output_dir: Path | None = None,
) -> list[BacktestResult]:
    markets = fetch_markets(closed=True, limit=closed_market_limit, order="volumeNum", ascending=False)
    results = [
        backtest_high_conviction_yield(markets, starting_balance),
        backtest_high_conviction_yield(
            markets, starting_balance, min_price=0.90, max_price=0.97, category_filter="POLITICS"
        ),
        backtest_momentum(markets, starting_balance),
        backtest_mean_reversion(markets, starting_balance),
        backtest_maker_sim(markets, starting_balance),
    ]

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = []
        for r in results:
            d = asdict(r)
            d["trades"] = [asdict(t) for t in r.trades[:20]]
            summary.append(d)
        (output_dir / "backtest_results.json").write_text(json.dumps(summary, indent=2))

    return results


def results_table(results: list[BacktestResult]) -> str:
    lines = [
        f"{'Strategy':<28} {'Return%':>8} {'Sharpe':>7} {'MaxDD%':>7} {'Trades':>7} {'WinRate':>8} {'Fees':>8}",
        "-" * 80,
    ]
    for r in results:
        lines.append(
            f"{r.strategy:<28} {r.total_return_pct:>8.2f} {r.sharpe:>7.2f} "
            f"{r.max_drawdown_pct:>7.2f} {r.trade_count:>7} {r.win_rate:>8.3f} {r.total_fees:>8.2f}"
        )
    return "\n".join(lines)
