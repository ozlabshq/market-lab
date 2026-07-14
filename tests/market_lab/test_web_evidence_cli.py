import json
from pathlib import Path
from unittest.mock import patch

from market_lab.web_evidence import ProviderHealth, utcnow
from market_lab.web_evidence_cli import main


class _SmokeProvider:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id

    def health(self):
        return ProviderHealth(self.provider_id, utcnow(), "ready", ["search", "fetch"])


def test_health_command_writes_optional_provider_rows(tmp_path: Path) -> None:
    out = tmp_path / "health.json"
    payload = {
        "profile": "keyless_standard",
        "providers": [
            {"provider_id": "ddgs", "status": "ready"},
            {"provider_id": "direct_http", "status": "ready"},
            {"provider_id": "tavily", "status": "unconfigured", "missing_configuration": ["TAVILY_API_KEY"]},
        ],
    }

    with patch("market_lab.web_evidence_cli.check_health", lambda **kwargs: payload):
        rc = main(["health", "--output", str(out), "--require-core-ready"])

    assert rc == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["providers"][2]["provider_id"] == "tavily"
    assert "TAVILY_API_KEY" in written["providers"][2]["missing_configuration"]


def test_smoke_command_writes_artifact(tmp_path: Path) -> None:
    out = tmp_path / "smoke.json"
    run_dir = tmp_path / "run"
    providers = [_SmokeProvider(provider_id) for provider_id in ["ddgs", "direct_http", "sec", "crossref", "arxiv", "government_http"]]

    with patch("market_lab.web_evidence_runner.build_registry", lambda profile, include_optional: providers):
        rc = main(["smoke", "--run-dir", str(run_dir), "--output", str(out)])

    assert rc == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["lane"] == "live"
    assert written["direct_http"]["status"] == "skipped"


def test_verify_command_exposes_typed_blockers(tmp_path: Path, capsys) -> None:
    payload = {"ok": False, "coverage_blockers": [{"type": "counterevidence_missing", "claim_id": "claim-1"}]}

    with patch("market_lab.web_evidence_cli.verify_run", lambda *args, **kwargs: payload):
        rc = main(["verify-run", "--run-dir", str(tmp_path), "--require-counterevidence-coverage"])

    assert rc == 0
    assert "counterevidence_missing" in capsys.readouterr().out
