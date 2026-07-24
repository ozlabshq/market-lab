from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType

import pytest

from market_lab.valuation_contracts import FORMULA_REGISTRY, decimal_value, stable_id


def test_stable_id_is_order_independent_domain_separated_and_float_strict() -> None:
    left = stable_id("mlab-candidate-id.v1", {"issuer_id": "ab", "security_id": "c"})
    reordered = stable_id("mlab-candidate-id.v1", {"security_id": "c", "issuer_id": "ab"})
    ambiguous = stable_id("mlab-candidate-id.v1", {"issuer_id": "a", "security_id": "bc"})
    other_domain = stable_id("mlab-valuation-id.v1", {"issuer_id": "ab", "security_id": "c"})

    assert left == reordered
    assert len(left) == 64
    assert len({left, ambiguous, other_domain}) == 3
    with pytest.raises(ValueError, match="binary floats"):
        stable_id("mlab-candidate-id.v1", {"value": 1.5})


def test_decimal_values_and_formula_registry_are_exact_and_immutable() -> None:
    assert decimal_value("1.2300") == Decimal("1.2300")
    with pytest.raises(TypeError, match="binary floats"):
        decimal_value(1.23)
    assert isinstance(FORMULA_REGISTRY, MappingProxyType)
    assert {
        "enterprise_value.lease_adjusted.v1",
        "wacc.multi_component_gross_capital.v1",
        "comparable_implied_value.v1",
        "fcff_dcf.gordon.lease_adjusted.v1",
        "terminal_value_share.pv_over_ev.v1",
    } <= set(FORMULA_REGISTRY)
    with pytest.raises(TypeError):
        FORMULA_REGISTRY["new"] = FORMULA_REGISTRY["comparable_implied_value.v1"]  # type: ignore[index]
