from __future__ import annotations

import os
from pathlib import Path
import stat

from market_lab.prediction_markets.errors import PathEscapeError


def prediction_data_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    if os.environ.get("MARKET_LAB_PREDICTION_DATA_DIR"):
        return Path(os.environ["MARKET_LAB_PREDICTION_DATA_DIR"]).expanduser()
    if os.environ.get("MARKET_LAB_DATA_DIR"):
        return (Path(os.environ["MARKET_LAB_DATA_DIR"]) / "prediction_markets").expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "market-lab" / "prediction_markets"


def assert_below_root(root: Path, path: Path) -> Path:
    root_input = _absolute_unresolved(root)
    _reject_existing_components(root_input)
    root_resolved = root_input.resolve(strict=False)
    target_input = _absolute_unresolved(path) if path.is_absolute() else root_input / path
    _reject_traversal(target_input)
    _reject_existing_components(target_input)
    target = target_input.resolve(strict=False)
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise PathEscapeError("path escapes prediction data root", path=str(path)) from exc
    return target


def assert_write_path(root: Path, path: Path) -> Path:
    target = assert_below_root(root, path)
    parent = assert_below_root(root, target.parent)
    parent.mkdir(parents=True, exist_ok=True)
    assert_below_root(root, parent)
    assert_below_root(root, target)
    return target


def _absolute_unresolved(path: Path) -> Path:
    path = path.expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _reject_traversal(path: Path) -> None:
    if ".." in path.parts:
        raise PathEscapeError("path traversal is not allowed", path=str(path))


def _reject_existing_components(path: Path) -> None:
    probe = Path(path.anchor)
    for part in path.parts[1:]:
        probe = probe / part
        _reject_special(probe)


def _reject_special(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        raise PathEscapeError("symlink component is not allowed", path=str(path))
    if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
        raise PathEscapeError("special filesystem entry is not allowed", path=str(path))
