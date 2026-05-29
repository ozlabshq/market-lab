from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("MARKET_LAB_DATA_DIR", ROOT / "data" / "market-lab")).expanduser().resolve()
PRICE_DIR = DATA_DIR / "prices"
SYNTHETIC_PRICE_DIR = DATA_DIR / "synthetic_prices"
REPORT_DIR = DATA_DIR / "reports"
FACTOR_DIR = DATA_DIR / "factors"
EVIDENCE_DIR = DATA_DIR / "evidence"
LEDGER_PATH = DATA_DIR / "mock_ledger.jsonl"
PENDING_CANDIDATES_PATH = DATA_DIR / "pending_order_candidates.jsonl"
STATE_PATH = DATA_DIR / "mock_portfolio_state.json"

DEFAULT_UNIVERSE = [
    # Broad but liquid starting watchlist: indexes, mega-cap tech, volatility proxy, crypto proxies.
    "SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "USO",
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA",
    "AMD", "AVGO", "SMCI", "COIN", "MSTR", "IBIT", "ETHA",
]

@dataclass(frozen=True)
class RiskConfig:
    starting_cash: float = 100_000.0
    max_position_pct: float = 0.10
    max_single_order_pct: float = 0.05
    min_trade_notional: float = 500.0
    max_trade_notional: float = 5_000.0
    commission_per_trade: float = 1.00
    slippage_bps: float = 5.0
    allow_short: bool = False
    allow_options: bool = False
    allow_margin: bool = False
    live_trading_enabled: bool = False

RISK = RiskConfig()

def ensure_dirs() -> None:
    for path in (DATA_DIR, PRICE_DIR, SYNTHETIC_PRICE_DIR, REPORT_DIR, FACTOR_DIR, EVIDENCE_DIR):
        path.mkdir(parents=True, exist_ok=True)
