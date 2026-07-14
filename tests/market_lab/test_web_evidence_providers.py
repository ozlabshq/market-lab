from unittest.mock import patch

from market_lab.web_evidence import SearchRequest
from market_lab.web_evidence_providers import OptionalProvider, build_optional_registry


def _request() -> SearchRequest:
    return SearchRequest(request_id="search-1", query_id="query-1", run_id="run", claim_ids=["claim"], exact_query="query", lane="test")


def test_optional_provider_missing_config_is_visible_and_unprobed() -> None:
    provider = OptionalProvider("tavily", "MISSING_TAVILY_FOR_TEST")

    health = provider.health()
    search = provider.search(_request())

    assert health.status == "unconfigured"
    assert health.missing_configuration == ["MISSING_TAVILY_FOR_TEST"]
    assert search.status == "unconfigured"
    assert search.typed_error == "missing-managed-key"


def test_configured_optional_provider_stays_disabled_until_safe_probe_exists() -> None:
    with patch.dict("os.environ", {"OPTIONAL_KEY_FOR_TEST": "secret"}):
        provider = OptionalProvider("brave", "OPTIONAL_KEY_FOR_TEST")
        health = provider.health()
        search = provider.search(_request())

    assert health.status == "disabled"
    assert health.capabilities_ready == []
    assert search.status == "disabled"
    assert search.typed_error == "probe_not_implemented"


def test_optional_registry_contains_visibility_rows() -> None:
    providers = build_optional_registry("keyless_standard")

    assert {"tavily", "brave", "exa", "firecrawl", "parallel", "searxng", "jina_reader"}.issubset(
        {provider.provider_id for provider in providers}
    )
