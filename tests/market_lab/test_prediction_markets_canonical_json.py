import pytest
import json
from market_lab.prediction_markets.models import canonical_json_bytes, sha256_hex

class DTO:
    def __init__(self, a, b):
        self.a = a
        self.b = b
    def asdict(self):
        return {'a': self.a, 'b': self.b}

def test_canonical_json_and_hash_equivalence_for_reordered_keys():
    dto1 = {'a': 1, 'b': 2}
    dto2 = {'b': 2, 'a': 1}  # keys intentionally reversed
    json1 = canonical_json_bytes(dto1)
    json2 = canonical_json_bytes(dto2)
    hash1 = sha256_hex(json1)
    hash2 = sha256_hex(json2)
    assert json1 == json2, f"Canonical JSON should be stable (got {json1!r} vs {json2!r})"
    assert hash1 == hash2, f"Hashes should be identical for equivalent dicts ({hash1} vs {hash2})"

def test_different_values_produce_different_hash():
    dto1 = {'a': 1, 'b': 2}
    dto2 = {'a': 1, 'b': 3}
    json1 = canonical_json_bytes(dto1)
    json2 = canonical_json_bytes(dto2)
    hash1 = sha256_hex(json1)
    hash2 = sha256_hex(json2)
    assert hash1 != hash2, "Canonical hash should differ if content is not identical"

def test_equivalent_dto_instances_serialize_equal_and_hash_equal():
    d1 = DTO(1, [1, 2, 3])
    d2 = DTO(1, [1, 2, 3])
    json1 = canonical_json_bytes(d1.asdict())
    json2 = canonical_json_bytes(d2.asdict())
    hash1 = sha256_hex(json1)
    hash2 = sha256_hex(json2)
    assert json1 == json2
    assert hash1 == hash2

def test_noncanonical_json_produces_canonical():
    data = json.loads(' { "b" : 9 ,  "a": 7 } ')
    canonical = canonical_json_bytes(data)
    # Output must not have stray whitespace or unsorted keys
    assert canonical == b'{"a":7,"b":9}'
