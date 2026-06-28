"""Polymarket public API client (Gamma, Data, CLOB)."""

from __future__ import annotations

import json
import time
from typing import Any

import requests

GAMMA_URL = "https://gamma-api.polymarket.com"
DATA_URL = "https://data-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "polymarket-research/1.0"})


def _get(url: str, params: dict | None = None, retries: int = 3) -> Any:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last_err}")


def fetch_leaderboard(
    category: str = "OVERALL",
    time_period: str = "MONTH",
    order_by: str = "PNL",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return _get(
        f"{DATA_URL}/v1/leaderboard",
        {
            "category": category,
            "timePeriod": time_period,
            "orderBy": order_by,
            "limit": limit,
            "offset": offset,
        },
    )


def fetch_trades(user: str, limit: int = 500, offset: int = 0) -> list[dict]:
    return _get(
        f"{DATA_URL}/trades",
        {"user": user, "limit": limit, "offset": offset},
    )


def fetch_all_trades(user: str, max_trades: int = 2000) -> list[dict]:
    out: list[dict] = []
    offset = 0
    page = 500
    while len(out) < max_trades:
        batch = fetch_trades(user, limit=page, offset=offset)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return out[:max_trades]


def fetch_closed_positions(user: str, limit: int = 50, offset: int = 0) -> list[dict]:
    return _get(
        f"{DATA_URL}/closed-positions",
        {"user": user, "limit": limit, "offset": offset},
    )


def fetch_activity(user: str, limit: int = 500, offset: int = 0) -> list[dict]:
    return _get(
        f"{DATA_URL}/activity",
        {"user": user, "limit": limit, "offset": offset},
    )


def fetch_markets(
    closed: bool | None = None,
    limit: int = 100,
    offset: int = 0,
    order: str | None = None,
    ascending: bool = False,
) -> list[dict]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if closed is not None:
        params["closed"] = str(closed).lower()
    if order:
        params["order"] = order
        params["ascending"] = str(ascending).lower()
    return _get(f"{GAMMA_URL}/markets", params)


def parse_outcome_prices(market: dict) -> list[float]:
    raw = market.get("outcomePrices")
    if not raw:
        return []
    if isinstance(raw, str):
        return [float(x) for x in json.loads(raw)]
    return [float(x) for x in raw]


def parse_token_ids(market: dict) -> list[str]:
    raw = market.get("clobTokenIds")
    if not raw:
        return []
    if isinstance(raw, str):
        return json.loads(raw)
    return list(raw)


def fetch_price_history(
    token_id: str,
    interval: str = "1w",
    fidelity: int = 60,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> list[dict]:
    params: dict[str, Any] = {"market": token_id, "fidelity": fidelity}
    if interval:
        params["interval"] = interval
    if start_ts:
        params["startTs"] = start_ts
    if end_ts:
        params["endTs"] = end_ts
    data = _get(f"{CLOB_URL}/prices-history", params)
    return data.get("history", [])


def fetch_orderbook(token_id: str) -> dict:
    return _get(f"{CLOB_URL}/book", {"token_id": token_id})


def fetch_spread(token_id: str) -> float | None:
    book = fetch_orderbook(token_id)
    bids = book.get("bids", [])
    asks = book.get("asks", [])
    if not bids or not asks:
        return None
    return float(asks[0]["price"]) - float(bids[0]["price"])
