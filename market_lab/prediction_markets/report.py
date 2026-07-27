from __future__ import annotations

from collections import Counter
from pathlib import Path

from market_lab.prediction_markets.models import canonical_json_bytes
from market_lab.prediction_markets.store import atomic_replace, atomic_write, dataset_digest, load_records, quarantine_count, verify


DISCLAIMER = "Offline frozen-fixture research only; no P&L, fillability, edge, legality, resolution, or strategy claim."


def render_report(root: Path) -> tuple[str, str]:
    records = load_records(root)
    digest = dataset_digest(records)
    status_counts = Counter(r.status for r in records)
    adm_counts = Counter(r.admissibility for r in records)
    lines = ["# Prediction Market Offline Report", "", f"Dataset digest: `{digest}`", "", DISCLAIMER, "", "## Counts", ""]
    lines.append("Status: " + canonical_json_bytes(dict(sorted(status_counts.items()))).decode("utf-8"))
    lines.append("Admissibility: " + canonical_json_bytes(dict(sorted(adm_counts.items()))).decode("utf-8"))
    lines.extend(["", "## Markets", "", "| market_key | source | status | admissibility | observed_at_utc | retrieved_at_utc |", "|---|---|---:|---:|---:|---:|"])
    for r in records:
        source = f"{r.source_class}/{r.provider_id}/{r.venue_id}/{r.api_surface_id}"
        lines.append(f"| {r.market_key} | {source} | {r.status} | {r.admissibility} | {r.observed_at_utc} | {r.retrieved_at_utc} |")
    lines.extend(["", "## Completeness", "", "| market_key | rules | fee | resolution | terms |", "|---|---:|---:|---:|---:|"])
    for r in records:
        rules = bool(r.rules_text and r.rules_hash)
        fee = bool(r.fee_schedule_id and r.fee_schedule_version)
        resolution = bool(r.resolution_source_description)
        terms = bool(r.terms_version and r.terms_sha256)
        lines.append(f"| {r.market_key} | {rules} | {fee} | {resolution} | {terms} |")
    check = verify(root)
    lines.extend(["", "## Integrity", "", f"Quarantine count: {quarantine_count(root)}", f"Verify ok: {check['ok']}"])
    return digest, "\n".join(lines) + "\n"


def write_report(root: Path) -> dict:
    digest, text = render_report(root)
    report_dir = root / "reports"
    atomic_write(report_dir / f"{digest}.md", text.encode("utf-8"))
    atomic_replace(report_dir / "latest.md", text.encode("utf-8"))
    return {"dataset_sha256": digest, "path": str(report_dir / "latest.md")}
