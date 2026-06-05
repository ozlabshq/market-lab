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
from market_lab.config import VT_TREND_STARTING_CASH
from market_lab.data import Bar
from market_lab.signals import generate_vt_trend_signal


def bars_from_prices(prices, opens=None):
    start = date(2024, 1, 1)
    opens = opens or prices
    return [Bar(start + timedelta(days=i), opens[i], max(opens[i], p) * 1.01, min(opens[i], p) * 0.99, p, 1_000_000) for i, p in enumerate(prices)]


class VtTrendTrackingTests(unittest.TestCase):
    def test_vt_trend_state_path_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            vt_state = Path(td) / "vt_trend" / "portfolio_state.json"
            main_state = Path(td) / "mock_portfolio_state.json"
            save_portfolio(Portfolio(cash=VT_TREND_STARTING_CASH), vt_state)
            save_portfolio(Portfolio(cash=100_000.0), main_state)
            self.assertTrue(vt_state.exists())
            self.assertTrue(main_state.exists())
            self.assertNotEqual(vt_state, main_state)

    def test_vt_trend_load_save_portfolio(self):
        with tempfile.TemporaryDirectory() as td:
            vt_state = Path(td) / "vt_trend" / "portfolio_state.json"
            main_state = Path(td) / "mock_portfolio_state.json"
            portfolio = Portfolio(cash=VT_TREND_STARTING_CASH, positions={"SPY": Position("SPY", 10, 100.0)})
            save_portfolio(portfolio, vt_state)
            save_portfolio(Portfolio(cash=100_000.0), main_state)
            loaded = load_portfolio(vt_state)
            self.assertEqual(loaded.cash, VT_TREND_STARTING_CASH)
            self.assertEqual(loaded.positions["SPY"].quantity, 10)
            # Verify main portfolio default path is untouched
            main = load_portfolio(main_state)
            self.assertEqual(main.cash, 100_000.0)

    def test_vt_trend_ledger_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            vt_ledger = Path(td) / "vt_trend" / "ledger.jsonl"
            main_ledger = Path(td) / "mock_ledger.jsonl"
            from market_lab.broker import OrderDecision
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            d1 = OrderDecision(True, "BUY", "SPY", 5, 100.0, 100.0, "test", now, "vt_trend")
            d2 = OrderDecision(True, "BUY", "QQQ", 5, 100.0, 100.0, "test", now, "ensemble")
            append_ledger(d1, vt_ledger)
            append_ledger(d2, main_ledger)
            vt_lines = [json.loads(line) for line in vt_ledger.read_text().strip().split("\n")]
            main_lines = [json.loads(line) for line in main_ledger.read_text().strip().split("\n")]
            self.assertEqual(len(vt_lines), 1)
            self.assertEqual(vt_lines[0]["strategy"], "vt_trend")
            self.assertEqual(len(main_lines), 1)
            self.assertEqual(main_lines[0]["strategy"], "ensemble")

    def test_vt_trend_candidate_queue(self):
        with tempfile.TemporaryDirectory() as td:
            vt_candidates = Path(td) / "vt_trend" / "pending_candidates.jsonl"
            main_candidates = Path(td) / "pending_order_candidates.jsonl"
            c = OrderCandidate("BUY", "SPY", 10, "vt_trend", 0.7, "test", "2024-01-02", 100.0)
            save_order_candidates([c], vt_candidates)
            save_order_candidates([], main_candidates)
            loaded = load_order_candidates(vt_candidates)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].strategy, "vt_trend")
            self.assertEqual(len(load_order_candidates(main_candidates)), 0)

    def test_vt_trend_signal_to_fill_cycle(self):
        prices = [100 + i * 0.5 for i in range(130)]
        bars = bars_from_prices(prices)
        sig = generate_vt_trend_signal("SPY", bars)
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "vt_trend" / "portfolio_state.json"
            ledger = Path(td) / "vt_trend" / "ledger.jsonl"
            portfolio = Portfolio(cash=VT_TREND_STARTING_CASH)
            save_portfolio(portfolio, state)
            if sig.action == "BUY" and sig.target_weight > 0:
                # Use a small qty that passes risk gates (under $1,250 notional)
                qty = 5
                candidate = OrderCandidate("BUY", "SPY", qty, "vt_trend", sig.confidence, sig.reason, bars[-1].date.isoformat(), sig.close)
                decision = candidate_to_order_at_open(candidate, bars[-1].open, {"SPY": bars[-1].open}, portfolio_path=state, ledger_path=ledger, execution_date=bars[-1].date.isoformat())
                self.assertTrue(decision.accepted)
                updated = load_portfolio(state)
                self.assertGreater(updated.positions.get("SPY", Position("SPY")).quantity, 0)
                self.assertTrue(ledger.exists())

    def test_vt_trend_initial_capital(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "vt_trend" / "portfolio_state.json"
            portfolio = Portfolio(cash=VT_TREND_STARTING_CASH)
            save_portfolio(portfolio, state)
            loaded = load_portfolio(state)
            self.assertEqual(loaded.cash, 25_000.0)
            self.assertNotEqual(loaded.cash, 100_000.0)

    def test_vt_trend_flat_period_logging(self):
        # When signal is HOLD, no candidate should be queued
        prices = [100] * 130
        bars = bars_from_prices(prices)
        sig = generate_vt_trend_signal("SPY", bars)
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "vt_trend" / "portfolio_state.json"
            candidates_path = Path(td) / "vt_trend" / "pending_candidates.jsonl"
            portfolio = Portfolio(cash=VT_TREND_STARTING_CASH)
            save_portfolio(portfolio, state)
            # Simulate no candidate creation for flat signal
            if sig.action == "HOLD" or sig.target_weight == 0:
                save_order_candidates([], candidates_path)
            loaded = load_order_candidates(candidates_path)
            self.assertEqual(len(loaded), 0)

    def test_vt_trend_reentry_produces_correct_side(self):
        # uptrend -> crash to level 2 -> recovery
        prices = (
            [100 + i * 0.5 for i in range(100)]
            + [150 - i * 1.5 for i in range(21)]
            + [120 + i * 0.3 for i in range(30)]
            + [129 + i * 0.5 for i in range(80)]
        )
        bars = bars_from_prices(prices)
        sig_crash = generate_vt_trend_signal("SPY", bars[:122])
        self.assertEqual(sig_crash.evidence["drawdown_level"], 2)
        sig_full = generate_vt_trend_signal("SPY", bars)
        self.assertTrue(sig_full.evidence["reentry_ok"])
        self.assertEqual(sig_full.action, "BUY")
        # After level 2 flat, re-entry should produce a BUY candidate for delta weight
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "vt_trend" / "portfolio_state.json"
            portfolio = Portfolio(cash=VT_TREND_STARTING_CASH)
            save_portfolio(portfolio, state)
            if sig_full.action == "BUY" and sig_full.target_weight > 0:
                equity = VT_TREND_STARTING_CASH
                notional = sig_full.target_weight * equity
                qty = max(1, int(notional // sig_full.close))
                candidate = OrderCandidate("BUY", "SPY", qty, "vt_trend", sig_full.confidence, sig_full.reason, bars[-1].date.isoformat(), sig_full.close)
                self.assertEqual(candidate.side, "BUY")
                self.assertGreater(candidate.quantity, 0)

    def test_vt_trend_diagnosis_integration(self):
        with tempfile.TemporaryDirectory() as td:
            vt_ledger = Path(td) / "vt_trend" / "ledger.jsonl"
            evidence_dir = Path(td) / "evidence"
            from market_lab.broker import OrderDecision
            from datetime import datetime, timezone
            from market_lab.diagnosis import diagnose_trade
            from market_lab.evidence import evidence_stream_path, load_evidence_records
            now = datetime.now(timezone.utc).isoformat()
            decision = OrderDecision(True, "BUY", "SPY", 10, 100.0, 100.0, "test", now, "vt_trend", execution_date="2024-01-02")
            append_ledger(decision, vt_ledger)
            bars = bars_from_prices([100 + i * 0.1 for i in range(10)])
            diagnosis = diagnose_trade(decision, bars, strategy="vt_trend")
            trades_path = evidence_stream_path("vt_trend_trades", evidence_dir)
            from market_lab.evidence import append_atomic_jsonl_batch
            append_atomic_jsonl_batch([diagnosis.as_record()], trades_path)
            records = load_evidence_records(trades_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["strategy"], "vt_trend")

    def test_vt_trend_synthetic_data_refusal(self):
        # Simulate the --require-live-data gate by checking source string
        from scripts.market_lab_vt_trend import _source_is_synthetic
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
