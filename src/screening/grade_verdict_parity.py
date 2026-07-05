"""Grade↔Verdict parity auditor — E4 display-semantics coverage (loop 89).

Diagnoses the ``C-GREEN-GRADE-AVOID-MISMATCH`` disease class flagged in loop
85: ``_composite_grade`` (composite_score.py) paints GREEN for composite>=0.5
regardless of the verdict, so an AVOID/HOLD pick can render a green grade
next to ``操作=AVOID`` — a visual-semantic conflict that misleads the
operator into reading a "do not buy" pick as "good confidence".

This module is **pure-diagnostic** (loop 89 engineering-owned slice). It:

- Does NOT touch ``_composite_grade``, ``build_front_door_verdict``, or any
  render function. Default front-door display semantics are byte-for-byte
  preserved (changing them is an owner decision pack — display-semantics
  boundary, see ``autodev-contract.md`` §需要 owner 最终决策).
- Quantifies the mismatch on real reports and classifies the trigger path,
  turning a single loop-85 flag into frequency evidence for the owner
  decision pack.
- Extends the E4 evaluator map to a new disease class (grade↔verdict parity),
  reusable as a regression guard for any future grade/verdict change.

Verified trigger paths (loop-89 dogfood on report 20260703_top5: AVOID picks
688017/300502/688766 all rendered green B at composite 0.679/0.661/0.663):

- ``short_term_signal_missing`` — composite>=0.5 (green B+) but neither T+5
  nor T+10 clears the BUY gate, and the watchable bar fails too → AVOID.
- ``market_gate_downgrade`` — composite>=0.5 AND short-term passes, but
  regime is crisis/risk_off → verdict downgrades while grade stays green.
- ``bearish_decision`` — composite>=0.5 but decision=bearish → AVOID.
- ``insufficient_sample`` — composite>=0.5 AND short-term passes but
  backing_sample<20 → HOLD/AVOID; grade stays green.

Usage (decision-pack evidence)::

    from src.screening.grade_verdict_parity import audit_grade_verdict_parity

    report = audit_grade_verdict_parity(picks, market_regime="normal")
    print(render_parity_audit(report))
    # write report.to_dict() to JSON for owner review
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from src.screening.investability import build_front_door_verdict
from src.utils.display import Fore, Style

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thresholds — must mirror ``_composite_grade`` (composite_score.py:343).
# Green = A (>=0.7) or B (>=0.5). Kept here as a named constant so any future
# change to ``_composite_grade`` is visible at one audit site.
# ---------------------------------------------------------------------------

GREEN_GRADE_THRESHOLD: float = 0.5
"""composite_score at/above which ``_composite_grade`` paints GREEN (B or A)."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GradeVerdictMismatch:
    """A single grade↔verdict mismatch occurrence on one pick."""

    ticker: str
    name: str
    composite_score: float
    grade_color: str  # "green" | "yellow" | "red"
    verdict: str  # "BUY" | "HOLD" | "AVOID"
    trigger_path: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "composite_score": self.composite_score,
            "grade_color": self.grade_color,
            "verdict": self.verdict,
            "trigger_path": self.trigger_path,
            "reason": self.reason,
        }


@dataclass
class GradeVerdictParityReport:
    """Aggregate grade↔verdict parity audit over a pick list."""

    total_picks: int = 0
    mismatch_count: int = 0
    mismatches: list[GradeVerdictMismatch] = field(default_factory=list)
    trigger_counts: dict[str, int] = field(default_factory=dict)
    market_regime: str = ""

    @property
    def mismatch_ratio(self) -> float:
        """Fraction of picks that are grade↔verdict mismatches (0..1)."""
        if self.total_picks == 0:
            return 0.0
        return self.mismatch_count / self.total_picks

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_picks": self.total_picks,
            "mismatch_count": self.mismatch_count,
            "mismatch_ratio": self.mismatch_ratio,
            "market_regime": self.market_regime,
            "trigger_counts": dict(self.trigger_counts),
            "mismatches": [m.to_dict() for m in self.mismatches],
        }


# ---------------------------------------------------------------------------
# Core auditor
# ---------------------------------------------------------------------------


def _grade_color_for_score(composite_score: float) -> str:
    """Return the color class ``_composite_grade`` would paint.

    Mirrors the green/yellow/red bands in ``composite_score.py:343`` without
    importing the renderer (which returns a colorama-wrapped string). Kept in
    sync via ``GREEN_GRADE_THRESHOLD`` and the unit tests above.
    """
    if composite_score >= 0.3:
        # 0.3..0.5 → yellow C/D; >=0.5 → green B/A. Both are "not red".
        if composite_score >= GREEN_GRADE_THRESHOLD:
            return "green"
        return "yellow"
    return "red"


def _classify_trigger_path(
    pick: dict[str, Any],
    verdict: str,
    market_regime: str,
) -> str | None:
    """Classify WHY a green-graded pick got a non-BUY verdict.

    Returns the trigger-path label, or ``None`` when verdict is BUY (no
    mismatch to classify). Mirrors the verdict logic in
    ``build_front_door_verdict`` (investability.py) but reads the SAME input
    fields, so any divergence is itself a signal.
    """
    if verdict == "BUY":
        return None

    regime_lower = str(market_regime or "").lower()
    is_market_gate_active = "crisis" in regime_lower or "risk_off" in regime_lower

    decision = str(pick.get("decision") or "").lower()
    if decision == "bearish":
        return "bearish_decision"

    expected_returns = pick.get("expected_returns") or {}
    win_rates = pick.get("win_rates") or {}

    def _num(v: Any) -> float:
        try:
            f = float(v)
            return f if f == f else 0.0  # NaN guard
        except (TypeError, ValueError):
            return 0.0

    t5_edge = _num(expected_returns.get("t5"))
    t5_win = _num(win_rates.get("t5"))
    t10_edge = _num(expected_returns.get("t10"))
    t10_win = _num(win_rates.get("t10"))

    t5_passes = t5_edge > 0 and t5_win >= 0.55
    t10_passes = t10_edge > 0 and t10_win >= 0.55
    short_term_passes = (
        t10_passes if is_market_gate_active else (t5_passes or t10_passes)
    )

    # Watchable bar (investability.py:283-285): winrate>=0.5, edge>=0.
    t5_watchable = t5_edge >= 0 and t5_win >= 0.5
    t10_watchable = t10_edge >= 0 and t10_win >= 0.5
    watchable = t5_watchable or t10_watchable

    if is_market_gate_active and short_term_passes:
        # Verdict would have been BUY absent the gate; downgrade is the cause.
        return "market_gate_downgrade"

    if short_term_passes:
        # Short-term signal passes but verdict is still non-BUY — sample
        # maturity is the most likely remaining gate (backing_sample<20).
        return "insufficient_sample"

    if not watchable:
        return "short_term_signal_missing"

    # Watchable but not BUY and not market-gated → HOLD on the watchable bar.
    # Still a green-grade-vs-non-actionable conflict; bucket as
    # short_term_signal_missing (the BUY bar was not met).
    return "short_term_signal_missing"


def audit_grade_verdict_parity(
    picks: list[dict[str, Any]],
    *,
    market_regime: str,
) -> GradeVerdictParityReport:
    """Audit grade↔verdict parity across a pick list.

    For each pick, computes the grade color (mirroring ``_composite_grade``)
    and the front-door verdict (via ``build_front_door_verdict``), and flags
    any pick where a GREEN grade coexists with a non-BUY verdict.

    Pure-diagnostic: no side effects, no mutation of inputs. Safe to call on
    any pick list at any layer (test, CLI, decision-pack script).
    """
    report = GradeVerdictParityReport(
        total_picks=len(picks),
        market_regime=market_regime,
    )
    trigger_counter: Counter[str] = Counter()

    for pick in picks:
        composite_score_raw = pick.get("composite_score_gated")
        if composite_score_raw is None:
            composite_score_raw = pick.get("composite_score")
        try:
            composite_score = float(composite_score_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            composite_score = 0.0
        if composite_score != composite_score:  # NaN
            composite_score = 0.0

        grade_color = _grade_color_for_score(composite_score)
        if grade_color != "green":
            continue  # only green grades can mismatch with non-BUY

        verdict_dict = build_front_door_verdict(pick, market_regime=market_regime)
        verdict = verdict_dict.get("action", "AVOID")
        if verdict == "BUY":
            continue  # aligned

        trigger_path = _classify_trigger_path(pick, verdict, market_regime)
        if trigger_path is None:
            continue

        ticker = str(pick.get("ticker", "") or "")
        name = str(pick.get("name", "") or "")
        reason = (
            f"composite={composite_score:+.3f} paints GREEN {grade_color} "
            f"but verdict={verdict} ({trigger_path})"
        )
        report.mismatches.append(
            GradeVerdictMismatch(
                ticker=ticker,
                name=name,
                composite_score=composite_score,
                grade_color=grade_color,
                verdict=verdict,
                trigger_path=trigger_path,
                reason=reason,
            )
        )
        trigger_counter[trigger_path] += 1

    report.mismatch_count = len(report.mismatches)
    report.trigger_counts = dict(trigger_counter)
    return report


# ---------------------------------------------------------------------------
# Render — operator-readable summary for the decision pack
# ---------------------------------------------------------------------------

_TRIGGER_PATH_LABEL: dict[str, str] = {
    "short_term_signal_missing": "短期信号缺失 (composite 高但 T+5/T+10 不达 BUY gate)",
    "market_gate_downgrade": "市场门控降级 (crisis/risk_off 把 BUY 压成 HOLD/AVOID)",
    "bearish_decision": "decision=bearish (composite 高但趋势向下)",
    "insufficient_sample": "样本不足 (short-term 通过但成熟样本 <20)",
}


def render_parity_audit(report: GradeVerdictParityReport) -> str:
    """Render the parity audit as an operator-readable summary.

    Intended for decision-pack evidence (file artifact or stderr print), NOT
    for the default front door. The default ``--top-picks`` display is
    unchanged; this render is invoked explicitly by the decision-pack script
    or a future ``--audit-grade-verdict`` diagnostic flag (owner-gated).
    """
    if report.total_picks == 0:
        return (
            f"{Fore.CYAN}🔍 Grade↔Verdict Parity Audit{Style.RESET_ALL}\n"
            f"  无推荐数据\n"
        )

    ratio_pct = report.mismatch_ratio * 100.0
    head_color = (
        Fore.RED if report.mismatch_count > 0 else Fore.GREEN
    )
    lines = [
        f"{Fore.CYAN}🔍 Grade↔Verdict Parity Audit "
        f"(等级↔操作语义一致性审计){Style.RESET_ALL}",
        f"  市场 regime={report.market_regime}  |  "
        f"总 picks={report.total_picks}  |  "
        f"{head_color}mismatch={report.mismatch_count} "
        f"({ratio_pct:.0f}%){Style.RESET_ALL}",
    ]

    if report.mismatch_count == 0:
        lines.append(f"  {Fore.GREEN}✓ 所有 green-grade picks 与 verdict 一致{Style.RESET_ALL}")
        return "\n".join(lines) + "\n"

    lines.append(f"  {Fore.RED}⚠ green 等级 (composite≥0.5) 与 非BUY 操作冲突 — "
                 f"操作者可能误读 AVOID/HOLD 票为「信心良好」{Style.RESET_ALL}")
    lines.append("  触发路径分布:")
    for path, count in sorted(
        report.trigger_counts.items(), key=lambda kv: -kv[1]
    ):
        label = _TRIGGER_PATH_LABEL.get(path, path)
        lines.append(f"    {Fore.YELLOW}• {path}{Style.RESET_ALL} "
                     f"({label}): {count}")

    lines.append("  冲突 picks (前 10):")
    for m in report.mismatches[:10]:
        lines.append(
            f"    {m.ticker:<8} {m.name[:10]:<10} "
            f"composite={m.composite_score:+.3f} "
            f"{Fore.GREEN}{m.grade_color}{Style.RESET_ALL} "
            f"→ verdict={Fore.RED}{m.verdict}{Style.RESET_ALL} "
            f"[{m.trigger_path}]"
        )
    if len(report.mismatches) > 10:
        lines.append(f"    ... +{len(report.mismatches) - 10} more")

    return "\n".join(lines) + "\n"
