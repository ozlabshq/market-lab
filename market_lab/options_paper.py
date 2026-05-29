from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .broker import Portfolio
from .config import OPTIONS_PAPER_LEDGER_PATH, OPTIONS_PAPER_STATE_PATH, OptionsRiskConfig, OPTIONS_RISK, ensure_dirs
from .options_data import OptionContract

OptionAction = Literal["BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_CLOSE"]


@dataclass(frozen=True)
class OptionPaperOrder:
    action: OptionAction
    contract: OptionContract
    contracts: int
    price: float
    strategy: str


@dataclass(frozen=True)
class OptionPaperDecision:
    accepted: bool
    action: OptionAction
    contract_id: str
    contracts: int
    price: float
    premium: float
    reason: str
    timestamp: str
    strategy: str


@dataclass
class OptionPaperPortfolio:
    cash: float = 100_000.0
    positions: dict[str, int] = field(default_factory=dict)
    avg_price: dict[str, float] = field(default_factory=dict)
    reserved_cash: float = 0.0
    reserved_shares: dict[str, int] = field(default_factory=dict)

    @property
    def available_cash(self) -> float:
        return self.cash - self.reserved_cash


def _reject(order: OptionPaperOrder, reason: str) -> OptionPaperDecision:
    return OptionPaperDecision(False, order.action, order.contract.contract_id, order.contracts, order.price, 0.0, reason, datetime.now(timezone.utc).isoformat(), order.strategy)


def _accept(order: OptionPaperOrder, premium: float, reason: str) -> OptionPaperDecision:
    return OptionPaperDecision(True, order.action, order.contract.contract_id, order.contracts, order.price, premium, reason, datetime.now(timezone.utc).isoformat(), order.strategy)


def evaluate_option_paper_order(paper: OptionPaperPortfolio, equity_portfolio: Portfolio, order: OptionPaperOrder, risk: OptionsRiskConfig = OPTIONS_RISK) -> OptionPaperDecision:
    if not risk.paper_options_enabled or risk.live_options_enabled:
        return _reject(order, "paper options are disabled or live options unexpectedly enabled")
    if order.contracts <= 0 or order.price <= 0:
        return _reject(order, "contracts and price must be positive")
    if order.contracts > risk.max_contracts_per_symbol:
        return _reject(order, "contract count exceeds per-symbol gate")
    contract = order.contract
    premium = order.price * 100 * order.contracts
    cid = contract.contract_id

    if order.action == "BUY_TO_OPEN":
        if premium > paper.available_cash:
            return _reject(order, "insufficient available cash for long option premium")
        paper.cash -= premium
        paper.positions[cid] = paper.positions.get(cid, 0) + order.contracts
        paper.avg_price[cid] = order.price
        return _accept(order, premium, "accepted paper long option; max loss limited to premium")

    if order.action == "SELL_TO_OPEN":
        if contract.option_type == "CALL":
            if risk.allow_naked_calls:
                return _reject(order, "naked calls remain blocked in paper gate")
            owned = equity_portfolio.positions.get(contract.underlying.upper())
            owned_shares = owned.quantity if owned else 0
            already_reserved = paper.reserved_shares.get(contract.underlying.upper(), 0)
            required = 100 * order.contracts
            if owned_shares - already_reserved < required:
                return _reject(order, "covered shares unavailable; naked calls blocked")
            paper.reserved_shares[contract.underlying.upper()] = already_reserved + required
        else:
            reserve = contract.strike * 100 * order.contracts
            if reserve > paper.available_cash:
                return _reject(order, "insufficient available cash for reserved cash-secured put")
            projected_reserved = paper.reserved_cash + reserve
            assignment_base = max(equity_portfolio.equity({contract.underlying: contract.strike}), paper.cash, 1.0)
            if projected_reserved > assignment_base * risk.max_total_options_assignment_pct:
                return _reject(order, "total options assignment reserve exceeds portfolio gate")
            paper.reserved_cash = projected_reserved
        paper.cash += premium
        paper.positions[cid] = paper.positions.get(cid, 0) - order.contracts
        paper.avg_price[cid] = order.price
        return _accept(order, premium, "accepted defined-risk paper short option with collateral reserved")

    current = paper.positions.get(cid, 0)
    if order.action == "SELL_TO_CLOSE":
        if current < order.contracts:
            return _reject(order, "cannot sell to close more long contracts than held")
        paper.cash += premium
        paper.positions[cid] = current - order.contracts
        if paper.positions[cid] == 0:
            paper.positions.pop(cid, None)
        return _accept(order, premium, "accepted paper close of long option")

    if order.action == "BUY_TO_CLOSE":
        if current > -order.contracts:
            return _reject(order, "cannot buy to close more short contracts than open")
        if contract.option_type == "CALL":
            collateral_release = 100 * order.contracts
            cash_available_for_close = paper.available_cash
        else:
            collateral_release = contract.strike * 100 * order.contracts
            cash_available_for_close = paper.available_cash + collateral_release
        if premium > cash_available_for_close:
            return _reject(order, "insufficient cash to buy short option closed")
        paper.cash -= premium
        paper.positions[cid] = current + order.contracts
        if contract.option_type == "CALL":
            paper.reserved_shares[contract.underlying.upper()] = max(0, paper.reserved_shares.get(contract.underlying.upper(), 0) - 100 * order.contracts)
        else:
            paper.reserved_cash = max(0.0, paper.reserved_cash - contract.strike * 100 * order.contracts)
        if paper.positions[cid] == 0:
            paper.positions.pop(cid, None)
        return _accept(order, premium, "accepted paper close of short option")

    return _reject(order, "unsupported paper option action")


def save_option_paper_portfolio(portfolio: OptionPaperPortfolio, path: Path = OPTIONS_PAPER_STATE_PATH) -> None:
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(portfolio), indent=2, sort_keys=True))


def load_option_paper_portfolio(path: Path = OPTIONS_PAPER_STATE_PATH) -> OptionPaperPortfolio:
    if not path.exists():
        return OptionPaperPortfolio()
    try:
        data = json.loads(path.read_text())
        return OptionPaperPortfolio(
            cash=float(data.get("cash", 100_000.0)),
            positions={k: int(v) for k, v in data.get("positions", {}).items()},
            avg_price={k: float(v) for k, v in data.get("avg_price", {}).items()},
            reserved_cash=float(data.get("reserved_cash", 0.0)),
            reserved_shares={k: int(v) for k, v in data.get("reserved_shares", {}).items()},
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return OptionPaperPortfolio()


def append_option_paper_ledger(decision: OptionPaperDecision, path: Path = OPTIONS_PAPER_LEDGER_PATH) -> None:
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(decision), sort_keys=True) + "\n")
