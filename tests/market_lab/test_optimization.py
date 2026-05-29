import unittest
from datetime import date, timedelta

from market_lab.backtest import ExecutionModel, moving_average_cross_backtest, run_signal_backtest
from market_lab.data import Bar
from market_lab.optimization import param_sweep, walk_forward_optimize
from market_lab.signals import Signal


def bars_from_prices(prices):
    start = date(2024, 1, 1)
    return [
        Bar(start + timedelta(days=i), p, p * 1.01, p * 0.99, p, 1_000_000)
        for i, p in enumerate(prices)
    ]


def threshold_backtest(symbol, bars, threshold=0.0, initial_cash=10_000.0):
    first = bars[0].close
    last = bars[-1].close
    ret = last / first - 1 if first > 0 else 0.0
    # Simple deterministic test double: looser thresholds trade more often but can overfit.
    score = ret - abs(threshold - 0.10)
    return {
        "symbol": symbol,
        "strategy": "threshold_test",
        "total_return": score,
        "sharpe": score * 10,
        "max_drawdown": -0.05,
        "trades": max(1, int(10 * (1 - threshold))),
        "final_equity": initial_cash * (1 + score),
    }


class OptimizationTests(unittest.TestCase):
    def test_param_sweep_ranks_results_by_requested_metric(self):
        bars = bars_from_prices([100 + i for i in range(40)])
        results = param_sweep(
            "SPY",
            bars,
            threshold_backtest,
            {"threshold": [0.0, 0.10, 0.25]},
            metric="sharpe",
        )

        self.assertEqual([r.params["threshold"] for r in results], [0.10, 0.0, 0.25])
        self.assertGreater(results[0].metrics["sharpe"], results[-1].metrics["sharpe"])

    def test_walk_forward_uses_train_winner_then_reports_oos_on_holdout(self):
        train = [100 + i for i in range(60)]
        holdout = [159 - i for i in range(40)]
        bars = bars_from_prices(train + holdout)

        result = walk_forward_optimize(
            "SPY",
            bars,
            threshold_backtest,
            {"threshold": [0.0, 0.10, 0.25]},
            metric="sharpe",
            train_pct=0.60,
        )

        self.assertEqual(result.best_params, {"threshold": 0.10})
        self.assertEqual(result.train_bars, 60)
        self.assertEqual(result.oos_bars, 40)
        self.assertLess(result.oos_metrics["total_return"], 0)
        self.assertNotEqual(result.train_metrics["total_return"], result.oos_metrics["total_return"])
    def test_walk_forward_preserves_warmup_context_for_oos_backtest(self):
        prices = [140 - i * 0.5 for i in range(80)] + [100 + i * 1.5 for i in range(40)]
        bars = bars_from_prices(prices)

        result = walk_forward_optimize(
            "SPY",
            bars,
            moving_average_cross_backtest,
            {"fast": [5], "slow": [50]},
            metric="total_return",
            train_pct=0.67,
        )

        self.assertEqual(result.oos_bars, 40)
        self.assertGreater(result.oos_metrics["trades"], 0)
        self.assertNotEqual(result.oos_metrics["total_return"], 0.0)
    def test_walk_forward_includes_first_oos_bar_return_from_boundary_signal(self):
        prices = [100.0] * 10 + [200.0, 200.0]
        opens = [100.0] * 12
        bars = [
            Bar(date(2024, 1, 1) + timedelta(days=i), opens[i], max(opens[i], prices[i]), min(opens[i], prices[i]), prices[i], 1_000_000)
            for i in range(len(prices))
        ]

        def buy_after_train_close(symbol, history):
            action = "BUY" if len(history) >= 10 else "HOLD"
            return Signal(symbol, action, 1.0, "boundary", history[-1].close, None, None, None, None, "boundary")

        result = run_signal_backtest(
            "SPY",
            bars,
            buy_after_train_close,
            min_history=2,
            initial_cash=10_000.0,
            execution=ExecutionModel(slippage_bps=0, commission_per_trade=0),
            evaluation_start_index=10,
        )

        self.assertEqual(result.trades, 1)
        self.assertAlmostEqual(result.total_return, 1.0)
        self.assertAlmostEqual(result.benchmark_return, 1.0)


if __name__ == "__main__":
    unittest.main()
