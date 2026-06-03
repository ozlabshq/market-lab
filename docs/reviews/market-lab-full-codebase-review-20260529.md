# Market Lab — Full Codebase Review (2026-05-29)

Reviewer: Claude Code (manual full-codebase review). Scope: all 17 modules in `market_lab/`
plus both runner scripts (`scripts/market_lab_daily.py`, `scripts/market_lab_review.py`).

> Note: this is a manual review, not the billed cloud `/code-review ultra`. The working tree was
> clean at review time (no diff against `main`), so the review covers the whole codebase rather
> than a change set.

## Test state

All **94 tests pass** via `uv run --extra dev pytest tests/market_lab`.

The README's `pip install -e '.[dev]'` does **not** work in this checkout: the local venv is
uv-managed (no `pip`), and the system `pip` is too old for PEP 660 editable installs of a
pyproject-only project. `uv run --extra dev pytest tests/market_lab` is the command that works
locally.

## What's genuinely well done

The safety posture is real, not cosmetic. Live-trading refusals are duplicated independently across
`broker.evaluate_order`, `options_paper.evaluate_option_paper_order`, and the screeners; the webapp
routes every write verb to HTTP 405; synthetic prices live in a separate cache dir so they can't
launder into the real cache; and the `(bars, source)` tuple threads provenance all the way to
`--require-live-data`. The equity portfolio gets `fcntl` locking + atomic temp-file-replace writes.
This is coherent defense-in-depth.

## Findings worth acting on

### 1. Options-paper persistence lacks the hardening the equity broker has
`options_paper.py:172` — `save_option_paper_portfolio` does a plain `path.write_text(...)`: no
atomic temp+`os.replace`, no `fcntl` lock — whereas `broker.save_portfolio` (`broker.py:106`) goes
through `_atomic_write_text` under `_portfolio_lock`. A crash mid-write corrupts
`paper_options_state.json`, and concurrent `daily` + `review` runs can race. This is the clearest
robustness inconsistency: the hardening deliberately applied to the cash ledger was not applied to
the options ledger. `evidence.py` already has reusable atomic helpers.

### 2. Screeners can each claim the full available capacity
`options_screeners.py:88-89` and `121-125` — both `screen_covered_calls` and
`screen_cash_secured_puts` size every qualifying contract against the *same* pool of available
shares / cash / assignment budget. If three strikes qualify, the report shows three candidates each
sized at full capacity, so aggregate suggested exposure overstates what's actually executable.
Order-time `evaluate_option_paper_order` gates per order, so this is not an execution bug, but the
*report* implies more capacity than exists. Either de-duplicate to one candidate per underlying or
annotate that candidates are mutually exclusive.

### 3. `_approx_delta` degenerate fallback feeds the delta gate
`options_data.py:76-86` — when IV/DTE/price are missing or non-positive, delta falls back to a crude
`moneyness - 0.5` heuristic rather than Black-Scholes. That value then flows into the
short-call/short-put delta gates (`max_abs_short_call_delta`, etc.) and into screener filters. A
contract could pass or fail a *risk* gate on a non-rigorous number. At minimum, contracts with
degenerate greeks should be tagged low-quality (mirroring the price-source discipline) so the gate
isn't trusting a placeholder.

### 4. `diagnose_trade` conflates "current mark" with "exit"
`diagnosis.py:125-130` — for still-open lots (the only ones `market_lab_review.py` diagnoses),
`exit_price` = last bar close and `pnl_pct` is computed as a realized return. It is actually
unrealized mark-to-market. `exit_date` stays `None` when `len==1`, which partly signals this, but
the field names will mislead anyone reading the evidence stream. A boolean like `is_open` /
`realized` would disambiguate.

## Minor / stylistic

- **Sharpe** uses population stdev (`pstdev`) and no risk-free rate, over equity curves that include
  warm-up/anchor points (`backtest.py:46`, `portfolio_construction.py:149`). Fine as a documented
  simplification, but it is an "edge-ish" metric reported without that caveat in the output.
- **Dead branch**: `broker.py:170-173` — both arms of the `allow_short` check reject the order.
  Safe, but the `if risk.allow_short` distinction does nothing.
- **Synthetic seed collisions**: `data._synthetic_prices` (and `factors.synthetic_factors`) seed an
  RNG on `sum(ord(c))` of the symbol, so anagrams / char-sum collisions get correlated series. Only
  matters in synthetic mode; acceptable.
- **README install drift**: `pip install -e '.[dev]'` does not work in this checkout (see Test
  state). Align the README / CLAUDE.md with the `uv` workflow.

## No issue found in the core execution discipline

The EOD→next-open execution discipline is correct. `run_signal_backtest`,
`moving_average_cross_backtest`, and the daily candidate queue/execute split all avoid lookahead
(signal computed on `bars[:i+1]`, fill at `i+1` open; warm-up bars do not carry positions into the
out-of-sample window).

## Suggested priority

1. Finding **#1** (atomic write + lock for options-paper persistence) — concrete robustness gap,
   in scope, low risk.
2. Finding **#3** (tag degenerate greeks) — protects the option risk gates from placeholder inputs.
3. Findings **#2** and **#4** — reporting/semantics clarity.
