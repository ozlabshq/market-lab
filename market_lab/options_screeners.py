from __future__ import annotations

from dataclasses import dataclass

from .broker import Portfolio
from .config import OptionsRiskConfig, OPTIONS_RISK
from .options_data import OptionChainSnapshot, OptionContract


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


def _liquid(contract: OptionContract, risk: OptionsRiskConfig) -> bool:
    q = contract.quote
    return q.bid > 0 and q.ask >= q.bid and q.spread_pct <= risk.max_bid_ask_spread_pct and q.open_interest >= risk.min_open_interest and q.volume >= risk.min_volume


def _dte_ok(snapshot: OptionChainSnapshot, contract: OptionContract, risk: OptionsRiskConfig) -> bool:
    dte = contract.dte(snapshot.as_of)
    return risk.min_dte <= dte <= risk.max_dte


def screen_covered_calls(snapshot: OptionChainSnapshot, portfolio: Portfolio, risk: OptionsRiskConfig = OPTIONS_RISK) -> list[CoveredCallCandidate]:
    if not risk.paper_options_enabled:
        return []
    shares = portfolio.positions.get(snapshot.underlying.upper())
    available_contracts = (shares.quantity // 100) if shares else 0
    if available_contracts <= 0:
        return []
    out: list[CoveredCallCandidate] = []
    for c in snapshot.contracts:
        if c.option_type != "CALL" or c.strike <= snapshot.underlying_price:
            continue
        if not _dte_ok(snapshot, c, risk) or not _liquid(c, risk):
            continue
        if abs(c.greeks.delta) > risk.max_abs_short_call_delta:
            continue
        dte = max(c.dte(snapshot.as_of), 1)
        premium = c.quote.mid * 100
        annualized = premium / max(snapshot.underlying_price * 100, 1) * (365 / dte)
        if annualized < risk.min_premium_yield_annualized:
            continue
        contracts = min(available_contracts, risk.max_contracts_per_symbol)
        out.append(CoveredCallCandidate(c, contracts, premium * contracts, annualized, c.strike / snapshot.underlying_price - 1, "covered call: shares available, liquid, defined assignment risk"))
    return sorted(out, key=lambda x: (x.annualized_yield, x.contract.quote.open_interest), reverse=True)


def screen_cash_secured_puts(snapshot: OptionChainSnapshot, portfolio: Portfolio, risk: OptionsRiskConfig = OPTIONS_RISK) -> list[CashSecuredPutCandidate]:
    if not risk.paper_options_enabled:
        return []
    out: list[CashSecuredPutCandidate] = []
    for c in snapshot.contracts:
        if c.option_type != "PUT" or c.strike >= snapshot.underlying_price:
            continue
        if not _dte_ok(snapshot, c, risk) or not _liquid(c, risk):
            continue
        if abs(c.greeks.delta) > risk.max_abs_short_put_delta:
            continue
        cash_reserved = c.strike * 100
        if cash_reserved > portfolio.cash or cash_reserved > portfolio.equity({snapshot.underlying: snapshot.underlying_price}) * risk.max_assignment_notional_pct:
            continue
        dte = max(c.dte(snapshot.as_of), 1)
        premium = c.quote.mid * 100
        annualized = premium / max(cash_reserved, 1) * (365 / dte)
        if annualized < risk.min_premium_yield_annualized:
            continue
        contracts = min(int(portfolio.cash // cash_reserved), risk.max_contracts_per_symbol)
        if contracts <= 0:
            continue
        out.append(CashSecuredPutCandidate(c, contracts, cash_reserved * contracts, premium * contracts, annualized, 1 - c.strike / snapshot.underlying_price, "cash-secured put: full cash reserve, liquid, defined assignment risk"))
    return sorted(out, key=lambda x: (x.annualized_yield, x.contract.quote.open_interest), reverse=True)
