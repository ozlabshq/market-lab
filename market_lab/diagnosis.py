from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from math import sqrt
from statistics import mean, pstdev

from .broker import OrderDecision
from .data import Bar
from .indicators import sma


@dataclass(frozen=True)
class TradeDiagnosis:
    decision_id: str
    symbol: str
    strategy: str
    side: str
    entry_date: str
    exit_date: str | None
    holding_bars: int
    entry_price: float
    exit_price: float | None
    pnl_pct: float
    pnl_vs_benchmark: float
    regime_label: str
    hypothesis: str
    evidence_snapshot: dict
    failure_mode: str | None
    confidence_at_entry: float
    data_quality: str = "live_or_cache"

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StrategyHealthReport:
    strategy: str
    total_trades: int
    win_rate: float
    avg_pnl: float
    sharpe_of_trades: float
    avg_holding_bars: float
    regime_breakdown: dict[str, dict]
    decay_alert: bool
    recommended_action: str
    top_failure_modes: list[str]

    def as_record(self) -> dict:
        return asdict(self)


def decision_id(decision: OrderDecision) -> str:
    payload = json.dumps(asdict(decision), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def label_regime(bars: list[Bar]) -> str:
    """Label a simple daily-bar regime for post-trade analysis.

    This deliberately uses coarse deterministic labels. It is a feature for agent review
    and health aggregation, not a trading signal by itself.
    """
    if len(bars) < 20:
        return "unknown"
    closes = [bar.close for bar in bars]
    sma50 = sma(closes, min(50, len(closes)))[-1]
    sma100 = sma(closes, min(100, len(closes)))[-1]
    if sma50 is None or sma100 is None:
        return "unknown"
    latest = closes[-1]
    trailing_return = closes[-1] / closes[max(0, len(closes) - 20)] - 1 if closes[max(0, len(closes) - 20)] > 0 else 0.0
    abs_move = abs(trailing_return)
    if latest > sma50 > sma100 and trailing_return > 0:
        return "trending_up"
    if latest < sma50 < sma100 and trailing_return < 0:
        return "trending_down"
    if abs_move < 0.03:
        return "chop"
    return "high_vol_chop"


def _trade_pnl_pct(side: str, entry_price: float, exit_price: float | None) -> float:
    if exit_price is None or entry_price <= 0:
        return 0.0
    if side == "SELL":
        return entry_price / exit_price - 1.0
    return exit_price / entry_price - 1.0


def _failure_mode(side: str, entry_price: float, exit_price: float | None, bars: list[Bar], requested_price: float) -> str | None:
    pnl = _trade_pnl_pct(side, entry_price, exit_price)
    if pnl >= -0.01:
        return None
    if requested_price > 0 and side == "BUY" and entry_price / requested_price - 1.0 > 0.005:
        return "slippage_drag"
    first_five = bars[: min(len(bars), 5)]
    if side == "BUY" and any(bar.close < entry_price * 0.99 for bar in first_five):
        return "whipsaw"
    if side == "SELL" and any(bar.close > entry_price * 1.01 for bar in first_five):
        return "whipsaw"
    if len(bars) >= 40 and label_regime(bars[:20]) != label_regime(bars[-20:]):
        return "regime_shift"
    return "false_positive"


def diagnose_trade(
    decision: OrderDecision,
    bars_after_entry: list[Bar],
    strategy: str = "unknown",
    evidence_snapshot: dict | None = None,
    benchmark_return: float = 0.0,
    hypothesis: str | None = None,
    confidence_at_entry: float = 0.0,
    data_quality: str = "live_or_cache",
) -> TradeDiagnosis:
    if not decision.accepted or decision.fill_price is None:
        raise ValueError("diagnose_trade requires an accepted decision with a fill_price")
    if not bars_after_entry:
        raise ValueError("diagnose_trade requires bars after entry")

    exit_price = bars_after_entry[-1].close
    pnl_pct = _trade_pnl_pct(decision.side, decision.fill_price, exit_price)
    regime = label_regime(bars_after_entry)
    failure = _failure_mode(decision.side, decision.fill_price, exit_price, bars_after_entry, decision.requested_price)
    entry_date = bars_after_entry[0].date.isoformat()
    exit_date = bars_after_entry[-1].date.isoformat() if len(bars_after_entry) > 1 else None
    return TradeDiagnosis(
        decision_id=decision_id(decision),
        symbol=decision.symbol,
        strategy=strategy,
        side=decision.side,
        entry_date=entry_date,
        exit_date=exit_date,
        holding_bars=max(0, len(bars_after_entry) - 1),
        entry_price=decision.fill_price,
        exit_price=exit_price,
        pnl_pct=pnl_pct,
        pnl_vs_benchmark=pnl_pct - benchmark_return,
        regime_label=regime,
        hypothesis=hypothesis or decision.reason,
        evidence_snapshot=evidence_snapshot or {},
        failure_mode=failure,
        confidence_at_entry=confidence_at_entry,
        data_quality=data_quality,
    )


def _sharpe(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    sd = pstdev(values)
    return mean(values) / sd * sqrt(len(values)) if sd > 0 else 0.0


def generate_strategy_health_report(strategy: str, diagnoses: list[TradeDiagnosis]) -> StrategyHealthReport:
    relevant = [d for d in diagnoses if d.strategy == strategy]
    if not relevant:
        return StrategyHealthReport(strategy, 0, 0.0, 0.0, 0.0, 0.0, {}, False, "continue", [])
    pnls = [d.pnl_pct for d in relevant]
    wins = [p for p in pnls if p > 0]
    by_regime: dict[str, list[float]] = defaultdict(list)
    for d in relevant:
        by_regime[d.regime_label].append(d.pnl_pct)
    regime_breakdown = {
        regime: {"trades": len(vals), "avg_pnl": mean(vals), "win_rate": len([v for v in vals if v > 0]) / len(vals)}
        for regime, vals in by_regime.items()
    }
    last_20 = relevant[-20:]
    last_20_pnls = [d.pnl_pct for d in last_20]
    last_20_win_rate = len([p for p in last_20_pnls if p > 0]) / len(last_20_pnls) if last_20_pnls else 0.0
    decay_alert = len(last_20_pnls) >= 20 and last_20_win_rate < 0.40 and mean(last_20_pnls) < 0
    failure_counts = Counter(d.failure_mode for d in relevant if d.failure_mode)
    if decay_alert:
        action = "pause"
    elif mean(pnls) < 0 and len(relevant) >= 10:
        action = "tune"
    else:
        action = "continue"
    return StrategyHealthReport(
        strategy=strategy,
        total_trades=len(relevant),
        win_rate=len(wins) / len(relevant),
        avg_pnl=mean(pnls),
        sharpe_of_trades=_sharpe(pnls),
        avg_holding_bars=mean([d.holding_bars for d in relevant]),
        regime_breakdown=regime_breakdown,
        decay_alert=decay_alert,
        recommended_action=action,
        top_failure_modes=[mode for mode, _count in failure_counts.most_common(3)],
    )
