# Market Lab Options Trading Implementation Plan

Goal: add options trading capability to OzLabs Market Lab without jumping to live broker execution.

Core stance: aggressive research, conservative execution.

## Current system baseline

Market Lab currently runs as a dry-run daily research engine:

- Daily OHLCV via yfinance/cache.
- Factor overlay via yfinance_info where available, synthetic only as disclosed fallback.
- Deterministic strategy families: TSMOM, cross-sectional momentum, RSI pullback, MA baseline.
- Report output under `data/market-lab/reports/latest.md`.
- Cron job runs weekdays after close at 14:05 PDT and sends the report to Telegram.
- No live orders, no broker integration, no options/margin/shorting.
- Mock state was reset to a clean $100k baseline.

## Options trading scope

Implement options in staged gates. Do not skip gates.

### Gate 0 — Research/spec only

Deliverables:
- Define supported strategies.
- Define option contract model.
- Define option chain provider interface.
- Define paper options ledger schema.
- Define risk limits and kill switch.

Allowed strategies for first pass:
- Covered call candidate research.
- Cash-secured put candidate research.
- Protective put / collar research later.

Explicitly out of scope for now:
- Naked short calls.
- Margin.
- Multi-leg spreads beyond collar/protective structures.
- Intraday options scalping.
- Autonomously submitted live orders.

### Gate 1 — Options data ingestion

Create:
- `market_lab/options.py`
- `tests/market_lab/test_options.py`

Core models:
- `OptionContract`
- `OptionChainSnapshot`
- `OptionQuote`
- `OptionGreeks` if available, optional at first.

Provider pattern:
- Start with yfinance options chains because it is available now.
- Cache chain snapshots under `data/market-lab/options/chains/`.
- Every report must disclose source and timestamp.

Required tests:
- Parse call/put contract rows.
- Reject stale chains.
- Require bid/ask/mid handling.
- Gracefully degrade when greeks are missing.

### Gate 2 — Strategy screeners, no trading

Create deterministic options screeners:

1. Covered call screener
   - Requires existing or hypothetical 100-share lot.
   - DTE range: configurable, initial 14–45 days.
   - Delta proxy target: if greeks available, 0.15–0.35; otherwise use moneyness proxy.
   - Liquidity gates: minimum open interest, minimum volume, max bid/ask spread percentage.
   - Risk notes: assignment risk, capped upside, earnings/catalyst caution.

2. Cash-secured put screener
   - Requires enough cash to buy 100 shares at strike.
   - DTE range: configurable, initial 14–45 days.
   - Strike below spot by configurable buffer.
   - Liquidity gates same as above.
   - Risk notes: downside equivalent to owning shares less premium, assignment risk.

Required tests:
- Reject illiquid contracts.
- Reject contracts with missing bid/ask.
- Reject CSP if cash reserve is insufficient.
- Rank candidates by conservative metrics, not raw premium alone.

### Gate 3 — Paper options ledger

Create:
- `market_lab/options_broker.py`
- `data/market-lab/options/paper_options_ledger.jsonl`
- `data/market-lab/options/paper_options_positions.json`

Paper lifecycle:
- Open paper option position.
- Mark-to-market from latest chain mid price.
- Expiration handling.
- Assignment simulation for ITM short options.
- Cash reserve for CSPs.
- Share-reserve for covered calls.

Required tests:
- Opening covered call reserves shares.
- Opening CSP reserves cash.
- Expiration OTM releases reserve and records premium result.
- Expiration ITM simulates assignment correctly.
- No position can exceed configured limits.

### Gate 4 — Report integration

Update daily report with an options section:

- Covered call candidates.
- Cash-secured put candidates.
- Liquidity warnings.
- Assignment risk summary.
- Earnings/catalyst warning placeholder.
- Paper-only disclaimer.

Default cron remains report-only. No automatic options paper fills until Ronak approves.

### Gate 5 — Read-only broker integration

Only after paper engine is working:
- Add read-only broker account/positions query.
- Compare Market Lab paper assumptions against real holdings/options chains.
- No order submission code enabled.

### Gate 6 — Approval-required orders

Only after read-only broker state is stable:
- Generate proposed order ticket.
- Require explicit Ronak approval.
- Enforce hard caps:
  - Max premium at risk.
  - Max assignment notional.
  - Max contracts per symbol.
  - No naked calls.
  - No live trading outside market hours unless explicitly allowed.
- Full audit log.
- Kill switch.

## Initial risk configuration proposal

File: `market_lab/config.py`

Add `OptionsRiskConfig`:

- `allow_options=False` by default.
- `paper_options_enabled=False` by default until screeners are verified.
- `live_options_enabled=False` always false until later gate.
- `min_dte=14`
- `max_dte=45`
- `max_bid_ask_spread_pct=0.15`
- `min_open_interest=100`
- `min_volume=10`
- `max_contracts_per_symbol=1`
- `max_assignment_notional_pct=0.10`
- `max_total_options_assignment_pct=0.25`
- `allow_naked_calls=False`
- `allow_margin=False`

## First build slice

Implement Gate 1 + basic Gate 2 as the first slice:

1. Create options contract dataclasses and cache path helpers.
2. Add yfinance chain fetcher with cache fallback and source disclosure.
3. Add liquidity gate helper.
4. Add covered-call/cash-secured-put candidate dataclasses.
5. Add tests for parsing, liquidity rejection, and CSP cash reserve.
6. Add a report-only options candidate section.

Verification command:

```bash
pytest -q tests/market_lab
python -m compileall -q market_lab scripts/market_lab_daily.py
python scripts/market_lab_daily.py --network --require-live-data --max-orders 3
```

## Non-negotiables

- Options starts as research/paper only.
- No autonomous live options orders.
- No margin or naked short calls.
- No strategy claim without backtest/paper evidence.
- Liquidity and assignment risk are first-class, not footnotes.
