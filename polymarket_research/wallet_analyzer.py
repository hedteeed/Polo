"""Analyze leaderboard wallets and classify trading behavior."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from .api_client import (
    fetch_all_trades,
    fetch_closed_positions,
    fetch_leaderboard,
)


@dataclass
class WalletProfile:
    address: str
    username: str
    leaderboard_pnl: float
    leaderboard_vol: float
    roi_pct: float
    trade_count: int
    buy_pct: float
    avg_trade_usdc: float
    median_trade_usdc: float
    avg_entry_price: float
    price_bucket_dist: dict[str, float]
    category_dist: dict[str, float]
    unique_markets: int
    avg_hold_hours: float | None
    win_rate_closed: float | None
    avg_closed_pnl_pct: float | None
    strategy_label: str
    copy_score: float


def _infer_category(title: str, slug: str) -> str:
    t = (title + " " + slug).lower()
    rules = [
        ("SPORTS", ["vs.", "nba", "nfl", "mlb", "soccer", "fifwc", "spread:", "o/u", "halftime"]),
        ("POLITICS", ["trump", "biden", "election", "president", "congress", "senate"]),
        ("CRYPTO", ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana"]),
        ("FINANCE", ["fed", "rate", "s&p", "stock", "earnings", "gdp"]),
        ("ECONOMICS", ["cpi", "inflation", "unemployment", "jobs report"]),
        ("TECH", ["ai", "openai", "apple", "google", "tesla"]),
    ]
    for cat, kws in rules:
        if any(k in t for k in kws):
            return cat
    return "OTHER"


def _price_bucket(p: float) -> str:
    if p < 0.15:
        return "extreme_low"
    if p < 0.35:
        return "low"
    if p < 0.65:
        return "mid"
    if p < 0.85:
        return "high"
    return "extreme_high"


def classify_strategy(
    buy_pct: float,
    avg_price: float,
    category_dist: dict[str, float],
    avg_trade_usdc: float,
    unique_markets: int,
) -> str:
    top_cat = max(category_dist, key=category_dist.get) if category_dist else "OTHER"
    cat_conc = max(category_dist.values()) if category_dist else 0

    if cat_conc > 0.6 and top_cat == "SPORTS" and buy_pct > 0.85:
        return "sports_accumulator"
    if avg_price > 0.85 or avg_price < 0.15:
        return "extreme_probability"
    if unique_markets > 100 and avg_trade_usdc < 500:
        return "high_frequency_scalper"
    if cat_conc > 0.5:
        return f"specialist_{top_cat.lower()}"
    if buy_pct > 0.9:
        return "buy_and_hold"
    return "mixed_directional"


def compute_copy_score(
    roi_pct: float,
    leaderboard_vol: float,
    win_rate: float | None,
    strategy_label: str,
    trade_count: int,
) -> float:
    """Score 0-100 for suitability as copy-trade signal source at $1k scale."""
    score = 0.0
    # ROI weight (cap whale outliers)
    score += min(roi_pct, 50) * 0.8
    # Volume sweet spot for retail mirroring
    if 100_000 <= leaderboard_vol <= 5_000_000:
        score += 25
    elif leaderboard_vol < 100_000:
        score += 10
  # Too large = can't mirror
    # Win rate
    if win_rate is not None:
        score += (win_rate - 0.5) * 40
    # Strategy fit
    if strategy_label in ("sports_accumulator", "specialist_sports", "specialist_politics"):
        score += 15
    if strategy_label == "high_frequency_scalper":
        score -= 20
    if trade_count >= 20:
        score += 10
    return round(max(0, min(100, score)), 2)


def analyze_wallet(
    address: str,
    username: str = "",
    leaderboard_pnl: float = 0,
    leaderboard_vol: float = 0,
    max_trades: int = 1000,
) -> WalletProfile:
    trades = fetch_all_trades(address, max_trades=max_trades)
    closed = fetch_closed_positions(address, limit=100)

    usdc_sizes = []
    prices = []
    categories: Counter[str] = Counter()
    markets: set[str] = set()
    sides: Counter[str] = Counter()

    for t in trades:
        side = t.get("side", "BUY")
        sides[side] += 1
        price = float(t.get("price", 0))
        size = float(t.get("size", 0))
        usdc = size * price
        usdc_sizes.append(usdc)
        prices.append(price)
        title = t.get("title", "")
        slug = t.get("slug", "")
        categories[_infer_category(title, slug)] += 1
        markets.add(t.get("conditionId", ""))

    total_cat = sum(categories.values()) or 1
    cat_dist = {k: v / total_cat for k, v in categories.items()}
    price_buckets = Counter(_price_bucket(p) for p in prices)
    total_pb = sum(price_buckets.values()) or 1
    pb_dist = {k: v / total_pb for k, v in price_buckets.items()}

    # Closed position stats
    win_rate = None
    avg_pnl_pct = None
    if closed:
        wins = 0
        pnl_pcts = []
        for cp in closed:
            avg_p = float(cp.get("avgPrice", 0))
            cur = float(cp.get("curPrice", 0))
            if cur >= 0.99:
                wins += 1
                if avg_p > 0:
                    pnl_pcts.append((1.0 - avg_p) / avg_p * 100)
            elif cur <= 0.01:
                if avg_p > 0:
                    pnl_pcts.append(-100)
        win_rate = wins / len(closed) if closed else None
        avg_pnl_pct = statistics.mean(pnl_pcts) if pnl_pcts else None

    buy_pct = sides.get("BUY", 0) / max(len(trades), 1)
    avg_price = statistics.mean(prices) if prices else 0.5
    avg_usdc = statistics.mean(usdc_sizes) if usdc_sizes else 0
    med_usdc = statistics.median(usdc_sizes) if usdc_sizes else 0
    roi = (leaderboard_pnl / leaderboard_vol * 100) if leaderboard_vol > 0 else 0

    label = classify_strategy(buy_pct, avg_price, cat_dist, avg_usdc, len(markets))
    copy_score = compute_copy_score(roi, leaderboard_vol, win_rate, label, len(trades))

    return WalletProfile(
        address=address,
        username=username,
        leaderboard_pnl=leaderboard_pnl,
        leaderboard_vol=leaderboard_vol,
        roi_pct=round(roi, 2),
        trade_count=len(trades),
        buy_pct=round(buy_pct, 3),
        avg_trade_usdc=round(avg_usdc, 2),
        median_trade_usdc=round(med_usdc, 2),
        avg_entry_price=round(avg_price, 3),
        price_bucket_dist={k: round(v, 3) for k, v in pb_dist.items()},
        category_dist={k: round(v, 3) for k, v in cat_dist.items()},
        unique_markets=len(markets),
        avg_hold_hours=None,
        win_rate_closed=round(win_rate, 3) if win_rate is not None else None,
        avg_closed_pnl_pct=round(avg_pnl_pct, 2) if avg_pnl_pct is not None else None,
        strategy_label=label,
        copy_score=copy_score,
    )


def screen_copy_candidates(
    time_period: str = "MONTH",
    min_vol: float = 100_000,
    max_vol: float = 5_000_000,
    min_roi: float = 10.0,
    min_pnl: float = 50_000,
    top_n: int = 15,
) -> list[WalletProfile]:
    profiles: list[WalletProfile] = []
    for offset in range(0, 200, 50):
        board = fetch_leaderboard(
            category="OVERALL",
            time_period=time_period,
            order_by="PNL",
            limit=50,
            offset=offset,
        )
        if not board:
            break
        for entry in board:
            vol = float(entry.get("vol", 0))
            pnl = float(entry.get("pnl", 0))
            roi = pnl / vol * 100 if vol > 0 else 0
            if vol < min_vol or vol > max_vol or pnl < min_pnl or roi < min_roi:
                continue
            try:
                p = analyze_wallet(
                    entry["proxyWallet"],
                    entry.get("userName", ""),
                    pnl,
                    vol,
                    max_trades=300,
                )
                profiles.append(p)
            except Exception:
                continue
    profiles.sort(key=lambda x: -x.copy_score)
    return profiles[:top_n]


def save_profiles(profiles: list[WalletProfile], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profiles": [asdict(p) for p in profiles],
    }
    path.write_text(json.dumps(data, indent=2))
