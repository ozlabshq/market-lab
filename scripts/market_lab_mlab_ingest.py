#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from market_lab import mlab_ingest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a durable MLAB ingest lifecycle on a captured X/Twitter post directory.",
    )
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--run-root", type=Path, default=None)
    parser.add_argument("--owner", default="mlab-ingest")
    parser.add_argument("--network", action="store_true", help="allow network-backed fetch steps in SourceThesis")
    parser.add_argument("--days", type=int, default=260)
    return parser.parse_args()


def _print_artifact_paths(run_dir: Path) -> None:
    for path in [
        run_dir / "status.json",
        run_dir / "audit_log.jsonl",
        run_dir / "claims.json",
        run_dir / "analysis.json",
        run_dir / "analysis.md",
        run_dir / "evidence.jsonl",
        run_dir / "research_plan.md",
        run_dir / "independent_review.md",
        run_dir / "next_actions.json",
        run_dir / "final_brief.md",
    ]:
        print(f"artifact={path} exists={path.exists()}")


def _print_status_lines(status: dict) -> None:
    print(f"run_dir={status.get('run_root', '')}")
    print(f"run_id={status.get('run_id')}")
    print(f"stage={status.get('stage')}")
    print(f"next_action={status.get('next_action')}")
    print(f"next_owner={status.get('next_owner')}")
    print(f"verdict={status.get('verdict')}")

def main() -> int:
    args = parse_args()
    run_dir = mlab_ingest.run_ingest_from_capture(
        args.capture_dir,
        run_root=args.run_root,
        owner=args.owner,
        network=args.network,
        days=args.days,
    )
    status = mlab_ingest.read_status(run_dir)
    claims = mlab_ingest.read_claims(run_dir)

    _print_status_lines(status)
    print(f"claims={len(claims.get('claims', []))}")
    print(f"audit_events={len(mlab_ingest.read_audit_log(run_dir))}")
    print(f"run_root={args.run_root or '(default)'}")
    _print_artifact_paths(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
