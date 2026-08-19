"""panel T+1 反向信号分解诊断 (只读, 2026-08-19).

背景: panel_health_check 首个诚实结论 (2026-08-16, 326 realized) 是一个标量差:
策略过滤组 T+1 +1.30% vs plan_eligible -1.37% (Welch p=0.040) — 全过滤挑出的
eligible 在 T+1 反而跑输被拒组。本工具把该信号拆到可定位的维度
(强度桶 / regime / 拒票原因结构), 随 panel 增长可复跑更新。

预注册解释纪律 (先于数据):
- 与 panel_health_check 同分组语义: degraded (行 degraded=True 或 block_reason
  以 'readiness degraded' 开头) 排除且单独披露计数, 不入对照;
- 每格 n<30 → 只披露不给判定 (对齐 BUY-gate backing_sample≥20 与 court 样本
  纪律的保守取向, 此处取 30 与 panel_health_check min_n 一致);
- 本工具是诊断, 不是参数变更提案 — 任何阈值调整 = 策略行为变化 = 新证据世代。

写入: data/reports/panel_decomposition_YYYYMMDD.{md,json} (决策包约定)。
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from statistics import fmean

from scipy import stats

PANEL_PATH = Path("data/reports/setup_output_panel.jsonl")
MIN_CELL_N = 30  # 与 panel_health_check.min_n 一致
HORIZONS = (1, 5, 10)  # T+1 主视野 (反向信号出处), T+5/T+10 诊断对照
STRENGTH_BUCKETS = ((0.50, "0.50-0.60"), (0.60, "0.60-0.70"), (0.70, "≥0.70"))


def load_rows(panel: Path) -> list[dict]:
    if not panel.exists():
        raise SystemExit(f"panel 缺失: {panel}")
    return [json.loads(l) for l in panel.read_text(encoding="utf-8").splitlines() if l.strip()]


def is_degraded(row: dict) -> bool:
    """panel_health_check._is_data_degraded 同语义 (防两处口径漂移)."""
    return bool(row.get("degraded")) or str(row.get("block_reason") or "").startswith("readiness degraded")


def split_groups(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"eligible": [], "rejected": [], "degraded": []}
    for r in rows:
        if is_degraded(r):
            out["degraded"].append(r)
        elif r.get("plan_eligible"):
            out["eligible"].append(r)
        else:
            out["rejected"].append(r)
    return out


def strength_bucket(row: dict) -> str:
    """拒(<0.50) 按 block_reason 语义归桶; eligible 按触发强度分桶.

    eligible 但强度 <0.50 (数据异常, 阈值门应已挡) 单独归 'eligible(<0.50)·异常'
    — 如实披露不吞掉。
    """
    if not row.get("plan_eligible"):
        return "拒(<0.50)"
    ts = float(row.get("trigger_strength") or 0.0)
    if ts < 0.50:
        return "eligible(<0.50)·异常"
    if ts < 0.60:
        return "0.50-0.60"
    if ts < 0.70:
        return "0.60-0.70"
    return "≥0.70"


def horizon_returns(rows: list[dict], horizon: int) -> list[float]:
    key = f"return_t{horizon}"
    out = []
    for r in rows:
        v = r.get(key)
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def welch(a: list[float], b: list[float]) -> dict:
    """Welch t (a vs b) + Cohen's d; 空组返回 n 感知的不可判结构."""
    if not a or not b:
        return {"n_a": len(a), "n_b": len(b), "t": None, "p": None, "cohens_d": None,
                "mean_a": fmean(a) if a else None, "mean_b": fmean(b) if b else None}
    res = stats.ttest_ind(a, b, equal_var=False)
    na, nb = len(a), len(b)
    sa = stats.tvar(a) if na > 1 else 0.0
    sb = stats.tvar(b) if nb > 1 else 0.0
    pooled = ((na - 1) * sa + (nb - 1) * sb) / max(1, na + nb - 2)
    d = (fmean(a) - fmean(b)) / (pooled ** 0.5) if pooled > 0 else 0.0
    return {"n_a": na, "n_b": nb, "t": float(res.statistic), "p": float(res.pvalue),
            "cohens_d": float(d), "mean_a": fmean(a), "mean_b": fmean(b)}


def cell(values: list[float]) -> dict:
    return {
        "n": len(values),
        "mean": fmean(values) if values else None,
        "win_rate": (sum(1 for v in values if v > 0) / len(values)) if values else None,
        "sufficient": len(values) >= MIN_CELL_N,
    }


def block_reason_class(reason: str | None) -> str:
    r = str(reason or "")
    if r.startswith("readiness degraded"):
        return "readiness_degraded"
    if "trigger_strength" in r or ("强度" in r and "阈值" in r):
        return "strength_below_threshold"
    if not r:
        return "unclassified"
    return r[:48]


def decompose(rows: list[dict]) -> dict:
    groups = split_groups(rows)
    elig, rej = groups["eligible"], groups["rejected"]
    out: dict = {
        "rows_total": len(rows),
        "degraded_excluded": len(groups["degraded"]),
        "eligible_n": len(elig),
        "rejected_n": len(rej),
        "headline": {},
        "strength_bucket_horizons": {},
        "regime_split_t1": {},
        "rejected_reason_classes": {},
    }
    # 1. headline: eligible vs rejected 逐 horizon Welch (复现 panel_health_check 口径)
    for h in HORIZONS:
        out["headline"][f"t{h}"] = welch(horizon_returns(elig, h), horizon_returns(rej, h))
    # 2. 强度桶 × horizon (非降级全量, 桶区分 eligible 强度层与 <0.50 拒票组)
    nond = elig + rej
    for h in HORIZONS:
        table = {}
        for label in ["拒(<0.50)", "0.50-0.60", "0.60-0.70", "≥0.70"]:
            bucket_rows = [r for r in nond if strength_bucket(r) == label]
            table[label] = cell(horizon_returns(bucket_rows, h))
        out["strength_bucket_horizons"][f"t{h}"] = table
    # 3. T+1 反向的 regime 分解
    for reg in sorted({str(r.get("regime")) for r in nond}):
        e = [r for r in elig if str(r.get("regime")) == reg]
        j = [r for r in rej if str(r.get("regime")) == reg]
        out["regime_split_t1"][reg] = welch(horizon_returns(e, 1), horizon_returns(j, 1))
    # 4. 拒票原因结构 (T+1 均值)
    for r in rej:
        r["_cls"] = block_reason_class(r.get("block_reason"))
    for cls in sorted({r["_cls"] for r in rej}):
        rows_cls = [r for r in rej if r["_cls"] == cls]
        out["rejected_reason_classes"][cls] = {
            "n": len(rows_cls), "t1": cell(horizon_returns(rows_cls, 1))
        }
    for r in rej:
        del r["_cls"]
    return out


def _fmt_pct(v: float | None) -> str:
    """panel 前向收益以百分数存储 (1.30 = +1.30%), 与 panel_health_check 同单位."""
    return "n/a" if v is None else f"{v:+.2f}%"


def render_md(payload: dict, date_str: str) -> str:
    h1 = payload["headline"]["t1"]
    lines = [
        "# panel T+1 反向信号分解 (只读诊断)",
        "",
        f"- 样本: {payload['rows_total']} 行 (排除降级 {payload['degraded_excluded']}, 单独披露不入对照)",
        f"- 非降级对照: eligible n={payload['eligible_n']} vs 策略拒票 n={payload['rejected_n']}",
        "",
        "## headline: eligible vs 拒票组 (Welch, 与 panel_health_check 同口径)",
        "",
    ]
    for h in HORIZONS:
        w = payload["headline"][f"t{h}"]
        p_txt = "n/a" if w["p"] is None else f"{w['p']:.3f}"
        d_txt = "n/a" if w["cohens_d"] is None else f"{w['cohens_d']:+.2f}"
        lines.append(
            f"- T+{h}: eligible {_fmt_pct(w['mean_a'])} (n={w['n_a']}) "
            f"vs 拒票 {_fmt_pct(w['mean_b'])} (n={w['n_b']}) · Welch p={p_txt} · d={d_txt}"
        )
    lines += [
        "",
        "## 强度桶 × horizon (每格 n<30 只披露不判定)",
        "",
    ]
    for h in HORIZONS:
        lines.append(f"### T+{h}")
        lines.append("| 桶 | n | 均值 | 胜率 | 判定 |")
        lines.append("|---|---|---|---|---|")
        for label, c in payload["strength_bucket_horizons"][f"t{h}"].items():
            wr = "n/a" if c["win_rate"] is None else f"{c['win_rate']:.0%}"
            verdict = "充分" if c["sufficient"] else "⚠样本不足"
            lines.append(f"| {label} | {c['n']} | {_fmt_pct(c['mean'])} | {wr} | {verdict} |")
    lines += ["", "## T+1 反向的 regime 分解", ""]
    for reg, w in payload["regime_split_t1"].items():
        p_txt = "n/a" if w["p"] is None else f"{w['p']:.3f}"
        lines.append(
            f"- {reg}: eligible {_fmt_pct(w['mean_a'])} (n={w['n_a']}) "
            f"vs 拒票 {_fmt_pct(w['mean_b'])} (n={w['n_b']}) · p={p_txt}"
        )
    lines += ["", "## 拒票原因结构 (T+1 均值)", ""]
    for cls, info in payload["rejected_reason_classes"].items():
        lines.append(f"- {cls}: n={info['n']} · T+1 {_fmt_pct(info['t1']['mean'])}")
    lines += [
        "",
        "## 纪律",
        "",
        "- 本报告是诊断分解, 不构成参数变更提案; 任何阈值调整 = 新证据世代 + owner 决策。",
        f"- 每格 n<{MIN_CELL_N} 只披露不判定 (对齐 panel_health_check min_n)。",
        "",
    ]
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--panel", default=None, help="panel jsonl 覆盖路径 (默认 repo-root 下标准位置)")
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    os.chdir(args.repo_root)
    panel = Path(args.panel) if args.panel else PANEL_PATH
    rows = load_rows(panel)
    payload = decompose(rows)
    payload["date"] = args.date
    payload["panel_path"] = str(panel)
    payload["pre_registered"] = {
        "min_cell_n": MIN_CELL_N,
        "interpretation": "n<30 cells: disclose only, no verdict; diagnostic, not a parameter-change proposal",
    }
    out_json = Path(f"data/reports/panel_decomposition_{args.date}.json")
    out_md = Path(f"data/reports/panel_decomposition_{args.date}.md")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(render_md(payload, args.date), encoding="utf-8")
    print(f"[decomp] {out_md}")
    print(f"[decomp] {out_json}")
    h1 = payload["headline"]["t1"]
    p_txt = "n/a" if h1["p"] is None else f"{h1['p']:.3f}"
    print(f"T+1 headline: elig {_fmt_pct(h1['mean_a'])} vs rej {_fmt_pct(h1['mean_b'])} p={p_txt}")


if __name__ == "__main__":
    main()
