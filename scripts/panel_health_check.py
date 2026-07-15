"""Read-only health check for the out-of-sample setup-output panel.

Reads ``data/reports/setup_output_panel.jsonl`` and, once enough forward returns
have realized per horizon (default >=30), runs a Welch's t-test comparing
``plan_eligible`` vs ``filtered`` forward returns. It answers one question:

    Does the full setup filter actually pick alpha, or is plan_eligible
    membership statistically indistinguishable from the filtered rejects?

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


def check_horizon(rows: list[dict], horizon: int, min_n: int, min_group: int) -> tuple[str, bool | None]:
    """Return (rendered_block, verdict). verdict: True=alpha, False=tested-no-alpha, None=untestable."""
    elig = _returns(rows, horizon, True)
    filt = _returns(rows, horizon, False)
    total = len(elig) + len(filt)
    lines = [
        f"--- T+{horizon} ---",
        f"  plan_eligible: {_fmt(_summarize(elig))}",
        f"  filtered     : {_fmt(_summarize(filt))}",
    ]
    if total < min_n:
        lines.append(f"  ⏳ 样本不足（已实现 {total} < {min_n}）——继续用 --daily-action + --auto 累积")
        return "\n".join(lines), None
    if len(elig) < min_group or len(filt) < min_group:
        lines.append(f"  ⏳ 某组样本过小（eligible={len(elig)}, filtered={len(filt)}, 需各 ≥{min_group}）")
        return "\n".join(lines), None

    res = stats.ttest_ind(elig, filt, equal_var=False)
    t_stat = float(res.statistic)
    p_val = float(res.pvalue)
    df_attr = getattr(res, "df", None)
    df = float(df_attr) if df_attr is not None else _welch_df(elig, filt)
    delta_mean = float(np.mean(elig)) - float(np.mean(filt))
    d = _cohens_d(elig, filt)
    lines.append(
        f"  Welch t-test: t={t_stat:+.2f}  df={df:.1f}  p={p_val:.4f}  "
        f"Δmean={delta_mean:+.2f}%  Cohen's d={d:+.2f}"
    )
    lines.append("  " + _verdict(p_val, delta_mean))
    return "\n".join(lines), bool(p_val < 0.05 and delta_mean > 0)


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
    print(f"记录: {len(rows)}  已实现: {len(realized)}  待实现: {len(rows) - len(realized)}  信号日: {len(days)} ({days[0]}→{days[-1]})")
    print("regime: " + "  ".join(f"{k}={v}" for k, v in regimes.most_common()))
    print("setup:  " + "  ".join(f"{k}={v}" for k, v in setups.most_common()))
    print(f"分组: plan_eligible={elig_n}  filtered={len(rows) - elig_n}")
    print(f"门槛: 每 horizon 已实现 ≥{args.min_n} 且每组 ≥{args.min_group} 才做 Welch t 检验")
    print("注: eligible 主要为过全过滤的 btst；filtered 含多种被拒 setup，样本足够后建议按 setup 分层复核。")
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
