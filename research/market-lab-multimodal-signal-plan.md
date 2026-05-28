# OzLabs Market Lab — Multimodal Signal Plan

Status: implementation direction after Ronak challenged price-only signals.

## Core correction

Price/charts are only one evidence layer. Market Lab should become a multi-lens research engine:

1. Price/technical behavior: momentum, trend, mean reversion, volatility.
2. Fundamentals: valuation, quality, growth, profitability, cash generation.
3. AI impact: direct AI sellers, infrastructure beneficiaries, productivity beneficiaries, disrupted incumbents.
4. Narrative/catalysts: filings, earnings calls, product launches, regulation, analyst revisions, news intensity.
5. Macro/liquidity: rates, dollar, oil, gold, credit, volatility, crypto liquidity.
6. Position/risk context: drawdown, correlation, concentration, liquidity, gap risk.

## Factor lens implemented now

`market_lab/factors.py` adds `FactorSnapshot` with:

- P/E
- P/B
- revenue growth YoY
- gross margin
- free cash flow yield
- AI impact score
- sentiment proxy
- source

Data sources now:

- `yfinance_info` when available and network is enabled.
- deterministic synthetic fallback only for pipeline continuity.
- cache under `data/market-lab/factors/*.csv`.

`apply_factor_overlay()` nudges ensemble confidence but is capped so fundamentals/narrative do not blindly flip trade direction.

## Near-term data sources to add

Free/low-cost, auditable first:

- SEC Company Facts API: revenue, net income, shares, assets, liabilities, cash flow.
- SEC 10-K/10-Q text: AI mentions, risk-factor changes, capex language, customer concentration.
- Earnings call transcripts: AI/productivity/capex mentions if free sources are available; otherwise manual CSV/import first.
- yfinance metadata: valuation/growth/margins as a pragmatic quick start.
- FRED: rates, yield curve, credit spreads, dollar proxy, liquidity context.
- News/RSS search: catalyst counts and evidence links, not LLM-only claims.

## Scoring principles

- Keep every score explainable with evidence fields.
- Label source quality: real API/cache/synthetic/manual.
- Separate signal types; do not collapse everything into one magic score too early.
- Use overlays to adjust confidence, not to claim edge.
- Require backtests or mock tracking per factor before weighting it heavily.

## AI impact taxonomy

- Direct AI suppliers: GPUs, accelerators, data center hardware, networking, memory, power/cooling.
- Cloud/platform winners: hyperscalers, developer platforms, SaaS copilots.
- AI adopters: companies with credible margin/revenue acceleration from AI use.
- AI-disrupted: seats/services vulnerable to automation or pricing compression.
- Second-order infrastructure: energy, copper, grid, cooling, REIT/data centers.

Initial score should combine:

- business description / filing language mentions,
- revenue segment relevance,
- capex/customer exposure,
- gross margin and revenue growth,
- price trend confirmation,
- news/catalyst evidence.

## Guardrails

- No synthetic factor should be treated as evidence.
- No LLM-generated AI impact fact should enter a score without a cited source/link or structured source field.
- Avoid one-day news chasing until execution model supports gaps/slippage.
- Track factor timestamp; stale fundamentals should not masquerade as current signals.
- For ETFs, factor data should be treated differently from single-stock fundamentals.

## Next implementation phases

1. Add SEC Company Facts ingestion for US equities.
2. Add macro regime module using FRED/yfinance proxies.
3. Add evidence store for news/filing snippets with URLs and timestamps.
4. Add AI impact scorer backed by filings/business summaries, then transcripts.
5. Add factor backtests: value + momentum, quality + momentum, growth-at-reasonable-price, AI basket vs benchmark.
