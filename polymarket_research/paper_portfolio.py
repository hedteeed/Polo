"""Production paper-trading portfolio engine with PNL, resolution, and copy tracking."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .api_client import (
    fetch_market_by_slug,
    fetch_markets,
    fetch_midpoint,
    fetch_trades,
    parse_outcome_prices,
    parse_token_ids,
)
from .fees import breakeven_edge_bps, compute_trade_fees
from .wallet_analyzer import WalletProfile, screen_copy_candidates

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _infer_category(slug: str, title: str = "") -> str:
    s = (slug + " " + title).lower()
    if any(x in s for x in ["fifwc", "nba", "nfl", "mlb", "vs.", "o/u", "spread:"]):
        return "SPORTS"
    if any(x in s for x in ["trump", "election", "president", "congress"]):
        return "POLITICS"
    if any(x in s for x in ["btc", "bitcoin", "eth", "crypto", "solana"]):
        return "CRYPTO"
    if any(x in s for x in ["fed", "rate", "cpi", "gdp"]):
        return "FINANCE"
    return "OTHER"


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hours_until(iso: str | None) -> float | None:
    dt = _parse_dt(iso)
    if not dt:
        return None
    delta = dt - datetime.now(timezone.utc)
    return round(delta.total_seconds() / 3600, 1)


@dataclass
class Position:
    id: str
    market_slug: str
    condition_id: str
    token_id: str
    title: str
    outcome: str
    side: str
    category: str
    copy_wallet: str | None
    copy_username: str | None
    signal_source: str
    entry_price: float
    shares: float
    entry_fee: float
    cost_basis: float
    opened_at: str
    resolution_date: str | None
    stop_loss_pct: float
    status: str  # OPEN | CLOSED
    current_price: float | None = None
    unrealized_pnl: float | None = None
    market_value: float | None = None
    closed_at: str | None = None
    exit_price: float | None = None
    exit_fee: float | None = None
    realized_pnl: float | None = None
    close_reason: str | None = None
    hours_to_resolution: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.status == "OPEN" and self.resolution_date:
            d["hours_to_resolution"] = _hours_until(self.resolution_date)
        return d


@dataclass
class PortfolioState:
    version: int = 2
    starting_balance: float = 1000.0
    cash_balance: float = 1000.0
    positions: list[Position] = field(default_factory=list)
    closed_trades: list[dict] = field(default_factory=list)
    watchlist: list[dict] = field(default_factory=list)
    seen_signals: list[str] = field(default_factory=list)
    equity_history: list[dict] = field(default_factory=list)
    activity_log: list[dict] = field(default_factory=list)
    last_scan_at: str | None = None
    last_price_update_at: str | None = None
    paused: bool = False
    pause_reason: str | None = None
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)


class PaperPortfolio:
    DEFAULT_STOP_LOSS = 0.50
    MAX_DRAWDOWN_PCT = 0.15
    DAILY_LOSS_LIMIT_PCT = 0.08

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
        self.state_path = state_path or DATA_DIR / "paper_portfolio.json"
        self.state = self._load()

    def _log(self, level: str, message: str, **extra: Any) -> None:
        entry = {"ts": _utcnow(), "level": level, "message": message, **extra}
        self.state.activity_log.insert(0, entry)
        self.state.activity_log = self.state.activity_log[:200]
        getattr(log, level.lower(), log.info)(message)

    def _load(self) -> PortfolioState:
        # Migrate legacy state file if present
        legacy = self.state_path.parent / "forward_test_state.json"
        if not self.state_path.exists() and legacy.exists():
            raw = json.loads(legacy.read_text())
            state = self._migrate_v1(raw)
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state = state
            self.save()
            return state

        if self.state_path.exists():
            raw = json.loads(self.state_path.read_text())
            if raw.get("version", 1) >= 2:
                positions = [Position(**p) for p in raw.get("positions", [])]
                return PortfolioState(
                    version=2,
                    starting_balance=float(raw.get("starting_balance", self.starting_balance)),
                    cash_balance=float(raw.get("cash_balance", self.starting_balance)),
                    positions=positions,
                    closed_trades=raw.get("closed_trades", []),
                    watchlist=raw.get("watchlist", []),
                    seen_signals=raw.get("seen_signals", []),
                    equity_history=raw.get("equity_history", []),
                    activity_log=raw.get("activity_log", []),
                    last_scan_at=raw.get("last_scan_at"),
                    last_price_update_at=raw.get("last_price_update_at"),
                    paused=raw.get("paused", False),
                    pause_reason=raw.get("pause_reason"),
                    created_at=raw.get("created_at", _utcnow()),
                    updated_at=raw.get("updated_at", _utcnow()),
                )
            return self._migrate_v1(raw)
        return PortfolioState(
            starting_balance=self.starting_balance,
            cash_balance=self.starting_balance,
        )

    def _migrate_v1(self, raw: dict) -> PortfolioState:
        """Migrate forward_test_state.json format."""
        positions = []
        for p in raw.get("positions", []):
            positions.append(
                Position(
                    id=str(uuid.uuid4()),
                    market_slug=p.get("market_slug", ""),
                    condition_id=p.get("condition_id", ""),
                    token_id=p.get("token_id", ""),
                    title=p.get("title", p.get("market_slug", "")),
                    outcome=p.get("outcome", "Yes"),
                    side=p.get("side", "BUY"),
                    category=p.get("category", "OTHER"),
                    copy_wallet=p.get("copy_wallet"),
                    copy_username=p.get("copy_username"),
                    signal_source=p.get("signal_source", "migrated"),
                    entry_price=float(p.get("entry_price", 0)),
                    shares=float(p.get("shares", 0)),
                    entry_fee=float(p.get("entry_fee", 0)),
                    cost_basis=float(p.get("cost_basis", 0)),
                    opened_at=p.get("opened_at", _utcnow()),
                    resolution_date=p.get("resolution_date"),
                    stop_loss_pct=self.DEFAULT_STOP_LOSS,
                    status="OPEN",
                )
            )
        wallets = raw.get("watchlist_wallets", [])
        watchlist = [{"address": w, "username": ""} for w in wallets]
        return PortfolioState(
            starting_balance=float(raw.get("starting_balance", self.starting_balance)),
            cash_balance=float(raw.get("balance", self.starting_balance)),
            positions=positions,
            watchlist=watchlist,
        )

    def save(self) -> None:
        self.state.updated_at = _utcnow()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.state.version,
            "starting_balance": self.state.starting_balance,
            "cash_balance": self.state.cash_balance,
            "positions": [p.to_dict() for p in self.state.positions if p.status == "OPEN"],
            "closed_trades": self.state.closed_trades,
            "watchlist": self.state.watchlist,
            "seen_signals": self.state.seen_signals,
            "equity_history": self.state.equity_history[-500:],
            "activity_log": self.state.activity_log,
            "last_scan_at": self.state.last_scan_at,
            "last_price_update_at": self.state.last_price_update_at,
            "paused": self.state.paused,
            "pause_reason": self.state.pause_reason,
            "created_at": self.state.created_at,
            "updated_at": self.state.updated_at,
        }
        fd, tmp = tempfile.mkstemp(dir=self.state_path.parent, suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self.state_path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def reset(self, balance: float | None = None) -> None:
        bal = balance if balance is not None else self.starting_balance
        self.state = PortfolioState(starting_balance=bal, cash_balance=bal)
        self._log("info", f"Paper account reset to ${bal:.2f}")
        self._record_equity()
        self.save()

    def _open_count(self) -> int:
        return sum(1 for p in self.state.positions if p.status == "OPEN")

    def _held_slugs(self) -> set[str]:
        return {p.market_slug for p in self.state.positions if p.status == "OPEN"}

    def _wallet_map(self) -> dict[str, str]:
        return {w["address"].lower(): w.get("username", "") for w in self.state.watchlist}

    def refresh_watchlist(self, top_n: int = 5, fast: bool = False) -> list[dict]:
        """Refresh copy targets. fast=True loads cached profiles without re-analyzing."""
        cached_path = self.state_path.parent / "watchlist.json"
        if fast and cached_path.exists():
            data = json.loads(cached_path.read_text())
            self.state.watchlist = data.get("wallets", [])
            self.save()
            return self.state.watchlist

        try:
            profiles: list[WalletProfile] = screen_copy_candidates(top_n=top_n)
            self.state.watchlist = [
                {
                    "address": p.address,
                    "username": p.username,
                    "roi_pct": p.roi_pct,
                    "copy_score": p.copy_score,
                    "strategy": p.strategy_label,
                    "win_rate_closed": p.win_rate_closed,
                    "leaderboard_pnl": p.leaderboard_pnl,
                    "leaderboard_vol": p.leaderboard_vol,
                }
                for p in profiles
            ]
            cached_path.write_text(
                json.dumps({"updated": _utcnow(), "wallets": self.state.watchlist}, indent=2)
            )
            self._log("info", f"Watchlist refreshed: {len(self.state.watchlist)} traders")
        except Exception as e:
            self._log("error", f"Watchlist refresh failed: {e}")
            if not self.state.watchlist and cached_path.exists():
                data = json.loads(cached_path.read_text())
                self.state.watchlist = data.get("wallets", [])
        self.save()
        return self.state.watchlist

    def update_prices(self) -> None:
        """Mark-to-market all open positions."""
        for pos in self.state.positions:
            if pos.status != "OPEN":
                continue
            mid = fetch_midpoint(pos.token_id)
            if mid is None:
                market = fetch_market_by_slug(pos.market_slug)
                if market:
                    if not pos.resolution_date:
                        pos.resolution_date = market.get("endDate") or market.get("endDateIso")
                    if market.get("closed"):
                        continue  # check_exits handles closed markets
                    prices = parse_outcome_prices(market)
                    tokens = parse_token_ids(market)
                    if tokens and pos.token_id == tokens[0] and prices:
                        mid = float(prices[0])
                    elif tokens and len(tokens) > 1 and pos.token_id == tokens[1] and prices:
                        mid = float(prices[1])
            if mid is None:
                mid = pos.entry_price  # fallback mark
            pos.current_price = mid
            pos.market_value = round(pos.shares * mid, 4)
            gross = pos.shares * mid
            exit_fee = compute_trade_fees(pos.shares, mid, pos.category, is_taker=True).taker_fee
            pos.unrealized_pnl = round(gross - exit_fee - pos.cost_basis, 4)
            pos.hours_to_resolution = _hours_until(pos.resolution_date)
        self.state.last_price_update_at = _utcnow()
        self._record_equity()
        self.save()

    def _close_position(
        self,
        pos: Position,
        exit_price: float,
        reason: str,
        is_resolution: bool = False,
    ) -> None:
        exit_fee = 0.0 if is_resolution else compute_trade_fees(
            pos.shares, exit_price, pos.category, is_taker=True
        ).taker_fee
        proceeds = pos.shares * exit_price - exit_fee
        realized = round(proceeds - pos.cost_basis, 4)
        pos.status = "CLOSED"
        pos.closed_at = _utcnow()
        pos.exit_price = exit_price
        pos.exit_fee = exit_fee
        pos.realized_pnl = realized
        pos.close_reason = reason
        pos.current_price = exit_price
        pos.unrealized_pnl = 0.0
        self.state.cash_balance = round(self.state.cash_balance + proceeds, 4)

        trade = pos.to_dict()
        trade["realized_pnl"] = realized
        self.state.closed_trades.insert(0, trade)
        self.state.closed_trades = self.state.closed_trades[:100]
        # Remove from active positions list
        self.state.positions = [p for p in self.state.positions if p.id != pos.id]
        self._log(
            "info",
            f"Closed {pos.title[:40]} @ {exit_price:.3f} | PnL ${realized:+.2f} ({reason})",
            position_id=pos.id,
        )

    def check_exits(self) -> int:
        """Stop-loss, resolution, stale market, and market-closed checks."""
        closed = 0
        now = datetime.now(timezone.utc)
        for pos in list(self.state.positions):
            if pos.status != "OPEN":
                continue

            market = fetch_market_by_slug(pos.market_slug)
            if market:
                if not pos.resolution_date:
                    pos.resolution_date = market.get("endDate") or market.get("endDateIso")
                if market.get("closed"):
                    prices = parse_outcome_prices(market)
                    if prices:
                        tokens = parse_token_ids(market)
                        if tokens and pos.token_id == tokens[0]:
                            exit_p = float(prices[0])
                        elif tokens and len(tokens) > 1 and pos.token_id == tokens[1]:
                            exit_p = float(prices[1])
                        else:
                            exit_p = float(prices[0])
                        self._close_position(pos, exit_p, "resolution", is_resolution=True)
                        closed += 1
                        continue
            else:
                # Market gone from API — close stale positions after 48h at last known price
                opened = _parse_dt(pos.opened_at)
                if opened and (now - opened).total_seconds() > 48 * 3600:
                    exit_p = pos.current_price or pos.entry_price
                    self._close_position(pos, exit_p, "stale_market")
                    closed += 1
                    continue

            if pos.current_price is not None and pos.entry_price > 0:
                loss_pct = (pos.entry_price - pos.current_price) / pos.entry_price
                if loss_pct >= pos.stop_loss_pct:
                    self._close_position(pos, pos.current_price, "stop_loss")
                    closed += 1
        if closed:
            self._check_risk_pause()
            self._record_equity()
            self.save()
        return closed

    def _check_risk_pause(self) -> None:
        snap = self._compute_totals()
        dd = (self.state.starting_balance - snap["equity"]) / self.state.starting_balance
        if dd >= self.MAX_DRAWDOWN_PCT:
            self.state.paused = True
            self.state.pause_reason = f"Max drawdown {dd*100:.1f}% exceeded"
            self._log("warning", self.state.pause_reason)

    def _record_equity(self) -> None:
        snap = self._compute_totals()
        self.state.equity_history.append(
            {"ts": _utcnow(), "equity": snap["equity"], "cash": snap["cash"]}
        )

    def _signal_key(self, wallet: str, condition_id: str) -> str:
        return f"{wallet.lower()}:{condition_id}"

    def _already_seen(self, key: str) -> bool:
        return key in self.state.seen_signals

    def _mark_seen(self, key: str) -> None:
        self.state.seen_signals.append(key)
        self.state.seen_signals = self.state.seen_signals[-500:]

    def scan_copy_signals(self) -> list[dict]:
        signals = []
        held = self._held_slugs()
        wmap = self._wallet_map()
        for w in self.state.watchlist:
            addr = w["address"]
            username = w.get("username") or wmap.get(addr.lower(), "")
            try:
                trades = fetch_trades(addr, limit=30)
            except Exception as e:
                self._log("warning", f"Failed to fetch trades for {username}: {e}")
                continue
            for t in trades:
                if t.get("side") != "BUY":
                    continue
                cid = t.get("conditionId", "")
                key = self._signal_key(addr, cid)
                if self._already_seen(key):
                    continue
                slug = t.get("slug", "")
                if slug in held:
                    continue
                if not self._market_is_tradeable(slug):
                    continue
                price = float(t.get("price", 0))
                if price < 0.20 or price > 0.85:
                    continue
                signals.append(
                    {
                        "wallet": addr,
                        "username": t.get("name") or username,
                        "slug": slug,
                        "title": t.get("title", slug),
                        "price": price,
                        "condition_id": cid,
                        "token_id": t.get("asset", ""),
                        "outcome": t.get("outcome", "Yes"),
                        "timestamp": t.get("timestamp", 0),
                        "source": "copy_signal",
                        "signal_key": key,
                    }
                )
        signals.sort(key=lambda x: -x.get("timestamp", 0))
        return signals[:10]

    def scan_conviction_signals(self) -> list[dict]:
        signals = []
        held = self._held_slugs()
        try:
            markets = fetch_markets(closed=False, limit=150)
        except Exception as e:
            self._log("warning", f"Market scan failed: {e}")
            return []
        for m in markets:
            prices = parse_outcome_prices(m)
            tokens = parse_token_ids(m)
            if not prices or not tokens:
                continue
            p = float(prices[0])
            if not (self.min_conviction_price <= p <= self.max_conviction_price):
                continue
            slug = m.get("slug", "")
            if slug in held:
                continue
            liq = float(m.get("liquidityNum", 0) or 0)
            if liq < 5000:
                continue
            cat = _infer_category(slug, m.get("question", ""))
            edge = breakeven_edge_bps(p, cat)
            gross_yield = (1.0 - p) / p * 100
            if gross_yield < edge * 2:
                continue
            signals.append(
                {
                    "slug": slug,
                    "title": m.get("question", slug),
                    "price": p,
                    "token_id": tokens[0],
                    "condition_id": m.get("conditionId", ""),
                    "outcome": "Yes",
                    "category": cat,
                    "gross_yield_pct": round(gross_yield, 2),
                    "resolution_date": m.get("endDate"),
                    "source": "conviction_yield",
                    "signal_key": f"conviction:{slug}",
                }
            )
        signals.sort(key=lambda x: -x["gross_yield_pct"])
        return signals[:5]

    def _market_is_tradeable(self, slug: str) -> bool:
        market = fetch_market_by_slug(slug)
        if not market:
            return False
        if market.get("closed"):
            return False
        end = market.get("endDate") or market.get("endDateIso")
        hrs = _hours_until(end)
        if hrs is not None and hrs < -1:
            return False
        return True

    def open_from_signal(self, signal: dict) -> Position | None:
        if self.state.paused:
            return None
        if self._open_count() >= self.max_positions:
            return None

        key = signal.get("signal_key", "")
        if key and self._already_seen(key):
            return None

        slug = signal.get("slug", "")
        if slug in self._held_slugs():
            return None
        if slug and signal.get("source") not in ("manual",) and not self._market_is_tradeable(slug):
            if key:
                self._mark_seen(key)
            return None

        price = float(signal["price"])
        title = signal.get("title", slug)
        cat = signal.get("category") or _infer_category(slug, title)
        alloc = self.state.cash_balance * self.position_pct
        if alloc < 5:
            return None

        shares = alloc / price
        fee = compute_trade_fees(shares, price, cat, is_taker=True).taker_fee
        cost = round(shares * price + fee, 4)
        if cost > self.state.cash_balance:
            return None

        resolution_date = signal.get("resolution_date")
        if not resolution_date:
            market = fetch_market_by_slug(slug)
            if market:
                resolution_date = market.get("endDate") or market.get("endDateIso")

        pos = Position(
            id=str(uuid.uuid4())[:8],
            market_slug=slug,
            condition_id=signal.get("condition_id", ""),
            token_id=signal.get("token_id") or signal.get("asset", ""),
            title=title,
            outcome=signal.get("outcome", "Yes"),
            side="BUY",
            category=cat,
            copy_wallet=signal.get("wallet"),
            copy_username=signal.get("username"),
            signal_source=signal.get("source", "manual"),
            entry_price=price,
            shares=round(shares, 6),
            entry_fee=fee,
            cost_basis=cost,
            opened_at=_utcnow(),
            resolution_date=resolution_date,
            stop_loss_pct=self.DEFAULT_STOP_LOSS,
            status="OPEN",
            current_price=price,
            unrealized_pnl=round(-fee, 4),
            market_value=round(shares * price, 4),
            hours_to_resolution=_hours_until(resolution_date),
        )
        self.state.cash_balance = round(self.state.cash_balance - cost, 4)
        self.state.positions.append(pos)
        if key:
            self._mark_seen(key)
        self._log(
            "info",
            f"Opened {title[:40]} @ {price:.3f} | ${cost:.2f} | copy={signal.get('username', '—')}",
            position_id=pos.id,
        )
        return pos

    def run_cycle(self, max_opens: int = 2) -> dict:
        """Full cycle: exits → prices → scan → open."""
        if not self.state.watchlist:
            self.refresh_watchlist(fast=True)
            if not self.state.watchlist:
                self.refresh_watchlist(fast=False)

        exits = self.check_exits()
        self.update_prices()
        if self.state.paused:
            self.save()
            return {"paused": True, "reason": self.state.pause_reason, "exits": exits}

        copy_sigs = self.scan_copy_signals()
        conv_sigs = self.scan_conviction_signals()
        opened = []

        for sig in copy_sigs:
            if len(opened) >= max_opens:
                break
            sig["category"] = _infer_category(sig.get("slug", ""), sig.get("title", ""))
            pos = self.open_from_signal(sig)
            if pos:
                opened.append(pos.to_dict())

        for sig in conv_sigs:
            if len(opened) >= max_opens:
                break
            pos = self.open_from_signal(sig)
            if pos:
                opened.append(pos.to_dict())

        self.state.last_scan_at = _utcnow()
        self.update_prices()
        self.save()
        return {
            "exits": exits,
            "copy_signals": len(copy_sigs),
            "conviction_signals": len(conv_sigs),
            "opened": opened,
            "opened_count": len(opened),
        }

    def _compute_totals(self) -> dict:
        open_pos = [p for p in self.state.positions if p.status == "OPEN"]
        unrealized = sum(p.unrealized_pnl or 0 for p in open_pos)
        realized = sum(t.get("realized_pnl", 0) or 0 for t in self.state.closed_trades)
        deployed = sum(p.cost_basis for p in open_pos)
        equity = round(self.state.cash_balance + sum(p.market_value or 0 for p in open_pos), 2)
        total_pnl = round(equity - self.state.starting_balance, 2)
        ret_pct = round(total_pnl / self.state.starting_balance * 100, 2) if self.state.starting_balance else 0
        return {
            "cash": round(self.state.cash_balance, 2),
            "deployed": round(deployed, 2),
            "equity": equity,
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl": round(realized, 2),
            "total_pnl": total_pnl,
            "return_pct": ret_pct,
            "open_count": len(open_pos),
        }

    def get_snapshot(self) -> dict:
        """Full dashboard payload."""
        self.check_exits()
        self.update_prices()
        totals = self._compute_totals()
        open_pos = sorted(
            [p.to_dict() for p in self.state.positions if p.status == "OPEN"],
            key=lambda x: x.get("hours_to_resolution") or 99999,
        )
        return {
            "totals": totals,
            "starting_balance": self.state.starting_balance,
            "paused": self.state.paused,
            "pause_reason": self.state.pause_reason,
            "watchlist": self.state.watchlist,
            "open_positions": open_pos,
            "closed_trades": self.state.closed_trades[:30],
            "equity_history": self.state.equity_history[-60:],
            "activity_log": self.state.activity_log[:40],
            "last_scan_at": self.state.last_scan_at,
            "last_price_update_at": self.state.last_price_update_at,
            "updated_at": _utcnow(),
            "config": {
                "position_pct": self.position_pct,
                "max_positions": self.max_positions,
                "stop_loss_pct": self.DEFAULT_STOP_LOSS,
            },
        }
