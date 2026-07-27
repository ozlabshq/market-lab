from pathlib import Path
import json

import pytest

from market_lab.prediction_markets.cli import main
from market_lab.prediction_markets.errors import PaperError, PaperIntegrityError, PaperNotAdmissibleError, PaperNotSyntheticError, PathEscapeError
from market_lab.prediction_markets.models import canonical_json_bytes, parse_json_bytes, sha256_hex
from market_lab.prediction_markets.paper import buy, init, portfolio, sell, settle
from market_lab.prediction_markets.store import import_descriptor


FIXTURES = Path(__file__).parent / "fixtures" / "prediction_markets"
MARKET = "synthetic_fixture:pm0_binary_open:rules_v1"


def _ready(root):
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    init(root, _d("1000.000000"), "2026-07-19T00:10:00Z")


def _d(value):
    from decimal import Decimal
    return Decimal(value)


def test_paper_required_e2e_lifecycle(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    bought = buy(root, MARKET, "YES", _d("10.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    assert bought["cash"] == "995.500000"
    settled = settle(root, MARKET, "YES", "2026-07-19T00:12:00Z")
    assert settled["payout"] == "10.000000"
    assert settled["cash"] == "1005.500000"
    assert settled["realized_pnl"] == "5.500000"
    state = portfolio(root)
    assert state["initial_cash"] == "1000.000000"
    assert state["positions"] == {}


@pytest.mark.parametrize(
    "call,error",
    [
        (lambda r: buy(r, MARKET, "YES", _d("1.000000"), _d("0.430000"), _d("0.010000"), "2026-07-19T00:11:00Z"), "limit price"),
        (lambda r: buy(r, MARKET, "YES", _d("1000.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z"), "depth"),
        (lambda r: buy(r, MARKET, "YES", _d("100.000000"), _d("0.440000"), _d("10.000000"), "2026-07-19T00:11:00Z"), "cash"),
        (lambda r: sell(r, MARKET, "YES", _d("1.000000"), _d("0.430000"), _d("0.010000"), "2026-07-19T00:11:00Z"), "naked"),
    ],
)
def test_paper_rejections_do_not_mutate(tmp_path, call, error):
    root = tmp_path / "prediction_markets"
    _ready(root)
    before = portfolio(root)
    events = root / "paper" / "events.jsonl"
    state = root / "paper" / "state.json"
    events_before = events.read_bytes()
    state_before = state.read_bytes()
    events_mtime = events.stat().st_mtime_ns
    state_mtime = state.stat().st_mtime_ns
    with pytest.raises(PaperError, match=error):
        call(root)
    assert portfolio(root) == before
    assert events.read_bytes() == events_before
    assert state.read_bytes() == state_before
    assert events.stat().st_mtime_ns == events_mtime
    assert state.stat().st_mtime_ns == state_mtime


def test_duplicate_settlement_and_tamper_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    buy(root, MARKET, "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    settle(root, MARKET, "YES", "2026-07-19T00:12:00Z")
    with pytest.raises(PaperError, match="already settled"):
        settle(root, MARKET, "YES", "2026-07-19T00:13:00Z")
    events = root / "paper" / "events.jsonl"
    events.write_text(events.read_text(encoding="utf-8").replace("PAPER_BUY_FILLED", "PAPER_BUY_TAMPERED"), encoding="utf-8")
    with pytest.raises(PaperIntegrityError):
        portfolio(root)
    with pytest.raises(PaperIntegrityError):
        buy(root, MARKET, "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:14:00Z")


def test_non_synthetic_market_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    data = parse_json_bytes((FIXTURES / "binary_open_valid.json").read_bytes())
    data["provider_id"] = "synthetic_fixture_alt"
    data["legal_entity_id"] = "synthetic_fixture_alt"
    data["provider_market_id"] = "pm0_binary_open_alt"
    fixture = tmp_path / "non_synthetic.json"
    fixture.write_text(json.dumps(data), encoding="utf-8")
    import_descriptor(root, fixture)
    init(root, _d("1000.000000"), "2026-07-19T00:10:00Z")
    with pytest.raises(PaperNotSyntheticError):
        buy(root, "synthetic_fixture_alt:pm0_binary_open_alt:rules_v1", "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")


def test_settlement_requires_pm0_verification_and_research_admissible(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_missing_rules.json")
    init(root, _d("1000.000000"), "2026-07-19T00:10:00Z")
    with pytest.raises(PaperNotAdmissibleError):
        settle(root, "synthetic_fixture:pm0_binary_missing_rules:rules_v1", "YES", "2026-07-19T00:11:00Z")
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    next((root / "raw" / "sha256").glob("*/*/manifest.json")).unlink()
    with pytest.raises(PaperNotAdmissibleError):
        settle(root, MARKET, "YES", "2026-07-19T00:12:00Z")


def test_void_or_nonstandard_settlement_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_void_or_nonstandard.json")
    init(root, _d("1000.000000"), "2026-07-19T00:10:00Z")
    with pytest.raises(PaperNotAdmissibleError):
        settle(root, "synthetic_fixture:pm0_binary_void_nonstandard:rules_v1", "YES", "2026-07-19T00:11:00Z")


def test_buy_after_settlement_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    buy(root, MARKET, "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    settle(root, MARKET, "YES", "2026-07-19T00:12:00Z")
    with pytest.raises(PaperError, match="already settled"):
        buy(root, MARKET, "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:13:00Z")


def test_bad_timestamp_and_event_id_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    with pytest.raises(PaperError):
        init(root, _d("1000.000000"), "Z")
    _ready(root)
    events = root / "paper" / "events.jsonl"
    rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    rows[0]["event_id"] = "0" * 64
    body = dict(rows[0])
    body.pop("event_hash")
    rows[0]["event_hash"] = sha256_hex(canonical_json_bytes(body))
    state = root / "paper" / "state.json"
    state_data = json.loads(state.read_text(encoding="utf-8"))
    state_data["last_event_hash"] = rows[-1]["event_hash"]
    events.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows) + "\n", encoding="utf-8")
    state.write_bytes(canonical_json_bytes(state_data) + b"\n")
    with pytest.raises(PaperIntegrityError):
        portfolio(root)


def test_backdated_buy_is_rejected_before_append(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    buy(root, MARKET, "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    events = root / "paper" / "events.jsonl"
    state = root / "paper" / "state.json"
    before_events = events.read_bytes()
    before_state = state.read_bytes()
    before_events_mtime = events.stat().st_mtime_ns
    before_state_mtime = state.stat().st_mtime_ns
    with pytest.raises(PaperIntegrityError):
        buy(root, MARKET, "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:10:30Z")
    assert events.read_bytes() == before_events
    assert state.read_bytes() == before_state
    assert events.stat().st_mtime_ns == before_events_mtime
    assert state.stat().st_mtime_ns == before_state_mtime


def test_rehashed_buy_arithmetic_forgery_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    buy(root, MARKET, "YES", _d("10.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    events = root / "paper" / "events.jsonl"
    rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    rows[1]["payload"]["gross"] = "0.400000"
    rows = _rehash_chain(rows)
    events.write_text("\n".join(canonical_json_bytes(row).decode("utf-8") for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(PaperIntegrityError, match="financial identity"):
        portfolio(root)


def test_rehashed_over_ask_depth_buy_rejected_by_portfolio_and_later_mutation(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    buy(root, MARKET, "YES", _d("10.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    events = root / "paper" / "events.jsonl"
    state = root / "paper" / "state.json"
    before_events = events.read_bytes()
    before_state = state.read_bytes()
    rows = [json.loads(line) for line in before_events.decode("utf-8").splitlines()]
    rows[1]["payload"]["quantity"] = "101.000000"
    rows[1]["payload"]["gross"] = "44.440000"
    rows[1]["payload"]["fee"] = "1.010000"
    rows = _rehash_chain(rows)
    events.write_text("\n".join(canonical_json_bytes(row).decode("utf-8") for row in rows) + "\n", encoding="utf-8")
    forged_events = events.read_bytes()
    forged_state = state.read_bytes()
    events_mtime = events.stat().st_mtime_ns
    state_mtime = state.stat().st_mtime_ns
    with pytest.raises(PaperIntegrityError, match="ask depth"):
        portfolio(root)
    with pytest.raises(PaperIntegrityError, match="ask depth"):
        buy(root, MARKET, "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:12:00Z")
    assert events.read_bytes() == forged_events
    assert state.read_bytes() == forged_state
    assert events.stat().st_mtime_ns == events_mtime
    assert state.stat().st_mtime_ns == state_mtime
    assert before_events != forged_events
    assert before_state == forged_state


def test_rehashed_over_bid_depth_sell_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    buy(root, MARKET, "YES", _d("100.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    buy(root, MARKET, "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:12:00Z")
    sell(root, MARKET, "YES", _d("1.000000"), _d("0.430000"), _d("0.010000"), "2026-07-19T00:13:00Z")
    events = root / "paper" / "events.jsonl"
    rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    rows[-1]["payload"]["quantity"] = "101.000000"
    rows[-1]["payload"]["gross"] = "43.430000"
    rows[-1]["payload"]["fee"] = "1.010000"
    rows = _rehash_chain(rows)
    events.write_text("\n".join(canonical_json_bytes(row).decode("utf-8") for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(PaperIntegrityError, match="bid depth"):
        portfolio(root)


def test_exactly_at_displayed_depth_buy_is_accepted(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    buy(root, MARKET, "YES", _d("100.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    state = portfolio(root)
    assert state["positions"][MARKET + ":YES"]["quantity"] == "100.000000"


def test_rehashed_settlement_payout_forgery_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    buy(root, MARKET, "YES", _d("10.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    settle(root, MARKET, "YES", "2026-07-19T00:12:00Z")
    events = root / "paper" / "events.jsonl"
    rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    rows[-1]["payload"]["payout"] = "1.000000"
    rows = _rehash_chain(rows)
    events.write_text("\n".join(canonical_json_bytes(row).decode("utf-8") for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(PaperIntegrityError, match="payout mismatch"):
        portfolio(root)


def test_post_settlement_replay_event_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    _ready(root)
    buy(root, MARKET, "YES", _d("1.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
    settle(root, MARKET, "YES", "2026-07-19T00:12:00Z")
    events = root / "paper" / "events.jsonl"
    rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    forged = {
        "schema_version": "mlab-pm-paper-event.v1",
        "event_type": "PAPER_BUY_FILLED",
        "observed_at_utc": "2026-07-19T00:13:00Z",
        "previous_event_hash": rows[-1]["event_hash"],
        "payload": {
            "market_key": MARKET, "outcome": "YES", "quantity": "1.000000",
            "price": "0.440000", "fee_per_contract": "0.010000",
            "gross": "0.440000", "fee": "0.010000", "synthetic_top_of_book": True,
            "snapshot_id": rows[1]["payload"]["snapshot_id"],
        },
    }
    forged["event_id"] = sha256_hex(canonical_json_bytes(forged))
    forged["event_hash"] = sha256_hex(canonical_json_bytes(forged))
    with events.open("ab") as handle:
        handle.write(canonical_json_bytes(forged) + b"\n")
    with pytest.raises(PaperIntegrityError, match="after market settlement"):
        portfolio(root)


def test_orphan_state_and_paper_symlink_rejected(tmp_path):
    root = tmp_path / "prediction_markets"
    (root / "paper").mkdir(parents=True)
    (root / "paper" / "state.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PaperIntegrityError):
        init(root, _d("1000.000000"), "2026-07-19T00:10:00Z")
    root2 = tmp_path / "prediction_markets2"
    outside = tmp_path / "outside"
    outside.mkdir()
    root2.mkdir()
    (root2 / "paper").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathEscapeError):
        init(root2, _d("1000.000000"), "2026-07-19T00:10:00Z")


def test_paper_cli_lifecycle(tmp_path):
    root = tmp_path / "prediction_markets"
    assert main(["--root", str(root), "import", "--input", str(FIXTURES / "binary_open_valid.json")]) == 0
    assert main(["--root", str(root), "paper", "init", "--cash", "1000.000000", "--observed-at", "2026-07-19T00:10:00Z"]) == 0
    assert main(["--root", str(root), "paper", "buy", MARKET, "--outcome", "YES", "--quantity", "10.000000", "--limit-price", "0.440000", "--fee-per-contract", "0.010000", "--observed-at", "2026-07-19T00:11:00Z"]) == 0
    assert main(["--root", str(root), "paper", "settle", MARKET, "--winning-outcome", "YES", "--observed-at", "2026-07-19T00:12:00Z"]) == 0
    assert main(["--root", str(root), "paper", "ledger"]) == 0


def test_paper_replay_is_deterministic(tmp_path):
    outputs = []
    for idx in range(2):
        root = tmp_path / f"prediction_markets_{idx}"
        _ready(root)
        buy(root, MARKET, "YES", _d("10.000000"), _d("0.440000"), _d("0.010000"), "2026-07-19T00:11:00Z")
        settle(root, MARKET, "YES", "2026-07-19T00:12:00Z")
        outputs.append(((root / "paper" / "events.jsonl").read_bytes(), (root / "paper" / "state.json").read_bytes()))
    assert outputs[0] == outputs[1]


def _rehash_chain(rows):
    prev = None
    out = []
    for row in rows:
        body = {k: v for k, v in row.items() if k not in {"event_id", "event_hash"}}
        body["previous_event_hash"] = prev
        event_id = sha256_hex(canonical_json_bytes(body))
        event = {**body, "event_id": event_id}
        event["event_hash"] = sha256_hex(canonical_json_bytes(event))
        out.append(event)
        prev = event["event_hash"]
    return out
