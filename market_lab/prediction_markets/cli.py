from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path
import sys

from market_lab.prediction_markets.config import prediction_data_root
from market_lab.prediction_markets.errors import PredictionMarketError, UsageError
from market_lab.prediction_markets.models import decimal_str, parse_decimal, record_to_dict
from market_lab.prediction_markets import paper
from market_lab.prediction_markets.report import write_report
from market_lab.prediction_markets.store import find_record, import_descriptor, load_records, verify


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _parser()
        args = parser.parse_args(argv)
        root = prediction_data_root(args.root)
        result, code = _run(args, root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return code
    except PredictionMarketError as exc:
        payload = {"error_code": exc.error_code, "message": exc.message}
        if exc.path:
            payload["path"] = exc.path
        if exc.details:
            payload["details"] = exc.details
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        if os.environ.get("MARKET_LAB_DEBUG") == "1":
            raise
        print(json.dumps({"error_code": "PM0_INTERNAL", "message": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 70


def _run(args, root: Path):
    if args.command == "import":
        result = import_descriptor(root, args.input)
        return result, _error_exit(result.get("error_code")) if result.get("quarantined") else 0
    if args.command == "list":
        records = [r for r in load_records(root) if (not args.status or r.status == args.status) and (not args.admissibility or r.admissibility == args.admissibility)]
        return [{"market_key": r.market_key, "snapshot_id": r.snapshot_id, "status": r.status, "admissibility": r.admissibility, "title": r.title} for r in records], 0
    if args.command == "show":
        return record_to_dict(find_record(root, args.market_key, args.snapshot_id)), 0
    if args.command == "verify":
        result = verify(root, strict=args.strict)
        return result, 0 if result["ok"] else 4
    if args.command == "report":
        return write_report(root), 0
    if args.command == "paper":
        return _paper(args, root), 0
    return {}, 2


def _paper(args, root: Path):
    if args.paper_command == "init":
        return paper.init(root, _dec(args.cash, "cash"), args.observed_at)
    if args.paper_command == "buy":
        return paper.buy(root, args.market_key, args.outcome, _dec(args.quantity, "quantity"), _dec(args.limit_price, "limit_price"), _dec(args.fee_per_contract, "fee_per_contract"), args.observed_at)
    if args.paper_command == "sell":
        return paper.sell(root, args.market_key, args.outcome, _dec(args.quantity, "quantity"), _dec(args.limit_price, "limit_price"), _dec(args.fee_per_contract, "fee_per_contract"), args.observed_at)
    if args.paper_command == "settle":
        return paper.settle(root, args.market_key, args.winning_outcome, args.observed_at)
    if args.paper_command == "portfolio":
        return paper.portfolio(root)
    if args.paper_command == "ledger":
        return paper.ledger(root)
    return {}


def _dec(value: str, field: str) -> Decimal:
    return parse_decimal(value, field, positive=True)


def _parser() -> argparse.ArgumentParser:
    p = _JSONArgumentParser(prog="market-lab-prediction", description="Offline frozen-fixture prediction markets; synthetic mock only; never live trading.")
    p.add_argument("--root", type=Path, default=None)
    sub = p.add_subparsers(dest="command", required=True, parser_class=_JSONArgumentParser)
    imp = sub.add_parser("import")
    imp.add_argument("--input", type=Path, required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--status")
    ls.add_argument("--admissibility")
    show = sub.add_parser("show")
    show.add_argument("market_key")
    show.add_argument("--snapshot-id")
    ver = sub.add_parser("verify")
    ver.add_argument("--strict", action="store_true")
    sub.add_parser("report")
    pp = sub.add_parser("paper", description="Synthetic mock only; never live trading.")
    ps = pp.add_subparsers(dest="paper_command", required=True, parser_class=_JSONArgumentParser)
    init_p = ps.add_parser("init")
    init_p.add_argument("--cash", required=True)
    init_p.add_argument("--observed-at", required=True)
    for name in ("buy", "sell"):
        cmd = ps.add_parser(name)
        cmd.add_argument("market_key")
        cmd.add_argument("--outcome", choices=("YES", "NO"), required=True)
        cmd.add_argument("--quantity", required=True)
        cmd.add_argument("--limit-price", required=True)
        cmd.add_argument("--fee-per-contract", required=True)
        cmd.add_argument("--observed-at", required=True)
    settle = ps.add_parser("settle")
    settle.add_argument("market_key")
    settle.add_argument("--winning-outcome", choices=("YES", "NO"), required=True)
    settle.add_argument("--observed-at", required=True)
    ps.add_parser("portfolio")
    ps.add_parser("ledger")
    return p


def _error_exit(error_code: str | None) -> int:
    return 4 if error_code in {"PM0_CONFLICT", "PM0_INTEGRITY", "PM0_PATH_ESCAPE", "PM1_INTEGRITY"} else 3


class _JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


if __name__ == "__main__":
    raise SystemExit(main())
