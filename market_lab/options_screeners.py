from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .broker import Portfolio
from .config import OptionsRiskConfig, OPTIONS_RISK
from .options_data import OptionChainSnapshot, OptionContract
from .options_paper import OptionPaperPortfolio


@dataclass(frozen=True)
class CoveredCallCandidate:
    contract: OptionContract
    contracts: int
    premium: float
    annualized_yield: float
    otm_pct: float
    reason: str


@dataclass(frozen=True)
class CashSecuredPutCandidate:
    contract: OptionContract
    contracts: int
    cash_reserved: float
    premium: float
    annualized_yield: float
    otm_pct: float
    reason: str


def _as_date(value: str | date | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if "T" in value else date.fromisoformat(value)


def _chain_fresh(snapshot: OptionChainSnapshot, risk: OptionsRiskConfig, as_of: str | date | None = None) -> bool:
    today = _as_date(as_of)
    snapshot_date = _as_date(snapshot.as_of)
    age_days = (today - snapshot_date).days
    return -1 <= age_days <= risk.max_chain_age_days


def _liquid(contract: OptionContract, risk: OptionsRiskConfig) -> bool:
    q = contract.quote
    return q.bid > 0 and q.ask >= q.bid and q.spread_pct <= risk.max_bid_ask_spread_pct and q.open_interest >= risk.min_open_interest and q.volume >= risk.min_volume


def _dte_ok(snapshot: OptionChainSnapshot, contract: OptionContract, risk: OptionsRiskConfig, as_of: str | date | None = None) -> bool:
    dte = contract.dte(_as_date(as_of).isoformat())
    return risk.min_dte <= dte <= risk.max_dte


def screen_covered_calls(snapshot: OptionChainSnapshot, portfolio: Portfolio, risk: OptionsRiskConfig = OPTIONS_RISK, as_of: str | date | None = None, paper: OptionPaperPortfolio | None = None) -> list[CoveredCallCandidate]:
    if not risk.allow_options or not risk.paper_options_enabled or risk.live_options_enabled or not _chain_fresh(snapshot, risk, as_of):
        return []
    shares = portfolio.positions.get(snapshot.underlying.upper())
    reserved_shares = paper.reserved_shares.get(snapshot.underlying.upper(), 0) if paper else 0
    available_contracts = max(((shares.quantity - reserved_shares) // 100) if shares else 0, 0)
    if available_contracts <= 0:
        return []
    out: list[CoveredCallCandidate] = []
    for c in snapshot.contracts:
        if c.option_type != "CALL" or c.strike <= snapshot.underlying_price:
            continue
        if not _dte_ok(snapshot, c, risk, as_of) or not _liquid(c, risk):
            continue
        if abs(c.greeks.delta) > risk.max_abs_short_call_delta:
            continue
        dte = max(c.dte(_as_date(as_of).isoformat()), 1)
        premium = c.quote.mid * 100
        annualized = premium / max(snapshot.underlying_price * 100, 1) * (365 / dte)
        if annualized < risk.min_premium_yield_annualized:
            continue
        contracts = min(available_contracts, risk.max_contracts_per_symbol)
        out.append(CoveredCallCandidate(c, contracts, premium * contracts, annualized, c.strike / snapshot.underlying_price - 1, "covered call: shares available, liquid, defined assignment risk"))
    return sorted(out, key=lambda x: (x.annualized_yield, x.contract.quote.open_interest), reverse=True)


def screen_cash_secured_puts(snapshot: OptionChainSnapshot, portfolio: Portfolio, risk: OptionsRiskConfig = OPTIONS_RISK, as_of: str | date | None = None, paper: OptionPaperPortfolio | None = None) -> list[CashSecuredPutCandidate]:
    if not risk.allow_options or not risk.paper_options_enabled or risk.live_options_enabled or not _chain_fresh(snapshot, risk, as_of):
        return []
    out: list[CashSecuredPutCandidate] = []
    for c in snapshot.contracts:
        if c.option_type != "PUT" or c.strike >= snapshot.underlying_price:
            continue
        if not _dte_ok(snapshot, c, risk, as_of) or not _liquid(c, risk):
            continue
        if abs(c.greeks.delta) > risk.max_abs_short_put_delta:
            continue
        cash_reserved = c.strike * 100
        dte = max(c.dte(_as_date(as_of).isoformat()), 1)
        premium = c.quote.mid * 100
        annualized = premium / max(cash_reserved, 1) * (365 / dte)
        if annualized < risk.min_premium_yield_annualized:
            continue
        reserved_cash = paper.reserved_cash if paper else 0.0
        available_cash = max(portfolio.cash - reserved_cash, 0.0)
        equity = portfolio.equity({snapshot.underlying: snapshot.underlying_price})
        max_assignment = equity * risk.max_assignment_notional_pct
        max_total_assignment = max(equity * risk.max_total_options_assignment_pct - reserved_cash, 0.0)
        max_contracts_by_assignment = int(min(max_assignment, max_total_assignment) // cash_reserved)
        max_contracts_by_cash = int(available_cash // cash_reserved)
        contracts = min(max_contracts_by_cash, max_contracts_by_assignment, risk.max_contracts_per_symbol)
        if contracts <= 0:
            continue
        total_reserved = cash_reserved * contracts
        out.append(CashSecuredPutCandidate(c, contracts, total_reserved, premium * contracts, annualized, 1 - c.strike / snapshot.underlying_price, "cash-secured put: full cash reserve, liquid, defined assignment risk"))
    return sorted(out, key=lambda x: (x.annualized_yield, x.contract.quote.open_interest), reverse=True)
