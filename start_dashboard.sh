#!/bin/bash
# One-click: starts dashboard + public link you can click
cd "$(dirname "$0")"
pip install -q -r polymarket_research/requirements.txt 2>/dev/null
exec python3 polymarket_research/launch.py
