"""BTST 先验漂移决策包 — 生产先验 vs 重建后 court 的三面对照 (纯诊断).

第一性原理: 生产 Kelly 先验 (known_distributions) 钉在 2026-08-19/22 世代的
旧 court (T+10 E=+0.56%, n=1464); R96 重建 (regime 空窗补全, +80 七月事件)
后证据基座变为 production_aligned E≈+0.015% (n=1618) — 相对高估 ~37×,
但 recheck 哨点 (±1pp) 仍绿 (er_delta +0.55pp 过半带)。本工具给 owner 决策包:

  ① 字段对照 — 新旧先验逐字段 (n/胜率/avg_gain/avg_loss/E/CI), T+10 与 T+8;
  ② Kelly 影响 — src.kelly_fraction 纯函数喂新旧先验; 若 f* 均低于 10%
     单票 cap (R15 已证 cap 是绑定约束), 漂移是披露级而非仓位级;
  ③ 日度选择贡献 — top_1 (每日最高强度) vs 全体对齐的 n/E/NAV 落差 —
     先验消费口径的语义差 (全体宇宙 vs 实际持仓选择)。

决策两选项 (工具不替 owner 决定):
  A. 现在重校准 — 新证据世代 (2026-08-19 先例: owner 批准 + provenance 更新);
  B. 等待 — 预注册触发器 conjunction / 官方前向 trial 积累后再校准。

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2); 先验重校准 = owner 决策 + 新证据世代。
  - 口径复用 review_btst_prior_court 单一实现 (candidate_universe /
    production_universe / net_ret / prior_snapshot — import 不复制)。
  - 确定性: 同输入逐字节同输出 (无 RNG; CI 直接引用 recheck 可复验值时标注)。

用法:
    uv run python scripts/btst_prior_drift_pack.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

COURT_TABLE = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
REPORTS_DIR = Path("data/reports")
PER_SETUP_CAP = 0.10  # per-setup 单票 cap (daily_action._SETUP_POSITION_CAPS btst=0.10)
HORIZON_COLS = {8: "gross_ret_t8", 10: "gross_ret_t10"}


def prior_constant(horizon: int) -> Any:
    from src.screening.offensive.known_distributions import BTST_BREAKOUT_T10, BTST_BREAKOUT_T8

    return {8: BTST_BREAKOUT_T8, 10: BTST_BREAKOUT_T10}[horizon]


def prior_fields(horizon: int) -> dict[str, Any]:
    d = prior_constant(horizon)
    return {
        "n": d.n,
        "winrate": d.winrate,
        "avg_gain": d.avg_gain,
        "avg_loss": d.avg_loss,
        "expected_return": d.expected_return,
        "ci_low": d.ci_low,
        "ci_high": d.ci_high,
        "provenance": d.provenance,
    }


def rebuilt_stats(universe: pd.DataFrame, horizon: int) -> dict[str, Any]:
    """重建后 court 的生产对齐口径 (net = gross − 往返成本, review 同式)."""
    from scripts.review_btst_prior_court import net_ret

    col = HORIZON_COLS[horizon]
    net = net_ret(universe[col].dropna())
    return {
        "n": int(net.size),
        "winrate": round(float((net > 0).mean()), 4) if net.size else None,
        "avg_gain": round(float(net[net > 0].mean()), 4) if (net > 0).any() else None,
        "avg_loss": round(float(net[net <= 0].mean()), 4) if (net <= 0).any() else None,
        "expected_return": round(float(net.mean()), 4) if net.size else None,
    }


def kelly_view(prior: Mapping[str, Any], rebuilt: Mapping[str, Any]) -> dict[str, Any]:
    """新旧先验的 full Kelly 对照 + cap 关系 (复用 src.kelly_fraction 纯函数)."""
    from src.screening.offensive.kelly import kelly_fraction

    def _f(stats: Mapping[str, Any]) -> float | None:
        if stats.get("winrate") is None or stats.get("avg_gain") is None or stats.get("avg_loss") is None:
            return None
        return kelly_fraction(float(stats["winrate"]), float(stats["avg_gain"]), float(stats["avg_loss"]))

    return {
        "prior_full_kelly": _f(prior),
        "rebuilt_full_kelly": _f(rebuilt),
        "per_setup_cap": PER_SETUP_CAP,
        "cap_binding_note": "若两侧 f* 均低于 cap, 漂移是披露级而非仓位级 (R15: cap 是现体系绑定约束)",
    }


def top1_view(universe: pd.DataFrame, horizon: int) -> dict[str, Any]:
    """每日按强度取前 1 笔的净口径视图 — 复用 review_btst_prior_court.daily_topk
    单一实现 (k=1; NAV 为日组合均值复合, 诊断口径非回测 — 见其 docstring)."""
    from scripts.review_btst_prior_court import daily_topk

    view = daily_topk(universe, k=1)
    keep = ("trade_mean", "winrate", "nav_compound")
    out = {"n_days": int(view.get("days", 0))}
    for key in keep:
        value = view.get(key)
        out[key] = round(float(value), 4) if isinstance(value, (int, float)) else value
    return out


def build_payload(universe: pd.DataFrame) -> dict[str, Any]:
    horizons = {}
    for horizon in (10, 8):
        prior = prior_fields(horizon)
        rebuilt = rebuilt_stats(universe, horizon)
        horizons[f"t{horizon}"] = {
            "prior": prior,
            "rebuilt": rebuilt,
            "er_delta_pp": (
                round((rebuilt["expected_return"] - prior["expected_return"]) * 100.0, 2)
                if rebuilt["expected_return"] is not None
                else None
            ),
            "kelly": kelly_view(prior, rebuilt),
        }
    return {
        "horizons": horizons,
        "selection_view": {
            "top_1_t10": top1_view(universe, 10),
            "aligned_all_t10": horizons["t10"]["rebuilt"],
            "note": "top_1 vs 全体的落差 = 日度选择贡献; 先验消费口径的语义差需在重校准讨论中显式选择; 本视图喂生产对齐宇宙 (review --check 的 top_1 喂候选宇宙, 数字因此略异 — 复用 daily_topk 单一实现, 输入宇宙是显式选择)",
        },
        "sentinel_status": "recheck --check 哨点 ±1pp 仍绿; er_delta +0.55pp 已过半带 — 如实呈现",
        "options": [
            "A. 现在重校准 — 新证据世代 (2026-08-19 先例: owner 批准 + provenance 更新)",
            "B. 等待 — 预注册触发器 conjunction / 官方前向 trial 积累后再校准",
        ],
        "discipline": [
            "纯诊断 (宪法 #2); 先验重校准 = owner 决策 + 新证据世代",
            "口径复用 review_btst_prior_court 单一实现; Kelly 复用 src.kelly_fraction",
        ],
    }


def render_md(payload: Mapping[str, Any]) -> str:
    lines = [
        "# BTST 先验漂移决策包 (生产先验 vs 重建后 court)",
        "",
        "哨点状态: " + payload["sentinel_status"],
        "",
    ]
    for key in ("t10", "t8"):
        h = payload["horizons"][key]
        lines += [
            f"## {key} 字段对照",
            "",
            "| 字段 | 生产先验 (committed) | 重建后 court |",
            "|---|---|---|",
        ]
        for field in ("n", "winrate", "avg_gain", "avg_loss", "expected_return"):
            lines.append(f"| {field} | {h['prior'][field]} | {h['rebuilt'][field]} |")
        lines += [
            "",
            f"E 漂移: **{h['er_delta_pp']}pp** · full Kelly: 先验 {h['kelly']['prior_full_kelly']}"
            f" vs 重建 {h['kelly']['rebuilt_full_kelly']} (cap {h['kelly']['per_setup_cap']})",
            "",
        ]
    sel = payload["selection_view"]
    lines += [
        "## 日度选择贡献 (t10)",
        "",
        f"top_1: n={sel['top_1_t10'].get('n_days')} 日 · E={sel['top_1_t10'].get('trade_mean')}"
        f" · NAV={sel['top_1_t10'].get('nav_compound')}",
        f"全体对齐: n={sel['aligned_all_t10'].get('n')} · E={sel['aligned_all_t10'].get('expected_return')}",
        "",
        sel["note"],
        "",
        "## 决策选项 (owner)",
        "",
    ]
    lines += [f"- {opt}" for opt in payload["options"]]
    lines += ["", "## 纪律", ""]
    lines += [f"- {d}" for d in payload["discipline"]]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE)
    args = parser.parse_args(argv)

    from scripts.review_btst_prior_court import candidate_universe, production_universe

    events = pd.read_csv(args.court_table)
    universe = production_universe(candidate_universe(events))
    payload = build_payload(universe)

    from datetime import date

    stamp = date.today().strftime("%Y%m%d")
    out_json = REPORTS_DIR / f"prior_drift_pack_{stamp}.json"
    out_md = REPORTS_DIR / f"prior_drift_pack_{stamp}.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({k: v["er_delta_pp"] for k, v in payload["horizons"].items()}, ensure_ascii=False))
    print(f"written: {out_json} / {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
