from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev
from typing import Callable

from .data import Bar
from .indicators import max_drawdown, sma
from .signals import Signal

SignalFunction = Callable[[str, list[Bar]], Signal]


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    trades: int
    total_return: float
    benchmark_return: float
    max_drawdown: float
    sharpe: float
    final_equity: float
    strategy: str = "ma_cross"


@dataclass(frozen=True)
class ExecutionModel:
    slippage_bps: float = 5.0
    commission_per_trade: float = 1.0

    def fill_price(self, side: str, open_price: float) -> float:
        slip = open_price * (self.slippage_bps / 10_000)
        return open_price + slip if side == "BUY" else open_price - slip


def _stats(symbol: str, strategy: str, bars: list[Bar], equity_curve: list[float], trades: int, initial_cash: float, benchmark_start_index: int, benchmark_base_price: float | None = None) -> BacktestResult:
    final_equity = equity_curve[-1] if equity_curve else initial_cash
    if initial_cash <= 0:
        total_return = 0.0
    else:
        total_return = final_equity / initial_cash - 1
    benchmark_base = benchmark_base_price if benchmark_base_price and benchmark_base_price > 0 else bars[benchmark_start_index].close if bars and benchmark_start_index < len(bars) and bars[benchmark_start_index].close > 0 else bars[0].close if bars else 1.0
    benchmark_return = bars[-1].close / benchmark_base - 1 if bars and benchmark_base > 0 else 0.0
    rets = [equity_curve[i] / equity_curve[i - 1] - 1 for i in range(1, len(equity_curve)) if equity_curve[i - 1] > 0]
    sharpe = (mean(rets) / pstdev(rets) * sqrt(252)) if len(rets) > 2 and pstdev(rets) > 0 else 0.0
    return BacktestResult(symbol, trades, total_return, benchmark_return, max_drawdown(equity_curve), sharpe, final_equity, strategy)


def _windowed_stats(
    symbol: str,
    strategy: str,
    bars: list[Bar],
    equity_points: list[tuple[int, float]],
    trades: int,
    initial_cash: float,
    benchmark_start_index: int,
    evaluation_start_index: int | None,
) -> BacktestResult:
    if evaluation_start_index is None:
        equity_curve = [equity for _, equity in equity_points]
        return _stats(symbol, strategy, bars, equity_curve, trades, initial_cash, benchmark_start_index)

    eval_points = [(idx, equity) for idx, equity in equity_points if idx >= evaluation_start_index]
    if not eval_points:
        return BacktestResult(symbol, 0, 0.0, 0.0, 0.0, 0.0, initial_cash, strategy)
    eval_start_idx = eval_points[0][0]
    eval_equity_curve = [equity for _, equity in eval_points]
    eval_initial = eval_equity_curve[0]
    benchmark_base_price = bars[eval_start_idx].open if 0 <= eval_start_idx < len(bars) else None
    return _stats(symbol, strategy, bars, eval_equity_curve, trades, eval_initial, eval_start_idx, benchmark_base_price)


def run_signal_backtest(
    symbol: str,
    bars: list[Bar],
    signal_func: SignalFunction,
    min_history: int = 120,
    initial_cash: float = 10_000.0,
    execution: ExecutionModel | None = None,
    evaluation_start_index: int | None = None,
) -> BacktestResult:
    """Generic long-only signal backtest.

    Decision uses bars through close of day t. Fill occurs at next bar open t+1.
    If evaluation_start_index is provided, earlier bars are warm-up context and metrics
    are reported only from that index forward.
    """
    execution = execution or ExecutionModel()
    strategy_name = getattr(signal_func, "__name__", "signal").replace("generate_", "").replace("_signal", "")
    if len(bars) < min_history + 2:
        return BacktestResult(symbol, 0, 0.0, 0.0, 0.0, 0.0, initial_cash, strategy_name)
    cash = initial_cash
    qty = 0.0
    trades = 0
    equity_points: list[tuple[int, float]] = []
    pending: str | None = None
    for i in range(min_history, len(bars) - 1):
        if evaluation_start_index is not None and i < evaluation_start_index - 1:
            equity_points.append((i, cash + qty * bars[i].close))
            pending = None
            continue
        if evaluation_start_index is not None and i == evaluation_start_index:
            equity_points.append((i, cash + qty * bars[i].open))
        if pending:
            px = execution.fill_price(pending, bars[i].open)
            if pending == "BUY" and qty == 0 and cash > execution.commission_per_trade:
                qty = max(0.0, (cash - execution.commission_per_trade) / px)
                cash = 0.0
                if evaluation_start_index is None or i >= evaluation_start_index:
                    trades += 1
            elif pending == "SELL" and qty > 0:
                cash = qty * px - execution.commission_per_trade
                qty = 0.0
                if evaluation_start_index is None or i >= evaluation_start_index:
                    trades += 1
            pending = None
        equity_points.append((i, cash + qty * bars[i].close))
        sig = signal_func(symbol, bars[: i + 1])
        if sig.action == "BUY" and qty == 0:
            pending = "BUY"
        elif sig.action == "SELL" and qty > 0:
            pending = "SELL"
    final_equity = cash + qty * bars[-1].close
    equity_points.append((len(bars) - 1, final_equity))
    return _windowed_stats(symbol, strategy_name, bars, equity_points, trades, initial_cash, min_history, evaluation_start_index)


def moving_average_cross_backtest(
    symbol: str,
    bars: list[Bar],
    fast: int = 20,
    slow: int = 50,
    initial_cash: float = 10_000.0,
    fee_bps: float = 5.0,
    evaluation_start_index: int | None = None,
) -> BacktestResult:
    if len(bars) < slow + 2:
        return BacktestResult(symbol, 0, 0.0, 0.0, 0.0, 0.0, initial_cash)
    closes = [b.close for b in bars]
    fasts = sma(closes, fast)
    slows = sma(closes, slow)
    cash = initial_cash
    qty = 0.0
    trades = 0
    equity_points: list[tuple[int, float]] = []
    pending = None
    execution = ExecutionModel(slippage_bps=fee_bps, commission_per_trade=0.0)
    for i in range(slow, len(bars) - 1):
        if evaluation_start_index is not None and i < evaluation_start_index - 1:
            equity_points.append((i, cash + qty * bars[i].close))
            pending = None
            continue
        if evaluation_start_index is not None and i == evaluation_start_index:
            equity_points.append((i, cash + qty * bars[i].open))
        if pending:
            px = execution.fill_price(pending, bars[i].open)
            if pending == "BUY" and qty == 0 and cash > 0:
                qty = cash / px
                cash = 0.0
                if evaluation_start_index is None or i >= evaluation_start_index:
                    trades += 1
            elif pending == "SELL" and qty > 0:
                cash = qty * px
                qty = 0.0
                if evaluation_start_index is None or i >= evaluation_start_index:
                    trades += 1
            pending = None
        equity_points.append((i, cash + qty * bars[i].close))
        if fasts[i] is None or slows[i] is None or fasts[i - 1] is None or slows[i - 1] is None:
            continue
        crossed_up = fasts[i - 1] <= slows[i - 1] and fasts[i] > slows[i]
        crossed_down = fasts[i - 1] >= slows[i - 1] and fasts[i] < slows[i]
        if crossed_up:
            pending = "BUY"
        elif crossed_down:
            pending = "SELL"
    final_equity = cash + qty * bars[-1].close
    equity_points.append((len(bars) - 1, final_equity))
    return _windowed_stats(symbol, "ma_cross", bars, equity_points, trades, initial_cash, slow, evaluation_start_index)
