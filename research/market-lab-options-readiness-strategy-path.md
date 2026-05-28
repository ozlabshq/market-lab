# Market Lab — Options Readiness Strategy Path
**Status:** Research gate definition — no execution code yet  
**Scope:** Design the data models, metrics, screening logic, risk/accounting framework, and test specifications required before any options paper-trading code is written.  
**Date:** 2026-05-28  
**Constraint:** Design-only. Do not implement order execution, broker integration, or live trading paths.

---

## 1. PURPOSE

Market Lab currently queues mock stock positions via `OrderCandidate` → `place_mock_order`. Ronak wants better strategies and options eventually. Before writing options execution code, we must define the **next research gate**: a complete design for options-chain ingestion, implied-volatility metrics, cash-secured put / covered-call screening, and the risk/accounting requirements that would govern a future paper-options ledger.

This document is the design contract. Implementation order and test specifications are explicit. No options execution code is written until this design is reviewed and the research gate is cleared.

---

## 2. CURRENT BASELINE (EQUITY-ONLY)

| Component | Current State | Options Gap |
|-----------|--------------|-------------|
| `broker.py` | `Position`, `Portfolio`, `OrderDecision`, `OrderCandidate` — all equity shares | No option contract model; no reserve accounting for CSP/covered-call collateral |
| `config.py` | `RiskConfig` with `allow_options=False` | Need `OptionsRiskConfig` sub-config |
| `data.py` | `Bar` (OHLCV) for equities | No option chain snapshot; no greeks; no term structure |
| `signals.py` | `Signal` action ∈ {BUY, SELL, HOLD} | No option-specific signal types (e.g., `WRITE_CALL`, `WRITE_PUT`) |
| `report.py` | Equity-only sections | No options candidate section |
| `backtest.py` | Long-only equity backtest | No option strategy backtest framework |
| Tests | `test_broker.py`, `test_research_strategies.py` | No options parsing, liquidity, or reserve tests |

---

## 3. RESEARCH GATE DEFINITION

### Gate 0 — Completed
- ✅ Define supported strategies (covered call, cash-secured put research)
- ✅ Define option contract model (see §4)
- ✅ Define option chain provider interface (see §5)
- ✅ Define paper options ledger schema (see §8)
- ✅ Define risk limits and kill switch (see §9)

### Gate 1 — Options Data Ingestion (NEXT)
**Deliverable:** `market_lab/options_data.py` + `tests/market_lab/test_options_data.py`

**Core models to design:**
- `OptionContract` — immutable dataclass representing a single call/put contract
- `OptionChainSnapshot` — expiration-date-indexed collection of contracts for one underlying
- `OptionQuote` — bid/ask/mid/last/volume/OI for a contract
- `OptionGreeks` — optional delta/gamma/theta/vega/rho; gracefully degrades when missing

**Provider pattern:**
- Primary: yfinance options chains (available now, no extra API keys)
- Cache: `data/market-lab/options/chains/{symbol}/{YYYYMMDD}_{expiration}.json`
- Every snapshot must carry `source: str` and `timestamp_utc: str`
- Disclosure rule: report must label chain source and staleness

**Required tests (to be written when Gate 1 is implemented):**
1. Parse call/put contract rows from yfinance chain DataFrame
2. Reject stale chains (> 24 hours old for daily research)
3. Handle bid/ask/mid correctly; reject contracts with missing bid or ask
4. Gracefully degrade when greeks are missing (do not crash)
5. Cache write/read roundtrip preserves all fields
6. Concurrent cache writes are safe (atomic rename pattern, same as `data.py`)

### Gate 2 — IV / Rank / Skew Metrics (NEXT)
**Deliverable:** `market_lab/options_metrics.py` + `tests/market_lab/test_options_metrics.py`

**Metrics to compute from chain snapshots:**

| Metric | Definition | Use Case |
|--------|-----------|----------|
| `iv_atm` | Implied volatility of nearest ATM call+put average | Baseline vol estimate |
| `iv_rank_52w` | `(current_iv - 52w_min) / (52w_max - 52w_min)` | Sell premium when rank > 50% |
| `iv_percentile` | Percentile of current IV over trailing 252 daily IV snapshots | Alternative to rank when 52w window incomplete |
| `skew_25d` | IV(25-delta put) − IV(25-delta call) | Risk-reversal skew; fear gauge |
| `term_structure_slope` | IV(30d) − IV(90d) | Contango/backwardation proxy |
| `expected_move_pct` | `(ATM_call_premium + ATM_put_premium) / spot_price` | Market-implied move into expiration |

**Design constraints:**
- All metrics must handle missing greeks via moneyness interpolation
- Historical IV window requires a new `data/market-lab/options/iv_history/` cache
- Metrics are **research-only** at this gate; no trading signals yet
- Must disclose when metrics are derived from bid/ask mid vs. last trade

**Required tests:**
1. ATM identification works when strikes are irregular (splits, reverse splits)
2. IV rank returns `None` when history < 30 days (insufficient data)
3. Skew calculation degrades to nearest available delta when 25d missing
4. Expected move never exceeds 100% (sanity cap)
5. All metrics return `None` rather than raise on empty chain

### Gate 3 — Cash-Secured Put / Covered Call Screening (NEXT)
**Deliverable:** `market_lab/options_screeners.py` + `tests/market_lab/test_options_screeners.py`

**Screener 1: Covered Call Candidate**

Inputs:
- `underlying_symbol: str`
- `spot_price: float`
- `chain: OptionChainSnapshot`
- `shares_owned: int` (or hypothetical 100-share lot)
- `config: OptionsRiskConfig`

Screening rules:
1. DTE ∈ [config.min_dte, config.max_dte] (default 14–45)
2. Delta proxy: if greeks available, 0.15 ≤ delta ≤ 0.35; else use moneyness (OTM by 1–5%)
3. Liquidity gates:
   - `volume ≥ config.min_volume` (default 10)
   - `open_interest ≥ config.min_open_interest` (default 100)
   - `bid_ask_spread_pct ≤ config.max_bid_ask_spread_pct` (default 15%)
4. Premium annualized yield ≥ 5% (conservative threshold)
5. Earnings/catalyst warning if expiration within 7 days of known event

Output: `CoveredCallCandidate` dataclass with:
- `symbol`, `strike`, `expiration`, `premium`, `annualized_yield`, `distance_otm_pct`, `delta`, `liquidity_score`, `risk_notes: list[str]`

**Screener 2: Cash-Secured Put Candidate**

Inputs:
- Same as above plus `cash_available: float`

Screening rules:
1. DTE ∈ [config.min_dte, config.max_dte]
2. Strike below spot by configurable buffer (default 3–10% OTM)
3. Same liquidity gates as covered call
4. Cash reserve check: `strike * 100 ≤ cash_available * config.max_assignment_notional_pct`
5. Premium annualized yield ≥ 5%
6. Earnings/catalyst warning same as above

Output: `CashSecuredPutCandidate` dataclass with similar fields plus `cash_required`, `buffer_pct`.

**Ranking logic:**
- Primary: annualized yield / max_drawdown_risk_proxy (conservative income metric)
- Secondary: liquidity score (volume * OI / spread)
- Tertiary: distance from spot (farther OTM = lower assignment risk)

**Required tests:**
1. Reject illiquid contracts (volume=0, OI=0, wide spread)
2. Reject contracts with missing bid/ask
3. Reject CSP if cash reserve insufficient
4. Reject covered call if no 100-share lot available
5. Rank candidates by conservative metric, not raw premium alone
6. Earnings warning flag populated when expiration near catalyst
7. Empty chain returns empty list, not exception

### Gate 4 — Risk / Accounting Requirements (NEXT)
**Deliverable:** Updates to `config.py` design + `market_lab/options_risk.py` (design-only)

**OptionsRiskConfig dataclass (to be added to `config.py`):**

```python
@dataclass(frozen=True)
class OptionsRiskConfig:
    allow_options: bool = False                    # master kill switch
    paper_options_enabled: bool = False            # allow paper tracking
    live_options_enabled: bool = False             # always False until Gate 6
    min_dte: int = 14
    max_dte: int = 45
    max_bid_ask_spread_pct: float = 0.15
    min_open_interest: int = 100
    min_volume: int = 10
    max_contracts_per_symbol: int = 1
    max_assignment_notional_pct: float = 0.10      # per-position cap
    max_total_options_assignment_pct: float = 0.25 # portfolio-wide cap
    allow_naked_calls: bool = False                # never in MVP
    allow_margin: bool = False                     # never in MVP
    min_premium_yield_annualized: float = 0.05     # screener threshold
    max_delta_short_call: float = 0.35             # delta guardrail
    max_delta_short_put: float = 0.30              # delta guardrail
    require_earnings_warning: bool = True
```

**Accounting rules for future paper ledger (design-only, not implemented):**

| Event | Accounting Action |
|-------|------------------|
| Open short call (covered) | Reserve 100 shares per contract; reduce available shares |
| Open short put (CSP) | Reserve cash = strike * 100 per contract; reduce available cash |
| Daily mark-to-market | MTM = mid_price * 100 * contracts; P&L = entry_credit − current liability |
| Expiration OTM | Release reserve; record premium as realized P&L |
| Expiration ITM short call | Simulate assignment: deliver shares at strike; release share reserve; record gain/loss vs. cost basis |
| Expiration ITM short put | Simulate assignment: buy shares at strike; release cash reserve; create equity position |
| Early assignment | Same as expiration ITM; log as early-assignment event |

**Kill switch rules:**
- If `allow_options=False`, no options code path may run (defensive check at entry points)
- If `live_options_enabled=False`, any live order submission raises `RuntimeError`
- If portfolio assignment exposure > `max_total_options_assignment_pct`, block new short options
- If any single symbol > `max_contracts_per_symbol`, block additional writes on that symbol

**Required tests (for when implemented):**
1. `allow_options=False` blocks all options screeners
2. Covered call opening reserves exactly 100 shares per contract
3. CSP opening reserves exactly `strike * 100` cash per contract
4. Expiration OTM releases reserve and records premium P&L
5. Expiration ITM simulates assignment with correct cost basis
6. Portfolio-wide assignment cap blocks new writes when exceeded
7. Kill switch raises on any live order attempt

---

## 4. OPTION CONTRACT DATA MODEL (DESIGN)

```python
from dataclasses import dataclass
from datetime import date
from typing import Literal

@dataclass(frozen=True)
class OptionGreeks:
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    rho: float | None

@dataclass(frozen=True)
class OptionQuote:
    bid: float
    ask: float
    last: float | None
    volume: int
    open_interest: int
    timestamp_utc: str

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float:
        if self.mid <= 0:
            return float("inf")
        return (self.ask - self.bid) / self.mid

@dataclass(frozen=True)
class OptionContract:
    underlying: str
    expiration: date
    strike: float
    option_type: Literal["CALL", "PUT"]
    quote: OptionQuote
    greeks: OptionGreeks | None

@dataclass(frozen=True)
class OptionChainSnapshot:
    underlying: str
    spot_price: float
    quote_date: date
    source: str
    timestamp_utc: str
    contracts: list[OptionContract]  # filtered to relevant expirations
```

**Serialization:** JSON with ISO date strings. Cache path: `data/market-lab/options/chains/{SYMBOL}/{YYYYMMDD}_{EXPIRATION}.json`.

---

## 5. PROVIDER INTERFACE (DESIGN)

```python
from abc import ABC, abstractmethod
from datetime import date

class OptionChainProvider(ABC):
    @abstractmethod
    def fetch_chain(self, symbol: str, as_of: date | None = None) -> OptionChainSnapshot:
        """Return full chain for symbol. as_of defaults to today."""
        ...

    @abstractmethod
    def available_expirations(self, symbol: str) -> list[date]:
        ...

class YFinanceOptionChainProvider(OptionChainProvider):
    """Concrete implementation using yfinance."""
    ...
```

**Caching strategy:**
- Fetch once per day per symbol (after market close)
- Store all expirations in one snapshot file per day
- TTL = 24 hours for research use; 4 hours if used for paper tracking
- Stale data must be labeled explicitly in reports

---

## 6. SCREENER OUTPUT MODELS (DESIGN)

```python
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class CoveredCallCandidate:
    underlying: str
    spot_price: float
    strike: float
    expiration: date
    premium: float              # mid price at write
    annualized_yield: float     # premium / spot / dte * 365
    distance_otm_pct: float
    delta: float | None
    liquidity_score: float
    risk_notes: list[str]
    source: str
    timestamp_utc: str

@dataclass(frozen=True)
class CashSecuredPutCandidate:
    underlying: str
    spot_price: float
    strike: float
    expiration: date
    premium: float
    annualized_yield: float
    buffer_pct: float           # (spot - strike) / spot
    cash_required: float        # strike * 100
    delta: float | None
    liquidity_score: float
    risk_notes: list[str]
    source: str
    timestamp_utc: str
```

---

## 7. INTEGRATION POINTS WITH EXISTING SYSTEM

| Existing Component | Integration | Change Required |
|-------------------|-------------|-----------------|
| `config.py` | Add `OptionsRiskConfig` | New dataclass; no breaking changes to `RiskConfig` |
| `report.py` | Add "Options Research" section | New optional parameter `options_candidates`; renders only when present |
| `market_lab_daily.py` | Add `--options-research` flag | Gated by `OptionsRiskConfig.allow_options`; fetches chains, runs screeners, appends to report |
| `broker.py` | No direct integration yet | Future: `options_broker.py` will handle paper ledger; keep `broker.py` equity-only for now |
| `signals.py` | No direct integration yet | Future: option signals are separate from equity signals; do not overload `Signal.action` |

**Report section draft (for Gate 3+):**

```markdown
## Options Research — Paper Only

### Covered Call Candidates
- AAPL $220 CALL 2026-06-20: premium $1.25, yield 18.2% ann, OTM 4.2%, delta 0.28, liq 8.5/10; risk: earnings 2026-06-15

### Cash-Secured Put Candidates
- MSFT $380 PUT 2026-06-20: premium $1.80, yield 14.1% ann, buffer 6.1%, cash req $38,000; risk: none

### Liquidity Warnings
- TSLA 2026-06-20 chain: 3 contracts rejected for spread > 15%

### Assignment Risk Summary
- Max single-position assignment exposure: 10.0%
- Portfolio-wide assignment exposure: 0.0% (no paper positions)

*Disclaimer: Options research only. No live orders. No margin. No naked calls.*
```

---

## 8. PAPER OPTIONS LEDGER SCHEMA (DESIGN-ONLY)

**Files (not created yet):**
- `data/market-lab/options/paper_options_ledger.jsonl` — chronological log
- `data/market-lab/options/paper_options_positions.json` — open positions snapshot
- `data/market-lab/options/reserves.json` — share/cash reserves

**Ledger entry schema:**
```json
{
  "event": "OPEN|MTM|EXPIRE|ASSIGN|CLOSE",
  "timestamp_utc": "2026-05-28T20:00:00Z",
  "underlying": "AAPL",
  "option_type": "CALL",
  "strike": 220.0,
  "expiration": "2026-06-20",
  "quantity": -1,
  "premium": 1.25,
  "mtm_value": null,
  "realized_pnl": null,
  "reserve_released": false,
  "notes": ["covered call opened", "100 shares reserved"]
}
```

**Position schema:**
```json
{
  "AAPL|CALL|220.0|2026-06-20": {
    "quantity": -1,
    "entry_premium": 1.25,
    "current_mid": 1.10,
    "unrealized_pnl": 15.0,
    "shares_reserved": 100,
    "cash_reserved": 0
  }
}
```

---

## 9. IMPLEMENTATION ORDER

| Phase | File(s) | Gate | Effort | Dependencies |
|-------|---------|------|--------|--------------|
| 1 | `market_lab/options_data.py` + `tests/market_lab/test_options_data.py` | Gate 1 | Medium | yfinance, existing cache patterns |
| 2 | `market_lab/options_metrics.py` + `tests/market_lab/test_options_metrics.py` | Gate 2 | Medium | Gate 1, historical IV cache |
| 3 | `market_lab/options_screeners.py` + `tests/market_lab/test_options_screeners.py` | Gate 3 | Medium | Gate 1–2, `OptionsRiskConfig` |
| 4 | Update `config.py` with `OptionsRiskConfig` | Gate 4 | Small | None (parallel with Phase 1) |
| 5 | Update `report.py` with options section | Gate 3 | Small | Gate 3 screener outputs |
| 6 | Update `market_lab_daily.py` with `--options-research` | Gate 3 | Small | Gate 3–5 |
| 7 | `market_lab/options_broker.py` + `tests/market_lab/test_options_broker.py` | Future | Large | All above + paper ledger design |
| 8 | Read-only broker integration | Gate 5 | Large | Stable paper engine |
| 9 | Approval-required live orders | Gate 6 | Very Large | Gate 5 + kill switch + audit log |

**Recommended first build slice:** Phases 1–4 together, then Phase 5–6 as a follow-up slice. This gives Ronak report-visible options research without any paper ledger complexity.

---

## 10. TEST SPECIFICATION SUMMARY

### Unit Tests by Gate

**Gate 1 — Data Ingestion (`test_options_data.py`)**
- `test_parse_yfinance_call_put_rows`
- `test_reject_stale_chain`
- `test_reject_missing_bid_ask`
- `test_degrade_missing_greeks`
- `test_cache_roundtrip`
- `test_concurrent_cache_writes_safe`

**Gate 2 — Metrics (`test_options_metrics.py`)**
- `test_atm_identification_irregular_strikes`
- `test_iv_rank_returns_none_for_short_history`
- `test_skew_degrades_to_nearest_delta`
- `test_expected_move_capped_at_100pct`
- `test_all_metrics_none_on_empty_chain`

**Gate 3 — Screeners (`test_options_screeners.py`)**
- `test_reject_illiquid_contracts`
- `test_reject_missing_bid_ask`
- `test_reject_csp_insufficient_cash`
- `test_reject_covered_call_without_100_shares`
- `test_rank_by_conservative_metric_not_premium`
- `test_earnings_warning_flag`
- `test_empty_chain_returns_empty_list`

**Gate 4 — Risk/Accounting (`test_options_risk.py` — future)**
- `test_allow_options_false_blocks_screeners`
- `test_covered_call_reserves_shares`
- `test_csp_reserves_cash`
- `test_expiration_otm_releases_reserve`
- `test_expiration_itm_simulates_assignment`
- `test_portfolio_assignment_cap_blocks_new_writes`
- `test_kill_switch_raises_on_live_order`

### Integration Tests (future)
- `test_daily_script_options_research_flag` — end-to-end with `--options-research --network`
- `test_report_contains_options_section_when_candidates_present`
- `test_report_discloses_stale_chain_source`

---

## 11. NON-NEGOTIABLES

1. **No options execution code until Gate 1–4 are complete and tested.**
2. **No live trading path until Gate 6.**
3. **No margin, no naked short calls, ever in MVP.**
4. **All option metrics and screeners are research-only until paper ledger is built.**
5. **Liquidity gates (spread, volume, OI) are mandatory, not optional.**
6. **Assignment risk must be explicit in every candidate output.**
7. **Ronak approval required before any code moves from paper to broker integration.**

---

## 12. BIBLIOGRAPHY & SOURCES

- Natenberg, S. (1994). *Option Volatility and Pricing Strategies.* McGraw-Hill.
- Cottle, S., Murray, R., & Block, F. (1988). *Graham and Dodd's Security Analysis.* McGraw-Hill. (covered call income framing)
- Hull, J. C. (2018). *Options, Futures, and Other Derivatives.* 10th ed. Pearson.
- Euan Sinclair (2010). *Option Trading: Pricing and Volatility Strategies and Techniques.* Wiley.
- Practitioner: Tastytrade / dough research on IV rank, IV percentile, and premium-selling expectancy.

---

*Document version: 1.0. Research use only. Not investment advice.*
