from __future__ import annotations

"""CLI for company-intelligence Slice 1."""

import argparse
import sys
from pathlib import Path
from typing import Any

from .agency_contracts import canonical_json
from .config import COMPANY_INTELLIGENCE_DIR
from .company_intelligence_runner import (
    build_frozen_company_run,
    run_company_intelligence_benchmark,
    publish_run,
    replay_run,
    validate_run,
    validate_web_evidence_input,
    DEFAULT_POLICY,
)


def _print(payload: dict[str, Any]) -> None:
    print(canonical_json(payload))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market_lab_company_intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--cases", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--output-root", default=str(COMPANY_INTELLIGENCE_DIR))
    build.add_argument("--builder-id", default="company-builder")

    validate = sub.add_parser("validate-run")
    validate.add_argument("--run-dir", required=True)
    validate.add_argument("--fail-on-gate", action="store_true")

    replay = sub.add_parser("replay")
    replay.add_argument("--run-dir", required=True)

    review = sub.add_parser("review-publish")
    review.add_argument("--run-dir", required=True)
    review.add_argument("--reviewer-id", required=True)
    review.add_argument("--decision", default="APPROVE")

    benchmark = sub.add_parser("benchmark")
    benchmark.add_argument("--lane", choices=("frozen", "chaos"), default="frozen")
    benchmark.add_argument("--cases", required=True)
    benchmark.add_argument("--fail-on-gate", action="store_true")

    shadow = sub.add_parser("live-shadow")
    shadow.add_argument("--input-root", required=True)
    shadow.add_argument("--as-of-utc", required=True)
    shadow.add_argument("--allow-live", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        _print(build_frozen_company_run(cases_path=Path(args.cases), output_root=Path(args.output_root), run_id=args.run_id, builder_id=args.builder_id))
        return 0
    if args.command == "validate-run":
        result = validate_run(Path(args.run_dir))
        _print(result)
        return 1 if args.fail_on_gate and not result["ok"] else 0
    if args.command == "replay":
        _print(replay_run(Path(args.run_dir)))
        return 0
    if args.command == "review-publish":
        _print(publish_run(Path(args.run_dir), reviewer_id=args.reviewer_id, decision=args.decision))
        return 0
    if args.command == "benchmark":
        result = run_company_intelligence_benchmark(Path(args.cases), lane=args.lane, fail_on_gate=args.fail_on_gate)
        _print(result)
        return 1 if not result["ok"] else 0
    if args.command == "live-shadow":
        if not args.allow_live:
            _print({"ok": False, "reason_codes": ["LIVE_RESEARCH_NOT_OPTED_IN"]})
            return 2
        result = validate_web_evidence_input(Path(args.input_root), "live", args.as_of_utc, DEFAULT_POLICY)
        _print(result.to_dict())
        return 0 if result.status == "ACCEPTED" else 1
    parser.error("unhandled command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
