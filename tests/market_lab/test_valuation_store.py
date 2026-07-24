from __future__ import annotations

from pathlib import Path

import pytest

from market_lab.valuation_store import ValuationStore, ValuationStoreError


def test_store_rejects_absolute_and_parent_traversal_artifact_names(tmp_path: Path) -> None:
    store = ValuationStore(tmp_path / "valuation")

    with pytest.raises(ValuationStoreError, match="unsafe valuation artifact path"):
        store.write_json("../escaped.json", {"value": "forbidden"})
    with pytest.raises(ValuationStoreError, match="unsafe valuation artifact path"):
        store.write_text(str(tmp_path / "absolute.md"), "forbidden")

    assert not (tmp_path / "escaped.json").exists()
    assert not (tmp_path / "absolute.md").exists()