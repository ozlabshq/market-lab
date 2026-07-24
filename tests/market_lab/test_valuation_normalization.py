from __future__ import annotations

from market_lab.valuation_normalization import derive_normalized_financials, select_preferred_fact


def test_source_ladder_prefers_latest_available_amended_filing_without_cutoff_leakage() -> None:
    facts = [
        {
            "fact_id": "ir-revenue",
            "concept": "revenue",
            "period_end": "2025-12-31",
            "available_at_utc": "2026-01-10T00:00:00Z",
            "source_class": "issuer_ir",
            "value": "100",
        },
        {
            "fact_id": "sec-original",
            "concept": "revenue",
            "period_end": "2025-12-31",
            "available_at_utc": "2026-01-09T00:00:00Z",
            "source_class": "sec_xbrl",
            "accession": "original",
            "value": "101",
        },
        {
            "fact_id": "sec-amended",
            "concept": "revenue",
            "period_end": "2025-12-31",
            "available_at_utc": "2026-01-15T00:00:00Z",
            "source_class": "sec_xbrl",
            "accession": "amended",
            "amends_accession": "original",
            "value": "102",
        },
    ]

    before_amendment = select_preferred_fact(
        facts,
        concept="revenue",
        period_end="2025-12-31",
        analysis_cutoff_utc="2026-01-12T00:00:00Z",
    )
    after_amendment = select_preferred_fact(
        facts,
        concept="revenue",
        period_end="2025-12-31",
        analysis_cutoff_utc="2026-01-20T00:00:00Z",
    )

    assert before_amendment["fact_id"] == "sec-original"
    assert after_amendment["fact_id"] == "sec-amended"


def test_normalization_derives_lease_adjusted_ebitda_fcf_and_enterprise_value_exactly() -> None:
    result = derive_normalized_financials(
        {
            "operating_income": "100",
            "depreciation_amortization": "20",
            "operating_lease_expense": "5",
            "net_cash_from_operations": "90",
            "cash_capital_expenditures": "30",
            "market_cap": "1000",
            "borrowings": "100",
            "leases": "50",
            "preferred": "20",
            "noncontrolling_interest": "10",
            "cash": "40",
            "non_operating_investments": "5",
        },
        input_fact_ids={key: [f"fact-{key}"] for key in (
            "operating_income",
            "depreciation_amortization",
            "operating_lease_expense",
            "net_cash_from_operations",
            "cash_capital_expenditures",
            "market_cap",
            "borrowings",
            "leases",
            "preferred",
            "noncontrolling_interest",
            "cash",
            "non_operating_investments",
        )},
    )

    assert result["lease_adjusted_ebitda"]["value"] == "125"
    assert result["levered_fcf"]["value"] == "60"
    assert result["enterprise_value"]["value"] == "1135"
    assert all(row["input_fact_ids"] for row in result.values())
    assert all(len(row["formula_definition_hash"]) == 64 for row in result.values())
