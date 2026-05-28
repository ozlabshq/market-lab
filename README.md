# Market Lab

OzLabs Market Lab is a research-first market intelligence and paper/mock trading system.

Current posture: **research-only**.

- No live broker execution
- No autonomous orders
- No margin, shorting, or options execution
- Mock/paper tracking only after explicit gates
- Reports are educational/research artifacts, not financial advice

## What is included

- `market_lab/` — Python package for data, indicators, signals, backtests, factors, reporting, and mock broker logic
- `scripts/market_lab_daily.py` — daily report runner
- `tests/market_lab/` — regression/safety tests
- `research/` — implementation plans and reviews
- `docs/` — diagrams and system roadmap artifacts

## Quick start

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest tests/market_lab -q
```

Generate a local research report:

```bash
python3 scripts/market_lab_daily.py
```

## Data/state policy

Generated market data, mock ledgers, portfolio state, reports, caches, and quarantine folders are intentionally excluded from git.

Do not commit:

- `data/market-lab/prices/`
- `data/market-lab/factors/`
- `data/market-lab/reports/`
- `data/market-lab/mock_ledger.jsonl`
- `data/market-lab/mock_portfolio_state.json`
- `data/market-lab/pending_order_candidates.jsonl`
- secrets or broker credentials

## Development workflow

Use branch + PR workflow for every non-trivial change:

```bash
git checkout main
git pull origin main
git checkout -b fix/synthetic-cache-source-tracking
# edit + test
git add .
git commit -m "fix: prevent synthetic price cache laundering"
git push -u origin HEAD
gh pr create --fill
```

Before options work, close the safety gaps documented in `research/market-lab-claude-opus-implementation-review-20260528.md`.
