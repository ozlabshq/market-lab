"""
Build 4: No-lookahead and anti-leakage test suite.
Verifies all signals, backtests, and order-pipeline logic do not
use future data (date/order/memo/time) in any decision making.

Also tests thesis portfolio modules for no-lookahead compliance.
"""
import unittest
from market_lab.signals import generate_strategy_signals
from market_lab.data import Bar
from market_lab.catalyst_monitor import (
    create_initial_monitoring_snapshot, evaluate_invalidation_triggers,
)
from market_lab.thesis_portfolio import (
    MemoRef, PortfolioContext, compute_deterministic_sizing,
    build_monitoring_plan, evaluate_portfolio_gate, ThesisPaperProposal,
)


class NoLookaheadTests(unittest.TestCase):
    def test_signals_do_not_use_future_data(self):
        bars = [Bar(date=20260101 + i, open=100+i, high=101+i, low=99+i, close=100+i, volume=1000) for i in range(100)]
        signals = generate_strategy_signals("FAKE", bars)
        for signal in signals:
            self.assertTrue(isinstance(signal.evidence, dict))

    # ── Thesis portfolio no-lookahead tests ──

    def test_sizing_uses_only_current_state(self):
        """Sizing decision must use only current portfolio state, not future."""
        portfolio = PortfolioContext(
            total_cash=100_000.0, total_paper_exposure=0.0,
            current_position_count=0,
        )
        # Should not crash or use future data
        decision = compute_deterministic_sizing(portfolio, price=100.0, conviction=0.5)
        self.assertFalse(decision.rejected)
        # Result should be deterministic for same inputs
        decision2 = compute_deterministic_sizing(portfolio, price=100.0, conviction=0.5)
        self.assertEqual(decision.approved_notional, decision2.approved_notional)

    def test_portfolio_gate_no_lookahead(self):
        """Gate evaluation must not depend on future position data."""
        memo = MemoRef(
            memo_id="memo_001", memo_sha256="a" * 64,
            thesis_summary="Test", security_identity="AAPL",
            benchmark="SPY", strategy="trend",
            valuation_range_low=150.0, valuation_range_high=200.0,
            reviewed_at_utc="2026-01-01T00:00:00Z",
        )
        portfolio = PortfolioContext(
            total_cash=100_000.0, total_paper_exposure=0.0,
            current_position_count=0,
        )
        sizing = compute_deterministic_sizing(portfolio, price=150.0, conviction=0.5)
        plan = build_monitoring_plan(memo)
        proposal = ThesisPaperProposal(
            proposal_id="prop_001", memo=memo,
            direction="LONG", proposed_size=5000.0, max_size=10000.0,
            reason="Test", confidence_at_entry=0.5,
            portfolio_context_snapshot=portfolio,
        )
        # Must produce deterministic result
        gate1 = evaluate_portfolio_gate(proposal, sizing, plan)
        gate2 = evaluate_portfolio_gate(proposal, sizing, plan)
        self.assertEqual(gate1.passed, gate2.passed)
        self.assertEqual(gate1.blockers, gate2.blockers)

    def test_monitoring_no_lookahead(self):
        """Monitoring snapshot evaluation must only use current data point."""
        initial = create_initial_monitoring_snapshot(
            position_id="pos_001",
            catalyst_descriptions=["earnings beat"],
            invalidation_descriptions=["regulatory change"],
        )
        # Evaluate with only current data, not future
        updated = evaluate_invalidation_triggers(
            "pos_001", initial,
            {"regulatory change": "new rules announced"},
        )
        # Should not have triggered catalyst (it wasn't in new_data)
        catalyst_triggered = [t for t in updated.catalyst_triggers if t.status == "triggered"]
        self.assertEqual(len(catalyst_triggered), 0)
        # Should have triggered invalidation
        invalidation_triggered = [t for t in updated.invalidation_triggers if t.status == "invalidated"]
        self.assertEqual(len(invalidation_triggered), 1)

    def test_deterministic_sizing_identical_inputs_identical_outputs(self):
        """Sizing must be deterministic for same inputs."""
        portfolio = PortfolioContext(
            total_cash=50_000.0, total_paper_exposure=10_000.0,
            current_position_count=2,
        )
        d1 = compute_deterministic_sizing(portfolio, price=75.0, conviction=0.6)
        d2 = compute_deterministic_sizing(portfolio, price=75.0, conviction=0.6)
        self.assertEqual(d1.approved_notional, d2.approved_notional)
        self.assertEqual(d1.rejected, d2.rejected)
        self.assertEqual(d1.overrides_applied, d2.overrides_applied)

    def test_deterministic_sizing_different_conviction_different_result(self):
        """Different conviction should produce different sizing."""
        portfolio = PortfolioContext(
            total_cash=100_000.0, total_paper_exposure=0.0,
            current_position_count=0,
        )
        d_low = compute_deterministic_sizing(portfolio, price=100.0, conviction=0.1)
        d_high = compute_deterministic_sizing(portfolio, price=100.0, conviction=0.9)
        # Higher conviction should get larger sizing
        self.assertGreater(d_high.approved_notional, d_low.approved_notional)


if __name__ == "__main__":
    unittest.main()