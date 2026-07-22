from __future__ import annotations

from dataclasses import dataclass
from market_lab.backtest import run_signal_backtest
from market_lab.data import Bar

@dataclass(frozen=True)
class SpyBeatResult:
    passed: bool
    strategy_oos_return: float
    spy_oos_return: float
    train_bars: int
    oos_bars: int
    reason: str

def _spy_oos_return(spy_bars: list[Bar], train_n: int) -> float:
    if train_n >= len(spy_bars):
        return 0.0
    start_price = spy_bars[train_n].open if spy_bars[train_n].open > 0 else spy_bars[train_n].close
    end_price = spy_bars[-1].close
    if start_price <= 0 or end_price <= 0:
        return 0.0
    return end_price / start_price - 1.0

def verify_spy_beat(
    symbol: str,
    bars: list[Bar],
    signal_func,
    spy_bars: list[Bar] | None = None,
    train_pct: float = 0.70,
    min_oos_bars: int = 20,
    min_total_bars: int = 60,
    execution=None,
) -> SpyBeatResult:
    if len(bars) < min_total_bars:
        return SpyBeatResult(True, 0.0, 0.0, len(bars), 0, "insufficient data; verifier passes by default")
    if not spy_bars:
        return SpyBeatResult(True, 0.0, 0.0, len(bars), 0, "no SPY data; verifier passes by default")

    aligned_spy = spy_bars[-len(bars):] if len(spy_bars) >= len(bars) else spy_bars
    train_n = max(min_oos_bars + 2, min(len(bars) - min_oos_bars, int(len(bars) * train_pct)))
    if train_n >= len(aligned_spy) or train_n >= len(bars):
        return SpyBeatResult(True, 0.0, 0.0, len(bars), 0, "insufficient OOS window; verifier passes by default")

    bt_result = run_signal_backtest(symbol, bars, signal_func, evaluation_start_index=train_n, execution=execution)
    strategy_oos_return = bt_result.total_return
    spy_oos_return = _spy_oos_return(aligned_spy, train_n)

    passed = strategy_oos_return > spy_oos_return
    reason = f"OOS strategy {strategy_oos_return:.2%} vs SPY {spy_oos_return:.2%} ({len(bars) - train_n} bars)"
    return SpyBeatResult(passed, strategy_oos_return, spy_oos_return, train_n, len(bars) - train_n, reason)


def apply_verifier_guard(
    candidate,
    symbol_bars: list[Bar] | None,
    signal_func,
    spy_bars: list[Bar] | None = None,
) -> tuple[bool, SpyBeatResult]:
    """Return (allow, result) for a single candidate. SELLs are always allowed."""
    from market_lab.broker import OrderCandidate
    if not candidate or not isinstance(candidate, OrderCandidate):
        return False, SpyBeatResult(True, 0.0, 0.0, 0, 0, "no candidate; skipped")
    if candidate.side != "BUY":
        return True, SpyBeatResult(True, 0.0, 0.0, 0, 0, f"{candidate.side} allowed without verifier")
    if not symbol_bars:
        return True, SpyBeatResult(True, 0.0, 0.0, 0, 0, "no price history; verifier passes by default")
    result = verify_spy_beat(candidate.symbol, symbol_bars, signal_func, spy_bars=spy_bars)
    return result.passed, result

