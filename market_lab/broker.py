from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .config import LEDGER_PATH, PENDING_CANDIDATES_PATH, STATE_PATH, RiskConfig, RISK, ensure_dirs

@contextmanager
def _portfolio_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w") as lock_file:
        try:
            import fcntl  # type: ignore
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                import fcntl  # type: ignore
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass

def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)

Side = Literal["BUY", "SELL"]

@dataclass
class Position:
    symbol: str
    quantity: int = 0
    avg_price: float = 0.0

@dataclass
class Portfolio:
    cash: float = RISK.starting_cash
    positions: dict[str, Position] = field(default_factory=dict)

    def market_value(self, prices: dict[str, float]) -> float:
        return sum(pos.quantity * prices.get(sym, pos.avg_price) for sym, pos in self.positions.items())

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + self.market_value(prices)

@dataclass(frozen=True)
class OrderDecision:
    accepted: bool
    side: Side
    symbol: str
    quantity: int
    requested_price: float
    fill_price: float | None
    reason: str
    timestamp: str

@dataclass(frozen=True)
class OrderCandidate:
    side: Side
    symbol: str
    quantity: int
    strategy: str
    confidence: float
    reason: str
    signal_date: str
    reference_close: float
    intended_execution: str = "next_open"

def position_market_value(portfolio: Portfolio, symbol: str, prices: dict[str, float]) -> float:
    pos = portfolio.positions.get(symbol.upper())
    if not pos:
        return 0.0
    return pos.quantity * prices.get(pos.symbol, pos.avg_price)

def load_portfolio(path: Path = STATE_PATH) -> Portfolio:
    if not path.exists():
        return Portfolio()
    try:
        data=json.loads(path.read_text())
        positions={sym: Position(**p) for sym,p in data.get("positions", {}).items()}
        return Portfolio(cash=float(data.get("cash", RISK.starting_cash)), positions=positions)
    except (json.JSONDecodeError, TypeError, ValueError):
        return Portfolio()

def save_portfolio(portfolio: Portfolio, path: Path = STATE_PATH) -> None:
    ensure_dirs()
    data={"cash": portfolio.cash, "positions": {k: asdict(v) for k,v in portfolio.positions.items() if v.quantity != 0}}
    _atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True))

def append_ledger(decision: OrderDecision, path: Path = LEDGER_PATH) -> None:
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(decision), sort_keys=True) + "\n")

def append_order_candidates(candidates: list[OrderCandidate], path: Path = PENDING_CANDIDATES_PATH) -> None:
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for candidate in candidates:
            f.write(json.dumps(asdict(candidate), sort_keys=True) + "\n")

def load_order_candidates(path: Path = PENDING_CANDIDATES_PATH) -> list[OrderCandidate]:
    if not path.exists():
        return []
    candidates=[]
    try:
        with path.open() as f:
            for line in f:
                line=line.strip()
                if line:
                    candidates.append(OrderCandidate(**json.loads(line)))
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    return candidates

def save_order_candidates(candidates: list[OrderCandidate], path: Path = PENDING_CANDIDATES_PATH) -> None:
    ensure_dirs()
    if not candidates:
        _atomic_write_text(path, "")
        return
    text = "".join(json.dumps(asdict(candidate), sort_keys=True) + "\n" for candidate in candidates)
    _atomic_write_text(path, text)

def candidate_to_order_at_open(candidate: OrderCandidate, next_open: float, prices: dict[str, float], portfolio_path: Path = STATE_PATH, ledger_path: Path = LEDGER_PATH) -> OrderDecision:
    return place_mock_order(candidate.side, candidate.symbol, candidate.quantity, next_open, prices, portfolio_path, ledger_path)

def evaluate_order(portfolio: Portfolio, side: Side, symbol: str, quantity: int, price: float, prices: dict[str, float], risk: RiskConfig = RISK) -> OrderDecision:
    now=datetime.now(timezone.utc).isoformat()
    symbol=symbol.upper()
    if risk.live_trading_enabled:
        return OrderDecision(False, side, symbol, quantity, price, None, "live trading flag unexpectedly enabled; mock broker refuses", now)
    if quantity <= 0 or price <= 0:
        return OrderDecision(False, side, symbol, quantity, price, None, "quantity and price must be positive", now)
    if side not in ("BUY", "SELL"):
        return OrderDecision(False, side, symbol, quantity, price, None, "unsupported side", now)
    pos=portfolio.positions.get(symbol, Position(symbol))
    if side == "SELL" and pos.quantity < quantity:
        if risk.allow_short:
            return OrderDecision(False, side, symbol, quantity, price, None, "shorting is unsupported in MVP mock broker", now)
        return OrderDecision(False, side, symbol, quantity, price, None, "sell rejected: no shorting and insufficient shares", now)
    equity=max(portfolio.equity(prices), 1.0)
    gross=quantity * price
    if gross < risk.min_trade_notional:
        return OrderDecision(False, side, symbol, quantity, price, None, "below minimum trade notional", now)
    if gross > risk.max_trade_notional or gross > equity * risk.max_single_order_pct:
        return OrderDecision(False, side, symbol, quantity, price, None, "order exceeds max order risk gate", now)
    slip = price * (risk.slippage_bps / 10_000)
    fill = price + slip if side == "BUY" else price - slip
    if side == "BUY":
        cost=quantity * fill + risk.commission_per_trade
        if cost > portfolio.cash:
            return OrderDecision(False, side, symbol, quantity, price, None, "insufficient cash", now)
        projected_position_value = position_market_value(portfolio, symbol, prices) + quantity * fill
        if projected_position_value > equity * risk.max_position_pct:
            return OrderDecision(False, side, symbol, quantity, price, None, "position would exceed max position size", now)
        new_qty=pos.quantity + quantity
        pos.avg_price=((pos.quantity*pos.avg_price)+(quantity*fill))/new_qty
        pos.quantity=new_qty
        portfolio.cash -= cost
        portfolio.positions[symbol]=pos
    else:
        proceeds=quantity * fill - risk.commission_per_trade
        pos.quantity -= quantity
        portfolio.cash += proceeds
        if pos.quantity == 0:
            portfolio.positions.pop(symbol, None)
        else:
            portfolio.positions[symbol]=pos
    return OrderDecision(True, side, symbol, quantity, price, fill, "accepted by mock broker", now)

def place_mock_order(side: Side, symbol: str, quantity: int, price: float, prices: dict[str, float], portfolio_path: Path = STATE_PATH, ledger_path: Path = LEDGER_PATH) -> OrderDecision:
    with _portfolio_lock(portfolio_path):
        portfolio=load_portfolio(portfolio_path)
        decision=evaluate_order(portfolio, side, symbol, quantity, price, prices)
        append_ledger(decision, ledger_path)
        if decision.accepted:
            save_portfolio(portfolio, portfolio_path)
        return decision
