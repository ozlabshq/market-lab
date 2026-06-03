# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Posture: research-only, safety-gated

This is a research/paper-trading lab, **not** a live trading system. There is no broker
execution, no autonomous orders, no margin, and no shorting. Several independent gates enforce
this, and they are deliberately redundant — do not weaken or remove them:

- `broker.evaluate_order` refuses every order if `RiskConfig.live_trading_enabled` is true.
- `options_paper.evaluate_option_paper_order` refuses if `live_options_enabled` is true, and
  always blocks naked calls (`allow_naked_calls` rejects even when set).
- `webapp.py` exposes only `GET /` and `GET /api/snapshot`; all write verbs (POST/PUT/PATCH/
  DELETE) return HTTP 405 `read_only_dashboard`.

Before adding any options trading capability, read and close the gaps in
`research/market-lab-claude-opus-implementation-review-20260528.md`.

## Commands

```bash
python3 -m pip install -e '.[dev]'        # install (Python >=3.11; only runtime dep is yfinance)
python3 -m pytest tests/market_lab -q      # full test suite (CI runs exactly this)
python3 -m pytest tests/market_lab/test_broker.py -q          # single file
python3 -m pytest tests/market_lab -q -k "synthetic or gate"  # by keyword

python3 scripts/market_lab_daily.py        # generate a daily research report (offline by default)
python3 scripts/market_lab_review.py       # post-trade diagnosis + strategy health (evidence council)
python3 scripts/market_lab_webapp.py --host 127.0.0.1 --port 8766   # read-only dashboard
```

There is no linter configured. Tests are the only gate.

## Data flow and the synthetic-source discipline

`data.fetch_prices` is a three-tier fallback: **yfinance (network) → on-disk cache → deterministic
synthetic generator**. Network is opt-in — scripts only attempt it with `--network`; otherwise
they run fully offline so tests and reports are reproducible.

Critically, **synthetic prices are cached in a separate directory** (`SYNTHETIC_PRICE_DIR`, not
`PRICE_DIR`) so synthetic data can never "launder" itself into the real price cache. Every fetch
returns a `(bars, source)` tuple, and the `source` string ("yfinance" / "cache" / "synthetic" /
"cache_synthetic") is propagated through reports. The daily script's `--require-live-data` flag
aborts candidate execution/queueing if any symbol fell back to synthetic. When touching the data
layer, preserve this source tracking — it is the integrity backbone, not incidental metadata.

## Module map (`market_lab/`)

- **config.py** — single source of truth for all paths and risk parameters. `RiskConfig` (equity)
  and `OptionsRiskConfig` (options) are frozen dataclasses with the safety flags above. Data
  location is overridable via the `MARKET_LAB_DATA_DIR` env var.
- **data.py** — `Bar` dataclass, CSV price I/O, the three-tier fetch.
- **indicators.py** — pure functions (sma, ema, rsi, volatility, max_drawdown). No I/O.
- **factors.py** — non-price fundamental/narrative factors (`FactorSnapshot`, `factor_score`).
- **signals.py** — strategy signals (`generate_tsmom_signal`, `generate_rsi_pullback_signal`,
  legacy `generate_signal`), the `generate_ensemble_signal` that blends them, cross-sectional
  momentum ranking, and `apply_factor_overlay`. **Execution discipline:** signals are computed at
  the close of day *t*; fills happen at the *next* bar's open. The factor overlay is intentionally
  capped — fundamentals nudge confidence but cannot flip a SELL into a BUY.
- **backtest.py** — long-only backtests with next-bar-open fills + slippage/commission. Supports an
  `evaluation_start_index` so early bars act as warm-up context excluded from reported metrics.
- **optimization.py** — parameter sweeps and walk-forward (train/OOS) wrappers over backtest fns.
- **portfolio_construction.py** — momentum target weighting / dual-momentum rotation.
- **broker.py** — mock equity broker. Risk gates in `evaluate_order`; atomic state writes via temp
  file + `os.replace` under an `fcntl` portfolio lock. Order-candidate queue (`OrderCandidate`)
  models the close→next-open delay: candidates are queued at signal close and filled only once a
  later bar exists.
- **options_data.py** — option `OptionContract`/chain snapshots, greeks, DTE; yfinance-backed with
  graceful absence if the dep is missing.
- **options_screeners.py** — covered-call and cash-secured-put candidate screens.
- **options_paper.py** — paper options portfolio. Defined-risk only: long options cap loss at
  premium; short calls require owned shares (reserved); short puts reserve cash collateral. Many
  gates (DTE, spread, OI/volume, delta, per-symbol count, assignment %).
- **diagnosis.py** / **evidence.py** — the "evidence council": post-trade `TradeDiagnosis`,
  strategy health reports, and append-only JSONL evidence streams (fsynced, atomic batch append).
- **report.py** — renders the daily markdown report; `webapp.py` — read-only HTML dashboard +
  `/api/snapshot`, building only from local artifacts.

## Daily script orchestration

`scripts/market_lab_daily.py` is the main pipeline: for each symbol it fetches prices + factors,
builds ensemble/family signals with the factor overlay, runs backtests, then optionally queues or
executes order candidates and screens paper options. Key flags: `--network`,
`--queue-order-candidates`, `--execute-pending-candidates`, `--require-live-data`,
`--fetch-options`. The candidate queue/execute split is what enforces close→next-open timing in
the daily loop (`_execute_due_candidates` fills only when `latest_date > candidate.signal_date`).

## Conventions

- Code is terse: dataclasses (mostly `frozen=True`), `from __future__ import annotations`, compact
  multi-statement lines in older modules. Match the surrounding density rather than reformatting.
- Generated state is **not** committed: `data/market-lab/prices/`, `factors/`, `reports/`,
  `mock_ledger.jsonl`, `mock_portfolio_state.json`, `pending_order_candidates.jsonl`, option
  chains/ledgers. Keep these gitignored.
- Use a branch + PR for every non-trivial change (`gh pr create --fill`); CI runs the test suite on
  PRs and pushes to `main`.
