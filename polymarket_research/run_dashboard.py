#!/usr/bin/env python3
"""Launch the Polo paper trading dashboard — accessible on your network IP."""

import argparse
import logging
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from polymarket_research.dashboard_server import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _local_ips() -> list[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return ips


def _print_urls(host: str, port: int) -> None:
    print("\n  ╔══════════════════════════════════════════════╗")
    print("  ║       Polo Paper Trading — LIVE Dashboard      ║")
    print("  ╚══════════════════════════════════════════════╝\n")
    print("  ⚠️  Paste this URL in your browser (NOT about:blank):\n")
    print(f"  →  http://localhost:{port}")
    if host == "0.0.0.0":
        for ip in _local_ips():
            print(f"  →  http://{ip}:{port}")
    print("\n  In Cursor: open the PORTS tab → forward port 8080 → click the link")
    print("  Updates every ~8s via WebSocket · Auto-scans every 90s\n")


def main():
    parser = argparse.ArgumentParser(description="Polo live paper trading dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (0.0.0.0 = all interfaces)")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    _print_urls(args.host, args.port)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
