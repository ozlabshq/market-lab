# Tradier Sandbox Integration — Research & Spec

**Status:** Pre-implementation specification
**Date:** 2026-05-29
**Author:** Ozzy (ozzy-research)
**Context:** Based on provider recommendation from t_13095612 (Tradier vs. IBKR vs. Alpaca vs. Polygon vs. ThetaData vs. ORATS comparison)
**Posture:** research/mock/paper only — live orders disabled by design

---

## Why Tradier Sandbox First

Six providers were evaluated (Tradier, IBKR, Alpaca, Polygon.io, ThetaData, ORATS). Tradier Sandbox wins for Phase 1 for three structural reasons:

**1. Data + Paper + Live in one API.** Tradier is the only provider where a single REST integration replaces yfinance option chains AND provides paper order execution AND graduates to live trading without a rewrite. Polygon/ThetaData/ORATS are data-only (no trading path). IBKR has both but requires a local Java gateway process. Alpaca has both but options support is newer and less mature.

**2. Free sandbox, zero recurring cost.** The sandbox account costs nothing. No monthly subscription, no data plan, no contract commitment. You can iterate, test, and validate without spending a dollar. Polygon's cheapest options tier is $79/mo. ORATS is $199+/mo. Tradier is free until you need live.

**3. Simple REST auth.** Single OAuth2 Bearer token — one HTTP header. Same auth pattern as the existing codebase. No TWS Gateway, no separate SDK, no WebSocket setup for basic use. Integration effort is 1-2 days.

### What Tradier Doesn't Do

- **Not a data firehose.** No tick-level historical data. For research backtesting, yfinance's daily/historical data remains the primary source. Tradier fills the *forward-looking* data gap: current chains with real bid/ask, IV, Greeks, OI, and volume.
- **Limited to US equities/options.** No futures, forex, or international markets. IBKR covers those if you need them later.
- **Sandbox data is simulated.** Prices in the sandbox are close to real but not guaranteed identical to live execution. Treat sandbox fills as indicative, not binding.

---

## Safety Gates (Preserved Research-Only Posture)

Market Lab already has a deliberately redundant safety architecture. The Tradier adapter plugs into it without weakening any gate:

### Current Gates

| Gate | Module | What it does | File |
|------|--------|-------------|------|
| `RiskConfig.live_trading_enabled` | `config.py` | `evaluate_order` refuses ALL orders if True | broker.py:163 |
| `OptionsRiskConfig.live_options_enabled` | `config.py` | `evaluate_option_paper_order` refuses if True AND disables screeners | options_paper.py:80, options_screeners.py:66 |
| `allow_naked_calls` | `config.py` | Always False; blocks uncovered short calls even when set | options_paper.py:113-114 |
| Webapp write verbs | `webapp.py` | POST/PUT/PATCH/DELETE return HTTP 405 | CLAUDE.md |
| `--require-live-data` | `daily.py` | Aborts execution if any symbol fell back to synthetic | daily script |

### New Tradier-Specific Gates

The Tradier adapter adds its own layer of gates — separate from the core RiskConfig — so the Tradier module can't be misconfigured independently:

```
TRADIER_LIVE_TRADING_DISABLED (env)  — default: "1" (disabled). Must be explicitly set to "0" for live.
                                       Docstring: "Kill switch for Tradier trading. Affects paper AND live.
                                       Market Lab never sets this to 0."
```

This is an **independent gate** — even if someone flips `RiskConfig.live_trading_enabled = True` by mistake, the Tradier adapter still refuses to send orders to the production URL because `TRADIER_LIVE_TRADING_DISABLED` is checked at the adapter level, not the risk config level.

### Adapter-Side Guard

The `TradierProvider` class will never construct a production base URL unless both conditions are met:
1. `market_lab.config.RiskConfig.live_trading_enabled` is True
2. `TRADIER_LIVE_TRADING_DISABLED` env var is NOT "1"

With default settings (both gates at their defaults), the base URL is always the sandbox URL `https://sandbox.tradier.com/v1`. This is runtime-checked — not just documented.

---

## Environment Variables

New env vars for Tradier config, added to `market_lab/config.py`:

```python
# --- Tradier Config ---
TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN")           # API bearer token — required
TRADIER_ACCOUNT_ID = os.environ.get("TRADIER_ACCOUNT_ID")  # Sandbox account number — required
TRADIER_API_BASE = "https://sandbox.tradier.com/v1"  # Default sandbox — constant, not env-overridable in Market Lab
TRADIER_LIVE_TRADING_DISABLED = os.environ.get("TRADIER_LIVE_TRADING_DISABLED", "1")
```

**Why token and account ID are separate:** Tradier's REST API needs both. The sandbox assigns an account number (e.g. `6US...`) on registration — it's not the same as the token. Both are required.

**Where they live locally:** Create `tradier.env` in the repo root (gitignored) matching the `.alpaca.env` pattern:

```
# tradier.env (gitignored)
ozlabshq@gmail.com
<sandbox_token_here>
<account_id_here>
```

### Environment Variable Matrix

| Var | Required | Where used | Source |
|-----|----------|-----------|--------|
| `TRADIER_TOKEN` | Yes | TradierProvider HTTP header | Tradier developer dashboard |
| `TRADIER_ACCOUNT_ID` | Yes | Order submission endpoint path | Tradier sandbox account page |
| `TRADIER_LIVE_TRADING_DISABLED` | No (default "1") | Adapter-level gate | Set once in .env, never changed |

---

## Data-Source Fallback Design

Market Lab's data layer currently has a three-tier fallback for equity prices (from CLAUDE.md):

```
yfinance (network) → on-disk cache → deterministic synthetic generator
```

Tradier adds a parallel path for **option chain data only** — it does not replace the equity price pipeline.

### Option Chain Flow (current)

```
fetch_option_chain_snapshot()
  └─ yfinance.Ticker(symbol).option_chain(expiration)  → OptionChainSnapshot
  └─ save/load via JSON (cached to OPTIONS_CHAIN_DIR)
```

### Option Chain Flow (with Tradier)

```
fetch_option_chain_snapshot(symbol, source="tradier")  
  ├─ source="tradier":  TradierProvider.fetch_chain(symbol, expiration)
  │                       └─ requests.get(TRADIER_API_BASE + "/markets/options/chains")
  │                       └─ Parse into OptionChainSnapshot
  ├─ source="yfinance":  Current yfinance path (unchanged)
  ├─ source=None:        Check TRADIER_TOKEN → Tradier → yfinance → cached → error
  └─ Cache to JSON (same OPTIONS_CHAIN_DIR, tagged with .source in metadata)
```

The **source selection** follows this priority when `source=None` (automatically chosen):

```
1. If TRADIER_TOKEN is set and requests module available → Tradier
2. If yfinance available → yfinance
3. If cached snapshot exists → load from cache
4. Raise RuntimeError("no option source available")
```

This is exposed as `config.OPTIONS_SOURCE` (string: "auto" | "tradier" | "yfinance"). Default: "auto" which runs the priority chain above.

### Cache Isolation

Tradier-sourced chains are cached to the SAME `OPTIONS_CHAIN_DIR` as yfinance chains, but the `source` field in `OptionChainSnapshot` metadata distinguishes them. The dashboard and reports distinguish `source: "tradier"` vs `source: "yfinance"` vs `source: "fixture"` vs `source: "cache"`. No cross-contamination: a Tradier-sourced cached chain loaded later reports `source: "tradier"`.

### When Network Is Not Available

The daily script's `--network` flag pattern already exists for equity prices. Tradier respects the same flag:
- `--network` flag OFF → use cached chains only (Tradier API not called)
- `--network` flag ON → fetch fresh chains from Tradier (or yfinance if Tradier unavailable)

This keeps the offline-first / reproducible-report posture.

---

## Paper-Only Adapter Boundaries

The Tradier integration introduces a `TradierProvider` class **and** a `TradierPaperBroker` adapter. These are deliberately separate from the core `options_paper.py` module.

### Module Architecture

```
market_lab/
  ├─ tradier_provider.py      NEW — Tradier REST API wrapper (data + orders)
  ├─ options_data.py          MODIFIED — add source routing to fetch_option_chain_snapshot
  ├─ config.py                MODIFIED — add TRADIER_ env vars, OPTIONS_SOURCE
  ├─ options_paper.py         UNCHANGED — pure-simulation paper portfolio stays as-is
  └─ ...
```

### TradierProvider (tradier_provider.py)

A stateless class wrapping Tradier REST endpoints:

```python
class TradierProvider:
    """REST wrapper for Tradier Broker API. Data + paper orders. No live trading."""

    def __init__(self):
        self.token = TRADIER_TOKEN
        self.account_id = TRADIER_ACCOUNT_ID
        self._base = self._resolve_base()
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.token}", "Accept": "application/json"})

    def _resolve_base(self) -> str:
        """Returns sandbox URL unless ALL safety gates are explicitly disabled."""
        if not TRADIER_LIVE_TRADING_DISABLED or not RISK.live_trading_enabled:
            return "https://sandbox.tradier.com/v1"  # always sandbox in Market Lab
        return "https://sandbox.tradier.com/v1"  # sandbox even if gate is off (belt + suspenders)

    def fetch_chain_snapshot(self, symbol: str, expiration: str | None = None,
                              min_dte: int = 14, max_dte: int = 60) -> OptionChainSnapshot:
        """Fetch option chain from Tradier sandbox. Returns OptionChainSnapshot."""

    def submit_paper_order(self, order: TradierOrder) -> TradierFill:
        """Submit order to Tradier sandbox. Returns fill confirmation."""

    def get_positions(self) -> list:
        """Fetch current positions from sandbox account."""

    def get_account_balance(self) -> dict:
        """Fetch sandbox account balance."""
```

**Key boundary rules:**
- `_resolve_base()` is the only place the base URL is determined — it always returns sandbox in Market Lab regardless of gate state (belt and suspenders on top of the env var gate).
- No secrets stored in the class — reads from `config` module globals.
- All HTTP errors surface as `TradierError` (custom exception), caught by the caller, with yfinance fallback.
- Paper orders use the exact same REST endpoint as live orders would (`POST /accounts/{id}/orders`) — the only difference is the base URL. This means the code path is validated against a real broker API even in paper mode.

### What Does NOT Cross the Boundary

| Does NOT cross from adapter into live | Why |
|----------------------------------------|-----|
| `_resolve_base()` returning production URL | Both gates must align; Market Lab defaults make this impossible |
| Storing production credentials | Only sandbox token is stored |
| Real-time market data subscriptions | Sandbox provides real-time without extra subscription |
| Automatic order retry on error | All failures are surfaced as `TradierError`; caller decides fallback |
| Order routing without `--network` flag | Same discipline as yfinance: flag must be set |
| Secret/credential in source code | Token lives in env / gitignored file only |

### Relationship with Existing Paper Portfolio

The existing `options_paper.py` (pure simulation) and `TradierPaperBroker` are **parallel paths**, not replacements:

```
Daily script flow (current):
  screen_covered_calls() / screen_cash_secured_puts()
    └─ evaluate_option_paper_order() → OptionPaperPortfolio (in-memory simulation)

Daily script flow (with Tradier paper):
  screen_covered_calls() / screen_cash_secured_puts()     (still uses OptionChainSnapshot)
    └─ evaluate_option_paper_order()                       (still runs risk gates)
    └─ TradierProvider.submit_paper_order()                (ALSO submits to Tradier sandbox)
```

The Tradier paper order is a **supplement** to the existing simulation — it lets you verify that the paper decision *would* have reached a broker API. But the existing `options_paper.py` simulation remains the primary portfolio tracker because:
- It works fully offline
- It doesn't depend on Tradier availability
- It has the full guardrail system (DTE, spread, delta, OI, volume, assignment limits)
- Tradier sandbox orders are advisory/indicative for validation

A config toggle `TRADIER_PAPER_VALIDATION` (default: False) controls whether Tradier paper submissions happen alongside the simulation.

---

## Exact First PR Scope

This is the minimal PR that gets Tradier into Market Lab without changing any existing behavior. Everything is additive and opt-in.

### Files Changed

| File | Change | Lines |
|------|--------|-------|
| `market_lab/config.py` | Add 4 env var constants + `OPTIONS_SOURCE` config | +~12 |
| `market_lab/options_data.py` | Add `fetch_option_chain_snapshot_tradier()` + source routing in `fetch_option_chain_snapshot` | +~40 |
| `market_lab/tradier_provider.py` | **NEW FILE** — `TradierProvider` class + `TradierOrder`/`TradierFill` dataclasses + `TradierError` | +~150 |
| `pyproject.toml` | Add `requests>=2.31` to `dependencies` | +1 |
| `tests/market_lab/test_tradier.py` | **NEW FILE** — unit tests with mocked HTTP | +~150 |
| `tradier.env.example` | **NEW FILE** — template for git (gitignored) | +5 |
| `.gitignore` | Add `tradier.env` | +1 |

### What Does NOT Change

- **No change** to `options_paper.py` — the pure-simulation module stays untouched
- **No change** to `options_screeners.py` — screeners read `OptionChainSnapshot` regardless of source
- **No change** to `broker.py` — equity broker is unaffected
- **No change** to `webapp.py` — still read-only
- **No change** to `daily.py` — the `--use-tradier` flag and Tradier paper submission come in a follow-up PR
- **No change** to existing tests — all pass unchanged
- **No change** to `data.py` — equity price fallback stays yfinance-only

### PR Branch Strategy

```
git checkout -b feat/tradier-sandbox-adapter
# Make changes
git commit -m "feat(options): add Tradier sandbox option chain + paper order adapter
                 
                 - TradierProvider class with chain fetch, order submission, position/balance queries
                 - source routing in fetch_option_chain_snapshot (auto/tradier/yfinance)
                 - TRADIER_TOKEN, TRADIER_ACCOUNT_ID, TRADIER_LIVE_TRADING_DISABLED env vars
                 - TRADIER_PAPER_VALIDATION toggle for supplementary paper submission
                 - requests>=2.31 dependency
                 - Unit tests with mocked HTTP (no sandbox token needed for tests)
                 
                 Posture: research-only. _resolve_base() always returns sandbox.
                 Independent TRADIER_LIVE_TRADING_DISABLED gate — separate from RiskConfig.
                 No change to options_paper.py, options_screeners.py, broker.py, or webapp.py."
# Open PR
gh pr create --fill
```

---

## Tests Required

### Unit Tests (test_tradier.py — no network, no sandbox token)

All tests use `responses` or `unittest.mock.patch('requests.Session')` to simulate Tradier API responses. No sandbox account needed to run tests.

| Test | What it verifies |
|------|-----------------|
| `test_fetch_chain_returns_option_chain_snapshot` | Parses a mocked Tradier chain JSON response into `OptionChainSnapshot` with correct contracts, greeks, source="tradier" |
| `test_fetch_chain_handles_empty_chain_gracefully` | Returns empty contracts list rather than crashing when chain has no options |
| `test_submit_paper_order_returns_fill` | Parses a mocked order response with order id, fill price, status, commission |
| `test_submit_paper_order_rejects_missing_fields` | Raises `TradierError` when required fields are missing |
| `test_resolve_base_always_sandbox` | `_resolve_base()` returns sandbox URL regardless of live_trading_enabled flag |
| `test_provider_raises_error_on_auth_failure` | `TradierError` raised on 401 from sandbox |
| `test_provider_raises_error_on_rate_limit` | `TradierError` raised on 429 |
| `test_source_routing_uses_tradier_when_token_present` | `fetch_option_chain_snapshot(source="auto")` routes to Tradier when token config is set |
| `test_source_routing_falls_back_to_yfinance` | `fetch_option_chain_snapshot(source="auto")` falls back to yfinance when token is missing |
| `test_source_routing_explicit_tradier_raises_without_token` | `fetch_option_chain_snapshot(source="tradier")` raises `RuntimeError` when token is missing |
| `test_source_tag_in_cached_snapshot` | Cached Tradier chain loads with `source: "tradier"` preserved |
| `test_provider_session_sets_correct_headers` | `Authorization: Bearer ...` and `Accept: application/json` headers are set |

### Integration Test (requires sandbox account — run manually)

```
pytest tests/market_lab/test_tradier.py -k "integration"  # skipped by default
```

| Test | What it verifies |
|------|-----------------|
| `test_integration_fetch_live_chain` | Fetches a real SPY chain from sandbox — verifies contracts have bid/ask/IV/OI/volume |
| `test_integration_account_balance` | Sandbox account balance endpoint returns expected structure |

### CI Run

```
python3 -m pytest tests/market_lab/test_tradier.py -q       # unit tests only
python3 -m pytest tests/market_lab -q                       # all existing tests + new unit tests
```

---

## Owner Steps (Ronak) — Sandbox Account & Token

These are the only steps that require a human at a browser. Everything else is implementable without them (the adapter falls through to yfinance when `TRADIER_TOKEN` is missing).

### Step 1: Register for Tradier Developer Sandbox

1. Go to https://developer.tradier.com/
2. Click **"Sign Up"** → use `ozlabshq@gmail.com`
3. Verify email
4. Once logged in, you'll see the **"Applications"** dashboard

### Step 2: Generate API Token

1. In the dashboard, click **"Get a Token"** or go to **"Access Tokens"**
2. Click **"Create a Token"** or **"Generate New Token"**
3. Copy the bearer token (a long alphanumeric string like `Bearer <token>` — the token is the part after "Bearer ")
4. Note the **Account ID** displayed on the dashboard (starts with `6US`)

### Step 3: Create `tradier.env`

```bash
cd /Users/ozlabs/market-lab
cp tradier.env.example tradier.env
# Edit tradier.env with the token and account ID:
# Line 1: ozlabshq@gmail.com
# Line 2: <paste_sandbox_token>
# Line 3: <paste_account_id>
```

### Step 4: Set Environment Variable (Optional — for shell sessions)

```bash
export TRADIER_TOKEN=<paste_sandbox_token>
export TRADIER_ACCOUNT_ID=<paste_account_id>
```

Or add to your `.zshrc` / `.bashrc` for persistent sessions.

### Verification

After setup, run the integration probe:
```bash
cd /Users/ozlabs/market-lab
python3 -c "
from market_lab.tradier_provider import TradierProvider
from market_lab.config import TRADIER_TOKEN, TRADIER_ACCOUNT_ID
assert TRADIER_TOKEN and TRADIER_ACCOUNT_ID, 'Token/Account ID required'
p = TradierProvider()
snap = p.fetch_chain_snapshot('SPY')
print(f'SPY chain fetched: {len(snap.contracts)} contracts, source={snap.source}')
for c in snap.contracts[:3]:
    print(f'  {c.option_type} {c.strike:.1f} bid={c.quote.bid:.2f} ask={c.quote.ask:.2f} IV={c.greeks.implied_volatility:.2%}')
"
```

Expected output: chain with real bid/ask/IV/Greeks. No errors.

---

## Follow-Up Scope (NOT in First PR)

These come in subsequent PRs after the adapter is merged and verified:

1. **`--use-tradier` flag in `scripts/market_lab_daily.py`** — wires TradierProvider into the daily report pipeline
2. **Tradier paper validation alongside simulation** — `TRADIER_PAPER_VALIDATION=True` sends orders to sandbox alongside `evaluate_option_paper_order`
3. **Dashboard integration** — shows Tradier sandbox account balance / positions on the read-only dashboard
4. **Chain caching with Tradier origin** — `source: "tradier"` caching so offline reports still work
5. **Chain freshness comparison** — diff Tradier vs yfinance chains for 10+ symbols before switching default source

---

## Risk Assessment for Phase 1

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Tradier sandbox API changes | Low | Pin to `/v1` path. Write integration tests against sandbox. All HTTP is through one `TradierProvider` class — easy to patch. |
| Tradier sandbox token leaks to git | Low-Med | `tradier.env` is gitignored. Token is never in source code. If leaked: revoke from Tradier dashboard, regenerate. |
| Tradier sandbox data quality differs from live | Med | Compare against yfinance for 10+ symbols before making Tradier the default source. Always keep yfinance fallback. |
| `requests` dependency increase | Low | Already planned in `pyproject.toml` — `requests` is standard library-adjacent and well-maintained. |
| Adapter over-engineered before validation | Low | The class is ~150 lines with 10 methods. Minimal surface. The order submission path is untested until `TRADIER_PAPER_VALIDATION` is wired in the daily script (follow-up PR). |

---

## Summary: One-Line Spec

> **Add `TradierProvider` (option chain fetch + sandbox order submission) as an optional yfinance alternative, gated by env vars and independent safety flags, with no changes to existing paper simulation or safety architecture.**
