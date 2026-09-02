"""c3 行业门舍入翻转带量化 — 判决在舍入噪声上的占比 (纯诊断).

第一性原理: c3 门 (industry_day_pct ≥ 2.0%) 消费的行业指数缓存自 2026-09-01
起换源 sw_daily (pct_change 仅 2 位小数, commit ba5b8447 重写过历史) — 源数据
一个发布量子的差异即可翻转边际判决 (R96 Op2 的 5 笔 c3 分歧交易即此机制)。
本工具预注册带宽并量化两面:

  预注册带宽 (冻结于代码):
    flip_pass  发布值 == 2.00 (边际通过 — 源低 0.005+ 即翻为 fail)
    flip_fail  发布值 == 1.99 (边际拦截 — 源高 0.005+ 即翻为 pass)
    firm_pass  发布值 ≥ 2.01; firm_fail 发布值 ≤ 1.98

  ① 事件侧 — court 事件 (全部通过 c3): flip_pass 占比与净结果 vs firm_pass;
  ② 预筛侧 — raw 面板涨停票 (pct≥9.5 非北交所, 不跑 detect 只看 c3):
    距阈分布 + 两侧翻转带计数 → 直接回答「c3 判决有多少比例在舍入噪声上」。

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2); 修门 (滞后带/精度源) = 参数变化 = owner 决策。
  - 行业值复算与 court build 同源 (industry_of + load_industry_day_pct)。
  - 确定性: 同输入逐字节同输出 (无 RNG)。

用法:
    uv run python scripts/btst_c3_flip_band.py
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

COURT_TABLE = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
RAW_DIR = Path("data/research/btst_court/raw")
REPORTS_DIR = Path("data/reports")

# 预注册带宽 (常量冻结): 阈值 2.0%, 发布量子 0.01
C3_THRESHOLD = 2.0
PUBLISH_QUANTUM = 0.01
FLIP_PASS_MIN = 2.0  # == 2.00 (边际通过)
FLIP_FAIL_MAX = 1.99  # == 1.99 (边际拦截)
FIRM_PASS_MIN = 2.01

NET_COST_PCT = 0.65
MIN_CELL_N = 30


@dataclass(frozen=True)
class BandClass:
    label: str


def classify_pct(pct: float | None) -> str:
    """发布值 → firm_pass / flip_pass / flip_fail / firm_fail (预注册带宽)."""
    if pct is None or pd.isna(pct):
        return "unknown"
    if pct >= FIRM_PASS_MIN:
        return "firm_pass"
    if abs(pct - FLIP_PASS_MIN) < PUBLISH_QUANTUM / 2:
        return "flip_pass"
    if abs(pct - FLIP_FAIL_MAX) < PUBLISH_QUANTUM / 2:
        return "flip_fail"
    if pct >= C3_THRESHOLD:
        return "firm_pass_marginal"  # 理论不可达 (2.00 已归 flip) — 防御披露
    return "firm_fail"


def band_stats(values: pd.Series, nets: pd.Series | None = None) -> dict[str, Any]:
    """一带 → 计数/占比 + (可选) 净 E/胜率."""
    out: dict[str, Any] = {"n": int(values.size)}
    if nets is not None and values.size:
        sub = nets[values.index]
        out["mean_net_e_pct"] = round(float(sub.mean()), 2)
        out["win_rate_pct"] = round(float((sub > 0).mean()) * 100.0, 1)
    return out


def event_side(events: pd.DataFrame, industry_pct_of) -> dict[str, Any]:
    """court 事件侧: 逐事件复算 industry_pct → 带分布 + 净结果对照."""
    rows = []
    for _, event in events.iterrows():
        symbol = str(event["ts_code"]).split(".")[0]
        day = str(event["signal_date"]).replace("-", "")[:8]
        rows.append((symbol, day, event.get("gross_ret_t10")))
    classified = {"firm_pass": [], "flip_pass": [], "other": []}
    nets: dict[str, list[float]] = {"firm_pass": [], "flip_pass": [], "other": []}
    for symbol, day, gross in rows:
        pct = industry_pct_of(symbol, day)
        band = classify_pct(pct)
        key = band if band in ("firm_pass", "flip_pass") else "other"
        classified[key].append(pct)
        if gross is not None and not pd.isna(gross):
            nets[key].append(float(gross) * 100.0 - NET_COST_PCT)
    out: dict[str, Any] = {}
    total = sum(len(v) for v in classified.values())
    for key in ("firm_pass", "flip_pass", "other"):
        out[key] = {"n": len(classified[key])}
        if nets[key]:
            out[key]["mean_net_e_pct"] = round(sum(nets[key]) / len(nets[key]), 2)
            out[key]["win_rate_pct"] = round(100.0 * sum(1 for v in nets[key] if v > 0) / len(nets[key]), 1)
    out["flip_pass_share_pct"] = round(100.0 * len(classified["flip_pass"]) / max(1, total), 2)
    return out


def prescreen_side(panel: pd.DataFrame, industry_pct_of) -> dict[str, Any]:
    """预筛侧: 面板涨停票 (pct≥9.5 非北交所) 的 c3 带分布 (不跑 detect)."""
    df = panel.copy()
    df["trade_date"] = df["trade_date"].map(lambda d: str(d).replace("-", "")[:8])
    df = df[~df["ts_code"].astype(str).str.startswith(("8", "4", "9"))]
    df = df[pd.to_numeric(df["pct_chg"], errors="coerce") >= 9.5]
    counts = {"firm_pass": 0, "flip_pass": 0, "flip_fail": 0, "firm_fail": 0, "unknown": 0}
    for _, row in df.iterrows():
        pct = industry_pct_of(str(row["ts_code"]).split(".")[0], row["trade_date"])
        band = classify_pct(pct)
        counts[band if band in counts else "unknown"] += 1
    total = sum(counts.values())
    decided = counts["firm_pass"] + counts["flip_pass"] + counts["flip_fail"] + counts["firm_fail"]
    return {
        "n_limitup_rows": total,
        "bands": counts,
        "flip_share_of_decided_pct": (
            round(100.0 * (counts["flip_pass"] + counts["flip_fail"]) / max(1, decided), 2)
        ),
        "pass_side_flip_share_pct": (
            round(100.0 * counts["flip_pass"] / max(1, counts["firm_pass"] + counts["flip_pass"]), 2)
        ),
        "sensitivity_note": (
            "若翻转带判决全部翻转: c3 通过人群 n 变化 = +flip_fail − flip_pass "
            f"({counts['flip_fail']:+d} / −{counts['flip_pass']}) — 方向性披露, 不做推断"
        ),
    }


def render_md(payload: Mapping[str, Any]) -> str:
    lines = [
        "# c3 行业门舍入翻转带量化 (预注册带宽)",
        "",
        f"带宽 (冻结): flip_pass = 发布值 2.00 · flip_fail = 1.99 · firm_pass ≥ 2.01 · 阈值 {C3_THRESHOLD}%",
        "发布量子 0.01 (sw_daily pct_change 2 位小数); 源数据 ±半量子差异即翻转边际判决。",
        "",
        "## ① 事件侧 (court 事件, 全部通过 c3)",
        "",
        "| 带 | n | 净E% | 胜率% |",
        "|---|---|---|---|",
    ]
    e = payload["event_side"]
    for key in ("firm_pass", "flip_pass", "other"):
        lines.append(f"| {key} | {e[key]['n']} | {e[key].get('mean_net_e_pct', '—')} | {e[key].get('win_rate_pct', '—')} |")
    lines += [
        "",
        f"flip_pass 占事件比: **{e['flip_pass_share_pct']}%**",
        "",
        "## ② 预筛侧 (面板涨停票, 不跑 detect)",
        "",
        f"涨停行 n={payload['prescreen_side']['n_limitup_rows']}",
        "",
        "| 带 | n |",
        "|---|---|",
    ]
    for band, count in payload["prescreen_side"]["bands"].items():
        lines.append(f"| {band} | {count} |")
    p = payload["prescreen_side"]
    lines += [
        "",
        f"翻转带占已判决比: **{p['flip_share_of_decided_pct']}%** · 通过侧翻转占比: **{p['pass_side_flip_share_pct']}%**",
        "",
        p["sensitivity_note"],
        "",
        "## 判读框架 (预注册)",
        "",
        f"- 翻转带占比 <2%: 脚注级, 无行动必要",
        "- 2%~5%: 值得 owner 讨论滞后带 (如 2.0±0.05 双阈值) 或精度源",
        "- >5%: c3 判决实质上部分由舍入噪声驱动, 修门讨论应提级",
        "",
        "## 纪律",
        "",
        "- 纯诊断 (宪法 #2); 修门 = 参数变化 = owner 决策 + 新证据世代",
        "- 行业值复算与 court build 同源 (industry_of + load_industry_day_pct)",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)

    import sys

    sys.path.insert(0, "scripts")
    from btst_court_build import industry_of, load_panel, load_sw_industry
    from setup_research import load_industry_day_pct

    sw = load_sw_industry(args.raw_dir)
    sw_rows: dict[str, list] = {}
    for row in sw.itertuples(index=False):
        sw_rows.setdefault(row[0], []).append((row[1], row[2], row[3]))
    industry_day_pct = load_industry_day_pct()

    def industry_pct_of(symbol: str, day: str) -> float | None:
        name = industry_of(sw_rows, symbol, day)
        return industry_day_pct.get((name, day)) if name else None

    events = pd.read_csv(args.court_table)
    panel = load_panel(args.raw_dir)

    payload = {
        "bands_pregistered": {
            "flip_pass": "== 2.00", "flip_fail": "== 1.99", "firm_pass": ">= 2.01", "threshold": C3_THRESHOLD,
        },
        "event_side": event_side(events, industry_pct_of),
        "prescreen_side": prescreen_side(panel, industry_pct_of),
        "discipline": [
            "纯诊断 (宪法 #2); 修门 = owner 决策",
            "带宽预注册冻结; 行业值复算同源 court build",
        ],
    }

    from datetime import date

    stamp = date.today().strftime("%Y%m%d")
    out_json = REPORTS_DIR / f"c3_flip_band_{stamp}.json"
    out_md = REPORTS_DIR / f"c3_flip_band_{stamp}.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({"flip_pass_share_pct": payload["event_side"]["flip_pass_share_pct"], "prescreen": payload["prescreen_side"]["bands"]}, ensure_ascii=False))
    print(f"written: {out_json} / {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
