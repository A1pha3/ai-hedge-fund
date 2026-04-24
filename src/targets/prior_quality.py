"""P3 prior quality hard gate: classifier and selection-target enforcement.

Rules (BTST 0422 P3 specification):
  - next_high_hit_rate_at_threshold == 0 → reject
  - evaluable_count < 3  → near_miss blocked (and selected blocked)
  - evaluable_count < 5  → selected blocked (watch_only at minimum)
  - next_close_positive_rate < 0.50 → watch_only (selected blocked)

Classification priority: reject > watch_only/selected_blocked > execution_ready

Only active when BTST_0422_P3_PRIOR_QUALITY_MODE=enforce.
Default (off) is a no-op: all existing behaviour preserved.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from src.targets.models import DualTargetEvaluation


class PriorQualityLabel(str, Enum):
    EXECUTION_READY = "execution_ready"
    WATCH_ONLY = "watch_only"
    REJECT = "reject"


# Thresholds (hard-coded per spec; exposed here for test introspection)
P3_MIN_N_SELECTED: int = 5     # n < 5 → selected blocked
P3_MIN_N_NEAR_MISS: int = 3    # n < 3 → near_miss blocked
P3_CLOSE_POSITIVE_MIN: float = 0.50  # close+ < 50% → watch_only
P3_HIGH_HIT_REJECT_THRESHOLD: float = 0.0  # high_hit_rate <= this → reject


class PriorQualityResult:
    """Result of prior quality classification."""

    __slots__ = ("label", "reason", "selected_blocked", "near_miss_blocked")

    def __init__(
        self,
        label: PriorQualityLabel,
        reason: str,
        selected_blocked: bool,
        near_miss_blocked: bool,
    ) -> None:
        self.label = label
        self.reason = reason
        self.selected_blocked = selected_blocked
        self.near_miss_blocked = near_miss_blocked

    def __repr__(self) -> str:  # pragma: no cover
        return f"PriorQualityResult(label={self.label!r}, reason={self.reason!r}, selected_blocked={self.selected_blocked}, near_miss_blocked={self.near_miss_blocked})"


def classify_prior_quality(
    *,
    evaluable_count: int,
    next_high_hit_rate_at_threshold: float,
    next_close_positive_rate: float,
    high_hit_reject_threshold: float = P3_HIGH_HIT_REJECT_THRESHOLD,
    min_n_selected: int = P3_MIN_N_SELECTED,
    min_n_near_miss: int = P3_MIN_N_NEAR_MISS,
    close_positive_min: float = P3_CLOSE_POSITIVE_MIN,
) -> PriorQualityResult:
    """Classify a historical prior as execution_ready, watch_only, or reject.

    Returns a PriorQualityResult with:
      - label: the quality classification
      - reason: machine-readable reason code(s), empty string if execution_ready
      - selected_blocked: True when this prior must not enter selected
      - near_miss_blocked: True when this prior must not enter near_miss

    All four threshold parameters default to the module-level constants (matching the spec);
    callers (e.g. apply_p3_prior_quality_gate_to_selection_targets) may pass profile-level
    overrides to honour active profile configuration.
    """
    reasons: list[str] = []

    # Rule 1: zero high-hit-rate → reject immediately (hardest gate)
    if next_high_hit_rate_at_threshold <= high_hit_reject_threshold:
        reasons.append("high_hit_rate_zero")
        return PriorQualityResult(
            label=PriorQualityLabel.REJECT,
            reason=",".join(reasons),
            selected_blocked=True,
            near_miss_blocked=True,
        )

    # Rule 2: tiny sample — n < min_n_near_miss blocks everything
    if evaluable_count < min_n_near_miss:
        reasons.append(f"sample_too_small_n{evaluable_count}_lt_{min_n_near_miss}")
        return PriorQualityResult(
            label=PriorQualityLabel.WATCH_ONLY,
            reason=",".join(reasons),
            selected_blocked=True,
            near_miss_blocked=True,
        )

    # Rule 3: small sample — n < min_n_selected blocks selected but not near_miss
    selected_blocked = evaluable_count < min_n_selected
    if selected_blocked:
        reasons.append(f"sample_small_n{evaluable_count}_lt_{min_n_selected}")

    # Rule 4: low close-positive-rate → watch_only (also blocks selected)
    low_close_pos = next_close_positive_rate < close_positive_min
    if low_close_pos:
        reasons.append("low_close_positive_rate")
        selected_blocked = True

    if selected_blocked or low_close_pos:
        return PriorQualityResult(
            label=PriorQualityLabel.WATCH_ONLY,
            reason=",".join(reasons),
            selected_blocked=True,
            near_miss_blocked=False,
        )

    return PriorQualityResult(
        label=PriorQualityLabel.EXECUTION_READY,
        reason="",
        selected_blocked=False,
        near_miss_blocked=False,
    )


def apply_p3_prior_quality_gate_to_selection_targets(
    selection_targets: dict[str, DualTargetEvaluation],
    mode: str,
    prior_by_ticker: dict[str, dict[str, Any]],
) -> None:
    """Apply P3 prior quality hard gate to selection_targets in-place.

    Only active when mode == 'enforce'. When mode == 'off' this is a no-op.

    For each evaluation:
      - Looks up the ticker's historical prior from prior_by_ticker.
      - Classifies prior quality.
      - If the prior quality blocks the current decision, sets p3_execution_blocked=True.
      - Always records p3_prior_quality_label and p3_sample_size for observability.
    """
    if mode != "enforce":
        return

    from src.targets.profiles import get_active_short_trade_target_profile
    profile = get_active_short_trade_target_profile()
    high_hit_reject_threshold = profile.p3_prior_quality_high_hit_reject_threshold
    min_n_selected = profile.p3_prior_quality_min_n_selected
    min_n_near_miss = profile.p3_prior_quality_min_n_near_miss
    close_positive_min = profile.p3_prior_quality_close_positive_min

    for ticker, evaluation in selection_targets.items():
        prior = prior_by_ticker.get(ticker) or {}
        if not prior:
            continue

        evaluable_count = int(prior.get("evaluable_count") or 0)
        next_high_hit = float(prior.get("next_high_hit_rate_at_threshold") or 0.0)
        next_close_pos = float(prior.get("next_close_positive_rate") or 0.0)

        qr = classify_prior_quality(
            evaluable_count=evaluable_count,
            next_high_hit_rate_at_threshold=next_high_hit,
            next_close_positive_rate=next_close_pos,
            high_hit_reject_threshold=high_hit_reject_threshold,
            min_n_selected=min_n_selected,
            min_n_near_miss=min_n_near_miss,
            close_positive_min=close_positive_min,
        )

        # Always set observability fields
        evaluation.p3_prior_quality_label = qr.label.value
        evaluation.p3_sample_size = evaluable_count

        # Check current decision against gate rules
        short_trade = evaluation.short_trade
        if short_trade is None:
            continue

        decision = str(short_trade.decision or "")
        blocked = False
        block_reason: str | None = None

        if decision == "selected" and qr.selected_blocked:
            blocked = True
            block_reason = f"p3_prior_quality:{qr.label.value}:{qr.reason}"
        elif decision == "near_miss" and qr.near_miss_blocked:
            blocked = True
            block_reason = f"p3_prior_quality:{qr.label.value}:{qr.reason}"

        if blocked:
            evaluation.p3_execution_blocked = True
            evaluation.p3_execution_block_reason = block_reason
