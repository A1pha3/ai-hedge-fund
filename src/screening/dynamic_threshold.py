"""Dynamic Recommendation Threshold -- P7-2.

Adjusts the minimum score_b threshold for recommendations based on
recent system performance. If recent recommendations underperform,
the threshold rises (stricter filtering). If they outperform,
the threshold relaxes (more candidates).

This is a self-correcting mechanism: the system automatically
becomes more selective after a losing streak.

CLI:
    python src/main.py --dynamic-threshold
    python src/main.py --dynamic-threshold --lookback=30 --target-hit-rate=0.5

Integration:
    ``run_auto_screening()`` can use ``get_dynamic_threshold()``
    instead of hardcoded score_b >= 0.3.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.recommendation_tracker import (
    _latest_recommended_date,
    _parse_date,
)
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BASE_THRESHOLD: float = 0.30
_DEFAULT_MIN_THRESHOLD: float = 0.15
_DEFAULT_MAX_THRESHOLD: float = 0.60
_DEFAULT_TARGET_HIT_RATE: float = 0.50
_DEFAULT_LOOKBACK: int = 30


# ---------------------------------------------------------------------------
# Core dynamic threshold
# ---------------------------------------------------------------------------


def compute_dynamic_threshold(
    *,
    base_threshold: float = _DEFAULT_BASE_THRESHOLD,
    min_threshold: float = _DEFAULT_MIN_THRESHOLD,
    max_threshold: float = _DEFAULT_MAX_THRESHOLD,
    target_hit_rate: float = _DEFAULT_TARGET_HIT_RATE,
    lookback_days: int = _DEFAULT_LOOKBACK,
    reports_dir: Path | None = None,
) -> dict[str, Any]:
    """Compute dynamic recommendation threshold based on recent performance.

    Algorithm:
    1. Load recent tracking history (last N days)
    2. Calculate hit rate (recommendations that gained)
    3. If hit_rate < target: raise threshold (more strict)
    4. If hit_rate > target: lower threshold (more relaxed)
    5. Clamp to [min_threshold, max_threshold]

    Args:
        base_threshold: Starting threshold (default 0.30)
        min_threshold: Floor (default 0.15)
        max_threshold: Ceiling (default 0.60)
        target_hit_rate: Desired hit rate (default 0.50)
        lookback_days: How many days to consider (default 30)
        reports_dir: Reports directory for tracking history

    Returns:
        Dict with ``threshold``, ``hit_rate``, ``adjustment``, ``sample_size``
    """
    search_dir = reports_dir or resolve_report_dir()

    # Try to load tracking history
    hit_rate, sample_size = _load_recent_hit_rate(search_dir, lookback_days)

    if sample_size < 5:
        # Not enough data: use base threshold
        return {
            "threshold": base_threshold,
            "hit_rate": None,
            "adjustment": 0.0,
            "sample_size": sample_size,
            "base_threshold": base_threshold,
            "note": "insufficient tracking data, using base threshold",
        }

    # Compute adjustment based on performance gap
    performance_gap = target_hit_rate - hit_rate  # positive = underperforming
    # Scale: each 10% gap = 0.05 threshold adjustment
    adjustment = performance_gap * 0.5

    # Apply adjustment
    new_threshold = base_threshold + adjustment
    new_threshold = max(min_threshold, min(max_threshold, new_threshold))

    return {
        "threshold": round(new_threshold, 4),
        "hit_rate": round(hit_rate, 4),
        "adjustment": round(adjustment, 4),
        "sample_size": sample_size,
        "base_threshold": base_threshold,
        "min_threshold": min_threshold,
        "max_threshold": max_threshold,
        "target_hit_rate": target_hit_rate,
    }


def render_dynamic_threshold(result: dict[str, Any]) -> str:
    """Render dynamic threshold result as readable text."""
    threshold = result["threshold"]
    base = result.get("base_threshold", _DEFAULT_BASE_THRESHOLD)
    hit_rate = result.get("hit_rate")
    sample_size = result.get("sample_size", 0)

    lines = [f"\n{Fore.CYAN}🎯 Dynamic Recommendation Threshold{Style.RESET_ALL}", ""]

    if hit_rate is None:
        lines.append(f"  Threshold: {threshold:.2f} (base, no adjustment)")
        lines.append(f"  Note: {result.get('note', 'insufficient data')}")
    else:
        adjustment = result.get("adjustment", 0.0)
        if adjustment > 0:
            adj_str = f"{Fore.YELLOW}↑ +{adjustment:.4f} (stricter){Style.RESET_ALL}"
        elif adjustment < 0:
            adj_str = f"{Fore.GREEN}↓ {adjustment:.4f} (relaxed){Style.RESET_ALL}"
        else:
            adj_str = "→ no change"

        lines.append(f"  Base threshold: {base:.2f}")
        lines.append(f"  Dynamic threshold: {threshold:.4f}  {adj_str}")
        lines.append(f"  Recent hit rate: {hit_rate:.1%} (target: {result.get('target_hit_rate', 0.5):.0%})")
        lines.append(f"  Sample size: {sample_size} recommendations")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_recent_hit_rate(
    reports_dir: Path,
    lookback_days: int,
) -> tuple[float | None, int]:
    """Load hit rate from tracking history.

    Returns (hit_rate, sample_size) or (None, 0) if no data.
    """
    history_path = reports_dir / "tracking_history.json"
    if not history_path.exists():
        return None, 0

    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, 0

    records = history.get("records") if history.get("records") else (history if isinstance(history, list) else [])
    if not records:
        return None, 0

    # R160: actually apply lookback_days — filter records to those whose
    # ``recommended_date`` falls within [anchor - lookback_days, anchor], where
    # the anchor is the latest parseable ``recommended_date`` (data-anchored,
    # per R62/BH-026). Before this fix ``lookback_days`` was accepted but never
    # used, so "recent hit rate" was silently the *all-time* hit rate — the
    # self-correcting threshold (docstring: "Load recent tracking history (last
    # N days)") could not tighten after a recent losing streak. When no records
    # carry a parseable date, fall back to including all (backward compat for
    # legacy / dateless tracking history that cannot be positioned in time).
    if lookback_days > 0:
        anchor = _latest_recommended_date(records)
        if anchor is not None:
            cutoff = anchor - timedelta(days=lookback_days)
            records = [rec for rec in records if _parse_date(str(rec.get("recommended_date", "") or "")) is not None and _parse_date(str(rec.get("recommended_date", "") or "")) >= cutoff]

    # Filter to recent records with known outcomes
    recent_with_outcome = 0
    hits = 0

    for rec in records:
        tracking_status = str(rec.get("tracking_status") or "")
        if tracking_status != "complete":
            continue

        # NS-18(3): Read the real tracking_history schema field
        # ``next_5day_return`` (written by ``recommendation_tracker``) rather
        # than the stale ``t_plus_5_return`` field name that never exists in
        # production data. Single T+5 horizon — no T+3/T+1 fallback, which
        # would inflate hit_rate with shorter-horizon noise (T+1/T+3 are
        # noisier and more likely positive by chance), lowering the bar for
        # ``--decision-flow`` BUY gate. Before this fix the feature was
        # silently dead: hit_rate was always None (field name mismatch) so
        # dynamic_threshold always returned base_threshold.
        ret = rec.get("next_5day_return")
        if ret is not None:
            try:
                if float(ret) > 0:
                    hits += 1
                recent_with_outcome += 1
            except (ValueError, TypeError):
                pass

    if recent_with_outcome < 5:
        return None, recent_with_outcome

    return hits / recent_with_outcome, recent_with_outcome


def run_dynamic_threshold(argv: list[str] | None = None) -> int:
    """CLI entry point for --dynamic-threshold."""

    lookback = _DEFAULT_LOOKBACK
    target = _DEFAULT_TARGET_HIT_RATE
    if argv:
        for arg in argv:
            if arg.startswith("--lookback="):
                try:
                    lookback = int(arg.split("=")[1])
                except ValueError:
                    pass
            elif arg.startswith("--target-hit-rate="):
                try:
                    target = float(arg.split("=")[1])
                except ValueError:
                    pass

    reports_dir = resolve_report_dir()
    result = compute_dynamic_threshold(
        lookback_days=lookback,
        target_hit_rate=target,
        reports_dir=reports_dir,
    )
    print(render_dynamic_threshold(result))
    return 0
