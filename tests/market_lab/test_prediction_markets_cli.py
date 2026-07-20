from pathlib import Path
import json

import pytest

from market_lab.prediction_markets import cli
from market_lab.prediction_markets.models import parse_json_bytes
from market_lab.prediction_markets.cli import main


FIXTURES = Path(__file__).parent / "fixtures" / "prediction_markets"


def test_cli_import_list_show_verify_report(tmp_path, capsys):
    root = tmp_path / "prediction_markets"
    assert main(["--root", str(root), "import", "--input", str(FIXTURES / "binary_open_valid.json")]) == 0
    assert main(["--root", str(root), "list"]) == 0
    listed = capsys.readouterr().out
    assert "synthetic_fixture:pm0_binary_open:rules_v1" in listed
    assert main(["--root", str(root), "show", "synthetic_fixture:pm0_binary_open:rules_v1"]) == 0
    shown = capsys.readouterr().out
    assert '"admissibility": "RESEARCH_ADMISSIBLE"' in shown
    assert main(["--root", str(root), "verify", "--strict"]) == 0
    assert main(["--root", str(root), "report"]) == 0
    assert (root / "reports" / "latest.md").read_text(encoding="utf-8").count("Offline frozen-fixture research only") == 1


def test_cli_quarantine_exit_code(tmp_path):
    root = tmp_path / "prediction_markets"
    assert main(["--root", str(root), "import", "--input", str(FIXTURES / "binary_malformed_prices.json")]) == 3


def test_cli_conflict_exit_code_is_integrity(tmp_path):
    root = tmp_path / "prediction_markets"
    assert main(["--root", str(root), "import", "--input", str(FIXTURES / "binary_open_valid.json")]) == 0
    data = parse_json_bytes((FIXTURES / "binary_open_valid.json").read_bytes())
    data["market"]["rules_text"] = "Changed rules under the same raw identity."
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(data), encoding="utf-8")
    assert main(["--root", str(root), "import", "--input", str(changed)]) == 4


def test_cli_usage_errors_are_structured_json(capsys):
    assert main([]) == 2
    err = capsys.readouterr().err
    assert '"error_code": "PM0_USAGE"' in err


def test_cli_debug_env_reraises_internal_errors(monkeypatch, tmp_path):
    def boom(args, root):
        raise RuntimeError("debug-visible")

    monkeypatch.setattr(cli, "_run", boom)
    monkeypatch.setenv("MARKET_LAB_DEBUG", "1")
    with pytest.raises(RuntimeError, match="debug-visible"):
        main(["--root", str(tmp_path), "list"])


def test_cli_explicit_root_symlink_cannot_write_to_target(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    lane = tmp_path / "lane"
    lane.symlink_to(outside, target_is_directory=True)
    assert main(["--root", str(lane), "import", "--input", str(FIXTURES / "binary_open_valid.json")]) == 4
    assert list(outside.iterdir()) == []
