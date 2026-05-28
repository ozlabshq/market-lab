# Market Lab Claude Opus Implementation Review

Generated: 2026-05-28

## Claude Opus Review

- subtype: success
- session_id: 0a360557-4d73-4b79-80f4-fd0b79233a4d
- num_turns: 1
- cost_usd: 0.34169974999999997

## Verdict

**Partial review.** I read `market_lab/{config,broker,backtest,signals,report}.py` and `scripts/market_lab_daily.py` in full. I did NOT read: `market_lab/{data,factors,indicators}.py`, any `tests/market_lab/*.py`, `docs/market-lab-system-options-roadmap.html`, `research/market-lab-options-trading-implementation-plan.md`, or `~/.hermes/scripts/market_lab_daily.sh`. I ran no tests. Findings below are limited to code I actually read; areas I couldn't read are flagged as unverified.

Overall posture is consistent with research-only: `RISK` defaults have `live_trading_enabled=False`, `allow_short=False`, `allow_options=False`, `allow_margin=False`, and `evaluate_order` rejects if `live_trading_enabled` is somehow flipped. But there are real correctness/safety gaps that should be closed before adding an options leg.

## Critical findings

1. **Same-bar execution risk in `_execute_due_candidates` (`scripts/market_lab_daily.py:54-73`).** The "fill only once a later bar exists" guard compares `latest_date > candidate.signal_date`, but the fill price is `bars[-1].open`. If `latest_date == signal_date` the candidate is correctly deferred, but as soon as a new bar arrives, the candidate fills at *today's* open — which is fine only if the candidate was generated strictly after yesterday's close. Nothing enforces that ordering: a candidate created mid-session today with `signal_date = today` would, on tomorrow's run, fill at tomorrow's open, which is actually correct. The real risk is `--queue-order-candidates` and `--execute-pending-candidates` running in the *same* invocation: a candidate queued now with `signal_date = today` will not execute this run (good), but `today` is derived from `bars[-1].date`, and `latest_date > candidate.signal_date` is a strict `>`. So same-run double-action is blocked. Acceptable, but the invariant is implicit; a single comment plus an assertion in `_execute_due_candidates` that `candidate.signal_date < latest_date` (already present as a guard) should be paired with a refusal to queue and execute in one process, or at minimum execute first and queue second is the wrong order — currently the script does execute (line 116) then queue (line 121), which is correct. Worth a comment lock-in.

2. **Production state path is hard-coded and shared by tests.** `STATE_PATH`, `LEDGER_PATH`, `PENDING_CANDIDATES_PATH` in `config.py:11-13` are module-level constants resolved from the repo root. Every broker function defaults its `path=` arg to these. Any test that calls `place_mock_order`, `append_ledger`, `save_portfolio`, `load_portfolio`, `append_order_candidates`, `save_order_candidates`, or `load_order_candidates` *without explicitly passing a tmp path* will read/write the real `data/market-lab/` files. The recent quarantine fix addressed one offender, but the API still makes pollution the default. I could not verify the tests since I didn't read them, but the surface area is dangerous. **The defaults should not point at production paths in any test-importable code path** — either drop the defaults and force callers to pass paths, or use an env-var-overridable base dir that pytest fixtures auto-redirect via a session-scoped `tmp_path`-based monkeypatch.

3. **`load_portfolio` silently resets to a fresh $100k portfolio on any parse error (`broker.py:62-67`).** A truncated/corrupt `mock_portfolio_state.json` returns `Portfolio()` with `cash=RISK.starting_cash` and no positions. That silently erases the ledger reality. For research it's tolerable, but for an options ledger this is a footgun: a partial write during a crash would zero positions and hand you fresh cash. Should fail loudly (raise) or load from the last ledger snapshot.

4. **`save_portfolio` is not atomic (`broker.py:69-72`).** `path.write_text(...)` is a non-atomic write. A crash or concurrent run mid-write produces the same corrupt-JSON state that #3 then "recovers" by zeroing. Use a `tempfile + os.replace` write-then-rename. Same applies to `save_order_candidates` (`broker.py:99-106`) and `save_report` (`report.py:130-137`).

5. **No concurrency guard on the portfolio/ledger.** Nothing prevents two daily runs (cron + manual, or Hermes shell wrapper retry) from racing on `STATE_PATH` and `LEDGER_PATH`. Append-only ledger races are mostly tolerable; the portfolio JSON race is not. A simple `fcntl.flock` on a sidecar lockfile around the read-modify-write in `place_mock_order` would close this. Without it, options accounting will compound the risk because each leg mutates more state.

## Important findings

6. **`evaluate_order` does read-modify-write on the live portfolio without checking ledger-vs-state consistency.** If the JSONL ledger and `mock_portfolio_state.json` diverge (after a crash, manual edit, or test pollution), there's no reconcile step. Recommend a `reconcile_from_ledger()` helper plus a periodic invariant check (cash + sum(positions*close) ≈ ledger-derived equity within tolerance).

7. **Sell-side risk gates are weaker than buy-side (`broker.py:111-153`).** SELL bypasses `max_position_pct` and `projected_position_value` checks (only BUY enforces). That's defensible for reducing risk, but the `max_single_order_pct` check uses `gross = quantity * price` for both, then the SELL branch doesn't re-check after slippage. Minor but inconsistent.

8. **`apply_factor_overlay` mutation rule asymmetry (`signals.py:193-221`).** Comment says "fundamentals/narrative can nudge confidence, but they do not turn a SELL into a BUY". The code only demotes BUY→HOLD and SELL→HOLD; it doesn't promote, which matches the doc. Good. But `evidence` is updated even when `factor` is None elsewhere — fine, but if a non-None factor has all None metrics, the report renders `n/a` correctly. No bug, just verify the test covers it.

9. **`max(bars[-1].date.isoformat() for bars in bars_by_symbol.values() if bars)` (`scripts/market_lab_daily.py:122`)** uses the *latest* bar across the universe as "today" for `signal_date`. If one symbol has a stale cache and another is fresh, the candidate's `signal_date` skews to the fresh symbol's date, which can let the stale-symbol candidate execute one bar earlier than intended. Pin `signal_date` per-symbol (use `bars_by_symbol[candidate.symbol][-1].date.isoformat()`).

10. **Backtest benchmark base bug edge case (`backtest.py:43`).** The chained ternary `bars[benchmark_start_index].close if ... else bars[0].close if bars else 1.0` is hard to read and the `benchmark_start_index < len(bars)` check uses `<` while the lookup is `bars[benchmark_start_index].close`. OK, but `min_history` is passed directly as `benchmark_start_index` from `run_signal_backtest` (line 85); if `len(bars) == min_history + 2` exactly, this is fine. Worth a small unit test at the boundary.

11. **No lookahead bias in `run_signal_backtest`** — decisions use `bars[: i + 1]` and fills happen at `bars[i].open` of the *next* loop iteration via `pending`. That looks correct.

12. **`moving_average_cross_backtest` benchmark base uses `bars[slow].close`, which matches `min_history=slow`. Correct.**

13. **Report claims (`report.py:39-44`) "Mock fills use next available open through explicit candidate ledger".** True for the candidate path, but `place_mock_order` (`broker.py:155-161`) is exported and can be called with any price by anything that imports it. If something in the daily script ever called it with `bars[-1].close`, you'd silently get a same-close fill. Recommend: rename to `_place_mock_order_internal` or have it refuse fills priced at a close known to the system (i.e., require a flag like `at_open=True`).

## Minor findings

14. `Position` is mutable while `OrderDecision`/`OrderCandidate` are frozen — fine, but inconsistent style.
15. `STATE_PATH` is checked via `path.exists()` then read without lock — TOCTOU, low risk in single-runner.
16. `_candidate_from_signal` floors `target_notional // sig.close` to int; for high-priced names ($500+) `max(1, ...)` can still emit 1-share candidates that fail `min_trade_notional` on the next line — already guarded, fine.
17. `_dedupe_candidates` keys by `(symbol, signal_date, strategy, side)` — strategy collisions across a re-run produce one candidate (correct), but a re-run with a different `args.max_orders` can still drop previously queued candidates if they're not re-emitted. The `load_order_candidates() + queued_candidates` merge preserves them, so OK; verify by test.
18. `_source_is_synthetic` substring match also matches `non-synthetic`, `synthetic-corrected`, etc. Make it equality or a known set.
19. `confidence` and `target_weight` are clamped at multiple call sites with `_clamp`; one place uses `+ 0.35` after a mean — confidence can therefore exceed `1.0` before clamp. Clamp does its job, but the constant additions are arbitrary and undocumented.

## Options implementation gate recommendations

Do not add options until the following are in place:

A. **Atomic + locked portfolio state** (fixes #3, #4, #5). Options ledgers have leg-level commit semantics and partial-fill scenarios that are far harder to recover from than equities.

B. **Test isolation by construction**, not by discipline (fixes #2). Convert `STATE_PATH`/`LEDGER_PATH`/`PENDING_CANDIDATES_PATH` into a `Paths` object injected via a `Context` and resolved from an env var (`OZLABS_MARKET_LAB_DATA_DIR`). Pytest sets the env var to a tmp dir at session start. No test should be able to write to `data/market-lab/` even if it tries.

C. **Margin/buying-power accounting before options.** Cash-secured puts require segregated cash; covered calls require share lock. The current `Portfolio` has no concept of "encumbered" cash or "locked" shares. Add `cash_reserved`, `shares_encumbered_by_short_call`, and net these out of buying-power calculations. Equity computation must subtract option liabilities at mark.

D. **Greeks + mark sourcing must be explicit and dated.** Decide up front: do you mark options at bid/mid/ask? Stale-mark policy when the chain is N minutes old? Refuse to fill when IV missing? Without this, P&L on the paper options ledger will drift and you'll trust numbers you shouldn't.

E. **No "options enabled" flag flip without a guard.** `allow_options=False` is just a default; add a runtime check in any options entrypoint that refuses if `live_trading_enabled is True OR allow_options is False` AND require an explicit `paper_options=True`. Three-flag gate, not one.

F. **Assignment/expiration is a scheduled event, not an order.** The daily script's "next-open candidate" model doesn't cover Friday-PM assignment, early assignment on dividends, or pin risk. The options ledger needs its own clock with `expiry_date` events that mutate the portfolio independently of any signal. Spec this before writing the screener.

G. **Chain-ingestion data quality gate.** Define what makes a chain row usable: bid > 0, ask > 0, ask/bid spread < X%, open interest > Y, last trade < Z minutes old. Reject chains failing the gate at ingestion. Otherwise the CSP/covered-call screener will recommend illiquid garbage.

H. **Realized vs. unrealized vol mismatch.** TSMOM uses `rolling_volatility(closes, 20)`. Options screeners need *implied* vol from the chain plus a historical-vol estimator. Don't reuse the equity `rolling_volatility` as a stand-in for IV.

I. **Position-sizing units change.** A short put commits `strike * 100 * contracts` of buying power, not `quantity * price`. The existing `max_position_pct` / `max_trade_notional` constants must be re-derived per-leg and per-contract; do not reuse without translating units.

J. **Read-only broker stage means read-only.** No `place_*` analogue should exist for the broker leg. The "approval-required tickets" stage should produce human-readable tickets that a human pastes elsewhere, not a callable function.

## Tests/commands run

None. I did not run pytest, ruff, the daily script, or the Hermes wrapper this turn. The system-reminder asked me to stop using tools and return the review based on what I had already read. Anything I claim about behavior is from static reading of the five files listed under Verdict.

## Suggested next patch list

1. `market_lab/config.py`: switch `STATE_PATH`/`LEDGER_PATH`/`PENDING_CANDIDATES_PATH` to read from `os.environ.get("OZLABS_MARKET_LAB_DATA_DIR", DEFAULT)`. Add a `tests/conftest.py` that sets it to a tmp dir per session and asserts in a pytest fixture that no test ever touches the real path.
2. `market_lab/broker.py`: make `save_portfolio` and `save_order_candidates` atomic (write to `path + ".tmp"`, `os.replace`). Add `fcntl.flock` (or `portalocker`) on a sidecar `STATE_PATH.with_suffix(".lock")` around the read-modify-write in `place_mock_order`.
3. `market_lab/broker.py`: change `load_portfolio` to raise on parse error instead of silently returning a fresh $100k portfolio. Add a separate `bootstrap_portfolio()` for the "no file yet" path.
4. `market_lab/broker.py`: rename `place_mock_order` → `_place_mock_order_internal` and have the public entry require a `next_open: True` kwarg, so any future caller has to acknowledge it's not a same-close fill.
5. `scripts/market_lab_daily.py`: pin `signal_date` per-symbol (`bars_by_symbol[sig.symbol][-1].date.isoformat()`) instead of using the universe-max date.
6. `market_lab/broker.py`: add a `reconcile_from_ledger(state_path, ledger_path)` and call it on startup of `market_lab_daily.py` to detect divergence before any new candidate is queued or executed.
7. Add a test (`tests/market_lab/test_state_isolation.py`) that imports broker and asserts `STATE_PATH` resolves under the test tmp dir; fail-by-construction if env var is not set.
8. `_source_is_synthetic`: replace substring match with `source.strip().lower() in {"synthetic", "synthetic-fallback"}` or whatever the closed set actually is.
9. Document (and unit-test) that `--execute-pending-candidates` must run before `--queue-order-candidates` within a single invocation, or refuse to run both flags together.
10. Before any options PR: add a `BuyingPower` dataclass (`cash`, `cash_reserved`, `shares_encumbered`) and migrate `evaluate_order` to consume buying power, not raw `portfolio.cash`. This is the substrate the options ledger needs.


---

## Claude Opus Addendum

- subtype: success
- session_id: 0a360557-4d73-4b79-80f4-fd0b79233a4d
- num_turns: 1
- cost_usd: 0.23873225

# Addendum (partial)

**Coverage this turn:** `market_lab/data.py`, `market_lab/factors.py`, `market_lab/indicators.py`, `tests/market_lab/test_broker.py`, `tests/market_lab/test_daily_script_safety.py`, `tests/market_lab/test_factors.py`. **NOT read this turn:** `tests/market_lab/test_hardening.py`, `test_indicators.py`, `test_research_strategies.py`, `test_signals_backtest.py`, `docs/market-lab-system-options-roadmap.html`, `research/market-lab-options-trading-implementation-plan.md`, `~/.hermes/scripts/market_lab_daily.sh`. No pytest run.

## Additional Critical findings

**C1. `test_factor_cache_roundtrip` mutates `market_lab.factors.FACTOR_DIR` module-level state — but `save_factors` calls `factor_path(...)` which dereferences `FACTOR_DIR` directly, so the monkeypatch works. However it then calls `ensure_dirs()` (`factors.py:102`), and `ensure_dirs()` re-imports paths from `config.py` and creates `DATA_DIR`, `PRICE_DIR`, `REPORT_DIR`, `FACTOR_DIR` **as defined in `config.py`** — i.e. it creates the *real* production directories on every test run, even though the test redirects `factors.FACTOR_DIR`. That's a real, observable side effect: every factors test invocation `mkdir -p`'s `/Users/ozlabs/OzLabs/data/market-lab/...`. Worse, the test's monkeypatch only swaps the binding inside `factors`; if any code path inside `factors` calls `FACTOR_DIR` indirectly (it doesn't today, but it's brittle), the test silently writes to prod. Confirms previous Critical #2: defaults are unsafe; `ensure_dirs()` should respect the override.

**C2. Network leak in `fetch_prices` and `fetch_factors` defaults.** `fetch_prices` defaults `prefer_network=True` (`data.py:82`); `fetch_factors` defaults `prefer_network=False` (`factors.py:162`), good. But the **`fetch_prices` default of True** means any test that imports `data` and calls `fetch_prices` without passing `prefer_network=False` will hit yfinance. The current test suite (from what I read) does not appear to call `fetch_prices` directly, but the daily script does call it from CI/cron with whatever `--network` resolves to — and the default in `argparse` is `action="store_true"` so CLI-default is False, fine. The pytest risk is "future test that touches data.py grabs the network and pollutes the prices cache under `data/market-lab/prices/`." Flip the library default to `prefer_network=False` and have the CLI explicitly pass `True` when `--network` is set.

**C3. `save_prices` overwrites the cache file every call (`data.py:50-59`).** When `fetch_prices` falls back to synthetic on network failure, it writes a *synthetic* CSV to the same `PRICE_DIR/<SYMBOL>.csv` path that real yfinance data lives at. The source string is returned, but the CSV on disk has **no source column** — once written, you cannot tell from disk whether the cache is real or synthetic. A subsequent `prefer_network=False` run (or a failed network call) will then read the synthetic CSV from cache and return `source="cache"` — laundering synthetic data into the "cache" source label. The `_source_is_synthetic` substring check (already weak) will not catch this. **This is a real research-integrity bug**: a single failed network run can poison the cache permanently. Fix: write synthetic data to a separate `PRICE_DIR/synthetic/` subdir, or add a `source` column to the CSV, or never persist synthetic to the same path as real data.

**C4. Same cache-poisoning risk in `factors`.** `save_factors` writes synthetic snapshots to the same path as yfinance ones (`factors.py:101-108`), but at least factors include a `source` column (`source: synthetic`) and `fetch_factors` translates cached synthetic to `"cache_synthetic"` (`factors.py:166`). The fix is wired through. **`data.py` does not have this discipline** — that's the actual gap.

## Additional Important findings

**I1. `_synthetic_prices` clock dependency (`data.py:61-80`).** `end = end or date.today()` means synthetic prices generated today differ from synthetic prices generated tomorrow even for the same symbol and `days`. Tests that depend on synthetic data are not reproducible across days unless they pin `end=`. The factors test correctly pins `as_of=date(2026, 1, 1)`; the prices code has no equivalent in any test I read. If `test_research_strategies.py` or `test_hardening.py` (not yet read) generates prices without pinning `end`, those tests are flaky on the date boundary.

**I2. `_synthetic_prices` `high`/`low` invariant.** `high = max(prev, price) * (1 + abs(...))` and `low = min(prev, price) * (1 - abs(...))`. That guarantees `low <= min(prev, price) <= max(prev, price) <= high`, so `open` (=prev) and `close` (=price) sit inside `[low, high]`. Correct. No bug, just calling out it survives scrutiny.

**I3. `fetch_prices` cache-age check (`data.py:106-110`).** `newest >= date.today() - timedelta(days=max_cache_age_days)` (default 3) is sane on a weekday but bites on long weekends/holidays — a Tuesday-after-three-day-weekend run with last cache from previous Friday is 4 days old, fails the freshness check, falls through to synthetic, **and poisons the cache (C3)**. Should use trading-day distance or extend default to ~5.

**I4. `yfinance` exception swallow is too broad (`data.py:104`, `factors.py:158`).** `except Exception: pass` masks rate-limit, auth, schema, and import errors — all of which silently fall through to synthetic data with no log. Combined with C3, a single yfinance schema break silently rewrites every symbol's cache with synthetic data on the next run. Recommend logging the exception and refusing to overwrite an existing real cache when yfinance fails.

**I5. `_yfinance_factors` "AI mentions" heuristic.** `" ai "` with surrounding spaces won't match "AI." or "AI," or "AI-" — fine, deterministic, no bug. But `info.get("trailingPE") or info.get("forwardPE")` will fall back to forward P/E if trailing is `0` or `None`, which is acceptable, just worth a comment that forward P/E is analyst-estimate and shouldn't drive factor scores symmetrically with trailing.

**I6. `rsi` returns `100.0` when `avg_loss == 0` (`indicators.py:37, 43`).** Standard convention. Fine, but combined with `generate_signal`'s `elif r14 > 78: score -= 0.35`, a long streak of green bars will hit RSI=100 and force a hard SELL signal contribution. That's the intended behavior of RSI but worth noting that ties between "uptrend" reasons (+0.45) and "overheated" (-0.35) net to +0.10, which can keep symbols in HOLD on strong rallies. Behavioral, not a bug.

**I7. `ema` returns the running EMA value but emits `None` until window is filled (`indicators.py:13-21`).** The `current` variable accumulates from the *first* value, so the EMA at position `window-1` is not the textbook SMA-of-first-N seed — it's an exponentially-weighted average starting from the first observation. For long series this converges; for short series the first emitted EMA value differs from the standard "seed with SMA(N), then EMA" formula. Not a bug, but if any caller compares EMAs to a textbook reference they'll see a small offset.

**I8. `rolling_volatility` uses `pstdev` (`indicators.py:51`), i.e. population stdev with N in the denominator.** Sample stdev (N-1) is the more common convention for return-vol. Difference is small at window=20 (~2.5%), but it's a hidden inconsistency vs. typical literature numbers used in the strategy comments.

**I9. `max_drawdown` peak init at `-inf` (`indicators.py:55`).** Correct. But the `if peak > 0` guard means a leading negative or zero equity sequence is skipped, and once a positive peak is set, a subsequent equity dip below zero returns `v/peak - 1` which can be < -1 (e.g., equity=-10, peak=100 → -1.1). The function can therefore return values < -1, which is non-standard. For the current backtest (long-only, can't go negative), unreachable. Worth a clamp.

**I10. Tests rely on global `RISK`/`config` defaults.** `test_buy_rejected_when_position_limit_exceeded` builds 1000 × $100 = $100,000 = 100% of cash and expects rejection via "max order" — relies on `max_single_order_pct=0.05` and `max_trade_notional=5_000`. Both defaults. If `RiskConfig` defaults change, these tests change meaning silently. Pass an explicit `risk=` like the short tests do.

**I11. `test_factor_cache_roundtrip` does not reset `factors.FACTOR_DIR` on test failure before `finally:` if `synthetic_factors` raises — actually it does, the `try/finally` is structured correctly. OK.**

**I12. `test_short_open_still_rejected_in_mvp_even_with_flag`** confirms that `allow_short=True` does NOT actually open short positions — the flag's only effect when the user has no shares is to swap the reject message. Worth a doc string clarifying that `allow_short` is currently a "messaging" flag, not a functional one. Easy footgun before adding options where flag semantics will multiply.

**I13. `_float_or_none` accepts `value in (None, "", "None", "nan")` — but `"NaN"`, `"NULL"`, `"null"`, `float('nan')` (which is `!= "nan"` and also `!= itself`) slip through. `float('nan')` will be returned as-is via the `float(value)` path. Downstream factor_score does `snapshot.pe_ratio < 18` — NaN comparisons always return False, so NaN P/E silently skips both branches. Not crashy, but it'd be invisible if yfinance ever returned NaN. Add `math.isnan` check.

## Revisions to previous findings

- **Previous Critical #2 (test pollution by default paths): CONFIRMED and STRENGTHENED.** The factors test demonstrates that `ensure_dirs()` *unconditionally* creates the real production directory tree on every invocation, regardless of any local monkeypatch. The defaults aren't just risky — they're guaranteed to touch the real filesystem on import-and-call.
- **Previous Important #18 (`_source_is_synthetic` substring match): REVISED to Critical-adjacent.** Combined with C3, synthetic data laundering into `source="cache"` means `_source_is_synthetic` will return False on poisoned caches — so `--require-live-data` will not catch the failure mode it was added to catch.
- **Previous Critical #3 (silent reset to fresh $100k on parse error): UNCHANGED.**
- **Previous Important #6 (no reconcile): UNCHANGED.**
- **Previous Important #9 (universe-max signal_date): UNCHANGED.**

## Tests/commands run

None this turn. The system-reminder asked me to stop using tools and return the addendum.

## Net recommendation update

The cache-poisoning path (C3) is the most important new finding. Before any options work — and arguably before the next daily-cron run — `data.py` should either (a) refuse to write synthetic data to the real price-cache path, or (b) add a `source` column to the price CSV so cached-synthetic can be detected on read. Right now a single yfinance failure rewrites the entire universe with synthetic prices that subsequently report as `source="cache"`, and the `--require-live-data` guard cannot see it.


## Ozzy verification

Ran `python3 -m pytest tests/market_lab -q`: 31 passed in 0.36s.
