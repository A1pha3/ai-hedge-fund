"""Lookback audit: compare historical selection results against actual price performance.

Given an audit date, reads the selection_snapshot.json artifact for that date,
extracts the top-N selected tickers, fetches forward price data, and computes
per-ticker return metrics (absolute return, max drawdown).

This closes the feedback loop described in feature-proposals.md 6.2:
"30 days ago the top-10 candidates were selected; how much did they actually move?"

Usage (CLI):
    python -m src.research.lookback_audit --date 20260505 --days 30

Usage (API):
    GET /research/lookback-audit?date=YYYYMMDD&days=30
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.data.models import Price
from src.utils.date_utils import format_date as _format_date, parse_date as _parse_date


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TickerAuditResult:
    """Per-ticker audit result: how a selected candidate performed after selection."""

    ticker: str
    rank: int
    score_final: float
    entry_date: str
    entry_price: float | None
    exit_date: str | None
    exit_price: float | None
    return_pct: float | None
    max_drawdown_pct: float | None
    max_return_pct: float | None
    trading_days_held: int
    data_status: str  # "ok" | "no_entry_price" | "no_forward_data" | "empty_prices"


@dataclass
class LookbackAuditResult:
    """Full audit result for one audit date."""

    audit_date: str
    lookforward_days: int
    selected_count: int
    audited_count: int
    ticker_results: list[TickerAuditResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_selection_snapshot(artifact_root: Path, trade_date: str) -> dict[str, Any]:
    """Read a selection_snapshot.json from disk.

    artifact_root layout:
        <artifact_root>/<YYYY-MM-DD>/selection_snapshot.json
    """
    formatted = _format_date(trade_date)
    snapshot_path = artifact_root / formatted / "selection_snapshot.json"
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Selection snapshot not found: {snapshot_path}")
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def _extract_top_tickers(snapshot: dict[str, Any], top_n: int = 10) -> list[dict[str, Any]]:
    """Extract top-N tickers from the snapshot's selected list."""
    selected = snapshot.get("selected") or []
    # selected is already sorted by score_final descending (from artifacts.py)
    return [
        {
            "ticker": str(entry.get("symbol") or ""),
            "rank": idx + 1,
            "score_final": float(entry.get("score_final") or 0.0),
        }
        for idx, entry in enumerate(selected[:top_n])
        if str(entry.get("symbol") or "").strip()
    ]


def _compute_max_drawdown(prices: list[Price]) -> float | None:
    """Compute maximum drawdown percentage from a price series.

    Returns a negative number (e.g., -0.12 for 12% drawdown), or None if < 2 prices.
    """
    if len(prices) < 2:
        return None
    peak = prices[0].close
    max_dd = 0.0
    for price in prices[1:]:
        if price.close > peak:
            peak = price.close
        dd = (price.close - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    return round(max_dd * 100, 4) if max_dd < 0 else 0.0


def _compute_max_return(prices: list[Price]) -> float | None:
    """Compute maximum return percentage from entry price.

    Returns a positive number for gains, negative for losses. None if < 2 prices.
    """
    if len(prices) < 2:
        return None
    entry = prices[0].close
    if entry <= 0:
        return None
    max_ret = max((p.close - entry) / entry for p in prices[1:])
    return round(max_ret * 100, 4)


def _filter_prices_in_window(
    prices: list[Price],
    start_date: datetime,
    end_date: datetime,
) -> list[Price]:
    """Keep only prices within [start_date, end_date] inclusive."""
    result: list[Price] = []
    for price in prices:
        try:
            price_date = datetime.strptime(str(price.time)[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if start_date <= price_date <= end_date:
            result.append(price)
    return result


# ---------------------------------------------------------------------------
# Price fetcher protocol (for testability)
# ---------------------------------------------------------------------------

class PriceFetcher:
    """Fetches forward prices for a given ticker and date range."""

    def __init__(self, use_robust: bool = True) -> None:
        self._use_robust = use_robust

    def fetch(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[Price]:
        """Fetch daily prices for ticker from start_date to end_date."""
        try:
            if self._use_robust:
                from src.tools.akshare_api import get_prices_robust
                return get_prices_robust(ticker, start_date, end_date)
            else:
                from src.tools.akshare_api import get_prices
                return get_prices(ticker, start_date, end_date)
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Core audit function
# ---------------------------------------------------------------------------

def run_lookback_audit(
    *,
    audit_date: str,
    lookforward_days: int = 30,
    top_n: int = 10,
    artifact_root: Path | str | None = None,
    price_fetcher: PriceFetcher | None = None,
) -> LookbackAuditResult:
    """Run the lookback audit for a given date.

    Args:
        audit_date: The selection date (YYYYMMDD or YYYY-MM-DD).
        lookforward_days: How many calendar days to look forward.
        top_n: How many top tickers to audit.
        artifact_root: Root directory for selection artifacts. If None,
            searches common locations.
        price_fetcher: Custom price fetcher (for testing). If None,
            uses the default PriceFetcher.

    Returns:
        LookbackAuditResult with per-ticker metrics.
    """
    if artifact_root is None:
        artifact_root = _find_artifact_root(audit_date)
    else:
        artifact_root = Path(artifact_root)

    if price_fetcher is None:
        price_fetcher = PriceFetcher()

    formatted_audit_date = _format_date(audit_date)
    audit_dt = _parse_date(audit_date)
    forward_end_dt = audit_dt + timedelta(days=lookforward_days)
    forward_end_str = forward_end_dt.strftime("%Y-%m-%d")

    # Read the selection snapshot
    try:
        snapshot = _read_selection_snapshot(artifact_root, formatted_audit_date)
    except FileNotFoundError:
        return LookbackAuditResult(
            audit_date=formatted_audit_date,
            lookforward_days=lookforward_days,
            selected_count=0,
            audited_count=0,
            summary={"error": f"Selection snapshot not found for {formatted_audit_date}"},
        )

    top_tickers = _extract_top_tickers(snapshot, top_n)
    if not top_tickers:
        return LookbackAuditResult(
            audit_date=formatted_audit_date,
            lookforward_days=lookforward_days,
            selected_count=0,
            audited_count=0,
            summary={"warning": "No selected tickers found in snapshot"},
        )

    # Audit each ticker
    ticker_results: list[TickerAuditResult] = []
    for entry in top_tickers:
        ticker = entry["ticker"]
        rank = entry["rank"]
        score_final = entry["score_final"]

        prices = price_fetcher.fetch(ticker, formatted_audit_date, forward_end_str)

        # Filter to only forward window (exclude the audit date itself or include it)
        forward_prices = _filter_prices_in_window(
            prices,
            audit_dt,
            forward_end_dt,
        )

        # Drop rows with non-finite close (defensive against upstream data
        # corruption — a NaN close would silently propagate into return_pct /
        # max_drawdown_pct / max_return_pct and surface as NaN in JSON).
        forward_prices = [
            p for p in forward_prices
            if isinstance(p.close, (int, float)) and p.close == p.close  # second check filters NaN
        ]

        if not forward_prices:
            ticker_results.append(TickerAuditResult(
                ticker=ticker,
                rank=rank,
                score_final=score_final,
                entry_date=formatted_audit_date,
                entry_price=None,
                exit_date=None,
                exit_price=None,
                return_pct=None,
                max_drawdown_pct=None,
                max_return_pct=None,
                trading_days_held=0,
                data_status="no_forward_data",
            ))
            continue

        entry_price = forward_prices[0].close
        last_price = forward_prices[-1].close
        exit_date = str(forward_prices[-1].time)[:10]

        if entry_price <= 0:
            ticker_results.append(TickerAuditResult(
                ticker=ticker,
                rank=rank,
                score_final=score_final,
                entry_date=formatted_audit_date,
                entry_price=entry_price,
                exit_date=exit_date,
                exit_price=last_price,
                return_pct=None,
                max_drawdown_pct=None,
                max_return_pct=None,
                trading_days_held=len(forward_prices),
                data_status="no_entry_price",
            ))
            continue

        return_pct = round((last_price - entry_price) / entry_price * 100, 4)
        max_dd = _compute_max_drawdown(forward_prices)
        max_ret = _compute_max_return(forward_prices)

        ticker_results.append(TickerAuditResult(
            ticker=ticker,
            rank=rank,
            score_final=score_final,
            entry_date=formatted_audit_date,
            entry_price=round(entry_price, 4),
            exit_date=exit_date,
            exit_price=round(last_price, 4),
            return_pct=return_pct,
            max_drawdown_pct=max_dd,
            max_return_pct=max_ret,
            trading_days_held=len(forward_prices),
            data_status="ok",
        ))

    # Build summary
    ok_results = [r for r in ticker_results if r.data_status == "ok"]
    summary: dict[str, Any] = {
        "total_selected": len(top_tickers),
        "total_audited_ok": len(ok_results),
        "total_no_data": len(ticker_results) - len(ok_results),
    }
    if ok_results:
        returns = [r.return_pct for r in ok_results if r.return_pct is not None]
        if returns:
            summary["avg_return_pct"] = round(sum(returns) / len(returns), 4)
            summary["median_return_pct"] = round(sorted(returns)[len(returns) // 2], 4)
            summary["hit_rate"] = round(sum(1 for r in returns if r > 0) / len(returns), 4)
            summary["best_return_pct"] = round(max(returns), 4)
            summary["worst_return_pct"] = round(min(returns), 4)
        drawdowns = [r.max_drawdown_pct for r in ok_results if r.max_drawdown_pct is not None]
        if drawdowns:
            summary["avg_max_drawdown_pct"] = round(sum(drawdowns) / len(drawdowns), 4)

    return LookbackAuditResult(
        audit_date=formatted_audit_date,
        lookforward_days=lookforward_days,
        selected_count=len(top_tickers),
        audited_count=len(ok_results),
        ticker_results=ticker_results,
        summary=summary,
    )


def _find_artifact_root(audit_date: str) -> Path:
    """Try to find the artifact root by searching common locations."""
    repo_root = Path(__file__).resolve().parents[2]
    formatted = _format_date(audit_date)

    # Check common locations in order of priority
    candidates = [
        repo_root / "data" / "paper_trading_window_sample" / "selection_artifacts",
        repo_root / "data" / "selection_artifacts",
    ]

    # Also check report directories
    reports_root = repo_root / "data" / "reports"
    if reports_root.exists():
        for report_dir in sorted(reports_root.iterdir()):
            if not report_dir.is_dir():
                continue
            sa = report_dir / "selection_artifacts"
            if (sa / formatted / "selection_snapshot.json").exists():
                return sa

    for candidate in candidates:
        if (candidate / formatted / "selection_snapshot.json").exists():
            return candidate

    # Fallback: return the first candidate that exists, even without the specific date
    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Last resort: return a default path
    return repo_root / "data" / "selection_artifacts"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_audit_table(result: LookbackAuditResult) -> str:
    """Format the audit result as a human-readable table."""
    lines: list[str] = []
    lines.append(f"Lookback Audit: {result.audit_date} +{result.lookforward_days}d")
    lines.append("=" * 80)
    lines.append(
        f"{'Rank':>4}  {'Ticker':<8}  {'Score':>8}  {'Entry':>10}  {'Exit':>10}  "
        f"{'Return%':>9}  {'MaxDD%':>8}  {'MaxRet%':>9}  {'Days':>4}  {'Status':<16}"
    )
    lines.append("-" * 80)

    for tr in result.ticker_results:
        ret_str = f"{tr.return_pct:+.2f}" if tr.return_pct is not None else "N/A"
        dd_str = f"{tr.max_drawdown_pct:.2f}" if tr.max_drawdown_pct is not None else "N/A"
        mr_str = f"{tr.max_return_pct:+.2f}" if tr.max_return_pct is not None else "N/A"
        entry_str = f"{tr.entry_price:.2f}" if tr.entry_price is not None else "N/A"
        exit_str = f"{tr.exit_price:.2f}" if tr.exit_price is not None else "N/A"
        lines.append(
            f"{tr.rank:>4}  {tr.ticker:<8}  {tr.score_final:>8.4f}  {entry_str:>10}  {exit_str:>10}  "
            f"{ret_str:>9}  {dd_str:>8}  {mr_str:>9}  {tr.trading_days_held:>4}  {tr.data_status:<16}"
        )

    lines.append("-" * 80)
    s = result.summary
    if s.get("avg_return_pct") is not None:
        lines.append(f"Summary: avg_return={s['avg_return_pct']:+.2f}%  "
                      f"median={s.get('median_return_pct', 'N/A')}%  "
                      f"hit_rate={s.get('hit_rate', 'N/A')}  "
                      f"best={s.get('best_return_pct', 'N/A')}%  "
                      f"worst={s.get('worst_return_pct', 'N/A')}%  "
                      f"avg_maxDD={s.get('avg_max_drawdown_pct', 'N/A')}%")
    lines.append(f"Audited: {result.audited_count}/{result.selected_count} tickers with data")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Lookback audit: compare selection results against actual performance",
    )
    parser.add_argument(
        "--date", required=True,
        help="Audit date in YYYYMMDD or YYYY-MM-DD format",
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Lookforward window in calendar days (default: 30)",
    )
    parser.add_argument(
        "--top-n", type=int, default=10,
        help="How many top tickers to audit (default: 10)",
    )
    parser.add_argument(
        "--artifact-root", type=str, default=None,
        help="Override artifact root directory",
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json",
        help="Output as JSON instead of table",
    )
    args = parser.parse_args(argv)

    result = run_lookback_audit(
        audit_date=args.date,
        lookforward_days=args.days,
        top_n=args.top_n,
        artifact_root=Path(args.artifact_root) if args.artifact_root else None,
    )

    if args.output_json:
        output = {
            "audit_date": result.audit_date,
            "lookforward_days": result.lookforward_days,
            "selected_count": result.selected_count,
            "audited_count": result.audited_count,
            "ticker_results": [asdict(tr) for tr in result.ticker_results],
            "summary": result.summary,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(format_audit_table(result))


if __name__ == "__main__":
    main()
