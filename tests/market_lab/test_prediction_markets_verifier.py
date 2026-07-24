import os
import stat
from pathlib import Path
import shutil
import pytest

from market_lab.prediction_markets.errors import PathEscapeError
from market_lab.prediction_markets.store import verify
from market_lab.prediction_markets.config import assert_below_root


def _touch(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("ok", encoding="utf-8")


def test_assert_below_root_blocks_traversal(tmp_path):
    root = tmp_path / "lane"
    root.mkdir()
    escape_path = root / ".." / "outside.txt"
    with pytest.raises(PathEscapeError):
        assert_below_root(root, escape_path)


def test_assert_below_root_blocks_symlink_escape(tmp_path):
    root = tmp_path / "lane"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("bad")
    bad_link = root / "badlink"
    bad_link.symlink_to(outside)
    with pytest.raises(PathEscapeError):
        assert_below_root(root, bad_link)


def test_assert_below_root_blocks_symlinked_parent(tmp_path):
    root = tmp_path / "lane"
    root.mkdir()
    outside = tmp_path / "outside"
    outside_dir = outside
    outside_dir.mkdir()
    link = root / "up"
    link.symlink_to(outside_dir, target_is_directory=True)
    child_file = link / "sneaky.txt"
    _touch(outside_dir / "sneaky.txt")
    with pytest.raises(PathEscapeError):
        assert_below_root(root, child_file)


def test_verify_has_no_read_side_effects(tmp_path):
    root = tmp_path / "lane"
    root.mkdir()
    # Setup: populate root with a harmless file
    d = root / "raw" / "sha256" / "ab" / "abcdefgh"
    d.mkdir(parents=True)
    f = d / "raw.bin"
    content = b"stuff"
    f.write_bytes(content)
    before = set(p.stat().st_mtime_ns for p in root.rglob("*"))
    before_names = set(str(p) for p in root.rglob("*"))
    verify(root)  # Should only read, never write/delete
    after = set(p.stat().st_mtime_ns for p in root.rglob("*"))
    after_names = set(str(p) for p in root.rglob("*"))
    assert before == after, "File modification times changed during verify() read"
    assert before_names == after_names, "File set changed during verify() read"


def test_verify_detects_artifact_outside_lane(tmp_path):
    root = tmp_path / "lane"
    root.mkdir()
    # Place an offending file outside lane root
    parent_artifact = tmp_path / "bad.json"
    parent_artifact.write_text("should not be seen")
    # Place a symlink in lane that points to parent
    sneaky_symlink = root / "bad.json"
    sneaky_symlink.symlink_to(parent_artifact)
    with pytest.raises(PathEscapeError):
        verify(root)
