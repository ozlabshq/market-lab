from __future__ import annotations

import argparse
import json
import re
import statistics
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import (
    SOURCE_THESIS_DIR,
    SOURCE_THESIS_REPORT_DIR,
    DEFAULT_UNIVERSE,
    ensure_dirs,
)
from .data import Bar, fetch_prices
from .factors import FactorSnapshot, fetch_factors


# Conservative fallback heuristics retained for backwards compatibility with the prior thesis
# pipeline.
DEFAULT_CONTROLS = ["FAST", "GWW", "CTAS", "ODFL", "KFY", "SAIA"]
BENCHMARKS = ["SPY", "IWM"]

LOW_MARGIN_INDUSTRY_TICKERS = {
    "logistics/freight": ["XPO", "CHRW", "FDX", "UPS", "ODFL"],
    "trucking": ["ODFL", "JBHT", "SAIA"],
    "staffing": ["RCPT", "MAN", "RHI"],
    "facilities/field services": ["ABM", "CIM"],
    "industrial distribution": ["GXO", "DCTH", "KFY"],
    "manufacturing": ["FAST", "GWW", "CTAS"],
    "healthcare services": ["HCA", "UNH"],
}

# Hard stop list for accidental uppercase token capture.
FORBIDDEN_TICKER_HINTS = {
    "THE",
    "THIS",
    "FROM",
    "WITH",
    "OPEN",
    "AI",
    "AND",
    "FOR",
    "YOUR",
    "OVER",
    "BELOW",
    "TOP",
    "BEST",
    "WHAT",
    "NOT",
    "OR",
    "BUT",
    "YOU",
    "US",
    "NEW",
}

KNOWN_TICKERS = {
    ticker.upper()
    for ticker in (
        DEFAULT_UNIVERSE
        + DEFAULT_CONTROLS
        + [
            "SPY",
            "IWM",
        ]
    )
}


@dataclass(frozen=True)
class SourceClaim:
    text: str
    citation: str
    source_url: str = ""
    source_artifact: str = ""
    author: str = ""
    captured_at: str = ""


@dataclass(frozen=True)
class ThesisFactor:
    name: str
    description: str
    measurable_proxies: list[str]
    unavailable_fields: list[str]
    confidence: float
    evidence: list[str]


@dataclass(frozen=True)
class SourceMediaAsset:
    media_id: str
    media_url: str
    local_path: str
    interpretation_status: str
    width: int | None = None
    height: int | None = None
    source_artifact: str = ""


@dataclass(frozen=True)
class SourceThesis:
    url: str
    title: str
    author: str
    captured_date: str
    source_quality: str
    claims: list[SourceClaim]
    cited_snippets: list[str]
    industries: list[str]
    candidate_tickers: list[str]
    control_tickers: list[str]
    factors: list[ThesisFactor]
    media_assets: list[SourceMediaAsset]
    guardrail: str = "Research/mock only. Source-derived theses never create live orders."


@dataclass(frozen=True)
class BasketMember:
    symbol: str
    role: str
    industry: str
    reason: str


@dataclass(frozen=True)
class BasketEvaluation:
    symbol: str
    role: str
    industry: str
    total_return: float | None
    vs_spy: float | None
    latest_close: float | None
    data_source: str
    factor_source: str
    gross_margin: float | None
    revenue_growth_yoy: float | None
    reason: str
    window_start: str = ""
    window_end: str = ""


@dataclass(frozen=True)
class ThesisRun:
    thesis: SourceThesis
    basket: list[BasketMember]
    evaluations: list[BasketEvaluation]
    benchmarks: dict[str, BasketEvaluation]
    promotion_status: str
    warnings: list[str] = field(default_factory=list)
    market_window_start: str = ""
    market_window_end: str = ""


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:90] if slug else "source-thesis"


def _read_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(errors="replace")


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    candidates = [
        "%a %b %d %H:%M:%S %z %Y",
        "%a %b %d %H:%M:%S %Y",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ]
    for fmt in candidates:
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def _normalize_metadata_timestamp(value: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return value
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _metadata_value(text: str, labels: Iterable[str]) -> str:
    for label in labels:
        pattern = rf"^\s*{re.escape(label)}\s*:\n?\s*(.+)$"
        match = re.search(pattern, text, flags=re.I | re.M)
        if match:
            return match.group(1).strip().strip("`")
    return ""


def _title_from_markdown(text: str, fallback: str = "(untitled)") -> str:
    match = re.search(r"^#\s+(.+)$", text, flags=re.M)
    if match:
        return match.group(1).strip()
    return fallback


def _source_quality(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ("memo", "source", "claim", "evidence", "thesis")):
        return "uncurated narrative source"
    return "primary post source"


def _strip_quote(raw_line: str) -> str | None:
    stripped = raw_line.strip()
    if not stripped:
        return None

    # Markdown block-quote line from X capture text.
    match = re.match(r"^>\s*(.+)$", raw_line)
    if match:
        return match.group(1).strip()

    # Claim style line from claim-vs-evidence style memo.
    match = re.match(r"^\s*(?:-\s*)?(?:\d+\)\s*)?\**\s*claim\s*:\**\s*(.+)$", raw_line, flags=re.I)
    if match:
        return match.group(1).strip()

    # Plain claim-style line without Markdown quote marker (common in structured captures).
    # Example: "Small quadcopter drone: Requires 8–12 bearings."
    match = re.match(r"^\s*(?:-\s*)?(?:\d+\)\s*)?(.+?:\s*.+)$", raw_line)
    if match:
        candidate = match.group(1).strip()
        if len(candidate) >= 15 and any(ch.isdigit() for ch in candidate):
            return candidate

    return None


def _extract_claims(
    text: str,
    *,
    source_url: str,
    source_artifact: str,
    author: str,
    captured_at: str,
) -> tuple[list[SourceClaim], list[str]]:
    claims: list[SourceClaim] = []
    cited: list[str] = []
    for i, raw_line in enumerate(text.splitlines(), start=1):
        quote = _strip_quote(raw_line)
        if not quote:
            continue
        if len(quote) < 15:
            continue
        lower = quote.lower()
        if lower.startswith(("created:", "captured:", "author:", "source post", "canonical")):
            continue
        if any(token in lower for token in ["source references", "attached images"]):
            continue
        if any(dup in quote for dup in ("source references", "source v")):
            continue

        claims.append(
            SourceClaim(
                text=quote,
                citation=f"{source_artifact or 'source'}:line_{i}",
                source_url=source_url,
                source_artifact=source_artifact,
                author=author,
                captured_at=captured_at,
            )
        )
        cited.append(quote)

    # Deduplicate while preserving order.
    seen = set()
    unique_claims: list[SourceClaim] = []
    unique_snippets: list[str] = []
    for claim, snippet in zip(claims, cited):
        if claim.text in seen:
            continue
        seen.add(claim.text)
        unique_claims.append(claim)
        unique_snippets.append(snippet)
    return unique_claims, unique_snippets


def _read_image_size(path: Path) -> tuple[int | None, int | None]:
    if not path.exists():
        return None, None
    raw = path.read_bytes()
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    if raw.startswith(b"\xff\xd8"):
        idx = 2
        while idx + 9 < len(raw):
            if raw[idx] != 0xFF:
                idx += 1
                continue
            marker = raw[idx + 1]
            if marker in {0xC0, 0xC2} and idx + 9 < len(raw):
                return (
                    int.from_bytes(raw[idx + 7 : idx + 9], "big"),
                    int.from_bytes(raw[idx + 5 : idx + 7], "big"),
                )
            seg_len = int.from_bytes(raw[idx + 2 : idx + 4], "big")
            if seg_len < 2:
                break
            idx += 2 + seg_len
    return None, None


def _parse_media_manifest(path: Path | None, capture_dir: Path) -> list[SourceMediaAsset]:
    if path is None or not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(errors="replace"))
    except Exception:
        return []

    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = raw.get("media") or raw.get("media_entries") or []
    else:
        return []

    assets: list[SourceMediaAsset] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        media_id = str(
            entry.get("id")
            or entry.get("media_id")
            or entry.get("media_key")
            or ""
        )
        media_url = str(entry.get("url") or entry.get("media_url") or "")
        local_path = str(entry.get("local_path") or entry.get("file") or entry.get("path") or "")
        width = entry.get("width")
        height = entry.get("height")

        if isinstance(width, (int, float)):
            width = int(width)
        else:
            width = None
        if isinstance(height, (int, float)):
            height = int(height)
        else:
            height = None

        interpretation_status = str(
            entry.get("interpretation_status")
            or entry.get("interpretation")
            or "media_not_interpreted"
        )

        resolved = Path(local_path)
        if local_path and not resolved.is_absolute():
            resolved = capture_dir / resolved

        if (width is None or height is None) and local_path:
            inferred_w, inferred_h = _read_image_size(resolved)
            width = width or inferred_w
            height = height or inferred_h

        if media_id or media_url or local_path:
            assets.append(
                SourceMediaAsset(
                    media_id=media_id,
                    media_url=media_url,
                    local_path=local_path,
                    interpretation_status=interpretation_status,
                    width=width,
                    height=height,
                    source_artifact=str(path),
                )
            )

    return assets


def _detect_industries(text: str) -> list[str]:
    lower = text.lower()
    findings: list[str] = []
    mapping = {
        "logistics": ("logistics", "freight", "distribution"),
        "trucking": ("trucking", "carrier", "truck"),
        "staffing": ("staffing", "employee", "workforce"),
        "manufacturing": ("manufacturing", "manufacturer", "factory"),
        "healthcare services": ("healthcare", "hospital", "patient"),
    }
    for name, terms in mapping.items():
        if any(term in lower for term in terms):
            findings.append(name)
    return findings


def _extract_explicit_tickers(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"\$([A-Z]{1,5})\b|\b([A-Z]{1,5})\b", text):
        token = (match.group(1) or match.group(2) or "").upper()
        if not token:
            continue
        if token in FORBIDDEN_TICKER_HINTS:
            continue
        if token in KNOWN_TICKERS and token not in candidates:
            candidates.append(token)
    return candidates


def _thesis_factors(text: str) -> list[ThesisFactor]:
    lower = text.lower()
    factors = [
        ThesisFactor(
            name="source_integrity",
            description="Source is treated as research-only evidence requiring explicit claim provenance.",
            measurable_proxies=["quote extraction precision", "time-anchored market window", "source artifact path"],
            unavailable_fields=["claim-level confidence grading from external NLP"],
            confidence=0.65,
            evidence=[line for line in text.splitlines() if line.strip().startswith(">")][:3],
        )
    ]

    if "openai" in lower or "ai" in lower:
        factors.append(
            ThesisFactor(
                name="workflow_ai_adoption_evidence",
                description="Claims around AI workflow claims require independent operational verification.",
                measurable_proxies=["evidence of implementation", "pilot outcomes", "workflow-level cost change"],
                unavailable_fields=["independent operational telemetry"],
                confidence=0.58,
                evidence=[
                    line
                    for line in text.splitlines()
                    if line.strip().startswith(">") and "ai" in line.lower()
                ],
            )
        )

    if "margin" in lower:
        factors.append(
            ThesisFactor(
                name="low_margin_operating_leverage",
                description="Low-margin operating leverage hypothesis tied to explicit source claims.",
                measurable_proxies=["gross margin", "revenue growth", "expense productivity"],
                unavailable_fields=["segment-level margin split"],
                confidence=0.62,
                evidence=[
                    line
                    for line in text.splitlines()
                    if "margin" in line.lower() and line.strip().startswith(">")
                ],
            )
        )

    if "coordination" in lower:
        factors.append(
            ThesisFactor(
                name="coordination_cost_exposure",
                description="Coordination complexity may imply leverage sensitivity.",
                measurable_proxies=["dispatch complexity", "order-to-cash cycle"],
                unavailable_fields=["quarterly coordination cost breakdown"],
                confidence=0.51,
                evidence=[
                    line
                    for line in text.splitlines()
                    if "coordination" in line.lower() and line.strip().startswith(">")
                ],
            )
        )

    if not factors:
        factors = [
            ThesisFactor(
                name="unmapped_source_thesis",
                description="Source requires human review before factor mapping.",
                measurable_proxies=[],
                unavailable_fields=["factor mapping"],
                confidence=0.20,
                evidence=[],
            )
        ]

    return factors


def _safe_factor(symbol: str, prefer_network: bool = False) -> tuple[FactorSnapshot | None, str]:
    try:
        factor, source = fetch_factors(symbol, prefer_network=prefer_network)
        return factor, source
    except Exception:
        return None, "factor_unavailable"


def _returns_from_window(bars: list[Bar]) -> tuple[float | None, float | None]:
    if len(bars) < 2:
        return None, None
    first = bars[0].close
    last = bars[-1].close
    if first <= 0:
        return None, None
    return last / first - 1.0, last


def _bars_after_timestamp(bars: list[Bar], source_timestamp: str) -> list[Bar]:
    if not bars:
        return []
    parsed = _parse_datetime(source_timestamp)
    if parsed is None:
        return []
    anchor = parsed.date()
    window = [bar for bar in bars if bar.date > anchor]
    return window


def _dedupe_symbols(symbols: list[str]) -> list[str]:
    return list(dict.fromkeys(symbols))


def _is_synthetic_like(source: str) -> bool:
    return source in {"synthetic", "cache_synthetic", "cache"}


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def extract_source_thesis(
    markdown_text: str,
    url: str = "",
    title: str = "",
    author: str = "",
    *,
    source_artifact: str = "",
    source_timestamp: str = "",
    media_manifest_path: Path | None = None,
    capture_dir: Path | None = None,
    captured_at: str = "",
) -> SourceThesis:
    text = markdown_text or ""
    normalized_captured = _normalize_metadata_timestamp(captured_at or source_timestamp)

    claims, cited = _extract_claims(
        text,
        source_url=url,
        source_artifact=source_artifact,
        author=author,
        captured_at=normalized_captured,
    )
    industries = _detect_industries(text)
    direct_tickers = _extract_explicit_tickers(text)
    candidate_tickers = _dedupe_symbols(direct_tickers)
    media_assets = _parse_media_manifest(media_manifest_path, capture_dir or Path("."))

    return SourceThesis(
        url=url,
        title=title or _title_from_markdown(text) or "(untitled source thesis)",
        author=author,
        captured_date=normalized_captured,
        source_quality=_source_quality(text),
        claims=claims,
        cited_snippets=cited,
        industries=industries,
        candidate_tickers=candidate_tickers,
        control_tickers=DEFAULT_CONTROLS,
        factors=_thesis_factors(text),
        media_assets=media_assets,
    )


def _industry_candidate_tickers(industries: list[str]) -> list[str]:
    # Kept for backwards-compatible API; no longer used for source-derived candidates.
    candidates: list[str] = []
    for industry in industries:
        for symbol in LOW_MARGIN_INDUSTRY_TICKERS.get(industry, []):
            if symbol not in candidates:
                candidates.append(symbol)
    return candidates


def _build_basket_from_thesis(thesis: SourceThesis) -> list[BasketMember]:
    basket: list[BasketMember] = []

    for symbol in thesis.candidate_tickers:
        basket.append(
            BasketMember(
                symbol=symbol,
                role="candidate",
                industry="source explicit",
                reason="explicit source text mention",
            )
        )

    for symbol in _dedupe_symbols(thesis.control_tickers):
        basket.append(
            BasketMember(
                symbol=symbol,
                role="control",
                industry="controls for validation",
                reason="baseline operational control",
            )
        )

    for symbol in _dedupe_symbols(BENCHMARKS):
        basket.append(
            BasketMember(
                symbol=symbol,
                role="benchmark",
                industry="market benchmark",
                reason="required benchmark/control",
            )
        )

    return basket


def build_basket(thesis: SourceThesis) -> list[BasketMember]:
    return _build_basket_from_thesis(thesis)


def evaluate_thesis_basket(
    thesis: SourceThesis,
    days: int = 260,
    prefer_network: bool = False,
) -> ThesisRun:
    basket = build_basket(thesis)
    warnings: list[str] = []

    parsed = _parse_datetime(thesis.captured_date)
    posted_date = parsed.date() if parsed else None

    spy_return: float | None = None
    source_window_start = thesis.captured_date
    source_window_end = ""

    evaluations: list[BasketEvaluation] = []
    benchmarks: dict[str, BasketEvaluation] = {}

    if parsed is None:
        warnings.append("Missing parseable source timestamp; post-source window is blocked for safety.")

    for member in basket:
        bars, bars_source = fetch_prices(member.symbol, days=days, prefer_network=prefer_network)
        window = _bars_after_timestamp(bars, thesis.captured_date)
        if bars:
            source_window_end = bars[-1].date.isoformat()

        total_ret, latest = _returns_from_window(window)

        if not bars:
            warnings.append(f"No price data for {member.symbol}.")
            continue

        if not window:
            if posted_date and bars:
                if bars[-1].date <= posted_date:
                    warnings.append(
                        f"No post-source market window for {member.symbol}; source timestamp {thesis.captured_date or 'n/a'} blocks same-day/future evidence."
                    )
            else:
                warnings.append(
                    f"No post-source market window for {member.symbol}; source timestamp was missing or unparsable."
                )

        factor, factor_source = _safe_factor(member.symbol, prefer_network=prefer_network)
        gm = factor.gross_margin if factor is not None else None
        growth = factor.revenue_growth_yoy if factor is not None else None

        if _is_synthetic_like(bars_source):
            warnings.append(
                f"{member.symbol}: price source '{bars_source}'; evidence is not a direct live-market confirmation relative to post-source time."
            )
        if bars_source in {"cache", "cache_synthetic"} and posted_date and bars and bars[-1].date <= posted_date:
            warnings.append(
                f"{member.symbol}: latest bar {bars[-1].date} is not after source timestamp {posted_date}; data may be stale for this evaluation."
            )

        window_start = window[0].date.isoformat() if window else ""
        window_end = window[-1].date.isoformat() if window else ""

        reason = f"source-anchored evaluation against post timestamp {thesis.captured_date or 'n/a'}"
        if not window:
            reason = "insufficient post-source evidence"

        eval_obj = BasketEvaluation(
            symbol=member.symbol,
            role=member.role,
            industry=member.industry,
            total_return=total_ret,
            vs_spy=None,
            latest_close=latest,
            data_source=bars_source,
            factor_source=factor_source,
            gross_margin=gm,
            revenue_growth_yoy=growth,
            reason=reason,
            window_start=window_start,
            window_end=window_end,
        )

        if member.role == "benchmark":
            benchmarks[member.symbol] = eval_obj
        else:
            evaluations.append(eval_obj)

    spy_return = benchmarks.get(
        "SPY",
        BasketEvaluation(
            symbol="",
            role="",
            industry="",
            total_return=None,
            vs_spy=None,
            latest_close=None,
            data_source="",
            factor_source="",
            gross_margin=None,
            revenue_growth_yoy=None,
            reason="",
            window_start="",
            window_end="",
        ),
    ).total_return

    updated: list[BasketEvaluation] = []
    for eval_obj in evaluations:
        vs_spy = None
        if eval_obj.total_return is not None and spy_return is not None:
            vs_spy = eval_obj.total_return - spy_return
        updated.append(replace(eval_obj, vs_spy=vs_spy))
    evaluations = updated

    candidate_evals = [e for e in evaluations if e.role == "candidate"]
    if not thesis.candidate_tickers:
        warnings.append("No explicit source candidate tickers found; no source-derived candidates were identified.")

    if not evaluations:
        promotion_status = "research_only_insufficient_data"
    elif not candidate_evals:
        promotion_status = "research_only_no_source_candidates"
    elif any(_is_synthetic_like(item.data_source) for item in evaluations):
        promotion_status = "research_only_synthetic_or_stale_data"
    else:
        candidate_vals = [e.total_return for e in candidate_evals if e.total_return is not None]
        if spy_return is None:
            promotion_status = "research_only_insufficient_benchmark_evidence"
        elif candidate_vals and statistics.mean(candidate_vals) > spy_return:
            promotion_status = "mock_tracking_candidate_requires_review"
        else:
            promotion_status = "research_only_no_strong_candidate_signal"

    return ThesisRun(
        thesis=thesis,
        basket=basket,
        evaluations=evaluations,
        benchmarks=benchmarks,
        promotion_status=promotion_status,
        warnings=warnings,
        market_window_start=source_window_start,
        market_window_end=source_window_end,
    )


def _fmt_pct(value: float | None) -> str:
    return f"{value:+.1%}" if value is not None else "n/a"


def _fmt_num(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def _fmt_eval_rows(items: Iterable[BasketEvaluation]) -> list[str]:
    rows = ["| Symbol | Role | Industry | Return | vs SPY | Window | Latest | Data Source | Reason |", "|---|---|---|---:|---:|---|---:|---|---|"]
    for item in sorted(items, key=lambda x: (x.role, x.symbol)):
        rows.append(
            f"| {item.symbol} | {item.role} | {item.industry} | {_fmt_pct(item.total_return)} | {_fmt_pct(item.vs_spy)} | {item.window_start or 'n/a'}→{item.window_end or 'n/a'} | {_fmt_num(item.latest_close)} | {item.data_source} | {_escape_md(item.reason)} |"
        )
    return rows


def render_thesis_report(run: ThesisRun) -> str:
    t = run.thesis
    lines: list[str] = [
        f"# Source Thesis Analysis: {t.title}",
        f"- Source URL: {t.url or 'n/a'}",
        f"- Author: {t.author or 'n/a'}",
        f"- Captured date (UTC): {t.captured_date or 'n/a'}",
        f"- Source quality: {t.source_quality}",
        f"- Promotion status: **{run.promotion_status}**",
        f"- Guardrail: {t.guardrail}",
        "",
        f"- Market window anchor: {run.market_window_start or 'missing/unparsable'}",
        f"- Market window end (latest fetched bar): {run.market_window_end or 'n/a'}",
        f"- Source-derived candidates: {', '.join(t.candidate_tickers) if t.candidate_tickers else 'none'}",
        f"- Source controls: {', '.join(t.control_tickers) if t.control_tickers else 'none'}",
        f"- Benchmarks: {', '.join(BENCHMARKS)}",
        "",
        "## Direct quotes with provenance",
        "| Claim quote | Source URL | Citation | Author | Source time |",
        "|---|---|---|---|---|",
    ]

    for claim in t.claims:
        lines.append(
            f"| {_escape_md(claim.text)} | {_escape_md(claim.source_url)} | {_escape_md(claim.citation)} | {_escape_md(claim.author or 'n/a')} | {_escape_md(claim.captured_at)} |"
        )

    if not t.claims:
        lines.append("- No direct claims extracted.")

    lines.extend([
        "",
        "## Source factors",
    ])
    for factor in t.factors:
        lines.extend(
            [
                f"### {factor.name}",
                f"- Description: {factor.description}",
                f"- Evidence snippets: {len(factor.evidence)}",
                f"- Confidence: {factor.confidence:.2f}",
                f"- Unavailable fields: {', '.join(factor.unavailable_fields) if factor.unavailable_fields else 'none'}",
                "",
            ]
        )

    lines.extend([
        "## Media provenance",
    ])
    if t.media_assets:
        lines.extend(
            [
                "| Media ID | Media URL | Local path | Dimensions | Interpretation status | Source artifact |",
                "|---|---|---|---|---|---|",
            ]
        )
        for media in t.media_assets:
            dims = f"{media.width or '?'}x{media.height or '?'}"
            lines.append(
                f"| {media.media_id or 'n/a'} | {_escape_md(media.media_url)} | {_escape_md(media.local_path)} | {dims} | {_escape_md(media.interpretation_status)} | {_escape_md(media.source_artifact)} |"
            )
    else:
        lines.append("- No media manifest found; no attached media assets available.")

    lines.extend(
        [
            "",
            "## Basket evaluations",
            "### Source-derived candidates",
        ]
    )
    candidate_rows = [item for item in run.evaluations if item.role == "candidate"]
    if candidate_rows:
        lines.extend(_fmt_eval_rows(candidate_rows))
    else:
        lines.append("- No source-derived candidates were identified.")

    lines.extend(["", "### Controls", "", ""])
    control_rows = [item for item in run.evaluations if item.role == "control"]
    if control_rows:
        lines.extend(_fmt_eval_rows(control_rows))

    lines.extend(["", "### Benchmarks", "", ""])
    if run.benchmarks:
        lines.extend(_fmt_eval_rows(run.benchmarks.values()))

    lines.extend(
        [
            "",
            "## Warnings / gating checks",
            "- Source timestamp is used as the strict lower bound for post-source evidence windows; same-day evidence is intentionally excluded.",
            "- Candidate tickers are only those explicitly present in source text; no silent inference is performed.",
            "- Controls and benchmarks are included for comparison and are not source-derived candidates.",
            "- This report does not queue orders or touch broker/order state.",
            "- Source-derived runs with synthetic or cache-only data are flagged and are research/mock only.",
        ]
    )
    for warning in run.warnings:
        lines.append(f"- {warning}")

    return "\n".join(lines)


def save_thesis_run(run: ThesisRun, slug: str | None = None) -> tuple[Path, Path]:
    ensure_dirs()
    safe_slug = slug or _slugify(run.thesis.title)
    json_path = SOURCE_THESIS_DIR / f"{safe_slug}.json"
    report_path = SOURCE_THESIS_REPORT_DIR / f"{safe_slug}.md"
    json_path.write_text(json.dumps(asdict(run), indent=2, sort_keys=True))
    report = render_thesis_report(run)
    report_path.write_text(report)
    (SOURCE_THESIS_REPORT_DIR / "latest.md").write_text(report)
    return json_path, report_path


def extract_source_thesis_from_file(
    path: str,
    url: str = "",
    title: str = "",
    author: str = "",
) -> SourceThesis:
    source_path = Path(path)
    if not source_path.exists():
        raise FileNotFoundError(f"Missing source file: {path}")

    source_text = ""
    source_timestamp = ""
    source_title = title
    source_author = author
    source_url = url

    if source_path.suffix.lower() == ".json":
        payload = json.loads(source_path.read_text(errors="replace"))
        if isinstance(payload, dict):
            tweet = payload.get("tweet", {}) if isinstance(payload.get("tweet"), dict) else payload
            source_text = str(tweet.get("text") or tweet.get("raw_text") or "")
            source_url = source_url or str(tweet.get("url") or "")
            source_timestamp = str(tweet.get("created_at") or "")

            if not source_title:
                source_title = str(tweet.get("title") or source_path.stem)

            if not source_author:
                tw_author = tweet.get("author")
                if isinstance(tw_author, dict):
                    source_author = str(
                        tw_author.get("name")
                        or tw_author.get("username")
                        or tw_author.get("screen_name")
                        or ""
                    )
                elif isinstance(tw_author, str):
                    source_author = tw_author
                else:
                    tw_author = payload.get("user", {})
                    if isinstance(tw_author, dict):
                        source_author = str(
                            tw_author.get("name")
                            or tw_author.get("screen_name")
                            or source_author
                        )
        else:
            source_text = ""
            source_timestamp = ""
    else:
        source_text = source_path.read_text(errors="replace")
        source_title = title or _title_from_markdown(source_text)
        source_timestamp = _metadata_value(source_text, ["Created", "Captured", "created", "captured"])
        if not source_url:
            source_url = _metadata_value(source_text, ["Source post", "Canonical post URL", "source", "Source URL"])
        if not source_author:
            source_author = _metadata_value(source_text, ["Author", "author", "By", "by"])

    manifest = source_path.parent / "media_manifest.json"
    return extract_source_thesis(
        markdown_text=source_text,
        url=source_url,
        title=source_title,
        author=source_author,
        source_artifact=str(source_path),
        source_timestamp=source_timestamp,
        media_manifest_path=manifest if manifest.exists() else None,
        capture_dir=source_path.parent,
        captured_at=source_timestamp,
    )


def _locate_capture_file(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        match = root / name
        if match.exists():
            return match
    candidates = sorted(root.glob("*.json"))
    for c in candidates:
        if "fxtwitter" in c.name or c.name.startswith("https"):
            return c
    return candidates[0] if candidates else None


def extract_source_thesis_from_capture_dir(capture_dir: str, *, prefer_network: bool = False, days: int = 260) -> ThesisRun:
    # Kept for CLI and test compatibility.
    root = Path(capture_dir)
    source_json = _locate_capture_file(
        root,
        (
            "source.json",
            "tweet.json",
            "https_api_fxtwitter_com_i_status_2076492034064425454.json",
        ),
    )
    source_md = _locate_capture_file(root, ("source.md", "article.md", "claim-vs-evidence.md"))

    if source_json is not None:
        thesis = extract_source_thesis_from_file(str(source_json), title="", author="")
    elif source_md is not None:
        raw = source_md.read_text(errors="replace")
        source_url = _metadata_value(raw, ["Source post", "Canonical post URL", "source post", "canonical post url"])
        source_title = _title_from_markdown(raw)
        captured = _metadata_value(raw, ["Created", "Captured", "Created UTC", "captured"])
        source_author = _metadata_value(raw, ["Author", "author"])
        manifest = root / "media_manifest.json"
        thesis = extract_source_thesis(
            markdown_text=raw,
            url=source_url,
            title=source_title,
            author=source_author,
            source_timestamp=captured,
            media_manifest_path=manifest if manifest.exists() else None,
            source_artifact=str(source_md),
            capture_dir=root,
            captured_at=captured,
        )
    else:
        raise FileNotFoundError(f"No source file found in capture directory: {root}")

    # Ignore prefer_network for now in extract step; it is passed into evaluation.
    return evaluate_thesis_basket(thesis, days=days, prefer_network=prefer_network)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build source-thesis artifacts for a source capture directory")
    parser.add_argument("capture_dir", help="Directory containing source JSON, markdown, and media manifest files")
    parser.add_argument("--network", action="store_true", help="Allow network-backed prices")
    parser.add_argument("--days", type=int, default=260, help="Price history window to fetch")
    parser.add_argument("--slug", default=None, help="Optional slug override for output names")
    parser.add_argument("--no-save", action="store_true", help="Render report only; do not persist run files")
    parser.add_argument("--run-log", default="", help="Write run log to this path (defaults under capture directory)")
    args = parser.parse_args(argv)

    run = extract_source_thesis_from_capture_dir(args.capture_dir, prefer_network=args.network, days=args.days)
    if args.no_save:
        print(render_thesis_report(run))
        return 0

    json_path, report_path = save_thesis_run(run, slug=args.slug)
    log_path = Path(args.run_log) if args.run_log else Path(args.capture_dir) / "source_thesis_run_log.json"

    run_log = {
        "capture_dir": str(Path(args.capture_dir).resolve()),
        "status": run.promotion_status,
        "claim_count": len(run.thesis.claims),
        "media_assets": len(run.thesis.media_assets),
        "source_window_start": run.market_window_start,
        "source_window_end": run.market_window_end,
        "source_candidate_tickers": run.thesis.candidate_tickers,
        "warnings": run.warnings,
        "outputs": {
            "json": str(json_path),
            "markdown": str(report_path),
            "latest": str(SOURCE_THESIS_REPORT_DIR / "latest.md"),
            "run_log": str(log_path),
        },
    }
    log_path.write_text(json.dumps(run_log, indent=2, sort_keys=True))
    SOURCE_THESIS_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_THESIS_DIR.joinpath("run_log.json").write_text(json.dumps(run_log, indent=2, sort_keys=True))

    print(f"JSON: {json_path}")
    print(f"Report: {report_path}")
    print(f"Latest: {SOURCE_THESIS_REPORT_DIR / 'latest.md'}")
    print(f"Run log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
