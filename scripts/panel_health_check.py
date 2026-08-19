"""Read-only health check for the out-of-sample setup-output panel.

Reads ``data/reports/setup_output_panel.jsonl`` and, once enough forward returns
have realized per horizon (default >=30), runs a Welch's t-test comparing
``plan_eligible`` vs ``filtered`` forward returns. It answers one question:

    Does the full setup filter actually pick alpha, or is plan_eligible
    membership statistically indistinguishable from the filtered rejects?

The filtered control group is stratified (2026-08-16): rows whose detector was
data-degraded (``degraded=True`` or ``block_reason`` starting with
``readiness degraded:``) never ran the full strategy judgment, so they are
reported as a separate disclosure layer and excluded from the control test.
Mixing them in once produced a p<0.001 fake "filter picks alpha" verdict off a
single-day industry_data_missing outage (257/295 filtered rows).

Strictly read-only: never writes files, never touches strategy params, no
network. Safe to run any time. Below the sample threshold it prints the current
distributions and says "not enough data yet" rather than guessing.

Run:
    uv run python scripts/panel_health_check.py
    uv run python scripts/panel_health_check.py --min-n 30 --min-group 5
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import stats

from scripts.validate_auto300_gate_removal import HORIZONS, _fmt, _summarize

PANEL = Path("data/reports/setup_output_panel.jsonl")


def load_panel(path: Path = PANEL) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _returns(rows: list[dict], horizon: int, eligible: bool) -> list[float]:
    """Realized forward returns for one group (eligible vs filtered), NaN-safe."""
    key = f"return_t{horizon}"
    out: list[float] = []
    for r in rows:
        if bool(r.get("plan_eligible")) is not eligible:
            continue
        v = r.get(key)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            out.append(fv)
    return out


def _is_data_degraded(row: dict) -> bool:
    """数据护栏降级票: 检测器因数据缺失降级, 未跑完整策略判断.

    判别优先结构化 ``degraded`` 字段, ``block_reason`` 前缀作交叉兜底
    (真实 panel 两者一致; 分离时以结构化字段为准).
    """
    if row.get("degraded"):
        return True
    return str(row.get("block_reason", "") or "").startswith("readiness degraded")


def _split_returns(rows: list[dict], horizon: int) -> tuple[list[float], list[float], list[float]]:
    """三层切分 realized 前向收益: (eligible, 策略过滤, 数据护栏降级)."""
    key = f"return_t{horizon}"
    elig: list[float] = []
    strat: list[float] = []
    deg: list[float] = []
    for r in rows:
        v = r.get(key)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(fv):
            continue
        if bool(r.get("plan_eligible")):
            elig.append(fv)
        elif _is_data_degraded(r):
            deg.append(fv)
        else:
            strat.append(fv)
    return elig, strat, deg


def _cohens_d(a: list[float], b: list[float]) -> float:
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan")
    va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if pooled == 0:
        return float("nan")
    return (float(np.mean(a)) - float(np.mean(b))) / pooled


def _welch_df(a: list[float], b: list[float]) -> float:
    na, nb = len(a), len(b)
    va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    num = (va / na + vb / nb) ** 2
    den = (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    return num / den if den > 0 else float("nan")


def _verdict(p: float, delta_mean: float, alpha: float = 0.05) -> str:
    if p < alpha and delta_mean > 0:
        return "✅ 全过滤显著挑出 alpha（eligible 前向收益显著高于 filtered）"
    if p < alpha and delta_mean < 0:
        return "⚠️ 反向：filtered 反而显著更优 —— 全过滤可能有害，需复核过滤逻辑"
    return "◻️ 不显著：无法证明全过滤挑出 alpha（eligible 与 filtered 无统计差异）"


def _test_horizon(rows: list[dict], horizon: int, min_n: int, min_group: int) -> dict | None:
    """Welch t-test stats for one horizon, or None if too few realized samples.

    Control group = strategy-filtered only; data-degraded rows are counted for
    disclosure but never enter the test.
    """
    elig, strat, deg = _split_returns(rows, horizon)
    if len(elig) + len(strat) < min_n or len(elig) < min_group or len(strat) < min_group:
        return None
    res = stats.ttest_ind(elig, strat, equal_var=False)
    df_attr = getattr(res, "df", None)
    return {
        "p": float(res.pvalue),
        "t": float(res.statistic),
        "df": float(df_attr) if df_attr is not None else _welch_df(elig, strat),
        "delta_mean": float(np.mean(elig)) - float(np.mean(strat)),
        "d": _cohens_d(elig, strat),
        "n_elig": len(elig),
        "n_filt": len(strat),
        "n_degraded": len(deg),
    }


def check_horizon(rows: list[dict], horizon: int, min_n: int, min_group: int) -> tuple[str, bool | None]:
    """Return (rendered_block, verdict). verdict: True=alpha, False=tested-no-alpha, None=untestable."""
    elig, strat, deg = _split_returns(rows, horizon)
    total = len(elig) + len(strat)
    lines = [
        f"--- T+{horizon} ---",
        f"  plan_eligible: {_fmt(_summarize(elig))}",
        f"  策略过滤      : {_fmt(_summarize(strat))}",
    ]
    if deg:
        lines.append(
            f"  数据护栏降级  : {_fmt(_summarize(deg))}  ← readiness 降级未跑完整策略判断, 不进对照检验"
        )
    stat = _test_horizon(rows, horizon, min_n, min_group)
    if stat is None:
        if total < min_n:
            lines.append(f"  ⏳ 样本不足（已实现 {total} < {min_n}，降级票 {len(deg)} 不计入）——继续用 --daily-action + --auto 累积")
        else:
            lines.append(f"  ⏳ 某组样本过小（eligible={len(elig)}, 策略过滤={len(strat)}, 需各 ≥{min_group}）")
        return "\n".join(lines), None
    lines.append(
        f"  Welch t-test: t={stat['t']:+.2f}  df={stat['df']:.1f}  p={stat['p']:.4f}  "
        f"Δmean={stat['delta_mean']:+.2f}%  Cohen's d={stat['d']:+.2f}"
    )
    lines.append("  " + _verdict(stat["p"], stat["delta_mean"]))
    return "\n".join(lines), bool(stat["p"] < 0.05 and stat["delta_mean"] > 0)


def panel_health_status(panel: Path = PANEL, min_n: int = 30, min_group: int = 5) -> dict:
    """Structured panel stats for the --auto briefing card (H1: compute once).

    Same loaders/thresholds as :func:`panel_health_oneline`; returns per-horizon
    testability + Welch stats instead of a rendered string so display layers can
    consume the facts without re-deriving them. ``n_filt`` counts the
    strategy-filtered control group only; ``n_degraded`` counts data-degraded
    rows (excluded from the test, disclosure only). Strictly read-only.
    """
    rows = load_panel(panel)
    realized = sum(1 for r in rows if r.get("realized"))
    horizons: dict[str, dict] = {}
    for horizon in HORIZONS:
        stat = _test_horizon(rows, horizon, min_n, min_group)
        if stat is None:
            elig, strat, deg = _split_returns(rows, horizon)
            horizons[str(horizon)] = {
                "testable": False,
                "n_elig": len(elig),
                "n_filt": len(strat),
                "n_degraded": len(deg),
            }
        else:
            horizons[str(horizon)] = {
                "testable": True,
                "p": stat["p"],
                "delta_mean": stat["delta_mean"],
                "n_elig": stat["n_elig"],
                "n_filt": stat["n_filt"],
                "n_degraded": stat["n_degraded"],
            }
    return {"rows": len(rows), "realized": realized, "horizons": horizons}


def _marginal_contrast_segment(rows: list[dict]) -> str:
    """「边缘对照」段: 预注册对比 (0.50-0.60 边缘桶 vs 拒(<0.50)) 的 T+1 计数.

    count-only (不报均值/p — 反偷看, 推断留给 panel_signal_decomposition 报告);
    成熟判据 min(a,b) >= MIN_CELL_N (与分解工具的披露门槛同源 import, 无第二处 30).
    任何异常只降级为占位文本, 绝不拖垮既有体检行.
    """
    try:
        from scripts.panel_signal_decomposition import MIN_CELL_N, contrast_t1_counts

        marginal, rejected = contrast_t1_counts(rows)
    except Exception:  # noqa: BLE001 - 新段异常隔离, 既有行不受影响
        return " · (桶计数不可用)"
    if min(marginal, rejected) >= MIN_CELL_N:
        return f" · ⚠边缘对照可初判 {marginal}|{rejected}→{MIN_CELL_N}"
    return f" · 边缘对照 {marginal}|{rejected}/{MIN_CELL_N}"


def panel_health_oneline(panel: Path = PANEL, min_n: int = 30, min_group: int = 5) -> str:
    """One-line panel-health summary for --auto logs (best-effort, read-only)."""
    rows = load_panel(panel)
    if not rows:
        return "面板为空"
    realized = sum(1 for r in rows if r.get("realized"))
    prefix = f"{len(rows)}条/已实现{realized}"
    degraded_total = sum(
        1 for r in rows if not r.get("plan_eligible") and _is_data_degraded(r)
    )
    if degraded_total:
        prefix += f"/降级{degraded_total}不入对照"
    contrast = _marginal_contrast_segment(rows)
    tags: list[str] = []
    testable = False
    for horizon in HORIZONS:
        stat = _test_horizon(rows, horizon, min_n, min_group)
        if stat is None:
            tags.append(f"T+{horizon}:⏳")
            continue
        testable = True
        if stat["p"] < 0.05 and stat["delta_mean"] > 0:
            tags.append(f"T+{horizon}:✅p={stat['p']:.3f}")
        elif stat["p"] < 0.05 and stat["delta_mean"] < 0:
            tags.append(f"T+{horizon}:⚠️反向p={stat['p']:.3f}")
        else:
            tags.append(f"T+{horizon}:◻️p={stat['p']:.3f}")
    if not testable:
        return f"{prefix} 未达检验门槛(需某 horizon 已实现≥{min_n}/组≥{min_group}, 对照=策略过滤组){contrast}"
    return f"{prefix}  " + " ".join(tags) + contrast


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only setup-output panel health check (plan_eligible vs filtered t-test).")
    ap.add_argument("--panel", type=Path, default=PANEL, help="panel jsonl path")
    ap.add_argument("--min-n", type=int, default=30, help="min realized rows per horizon to run the test")
    ap.add_argument("--min-group", type=int, default=5, help="min realized rows required in EACH group")
    args = ap.parse_args()

    rows = load_panel(args.panel)
    print("━" * 60)
    print("setup-output 面板体检（只读；不改策略、不写文件、不联网）")
    print(f"面板: {args.panel}")
    if not rows:
        print("面板为空 —— 先跑 --daily-action（记录信号）与 --auto（回填收益）累积样本。")
        return

    realized = [r for r in rows if r.get("realized")]
    days = sorted({str(r.get("signal_date")) for r in rows if r.get("signal_date")})
    regimes = Counter(str(r.get("regime")) for r in rows)
    setups = Counter(str(r.get("setup")) for r in rows)
    elig_n = sum(1 for r in rows if r.get("plan_eligible"))
    deg_n = sum(1 for r in rows if not r.get("plan_eligible") and _is_data_degraded(r))
    print(f"记录: {len(rows)}  已实现: {len(realized)}  待实现: {len(rows) - len(realized)}  信号日: {len(days)} ({days[0]}→{days[-1]})")
    print("regime: " + "  ".join(f"{k}={v}" for k, v in regimes.most_common()))
    print("setup:  " + "  ".join(f"{k}={v}" for k, v in setups.most_common()))
    print(f"分组: plan_eligible={elig_n}  策略过滤={len(rows) - elig_n - deg_n}  数据护栏降级={deg_n}（不入对照）")
    print(f"门槛: 每 horizon 已实现 ≥{args.min_n} 且每组 ≥{args.min_group} 才做 Welch t 检验（对照 = 策略过滤组；数据护栏降级票不入对照，单独披露）")
    print("注: eligible 主要为过全过滤的 btst；策略过滤组为检测器正常但被策略判断拒绝的票（强度/资金流/行业等）；数据护栏降级组未跑完整策略判断，不是策略证据。")
    print("─" * 60)

    tested = False
    any_alpha = False
    for horizon in HORIZONS:
        block, verdict = check_horizon(rows, horizon, args.min_n, args.min_group)
        print(block)
        if verdict is not None:
            tested = True
            any_alpha = any_alpha or verdict
    print("─" * 60)
    if not tested:
        print("结论: 样本尚未到期/不足，无法判定「全过滤是否挑出 alpha」。闭环会随日累积，样本够后本工具自动出检验结果。")
    elif any_alpha:
        print("结论: 至少一个 horizon 上 plan_eligible 前向收益显著高于 filtered → 全过滤在挑 alpha（样本外证据，非回测）。")
    else:
        print("结论: 已可检验的 horizon 均未显示 eligible 显著优于 filtered → 尚无证据表明全过滤挑出 alpha；继续累积或复核过滤逻辑。")


if __name__ == "__main__":
    main()
