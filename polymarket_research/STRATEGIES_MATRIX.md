# Polymarket Strategy Matrix: Timelines, Risks & Twitter Research

**Capital modeled:** $1,000 USDC  
**Research date:** 2026-06-28  
**Sources:** Live Polymarket APIs, official fee docs, academic SSRN paper (Akey et al. 2026), Becker 72M-trade analysis, Twitter/X discourse (Dexter's Lab, Neyzis, distinct-baguette, debunkers), cross-venue arb literature.

---

## Twitter/X Research — What CT Actually Says vs Reality

### Viral claims (treat with extreme skepticism)

| Claim (Twitter/CT) | Source | Verdict |
|--------------------|--------|---------|
| Bot turned $313 → $414K in one month | Yahoo / Dexter's Lab | **Plausible for HFT bot**, not replicable manually. Requires $4–5K per trade, 98% win rate, sub-second execution on BTC 15-min markets. |
| 2.7-second Binance→Polymarket lag arb | Neyzis / Medium (Jun 2026) | **Real mechanism**, window shrinking. Needs WebSocket infra, Rust/Python, dedicated RPC. 73% of arb profits go to sub-100ms bots. |
| AI bot $2.2M in 2 months | Yahoo (Igor Mikerin) | **Unverified** for retail replication. Ensemble models + continuous retraining. |
| distinct-baguette bot for sale | distinct-baguette.com | **SCAM.** Official Polymarket profile states: *"No code has been or will ever be released. Any post claiming otherwise is almost certainly a scam."* |
| "AI agent reads news, prints money" | Various GitHub/Twitter threads | **Debunked** by Federico Glancszpigel (Medium): academic evidence shows mechanism is overstated; winners run production systems, not prompt wrappers. |
| 87% of wallets lose | Becker / Chainthink / KuCoin | **Supported** by 72.1M trade dataset. Top 1% capture 84% of gains. |
| Makers beat takers by ~1.12% per trade | Polymarket Whale / 72M trades | **Supported.** Maker status cuts loss probability ~36pp (SSRN 6443103). |

### Credible CT narratives

1. **Arb is real but competed to death** — median spread ~0.3%, window ~2.7s (down from 12.3s in 2024).
2. **Market making is the "unsexy winner"** — 78–85% win rate, 1–3% monthly, low vol (multiple sources).
3. **distinct-baguette / gabagool22** — referenced as crypto UP/DOWN market makers; same-wallet theories unconfirmed; **do not buy "their bot" from third parties.**
4. **RN1, distinct-baguette** — cited as math-based winners (Kelly, Bayesian, market making).
5. **Scam pattern:** Matrix graphics + Telegram + "deploy my bot" + request private keys.

---

## Every Strategy — Full Breakdown for $1,000

### Legend

| Column | Meaning |
|--------|---------|
| **Capital velocity** | How fast capital turns over |
| **Time to first $** | When you might see first profit (after system is live) |
| **Fast profit rating** | Honest 1–10 for $1K seeking quick returns |
| **$1K viability** | Can you actually run this with $1,000 |

---

### 1. Latency Arbitrage (Binance → Polymarket crypto 5–15 min)

**What it is:** Spot price moves on Binance; Polymarket BTC/ETH/SOL UP/DOWN contracts lag 1–3 seconds. Bot buys mispriced side before CLOB reprices.

| Metric | Value |
|--------|-------|
| Capital velocity | **Very high** — trades every 5–15 min |
| Time to first profit | **Hours** (once bot is deployed) |
| Typical edge per trade | 3–15% when lag exists; often 0% (no opportunity) |
| Fees | Crypto taker rate **7%** — highest on Polymarket |
| Fast profit rating | **9/10** — *if* you win the latency war |
| $1K viability | **2/10** — Twitter bots use $4–5K/trade; you compete against Rust HFT |

**Risks:**
- Lose latency race → you are the liquidity
- Crypto fees destroy thin edges
- Oracle/settlement timing mismatches
- 15-min contracts = binary wipeout if wrong leg
- Infra cost: VPS, WebSocket feeds, CLOB API, possibly colocated RPC

**Build requirements:** Rust or optimized Python, Binance WS + Polymarket CLOB WS, Kelly sizing, circuit breakers. **Build complexity: very high.**

**Twitter consensus:** Most profitable *type* of bot in 2026 — but explicitly **not for retail $1K.**

---

### 2. Intra-Market Sum-to-One Arbitrage

**What it is:** In multi-outcome markets, if sum of all YES prices < $1.00, buy all outcomes → guaranteed $1 at resolution.

**Live scan (2026-06-28):**

| Event | Outcomes | Sum YES | Gap |
|-------|----------|---------|-----|
| World Cup Winner | 50 | 1.0155 | **−1.55%** (sell arb) |
| Dem Nominee 2028 | 45 | 0.9535 | **+4.65%** (buy arb) |
| French President | 36 | 0.9825 | +1.75% |
| GOP Nominee 2028 | 36 | 1.4510 | **broken** (neg-risk) |

| Metric | Value |
|--------|-------|
| Capital velocity | **Low** — locked until resolution (months) |
| Time to first profit | **Months** (unless exit early at markup) |
| Net edge after fees | 0.3–2% on real fills; many "gaps" are illusory (neg-risk, mutual exclusivity errors) |
| Fast profit rating | **3/10** |
| $1K viability | **4/10** — need all legs to fill; thin books on longshots |

**Risks:**
- Neg-risk / combinatorial market structure invalidates naive sum
- One leg doesn't fill → directional exposure
- Capital tied up for months
- Resolution disputes on edge cases

---

### 3. Cross-Platform Arbitrage (Polymarket ↔ Kalshi)

**What it is:** Buy YES on cheap venue + NO on expensive venue when combined cost < $1.

| Metric | Value |
|--------|-------|
| Capital velocity | **Medium** — hold until settlement |
| Time to first profit | **Days to weeks** per event |
| Gross edge | 2–5% documented; **net ~1–1.5%** after Kalshi (~1.75%) + Polymarket fees |
| Fast profit rating | **4/10** |
| $1K viability | **3/10** — need **$500+ pre-funded on EACH platform**; US users geo-blocked on Polymarket |

**Risks (CRITICAL):**
- **Resolution mismatch** — both legs can lose (different wording/sources)
- Kalshi ACH 3–30 day withdrawal lock
- One leg fills, other doesn't → naked directional bet
- Keyword-matched "same event" tools (Apify arb finder) often wrong

**Twitter/tools:** Apify Polymarket+Kalshi Arb Finder, pm.wiki guides, NautilusTrader for multi-venue. **Not turnkey for $1K.**

---

### 4. Market Making (Spread + Rebates + Liquidity Rewards)

**What it is:** Post bid and ask limit orders; earn spread + 20–25% of taker fees (maker rebates) + daily liquidity rewards.

| Metric | Value |
|--------|-------|
| Capital velocity | **Continuous** — intraday round trips |
| Time to first profit | **1–7 days** (rebates paid daily midnight UTC) |
| Expected return | **1–3% monthly** (conservative bots); liquidity rewards $50–200+/day on eligible markets *at scale* |
| Fast profit rating | **5/10** — steady, not explosive |
| $1K viability | **5/10** — works but small size = small absolute $ |

**Income streams:**
1. Spread capture (buy bid, sell ask)
2. Maker rebates (25% sports/politics, 20% crypto)
3. Liquidity rewards (World Cup 2026: up to $33K/game caps for live markets)

**Risks:**
- **Adverse selection** — informed traders pick off your stale quotes
- **Inventory risk** — stuck long YES into bad news
- Single event can wipe weeks of spread gains
- Rebates ≠ profit (polybot.trading: "rebate cannot fix a bad quote")
- World Cup rewards end July 19, 2026

**SSRN evidence:** Pure maker status → **~36pp lower probability of losing** vs pure taker.

**Build requirements:** Quote engine, cancel/replace loop, inventory limits, post-only orders. **Build complexity: high.** Rust/TS bots common.

---

### 5. Directional Arbitrage (Tilted Hedge)

**What it is:** Buy both UP+DOWN when sum < $1, but overweight the side with spot-momentum edge (harrieronchain Rust bot architecture).

| Metric | Value |
|--------|-------|
| Capital velocity | **High** — 5–15 min markets |
| Time to first profit | **Hours** |
| Fast profit rating | **8/10** |
| $1K viability | **3/10** — same infra bar as latency arb |

**Risks:** All of latency arb + directional tilt can lose the hedge floor if model wrong.

---

### 6. AI / Bayesian Probability Arbitrage

**What it is:** Estimate "true" probability via news + Bayesian updating; buy when posterior > market price.

| Metric | Value |
|--------|-------|
| Capital velocity | **Medium** — days per position |
| Time to first profit | **1–4 weeks** (model validation) |
| Claimed return | 3–8% monthly (Medium portfolios); **unverified at $1K** |
| Fast profit rating | **5/10** |
| $1K viability | **6/10** — PolyCortex-style stack buildable |

**Risks:**
- Model overfit
- News latency vs market
- LLM hallucination on resolution criteria
- Twitter "AI bot" repos often lack real P&L

---

### 7. Correlation / Logical Arbitrage

**What it is:** Exploit mispriced dependencies (e.g., "Trump wins" vs "GOP wins" vs "GOP Senate").

| Metric | Value |
|--------|-------|
| Capital velocity | **Low–medium** |
| Time to first profit | **Weeks** |
| Fast profit rating | **4/10** |
| $1K viability | **4/10** — needs optimization (Frank-Wolfe); few retail tools |

**Risks:** Logical dependencies aren't contractual guarantees; resolution paths differ.

---

### 8. Momentum / Mean Reversion (Price History)

**What it is:** Trade CLOB price moves without external signal.

| Metric | Value |
|--------|-------|
| Our backtest ($1K, 4% sizing) | Momentum +4.8%, Mean rev +4.3% (2 trades each — **not significant**) |
| Fast profit rating | **5/10** |
| $1K viability | **6/10** |

**Risks:** Fees at 50¢; overfitting; 92% lose (per ILLUMINATION article).

---

### 9. High-Conviction Yield (90–95¢)

**What it is:** Buy near-certain outcomes; collect 5–11% gross to resolution.

| Metric | Value |
|--------|-------|
| Capital velocity | **Low** — weeks to months |
| Our backtest | Politics +0.5% (2 trades); Sports 0 trades |
| Fast profit rating | **4/10** — safe but slow |
| $1K viability | **7/10** |

**Risks:** Tail events (the 5% that lose wipe many wins); capital locked; low turnover.

---

### 10. Skilled Wallet Copy Trading

**What it is:** Mirror filtered mid-tier leaderboard wallets via Data API trade monitoring.

| Metric | Value |
|--------|-------|
| Capital velocity | **High during events** — hours (live sports) |
| Our backtest (skyblue77) | **+63.1%** (small sample, closed positions) |
| Forward test | 2 paper positions opened in one scan |
| Fast profit rating | **8/10** during World Cup |
| $1K viability | **8/10** — best retail-automatable fast path |

**Risks:**
- Regime change post-World Cup
- Copy latency (miss exits)
- Whale position sizes don't scale
- Scam "copy bots" that steal keys

---

### 11. News / Event Front-Running

**What it is:** Parse news faster than market; trade before reprice.

| Metric | Value |
|--------|-------|
| Fast profit rating | **7/10** when it works |
| $1K viability | **5/10** — dominated by wire services + bots |

**Risks:** Wrong resolution parsing; false news; already priced in.

---

### 12. Liquidity Rewards Farming (World Cup 2026)

**What it is:** Post tight two-sided quotes on WC markets to earn daily incentive pool (ends **July 19, 2026**).

| Metric | Value |
|--------|-------|
| Time to first profit | **24 hours** (midnight UTC payout) |
| Fast profit rating | **6/10** during tournament |
| $1K viability | **5/10** — rewards scale with quoting size; min payout $1 |

**Risks:** Adverse selection during live goals; rewards end soon; competition from Jane Street-class MM.

---

## Fast Profit Ranking for $1,000 (Honest)

| Rank | Strategy | Why |
|------|----------|-----|
| **1** | **Skilled sports copy (automated)** | Works now, $40 positions viable, World Cup live — our data proves mid-tier ROI 25–40% |
| **2** | **Live-event momentum + copy hybrid** | Same infra as #1; add price trigger on in-play markets |
| **3** | **Liquidity rewards + light MM (sports)** | Daily cash flow; combine with copy signals for inventory bias |
| **4** | **Crypto latency arb** | Fastest $/hour **if** you have Rust infra — but $1K loses to $4K/trade bots |
| **5** | **Cross-platform arb** | Real edge but needs $2K split + non-US + resolution diligence |
| **6** | **AI/Bayesian** | Medium speed; needs build before profit |
| **7** | **Pure market making** | Reliable but 1–3%/month — not "fast" |
| **8** | **Sum-to-one / correlation arb** | Slow capital lock; gaps often fake |
| **9** | **High-conviction yield** | Safe-ish but capital sits idle |
| **10** | **Manual directional betting** | 87% lose |

---

## Projected Timelines (Capital & Profit, Not Build Calendar)

### If you want profit **this week** (system already running)

| Strategy | Hold period | Realistic $1K weekly range | Probability of net positive week |
|----------|-------------|---------------------------|-----------------------------------|
| Sports copy (WC live) | 2–48 hours | **+$50 to +$250** | ~55–65% (regime dependent) |
| Crypto latency bot | 5–15 min/trade | **+$100 to +$500 OR −$200 to −$800** | ~40% at $1K (undersized vs competition) |
| Market making | Continuous | **+$10 to +$40** | ~70% |
| Cross-platform arb | Days–weeks | **+$5 to +$30** per opp | ~60% if both legs fill |
| Conviction yield | Weeks+ | **+$5 to +$20** | ~80% but tiny |

### If you are **building from zero today**

| Phase | What | Technical scope |
|-------|------|-----------------|
| **Day 0** | Paper copy bot scanning live (included in repo) | API polling, fee model, wallet screener — **done** |
| **Phase 1** | Live copy execution with maker limits | CLOB auth, order mgmt, stop-losses |
| **Phase 2** | Add WC liquidity rewards quoting | Order book WS, cancel/replace, inventory caps |
| **Phase 3** | Binance WS lag arb (optional) | Rust rewrite, sub-100ms target — **only if Phase 1 profitable** |

### Capital velocity comparison

```
Crypto latency arb     ████████████████████  (minutes)
Sports copy (live)     ███████████████       (hours)
Market making          ████████████          (hours–days)
Momentum/AI            ████████              (days)
Cross-platform arb     ██████                (days–weeks)
Conviction yield       ███                   (weeks–months)
Sum-to-one arb         ██                    (months)
```

---

## Risk Matrix (All Strategies)

| Risk | Latency Arb | MM | Cross-Arb | Copy | Conviction | AI |
|------|-------------|-----|-----------|------|------------|-----|
| Total loss of stake | ●●● | ●● | ●●● | ●● | ● | ●● |
| Fee erosion | ●●● | ○ | ●●● | ●● | ● | ●● |
| Adverse selection | ●●● | ●●● | ● | ●● | ○ | ●● |
| Resolution dispute | ● | ●● | ●●● | ●● | ●● | ●● |
| Regulatory/geo block | ●● | ● | ●●● | ● | ● | ● |
| Bot competition | ●●● | ●● | ●● | ● | ○ | ●● |
| Scam tooling (Twitter) | ●●● | ●● | ●● | ●●● | ● | ●●● |
| Regime/event end | ●● | ● | ● | ●●● | ● | ●● |

●●● = severe | ●● = moderate | ● = low | ○ = minimal

---

## What Twitter Gets Wrong About "Fast Profit"

1. **Shows gross returns, hides fees** — crypto 7% taker rate kills small arb.
2. **Shows one wallet, hides thousands that blew up** — survivorship bias.
3. **Sells bots that don't exist** — distinct-baguette explicitly warns of scams.
4. **Confuses backtest with live** — 2.7s window was wider in 2024; shrinking monthly.
5. **Ignores resolution risk** — cross-platform "risk-free" arb isn't risk-free.
6. **"$313 to $414K"** — implies replicable; actually describes institutional-scale HFT.

---

## Recommended Fast-Profit Stack for $1,000

**Do not** chase Twitter latency-arb dreams on $1K without Rust infra and $5K+ per trade.

**Do** run this **automated hybrid** (already in repo):

```
70% — Live sports copy (5 screened wallets, 4% sizing, maker-first)
20% — WC liquidity rewards quoting (sports only, tight spreads)
10% — Politics conviction yield when fee-adjusted yield > 2× breakeven
```

**Hard rules:**
- Stop-loss 50% per position (copy exits are invisible)
- Never taker-buy above 60¢ unless copy signal < 60s old
- Pause if daily drawdown > 8%
- Re-screen watchlist every 7 days
- **Ignore all Telegram/Twitter bot sales**

**Realistic fast-profit target:** Turn $1,000 → $1,100–$1,300 in **7 days** during World Cup if copy signals stay hot. **Not guaranteed.** Worst case: −15% to −30% on a bad sports weekend.

---

## Sources

- [Polymarket fees](https://docs.polymarket.com/trading/fees)
- [Maker rebates & liquidity rewards](https://docs.polymarket.com/market-makers/liquidity-rewards)
- [Akey et al. SSRN 6443103](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6443103) — maker/taker loss rates
- Becker 72.1M trade analysis (Kalshi, applies to Polymarket mechanics)
- [pm.wiki Polymarket-Kalshi arb](https://pm.wiki/learn/polymarket-kalshi-arbitrage)
- [insidepredictions.com arb math](https://insidepredictions.com/learn/prediction-market-arbitrage)
- [@distinct-baguette Polymarket profile](https://polymarket.com/@distinct-baguette) — scam warning
- [Debunking the Polymarket Dream](https://fglancszpigel.medium.com/debunking-the-polymarket-dream-d67ba3922e4b)
- Live API scans in `polymarket_research/data/`
