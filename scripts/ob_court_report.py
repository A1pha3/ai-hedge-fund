"""OB court 复核第二步: 预注册暂停复核谓词 → 决策包 (2026-08-19).

预注册判定 (先于任何数据写死, 冻结于本文件与产物 manifest):
- 主视野 T+5 (= OB natural_horizon), 净收益 net = gross - 65bps
  (30bps/边滑点 + 5bps 卖出印花税, v2.1 口径, 与 btst_court_views.net_ret 同源);
- 暂停复核谓词 pause_holds = 全候选净 E[r](T+5, fillable) 按信号日聚类
  bootstrap 单侧 90% CI 下界 ≤ 0;CI 下界 > 0 → 上报 owner 复议暂停
  (复议 ≠ 恢复: 恢复仍是 owner 决策 + 新证据世代);
- 分层视图 (regime × 半年度) 与 T+3/T+10 对照为描述性, 不参与谓词。

对照锚: journal 成交子集执行口径 E=-2.15%/wr=39% (n=56, trap 19 选择偏差
样本) — 本报告量化「成交子集 vs 全候选」的证据差。

写入: data/reports/ob_pause_court_recheck_YYYYMMDD.{md,json}。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _btst_court_common import SELL_STAMP_BPS, SLIPPAGE_BPS  # noqa: E402
from btst_court_views import cluster_boot_ci_low, net_ret  # noqa: E402

from ob_court_build import OB_TABLE_DIR, PRIMARY_HORIZON, REF_HORIZONS  # noqa: E402

# journal 成交子集执行口径锚 (2026-08-16 重建, AGENTS.md「2026 实测表现」)
JOURNAL_ANCHOR = {"n": 56, "mean": -0.0215, "win_rate": 0.39, "source": "journal executable subset (trap 19 biased)"}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=date.today().strftime("%Y%m%d"), help="产物日期后缀 YYYYMMDD")
    parser.add_argument("--repo-root", default=".", help="数据根 (默认 cwd)")
    return parser.parse_args(argv)


def _half(s: str) -> str:
    return f"{s[:4]}H{1 if s[4:6] <= '06' else 2}"


def pause_verdict(df: pd.DataFrame, slip_bps: float = SLIPPAGE_BPS) -> dict:
    """预注册谓词 (纯函数): T+5 净收益按信号日聚类 bootstrap 90% CI 下界。"""
    col = f"gross_ret_t{PRIMARY_HORIZON}"
    sub = df[df["fillable"] & df[col].notna()].copy()
    if len(sub) < 30:
        return {"n": len(sub), "ci_low": None, "pause_holds": None,
                "note": f"n={len(sub)} < 30 — 样本不足, 不判谓词"}
    net = net_ret(sub[col], slip_bps)
    ci_low = cluster_boot_ci_low(net, sub["signal_date"])
    return {
        "n": int(len(sub)),
        "mean_net": float(net.mean()),
        "win_rate": float((net > 0).mean()),
        "ci_low_90": float(ci_low),
        "pause_holds": bool(ci_low <= 0),
    }


def _segment(df: pd.DataFrame, slip_bps: float = SLIPPAGE_BPS) -> pd.DataFrame:
    col = f"gross_ret_t{PRIMARY_HORIZON}"
    rows = []
    for keys, g in df.groupby(["regime", df["signal_date"].map(_half)]):
        sub = g[g["fillable"] & g[col].notna()]
        net = net_ret(sub[col], slip_bps) if len(sub) else None
        rows.append({
            "regime": keys[0], "half": keys[1],
            "events": int(len(g)), "filled": int(len(sub)),
            "net_t5_mean": float(net.mean()) if net is not None and len(net) else None,
            "win_rate": float((net > 0).mean()) if net is not None and len(net) else None,
        })
    return pd.DataFrame(rows)


def main() -> None:
    import os

    args = _parse_args()
    os.chdir(args.repo_root)

    table_path = OB_TABLE_DIR / "ob_event_table_v1.csv.gz"
    manifest_path = OB_TABLE_DIR / "manifest_v1.json"
    if not table_path.exists() or not manifest_path.exists():
        raise SystemExit(f"事件表缺失 ({table_path}) — 先跑 scripts/ob_court_build.py")
    df = pd.read_csv(table_path, dtype={"signal_date": str})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    verdict = pause_verdict(df)
    seg = _segment(df)
    # 对照视野 (描述性)
    ref = {}
    for k in REF_HORIZONS:
        col = f"gross_ret_t{k}"
        sub = df[df["fillable"] & df[col].notna()]
        net = net_ret(sub[col], SLIPPAGE_BPS)
        ref[f"t{k}"] = {"n": int(len(sub)), "mean_net": float(net.mean()) if len(sub) else None,
                        "win_rate": float((net > 0).mean()) if len(sub) else None}
    fills = {
        "events": int(len(df)),
        "fillable": int(df["fillable"].sum()),
        "t1_unbuyable": int(df["t1_unbuyable"].sum()),
        "t1_missing_bar": int(df["t1_missing_bar"].sum()),
    }

    payload = {
        "date": args.date,
        "manifest_window": manifest["window"],
        "manifest_formula": manifest["formula_fingerprint"],
        "primary_horizon": PRIMARY_HORIZON,
        "cost_bps": {"slippage_per_side": SLIPPAGE_BPS, "sell_stamp": SELL_STAMP_BPS},
        "funnel": manifest["funnel"],
        "fills": fills,
        "verdict": verdict,
        "segments": seg.to_dict(orient="records"),
        "reference_horizons": ref,
        "journal_anchor": JOURNAL_ANCHOR,
        "pre_registered_rule": "pause_holds = (T+5 net cluster-bootstrap 90% CI low <= 0); CI low > 0 -> owner review",
    }

    out_json = Path(f"data/reports/ob_pause_court_recheck_{args.date}.json")
    out_md = Path(f"data/reports/ob_pause_court_recheck_{args.date}.md")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    v = verdict
    lines = [
        "# OB 暂停决定 court 级复核 (全候选重放)",
        "",
        f"- 窗口: {manifest['window']['start']} → {manifest['window']['end']} ({manifest['window']['sessions']} 会话)",
        f"- 漏斗: 预筛 {manifest['funnel']['prefilter']:,} → hits {manifest['funnel']['hits']:,}"
        f" → fillable {fills['fillable']:,} (一字 {fills['t1_unbuyable']} / 缺bar {fills['t1_missing_bar']})",
        f"- 公式指纹: oversold_bounce {manifest['formula_fingerprint']['oversold_bounce_sha256'][:12]}…",
        "",
        "## 预注册谓词 (T+5 净收益, 按信号日聚类 bootstrap 90% CI)",
        "",
    ]
    if v["pause_holds"] is None:
        lines.append(f"- **样本不足** (n={v['n']} < 30) — 不判谓词, 维持暂停 (fail-closed)")
    else:
        verdict_text = "维持暂停" if v["pause_holds"] else "**上报 owner 复议** (CI 下界 > 0)"
        lines.append(
            f"- n={v['n']} · 净 E[r] {v['mean_net']:+.2%} · 胜率 {v['win_rate']:.1%} · CI90 下界 {v['ci_low_90']:+.2%}"
            f" → **{verdict_text}**"
        )
    lines += [
        "",
        "## 对照: journal 成交子集 vs 全候选",
        "",
        f"- journal 执行口径 (暂停依据, n={JOURNAL_ANCHOR['n']}): {JOURNAL_ANCHOR['mean']:+.2%} / {JOURNAL_ANCHOR['win_rate']:.0%}",
        f"- court 全候选 T+5 (n={v.get('n')}): {('%.2f' % (v['mean_net'] * 100)) if v.get('mean_net') is not None else 'n/a'}%"
        f" / {('%.0f' % (v['win_rate'] * 100)) if v.get('win_rate') is not None else 'n/a'}%",
        "- 差异来源: journal 是回测实际成交子集 (资金/排队条件化, trap 19); court 是全触发候选",
        "",
        "## regime × 半年度 (T+5 净, 描述性)",
        "",
        "| regime | 半年 | 事件 | 成交 | 净均值 | 胜率 |",
        "|---|---|---|---|---|---|",
    ]
    for r in seg.to_dict(orient="records"):
        nm = f"{r['net_t5_mean']:+.2%}" if r["net_t5_mean"] is not None else "n/a"
        wr = f"{r['win_rate']:.0%}" if r["win_rate"] is not None else "n/a"
        lines.append(f"| {r['regime']} | {r['half']} | {r['events']} | {r['filled']} | {nm} | {wr} |")
    lines += [
        "",
        "## 纪律",
        "",
        "- 本报告是研究复核产物: 谓词为真只证明「暂停在 court 口径下站得住」;",
        "  谓词为假也只是**上报 owner 复议**, 恢复/参数变更 = 新证据世代 + owner 决策。",
        "- 已知局限: ST 一字判定按 10% 板 (面板无 name); OB 无外部权威候选名单",
        "  (完备性由预筛与生产 detect 同面板同数学保证, 抽查 |Δ|<1e-9)。",
        "",
    ]
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] {out_md}")
    print(f"[report] {out_json}")
    print(json.dumps({"verdict": verdict, "fills": fills}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
