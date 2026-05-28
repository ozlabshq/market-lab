# OptionsBooster reuse assessment for OzLabs Market Lab

Date: 2026-05-27
Repo: https://github.com/ronakgune/OptionsBooster
Local clone: `/Users/ozlabs/OzLabs/external/OptionsBooster`
Commit inspected: `b84bc72` on `master`

## Verdict

Useful as a **seed architecture and code mine**, not as a production trading engine.

OptionsBooster already contains a lot of concepts that match OzLabs Market Lab:
- local-first trading research app
- Magnificent 7 options-income focus
- covered call and cash-secured put workflows
- paper trading portfolio and paper trade persistence
- API fallback/caching layer
- multi-agent market/risk/portfolio architecture
- LangChain tools for market data, portfolio query, paper trade execution, and risk analysis
- SQLite models for holdings, cash, options trades, paper trades, performance, market cache, and agent state

But it should not be connected to live money as-is because core analytics are simplified/placeholders and the dependency footprint is heavy for the current 8GB MacBook.

## Live access and verification

- Public access works after Ronak made the repo public.
- Cloned into `/Users/ozlabs/OzLabs/external/OptionsBooster`.
- GitHub reports:
  - owner/repo: `ronakgune/OptionsBooster`
  - visibility: public
  - primary language: Python
  - default branch: `master`
- Python syntax compile check passed: `python3 -m compileall -q src main.py quick_demo.py quick_test.py simple_test.py test_*.py`
- Code size: 43 Python files, approx 8,611 nonblank/noncomment Python LOC.

## Important security note

The repo docs say real API keys were previously committed and later replaced with placeholders. Even if current files are scrubbed, old public git history may still expose those historical secrets unless history was rewritten.

Recommended actions before relying on any old keys:
1. Treat all previously committed Polygon, Alpha Vantage, Gemini, Alpaca, and Tradier credentials as compromised.
2. Revoke/regenerate them.
3. Optionally rewrite repo history or archive this public repo and start a clean OzLabs-private successor.
4. Add secret scanning/pre-commit before future commits.

## Reusable pieces

### 1. Product direction

The strongest reusable asset is the original product framing in `docs/product_idea.md`:
- focused on Mag 7 stocks
- conservative income strategies
- manual/broker-agnostic MVP
- local privacy
- trade suggestions, trade tracking, position management, performance analytics

This maps well into OzLabs Market Lab if we broaden the first universe to:
- research ETF core: `SPY`, `QQQ`, maybe `IWM`
- options-income watchlist: `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `NVDA`, `META`, `TSLA`

### 2. Database schema

Useful models:
- `src/models/portfolio.py`
  - `Holdings`
  - `CashPosition`
  - `OptionsTrades`
  - `PaperPortfolio`
  - `PaperTrades`
  - `PaperPerformance`
- `src/models/market_data.py`
- `src/models/agent_state.py`

Good starting point for a Market Lab persistence layer, but should be simplified and migrated into a clean `market_lab/` module rather than reused wholesale.

### 3. Paper trading persistence

`src/core/database_manager.py` has workable patterns for:
- initializing a paper portfolio
- recording paper option trades
- tracking open paper trades
- summarizing paper performance
- caching market data

Caveat: the paper trade simulation is simplified. It records premiums and reserves cash, but does not yet model realistic fills, assignment, bid/ask spread, early assignment, option valuation, or expiration processing robustly.

### 4. API manager/fallbacks

`src/api/api_manager.py` is useful conceptually:
- `DataType` enum for stock price, options chain, VIX, volatility, market status, RSI
- fallback order: Polygon -> Yahoo -> cache for some data types
- cache update through database manager

For OzLabs, this should be refactored into a thinner provider interface:
- `MarketDataProvider`
- `OptionsDataProvider`
- `BrokerReadProvider`
- `PaperExecutionProvider`

### 5. Agent architecture

Useful concepts:
- `MarketIntelligenceAgent`
- `RiskManagementAgent`
- `PortfolioManagementAgent`
- message bus/event routing
- daily scheduled market/risk analysis
- formatted reports

But in OzLabs we should probably not run a full internal agent bus on the 8GB MacBook. Better first version:
- deterministic scripts generate signals and reports
- Ozzy interprets/reviews output
- only later add multiple autonomous agents

### 6. LangChain tools

`src/agents/langchain_integration/tools.py` is directly relevant to Robinhood MCP-style thinking. Existing tools include:
- get stock price
- get options chain
- get VIX
- get volatility
- get portfolio
- get paper portfolio
- execute paper trade
- analyze risk

This can inspire an OzLabs tool interface, but we should implement it leaner and framework-light initially.

## Not production-ready / do not reuse blindly

### Strategy quality

Current signals are mostly toy heuristics:
- RSI > 70 -> consider covered calls
- RSI < 30 -> consider cash-secured puts
- VIX thresholds drive broad recommendations
- portfolio metrics include placeholders for win rate, Sharpe, drawdown, volatility, beta, alpha
- expected returns are hardcoded assumptions
- Kelly criterion is simplified and RSI-based, not derived from actual win/loss distribution

These are useful scaffolds, not edge.

### Options math

Risk/probability calculations are simplified and probably dimensionally weak:
- approximate probability ITM from moneyness and volatility
- simplified premium calculation in `ExecutePaperTradeTool`
- no proper Greeks-based selection engine
- no bid/ask or open interest/liquidity filtering as a first-class constraint

### Live trading boundary

The repo has real-trade concepts (`OptionsTrades`, real holdings/cash), but no safe live execution layer. For OzLabs, live trading should remain disabled until:
- backtest evidence exists
- paper-trading evidence exists
- broker connection is read-only first
- explicit approval mode is implemented
- hard max-loss/order limits and kill switch exist

### Dependency footprint

`requirements.txt` is large: LangChain, ChromaDB, FastAPI, OpenTelemetry, Kubernetes, Google GenAI, Alpaca SDK, pandas, SQLAlchemy, etc.

On the 2017 MacBook with 8GB RAM, we should not install/run the full stack unless isolated in a venv and only when needed. A clean Market Lab MVP should use a minimal dependency set.

## Suggested OzLabs path

### Immediate reuse

Do not revive OptionsBooster as the main app. Instead:
1. Keep it as `/external/OptionsBooster` reference material.
2. Extract ideas into a new clean Market Lab MVP under `/Users/ozlabs/OzLabs/market_lab/`.
3. Start with deterministic, auditable research scripts.

### Market Lab MVP

Build a lean engine that:
- pulls daily OHLCV for `SPY`, `QQQ`, `AAPL`, `MSFT`, `NVDA`, etc.
- computes RSI, moving averages, realized volatility, drawdowns
- generates non-trading signals/research notes
- backtests simple baseline strategies
- stores outputs under `data/market-lab/`
- sends/prints a daily report
- does not place live trades

### OptionsBooster components to port later

Port in this order:
1. `OptionType`, `TradeStatus`, `PaperTrades` style models
2. paper portfolio summary logic
3. market data cache schema
4. options-chain provider interface
5. risk-gate rules from `RiskManagementAgent`
6. agent tool interface inspired by LangChain tools, but without LangChain dependency initially

## Bottom line

OptionsBooster is absolutely useful for us. It proves Ronak already pushed in the right direction with agentic trading before Robinhood MCP made the surface more obvious.

The best move is to treat it as a prior prototype and fold the durable ideas into a cleaner OzLabs Market Lab:
- research-first
- paper-first
- transparent/auditable
- low-dependency
- no live orders until much later
