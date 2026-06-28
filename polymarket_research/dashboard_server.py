"""FastAPI dashboard server for paper trading."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .paper_portfolio import PaperPortfolio

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
portfolio: PaperPortfolio | None = None
_scan_task: asyncio.Task | None = None
_live_task: asyncio.Task | None = None
_ws_clients: set[WebSocket] = set()
AUTO_SCAN_SEC = 90
LIVE_PUSH_SEC = 8


class ResetRequest(BaseModel):
    balance: float = 1000.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global portfolio, _scan_task, _live_task
    portfolio = PaperPortfolio()
    if not portfolio.state.watchlist:
        portfolio.refresh_watchlist(fast=True)
    # Fast startup — run heavy checks in background
    asyncio.create_task(_startup_tasks())
    _scan_task = asyncio.create_task(_auto_scan_loop())
    _live_task = asyncio.create_task(_live_push_loop())
    log.info("Dashboard ready at http://0.0.0.0:8080")
    yield
    for task in (_scan_task, _live_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _startup_tasks():
    try:
        if portfolio:
            await asyncio.to_thread(portfolio.check_exits)
            portfolio.update_prices()
            portfolio._record_equity()
            portfolio.save()
            log.info("Portfolio loaded — equity $%.2f", portfolio.get_snapshot(full=False)["totals"]["equity"])
    except Exception:
        log.exception("Startup portfolio init failed")


async def _auto_scan_loop():
    while True:
        try:
            await asyncio.sleep(AUTO_SCAN_SEC)
            if portfolio and not portfolio.state.paused:
                await asyncio.to_thread(portfolio.run_cycle)
                await _broadcast_snapshot()
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("Auto-scan error")


_exit_check_counter = 0

async def _live_push_loop():
    """Push portfolio updates to all WebSocket clients every LIVE_PUSH_SEC."""
    global _exit_check_counter
    while True:
        try:
            await asyncio.sleep(LIVE_PUSH_SEC)
            _exit_check_counter += 1
            if portfolio and _exit_check_counter % 4 == 0:
                await asyncio.to_thread(portfolio.check_exits)
            await _broadcast_snapshot()
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("Live push error")


async def _broadcast_snapshot():
    if not portfolio or not _ws_clients:
        return
    snap = await asyncio.to_thread(lambda: portfolio.get_snapshot(full=False))
    snap["live"] = True
    dead: list[WebSocket] = []
    for ws in list(_ws_clients):
        try:
            await ws.send_json(snap)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


app = FastAPI(title="Polo Paper Trading", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _build_dashboard_html() -> str:
    """Single-file HTML with inlined CSS/JS — no external deps, instant render."""
    index = (STATIC_DIR / "index.html").read_text()
    css = (STATIC_DIR / "styles.css").read_text()
    js = (STATIC_DIR / "app.js").read_text()
    # Remove external stylesheet/script links and google fonts
    index = index.replace('<link rel="stylesheet" href="/static/styles.css" />', f"<style>{css}</style>")
    index = index.replace(
        '<link rel="preconnect" href="https://fonts.googleapis.com" />\n  '
        '<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />',
        "",
    )
    index = index.replace('<script src="/static/app.js"></script>', f"<script>{js}</script>")
    # Instant dark background before any JS
    index = index.replace("<body>", '<body style="background:#0b0d12;color:#e8ecf4;margin:0">')
    return index


_dashboard_html_cache: str | None = None


def _get_dashboard_html() -> str:
    global _dashboard_html_cache
    if _dashboard_html_cache is None:
        _dashboard_html_cache = _build_dashboard_html()
    return _dashboard_html_cache


@app.get("/")
async def index():
    return HTMLResponse(_get_dashboard_html(), headers={"Cache-Control": "no-cache"})


@app.get("/api/info")
async def api_info():
    import socket
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return {
        "status": "running",
        "urls": [f"http://{ip}:8080" for ip in ips] + ["http://localhost:8080"],
        "message": "Open one of these URLs in your browser (not about:blank)",
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": "paper"}


@app.get("/api/portfolio")
async def get_portfolio():
    assert portfolio is not None
    return await asyncio.to_thread(lambda: portfolio.get_snapshot(full=True))


@app.post("/api/scan")
async def run_scan():
    assert portfolio is not None
    result = await asyncio.to_thread(portfolio.run_cycle)
    snap = portfolio.get_snapshot()
    await _broadcast_snapshot()
    return {"cycle": result, "portfolio": snap}


@app.post("/api/prices")
async def update_prices():
    assert portfolio is not None
    await asyncio.to_thread(portfolio.update_prices)
    await asyncio.to_thread(portfolio.check_exits)
    snap = portfolio.get_snapshot()
    await _broadcast_snapshot()
    return snap


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


@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    log.info("WebSocket client connected (%d total)", len(_ws_clients))
    try:
        if portfolio:
            snap = await asyncio.to_thread(lambda: portfolio.get_snapshot(full=False))
            snap["live"] = True
            await ws.send_json(snap)
        while True:
            # Client sends "ping" keepalives; we push via _live_push_loop
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)
        log.info("WebSocket client disconnected (%d remain)", len(_ws_clients))
