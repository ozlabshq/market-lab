import ast
import hashlib
from pathlib import Path
import os
import shutil
import subprocess
import venv
import zipfile


ALLOWED = {
    "__future__", "argparse", "base64", "collections", "contextlib", "dataclasses", "datetime",
    "decimal", "enum", "hashlib", "json", "os", "pathlib", "re", "stat", "sys", "tempfile", "typing",
    "market_lab.prediction_markets",
}
FORBIDDEN_CALLS = {"__import__", "eval", "exec", "compile"}
FORBIDDEN_IMPORT_ROOTS = {"socket", "subprocess", "urllib", "http", "httpx", "requests", "websocket", "asyncio", "importlib"}
REPO = Path(__file__).parents[2]
FIXTURES = REPO / "tests" / "market_lab" / "fixtures" / "prediction_markets"


def test_prediction_market_import_allowlist():
    for path in sorted((REPO / "market_lab" / "prediction_markets").glob("*.py")):
        _scan_source(path.read_text(encoding="utf-8"), str(path))


def test_no_dynamic_loading_or_process_network_imports():
    for path in sorted((REPO / "market_lab" / "prediction_markets").glob("*.py")):
        _scan_source(path.read_text(encoding="utf-8"), str(path))


def test_existing_market_lab_modules_do_not_import_prediction_mutable_internals():
    for path in sorted((REPO / "market_lab").glob("*.py")):
        if path.parent.name == "prediction_markets":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("market_lab.prediction_markets"), (path, alias.name)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("market_lab.prediction_markets"), (path, node.module)


def test_built_wheel_prediction_sources_match_boundary(tmp_path):
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as zf:
        names = sorted(n for n in zf.namelist() if n.startswith("market_lab/prediction_markets/") and n.endswith(".py"))
        assert names
        for name in names:
            _scan_source(zf.read(name).decode("utf-8"), name)


def test_installed_wheel_import_entrypoint_and_audit_hook(tmp_path):
    wheel = _build_wheel(tmp_path)
    venv_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = venv_dir / "bin" / "python"
    env = _child_env()
    subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True, cwd=tmp_path, env=env)
    subprocess.run([str(python), "-m", "pip", "install", "--force-reinstall", "--no-deps", str(wheel)], check=True, cwd=tmp_path, env=env)
    import_check = "import pathlib,sys; import market_lab.prediction_markets.cli as c; p=pathlib.Path(c.__file__).resolve(); assert callable(c.main); assert p.is_relative_to(pathlib.Path(sys.prefix).resolve()), p"
    subprocess.run([str(python), "-c", import_check], check=True, cwd=tmp_path, env=env)
    script = venv_dir / "bin" / "market-lab-prediction"
    assert script.exists()
    help_run = subprocess.run([str(script), "--help"], check=True, text=True, capture_output=True, cwd=tmp_path, env=env)
    paper_help = subprocess.run([str(script), "paper", "--help"], check=True, text=True, capture_output=True, cwd=tmp_path, env=env)
    assert "never live trading" in help_run.stdout + paper_help.stdout
    child = tmp_path / "audit_child.py"
    child.write_text(
        """
import sys
from pathlib import Path

def hook(event, args):
    if event.startswith("socket.") or event.startswith("subprocess.") or event in {"os.system", "os.posix_spawn", "os.fork", "os.exec"}:
        raise RuntimeError("denied audit event: " + event)

sys.addaudithook(hook)
from market_lab.prediction_markets.cli import main
root = Path(sys.argv[1])
fixture = Path(sys.argv[2])
market = "synthetic_fixture:pm0_binary_open:rules_v1"
assert main(["--root", str(root), "import", "--input", str(fixture / "binary_open_valid.json")]) == 0
assert main(["--root", str(root), "list"]) == 0
assert main(["--root", str(root), "show", market]) == 0
assert main(["--root", str(root), "verify", "--strict"]) == 0
assert main(["--root", str(root), "report"]) == 0
assert main(["--root", str(root), "paper", "init", "--cash", "1000.000000", "--observed-at", "2026-07-19T00:10:00Z"]) == 0
assert main(["--root", str(root), "paper", "buy", market, "--outcome", "YES", "--quantity", "10.000000", "--limit-price", "0.440000", "--fee-per-contract", "0.010000", "--observed-at", "2026-07-19T00:11:00Z"]) == 0
assert main(["--root", str(root), "paper", "settle", market, "--winning-outcome", "YES", "--observed-at", "2026-07-19T00:12:00Z"]) == 0
""",
        encoding="utf-8",
    )
    subprocess.run([str(python), str(child), str(tmp_path / "lane"), str(FIXTURES)], check=True, cwd=tmp_path, env=env)


def _build_wheel(tmp_path: Path) -> Path:
    before = _checkout_inventory()
    out = tmp_path / "dist"
    out.mkdir()
    source = tmp_path / "source"
    _copy_source_tree(source)
    build_env = tmp_path / "build-venv"
    venv.EnvBuilder(with_pip=True).create(build_env)
    python = build_env / "bin" / "python"
    env = _child_env()
    try:
        subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True, cwd=tmp_path, env=env)
        subprocess.run([str(python), "-m", "pip", "install", "wheel"], check=True, cwd=tmp_path, env=env)
        subprocess.run([str(python), "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-w", str(out), str(source)], check=True, cwd=tmp_path, env=env)
        wheels = sorted(out.glob("*.whl"))
        assert len(wheels) == 1
        return wheels[0]
    finally:
        assert _checkout_inventory() == before


def _copy_source_tree(target: Path) -> None:
    ignore_names = {".git", ".venv", ".pytest_cache", "__pycache__", "build", "dist"}

    def ignore(_dir, names):
        return {name for name in names if name in ignore_names or name.endswith(".egg-info") or name.endswith(".pyc")}

    shutil.copytree(REPO, target, ignore=ignore)


def _checkout_inventory() -> dict[str, tuple]:
    inventory = {}
    skip = {".git", ".venv"}
    for path in sorted(REPO.rglob("*")):
        rel = path.relative_to(REPO)
        if rel.parts and rel.parts[0] in skip:
            continue
        st = path.lstat()
        if path.is_dir():
            inventory[str(rel)] = ("dir", st.st_mode, st.st_mtime_ns)
        elif path.is_file():
            inventory[str(rel)] = ("file", st.st_mode, st.st_mtime_ns, st.st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        elif path.is_symlink():
            inventory[str(rel)] = ("symlink", st.st_mode, st.st_mtime_ns, os.readlink(path))
        else:
            inventory[str(rel)] = ("special", st.st_mode, st.st_mtime_ns)
    return inventory


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    env.setdefault("UV_CACHE_DIR", "/private/tmp/uv-cache-pm0-fix2")
    return env


def _scan_source(source: str, label: str) -> None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in ALLOWED or alias.name == "market_lab.prediction_markets" or alias.name.startswith("market_lab.prediction_markets."), (label, alias.name)
                assert alias.name.split(".")[0] not in FORBIDDEN_IMPORT_ROOTS, (label, alias.name)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] in ALLOWED or node.module == "market_lab.prediction_markets" or node.module.startswith("market_lab.prediction_markets."), (label, node.module)
            assert node.module.split(".")[0] not in FORBIDDEN_IMPORT_ROOTS, (label, node.module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_CALLS, (label, node.func.id)
