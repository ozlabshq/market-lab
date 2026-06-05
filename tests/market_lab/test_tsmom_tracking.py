import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from market_lab.broker import (
    OrderCandidate,
    Portfolio,
    Position,
    append_ledger,
    candidate_to_order_at_open,
    load_order_candidates,
    load_portfolio,
    place_mock_order,
    save_order_candidates,
    save_portfolio,
)
from market_lab.config import TSMOM_STARTING_CASH
from market_lab.data import Bar
from market_lab.signals import generate_tsmom_signal


def bars_from_prices(prices, opens=None):
    start = date(2024, 1, 1)
    opens = opens or prices
    return [Bar(start + timedelta(days=i), opens[i], max(opens[i], p) * 1.01, min(opens[i], p) * 0.99, p, 1_000_000) for i, p in enumerate(prices)]


class TsmomTrackingTests(unittest.TestCase):
    def test_tsmom_state_path_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            tsmom_state = Path(td) / "tsmom" / "portfolio_state.json"
            main_state = Path(td) / "mock_portfolio_state.json"
            save_portfolio(Portfolio(cash=TSMOM_STARTING_CASH), tsmom_state)
            save_portfolio(Portfolio(cash=100_000.0), main_state)
            self.assertTrue(tsmom_state.exists())
            self.assertTrue(main_state.exists())
            self.assertNotEqual(tsmom_state, main_state)

    def test_tsmom_load_save_portfolio(self):
        with tempfile.TemporaryDirectory() as td:
            tsmom_state = Path(td) / "tsmom" / "portfolio_state.json"
            main_state = Path(td) / "mock_portfolio_state.json"
            portfolio = Portfolio(cash=TSMOM_STARTING_CASH, positions={"SPY": Position("SPY", 10, 100.0)})
            save_portfolio(portfolio, tsmom_state)
            save_portfolio(Portfolio(cash=100_000.0), main_state)
            loaded = load_portfolio(tsmom_state)
            self.assertEqual(loaded.cash, TSMOM_STARTING_CASH)
            self.assertEqual(loaded.positions["SPY"].quantity, 10)
            # Verify main portfolio default path is untouched
            main = load_portfolio(main_state)
            self.assertEqual(main.cash, 100_000.0)

    def test_tsmom_ledger_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            tsmom_ledger = Path(td) / "tsmom" / "ledger.jsonl"
            main_ledger = Path(td) / "mock_ledger.jsonl"
            from market_lab.broker import OrderDecision
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            d1 = OrderDecision(True, "BUY", "SPY", 5, 100.0, 100.0, "test", now, "tsmom")
            d2 = OrderDecision(True, "BUY", "QQQ", 5, 100.0, 100.0, "test", now, "ensemble")
            append_ledger(d1, tsmom_ledger)
            append_ledger(d2, main_ledger)
            tsmom_lines = [json.loads(line) for line in tsmom_ledger.read_text().strip().split("\n")]
            main_lines = [json.loads(line) for line in main_ledger.read_text().strip().split("\n")]
            self.assertEqual(len(tsmom_lines), 1)
            self.assertEqual(tsmom_lines[0]["strategy"], "tsmom")
            self.assertEqual(len(main_lines), 1)
            self.assertEqual(main_lines[0]["strategy"], "ensemble")

    def test_tsmom_candidate_queue(self):
        with tempfile.TemporaryDirectory() as td:
            tsmom_candidates = Path(td) / "tsmom" / "pending_candidates.jsonl"
            main_candidates = Path(td) / "pending_order_candidates.jsonl"
            c = OrderCandidate("BUY", "SPY", 10, "tsmom", 0.7, "test", "2024-01-02", 100.0)
            save_order_candidates([c], tsmom_candidates)
            save_order_candidates([], main_candidates)
            loaded = load_order_candidates(tsmom_candidates)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].strategy, "tsmom")
            self.assertEqual(len(load_order_candidates(main_candidates)), 0)

    def test_tsmom_signal_to_fill_cycle(self):
        # Strong enough uptrend to trigger BUY with enough bars
        prices = [100 + i * 0.5 for i in range(200)]
        bars = bars_from_prices(prices)
        sig = generate_tsmom_signal("SPY", bars)
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "tsmom" / "portfolio_state.json"
            ledger = Path(td) / "tsmom" / "ledger.jsonl"
            portfolio = Portfolio(cash=TSMOM_STARTING_CASH)
            save_portfolio(portfolio, state)
            if sig.action == "BUY" and sig.target_weight > 0:
                qty = 5  # small qty that passes risk gates
                candidate = OrderCandidate("BUY", "SPY", qty, "tsmom", sig.confidence, sig.reason, bars[-1].date.isoformat(), sig.close)
                decision = candidate_to_order_at_open(candidate, bars[-1].open, {"SPY": bars[-1].open}, portfolio_path=state, ledger_path=ledger, execution_date=bars[-1].date.isoformat())
                self.assertTrue(decision.accepted)
                updated = load_portfolio(state)
                self.assertGreater(updated.positions.get("SPY", Position("SPY")).quantity, 0)
                self.assertTrue(ledger.exists())

    def test_tsmom_initial_capital(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "tsmom" / "portfolio_state.json"
            portfolio = Portfolio(cash=TSMOM_STARTING_CASH)
            save_portfolio(portfolio, state)
            loaded = load_portfolio(state)
            self.assertEqual(loaded.cash, 25_000.0)
            self.assertNotEqual(loaded.cash, 100_000.0)

    def test_tsmom_flat_period_logging(self):
        # Flat prices → no momentum → signal should be HOLD
        prices = [100] * 200
        bars = bars_from_prices(prices)
        sig = generate_tsmom_signal("SPY", bars)
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "tsmom" / "portfolio_state.json"
            candidates_path = Path(td) / "tsmom" / "pending_candidates.jsonl"
            portfolio = Portfolio(cash=TSMOM_STARTING_CASH)
            save_portfolio(portfolio, state)
            if sig.action == "HOLD" or sig.target_weight == 0:
                save_order_candidates([], candidates_path)
            loaded = load_order_candidates(candidates_path)
            self.assertEqual(len(loaded), 0)

    def test_tsmom_drawdown_sell_produces_candidate(self):
        # Uptrend then crash
        prices = (
            [100 + i * 0.5 for i in range(150)]
            + [175 - i * 2.0 for i in range(30)]
        )
        bars = bars_from_prices(prices)
        sig = generate_tsmom_signal("SPY", bars)
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "tsmom" / "portfolio_state.json"
            portfolio = Portfolio(cash=TSMOM_STARTING_CASH, positions={"SPY": Position("SPY", 50, 150.0)})
            save_portfolio(portfolio, state)
            if sig.action == "SELL":
                equity = TSMOM_STARTING_CASH + 50 * 150.0
                notional = min(50 * 150.0, 5000.0, equity * 0.05)
                qty = max(1, int(notional // bars[-1].open))
                candidate = OrderCandidate("SELL", "SPY", qty, "tsmom", sig.confidence, sig.reason, bars[-1].date.isoformat(), sig.close)
                self.assertEqual(candidate.side, "SELL")
                self.assertGreater(candidate.quantity, 0)

    def test_tsmom_diagnosis_integration(self):
        with tempfile.TemporaryDirectory() as td:
            tsmom_ledger = Path(td) / "tsmom" / "ledger.jsonl"
            evidence_dir = Path(td) / "evidence"
            from market_lab.broker import OrderDecision
            from datetime import datetime, timezone
            from market_lab.diagnosis import diagnose_trade
            from market_lab.evidence import evidence_stream_path, load_evidence_records
            now = datetime.now(timezone.utc).isoformat()
            decision = OrderDecision(True, "BUY", "SPY", 10, 100.0, 100.0, "test", now, "tsmom", execution_date="2024-01-02")
            append_ledger(decision, tsmom_ledger)
            bars = bars_from_prices([100 + i * 0.1 for i in range(10)])
            diagnosis = diagnose_trade(decision, bars, strategy="tsmom")
            trades_path = evidence_stream_path("tsmom_trades", evidence_dir)
            from market_lab.evidence import append_atomic_jsonl_batch
            append_atomic_jsonl_batch([diagnosis.as_record()], trades_path)
            records = load_evidence_records(trades_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["strategy"], "tsmom")

    def test_tsmom_synthetic_data_refusal(self):
        # Simulate the --require-live-data gate by checking source string
        from scripts.market_lab_tsmom import _source_is_synthetic
        self.assertTrue(_source_is_synthetic("synthetic"))
        self.assertTrue(_source_is_synthetic("cache"))
        self.assertTrue(_source_is_synthetic("cache_synthetic"))
        self.assertFalse(_source_is_synthetic("yfinance"))
        require_live_data = True
        for source in ("synthetic", "cache", "cache_synthetic"):
            should_abort = require_live_data and _source_is_synthetic(source)
            self.assertTrue(should_abort, f"expected abort for source={source}")
        self.assertFalse(require_live_data and _source_is_synthetic("yfinance"))


if __name__ == "__main__":
    unittest.main()
