# Polo — Polymarket Strategy Research

Deep analysis of Polymarket leaderboard wallets, fees, backtests, and an automatable trading strategy for a **$1,000** starting balance.

## Quick start

```bash
pip install -r polymarket_research/requirements.txt
python polymarket_research/run_research.py   # full research pipeline
python -m polymarket_research.bot --cycles 1 # paper-trading scan
```

## Key finding

**Skilled Copy + Fee-Aware Conviction Yield** — mirror filtered mid-tier sports specialists (not volume whales), add fee-filtered high-conviction entries, execute with maker limit orders.

Full report: [polymarket_research/RESEARCH.md](polymarket_research/RESEARCH.md)

## Project structure

```
polymarket_research/
├── api_client.py      # Gamma / Data / CLOB API client
├── fees.py            # Official fee model
├── wallet_analyzer.py # Leaderboard screening & strategy classification
├── backtest.py        # Historical strategy backtests
├── forward_test.py    # Paper trading engine
├── bot.py             # Automated bot (paper + live)
├── run_research.py    # One-command research pipeline
├── RESEARCH.md        # Full analysis report
└── data/              # Generated research outputs
```

## Data sources (live, no assumptions)

- Leaderboard: `https://data-api.polymarket.com/v1/leaderboard`
- Trades: `https://data-api.polymarket.com/trades`
- Markets: `https://gamma-api.polymarket.com/markets`
- Price history: `https://clob.polymarket.com/prices-history`
- Fees: [docs.polymarket.com/trading/fees](https://docs.polymarket.com/trading/fees)
