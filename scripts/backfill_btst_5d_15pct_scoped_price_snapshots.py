from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_btst_5d_15pct_scoped_missing_price_manifest import (
    DEFAULT_OUTPUT_JSON as DEFAULT_MANIFEST_JSON,
)

DEFAULT_REPORTS_ROOT = Path("data/reports")
DEFAULT_LOCAL_SNAPSHOT_ROOT = Path("data/snapshots")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_5d_15pct_scoped_price_backfill_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_5d_15pct_scoped_price_backfill_latest.md")
DEFAULT_PRIORITY_BUCKETS = ("p0_trend_top40_missing_ticker_snapshot_root",)


FetchPricesFn = Callable[[str, str, str], Iterable[Any]]


def _load_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _parse_trade_date(value: str) -> datetime:
    return datetime.strptime(str(value), "%Y-%m-%d")


def _fetch_window(trade_date: str, *, lookback_calendar_days: int, forward_calendar_days: int) -> tuple[str, str]:
    parsed = _parse_trade_date(trade_date)
    start_date = (parsed - timedelta(days=lookback_calendar_days)).strftime("%Y-%m-%d")
    end_date = (parsed + timedelta(days=forward_calendar_days)).strftime("%Y-%m-%d")
    return start_date, end_date


def _target_paths(row: dict[str, Any], reports_root: Path) -> list[Path]:
    report_dir_names = list(row.get("report_dir_names") or [])
    if not report_dir_names and row.get("report_dir_name"):
        report_dir_names = [str(row.get("report_dir_name"))]
    ticker = str(row.get("ticker") or "")
    trade_date = str(row.get("trade_date") or "")
    paths = [reports_root / str(report_dir_name) / "data_snapshots" / ticker / trade_date / "prices.json" for report_dir_name in report_dir_names if report_dir_name and ticker and trade_date]
    return sorted(dict.fromkeys(paths))


def _serialize_price(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        payload = row.model_dump()
    elif isinstance(row, dict):
        payload = dict(row)
    else:
        payload = dict(row)
    return {
        "open": float(payload["open"]),
        "close": float(payload["close"]),
        "high": float(payload["high"]),
        "low": float(payload["low"]),
        "volume": int(payload["volume"]),
        "time": str(payload["time"]),
    }


def _write_prices(path: Path, prices: list[dict[str, Any]], *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def _read_price_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = payload if isinstance(payload, list) else list(payload.get("prices") or [])
    serialized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            serialized.append(_serialize_price(row))
        except (KeyError, TypeError, ValueError):
            continue
    return serialized


def _price_dates(prices: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row.get("time") or "") for row in prices if row.get("time")})


def _prices_cover_trade_date(prices: list[dict[str, Any]], trade_date: str) -> bool:
    return trade_date in set(_price_dates(prices))


def _prices_cover_repair_window(prices: list[dict[str, Any]], trade_date: str, *, missing_reason: str) -> bool:
    if not _prices_cover_trade_date(prices, trade_date):
        return False
    if missing_reason != "local_snapshot_missing_future_bar":
        return True
    future_dates = [date for date in _price_dates(prices) if date > trade_date]
    return len(future_dates) >= 2


def _iter_local_price_paths(
    *,
    ticker: str,
    reports_root: Path,
    local_snapshot_roots: list[Path],
    scan_report_snapshots: bool,
) -> list[Path]:
    paths: list[Path] = []
    for root in local_snapshot_roots:
        paths.extend(sorted(root.expanduser().resolve().glob(f"{ticker}/*/prices.json")))
    if scan_report_snapshots and reports_root.exists():
        paths.extend(sorted(reports_root.glob(f"*/data_snapshots/{ticker}/*/prices.json")))
    return sorted(dict.fromkeys(path.resolve() for path in paths if path.exists()))


def _find_local_price_source(
    *,
    ticker: str,
    trade_date: str,
    missing_reason: str,
    reports_root: Path,
    local_snapshot_roots: list[Path],
    scan_report_snapshots: bool,
    local_price_cache: dict[str, list[tuple[Path, list[dict[str, Any]]]]],
) -> tuple[Path, list[dict[str, Any]]] | None:
    if ticker not in local_price_cache:
        cached: list[tuple[Path, list[dict[str, Any]]]] = []
        for path in _iter_local_price_paths(
            ticker=ticker,
            reports_root=reports_root,
            local_snapshot_roots=local_snapshot_roots,
            scan_report_snapshots=scan_report_snapshots,
        ):
            rows = _read_price_rows(path)
            if rows:
                cached.append((path, rows))
        local_price_cache[ticker] = cached

    candidates = [(path, rows) for path, rows in local_price_cache[ticker] if _prices_cover_repair_window(rows, trade_date, missing_reason=missing_reason)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-len(item[1]), str(item[0])))[0]


def _default_fetch_prices(ticker: str, start_date: str, end_date: str) -> Iterable[Any]:
    from src.tools.api import get_prices

    return get_prices(ticker, start_date, end_date)


def _select_manifest_rows(manifest: dict[str, Any], priority_buckets: set[str], max_requests: int | None) -> list[dict[str, Any]]:
    rows = [dict(row) for row in list(manifest.get("manifest_rows") or []) if str(row.get("priority_bucket") or "") in priority_buckets]
    rows.sort(key=lambda row: int(row.get("priority_rank") or 999999))
    return rows if not max_requests or max_requests <= 0 else rows[:max_requests]


def _result_row_base(row: dict[str, Any], target_paths: list[Path], fetch_start_date: str, fetch_end_date: str) -> dict[str, Any]:
    return {
        "priority_rank": row.get("priority_rank"),
        "priority_bucket": row.get("priority_bucket"),
        "ticker": row.get("ticker"),
        "trade_date": row.get("trade_date"),
        "event_prototype": row.get("event_prototype"),
        "local_price_missing_reason": row.get("local_price_missing_reason"),
        "priority_score": row.get("priority_score"),
        "occurrence_count": row.get("occurrence_count"),
        "fetch_start_date": fetch_start_date,
        "fetch_end_date": fetch_end_date,
        "target_paths": [str(path) for path in target_paths],
    }


def backfill_btst_5d_15pct_scoped_price_snapshots(
    manifest_path: str | Path,
    *,
    reports_root: str | Path = DEFAULT_REPORTS_ROOT,
    dry_run: bool = True,
    priority_buckets: list[str] | tuple[str, ...] = DEFAULT_PRIORITY_BUCKETS,
    max_requests: int | None = None,
    lookback_calendar_days: int = 120,
    forward_calendar_days: int = 14,
    force: bool = False,
    local_snapshot_roots: list[str | Path] | tuple[str | Path, ...] = (DEFAULT_LOCAL_SNAPSHOT_ROOT,),
    scan_report_snapshots: bool = True,
    local_only: bool = False,
    fetch_prices_fn: FetchPricesFn | None = None,
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    selected_rows = _select_manifest_rows(manifest, set(priority_buckets), max_requests)
    fetch_fn = fetch_prices_fn or _default_fetch_prices
    result_rows: list[dict[str, Any]] = []
    planned_target_count = 0
    written_target_count = 0
    skipped_existing_target_count = 0
    success_request_count = 0
    failed_request_count = 0
    local_source_request_count = 0
    skipped_no_local_source_request_count = 0
    local_price_cache: dict[str, list[tuple[Path, list[dict[str, Any]]]]] = {}
    resolved_local_snapshot_roots = [Path(root).expanduser().resolve() for root in local_snapshot_roots]

    for row in selected_rows:
        trade_date = str(row.get("trade_date") or "")
        ticker = str(row.get("ticker") or "")
        fetch_start_date, fetch_end_date = _fetch_window(
            trade_date,
            lookback_calendar_days=lookback_calendar_days,
            forward_calendar_days=forward_calendar_days,
        )
        paths = _target_paths(row, resolved_reports_root)
        planned_target_count += len(paths)
        result = _result_row_base(row, paths, fetch_start_date, fetch_end_date)
        if dry_run:
            result.update({"status": "dry_run", "price_row_count": None, "written_target_count": 0, "skipped_existing_target_count": 0})
            result_rows.append(result)
            continue

        local_source = _find_local_price_source(
            ticker=ticker,
            trade_date=trade_date,
            missing_reason=str(row.get("local_price_missing_reason") or ""),
            reports_root=resolved_reports_root,
            local_snapshot_roots=resolved_local_snapshot_roots,
            scan_report_snapshots=scan_report_snapshots,
            local_price_cache=local_price_cache,
        )
        if local_source is not None:
            source_path, prices = local_source
            request_written = 0
            request_skipped = 0
            for path in paths:
                if _write_prices(path, prices, force=force):
                    request_written += 1
                else:
                    request_skipped += 1
            written_target_count += request_written
            skipped_existing_target_count += request_skipped
            success_request_count += 1
            local_source_request_count += 1
            result.update(
                {
                    "status": "copied_local_snapshot" if request_written else "already_exists",
                    "source_path": str(source_path),
                    "price_row_count": len(prices),
                    "written_target_count": request_written,
                    "skipped_existing_target_count": request_skipped,
                }
            )
            result_rows.append(result)
            continue

        if local_only:
            skipped_no_local_source_request_count += 1
            result.update({"status": "missing_local_source", "price_row_count": 0, "written_target_count": 0, "skipped_existing_target_count": 0})
            result_rows.append(result)
            continue

        try:
            prices = [_serialize_price(price) for price in fetch_fn(ticker, fetch_start_date, fetch_end_date)]
        except Exception as exc:  # pragma: no cover - exercised through CLI/provider integration
            failed_request_count += 1
            result.update({"status": "fetch_error", "error": str(exc), "price_row_count": 0, "written_target_count": 0, "skipped_existing_target_count": 0})
            result_rows.append(result)
            continue

        if not prices:
            failed_request_count += 1
            result.update({"status": "no_prices", "price_row_count": 0, "written_target_count": 0, "skipped_existing_target_count": 0})
            result_rows.append(result)
            continue

        request_written = 0
        request_skipped = 0
        for path in paths:
            if _write_prices(path, prices, force=force):
                request_written += 1
            else:
                request_skipped += 1
        written_target_count += request_written
        skipped_existing_target_count += request_skipped
        success_request_count += 1
        result.update(
            {
                "status": "written" if request_written else "already_exists",
                "price_row_count": len(prices),
                "written_target_count": request_written,
                "skipped_existing_target_count": request_skipped,
            }
        )
        result_rows.append(result)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_path": str(Path(manifest_path).expanduser().resolve()),
        "reports_root": str(resolved_reports_root),
        "dry_run": dry_run,
        "priority_buckets": list(priority_buckets),
        "max_requests": max_requests,
        "lookback_calendar_days": lookback_calendar_days,
        "forward_calendar_days": forward_calendar_days,
        "force": force,
        "local_only": local_only,
        "local_snapshot_roots": [str(root) for root in resolved_local_snapshot_roots],
        "scan_report_snapshots": scan_report_snapshots,
        "selected_request_count": len(selected_rows),
        "planned_target_count": planned_target_count,
        "success_request_count": success_request_count,
        "failed_request_count": failed_request_count,
        "local_source_request_count": local_source_request_count,
        "skipped_no_local_source_request_count": skipped_no_local_source_request_count,
        "written_target_count": written_target_count,
        "skipped_existing_target_count": skipped_existing_target_count,
        "result_rows": result_rows,
    }


def render_btst_scoped_price_backfill_markdown(result: dict[str, Any], *, row_limit: int = 120) -> str:
    lines = ["# BTST 5D / 15% Scoped Price Backfill", ""]
    for key in (
        "dry_run",
        "selected_request_count",
        "planned_target_count",
        "success_request_count",
        "failed_request_count",
        "local_source_request_count",
        "skipped_no_local_source_request_count",
        "written_target_count",
        "skipped_existing_target_count",
    ):
        lines.append(f"- {key}: {result.get(key)}")
    lines.append("")
    lines.append("## Requests")
    for row in list(result.get("result_rows") or [])[:row_limit]:
        lines.append(f"- #{row.get('priority_rank')} {row.get('status')} {row.get('priority_bucket')} " f"{row.get('ticker')} {row.get('trade_date')} targets={len(row.get('target_paths') or [])} " f"prices={row.get('price_row_count')}")
    lines.append("")
    return "\n".join(lines)


def _stdout_summary(result: dict[str, Any], output_json: Path, output_md: Path) -> dict[str, Any]:
    return {
        "generated_at": result.get("generated_at"),
        "dry_run": result.get("dry_run"),
        "selected_request_count": result.get("selected_request_count"),
        "planned_target_count": result.get("planned_target_count"),
        "success_request_count": result.get("success_request_count"),
        "failed_request_count": result.get("failed_request_count"),
        "local_source_request_count": result.get("local_source_request_count"),
        "skipped_no_local_source_request_count": result.get("skipped_no_local_source_request_count"),
        "written_target_count": result.get("written_target_count"),
        "skipped_existing_target_count": result.get("skipped_existing_target_count"),
        "output_json": str(output_json),
        "output_md": str(output_md),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill report-local price snapshots from the scoped BTST missing-price manifest.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_JSON))
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--priority-bucket", action="append", dest="priority_buckets", default=None)
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument("--lookback-calendar-days", type=int, default=120)
    parser.add_argument("--forward-calendar-days", type=int, default=14)
    parser.add_argument("--local-snapshot-root", action="append", dest="local_snapshot_roots", default=None)
    parser.add_argument("--no-scan-report-snapshots", action="store_true", help="Do not search existing report-local data_snapshots as local sources.")
    parser.add_argument("--local-only", action="store_true", help="Use local snapshots only; do not call external price providers.")
    parser.add_argument("--execute", action="store_true", help="Fetch prices and write prices.json. Omit for dry-run planning.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing prices.json files.")
    parser.add_argument("--markdown-row-limit", type=int, default=120)
    args = parser.parse_args()

    result = backfill_btst_5d_15pct_scoped_price_snapshots(
        args.manifest,
        reports_root=args.reports_root,
        dry_run=not args.execute,
        priority_buckets=tuple(args.priority_buckets or DEFAULT_PRIORITY_BUCKETS),
        max_requests=args.max_requests,
        lookback_calendar_days=args.lookback_calendar_days,
        forward_calendar_days=args.forward_calendar_days,
        force=args.force,
        local_snapshot_roots=tuple(args.local_snapshot_roots or [DEFAULT_LOCAL_SNAPSHOT_ROOT]),
        scan_report_snapshots=not args.no_scan_report_snapshots,
        local_only=args.local_only,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_scoped_price_backfill_markdown(result, row_limit=args.markdown_row_limit), encoding="utf-8")
    print(json.dumps(_stdout_summary(result, output_json, output_md), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
