from __future__ import annotations

import ast
from pathlib import Path

import pytest

from market_lab.agency_contracts import canonical_json, strict_json_loads
from market_lab.agency_policy import snapshot_protected_state
from market_lab.company_identity import IdentityStatus, IssuerRecord, SecurityRecord
from market_lab.company_intelligence import CompanyIntelligenceFixtureRow, load_company_intelligence_fixture

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "market_lab" / "fixtures" / "company_intelligence" / "slice1_identity_subset.jsonl"


def test_company_intelligence_fixture_is_nonempty_deterministic_and_zero_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def network_forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("company intelligence fixture attempted network access")

    monkeypatch.setattr("socket.socket", network_forbidden)
    rows = load_company_intelligence_fixture(FIXTURE)
    assert len(rows) == 3
    assert [row.case_id for row in rows] == ["active-common", "historical-symbol", "blocked-private"]
    assert all(isinstance(row, CompanyIntelligenceFixtureRow) for row in rows)
    assert all(canonical_json(row.to_dict()) == canonical_json(strict_json_loads(canonical_json(row.to_dict()))) for row in rows)
    assert any(row.expected_identity_status is IdentityStatus.RESOLVED and row.security is not None for row in rows)
    assert any(row.security and row.security.active_to is not None for row in rows)
    assert any(row.expected_identity_status is not IdentityStatus.RESOLVED or row.security is None for row in rows)


def test_product_code_does_not_touch_protected_state_or_import_execution_modules(tmp_path: Path) -> None:
    before = snapshot_protected_state(tmp_path)
    rows = load_company_intelligence_fixture(FIXTURE)
    assert {type(row.issuer) for row in rows} == {IssuerRecord}
    assert any(isinstance(row.security, SecurityRecord) for row in rows)
    after = snapshot_protected_state(tmp_path)
    assert after == before

    forbidden = {"broker", "options_data", "options_paper", "options_screeners", "portfolio_construction", "alpaca"}
    for path in (ROOT / "market_lab" / "company_intelligence.py", ROOT / "market_lab" / "company_identity.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported = {((node.module or "").split(".")[0])}
            else:
                continue
            assert imported.isdisjoint(forbidden), f"{path.name} imports execution module {imported & forbidden}"


def test_safety_mode_constant_remains_research_mock_only() -> None:
    rows = load_company_intelligence_fixture(FIXTURE)
    assert {row.safety_mode for row in rows} == {"research_mock_only"}
