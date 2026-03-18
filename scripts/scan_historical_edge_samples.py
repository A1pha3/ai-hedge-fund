from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_REPORTS_DIR = Path("data/reports")
JSON_GLOBS = ("*.json", "*.jsonl")


def _iter_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in JSON_GLOBS:
        paths.extend(root.rglob(pattern))
    return sorted(path for path in paths if path.is_file() and not path.name.startswith("historical_edge_sample_scan_"))


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def _append_context(base_context: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    context = dict(base_context)
    for key in ("trade_date", "date", "ticker", "decision", "bc_conflict", "event", "variant", "source"):
        if key not in payload:
            continue
        value = payload.get(key)
        if _is_scalar(value):
            context[key] = value
    return context


def _normalize_trade_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return text
    return text or None


def _build_record(payload: dict[str, Any], context: dict[str, Any], source_path: Path, path_hint: str) -> dict[str, Any] | None:
    ticker = payload.get("ticker")
    score_final = payload.get("score_final")
    decision = payload.get("decision")
    if not isinstance(ticker, str) or score_final is None or not isinstance(decision, str):
        return None

    score_b = payload.get("score_b")
    score_c = payload.get("score_c")
    bc_conflict = payload.get("bc_conflict")
    trade_date = _normalize_trade_date(payload.get("trade_date") or context.get("trade_date") or payload.get("date") or context.get("date"))
    record = {
        "source": str(source_path),
        "path_hint": path_hint,
        "trade_date": trade_date,
        "ticker": ticker,
        "decision": decision,
        "bc_conflict": bc_conflict,
        "score_final": float(score_final),
        "score_b": float(score_b) if isinstance(score_b, (int, float)) else None,
        "score_c": float(score_c) if isinstance(score_c, (int, float)) else None,
        "event": payload.get("event") or context.get("event"),
        "variant": payload.get("variant") or context.get("variant"),
    }
    return record


def _walk_json(node: Any, source_path: Path, context: dict[str, Any], path_hint: str, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        next_context = _append_context(context, node)
        record = _build_record(node, next_context, source_path, path_hint)
        if record is not None:
            out.append(record)
        for key, value in node.items():
            child_hint = f"{path_hint}.{key}" if path_hint else str(key)
            _walk_json(value, source_path, next_context, child_hint, out)
        return

    if isinstance(node, list):
        for index, value in enumerate(node):
            child_hint = f"{path_hint}[{index}]" if path_hint else f"[{index}]"
            _walk_json(value, source_path, context, child_hint, out)


def _load_records(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if path.suffix == ".jsonl":
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            _walk_json(payload, path, {}, f"line[{line_number}]", rows)
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        _walk_json(payload, path, {}, "root", rows)
    return rows


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = (
            record["source"],
            record.get("trade_date"),
            record["ticker"],
            round(record["score_final"], 6),
            record["decision"],
            record.get("bc_conflict"),
            round(record["score_b"], 6) if isinstance(record.get("score_b"), float) else None,
            round(record["score_c"], 6) if isinstance(record.get("score_c"), float) else None,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _classify_band(record: dict[str, Any], lower_bound: float, near_min: float, near_max: float) -> str | None:
    if record["decision"] != "watch" or record.get("bc_conflict") is not None:
        return None
    score_final = record["score_final"]
    if near_min <= score_final <= near_max:
        return "near_threshold_watch"
    if lower_bound <= score_final < near_min:
        return "sub_threshold_watch"
    if score_final > near_max:
        return "high_score_watch"
    return None


def _summarize_bucket(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_ticker[record["ticker"]].append(record)

    ticker_summary: list[dict[str, Any]] = []
    for ticker, ticker_records in sorted(by_ticker.items()):
        scores = [row["score_final"] for row in ticker_records]
        dates = sorted({row["trade_date"] for row in ticker_records if row.get("trade_date")})
        sources = sorted({Path(row["source"]).name for row in ticker_records})
        ticker_summary.append(
            {
                "ticker": ticker,
                "count": len(ticker_records),
                "dates": dates,
                "score_final_min": round(min(scores), 4),
                "score_final_max": round(max(scores), 4),
                "sources": sources,
                "examples": [
                    {
                        "trade_date": row.get("trade_date"),
                        "score_final": round(row["score_final"], 4),
                        "score_b": round(row["score_b"], 4) if isinstance(row.get("score_b"), float) else None,
                        "score_c": round(row["score_c"], 4) if isinstance(row.get("score_c"), float) else None,
                        "source": row["source"],
                    }
                    for row in ticker_records[:5]
                ],
            }
        )

    return {
        "record_count": len(records),
        "unique_ticker_count": len(ticker_summary),
        "tickers": ticker_summary,
    }


def scan_reports(reports_dir: Path, lower_bound: float, near_min: float, near_max: float) -> dict[str, Any]:
    files = _iter_files(reports_dir)
    raw_records: list[dict[str, Any]] = []
    for path in files:
        raw_records.extend(_load_records(path))

    deduped = _dedupe_records(raw_records)
    classified: dict[str, list[dict[str, Any]]] = {
        "near_threshold_watch": [],
        "sub_threshold_watch": [],
        "high_score_watch": [],
    }
    for record in deduped:
        bucket = _classify_band(record, lower_bound=lower_bound, near_min=near_min, near_max=near_max)
        if bucket is not None:
            classified[bucket].append(record)

    return {
        "reports_dir": str(reports_dir),
        "files_scanned": len(files),
        "raw_record_count": len(raw_records),
        "deduped_record_count": len(deduped),
        "bands": {
            bucket: _summarize_bucket(records)
            for bucket, records in classified.items()
        },
    }


def _print_summary(report: dict[str, Any]) -> None:
    print(
        "scan_overview",
        {
            "reports_dir": report["reports_dir"],
            "files_scanned": report["files_scanned"],
            "raw_record_count": report["raw_record_count"],
            "deduped_record_count": report["deduped_record_count"],
        },
    )
    for bucket_name, payload in report["bands"].items():
        print(bucket_name, {"record_count": payload["record_count"], "unique_ticker_count": payload["unique_ticker_count"]})
        for row in payload["tickers"]:
            print(
                " ",
                {
                    "ticker": row["ticker"],
                    "count": row["count"],
                    "dates": row["dates"],
                    "score_range": [row["score_final_min"], row["score_final_max"]],
                    "sources": row["sources"],
                },
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan historical report artifacts for non-conflict watch samples")
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR), help="Reports directory to scan")
    parser.add_argument("--lower-bound", type=float, default=0.14, help="Lower bound for sub-threshold watch scan")
    parser.add_argument("--near-min", type=float, default=0.17, help="Minimum score_final for near-threshold band")
    parser.add_argument("--near-max", type=float, default=0.26, help="Maximum score_final for near-threshold band")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir).resolve()
    report = scan_reports(reports_dir=reports_dir, lower_bound=args.lower_bound, near_min=args.near_min, near_max=args.near_max)
    _print_summary(report)

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved_json {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())