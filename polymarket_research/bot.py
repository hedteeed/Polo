"""
Automated Polymarket trading bot — recommended hybrid strategy.

Strategy: "Skilled Copy + Fee-Aware Conviction Yield"
- Primary edge: mirror filtered mid-tier leaderboard wallets (sports specialists)
- Secondary: high-conviction yield (90-95c) when gross yield > 2x fee breakeven
- Execution: prefer maker limit orders; taker only when signal urgency demands it
- Risk: 4% per position, max 8 concurrent, 32% max deployment

Requires env vars for live trading:
  POLY_PRIVATE_KEY, POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE, POLY_FUNDER
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .api_client import fetch_trades
from .fees import compute_trade_fees, breakeven_edge_bps
from .paper_portfolio import PaperPortfolio
from .wallet_analyzer import screen_copy_candidates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("polymarket_bot")


@dataclass
class BotConfig:
    starting_balance: float = 1000.0
    position_pct: float = 0.04
    max_positions: int = 8
    min_conviction_price: float = 0.90
    max_conviction_price: float = 0.95
    copy_wallet_count: int = 5
    poll_interval_sec: int = 60
    paper_mode: bool = True
    state_dir: Path = Path(__file__).resolve().parent / "data"


class PolymarketBot:
    def __init__(self, config: BotConfig | None = None):
        self.config = config or BotConfig()
        self.forward = PaperPortfolio(
            starting_balance=self.config.starting_balance,
            position_pct=self.config.position_pct,
            max_positions=self.config.max_positions,
            min_conviction_price=self.config.min_conviction_price,
            max_conviction_price=self.config.max_conviction_price,
            state_path=self.config.state_dir / "paper_portfolio.json",
        )
        self._live_client = None

    def _init_live_client(self):
        """Initialize py-clob-client when paper_mode=False."""
        if self.config.paper_mode:
            return None
        try:
            from py_clob_client.client import ClobClient  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Install py-clob-client for live trading: pip install py-clob-client"
            ) from e

        key = os.environ["POLY_PRIVATE_KEY"]
        host = os.environ.get("POLY_CLOB_HOST", "https://clob.polymarket.com")
        chain_id = int(os.environ.get("POLY_CHAIN_ID", "137"))
        funder = os.environ.get("POLY_FUNDER", "")
        sig_type = int(os.environ.get("POLY_SIGNATURE_TYPE", "1"))

        client = ClobClient(host, key=key, chain_id=chain_id, signature_type=sig_type, funder=funder)
        client.set_api_creds(client.create_or_derive_api_creds())
        return client

    def refresh_watchlist(self) -> list[dict]:
        candidates = screen_copy_candidates(top_n=self.config.copy_wallet_count)
        self.forward.state.watchlist = [
            {"address": c.address, "username": c.username, "roi_pct": c.roi_pct,
             "copy_score": c.copy_score, "strategy": c.strategy_label}
            for c in candidates
        ]
        self.forward.save()
        profiles = [c.__dict__ if hasattr(c, "__dict__") else c for c in candidates]
        out_path = self.config.state_dir / "watchlist.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "updated": datetime.now(timezone.utc).isoformat(),
                    "wallets": [
                        {
                            "address": c.address,
                            "username": c.username,
                            "roi_pct": c.roi_pct,
                            "copy_score": c.copy_score,
                            "strategy": c.strategy_label,
                        }
                        for c in candidates
                    ],
                },
                indent=2,
            )
        )
        log.info("Watchlist refreshed: %d wallets", len(candidates))
        return profiles

    def place_limit_order(self, token_id: str, price: float, size: float, side: str = "BUY") -> dict | None:
        """Place maker limit order (live mode only)."""
        if self.config.paper_mode:
            log.info("PAPER limit %s %s shares @ %.4f token=%s", side, size, price, token_id[:16])
            return {"status": "paper", "token_id": token_id, "price": price, "size": size}

        if self._live_client is None:
            self._live_client = self._init_live_client()

        from py_clob_client.clob_types import OrderArgs  # type: ignore

        args = OrderArgs(token_id=token_id, price=price, size=size, side=side)
        return self._live_client.create_and_post_order(args)

    def run_once(self) -> dict:
        result = self.forward.run_cycle()
        snap = self.forward.get_snapshot()
        log.info(
            "Cycle: equity=%.2f positions=%d opened=%d",
            snap["totals"]["equity"],
            snap["totals"]["open_count"],
            result.get("opened_count", 0),
        )
        return {**result, "portfolio": snap}

    def run_loop(self, max_cycles: int | None = None) -> None:
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            try:
                if cycles % 10 == 0:
                    self.refresh_watchlist()
                self.run_once()
            except Exception:
                log.exception("Cycle error")
            cycles += 1
            time.sleep(self.config.poll_interval_sec)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Polymarket hybrid strategy bot")
    parser.add_argument("--live", action="store_true", help="Enable live trading (requires credentials)")
    parser.add_argument("--cycles", type=int, default=1, help="Number of scan cycles (0=forever)")
    parser.add_argument("--balance", type=float, default=1000.0)
    args = parser.parse_args()

    cfg = BotConfig(starting_balance=args.balance, paper_mode=not args.live)
    bot = PolymarketBot(cfg)
    bot.refresh_watchlist()
    if args.cycles == 0:
        bot.run_loop()
    else:
        for _ in range(args.cycles):
            bot.run_once()


if __name__ == "__main__":
    main()
