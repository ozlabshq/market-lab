from unittest.mock import patch

from ddgs.exceptions import DDGSException, TimeoutException

from market_lab.web_evidence import SearchRequest
from market_lab.web_evidence_providers import DDGSProvider, OptionalProvider, build_optional_registry


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


class _FailingDDGS:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def text(self, *args, **kwargs):
        raise self.exc


def test_ddgs_clean_no_results_has_distinct_typed_status() -> None:
    with patch("ddgs.DDGS", lambda *args, **kwargs: _FailingDDGS(DDGSException("No results found."))):
        response = DDGSProvider().search(_request())

    assert response.status == "zero_results"
    assert response.typed_error == "zero_results"
    assert response.result_count == 0


def test_ddgs_timeout_remains_transport_error() -> None:
    with patch("ddgs.DDGS", lambda *args, **kwargs: _FailingDDGS(TimeoutException("timed out"))):
        response = DDGSProvider().search(_request())

    assert response.status == "transport_error"
    assert response.typed_error == "timed out"


def test_ddgs_provider_exception_remains_transport_error() -> None:
    with patch("ddgs.DDGS", lambda *args, **kwargs: _FailingDDGS(DDGSException("backend exploded"))):
        response = DDGSProvider().search(_request())

    assert response.status == "transport_error"
    assert response.typed_error == "backend exploded"
