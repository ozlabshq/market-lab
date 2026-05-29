from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .config import EVIDENCE_DIR, ensure_dirs


def append_evidence_record(record: dict[str, Any], path: Path) -> None:
    """Append one JSON record to an evidence stream.

    JSONL append is intentionally simple and inspectable. The parent directory is
    created on demand; each record is fsynced so post-run council artifacts survive
    process crashes better than buffered writes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def append_atomic_jsonl_batch(records: list[dict[str, Any]], path: Path) -> None:
    """Append a batch by rewriting through a temp file + replace.

    Use this when a council run produces multiple records that should appear as one
    durable update. Existing content is preserved, then the new records are appended.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    addition = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as tmp:
        tmp.write(existing)
        tmp.write(addition)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def load_evidence_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def evidence_stream_path(stream_name: str, evidence_dir: Path = EVIDENCE_DIR) -> Path:
    ensure_dirs()
    safe = stream_name.replace("/", "_").replace("..", "_")
    return evidence_dir / f"{safe}.jsonl"
