#!/bin/bash
# Start Polo live dashboard — paste the printed URL into your browser
cd "$(dirname "$0")/.."
pip install -q -r polymarket_research/requirements.txt 2>/dev/null
exec python3 polymarket_research/run_dashboard.py --host 0.0.0.0 --port 8080
