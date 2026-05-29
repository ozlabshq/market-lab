import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from market_lab.broker import OrderCandidate, OrderDecision, Portfolio, Position, candidate_to_order_at_open
from market_lab.data import Bar
from market_lab.diagnosis import (
    TradeDiagnosis,
    diagnose_trade,
    generate_strategy_health_report,
    label_regime,
)
from market_lab.evidence import append_evidence_record, load_evidence_records
from scripts import market_lab_review


def bars_from_closes(closes, start=date(2026, 1, 1), volume=1_000_000):
    return [
        Bar(start + timedelta(days=i), close, close * 1.01, close * 0.99, close, volume)
        for i, close in enumerate(closes)
    ]


class DiagnosisCouncilTests(unittest.TestCase):
    def test_label_regime_identifies_trending_up_and_down(self):
        up = bars_from_closes([100 + i for i in range(120)])
        down = bars_from_closes([220 - i for i in range(120)])

        self.assertEqual(label_regime(up), "trending_up")
        self.assertEqual(label_regime(down), "trending_down")

    def test_diagnose_trade_computes_pnl_and_whipsaw_failure_mode(self):
        decision = OrderDecision(True, "BUY", "SPY", 10, 100.0, 100.0, "accepted", "2026-01-01T00:00:00Z")
        bars = bars_from_closes([100.0, 98.0, 97.5, 97.0, 96.0, 96.5])

        diagnosis = diagnose_trade(
            decision,
            bars,
            strategy="tsmom",
            evidence_snapshot={"momentum": 0.12},
            benchmark_return=0.01,
        )

        self.assertIsInstance(diagnosis, TradeDiagnosis)
        self.assertEqual(diagnosis.symbol, "SPY")
        self.assertEqual(diagnosis.strategy, "tsmom")
        self.assertAlmostEqual(diagnosis.pnl_pct, -0.035)
        self.assertAlmostEqual(diagnosis.pnl_vs_benchmark, -0.045)
        self.assertEqual(diagnosis.failure_mode, "whipsaw")
        self.assertEqual(diagnosis.evidence_snapshot["momentum"], 0.12)

    def test_strategy_health_report_pauses_decaying_strategy(self):
        diagnoses = [
            TradeDiagnosis(
                decision_id=f"d{i}",
                symbol="SPY",
                strategy="vc_mr",
                side="BUY",
                entry_date="2026-01-01",
                exit_date="2026-01-02",
                holding_bars=1,
                entry_price=100.0,
                exit_price=99.0,
                pnl_pct=-0.01,
                pnl_vs_benchmark=-0.02,
                regime_label="high_vol_chop",
                hypothesis="test",
                evidence_snapshot={},
                failure_mode="whipsaw",
                confidence_at_entry=0.7,
                data_quality="live_or_cache",
            )
            for i in range(20)
        ]

        report = generate_strategy_health_report("vc_mr", diagnoses)

        self.assertTrue(report.decay_alert)
        self.assertEqual(report.recommended_action, "pause")
        self.assertEqual(report.top_failure_modes[0], "whipsaw")
        self.assertLess(report.avg_pnl, 0)

    def test_evidence_records_are_append_only_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "evidence" / "trades.jsonl"
            first = {"type": "trade", "id": "a"}
            second = {"type": "trade", "id": "b"}

            append_evidence_record(first, path)
            append_evidence_record(second, path)

            raw = path.read_text().strip().splitlines()
            self.assertEqual(len(raw), 2)
            self.assertEqual(json.loads(raw[0])["id"], "a")
            self.assertEqual([r["id"] for r in load_evidence_records(path)], ["a", "b"])
    def test_review_script_skips_sells_and_slices_bars_after_decision_date(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_dir = Path(td) / "evidence"
            buy = OrderDecision(True, "BUY", "SPY", 10, 100.0, 100.0, "accepted", "2026-01-03T15:00:00Z")
            sell = OrderDecision(True, "SELL", "QQQ", 10, 105.0, 105.0, "accepted", "2026-01-04T15:00:00Z")
            fetched = bars_from_closes([90.0, 95.0, 100.0, 101.0, 102.0], start=date(2026, 1, 1))

            with (
                patch.object(market_lab_review, "EVIDENCE_DIR", evidence_dir),
                patch.object(market_lab_review, "_load_accepted_decisions", return_value=[buy, sell]),
                patch.object(market_lab_review, "fetch_prices", return_value=(fetched, "cache")),
            ):
                diagnoses = market_lab_review.diagnose_new_mock_decisions(days=5)

            self.assertEqual(len(diagnoses), 1)
            self.assertEqual(diagnoses[0].side, "BUY")
            self.assertEqual(diagnoses[0].entry_date, "2026-01-03")
            self.assertEqual(diagnoses[0].holding_bars, 2)

    def test_review_script_waits_for_post_entry_bar_before_diagnosing(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_dir = Path(td) / "evidence"
            buy = OrderDecision(True, "BUY", "SPY", 10, 100.0, 100.0, "accepted", "2026-01-03T15:00:00Z")
            fetched = bars_from_closes([90.0, 95.0, 100.0], start=date(2026, 1, 1))

            with (
                patch.object(market_lab_review, "EVIDENCE_DIR", evidence_dir),
                patch.object(market_lab_review, "_load_accepted_decisions", return_value=[buy]),
                patch.object(market_lab_review, "fetch_prices", return_value=(fetched, "cache")),
            ):
                diagnoses = market_lab_review.diagnose_new_mock_decisions(days=3)

            self.assertEqual(diagnoses, [])
    def test_candidate_execution_preserves_strategy_and_market_execution_date(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            ledger = Path(td) / "ledger.jsonl"
            candidate = OrderCandidate("BUY", "SPY", 10, "dual_momentum", 0.8, "rank winner", "2026-01-02", 100.0)

            decision = candidate_to_order_at_open(
                candidate,
                next_open=101.0,
                prices={"SPY": 101.0},
                portfolio_path=state,
                ledger_path=ledger,
                execution_date="2026-01-03",
            )

            self.assertTrue(decision.accepted)
            self.assertEqual(decision.strategy, "dual_momentum")
            self.assertEqual(decision.signal_date, "2026-01-02")
            self.assertEqual(decision.execution_date, "2026-01-03")
            persisted = json.loads(ledger.read_text().strip())
            self.assertEqual(persisted["strategy"], "dual_momentum")
            self.assertEqual(persisted["execution_date"], "2026-01-03")

    def test_review_script_uses_execution_date_and_strategy_from_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_dir = Path(td) / "evidence"
            decision = OrderDecision(
                True,
                "BUY",
                "SPY",
                10,
                100.0,
                100.0,
                "accepted",
                "2026-01-10T15:00:00Z",
                strategy="tsmom",
                signal_date="2026-01-02",
                execution_date="2026-01-03",
            )
            fetched = bars_from_closes([90.0, 95.0, 100.0, 101.0, 102.0], start=date(2026, 1, 1))

            with (
                patch.object(market_lab_review, "EVIDENCE_DIR", evidence_dir),
                patch.object(market_lab_review, "_load_accepted_decisions", return_value=[decision]),
                patch.object(market_lab_review, "fetch_prices", return_value=(fetched, "cache")),
            ):
                diagnoses = market_lab_review.diagnose_new_mock_decisions(days=5)

            self.assertEqual(len(diagnoses), 1)
            self.assertEqual(diagnoses[0].entry_date, "2026-01-03")
            self.assertEqual(diagnoses[0].strategy, "tsmom")
    def test_review_script_skips_buy_when_later_sell_closed_same_symbol(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_dir = Path(td) / "evidence"
            buy = OrderDecision(
                True,
                "BUY",
                "SPY",
                10,
                100.0,
                100.0,
                "accepted",
                "2026-01-03T15:00:00Z",
                execution_date="2026-01-03",
            )
            sell = OrderDecision(
                True,
                "SELL",
                "SPY",
                10,
                105.0,
                105.0,
                "accepted",
                "2026-01-04T15:00:00Z",
                execution_date="2026-01-04",
            )
            fetched = bars_from_closes([100.0, 101.0, 102.0, 103.0, 104.0], start=date(2026, 1, 3))

            with (
                patch.object(market_lab_review, "EVIDENCE_DIR", evidence_dir),
                patch.object(market_lab_review, "_load_accepted_decisions", return_value=[buy, sell]),
                patch.object(market_lab_review, "fetch_prices", return_value=(fetched, "cache")),
            ):
                diagnoses = market_lab_review.diagnose_new_mock_decisions(days=5)

            self.assertEqual(diagnoses, [])
    def test_review_script_appends_updated_open_trade_snapshots_and_health_uses_latest(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_dir = Path(td) / "evidence"
            decision = OrderDecision(
                True,
                "BUY",
                "SPY",
                10,
                100.0,
                100.0,
                "accepted",
                "2026-01-03T15:00:00Z",
                strategy="tsmom",
                execution_date="2026-01-03",
            )
            stale = diagnose_trade(decision, bars_from_closes([100.0, 101.0], start=date(2026, 1, 3)), strategy="tsmom")
            updated_bars = bars_from_closes([100.0, 101.0, 102.0, 103.0], start=date(2026, 1, 3))

            with patch.object(market_lab_review, "EVIDENCE_DIR", evidence_dir):
                market_lab_review.append_atomic_jsonl_batch([stale.as_record()], market_lab_review.evidence_stream_path("trades", evidence_dir))
                with (
                    patch.object(market_lab_review, "_load_accepted_decisions", return_value=[decision]),
                    patch.object(market_lab_review, "fetch_prices", return_value=(updated_bars, "cache")),
                ):
                    diagnoses = market_lab_review.diagnose_new_mock_decisions(days=4)
                latest = market_lab_review._latest_trade_diagnoses()

            self.assertEqual(len(diagnoses), 1)
            self.assertEqual(diagnoses[0].holding_bars, 3)
            self.assertEqual(len(latest), 1)
            self.assertEqual(latest[0].holding_bars, 3)
    def test_review_script_keeps_open_lot_after_partial_sell(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_dir = Path(td) / "evidence"
            first_buy = OrderDecision(True, "BUY", "SPY", 10, 100.0, 100.0, "accepted", "2026-01-03T15:00:00Z", execution_date="2026-01-03")
            second_buy = OrderDecision(True, "BUY", "SPY", 10, 101.0, 101.0, "accepted", "2026-01-04T15:00:00Z", execution_date="2026-01-04")
            partial_sell = OrderDecision(True, "SELL", "SPY", 10, 105.0, 105.0, "accepted", "2026-01-05T15:00:00Z", execution_date="2026-01-05")
            fetched = bars_from_closes([100.0, 101.0, 102.0, 103.0, 104.0], start=date(2026, 1, 3))

            with (
                patch.object(market_lab_review, "EVIDENCE_DIR", evidence_dir),
                patch.object(market_lab_review, "_load_accepted_decisions", return_value=[first_buy, second_buy, partial_sell]),
                patch.object(market_lab_review, "fetch_prices", return_value=(fetched, "cache")),
            ):
                diagnoses = market_lab_review.diagnose_new_mock_decisions(days=5)

            self.assertEqual(len(diagnoses), 1)
            self.assertEqual(diagnoses[0].entry_price, 101.0)
            self.assertEqual(diagnoses[0].entry_date, "2026-01-04")
    def test_review_script_skips_when_fetch_window_does_not_include_entry_bar(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_dir = Path(td) / "evidence"
            buy = OrderDecision(True, "BUY", "SPY", 10, 100.0, 100.0, "accepted", "2026-01-03T15:00:00Z", execution_date="2026-01-03")
            fetched = bars_from_closes([120.0, 121.0, 122.0], start=date(2026, 2, 1))

            with (
                patch.object(market_lab_review, "EVIDENCE_DIR", evidence_dir),
                patch.object(market_lab_review, "_load_accepted_decisions", return_value=[buy]),
                patch.object(market_lab_review, "fetch_prices", return_value=(fetched, "cache")),
            ):
                diagnoses = market_lab_review.diagnose_new_mock_decisions(days=3)

            self.assertEqual(diagnoses, [])


if __name__ == "__main__":
    unittest.main()
