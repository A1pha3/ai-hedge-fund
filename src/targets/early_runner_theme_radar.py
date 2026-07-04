from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _safe_float(value: Any) -> float | None:
    """Return a float when parsing succeeds, otherwise ``None``."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    """Convert mixed inputs into float while preserving a caller-provided default."""
    parsed = _safe_float(value)
    return default if parsed is None else float(parsed)


def _clamp_unit_interval(value: float) -> float:
    """Clamp a numeric score into the inclusive ``[0.0, 1.0]`` range."""
    return max(0.0, min(1.0, float(value)))


def compute_catalyst_theme_score(candidate_source: str) -> float:
    """Map candidate-source provenance into the current theme-proxy score."""
    normalized = str(candidate_source or "")
    if normalized == "catalyst_theme":
        return 1.0
    if normalized == "catalyst_theme_shadow":
        return 0.88
    if normalized == "upstream_liquidity_corridor_shadow":
        return 0.78
    return 0.42


def compute_historical_prior_score(historical_prior: dict[str, Any]) -> float:
    """Shrink sparse historical priors before turning them into a bounded score."""
    if not historical_prior:
        return 0.0
    hit_rate = _as_float(historical_prior.get("next_high_hit_rate_at_threshold"), 0.0)
    positive_rate = _as_float(historical_prior.get("next_close_positive_rate"), 0.0)
    sample_count = _as_float(historical_prior.get("sample_count"), 0.0)
    shrinkage = _clamp_unit_interval(sample_count / 12.0)
    return round(_clamp_unit_interval(((hit_rate * 0.55) + (positive_rate * 0.45)) * (0.40 + (0.60 * shrinkage))), 4)


def compute_retention_proxy(preferred_entry_mode: str) -> float:
    """Translate current entry-mode guidance into the legacy retention proxy."""
    normalized = str(preferred_entry_mode or "")
    if "hold" in normalized:
        return 0.85
    if "review" in normalized or "reconfirm" in normalized:
        return 0.55
    if "avoid_open_chase" in normalized:
        return 0.45
    return 0.50


def compute_breakout_proximity(row: dict[str, Any]) -> float:
    """Estimate how cleanly a setup sits near a breakout without crowding the limit."""
    breakout_freshness = _as_float(row.get("breakout_freshness"), 0.0)
    gap_to_limit = _as_float(row.get("gap_to_limit"), 0.05)
    supply_pressure_60 = _as_float(row.get("supply_pressure_60"), 0.10)
    gap_room = _clamp_unit_interval((gap_to_limit - 0.01) / 0.09)
    supply_relief = 1.0 - _clamp_unit_interval(supply_pressure_60 / 0.25)
    return round(_clamp_unit_interval((0.45 * breakout_freshness) + (0.30 * gap_room) + (0.25 * supply_relief)), 4)


def compute_close_structure(row: dict[str, Any]) -> float:
    """Project the current close-structure proxy from close-strength."""
    return round(_clamp_unit_interval(_as_float(row.get("close_strength"), 0.0)), 4)


def compute_overheat_penalty(row: dict[str, Any]) -> float:
    """Apply the current research penalties for overextended setups."""
    penalty = 0.0
    ret_5d = _as_float(row.get("ret_5d"), 0.0)
    ret_10d = _as_float(row.get("ret_10d"), 0.0)
    close_strength = _as_float(row.get("close_strength"), 0.0)
    volume_ratio = _as_float(row.get("vol_ratio"), 0.0)
    upper_shadow = _as_float(row.get("upper_shadow"), 0.0)
    if ret_5d > 0.18:
        penalty += 0.10
    if ret_5d > 0.25:
        penalty += 0.18
    if ret_10d > 0.50:
        penalty += 0.25
    if close_strength >= 0.95:
        penalty += 0.10
    if volume_ratio > 4.0 and upper_shadow >= 0.04:
        penalty += 0.10
    return round(penalty, 4)


def compute_regime_penalty(row: dict[str, Any]) -> float:
    """Apply the current market-regime penalty schedule used by early runner."""
    gate = str(row.get("btst_regime_gate") or "normal_trade")
    penalty = 0.0
    if gate == "shadow_only":
        penalty += 0.10
    elif gate == "halt":
        penalty += 0.25
    if _as_float(row.get("supply_pressure_60"), 0.0) > 0.18:
        penalty += 0.08
    return round(penalty, 4)


def compute_pre_score(row: dict[str, Any]) -> float:
    """Compute the current pre-score contract without introducing new feature fields."""
    score = (
        (0.22 * _as_float(row.get("trend_acceleration"), 0.0))
        + (0.16 * _as_float(row.get("breakout_proximity"), 0.0))
        + (0.14 * _as_float(row.get("volume_expansion_quality"), 0.0))
        + (0.14 * _as_float(row.get("close_structure"), 0.0))
        + (0.12 * _as_float(row.get("sector_resonance"), 0.0))
        + (0.10 * _as_float(row.get("catalyst_theme_score"), 0.0))
        + (0.08 * _as_float(row.get("retention_proxy"), 0.0))
        + (0.04 * _as_float(row.get("historical_prior_score"), 0.0))
        - _as_float(row.get("overheat_penalty"), 0.0)
        - _as_float(row.get("regime_penalty"), 0.0)
    )
    return round(_clamp_unit_interval(score), 4)


def _normalize_theme_label(value: Any) -> str:
    """Normalize a theme-like label while preserving empty as ``unknown``."""
    normalized = str(value or "").strip()
    return normalized or "unknown"


def _candidate_theme_label(entry: dict[str, Any]) -> str:
    """Resolve the most informative theme label from a catalyst entry."""
    candidate = dict(entry or {})
    return _normalize_theme_label(candidate.get("theme_name") or candidate.get("theme_category") or candidate.get("industry"))


def _backfill_candidate_theme_labels(entries: list[dict[str, Any]], *, rows_by_ticker: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Backfill empty catalyst-theme labels from row-level industry/theme context."""
    enriched_entries: list[dict[str, Any]] = []
    for entry in [dict(item or {}) for item in list(entries or [])]:
        if _candidate_theme_label(entry) != "unknown":
            enriched_entries.append(entry)
            continue
        ticker = str(entry.get("ticker") or "").strip()
        row = dict(rows_by_ticker.get(ticker) or {})
        if row:
            if not str(entry.get("theme_name") or "").strip():
                entry["theme_name"] = str(row.get("theme_name") or row.get("theme_category") or row.get("industry") or "")
            if not str(entry.get("theme_category") or "").strip():
                entry["theme_category"] = str(row.get("theme_category") or row.get("industry") or "")
            if not str(entry.get("industry") or "").strip():
                entry["industry"] = str(row.get("industry") or "")
        enriched_entries.append(entry)
    return enriched_entries


def build_theme_radar_summary(
    *,
    trade_date: str,
    catalyst_theme_candidates: list[dict[str, Any]],
    catalyst_theme_shadow_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate catalyst-theme candidates into a theme-first radar summary."""
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trade_date": trade_date,
            "theme_label": "unknown",
            "leader_tickers": [],
            "midfield_tickers": [],
            "candidate_sources": Counter(),
            "theme_category": "",
            "is_new_theme": False,
        }
    )
    for entry in [dict(item or {}) for item in list(catalyst_theme_candidates or [])]:
        theme_label = _candidate_theme_label(entry)
        group = grouped[theme_label]
        group["theme_label"] = theme_label
        ticker = str(entry.get("ticker") or "").strip()
        if ticker and ticker not in group["leader_tickers"]:
            group["leader_tickers"].append(ticker)
        group["theme_category"] = str(entry.get("theme_category") or group.get("theme_category") or "")
        group["is_new_theme"] = bool(entry.get("is_new_theme") or group.get("is_new_theme"))
        group["candidate_sources"].update([str(entry.get("candidate_source") or "catalyst_theme")])
    for entry in [dict(item or {}) for item in list(catalyst_theme_shadow_candidates or [])]:
        theme_label = _candidate_theme_label(entry)
        group = grouped[theme_label]
        group["theme_label"] = theme_label
        ticker = str(entry.get("ticker") or "").strip()
        if ticker and ticker not in group["midfield_tickers"] and ticker not in group["leader_tickers"]:
            group["midfield_tickers"].append(ticker)
        group["theme_category"] = str(entry.get("theme_category") or group.get("theme_category") or "")
        group["is_new_theme"] = bool(entry.get("is_new_theme") or group.get("is_new_theme"))
        group["candidate_sources"].update([str(entry.get("candidate_source") or "catalyst_theme_shadow")])

    theme_boards: list[dict[str, Any]] = []
    for group in grouped.values():
        leader_count = len(group["leader_tickers"])
        midfield_count = len(group["midfield_tickers"])
        breadth_score = round(_clamp_unit_interval(((leader_count * 0.65) + (midfield_count * 0.35)) / 3.0), 4)
        is_hot_theme_board = leader_count >= 2 or (leader_count >= 1 and midfield_count >= 2 and breadth_score >= 0.55)
        theme_boards.append(
            {
                "trade_date": trade_date,
                "theme_label": group["theme_label"],
                "theme_category": group["theme_category"],
                "is_new_theme": bool(group["is_new_theme"]),
                "theme_leader_count": leader_count,
                "theme_midfield_count": midfield_count,
                "theme_leader_tickers": list(group["leader_tickers"]),
                "theme_midfield_candidates": list(group["midfield_tickers"]),
                "theme_breadth_score": breadth_score,
                "is_hot_theme_board": is_hot_theme_board,
                "candidate_source_counts": dict(group["candidate_sources"]),
            }
        )
    theme_boards.sort(
        key=lambda row: (
            bool(row.get("is_hot_theme_board")),
            float(row.get("theme_breadth_score") or 0.0),
            int(row.get("theme_leader_count") or 0),
            str(row.get("theme_label") or ""),
        ),
        reverse=True,
    )
    hot_theme_boards = [dict(row) for row in theme_boards if bool(row.get("is_hot_theme_board"))]
    return {
        "trade_date": trade_date,
        "theme_board_count": len(theme_boards),
        "hot_theme_board_count": len(hot_theme_boards),
        "top_active_themes": [str(row.get("theme_label") or "") for row in theme_boards[:5] if str(row.get("theme_label") or "").strip()],
        "hot_theme_board": [str(row.get("theme_label") or "") for row in hot_theme_boards],
        "theme_boards": theme_boards,
    }


def build_industry_radar_summary(rows: list[dict[str, Any]], *, trade_date: str) -> dict[str, Any]:
    """Aggregate row-level industries into a lightweight industry breadth radar."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in [dict(item or {}) for item in list(rows or [])]:
        grouped[_normalize_theme_label(row.get("industry"))].append(row)
    industries: list[dict[str, Any]] = []
    for industry, members in grouped.items():
        leader_count = sum(1 for row in members if str(row.get("bucket") or "") == "early_runner_first_entry")
        breadth_score = round(_clamp_unit_interval(((leader_count * 0.70) + (len(members) * 0.30)) / 4.0), 4)
        industries.append(
            {
                "trade_date": trade_date,
                "industry": industry,
                "member_count": len(members),
                "leader_count": leader_count,
                "breadth_score": breadth_score,
                "tickers": [str(row.get("ticker") or "") for row in members if str(row.get("ticker") or "").strip()],
            }
        )
    industries.sort(key=lambda row: (float(row.get("breadth_score") or 0.0), int(row.get("leader_count") or 0), int(row.get("member_count") or 0), str(row.get("industry") or "")), reverse=True)
    return {
        "trade_date": trade_date,
        "industry_board_count": len(industries),
        "top_industries": [str(row.get("industry") or "") for row in industries[:5] if str(row.get("industry") or "").strip()],
        "industry_boards": industries,
    }


def build_theme_radar_context_by_ticker(
    *,
    trade_date: str,
    rows: list[dict[str, Any]],
    catalyst_theme_candidates: list[dict[str, Any]],
    catalyst_theme_shadow_candidates: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Build per-ticker radar context plus theme/industry summaries for a trade date."""
    rows_by_ticker = {str(dict(row or {}).get("ticker") or "").strip(): dict(row or {}) for row in list(rows or []) if str(dict(row or {}).get("ticker") or "").strip()}
    theme_summary = build_theme_radar_summary(
        trade_date=trade_date,
        catalyst_theme_candidates=_backfill_candidate_theme_labels(catalyst_theme_candidates, rows_by_ticker=rows_by_ticker),
        catalyst_theme_shadow_candidates=_backfill_candidate_theme_labels(catalyst_theme_shadow_candidates, rows_by_ticker=rows_by_ticker),
    )
    industry_summary = build_industry_radar_summary(rows, trade_date=trade_date)
    by_theme = {str(row.get("theme_label") or ""): dict(row) for row in list(theme_summary.get("theme_boards") or [])}
    radar_context: dict[str, dict[str, Any]] = {}
    for row in [dict(item or {}) for item in list(rows or [])]:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        theme_label = _normalize_theme_label(row.get("theme_name") or row.get("theme_category") or row.get("industry"))
        theme_payload = dict(by_theme.get(theme_label) or {})
        radar_context[ticker] = {
            "theme_label": theme_label,
            "hot_theme_board": theme_label if bool(theme_payload.get("is_hot_theme_board")) else "",
            "theme_breadth_score": float(theme_payload.get("theme_breadth_score") or 0.0),
            "theme_leader_count": int(theme_payload.get("theme_leader_count") or 0),
            "theme_midfield_candidates": list(theme_payload.get("theme_midfield_candidates") or []),
        }
    return radar_context, theme_summary, industry_summary
