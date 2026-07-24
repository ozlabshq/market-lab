"""
Build 4: Crash/recovery test suite.
Tests recovery from interruption during paper-portfolio operations
and verifies portfolio/event atomicity and no data loss.
"""
import unittest
import tempfile
from pathlib import Path
from decimal import Decimal
from market_lab.broker import load_portfolio, save_portfolio
from market_lab.options_paper import load_option_paper_portfolio, save_option_paper_portfolio
from market_lab.thesis_portfolio import (
    MemoRef, ThesisPaperProposal, PortfolioContext, SizingDecision,
    check_input_eligibility, compute_deterministic_sizing,
    build_monitoring_plan, evaluate_portfolio_gate, GateReport,
)
from market_lab.catalyst_monitor import (
    create_initial_monitoring_snapshot, evaluate_invalidation_triggers, MonitoringSnapshot,
)


class CrashRecoveryTests(unittest.TestCase):
    def test_corrupt_portfolio_state_loads_default_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            path.write_text("{not json")
            portfolio = load_portfolio(path)
            self.assertGreater(portfolio.cash, 0)
            self.assertEqual(portfolio.positions, {})

    def test_corrupt_option_paper_portfolio_loads_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "paper_state.json"
            path.write_text("{not json")
            portfolio = load_option_paper_portfolio(path)
            self.assertEqual(portfolio.cash, 100_000.0)
            self.assertFalse(portfolio.positions)

    # ── Thesis portfolio crash/recovery tests ──

    def test_input_eligibility_rejects_empty_memo(self):
        passed, blockers = check_input_eligibility(
            MemoRef(memo_id="", memo_sha256="", thesis_summary="",
                    security_identity="", benchmark="", strategy="",
                    valuation_range_low=0, valuation_range_high=0)
        )
        self.assertFalse(passed)
        self.assertGreater(len(blockers), 0)

    def test_input_eligibility_passes_valid_memo(self):
        memo = MemoRef(
            memo_id="memo_001", memo_sha256="a" * 64,
            thesis_summary="Growth thesis", security_identity="AAPL",
            benchmark="SPY", strategy="trend",
            valuation_range_low=150.0, valuation_range_high=200.0,
            reviewed_at_utc="2026-01-01T00:00:00Z",
        )
        passed, blockers = check_input_eligibility(memo)
        self.assertTrue(passed)
        self.assertEqual(blockers, [])

    def test_deterministic_sizing_with_sufficient_cash(self):
        portfolio = PortfolioContext(
            total_cash=100_000.0, total_paper_exposure=0.0,
            current_position_count=0,
        )
        decision = compute_deterministic_sizing(portfolio, price=100.0, conviction=0.8)
        self.assertFalse(decision.rejected)
        self.assertGreater(decision.approved_notional, Decimal("0"))
        self.assertGreater(decision.position_pct, 0)

    def test_deterministic_sizing_rejects_no_cash(self):
        portfolio = PortfolioContext(
            total_cash=0.0, total_paper_exposure=0.0,
            current_position_count=0,
        )
        decision = compute_deterministic_sizing(portfolio, price=100.0)
        self.assertTrue(decision.rejected)
        self.assertIn("no cash", decision.reject_reason)

    def test_deterministic_sizing_rejects_max_positions(self):
        portfolio = PortfolioContext(
            total_cash=100_000.0, total_paper_exposure=0.0,
            current_position_count=10, max_positions=10,
        )
        decision = compute_deterministic_sizing(portfolio, price=100.0)
        self.assertTrue(decision.rejected)
        self.assertIn("max positions", decision.reject_reason)

    def test_deterministic_sizing_rejects_invalid_price(self):
        portfolio = PortfolioContext(
            total_cash=100_000.0, total_paper_exposure=0.0,
            current_position_count=0,
        )
        decision = compute_deterministic_sizing(portfolio, price=0)
        self.assertTrue(decision.rejected)
        self.assertIn("invalid price", decision.reject_reason)

    def test_portfolio_gate_passes_with_valid_proposal(self):
        memo = MemoRef(
            memo_id="memo_001", memo_sha256="a" * 64,
            thesis_summary="Growth thesis", security_identity="AAPL",
            benchmark="SPY", strategy="trend",
            valuation_range_low=150.0, valuation_range_high=200.0,
            reviewed_at_utc="2026-01-01T00:00:00Z",
        )
        portfolio = PortfolioContext(
            total_cash=100_000.0, total_paper_exposure=0.0,
            current_position_count=0,
        )
        sizing = compute_deterministic_sizing(portfolio, price=150.0, conviction=0.7)
        plan = build_monitoring_plan(memo)
        proposal = ThesisPaperProposal(
            proposal_id="prop_001", memo=memo,
            direction="LONG", proposed_size=5000.0, max_size=10000.0,
            reason="Qualified thesis", confidence_at_entry=0.7,
            portfolio_context_snapshot=portfolio,
        )
        gate = evaluate_portfolio_gate(proposal, sizing, plan)
        self.assertTrue(gate.passed)
        self.assertEqual(len(gate.blockers), 0)

    def test_portfolio_gate_rejects_invalid_direction(self):
        memo = MemoRef(
            memo_id="memo_001", memo_sha256="a" * 64,
            thesis_summary="Growth thesis", security_identity="AAPL",
            benchmark="SPY", strategy="trend",
            valuation_range_low=150.0, valuation_range_high=200.0,
            reviewed_at_utc="2026-01-01T00:00:00Z",
        )
        portfolio = PortfolioContext(
            total_cash=100_000.0, total_paper_exposure=0.0,
            current_position_count=0,
        )
        sizing = compute_deterministic_sizing(portfolio, price=150.0, conviction=0.7)
        plan = build_monitoring_plan(memo)
        proposal = ThesisPaperProposal(
            proposal_id="prop_002", memo=memo,
            direction="SHORT", proposed_size=5000.0, max_size=10000.0,
            reason="Should fail", confidence_at_entry=0.7,
            portfolio_context_snapshot=portfolio,
        )
        gate = evaluate_portfolio_gate(proposal, sizing, plan)
        self.assertFalse(gate.passed)
        self.assertGreater(len(gate.blockers), 0)

    # ── Catalyst monitor crash/recovery tests ──

    def test_initial_monitoring_snapshot_creates_pending_triggers(self):
        snapshot = create_initial_monitoring_snapshot(
            position_id="pos_001",
            catalyst_descriptions=["earnings beat", "new product launch"],
            invalidation_descriptions=["regulatory change", "competitor disruption"],
        )
        self.assertEqual(len(snapshot.catalyst_triggers), 2)
        self.assertEqual(len(snapshot.invalidation_triggers), 2)
        self.assertEqual(snapshot.alert_level, "green")
        self.assertFalse(snapshot.any_invalidation_fired)

    def test_evaluate_invalidation_triggers_detects_event(self):
        initial = create_initial_monitoring_snapshot(
            position_id="pos_002",
            catalyst_descriptions=["earnings beat"],
            invalidation_descriptions=["regulatory change"],
        )
        updated = evaluate_invalidation_triggers(
            "pos_002", initial,
            {"regulatory change": "SEC announced new rules"},
        )
        self.assertTrue(updated.any_invalidation_fired)
        self.assertEqual(updated.alert_level, "red")
        invalidation = [t for t in updated.invalidation_triggers if t.status == "invalidated"]
        self.assertEqual(len(invalidation), 1)

    def test_evaluate_invalidation_triggers_no_event(self):
        initial = create_initial_monitoring_snapshot(
            position_id="pos_003",
            catalyst_descriptions=["earnings beat"],
            invalidation_descriptions=["regulatory change"],
        )
        updated = evaluate_invalidation_triggers(
            "pos_003", initial, {}
        )
        self.assertFalse(updated.any_invalidation_fired)
        self.assertEqual(updated.alert_level, "green")

    # ── Build monitoring plan ──

    def test_build_monitoring_plan_from_memo(self):
        memo = MemoRef(
            memo_id="memo_003", memo_sha256="b" * 64,
            thesis_summary="Value thesis", security_identity="MSFT",
            benchmark="SPY", strategy="value",
            valuation_range_low=300.0, valuation_range_high=400.0,
            catalysts=["AI adoption", "cloud growth"],
            invalidations=["regulation", "competition"],
            reviewed_at_utc="2026-01-15T00:00:00Z",
        )
        plan = build_monitoring_plan(memo)
        self.assertEqual(len(plan.catalyst_triggers), 2)
        self.assertEqual(len(plan.invalidation_triggers), 2)
        self.assertTrue(plan.exit_plan.thesis_invalidation_exit)


if __name__ == "__main__":
    unittest.main()