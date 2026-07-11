import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from market_lab.broker import Portfolio
from market_lab.data import Bar
import scripts.market_lab_daily as daily


def _bars_from_prices(start: date, closes: list[float]) -> list[Bar]:
    return [
        Bar(
            start + timedelta(days=i),
            close,
            close * 1.01,
            close * 0.99,
            close,
            1_000_000,
        )
        for i, close in enumerate(closes)
    ]


class MarketLabDailySpyRelativeExitTests(unittest.TestCase):
    def test_queue_order_candidates_with_spy_relative_exit_trail_uses_fallback_spy_data(self) -> None:
        aapl_bars = _bars_from_prices(date(2024, 1, 1), [160.0])
        spy_bars = _bars_from_prices(date(2024, 1, 1), [520.0])

        def fake_fetch_prices(symbol: str, days: int, prefer_network: bool = False):
            if symbol == "AAPL":
                return aapl_bars, "fixture"
            if symbol == "SPY":
                return spy_bars, "fixture"
            return [aapl_bars[0]], "fixture"

        with tempfile.TemporaryDirectory() as td:
            report_path = Path(td) / "latest.md"
            with ExitStack() as stack:
                fetch_prices = stack.enter_context(
                    patch("scripts.market_lab_daily.fetch_prices", side_effect=fake_fetch_prices)
                )
                stack.enter_context(patch("scripts.market_lab_daily.ensure_dirs"))
                stack.enter_context(patch("scripts.market_lab_daily.fetch_factors", return_value=([], "fixture")))
                stack.enter_context(patch("scripts.market_lab_daily.apply_factor_overlay", side_effect=lambda signal, factor: signal))
                stack.enter_context(patch("scripts.market_lab_daily.generate_ensemble_signal", return_value=[]))
                stack.enter_context(patch("scripts.market_lab_daily.generate_strategy_signals", return_value=[]))
                stack.enter_context(patch("scripts.market_lab_daily.run_signal_backtest", return_value=MagicMock()))
                stack.enter_context(patch("scripts.market_lab_daily.moving_average_cross_backtest", return_value=MagicMock()))
                stack.enter_context(patch("scripts.market_lab_daily.rank_signals", return_value=[]))
                stack.enter_context(patch("scripts.market_lab_daily.cross_sectional_momentum_ranks", return_value={}))
                stack.enter_context(patch("scripts.market_lab_daily.load_portfolio", return_value=Portfolio()))
                stack.enter_context(patch("scripts.market_lab_daily.load_order_candidates", return_value=[]))
                stack.enter_context(patch("scripts.market_lab_daily.save_order_candidates"))
                stack.enter_context(patch("scripts.market_lab_daily.load_available_option_chains", return_value=[]))
                stack.enter_context(patch("scripts.market_lab_daily.load_option_paper_candidates", return_value=[]))
                stack.enter_context(patch("scripts.market_lab_daily.load_option_paper_portfolio", return_value={}))
                stack.enter_context(patch("scripts.market_lab_daily.compute_spy_benchmark", return_value={}))
                stack.enter_context(patch("scripts.market_lab_daily.render_report", return_value="report"))
                stack.enter_context(patch("scripts.market_lab_daily.save_report", return_value=report_path))
                evaluate_spy_relative_exits = stack.enter_context(
                    patch("scripts.market_lab_daily.evaluate_spy_relative_exits")
                )
                evaluate_spy_relative_exits.return_value = []

                with patch.object(sys, "argv", [
                    "market-lab-daily",
                    "--symbols",
                    "AAPL",
                    "--queue-order-candidates",
                    "--spy-relative-exit-trail",
                    "0.03",
                    "--days",
                    "3",
                ]):
                    rc = daily.main()

            self.assertEqual(rc, 0)
            self.assertEqual(evaluate_spy_relative_exits.call_count, 1)
            called_spy_bars = evaluate_spy_relative_exits.call_args.args[2]
            self.assertEqual(called_spy_bars, spy_bars)
            self.assertIn("SPY", [call.args[0] for call in fetch_prices.call_args_list])


if __name__ == "__main__":
    unittest.main()
