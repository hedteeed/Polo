"""Polymarket fee model from official docs (docs.polymarket.com/trading/fees)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Category = Literal[
    "CRYPTO",
    "SPORTS",
    "FINANCE",
    "POLITICS",
    "ECONOMICS",
    "CULTURE",
    "WEATHER",
    "OTHER",
    "MENTIONS",
    "TECH",
    "GEOPOLITICS",
]

# Taker fee rates (feeRate in formula fee = C * feeRate * p * (1-p))
TAKER_FEE_RATES: dict[str, float] = {
    "CRYPTO": 0.07,
    "SPORTS": 0.03,
    "FINANCE": 0.04,
    "POLITICS": 0.04,
    "ECONOMICS": 0.05,
    "CULTURE": 0.05,
    "WEATHER": 0.05,
    "OTHER": 0.05,
    "MENTIONS": 0.04,
    "TECH": 0.04,
    "GEOPOLITICS": 0.0,
}

MAKER_REBATE_PCT: dict[str, float] = {
    "CRYPTO": 0.20,
    "SPORTS": 0.25,
    "FINANCE": 0.25,
    "POLITICS": 0.25,
    "ECONOMICS": 0.25,
    "CULTURE": 0.25,
    "WEATHER": 0.25,
    "OTHER": 0.25,
    "MENTIONS": 0.25,
    "TECH": 0.25,
    "GEOPOLITICS": 0.0,
}


@dataclass(frozen=True)
class FeeBreakdown:
    shares: float
    price: float
    category: str
    is_taker: bool
    gross_usdc: float
    taker_fee: float
    maker_rebate: float
    net_cost: float
    fee_pct_of_notional: float


def taker_fee_usdc(shares: float, price: float, category: str) -> float:
    """fee = C * feeRate * p * (1-p), rounded to 5 decimals per docs."""
    rate = TAKER_FEE_RATES.get(category.upper(), 0.05)
    if rate == 0:
        return 0.0
    raw = shares * rate * price * (1.0 - price)
    return round(raw, 5) if raw >= 0.00001 else 0.0


def maker_rebate_usdc(shares: float, price: float, category: str) -> float:
    """Daily rebate share; approximate per-fill using category rebate %."""
    taker = taker_fee_usdc(shares, price, category)
    pct = MAKER_REBATE_PCT.get(category.upper(), 0.25)
    return round(taker * pct, 5)


def compute_trade_fees(
    shares: float,
    price: float,
    category: str,
    is_taker: bool = True,
) -> FeeBreakdown:
    gross = shares * price
    taker = taker_fee_usdc(shares, price, category) if is_taker else 0.0
    rebate = 0.0 if is_taker else maker_rebate_usdc(shares, price, category)
    net = gross + taker - rebate
    pct = (taker / gross * 100) if gross > 0 and is_taker else 0.0
    return FeeBreakdown(
        shares=shares,
        price=price,
        category=category,
        is_taker=is_taker,
        gross_usdc=gross,
        taker_fee=taker,
        maker_rebate=rebate,
        net_cost=net,
        fee_pct_of_notional=pct,
    )


def breakeven_edge_bps(price: float, category: str) -> float:
    """Minimum edge (probability points) to overcome taker fee on entry+exit."""
    rate = TAKER_FEE_RATES.get(category.upper(), 0.05)
    if rate == 0:
        return 0.0
    # Round-trip fee as fraction of notional at price p
    single = rate * price * (1.0 - price)
    round_trip = 2 * single
    return round_trip * 100  # convert to percentage points


def fee_table_sample(category: str = "SPORTS", shares: float = 100.0) -> list[dict]:
    rows = []
    for p in [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]:
        fb = compute_trade_fees(shares, p, category, is_taker=True)
        rows.append(
            {
                "price": p,
                "notional": fb.gross_usdc,
                "taker_fee": fb.taker_fee,
                "fee_pct": fb.fee_pct_of_notional,
                "breakeven_edge_pts": breakeven_edge_bps(p, category),
            }
        )
    return rows
