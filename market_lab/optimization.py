from __future__ import annotations

from dataclasses import dataclass
from inspect import signature
from itertools import product
from typing import Any, Callable, Mapping

from .data import Bar

BacktestFunction = Callable[..., Any]


@dataclass(frozen=True)
class SweepResult:
    params: dict[str, Any]
    metrics: dict[str, float]


@dataclass(frozen=True)
class WalkForwardResult:
    best_params: dict[str, Any]
    train_metrics: dict[str, float]
    oos_metrics: dict[str, float]
    train_bars: int
    oos_bars: int
    metric: str


def _metric_dict(result: Any) -> dict[str, float]:
    if isinstance(result, Mapping):
        source = result
    elif hasattr(result, "__dataclass_fields__"):
        source = {name: getattr(result, name) for name in result.__dataclass_fields__}
    else:
        source = vars(result)

    metrics: dict[str, float] = {}
    for key, value in source.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            metrics[key] = float(value)
    return metrics


def _param_combinations(param_grid: Mapping[str, list[Any] | tuple[Any, ...]]) -> list[dict[str, Any]]:
    keys = list(param_grid.keys())
    values = [list(param_grid[key]) for key in keys]
    if not keys:
        return [{}]
    return [dict(zip(keys, combo)) for combo in product(*values)]


def _run(backtest_func: BacktestFunction, symbol: str, bars: list[Bar], params: dict[str, Any], **extra_kwargs: Any) -> dict[str, float]:
    call_kwargs = dict(params)
    accepted = set(signature(backtest_func).parameters)
    for key, value in extra_kwargs.items():
        if key in accepted:
            call_kwargs[key] = value
    return _metric_dict(backtest_func(symbol, bars, **call_kwargs))


def param_sweep(
    symbol: str,
    bars: list[Bar],
    backtest_func: BacktestFunction,
    param_grid: Mapping[str, list[Any] | tuple[Any, ...]],
    metric: str = "sharpe",
) -> list[SweepResult]:
    """Run a deterministic parameter grid and rank by the requested metric.

    This is intentionally small and auditable. It does not pick production params by itself;
    use walk-forward optimization before promoting any strategy into mock queueing.
    """
    results: list[SweepResult] = []
    for params in _param_combinations(param_grid):
        metrics = _run(backtest_func, symbol, bars, params)
        results.append(SweepResult(params=params, metrics=metrics))
    return sorted(results, key=lambda result: result.metrics.get(metric, float("-inf")), reverse=True)


def walk_forward_optimize(
    symbol: str,
    bars: list[Bar],
    backtest_func: BacktestFunction,
    param_grid: Mapping[str, list[Any] | tuple[Any, ...]],
    metric: str = "sharpe",
    train_pct: float = 0.70,
) -> WalkForwardResult:
    """Pick parameters on an in-sample window, then report holdout metrics only OOS.

    The selected parameters come from train bars only. The out-of-sample metrics are
    computed on the holdout slice and kept separate to reduce full-history overfit.
    """
    if not 0 < train_pct < 1:
        raise ValueError("train_pct must be between 0 and 1")
    if len(bars) < 4:
        raise ValueError("walk-forward optimization requires at least 4 bars")

    train_n = max(2, min(len(bars) - 2, int(len(bars) * train_pct)))
    train_bars = bars[:train_n]
    oos_bars = bars[train_n:]
    if len(oos_bars) < 2:
        raise ValueError("out-of-sample window must contain at least 2 bars")

    ranked = param_sweep(symbol, train_bars, backtest_func, param_grid, metric=metric)
    if not ranked:
        raise ValueError("param_grid produced no parameter combinations")
    winner = ranked[0]
    oos_context_bars = train_bars + oos_bars
    if "evaluation_start_index" in signature(backtest_func).parameters:
        oos_metrics = _run(backtest_func, symbol, oos_context_bars, winner.params, evaluation_start_index=len(train_bars))
    else:
        oos_metrics = _run(backtest_func, symbol, oos_bars, winner.params)
    return WalkForwardResult(
        best_params=winner.params,
        train_metrics=winner.metrics,
        oos_metrics=oos_metrics,
        train_bars=len(train_bars),
        oos_bars=len(oos_bars),
        metric=metric,
    )
