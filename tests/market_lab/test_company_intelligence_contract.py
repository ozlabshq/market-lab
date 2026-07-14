from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from market_lab.agency_contracts import TypedID, canonical_json, strict_json_loads
from market_lab.company_intelligence import (
    BottleneckType,
    ClaimStatus,
    Confidence,
    EvidenceKind,
    EvidenceRef,
    GraphValidationError,
    MechanismClaim,
    NodeRole,
    ThemeDefinition,
    ThemeStatus,
    ValueChainEdge,
    ValueChainGraph,
    ValueChainNode,
    ValueChainRelation,
    ValueChainStatus,
    validate_theme,
)

NOW = "2026-07-14T08:00:00Z"


def tid(kind: str, local_id: str) -> TypedID:
    return TypedID(kind=kind, domain="agency", id_schema_version="v1", local_id=local_id)


def evidence(local_id: str, *, synthetic: bool = False, status: ClaimStatus = ClaimStatus.VERIFIED) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=tid("evidence", local_id),
        claim_id=tid("claim", f"{local_id}-claim"),
        claim_status=status,
        evidence_kind=EvidenceKind.SYNTHETIC if synthetic else EvidenceKind.OFFICIAL_FILING,
    )


def valid_theme() -> ThemeDefinition:
    claim = tid("claim", "grid-claim")
    evidence_id = tid("evidence", "grid-evidence")
    return ThemeDefinition(
        theme_id=tid("theme", "grid-capacity"),
        name="Grid capacity transformer replacement cycle",
        canonical_definition="Regulated grid capacity additions increase demand for high-voltage transformers.",
        included_mechanisms=("regulated capex demand", "transformer capacity bottleneck"),
        excluded_mechanisms=("general electrification sentiment",),
        geographies=("US",),
        horizon="2026-2030",
        as_of_utc=NOW,
        origin_claim_ids=(claim,),
        material_claim_ids=(claim,),
        counterclaim_ids=(tid("claim", "grid-counterclaim"),),
        keywords=("grid", "transformer"),
        synonyms=("transmission equipment",),
        ambiguous_terms=("AI power",),
        analyst_rationale="Filings and official grid plans identify transformer supply as a gating mechanism.",
        rationale_claim_ids=(claim,),
        rationale_evidence_ids=(evidence_id,),
        material_mechanisms=(
            MechanismClaim(
                mechanism="regulated capex demand",
                claim_ids=(claim,),
                evidence_ids=(evidence_id,),
            ),
        ),
        disconfirmation_questions=("Do grid interconnection delays reduce transformer orders?",),
        falsifiers=("Order lead times normalize below one quarter.",),
        status=ThemeStatus.VALIDATED,
    )


def node(local_id: str, role: NodeRole, status: ValueChainStatus = ValueChainStatus.EVIDENCED) -> ValueChainNode:
    return ValueChainNode(
        node_id=tid("value_chain_node", local_id),
        label=local_id.replace("-", " "),
        role=role,
        description=f"{local_id} role",
        geography="US",
        economic_driver="regulated capex",
        bottleneck_type=BottleneckType.CAPACITY,
        material_claim_ids=(tid("claim", f"{local_id}-claim"),),
        evidence_ids=(tid("evidence", f"{local_id}-evidence"),),
        counterevidence_ids=(),
        confidence=Confidence.HIGH,
        status=status,
    )


def edge(local_id: str, from_node: ValueChainNode, to_node: ValueChainNode, status: ValueChainStatus = ValueChainStatus.EVIDENCED) -> ValueChainEdge:
    return ValueChainEdge(
        edge_id=tid("value_chain_edge", local_id),
        from_node_id=from_node.node_id,
        to_node_id=to_node.node_id,
        relation=ValueChainRelation.ENABLES,
        economic_transmission="Capacity additions transmit demand to equipment suppliers.",
        units_or_basis="contracted capacity",
        valid_from="2026-01-01T00:00:00Z",
        valid_to=None,
        claim_ids=(tid("claim", f"{local_id}-claim"),),
        evidence_ids=(tid("evidence", f"{local_id}-evidence"),),
        status=status,
    )


def graph_with_path(*, proposed_middle: bool = False) -> tuple[ValueChainGraph, ValueChainNode, ValueChainNode]:
    driver = node("driver", NodeRole.CUSTOMER)
    equipment = node("equipment", NodeRole.EQUIPMENT, ValueChainStatus.PROPOSED if proposed_middle else ValueChainStatus.EVIDENCED)
    manufacturer = node("manufacturer", NodeRole.MANUFACTURER)
    graph = ValueChainGraph(
        theme_id=tid("theme", "grid-capacity"),
        as_of_utc=NOW,
        nodes=(driver, equipment, manufacturer),
        edges=(
            edge("driver-equipment", driver, equipment),
            edge("equipment-manufacturer", equipment, manufacturer),
            edge("cycle", manufacturer, equipment),
        ),
        coverage_gaps=("alternate substitutes not fully mapped",),
    )
    return graph, driver, manufacturer


def test_valid_theme_contract_round_trip_digest_and_frozen() -> None:
    theme = valid_theme()
    evidence_index = {
        tid("evidence", "grid-evidence"): evidence("grid-evidence"),
    }
    result = validate_theme(theme, evidence_index)
    assert result.ok is True
    assert result.reason_codes == ()
    assert ThemeDefinition.from_dict(strict_json_loads(canonical_json(theme.to_dict()))) == theme
    assert len(theme.theme_digest_sha256) == 64
    with pytest.raises(FrozenInstanceError):
        theme.name = "mutated"  # type: ignore[misc]


def test_theme_validation_rejects_schema_enum_missing_bounds_and_synthetic_evidence() -> None:
    theme = valid_theme()
    payload = theme.to_dict()
    payload["schema_version"] = "mlab-theme.v2"
    with pytest.raises(ValueError, match="schema_version"):
        ThemeDefinition.from_dict(payload)
    payload = theme.to_dict()
    payload["status"] = "MAYBE"
    with pytest.raises(ValueError, match="status"):
        ThemeDefinition.from_dict(payload)
    unbounded = ThemeDefinition.from_dict({**theme.to_dict(), "excluded_mechanisms": [], "falsifiers": []})
    assert validate_theme(unbounded, {tid("evidence", "grid-evidence"): evidence("grid-evidence")}).ok is False
    synthetic = validate_theme(theme, {tid("evidence", "grid-evidence"): evidence("grid-evidence", synthetic=True)})
    assert synthetic.ok is False
    assert "synthetic_evidence" in synthetic.reason_codes


def test_value_chain_graph_digest_round_trip_duplicate_reference_and_cycle_rules() -> None:
    graph, driver, manufacturer = graph_with_path()
    assert ValueChainGraph.from_dict(strict_json_loads(canonical_json(graph.to_dict()))) == graph
    assert len(graph.graph_digest) == 64
    assert graph.has_evidenced_path((driver.node_id,), manufacturer.node_id) is True

    duplicate = ValueChainGraph(
        theme_id=graph.theme_id,
        as_of_utc=NOW,
        nodes=(graph.nodes[0], graph.nodes[0]),
        edges=(),
        coverage_gaps=("duplicate",),
    )
    with pytest.raises(GraphValidationError, match="duplicate node"):
        duplicate.validate()

    missing_ref = ValueChainGraph(
        theme_id=graph.theme_id,
        as_of_utc=NOW,
        nodes=(driver,),
        edges=(edge("bad-ref", driver, manufacturer),),
        coverage_gaps=("bad ref",),
    )
    with pytest.raises(GraphValidationError, match="unknown node"):
        missing_ref.validate()


def test_only_evidenced_nodes_and_edges_support_paths() -> None:
    graph, driver, manufacturer = graph_with_path(proposed_middle=True)
    assert graph.has_evidenced_path((driver.node_id,), manufacturer.node_id) is False
    unsupported_edge = ValueChainGraph(
        theme_id=graph.theme_id,
        as_of_utc=NOW,
        nodes=graph.nodes,
        edges=(edge("driver-equipment", graph.nodes[0], graph.nodes[1], ValueChainStatus.PROPOSED),),
        coverage_gaps=("proposed edge",),
    )
    assert unsupported_edge.has_evidenced_path((driver.node_id,), manufacturer.node_id) is False
    assert unsupported_edge.has_evidenced_path((tid("value_chain_node", "missing"),), manufacturer.node_id) is False
