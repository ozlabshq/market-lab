from __future__ import annotations

"""Command entry points for web evidence operations."""

import argparse
import json
from pathlib import Path

from .web_evidence import BudgetProfile, load_budget_profile
from .web_evidence_runner import check_health, collect_for_claims, run_benchmark, run_smoke, verify_run
from .web_evidence_store import write_atomic_json


def _path_arg(value: str) -> Path:
    return Path(value)


def _read_claims(path: Path) -> list[dict]:
    rows: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        rows.append(json.loads(raw))
    return rows


def cmd_health(args: argparse.Namespace) -> dict:
    result = check_health(profile=args.profile, include_optional=args.include_optional, require_core_ready=args.require_core_ready)
    return result


def cmd_smoke(args: argparse.Namespace) -> dict:
    run_dir = Path(args.run_dir)
    result = run_smoke(
        run_dir=run_dir,
        profile=args.profile,
        query=args.query,
        url=args.url,
        sec_cik=args.sec_cik,
        crossref_doi=args.crossref_doi,
        arxiv_id=args.arxiv_id,
        government_url=args.government_url,
    )
    return result


def cmd_collect(args: argparse.Namespace) -> dict:
    run_dir = Path(args.run_dir)
    claims = _read_claims(Path(args.claims))
    profile = args.profile
    result = collect_for_claims(
        run_dir=run_dir,
        claims=claims,
        profile=profile,
        run_id=args.run_id or run_dir.name,
        mode=args.mode,
        max_claims=args.max_claims,
        budget_profile=load_budget_profile(profile),
    )
    return result


def cmd_verify_run(args: argparse.Namespace) -> dict:
    return verify_run(
        run_dir=Path(args.run_dir),
        require_snapshots=args.require_snapshots,
        require_counterevidence_coverage=args.require_counterevidence_coverage,
        require_audit_chain=args.require_audit_chain,
        require_zero_snippet_evidence=args.require_zero_snippet_evidence,
        require_zero_execution_side_effects=args.require_zero_execution_side_effects,
    )


def cmd_benchmark(args: argparse.Namespace) -> dict:
    return run_benchmark(
        Path(args.run_dir or Path(args.output).with_suffix("").as_posix() + "_run"),
        lane=args.lane,
        cases_path=Path(args.cases),
        output_path=Path(args.output),
        fail_on_gate=args.fail_on_gate,
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Web evidence toolkit")
    sub = p.add_subparsers(dest="command", required=True)

    hp = sub.add_parser("health", help="check provider health")
    hp.add_argument("--profile", default="keyless_standard")
    hp.add_argument("--output")
    hp.add_argument("--require-core-ready", action="store_true", dest="require_core_ready")
    hp.add_argument("--include-optional", action="store_true", default=True, dest="include_optional")

    sp = sub.add_parser("smoke", help="run smoke probes")
    sp.add_argument("--profile", default="keyless_standard")
    sp.add_argument("--run-dir", required=True)
    sp.add_argument("--output")
    sp.add_argument("--query")
    sp.add_argument("--url")
    sp.add_argument("--sec-cik")
    sp.add_argument("--crossref-doi")
    sp.add_argument("--arxiv-id")
    sp.add_argument("--government-url")

    cp = sub.add_parser("collect", help="collect evidence for claims")
    cp.add_argument("--profile", default="keyless_standard")
    cp.add_argument("--run-dir", required=True)
    cp.add_argument("--claims", required=True)
    cp.add_argument("--run-id", default=None)
    cp.add_argument("--mode", choices=["off", "live", "frozen"], default="off")
    cp.add_argument("--max-claims", type=int, default=None, dest="max_claims")

    vr = sub.add_parser("verify-run", help="verify evidence artifacts")
    vr.add_argument("--run-dir", required=True)
    vr.add_argument("--require-snapshots", action="store_true", default=False)
    vr.add_argument("--require-counterevidence-coverage", action="store_true", default=False)
    vr.add_argument("--require-audit-chain", action="store_true", default=False)
    vr.add_argument("--require-zero-snippet-evidence", action="store_true", default=False)
    vr.add_argument("--require-zero-execution-side-effects", action="store_true", default=False)

    bp = sub.add_parser("benchmark", help="run benchmark cases")
    bp.add_argument("--run-dir", required=False)
    bp.add_argument("--lane", required=True)
    bp.add_argument("--cases", required=True)
    bp.add_argument("--output", required=True)
    bp.add_argument("--fail-on-gate", action="store_true", default=False)

    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "health":
        payload = cmd_health(args)
    elif args.command == "smoke":
        payload = cmd_smoke(args)
    elif args.command == "collect":
        payload = cmd_collect(args)
    elif args.command == "verify-run":
        payload = cmd_verify_run(args)
    elif args.command == "benchmark":
        payload = cmd_benchmark(args)
    else:
        raise SystemExit("unknown command")

    output = getattr(args, "output", None)
    if output and args.command in {"health", "smoke"}:
        write_atomic_json(Path(output), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
