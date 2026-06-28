#!/usr/bin/env python3
"""Launch the Polo paper trading dashboard."""

import argparse
import logging
import sys
from pathlib import Path

# Ensure package import works when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from polymarket_research.dashboard_server import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Polo paper trading dashboard")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"\n  Polo Paper Trading Dashboard")
    print(f"  Open http://localhost:{args.port} in your browser\n")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
