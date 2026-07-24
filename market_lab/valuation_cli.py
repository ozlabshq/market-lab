from __future__ import annotations

"""CLI adapter for the research-only valuation and memo engine."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Sequence

from .valuation_benchmark import run_valuation_benchmark
from .valuation_runner import build_valuation_run, review_valuation_run, verify_valuation_run


def _dump(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _resolve_cutoff(value: str) -> str:
    if value == "NOW":
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def _build(args: argparse.Namespace) -> int:
    try:
        result = build_valuation_run(
            run_dir=Path(args.run_dir),
            output_dir=Path(args.output_dir),
            candidate_id=args.candidate_id,
            analysis_cutoff_utc=_resolve_cutoff(args.analysis_cutoff),
            mode=args.mode,
            forecast_years=args.forecast_years,
            builder_id=args.builder_id,
        )
    except (OSError, ValueError) as exc:
        _dump({"status": "BLOCKED", "reason": str(exc)})
        return 2
    _dump(result)
    return 4 if args.require_approvable and result["status"] != "APPROVED_RESEARCH" else 0


def _verify(args: argparse.Namespace) -> int:
    result = verify_valuation_run(
        Path(args.output_dir),
        require_independent_review=args.require_independent_review,
        review_authority_dir=Path(args.review_authority_dir) if args.review_authority_dir else None,
    )
    _dump(result)
    return 0 if result["ok"] else 3


def _review(args: argparse.Namespace) -> int:
    try:
        result = review_valuation_run(
            Path(args.output_dir),
            reviewer_id=args.reviewer_id,
            decision=args.decision,
            review_authority_dir=Path(args.review_authority_dir) if args.review_authority_dir else None,
        )
    except (OSError, ValueError) as exc:
        _dump({"status": "REVIEW_BLOCKED", "reason": str(exc)})
        return 4
    _dump(result)
    return 0 if result["status"] == "APPROVED_RESEARCH" else 4


def _benchmark(args: argparse.Namespace) -> int:
    try:
        result = run_valuation_benchmark(Path(args.fixture), fail_on_gate=args.fail_on_gate)
    except (OSError, ValueError) as exc:
        _dump({"status": "BENCHMARK_FAILED", "reason": str(exc)})
        return 5
    _dump(result)
    return 0 if result["ok"] else 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market_lab_valuation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--run-dir", required=True)
    build.add_argument("--candidate-id", required=True)
    build.add_argument("--analysis-cutoff", required=True)
    build.add_argument("--mode", choices=("frozen", "live"), default="frozen")
    build.add_argument("--forecast-years", type=int, default=5)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--builder-id", default="valuation-builder")
    build.add_argument("--require-approvable", action="store_true")
    build.set_defaults(func=_build)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--output-dir", required=True)
    verify.add_argument("--require-provenance", action="store_true")
    verify.add_argument("--require-cutoff-integrity", action="store_true")
    verify.add_argument("--require-no-false-precision", action="store_true")
    verify.add_argument("--require-independent-review", action="store_true")
    verify.add_argument("--require-zero-execution-side-effects", action="store_true")
    verify.add_argument("--review-authority-dir")
    verify.set_defaults(func=_verify)

    review = subparsers.add_parser("review")
    review.add_argument("--output-dir", required=True)
    review.add_argument("--reviewer-id", required=True)
    review.add_argument("--decision", choices=("APPROVE", "REJECT"), required=True)
    review.add_argument("--review-authority-dir")
    review.set_defaults(func=_review)

    benchmark = subparsers.add_parser("benchmark")
    benchmark.add_argument("--fixture", required=True)
    benchmark.add_argument("--fail-on-gate", action="store_true")
    benchmark.set_defaults(func=_benchmark)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
