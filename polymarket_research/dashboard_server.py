"""FastAPI dashboard server for paper trading."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .paper_portfolio import PaperPortfolio

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
portfolio: PaperPortfolio | None = None
_scan_task: asyncio.Task | None = None
AUTO_SCAN_SEC = 90


class ResetRequest(BaseModel):
    balance: float = 1000.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global portfolio, _scan_task
    portfolio = PaperPortfolio()
    if not portfolio.state.watchlist:
        portfolio.refresh_watchlist(fast=True)
    await asyncio.to_thread(portfolio.check_exits)
    portfolio.update_prices()
    portfolio._record_equity()
    portfolio.save()
    _scan_task = asyncio.create_task(_auto_scan_loop())
    log.info("Paper portfolio started — equity $%.2f", portfolio.get_snapshot()["totals"]["equity"])
    yield
    if _scan_task:
        _scan_task.cancel()
        try:
            await _scan_task
        except asyncio.CancelledError:
            pass


async def _auto_scan_loop():
    while True:
        try:
            await asyncio.sleep(AUTO_SCAN_SEC)
            if portfolio and not portfolio.state.paused:
                await asyncio.to_thread(portfolio.run_cycle)
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("Auto-scan error")


app = FastAPI(title="Polo Paper Trading", lifespan=lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "Dashboard UI not found")
    return FileResponse(index_path)


@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": "paper"}


@app.get("/api/portfolio")
async def get_portfolio():
    assert portfolio is not None
    return await asyncio.to_thread(portfolio.get_snapshot)


@app.post("/api/scan")
async def run_scan():
    assert portfolio is not None
    result = await asyncio.to_thread(portfolio.run_cycle)
    snap = portfolio.get_snapshot()
    return {"cycle": result, "portfolio": snap}


@app.post("/api/prices")
async def update_prices():
    assert portfolio is not None
    await asyncio.to_thread(portfolio.update_prices)
    await asyncio.to_thread(portfolio.check_exits)
    return portfolio.get_snapshot()


@app.post("/api/watchlist/refresh")
async def refresh_watchlist(fast: bool = Query(False)):
    assert portfolio is not None
    wl = await asyncio.to_thread(portfolio.refresh_watchlist, 5, fast)
    snap = portfolio.get_snapshot()
    return {"watchlist": wl, "count": len(wl), "portfolio": snap}


@app.post("/api/reset")
async def reset_portfolio(req: ResetRequest):
    assert portfolio is not None
    await asyncio.to_thread(portfolio.reset, req.balance)
    return portfolio.get_snapshot()


@app.post("/api/resume")
async def resume_trading():
    assert portfolio is not None
    portfolio.state.paused = False
    portfolio.state.pause_reason = None
    portfolio.save()
    return portfolio.get_snapshot()
