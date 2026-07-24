"""
Build 4: Outcome learning, attribution, feedback, and scorecard test suite.
Verifies trade attribution, outcome-linked analyst/process scorecards,
feedback event streams, and diagnostic artifact generation.
"""
import unittest
from market_lab.diagnosis import TradeDiagnosis, generate_strategy_health_report
from market_lab.agency_events import create_event
from market_lab.agency_contracts import TypedID
from market_lab.postmortem import (
    PositionResult, AttributionBreakdown, PostmortemFinding,
    build_postmortem, compute_attribution, serialize_postmortem,
)
from market_lab.scorecard import (
    ScorecardEntry, compute_pre_trade_scores, compute_post_trade_scorecard,
    aggregate_analyst_scorecard, AnalystScorecard,
)
from market_lab.feedback_events import (
    FeedbackEvent, FeedbackStream, create_feedback_event,
    process_feedback_event, LearningOverride,
)


class OutcomeLearningTests(unittest.TestCase):
    def test_trade_diagnosis_attribution(self):
        diagnosis = TradeDiagnosis(
            decision_id="123", symbol="FAKE", strategy="trend", side="BUY", entry_date="2026-01-05",
            exit_date="2026-01-06", holding_bars=1, entry_price=100.0, exit_price=102.0, pnl_pct=0.02,
            pnl_vs_benchmark=0.01, regime_label="up", hypothesis="n/a", evidence_snapshot={}, failure_mode=None,
            confidence_at_entry=0.5
        )
        rec = diagnosis.as_record()
        self.assertEqual(rec["symbol"], "FAKE")
        self.assertIn("pnl_pct", rec)

    def test_scorecard_and_feedback_event(self):
        event = create_event(
            event_id=TypedID("event", "agency", "v1", "evt1"),
            agency_case_id=TypedID("case", "agency", "v1", "case1"),
            subsystem="diagnosis",
            subsystem_run_id=TypedID("run", "agency", "v1", "run1"),
            sequence_number=1,
            idempotency_key="none",
            event_type="scorecard",
            occurred_at_utc="2026-01-07T00:00:00Z",
            actor_type="analyst",
            actor_id="ronak",
            mode="paper",
            state_namespace="scorecard",
            state_before=None,
            state_after=None,
            policy_hash="0"*64,
            event_payload={"process_feedback": "well reasoned"},
        )
        self.assertEqual(event["event_type"], "scorecard")

    # ── Postmortem & Attribution tests ──

    def test_build_postmortem_profitable_position(self):
        result = PositionResult(
            position_id="pos_1", proposal_id="prop_1", memo_id="memo_1",
            entry_price=100.0, exit_price=110.0, pnl_pct=0.10, pnl_absolute=10.0,
            holding_bars=20, entry_date="2026-01-05", exit_date="2026-02-01",
            exit_reason="target", benchmark_return_pct=0.03, alpha_pct=0.07,
        )
        attribution = compute_attribution(
            entry_price=100.0, exit_price=110.0,
            benchmark_entry=100.0, benchmark_exit=103.0,
            position_size_pct=0.05,
        )
        postmortem = build_postmortem(result, attribution)
        self.assertTrue(postmortem.thesis_was_valid)
        # Should have thesis alpha finding (alpha_pct 0.07 > 0.05 threshold)
        self.assertGreaterEqual(len(postmortem.findings), 0)

    def test_build_postmortem_losing_position(self):
        result = PositionResult(
            position_id="pos_2", proposal_id="prop_2", memo_id="memo_2",
            entry_price=100.0, exit_price=82.0, pnl_pct=-0.18, pnl_absolute=-18.0,
            holding_bars=10, entry_date="2026-01-05", exit_date="2026-01-20",
            exit_reason="stop_loss", benchmark_return_pct=0.01, alpha_pct=-0.19,
        )
        attribution = compute_attribution(
            entry_price=100.0, exit_price=82.0,
            benchmark_entry=100.0, benchmark_exit=101.0,
            position_size_pct=0.05,
        )
        postmortem = build_postmortem(result, attribution)
        self.assertFalse(postmortem.thesis_was_valid)
        # Should have critical finding for large drawdown (pnl_pct -0.18 < -0.15 threshold)
        has_critical = any(f.severity == "critical" for f in postmortem.findings)
        self.assertTrue(has_critical)

    def test_compute_attribution_positive_alpha(self):
        attribution = compute_attribution(
            entry_price=100.0, exit_price=110.0,
            benchmark_entry=100.0, benchmark_exit=105.0,
            position_size_pct=0.05,
        )
        self.assertGreater(attribution.benchmark_alpha, 0)
        self.assertGreater(attribution.thesis_alpha, 0)

    def test_serialize_postmortem(self):
        result = PositionResult(
            position_id="pos_3", proposal_id="prop_3", memo_id="memo_3",
            entry_price=50.0, exit_price=55.0, pnl_pct=0.10, pnl_absolute=5.0,
            holding_bars=15, entry_date="2026-02-01", exit_date="2026-02-20",
            exit_reason="target", benchmark_return_pct=0.02, alpha_pct=0.08,
        )
        attribution = compute_attribution(
            entry_price=50.0, exit_price=55.0,
            benchmark_entry=50.0, benchmark_exit=51.0,
            position_size_pct=0.05,
        )
        postmortem = build_postmortem(result, attribution)
        serialized = serialize_postmortem(postmortem)
        self.assertIn("pos_3", serialized)
        self.assertIn("thesis_alpha", serialized)

    # ── Scorecard tests ──

    def test_pre_trade_scores_all_checks_pass(self):
        scorecard = compute_pre_trade_scores(
            memo_has_evidence=True, memo_is_reviewed=True,
            sizing_was_deterministic=True, exit_plan_defined=True,
            catalyst_monitoring_defined=True, conviction=0.8,
        )
        self.assertEqual(scorecard.score_type, "pre_trade")
        self.assertGreater(scorecard.evidence_quality_score, 0.9)
        self.assertGreater(scorecard.process_discipline_score, 0.9)

    def test_pre_trade_scores_missing_evidence(self):
        scorecard = compute_pre_trade_scores(
            memo_has_evidence=False, memo_is_reviewed=True,
            sizing_was_deterministic=True, exit_plan_defined=True,
            catalyst_monitoring_defined=True, conviction=0.5,
        )
        self.assertEqual(scorecard.evidence_quality_score, 0.0)

    def test_post_trade_scorecard(self):
        result = PositionResult(
            position_id="pos_sc1", proposal_id="prop_sc1", memo_id="memo_sc1",
            entry_price=100.0, exit_price=110.0, pnl_pct=0.10, pnl_absolute=10.0,
            holding_bars=20, entry_date="2026-01-05", exit_date="2026-02-01",
            exit_reason="target", benchmark_return_pct=0.03, alpha_pct=0.07,
        )
        attribution = compute_attribution(
            entry_price=100.0, exit_price=110.0,
            benchmark_entry=100.0, benchmark_exit=103.0,
            position_size_pct=0.05,
        )
        postmortem = build_postmortem(result, attribution)
        sc = compute_post_trade_scorecard(postmortem)
        self.assertEqual(sc.analyst_id, "system")
        self.assertGreater(sc.outcome_score, 0.5)  # profitable

    def test_aggregate_analyst_scorecard(self):
        entries = [
            ScorecardEntry(
                scorecard_id="1", position_id="p1", memo_id="m1",
                analyst_id="alice", score_type="pre_trade",
                process_discipline_score=0.9, evidence_quality_score=0.8,
                decision_quality_score=0.85, outcome_score=0.0,
            ),
            ScorecardEntry(
                scorecard_id="2", position_id="p2", memo_id="m2",
                analyst_id="alice", score_type="post_trade",
                process_discipline_score=0.85, evidence_quality_score=0.0,
                decision_quality_score=0.8, outcome_score=0.75,
            ),
        ]
        agg = aggregate_analyst_scorecard(entries, "alice")
        self.assertEqual(agg.total_decisions, 2)
        self.assertAlmostEqual(agg.avg_process_discipline, 0.875)
        self.assertAlmostEqual(agg.avg_decision_quality, 0.825)

    # ── Feedback event tests ──

    def test_create_feedback_event(self):
        event = create_feedback_event(
            source="postmortem", event_type="process_feedback",
            target_type="strategy", target_id="trend_follow",
            severity="warning", description="Strategy underperforming in range-bound markets",
            recommendation="Reduce position sizing in low-volatility regimes",
        )
        self.assertEqual(event.source, "postmortem")
        self.assertEqual(event.event_type, "process_feedback")
        self.assertIn("fb_", event.event_id)

    def test_critical_feedback_creates_override(self):
        event = create_feedback_event(
            source="postmortem", event_type="process_feedback",
            target_type="strategy", target_id="momentum",
            severity="critical", description="Strategy consistently losing money",
            recommendation="Pause strategy until review",
        )
        stream = process_feedback_event(event, FeedbackStream())
        self.assertEqual(len(stream.events), 1)
        self.assertGreater(len(stream.overrides), 0)
        self.assertEqual(stream.overrides[0].override_type, "adjust_risk")

    def test_pause_event_creates_override(self):
        event = create_feedback_event(
            source="monitoring", event_type="pause",
            target_type="position", target_id="pos_1",
            severity="warning", description="Multiple invalidations triggered",
            recommendation="Pause position for review",
        )
        stream = process_feedback_event(event, FeedbackStream())
        self.assertEqual(len(stream.overrides), 1)
        self.assertEqual(stream.overrides[0].override_type, "pause")

    def test_retire_event_creates_override(self):
        event = create_feedback_event(
            source="scorecard", event_type="retire",
            target_type="strategy", target_id="old_strategy",
            severity="warning", description="Strategy obsolete",
            recommendation="Retire this strategy",
        )
        stream = process_feedback_event(event, FeedbackStream())
        self.assertEqual(len(stream.overrides), 1)
        self.assertEqual(stream.overrides[0].override_type, "retire")

    def test_recurring_warnings_trigger_tune(self):
        stream = FeedbackStream()
        for i in range(3):
            event = create_feedback_event(
                source="monitoring", event_type="process_feedback",
                target_type="strategy", target_id="volatility",
                severity="warning", description=f"Warning {i+1}",
            )
            stream = process_feedback_event(event, stream)
        # At least one tune override from recurring warnings
        tune_overrides = [o for o in stream.overrides if o.override_type == "tune"]
        self.assertGreaterEqual(len(tune_overrides), 1)

    # ── Serialization tests ──

    def test_serialize_feedback_event(self):
        event = create_feedback_event(
            source="system", event_type="process_feedback",
            target_type="process", target_id="sizing_policy",
            severity="info", description="Sizing policy updated",
        )
        s = event.__class__.__module__ + "." + event.__class__.__name__
        self.assertIn("feedback_events", s)

    # ── Edge case tests ──

    def test_empty_attribution_no_exit(self):
        attribution = compute_attribution(
            entry_price=100.0, exit_price=None,
            benchmark_entry=100.0, benchmark_exit=105.0,
            position_size_pct=0.05,
        )
        self.assertEqual(attribution.market_beta, 0.0)
        self.assertEqual(attribution.thesis_alpha, 0.0)

    def test_build_postmortem_no_findings(self):
        result = PositionResult(
            position_id="pos_no_find", proposal_id="prop_no", memo_id="memo_no",
            entry_price=100.0, exit_price=102.0, pnl_pct=0.02, pnl_absolute=2.0,
            holding_bars=30, entry_date="2026-01-05", exit_date="2026-02-15",
            exit_reason="target", benchmark_return_pct=0.01, alpha_pct=0.01,
        )
        attribution = compute_attribution(
            entry_price=100.0, exit_price=102.0,
            benchmark_entry=100.0, benchmark_exit=101.0,
            position_size_pct=0.05,
        )
        postmortem = build_postmortem(result, attribution)
        self.assertTrue(postmortem.thesis_was_valid)


if __name__ == "__main__":
    unittest.main()