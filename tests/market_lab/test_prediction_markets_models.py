from pathlib import Path
import json

import pytest

from market_lab.prediction_markets.errors import SchemaError
from market_lab.prediction_markets.models import normalize_descriptor, parse_json_bytes


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
