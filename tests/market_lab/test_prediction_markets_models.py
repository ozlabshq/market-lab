from pathlib import Path
import json

import pytest

from market_lab.prediction_markets.errors import SchemaError
from market_lab.prediction_markets.models import normalize_descriptor, parse_json_bytes, canonical_json_bytes, sha256_hex, MarketSnapshotV1, OutcomeSnapshot, record_to_dict

FIXTURES = Path(__file__).parent / "fixtures" / "prediction_markets"

def _load(name):
    return parse_json_bytes((FIXTURES / name).read_bytes())


def test_valid_fixture_normalizes_to_research_admissible():
    record = normalize_descriptor(_load("binary_open_valid.json"))
    assert record.market_key == "synthetic_fixture:pm0_binary_open:rules_v1"
    assert record.admissibility == "RESEARCH_ADMISSIBLE"
    assert record.outcomes[0].best_ask is not None
    assert record.normalized_record_hash


def test_missing_rules_downgrades_to_quote_admissible():
    record = normalize_descriptor(_load("binary_missing_rules.json"))
    assert record.admissibility == "QUOTE_ADMISSIBLE"
    assert record.inadmissibility_reasons == ("MISSING_RULES",)


def test_malformed_price_rejected():
    with pytest.raises(SchemaError):
        normalize_descriptor(_load("binary_malformed_prices.json"))


def test_unknown_field_rejected():
    data = _load("binary_open_valid.json")
    data["unexpected"] = True
    with pytest.raises(SchemaError):
        normalize_descriptor(data)


def test_closed_not_final_preserves_closed_status_without_resolution_claim():
    record = normalize_descriptor(_load("binary_closed_not_final.json"))
    assert record.status == "CLOSED"
    assert record.admissibility == "RESEARCH_ADMISSIBLE"


def test_rule_revision_changes_market_key():
    first = normalize_descriptor(_load("binary_open_valid.json"))
    second = normalize_descriptor(_load("binary_rule_revision.json"))
    assert first.provider_market_id == second.provider_market_id
    assert first.market_key != second.market_key

# NEW TESTS BEGIN HERE

def test_dto_frozen_immutable():
    record = normalize_descriptor(_load("binary_open_valid.json"))
    with pytest.raises(Exception):
        record.status = "VOID"
    out = record.outcomes[0]
    with pytest.raises(Exception):
        out.best_bid = None


def test_decimal_enforcement():
    record = normalize_descriptor(_load("binary_open_valid.json"))
    assert isinstance(record.payout_unit, type(record.outcomes[0].best_bid))
    for out in record.outcomes:
        if out.best_bid is not None:
            assert isinstance(out.best_bid, type(record.payout_unit))
        if out.best_ask is not None:
            assert isinstance(out.best_ask, type(record.payout_unit))
        if out.last is not None:
            assert isinstance(out.last, type(record.payout_unit))
        if out.bid_size is not None:
            assert isinstance(out.bid_size, type(record.payout_unit))
        if out.ask_size is not None:
            assert isinstance(out.ask_size, type(record.payout_unit))


def test_canonical_json_and_hash_stable_and_consistent():
    record = normalize_descriptor(_load("binary_open_valid.json"))
    rec_dict = record_to_dict(record)
    json_a = canonical_json_bytes(rec_dict)
    hash_a = sha256_hex(json_a)
    # Reorder dictionary with sorted keys for B
    rec_dict2 = {k: rec_dict[k] for k in sorted(rec_dict.keys(), reverse=True)}
    json_b = canonical_json_bytes(rec_dict2)
    hash_b = sha256_hex(json_b)
    assert json_a == json_b
    assert hash_a == hash_b


def test_admissibility_entity_identity_restrictions():
    data = _load("binary_open_valid.json")
    # Try patching forbidden/generic identities
    for field in ["provider_id", "legal_entity_id", "venue_id", "api_surface_id"]:
        data_bad = dict(data)
        data_bad[field] = "polymarket"
        with pytest.raises(SchemaError):
            normalize_descriptor(data_bad)
        data_bad[field] = "unknown"
        with pytest.raises(SchemaError):
            normalize_descriptor(data_bad)
        data_bad[field] = "entity:alias"
        with pytest.raises(SchemaError):
            normalize_descriptor(data_bad)

    # Passes with explicit synthetic_fixture identity
    record = normalize_descriptor(data)
    assert record.provider_id == "synthetic_fixture"
