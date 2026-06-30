"""Forward (paper) testing engine for live Polymarket markets."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from .api_client import fetch_leaderboard, fetch_markets, fetch_trades, parse_outcome_prices, parse_token_ids
from .fees import compute_trade_fees, breakeven_edge_bps
from .wallet_analyzer import screen_copy_candidates


@dataclass
class PaperPosition:
    market_slug: str
    token_id: str
    side: str
    entry_price: float
    shares: float
    entry_fee: float
    cost_basis: float
    category: str
    opened_at: str
    signal_source: str


@dataclass
class ForwardTestState:
    balance: float
    positions: list[PaperPosition]
    closed_trades: list[dict]
    watchlist_wallets: list[str]
    last_updated: str


def _infer_category(slug: str, title: str = "") -> str:
    s = (slug + " " + title).lower()
    if any(x in s for x in ["fifwc", "nba", "nfl", "vs.", "o/u"]):
        return "SPORTS"
    if any(x in s for x in ["trump", "election", "president"]):
        return "POLITICS"
    if any(x in s for x in ["btc", "bitcoin", "eth"]):
        return "CRYPTO"
    return "OTHER"


class ForwardTester:
    """
    Paper-trades the recommended hybrid strategy:
    1. Skilled wallet copy signals (sports specialists)
    2. High-conviction yield entries (90-95c, fee-aware)
    3. Maker limit orders where spread justifies fees
    """

    def __init__(
        self,
        starting_balance: float = 1000.0,
        position_pct: float = 0.04,
        max_positions: int = 8,
        min_conviction_price: float = 0.90,
        max_conviction_price: float = 0.95,
        state_path: Path | None = None,
    ):
        self.starting_balance = starting_balance
        self.position_pct = position_pct
        self.max_positions = max_positions
        self.min_conviction_price = min_conviction_price
        self.max_conviction_price = max_conviction_price
        self.state_path = state_path or Path("data/forward_test_state.json")
        self.state = self._load_or_init()

    def _load_or_init(self) -> ForwardTestState:
        if self.state_path.exists():
            raw = json.loads(self.state_path.read_text())
            positions = [PaperPosition(**p) for p in raw.get("positions", [])]
            return ForwardTestState(
                balance=raw["balance"],
                positions=positions,
                closed_trades=raw.get("closed_trades", []),
                watchlist_wallets=raw.get("watchlist_wallets", []),
                last_updated=raw.get("last_updated", ""),
            )
        return ForwardTestState(
            balance=self.starting_balance,
            positions=[],
            closed_trades=[],
            watchlist_wallets=[],
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "balance": self.state.balance,
            "positions": [asdict(p) for p in self.state.positions],
            "closed_trades": self.state.closed_trades,
            "watchlist_wallets": self.state.watchlist_wallets,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "starting_balance": self.starting_balance,
            "pnl": round(self.state.balance - self.starting_balance, 2),
            "return_pct": round(
                (self.state.balance - self.starting_balance) / self.starting_balance * 100, 2
            ),
        }
        self.state_path.write_text(json.dumps(data, indent=2))

    def refresh_watchlist(self) -> list[str]:
        candidates = screen_copy_candidates(top_n=5)
        self.state.watchlist_wallets = [c.address for c in candidates]
        self.save()
        return self.state.watchlist_wallets

    def scan_copy_signals(self) -> list[dict]:
        """Detect new BUY trades from watchlist wallets not yet mirrored."""
        signals = []
        held_slugs = {p.market_slug for p in self.state.positions}
        for wallet in self.state.watchlist_wallets:
            trades = fetch_trades(wallet, limit=20)
            for t in trades:
                if t.get("side") != "BUY":
                    continue
                slug = t.get("slug", "")
                if slug in held_slugs:
                    continue
                price = float(t.get("price", 0))
                if price < 0.20 or price > 0.85:
                    continue  # fee-efficient zone for copy
                signals.append(
                    {
                        "wallet": wallet,
                        "slug": slug,
                        "price": price,
                        "title": t.get("title", ""),
                        "condition_id": t.get("conditionId", ""),
                        "asset": t.get("asset", ""),
                        "timestamp": t.get("timestamp", 0),
                        "source": "copy_signal",
                    }
                )
        return signals[:5]

    def scan_conviction_markets(self) -> list[dict]:
        """Find active markets with 90-95c YES and sufficient liquidity."""
        markets = fetch_markets(closed=False, limit=200)
        signals = []
        held_slugs = {p.market_slug for p in self.state.positions}
        for m in markets:
            prices = parse_outcome_prices(m)
            tokens = parse_token_ids(m)
            if not prices or not tokens:
                continue
            p = float(prices[0])
            if not (self.min_conviction_price <= p <= self.max_conviction_price):
                continue
            slug = m.get("slug", "")
            if slug in held_slugs:
                continue
            liq = float(m.get("liquidityNum", 0) or 0)
            if liq < 5000:
                continue
            cat = _infer_category(slug, m.get("question", ""))
            edge_needed = breakeven_edge_bps(p, cat)
            gross_yield = (1.0 - p) / p * 100
            if gross_yield < edge_needed * 2:
                continue  # yield must exceed 2x fee breakeven
            signals.append(
                {
                    "slug": slug,
                    "price": p,
                    "title": m.get("question", ""),
                    "token_id": tokens[0],
                    "category": cat,
                    "liquidity": liq,
                    "gross_yield_pct": round(gross_yield, 2),
                    "fee_breakeven_pts": round(edge_needed, 3),
                    "source": "conviction_yield",
                }
            )
        signals.sort(key=lambda x: -x["gross_yield_pct"])
        return signals[:5]

    def open_position(self, signal: dict) -> bool:
        if len(self.state.positions) >= self.max_positions:
            return False
        price = float(signal["price"])
        cat = signal.get("category", _infer_category(signal.get("slug", "")))
        alloc = self.state.balance * self.position_pct
        if alloc < 5 or alloc > self.state.balance * 0.95:
            return False
        shares = alloc / price
        fee = compute_trade_fees(shares, price, cat, is_taker=True).taker_fee
        cost = shares * price + fee
        if cost > self.state.balance:
            return False

        pos = PaperPosition(
            market_slug=signal.get("slug", ""),
            token_id=signal.get("asset") or signal.get("token_id", ""),
            side="BUY",
            entry_price=price,
            shares=shares,
            entry_fee=fee,
            cost_basis=cost,
            category=cat,
            opened_at=datetime.now(timezone.utc).isoformat(),
            signal_source=signal.get("source", "manual"),
        )
        self.state.balance -= cost
        self.state.positions.append(pos)
        self.save()
        return True

    def run_scan_cycle(self) -> dict:
        """One forward-test iteration: refresh watchlist, scan, paper-open best signals."""
        if not self.state.watchlist_wallets:
            self.refresh_watchlist()

        copy_signals = self.scan_copy_signals()
        conviction_signals = self.scan_conviction_markets()
        opened = []

        # Prioritize copy signals (higher historical edge), then conviction
        for sig in copy_signals[:2]:
            sig["category"] = _infer_category(sig.get("slug", ""), sig.get("title", ""))
            if self.open_position(sig):
                opened.append(sig)

        for sig in conviction_signals[:2]:
            if self.open_position(sig):
                opened.append(sig)

        self.save()
        return {
            "balance": self.state.balance,
            "open_positions": len(self.state.positions),
            "copy_signals_found": len(copy_signals),
            "conviction_signals_found": len(conviction_signals),
            "opened_this_cycle": opened,
            "watchlist": self.state.watchlist_wallets,
        }
