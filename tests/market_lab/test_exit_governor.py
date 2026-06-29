import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from market_lab.broker import (
    OrderCandidate,
    Portfolio,
    Position,
    load_portfolio,
    place_mock_order,
)
from market_lab.data import Bar
from market_lab.exit_governor import (
    check_spy_relative_exit,
    evaluate_spy_relative_exits,
    _last_buy_entries_from_ledger,
    _spy_close_for_date,
)


def _bars_from_prices(prices: list[float], start: date | None = None) -> list[Bar]:
    start = start or date(2024, 1, 1)
    return [
        Bar(start + timedelta(days=i), p, p * 1.01, p * 0.99, p, 1_000_000)
        for i, p in enumerate(prices)
    ]


class CheckSpyRelativeExitTests(unittest.TestCase):
    def test_triggers_when_asset_lags_spy(self):
        """Position +1% but SPY +5% -> relative -4% -> exit at -3% trail."""
        triggered, reason = check_spy_relative_exit("AAPL", 313.1, 310.0, 787.5, 750.0, trail=-0.03)
        self.assertTrue(triggered)
        self.assertIn("SPY-relative exit governor", reason)
        self.assertIn("trailing SPY", reason)

    def test_holds_when_asset_beats_spy(self):
        """Position +3% and SPY +2% -> relative +1% -> no exit."""
        triggered, reason = check_spy_relative_exit("AAPL", 319.3, 310.0, 765.0, 750.0, trail=-0.03)
        self.assertFalse(triggered)
        self.assertIn("SPY-relative hold", reason)

    def test_triggers_on_relative_loss_despite_absolute_gain(self):
        """Position +5% but SPY +20% -> relative -15% -> exit (lagger in strong mkt)."""
        triggered, reason = check_spy_relative_exit("AAPL", 325.5, 310.0, 900.0, 750.0, trail=-0.03)
        self.assertTrue(triggered)
        self.assertIn("SPY-relative exit governor", reason)

    def test_no_trigger_at_exact_threshold(self):
        """Position -2% and SPY +1% -> relative -3% exactly -> no exit (< not <=)."""
        triggered, _ = check_spy_relative_exit("AAPL", 98.0, 100.0, 101.0, 100.0, trail=-0.03)
        self.assertFalse(triggered)

    def test_negative_prices_return_safe_false(self):
        """Invalid prices should be safe (no premature exit)."""
        triggered, reason = check_spy_relative_exit("AAPL", -1.0, 100.0, 100.0, 100.0, trail=-0.03)
        self.assertFalse(triggered)
        self.assertIn("invalid prices", reason)


class SpyCloseForDateTests(unittest.TestCase):
    def test_exact_match(self):
        bars = _bars_from_prices([100.0, 101.0, 102.0])
        self.assertEqual(_spy_close_for_date(bars, date(2024, 1, 2)), 101.0)

    def test_nearest_prior_bar(self):
        bars = _bars_from_prices([100.0, 101.0, 102.0])
        # No bar for Jan 5; should return last prior close (102.0)
        self.assertEqual(_spy_close_for_date(bars, date(2024, 1, 5)), 102.0)

    def test_before_first_bar_returns_none(self):
        bars = _bars_from_prices([100.0, 101.0])
        self.assertIsNone(_spy_close_for_date(bars, date(2023, 12, 25)))

    def test_empty_list_returns_none(self):
        self.assertIsNone(_spy_close_for_date([], date(2024, 1, 1)))


class LastBuyEntriesFromLedgerTests(unittest.TestCase):
    def test_extracts_latest_accepted_buy_per_symbol(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.jsonl"
            # Write ledger lines directly so dates are deterministic.
            lines = [
                json.dumps({"accepted": True, "side": "BUY", "symbol": "AAPL", "fill_price": 150.0, "execution_date": "2024-01-01", "timestamp": "2024-01-01T10:00:00+00:00"}),
                json.dumps({"accepted": True, "side": "BUY", "symbol": "AAPL", "fill_price": 155.0, "execution_date": "2024-01-03", "timestamp": "2024-01-03T10:00:00+00:00"}),
                json.dumps({"accepted": False, "side": "BUY", "symbol": "MSFT", "fill_price": 300.0, "execution_date": "2024-01-01", "timestamp": "2024-01-01T10:00:00+00:00"}),
                json.dumps({"accepted": True, "side": "SELL", "symbol": "AAPL", "fill_price": 160.0, "execution_date": "2024-01-05", "timestamp": "2024-01-05T10:00:00+00:00"}),
            ]
            ledger.write_text("\n".join(lines) + "\n")

            entries = _last_buy_entries_from_ledger(ledger)
            self.assertEqual(len(entries), 1)
            self.assertIn("AAPL", entries)
            self.assertEqual(entries["AAPL"][0], 155.0)
            self.assertEqual(entries["AAPL"][1].isoformat(), "2024-01-03")

    def test_missing_ledger_returns_empty(self):
        entries = _last_buy_entries_from_ledger(Path("/nonexistent/ledger.jsonl"))
        self.assertEqual(entries, {})


class EvaluateSpyRelativeExitsTests(unittest.TestCase):
    def setUp(self):
        self.spy_bars = _bars_from_prices([100.0, 102.0, 104.0, 106.0, 108.0, 110.0])

    def test_empty_portfolio_returns_no_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.jsonl"
            candidates = evaluate_spy_relative_exits(
                Portfolio(),
                {"AAPL": 100.0},
                self.spy_bars,
                ledger,
                trail_threshold=-0.03,
            )
            self.assertEqual(candidates, [])

    def test_missing_ledger_returns_no_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.jsonl"
            portfolio = Portfolio(cash=50_000, positions={"AAPL": Position("AAPL", quantity=10, avg_price=150.0)})
            candidates = evaluate_spy_relative_exits(
                portfolio,
                {"AAPL": 100.0},
                self.spy_bars,
                ledger,
            )
            self.assertEqual(candidates, [])

    def test_missing_spy_bars_returns_no_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.jsonl"
            portfolio = Portfolio(cash=50_000, positions={"AAPL": Position("AAPL", quantity=10, avg_price=150.0)})
            candidates = evaluate_spy_relative_exits(
                portfolio,
                {"AAPL": 100.0},
                None,
                ledger,
            )
            self.assertEqual(candidates, [])

    def test_triggers_exit_when_relative_trail_breached(self):
        """
        Entry on Jan 1: AAPL @ $100, SPY @ $100.
        Current (Jan 6): AAPL @ $101 (+1%), SPY @ $110 (+10%).
        Relative = -9% < -3% trail -> exit.
        """
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            ledger = Path(td) / "ledger.jsonl"
            # Seed ledger with a BUY on Jan 1
            place_mock_order("BUY", "AAPL", 10, 100.0, {"AAPL": 100.0}, state, ledger, execution_date="2024-01-01")
            portfolio = load_portfolio(state)
            # Only Jan 1 bar needed for SPY entry lookup; current is the last bar (Jan 6)
            spy_bars = _bars_from_prices([100.0, 102.0, 104.0, 106.0, 108.0, 110.0])
            candidates = evaluate_spy_relative_exits(
                portfolio,
                {"AAPL": 101.0},
                spy_bars,
                ledger,
                trail_threshold=-0.03,
                signal_date="2024-01-06",
            )
            self.assertEqual(len(candidates), 1)
            c = candidates[0]
            self.assertIsInstance(c, OrderCandidate)
            self.assertEqual(c.side, "SELL")
            self.assertEqual(c.symbol, "AAPL")
            self.assertEqual(c.quantity, 10)
            self.assertEqual(c.strategy, "spy_exit_governor")
            self.assertEqual(c.intended_execution, "next_open")
            self.assertIn("SPY-relative exit governor", c.reason)

    def test_no_exit_when_within_trail(self):
        """
        Entry on Jan 1: AAPL @ $100, SPY @ $100.
        Current (Jan 6): AAPL @ $110 (+10%), SPY @ $105 (+5%).
        Relative = +5% -> no exit.
        """
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            ledger = Path(td) / "ledger.jsonl"
            place_mock_order("BUY", "AAPL", 10, 100.0, {"AAPL": 100.0}, state, ledger, execution_date="2024-01-01")
            portfolio = load_portfolio(state)
            spy_bars = _bars_from_prices([100.0, 102.0, 104.0, 106.0, 108.0, 105.0])
            candidates = evaluate_spy_relative_exits(
                portfolio,
                {"AAPL": 110.0},
                spy_bars,
                ledger,
                trail_threshold=-0.03,
            )
            self.assertEqual(candidates, [])

    def test_multiple_positions_only_exits_triggered_ones(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            ledger = Path(td) / "ledger.jsonl"
            # MSFT enters later and doesn't breach
            place_mock_order("BUY", "AAPL", 10, 100.0, {"AAPL": 100.0}, state, ledger, execution_date="2024-01-01")
            place_mock_order("BUY", "MSFT", 5, 200.0, {"MSFT": 200.0}, state, ledger, execution_date="2024-01-03")
            portfolio = load_portfolio(state)
            # AAPL+1% vs SPY+10% -> breach; MSFT+0% vs SPY+6% -> breach too actually
            # Let's make MSFT beat SPY
            spy_bars = _bars_from_prices([100.0, 102.0, 104.0, 106.0, 108.0, 110.0])
            candidates = evaluate_spy_relative_exits(
                portfolio,
                {"AAPL": 101.0, "MSFT": 220.0},
                spy_bars,
                ledger,
                trail_threshold=-0.03,
            )
            symbols = [c.symbol for c in candidates]
            self.assertIn("AAPL", symbols)
            self.assertNotIn("MSFT", symbols)  # MSFT +10% vs SPY +10% = 0% within trail

    def test_reentry_allowed_after_exit(self):
        """The governor generates a candidate; it must not persist any blacklist state."""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            ledger = Path(td) / "ledger.jsonl"
            place_mock_order("BUY", "AAPL", 10, 100.0, {"AAPL": 100.0}, state, ledger, execution_date="2024-01-01")
            portfolio = load_portfolio(state)
            spy_bars = _bars_from_prices([100.0, 102.0, 104.0, 106.0, 108.0, 110.0])
            # First call generates exit
            c1 = evaluate_spy_relative_exits(
                portfolio, {"AAPL": 101.0}, spy_bars, ledger, trail_threshold=-0.03
            )
            self.assertEqual(len(c1), 1)
            # Second call with same inputs still generates exactly the same candidate
            c2 = evaluate_spy_relative_exits(
                portfolio, {"AAPL": 101.0}, spy_bars, ledger, trail_threshold=-0.03
            )
            self.assertEqual(len(c2), 1)
            # No side effect / mutation of portfolio or ledger
            after = load_portfolio(state)
            self.assertEqual(after.positions["AAPL"].quantity, 10)

    def test_no_lookahead_only_uses_current_bar(self):
        """Ensure the function never uses bars beyond the latest provided one."""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            ledger = Path(td) / "ledger.jsonl"
            place_mock_order("BUY", "AAPL", 10, 100.0, {"AAPL": 100.0}, state, ledger, execution_date="2024-01-01")
            portfolio = load_portfolio(state)
            spy_bars = _bars_from_prices([100.0, 110.0])  # only 2 bars
            # Should work with only the latest bar; no future data needed.
            candidates = evaluate_spy_relative_exits(
                portfolio, {"AAPL": 90.0}, spy_bars, ledger, trail_threshold=-0.03
            )
            self.assertEqual(len(candidates), 1)  # asset -10% vs SPY +10% = -20% breach

    def test_spy_missing_for_entry_date_skips_position(self):
        """If the ledger entry date precedes all spy_bars, skip safely."""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            ledger = Path(td) / "ledger.jsonl"
            place_mock_order("BUY", "AAPL", 10, 100.0, {"AAPL": 100.0}, state, ledger, execution_date="2023-12-01")
            portfolio = load_portfolio(state)
            spy_bars = _bars_from_prices([100.0, 110.0], start=date(2024, 1, 1))
            candidates = evaluate_spy_relative_exits(
                portfolio, {"AAPL": 90.0}, spy_bars, ledger, trail_threshold=-0.03
            )
            # Entry date 2023-12-01 is before first spy bar 2024-01-01; spy_entry would be None
            self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
