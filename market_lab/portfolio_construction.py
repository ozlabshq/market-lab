from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev

from .data import Bar
from .indicators import max_drawdown


@dataclass(frozen=True)
class MomentumTarget:
    symbol: str
    rank: int
    relative_score: float
    absolute_momentum: float
    target_weight: float
    reason: str


@dataclass(frozen=True)
class RebalanceSnapshot:
    decision_index: int
    fill_index: int
    targets: list[MomentumTarget]
    fill_prices: dict[str, float]
    equity_before: float
    equity_after: float


@dataclass(frozen=True)
class DualMomentumBacktestResult:
    total_return: float
    benchmark_return: float
    max_drawdown: float
    sharpe: float
    final_equity: float
    rebalances: int
    snapshots: list[RebalanceSnapshot]
    strategy: str = "dual_momentum"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _price_at_or_before(bars: list[Bar], idx: int) -> float:
    if not bars:
        return 0.0
    return bars[max(0, min(idx, len(bars) - 1))].close


def _momentum(bars: list[Bar], decision_index: int, formation_days: int, skip_days: int) -> float | None:
    end_idx = decision_index - skip_days
    return _return_between(bars, end_idx - formation_days, end_idx)


def _return_between(bars: list[Bar], start_idx: int, end_idx: int) -> float | None:
    if start_idx < 0 or end_idx >= len(bars):
        return None
    start = bars[start_idx].close
    end = bars[end_idx].close
    if start <= 0:
        return None
    return end / start - 1.0


def dual_momentum_targets(
    bars_by_symbol: dict[str, list[Bar]],
    formation_days: int = 252,
    skip_days: int = 21,
    top_n: int = 3,
    absolute_threshold: float = 0.0,
    max_weight: float = 0.20,
    decision_index: int | None = None,
) -> list[MomentumTarget]:
    """Select relative winners that also pass an absolute momentum filter.

    This is an auditable dual-momentum primitive: rank by formation return, reject
    symbols below the absolute threshold, then assign equal target weights capped per symbol.
    Execution is handled separately by the backtest/mock broker at the next open.
    """
    if formation_days <= 0:
        raise ValueError("formation_days must be positive")
    if skip_days < 0:
        raise ValueError("skip_days must be non-negative")
    if top_n <= 0:
        return []

    scores: list[tuple[str, float, float]] = []
    for symbol, bars in bars_by_symbol.items():
        if not bars:
            continue
        if decision_index is None:
            idx = len(bars) - 1
        elif decision_index >= len(bars):
            continue
        else:
            idx = decision_index
        relative_score = _momentum(bars, idx, formation_days, skip_days)
        absolute_momentum = _return_between(bars, idx - formation_days, idx)
        if relative_score is None or absolute_momentum is None:
            continue
        scores.append((symbol.upper(), relative_score, absolute_momentum))

    scores.sort(key=lambda item: item[1], reverse=True)
    selected = [(symbol, relative_score, absolute_momentum) for symbol, relative_score, absolute_momentum in scores if absolute_momentum > absolute_threshold][:top_n]
    if not selected:
        return []

    equal_weight = min(max_weight, 1.0 / len(selected))
    return [
        MomentumTarget(
            symbol=symbol,
            rank=rank,
            relative_score=relative_score,
            absolute_momentum=absolute_momentum,
            target_weight=equal_weight,
            reason=f"dual momentum rank {rank}: relative {relative_score:.1%}; absolute {absolute_momentum:.1%} > {absolute_threshold:.1%} filter",
        )
        for rank, (symbol, relative_score, absolute_momentum) in enumerate(selected, start=1)
    ]


def _portfolio_value(cash: float, positions: dict[str, float], bars_by_symbol: dict[str, list[Bar]], idx: int, use_open: bool = False) -> float:
    total = cash
    for symbol, qty in positions.items():
        bars = bars_by_symbol.get(symbol, [])
        if not bars:
            continue
        bar = bars[max(0, min(idx, len(bars) - 1))]
        total += qty * (bar.open if use_open else bar.close)
    return total


def _align_on_common_dates(bars_by_symbol: dict[str, list[Bar]]) -> dict[str, list[Bar]]:
    dated = {symbol.upper(): {bar.date: bar for bar in bars} for symbol, bars in bars_by_symbol.items() if bars}
    if not dated:
        return {}
    common_dates = set.intersection(*(set(by_date) for by_date in dated.values()))
    if not common_dates:
        return {}
    ordered_dates = sorted(common_dates)
    return {symbol: [by_date[d] for d in ordered_dates] for symbol, by_date in dated.items()}


def _stats(equity_curve: list[float]) -> tuple[float, float, float]:
    rets = [equity_curve[i] / equity_curve[i - 1] - 1 for i in range(1, len(equity_curve)) if equity_curve[i - 1] > 0]
    sharpe = (mean(rets) / pstdev(rets) * sqrt(252)) if len(rets) > 2 and pstdev(rets) > 0 else 0.0
    mdd = max_drawdown(equity_curve)
    total_return = equity_curve[-1] / equity_curve[0] - 1 if equity_curve and equity_curve[0] > 0 else 0.0
    return total_return, mdd, sharpe


def run_dual_momentum_backtest(
    bars_by_symbol: dict[str, list[Bar]],
    formation_days: int = 252,
    skip_days: int = 21,
    top_n: int = 3,
    rebalance_every: int = 21,
    start_index: int | None = None,
    initial_cash: float = 10_000.0,
    max_weight: float = 0.20,
    absolute_threshold: float = 0.0,
) -> DualMomentumBacktestResult:
    if rebalance_every <= 0:
        raise ValueError("rebalance_every must be positive")
    if not bars_by_symbol:
        return DualMomentumBacktestResult(0.0, 0.0, 0.0, 0.0, initial_cash, 0, [])

    normalized_bars_by_symbol = _align_on_common_dates(bars_by_symbol)
    if not normalized_bars_by_symbol:
        return DualMomentumBacktestResult(0.0, 0.0, 0.0, 0.0, initial_cash, 0, [])

    min_len = min(len(bars) for bars in normalized_bars_by_symbol.values())
    if min_len < formation_days + skip_days + 2:
        return DualMomentumBacktestResult(0.0, 0.0, 0.0, 0.0, initial_cash, 0, [])
    start = start_index if start_index is not None else formation_days + skip_days
    start = max(start, formation_days + skip_days)
    end = min_len - 1
    if start >= end:
        return DualMomentumBacktestResult(0.0, 0.0, 0.0, 0.0, initial_cash, 0, [])

    cash = initial_cash
    positions: dict[str, float] = {}
    equity_curve: list[float] = [initial_cash]
    snapshots: list[RebalanceSnapshot] = []

    for idx in range(start, end):
        if (idx - start) % rebalance_every == 0 and idx + 1 < min_len:
            equity_before = _portfolio_value(cash, positions, normalized_bars_by_symbol, idx)
            targets = dual_momentum_targets(
                normalized_bars_by_symbol,
                formation_days=formation_days,
                skip_days=skip_days,
                top_n=top_n,
                absolute_threshold=absolute_threshold,
                max_weight=max_weight,
                decision_index=idx,
            )
            fill_idx = idx + 1
            fill_prices = {target.symbol: normalized_bars_by_symbol[target.symbol][fill_idx].open for target in targets}
            equity_at_fill = _portfolio_value(cash, positions, normalized_bars_by_symbol, fill_idx, use_open=True)
            new_positions: dict[str, float] = {}
            invested = 0.0
            for target in targets:
                px = fill_prices[target.symbol]
                allocation = equity_at_fill * _clamp(target.target_weight, 0.0, max_weight)
                if px > 0 and allocation > 0:
                    new_positions[target.symbol] = allocation / px
                    invested += allocation
            cash = max(0.0, equity_at_fill - invested)
            positions = new_positions
            snapshots.append(RebalanceSnapshot(idx, fill_idx, targets, fill_prices, equity_before, _portfolio_value(cash, positions, normalized_bars_by_symbol, fill_idx)))
        equity_curve.append(_portfolio_value(cash, positions, normalized_bars_by_symbol, idx + 1))

    final_equity = equity_curve[-1]
    total_return, mdd, sharpe = _stats(equity_curve)
    first_symbol = sorted(normalized_bars_by_symbol)[0]
    benchmark_start = _price_at_or_before(normalized_bars_by_symbol[first_symbol], start)
    benchmark_end = _price_at_or_before(normalized_bars_by_symbol[first_symbol], end)
    benchmark_return = benchmark_end / benchmark_start - 1 if benchmark_start > 0 else 0.0
    return DualMomentumBacktestResult(total_return, benchmark_return, mdd, sharpe, final_equity, len(snapshots), snapshots)
