# isort: skip_file
"""BTST profile experiment — walk-forward comparison harness.

P2 phase 1 (2026-06-05): scaffolding for real profile routing experiments.

**Goal:** Given a profile routing contract and a set of historical outcome
ledgers, evaluate conservative vs aggressive against closed outcomes.

This script does NOT modify upstream candidate selection. It produces a
report that downstream integration can consume once P2 phase 2 wires up
the routing.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.paper_trading.btst_outcome_ledger import (
    OutcomeVerdict,
    read_outcome_ledger,
)
from src.paper_trading.btst_profile_routing import (
    DEFAULT_PROFILE_ROUTING_CONTRACT,
    ProfileRoutingContract,
)

# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_outcomes_by_profile(
    ledger_paths: list[Path],
) -> dict[str, dict[str, Any]]:
    """Aggregate outcome ledger data grouped by profile.

    Returns:
        {
            "conservative": {"sample_count": ..., "win_rate": ..., ...},
            "aggressive": {"sample_count": ..., "win_rate": ..., ...},
            "_skipped_ledgers": [{"path": ..., "error": ...}, ...],  # NS-17/c288
        }

    NS-17/c288: previously ``except Exception: continue`` silently dropped
    corrupt/unreadable ledgers — operator got a report on the surviving
    subset with NO indication data was lost (dogfood: 1 valid + 2 corrupt
    → "1 sample, 100% win rate" with no warning). Now skipped ledgers are
    recorded under the ``_skipped_ledgers`` key (a non-profile bucket) so
    the render can surface a warning. The caller can also inspect it.
    """
    groups: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, str]] = []
    for path in ledger_paths:
        try:
            header, outcomes = read_outcome_ledger(path)
        except Exception as exc:
            # NS-17/c288: record the skip instead of silently continuing.
            # name the file + error so the operator can fix the root cause
            # (corrupt write, partial file, schema drift) rather than trust
            # a report built on a silently-truncated sample.
            skipped.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        for outcome in outcomes:
            profile = str(outcome.profile or "unknown")
            bucket = groups.setdefault(
                profile,
                {
                    "sample_count": 0,
                    "profit_count": 0,
                    "loss_count": 0,
                    "breakeven_count": 0,
                    "no_entry_count": 0,
                    "missing_data_count": 0,
                    "regimes_covered": set(),
                    "decision_ids": set(),
                },
            )
            bucket["sample_count"] += 1
            if outcome.verdict == OutcomeVerdict.PROFIT:
                bucket["profit_count"] += 1
            elif outcome.verdict == OutcomeVerdict.LOSS:
                bucket["loss_count"] += 1
            elif outcome.verdict == OutcomeVerdict.BREAKEVEN:
                bucket["breakeven_count"] += 1
            elif outcome.verdict == OutcomeVerdict.NO_ENTRY:
                bucket["no_entry_count"] += 1
            elif outcome.verdict == OutcomeVerdict.MISSING_DATA:
                bucket["missing_data_count"] += 1
            if outcome.regime_gate_level and outcome.regime_gate_level != "n/a":
                bucket["regimes_covered"].add(outcome.regime_gate_level)
            bucket["decision_ids"].add(outcome.decision_id)
    # Normalize sets to sorted lists and compute derived stats.
    normalized: dict[str, dict[str, Any]] = {}
    for profile, bucket in groups.items():
        decided = bucket["profit_count"] + bucket["loss_count"] + bucket["breakeven_count"]
        win_rate = round(bucket["profit_count"] / decided, 4) if decided > 0 else None
        coverage = round(decided / bucket["sample_count"], 4) if bucket["sample_count"] > 0 else None
        # Confidence interval approximation (Wilson score at z=1.96).
        # If decided=0, ci_low=ci_high=None.
        if decided > 0:
            p = bucket["profit_count"] / decided
            z = 1.96
            denom = 1 + z * z / decided
            center = (p + z * z / (2 * decided)) / denom
            spread = z * ((p * (1 - p) + z * z / (4 * decided)) / decided) ** 0.5 / denom
            ci_low = round(max(0.0, center - spread), 4)
            ci_high = round(min(1.0, center + spread), 4)
        else:
            ci_low = ci_high = None
        normalized[profile] = {
            "sample_count": bucket["sample_count"],
            "decided_count": decided,
            "profit_count": bucket["profit_count"],
            "loss_count": bucket["loss_count"],
            "breakeven_count": bucket["breakeven_count"],
            "no_entry_count": bucket["no_entry_count"],
            "missing_data_count": bucket["missing_data_count"],
            "win_rate": win_rate,
            "coverage": coverage,
            "win_rate_ci_95": (ci_low, ci_high) if ci_low is not None else None,
            "regimes_covered": sorted(bucket["regimes_covered"]),
            "decision_count": len(bucket["decision_ids"]),
        }
    # NS-17/c288: surface skipped-ledger diagnostics so the render can warn.
    # Stored under a non-profile key (profiles are lowercase like "conservative"
    # / "aggressive" / "unknown"; "_skipped_ledgers" cannot collide).
    if skipped:
        normalized["_skipped_ledgers"] = skipped
    return normalized


# ---------------------------------------------------------------------------
# Comparison report
# ---------------------------------------------------------------------------


def render_profile_experiment_report(
    *,
    contract: ProfileRoutingContract | None = None,
    aggregated: dict[str, dict[str, Any]] | None = None,
    experiment_name: str = "btst_profile_experiment_v1",
) -> str:
    """Render a markdown report comparing conservative vs aggressive.

    If outcome data is insufficient, the report must explicitly say so —
    per the plan, "证据不足" must be written when evidence is missing.
    """
    contract = contract or DEFAULT_PROFILE_ROUTING_CONTRACT
    aggregated = aggregated or {}

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"# BTST Profile Experiment — {experiment_name}",
        "",
        f"- 生成时间: `{now_iso}`",
        f"- 路由契约: `{contract.name}`",
        "- 比较 scope: 真实上游候选筛选与执行规则差异",
        "",
        "## Profile Routing Rules",
        "",
    ]

    for profile_name in ("conservative", "aggressive"):
        rule = contract.conservative if profile_name == "conservative" else contract.aggressive
        lines.append(f"### {profile_name}")
        lines.append("")
        if rule.description:
            lines.append(f"- {rule.description}")
        for gate_key in ("normal_trade", "aggressive_trade", "shadow_only", "halt"):
            hook = rule.hook_for(gate_key)
            lines.append(f"- **{gate_key}**: select={hook.select_threshold}, " f"rank_cap={hook.rank_cap}, action={hook.gate_action}, " f"confirm={hook.confirmation_required}, size_scale={hook.position_size_scale}")
        lines.append("")

    lines.extend(["## Outcome Aggregation", ""])
    # NS-17/c288: surface skipped-ledger warning BEFORE the table so the operator
    # sees data loss before reading stats built on a silently-truncated subset.
    skipped = aggregated.get("_skipped_ledgers") if isinstance(aggregated, dict) else None
    if skipped:
        lines.append(f"- **⚠ 跳过 {len(skipped)} 个无法读取的 outcome ledger** — 聚合基于剩余可读 ledger, " f"统计可能不代表完整样本. 请检查下列文件 (损坏写入 / schema 漂移 / 部分文件):")
        for s in skipped:
            lines.append(f"  - `{s['path']}`: {s['error']}")
        lines.append("")
    if not aggregated:
        lines.append("- **证据不足**：尚未收集到闭合的 outcome 样本。")
        lines.append("")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| profile | sample_count | decided | profit | loss | breakeven | win_rate | ci_95 | coverage | regimes |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |",
        ]
    )
    for profile_name in ("conservative", "aggressive"):
        if profile_name not in aggregated:
            lines.append(f"| {profile_name} | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | n/a |")
            continue
        data = aggregated[profile_name]
        ci = data.get("win_rate_ci_95") or (None, None)
        ci_str = f"[{ci[0]}, {ci[1]}]" if ci[0] is not None else "n/a"
        regimes = ", ".join(data.get("regimes_covered") or []) or "n/a"
        lines.append(f"| {profile_name} | {data['sample_count']} | {data['decided_count']} | " f"{data['profit_count']} | {data['loss_count']} | {data['breakeven_count']} | " f"{data['win_rate'] if data['win_rate'] is not None else 'n/a'} | " f"{ci_str} | " f"{data['coverage'] if data['coverage'] is not None else 'n/a'} | " f"{regimes} |")
    lines.append("")

    # Verdict.
    cons = aggregated.get("conservative", {})
    agg = aggregated.get("aggressive", {})
    lines.extend(["## Verdict", ""])
    if cons.get("decided_count", 0) < 20 or agg.get("decided_count", 0) < 20:
        lines.append("- **证据不足**：decided 样本不足 20，无法给出 statistically meaningful 结论。")
    else:
        cons_wr = cons.get("win_rate")
        agg_wr = agg.get("win_rate")
        if cons_wr is not None and agg_wr is not None:
            if cons_wr > agg_wr + 0.05:
                lines.append(f"- Conservative 在该 regime 样本上胜率明显更高 ({cons_wr:.3f} vs {agg_wr:.3f})。")
            elif agg_wr > cons_wr + 0.05:
                lines.append(f"- Aggressive 在该 regime 样本上胜率明显更高 ({agg_wr:.3f} vs {cons_wr:.3f})。")
            else:
                lines.append(f"- 两套 profile 胜率相近 ({cons_wr:.3f} vs {agg_wr:.3f})，无法区分。")
        else:
            lines.append("- Win rate 数据不完整，无法给出结论。")
    lines.append("")

    # Regime coverage check.
    expected_regimes = {"normal_trade", "shadow_only", "halt"}
    actual_regimes = set(cons.get("regimes_covered") or []) | set(agg.get("regimes_covered") or [])
    missing = expected_regimes - actual_regimes
    if missing:
        lines.append(f"- **Regime 覆盖警告**: 缺失 {sorted(missing)} 的样本，需要补充。")
    else:
        lines.append("- Regime 覆盖: 至少覆盖 normal_trade / shadow_only / halt。")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="BTST profile experiment harness (P2 phase 1).")
    parser.add_argument(
        "--ledger",
        action="append",
        type=Path,
        default=[],
        help="Path(s) to outcome_ledger.json files to aggregate.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/btst_profile_experiment_report.md"),
        help="Output markdown path.",
    )
    parser.add_argument(
        "--experiment-name",
        default="btst_profile_experiment_v1",
        help="Experiment name for the report header.",
    )
    args = parser.parse_args()

    aggregated = aggregate_outcomes_by_profile(args.ledger) if args.ledger else {}
    report = render_profile_experiment_report(
        aggregated=aggregated,
        experiment_name=args.experiment_name,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote {args.output}")
    # Also print to stdout for convenience.
    print(report)


if __name__ == "__main__":
    main()
