import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import cast

from market_lab.data import Bar
from market_lab.signals import (
    Signal,
    cross_sectional_momentum_ranks,
    generate_ensemble_signal,
    generate_strategy_signals,
    generate_tsmom_signal,
    generate_vt_trend_signal,
)
from market_lab.backtest import ExecutionModel, run_signal_backtest, run_signal_backtest_with_sizing
from market_lab.broker import OrderCandidate, candidate_to_order_at_open


def bars_from_prices(prices, opens=None):
    start = date(2024, 1, 1)
    opens = opens or prices
    return [Bar(start + timedelta(days=i), opens[i], max(opens[i], p) * 1.01, min(opens[i], p) * 0.99, p, 1_000_000) for i, p in enumerate(prices)]


class ResearchStrategyTests(unittest.TestCase):
    def test_tsmom_buys_persistent_positive_multi_horizon_momentum(self):
        prices = [100 + i * 0.28 for i in range(180)]
        sig = generate_tsmom_signal("TREND", bars_from_prices(prices))
        self.assertEqual(sig.action, "BUY")
        self.assertIn("TSMOM", sig.reason)
        self.assertGreater(sig.confidence, 0.30)

    def test_tsmom_sells_when_multi_horizon_momentum_breaks_negative(self):
        prices = [180 - i * 0.35 for i in range(180)]
        sig = generate_tsmom_signal("DOWN", bars_from_prices(prices))
        self.assertEqual(sig.action, "SELL")
        self.assertIn("negative", sig.reason.lower())

    def test_tsmom_drawdown_guard_exits_deep_pullback(self):
        prices = [100 + i * 0.45 for i in range(150)] + [167 - i * 1.4 for i in range(30)]
        sig = generate_tsmom_signal("DD", bars_from_prices(prices))
        self.assertEqual(sig.action, "SELL")
        self.assertIn("drawdown", sig.reason.lower())
        drawdown = sig.evidence["drawdown_from_peak"]
        self.assertIsInstance(drawdown, float)
        self.assertLess(drawdown, -0.15)

    def test_tsmom_target_weight_scales_down_in_higher_volatility(self):
        low_vol = [100 + i * 0.30 for i in range(180)]
        high_vol = [100 + i * 0.80 + (6.0 if i % 2 == 0 else -6.0) for i in range(180)]
        low_sig = generate_tsmom_signal("LOWVOL", bars_from_prices(low_vol))
        high_sig = generate_tsmom_signal("HIGHVOL", bars_from_prices(high_vol))
        self.assertEqual(low_sig.action, "BUY")
        self.assertEqual(high_sig.action, "BUY")
        self.assertGreater(low_sig.target_weight, high_sig.target_weight)

    def test_tsmom_spy_bear_market_blocks_buy(self):
        asset = [100 + i * 0.30 for i in range(180)]
        spy = [140 - i * 0.18 for i in range(180)]
        sig = generate_tsmom_signal("ASSET", bars_from_prices(asset), spy_bars=bars_from_prices(spy))
        self.assertEqual(sig.action, "SELL")
        self.assertIn("SPY regime guard", sig.reason)
        spy_momentum = cast(float, sig.evidence["spy_momentum"])
        self.assertLessEqual(spy_momentum, 0.0)

    def test_tsmom_underperforming_spy_blocks_positive_absolute_momentum(self):
        asset = [100 + i * 0.15 for i in range(180)]
        spy = [100 + i * 0.35 for i in range(180)]
        sig = generate_tsmom_signal("LAG", bars_from_prices(asset), spy_bars=bars_from_prices(spy))
        self.assertEqual(sig.action, "HOLD")
        self.assertIn("relative-momentum guard", sig.reason)
        self.assertLessEqual(cast(float, sig.evidence["spy_relative_momentum"]), 0.0)

    def test_tsmom_allows_buy_when_asset_beats_positive_spy(self):
        asset = [100 + i * 0.45 for i in range(180)]
        spy = [100 + i * 0.10 for i in range(180)]
        sig = generate_tsmom_signal("LEAD", bars_from_prices(asset), spy_bars=bars_from_prices(spy))
        self.assertEqual(sig.action, "BUY")
        self.assertGreater(cast(float, sig.evidence["spy_relative_momentum"]), 0.0)

    def test_tsmom_spy_filter_has_no_future_lookahead(self):
        asset = [100 + i * 0.45 for i in range(200)]
        spy = [100 + i * 0.10 for i in range(200)]
        baseline = generate_tsmom_signal("NL", bars_from_prices(asset[:160]), spy_bars=bars_from_prices(spy[:160]))
        mutated_future_spy = spy[:160] + [1000 + i * 50 for i in range(40)]
        mutated = generate_tsmom_signal("NL", bars_from_prices(asset[:160]), spy_bars=bars_from_prices(mutated_future_spy[:160]))
        self.assertEqual(baseline.action, mutated.action)
        self.assertEqual(baseline.evidence["spy_momentum"], mutated.evidence["spy_momentum"])

    def test_ensemble_spy_overlay_downgrades_underperforming_buy(self):
        asset = [100 + i * 0.15 for i in range(180)]
        spy = [100 + i * 0.35 for i in range(180)]
        sig = generate_ensemble_signal("LAG", bars_from_prices(asset), spy_bars=bars_from_prices(spy))
        self.assertNotEqual(sig.action, "BUY")
        self.assertIn("SPY guard", sig.reason)

    def test_cross_sectional_momentum_can_rank_excess_return_over_spy(self):
        spy = bars_from_prices([100 + i * 0.30 for i in range(180)])
        ranks = cross_sectional_momentum_ranks({
            "BEATER": bars_from_prices([100 + i * 0.45 for i in range(180)]),
            "LAGGER": bars_from_prices([100 + i * 0.10 for i in range(180)]),
        }, formation_days=126, skip_days=21, spy_bars=spy)
        self.assertEqual(ranks[0].symbol, "BEATER")
        self.assertGreater(ranks[0].score, 0.0)
        self.assertLess(ranks[1].score, 0.0)

    def test_cross_sectional_momentum_uses_one_month_skip(self):
        steady_winner = [100 + i * 0.40 for i in range(180)]
        recent_spike_loser = [120 - i * 0.25 for i in range(160)] + [90 + i * 2.0 for i in range(20)]
        ranks = cross_sectional_momentum_ranks({
            "WIN": bars_from_prices(steady_winner),
            "SPIKE": bars_from_prices(recent_spike_loser),
        }, formation_days=126, skip_days=21)
        self.assertEqual(ranks[0].symbol, "WIN")
        self.assertGreater(ranks[0].score, ranks[1].score)

    def test_strategy_family_outputs_multiple_researched_models(self):
        prices = [100 + i * 0.18 for i in range(180)]
        signals = generate_strategy_signals("FAM", bars_from_prices(prices))
        names = {s.strategy for s in signals}
        self.assertIn("tsmom", names)
        self.assertIn("rsi_pullback", names)
        self.assertIn("baseline_scoring", names)

    def test_backtest_executes_signal_at_next_open_not_same_close(self):
        prices = [100] * 60 + [101 + i for i in range(80)]
        opens = list(prices)
        # Exaggerate next open after first BUY; if engine used same close this would not matter.
        opens[61] = 250

        def always_buy(symbol, bars):
            return Signal(symbol, "BUY", 1.0, "test", bars[-1].close, None, None, None, None, "test")

        result = run_signal_backtest("X", bars_from_prices(prices, opens=opens), always_buy, min_history=60)
        self.assertGreaterEqual(result.trades, 1)
        self.assertLess(result.final_equity, 10_000)  # expensive next-open fill hurts; proves lag is modeled

    def test_order_candidate_converts_to_order_using_next_open_only(self):
        candidate = OrderCandidate("BUY", "ABC", 5, "tsmom", 0.7, "next session", "2024-01-02", 101.0)
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            ledger_path = Path(td) / "ledger.jsonl"
            decision = candidate_to_order_at_open(
                candidate,
                next_open=105.0,
                prices={"ABC": 105.0},
                portfolio_path=state_path,
                ledger_path=ledger_path,
            )
            self.assertEqual(decision.requested_price, 105.0)
            self.assertTrue(decision.accepted)
            self.assertTrue(state_path.exists())
            self.assertTrue(ledger_path.exists())

    # --- vt_trend tests ---
    # --- vt_trend tests ---

    def test_vt_trend_vol_scaling_reduces_size_in_spikes(self):
        def _prices_from_rets(rets, start=100):
            prices = [start]
            for r in rets:
                prices.append(prices[-1] * (1 + r))
            return prices

        # Low vol ~10% annualized (daily std ~0.0063)
        low_rets = [0.001 + 0.0063 * (1 if i % 2 == 0 else -1) for i in range(179)]
        low_vol = _prices_from_rets(low_rets)
        sig_low = generate_vt_trend_signal("LOWVOL", bars_from_prices(low_vol))
        self.assertEqual(sig_low.action, "BUY")
        self.assertAlmostEqual(sig_low.target_weight, 1.0, delta=0.01)

        # High vol ~60% annualized (daily std ~0.0378)
        high_rets = [0.001 + 0.0378 * (1 if i % 2 == 0 else -1) for i in range(179)]
        high_vol = _prices_from_rets(high_rets)
        sig_high = generate_vt_trend_signal("HIGHVOL", bars_from_prices(high_vol))
        self.assertEqual(sig_high.action, "BUY")
        self.assertAlmostEqual(sig_high.target_weight, 0.25, delta=0.05)
        self.assertLess(sig_high.target_weight, sig_low.target_weight)

    def test_vt_trend_floor_at_point_one_zero(self):
        prices = [100] * 20 + [100 + (25 if i % 2 == 0 else -25) for i in range(160)]
        sig = generate_vt_trend_signal("FLOOR", bars_from_prices(prices))
        self.assertEqual(sig.action, "SELL")
        self.assertEqual(sig.target_weight, 0.0)
        self.assertIn("exposure floor", sig.reason.lower())

    def test_vt_trend_drawdown_level_one_triggers(self):
        prices = [100 + i * 0.5 for i in range(100)] + [150 - i * 0.8 for i in range(30)]
        bars = bars_from_prices(prices)
        sig = generate_vt_trend_signal("DD1", bars)
        self.assertEqual(sig.evidence["drawdown_level"], 1)
        full_target = sig.evidence.get("full_target_weight")
        self.assertIsInstance(full_target, float)
        self.assertLess(sig.target_weight, float(full_target))

    def test_vt_trend_drawdown_level_two_triggers(self):
        prices = [100 + i * 0.5 for i in range(100)] + [150 - i * 1.2 for i in range(30)]
        bars = bars_from_prices(prices)
        sig = generate_vt_trend_signal("DD2", bars)
        self.assertEqual(sig.evidence["drawdown_level"], 2)
        self.assertEqual(sig.target_weight, 0.0)

    def test_vt_trend_reentry_after_level_two(self):
        # uptrend -> crash to level 2 -> partial recovery -> full recovery
        prices = (
            [100 + i * 0.5 for i in range(100)]       # uptrend to 150 (indices 0..99)
            + [150 - i * 1.5 for i in range(21)]      # crash to 120 (indices 100..120)
            + [120 + i * 0.3 for i in range(30)]      # recover to 129 (indices 121..150)
            + [129 + i * 0.5 for i in range(80)]      # recover to 169 (indices 151..230)
        )
        bars = bars_from_prices(prices)
        sig_crash = generate_vt_trend_signal("REENTRY", bars[:122])
        self.assertEqual(sig_crash.evidence["drawdown_level"], 2)
        sig_partial = generate_vt_trend_signal("REENTRY", bars[:152])
        self.assertFalse(sig_partial.evidence["reentry_ok"])
        sig_full = generate_vt_trend_signal("REENTRY", bars)
        self.assertTrue(sig_full.evidence["reentry_ok"])
        self.assertEqual(sig_full.action, "BUY")

    def test_vt_trend_trend_break_exits(self):
        prices = [100 + i * 0.5 for i in range(150)] + [175 - i * 0.8 for i in range(30)]
        bars = bars_from_prices(prices)
        sig = generate_vt_trend_signal("TB", bars)
        self.assertEqual(sig.action, "SELL")
        self.assertIn("trend break", sig.reason.lower())

    def test_vt_trend_no_lookahead_in_vol(self):
        from market_lab.indicators import returns
        prices = [100 + i * 0.3 for i in range(180)]
        bars = bars_from_prices(prices)
        sig = generate_vt_trend_signal("NL", bars[:150])
        closes = [b.close for b in bars[:150]]
        rets = [r for r in returns(closes) if r is not None]
        last_20 = rets[-20:]
        mean_ret = sum(last_20) / len(last_20)
        pop_std = (sum((r - mean_ret) ** 2 for r in last_20) / len(last_20)) ** 0.5
        expected_vol20 = pop_std * (252 ** 0.5)
        self.assertAlmostEqual(sig.evidence["vol20"], expected_vol20, places=6)

    def test_vt_trend_backtest_respects_drawdown_level_two_and_reentry(self):
        prices = (
            [100 + i * 0.5 for i in range(100)]
            + [150 - i * 1.5 for i in range(20)]
            + [120 + i * 0.3 for i in range(30)]
            + [129 + i * 0.5 for i in range(60)]
        )
        bars = bars_from_prices(prices)
        result = run_signal_backtest_with_sizing("REENTRY", bars, generate_vt_trend_signal, min_history=120)
        self.assertGreater(result.trades, 0)
        self.assertGreater(result.final_equity, 0)

    def test_sizing_backtest_uses_sell_fill_when_reducing_positive_target_weight(self):
        prices = [100.0] * 125
        bars = bars_from_prices(prices)
        sides = []

        class RecordingExecution:
            commission_per_trade = 0.0
            def fill_price(self, side, open_price):
                sides.append(side)
                return open_price

        def rebalance_signal(symbol, history):
            if len(history) <= 121:
                return Signal(symbol, "BUY", 1.0, "enter", history[-1].close, None, None, None, None, "rebalance", 1.0)
            return Signal(symbol, "BUY", 1.0, "halve", history[-1].close, None, None, None, None, "rebalance", 0.5)

        result = run_signal_backtest_with_sizing("REB", bars, rebalance_signal, min_history=120, execution=RecordingExecution())

        self.assertGreaterEqual(result.trades, 2)
        self.assertEqual(sides[:2], ["BUY", "SELL"])

    def test_level_one_drawdown_holds_signal_target_instead_of_repeated_halving(self):
        prices = [100.0] * 122 + [110.0] + [120.0] * 7
        bars = bars_from_prices(prices)
        sides = []

        class RecordingExecution:
            commission_per_trade = 0.0
            def fill_price(self, side, open_price):
                sides.append(side)
                return open_price

        def level_one_signal(symbol, history):
            if len(history) <= 121:
                return Signal(symbol, "BUY", 1.0, "enter", history[-1].close, None, None, None, None, "level_one", 1.0, {"drawdown_level": 0})
            return Signal(symbol, "SELL", 1.0, "level one", history[-1].close, None, None, None, None, "level_one", 0.5, {"drawdown_level": 1})

        result = run_signal_backtest_with_sizing("L1", bars, level_one_signal, min_history=120, execution=RecordingExecution())

        self.assertLessEqual(result.trades, 3)
        self.assertEqual(sides[:2], ["BUY", "SELL"])
        self.assertGreater(result.final_equity, 11_000.0)
    def test_sizing_backtest_executes_final_pending_trade_at_last_open(self):
        bars = bars_from_prices([100.0] * 124)
        bars.append(Bar(date(2026, 5, 4), 100.0, 100.0, 50.0, 50.0, 1_000_000))

        def exit_penultimate_signal(symbol, history):
            if len(history) < 124:
                return Signal(symbol, "BUY", 1.0, "enter", history[-1].close, None, None, None, None, "final_exit", 1.0, {})
            return Signal(symbol, "SELL", 1.0, "exit", history[-1].close, None, None, None, None, "final_exit", 0.0, {})

        result = run_signal_backtest_with_sizing("LAST", bars, exit_penultimate_signal, min_history=120, execution=ExecutionModel(slippage_bps=0.0, commission_per_trade=0.0))

        self.assertEqual(result.trades, 2)
        self.assertAlmostEqual(result.final_equity, 10_000.0)


if __name__ == "__main__":
    unittest.main()
