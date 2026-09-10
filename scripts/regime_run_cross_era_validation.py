"""R168 d1_run 决定性对比的跨时代外部验证 (R178 Op1, 纯诊断).

动机: R168 的决定性对比 (d1_blip +1.77% vs d1_run −5.74%, 配对差 CI90
[+2.49%,+11.94%] 越零) 建在单一时代 (court 当前窗口 2025-07 起) 上,
R170 已诚实降格其时序识别力 (placebo 循环移位 p=0.148 未越 p95) —
「决定性」是样本内幅度, 不是跨时代结构。早期窗口事件表
(data/research/btst_court/event_tables_early/, 20220104-20241231, 同公式
指纹逐字一致, regime 轴同源) 提供独立时代的外部验证样本: Observe 探针
(宿主真实数据, R168 analyze 单一实现直跑早期表) 实证 d1 罚分不复制的
迹象且罚分移位 d3p — 本工具把该验证形态化: 双表分析 + 判定谓词 +
阻断结构语境 + 混杂披露, 产出可重验的证据状态更新。

Observe 期真实数据快查实证 (20260911, 生产对齐): 当前时代 d1_run 罚分
−7.51pp (CI90 [+2.49%,+11.94%]); 早期时代 d1_blip +5.31% (n=1082) vs
d1_run +4.59% (n=919), 配对差 CI [−7.87%,+6.78%] 跨零, split-half 跨半
翻转; d3p_run −4.32% (n=322) 配对 CI [−0.25%,+8.69%] 贴零。唯一已记录
混杂 = 幸存者偏差方向性 (早期宇宙缺退市票, 偏差不成比例落在危机后组 →
早期 d1_run 读数乐观, 不复制≠决定性反证)。

判定谓词 (预注册, 机械):
- d1_penalty_sign_consistent: 两时代 d1_run_vs_blip 配对差 CI 下界同 > 0
  (正 = run 罚分, R168 grouped_delta 方向语义);
- early_ci_excludes_current_point: 早期区间整体不覆盖当前时代点罚分
  (blip E − run E) — 「早期数据能否排除当前量级」的机械读数;
- verdict: 三形态装配 (独立时代支持 / 仅当前时代 / 不可判定), CI 缺失
  (n<MIN_CELL_N) 走诚实路径, 不冒充判定。

纪律 (宪法 #2):
- 纯诊断披露 — 本工具不判定 d1_run 规则, 只回答『R168 d1 边界是否可
  外推到独立时代』; 任何据此的策略变化 = 新证据世代 owner 决策 (预注册
  champion/challenger)。
- 时代分析 100% 委托 R168 analyze 单一实现 (production_aligned / 分组
  表 / 配对 CI / split-half / label 一致性 / 强度交叉全部内含), 本模块
  零统计 fork; 唯一新增算术 = 阻断段结构直方图 (描述性语境, 非决策轴;
  run_geometry 对 blocked 日本身返回 run=0, 段长度语境需独立 8 行遍历)。
- 一次性 owner 触发工件, 不进夜刷链 (早期侧冻结, 数字不随新数据变化;
  当前时代侧刷新时 owner 重跑本工具即可)。
- fixture 驱动测试 slot 自足 (R10 纪律); 真实数据重跑作为宿主侧证据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.regime_proximity_conditioning import (
    COURT_TABLE_DEFAULT,
    REGIME_HISTORY_DEFAULT,
    REPORT_DIR_DEFAULT,
    load_regime_history,
)
from scripts.regime_blocked_run_conditioning import (
    RegimeBlockedRunError,
    analyze,
)

REPORT_STEM = "regime_run_cross_era_validation"

CURRENT_MANIFEST_DEFAULT = Path(
    "data/research/btst_court/event_tables/manifest_v1.json"
)
EARLY_TABLE_DEFAULT = Path(
    "data/research/btst_court/event_tables_early/event_table_v1.csv.gz"
)
EARLY_MANIFEST_DEFAULT = Path(
    "data/research/btst_court/event_tables_early/manifest_v1.json"
)

_CROSS_GROUPS: tuple[str, ...] = (
    "d1_blip",
    "d1_run",
    "d2_run",
    "d3p_run",
)

# 混杂披露 (静态结构化; 数字面如 label 一致性逐时代动态附入)
CONFOUNDS: dict[str, dict[str, str]] = {
    "survivorship_direction": {
        "finding": (
            "早期宇宙为存活交集子集 (缺退市票); 退市票的灾难结局不成比例"
            "集中在危机后入场组 (d1_run/d3p_run)"
        ),
        "implication": (
            "早期 d1_run 读数系统性乐观 — 『早期未复制 d1 罚分』不是决定性"
            "反证; 但若罚分在乐观偏差下仍复制则为保守强证据"
        ),
    },
    "partial_universe": {
        "finding": "早期表为部分宇宙重建 (fund_flow/price 交集), 非全市场",
        "implication": "组级 n 与构成和当前时代不严格可比, 差异方向不可归因",
    },
    "era_label_volatility": {
        "finding": (
            "2022-24 阻断日频率与连跑结构和当前时代相近 (见 era_structure), "
            "轴算术相同 (同一 run_geometry 单一实现)"
        ),
        "implication": (
            "d1 边界语义在两时代同构 — 观察到的差异是市场行为差异而非定义"
            "伪影 (幸存者偏差混杂仍独立成立)"
        ),
    },
}

DISCIPLINE: dict[str, str] = {
    "scope": (
        "本工具只回答『R168 d1 边界是否可外推到独立时代』, 不判定 d1_run "
        "重入规则; 任何策略变化 = 新证据世代 owner 决策 (宪法 #2)"
    ),
    "direction_semantics": (
        "run_deltas 正值 = run 罚分 (hi=blip 基线, lo=run 对照 — R168 "
        "grouped_delta 语义逐字继承)"
    ),
    "one_shot": (
        "早期侧冻结 (20220104-20241231), 数字不随新数据变化; 当前时代侧"
        "刷新后 owner 重跑本工具刷新对比"
    ),
    "verdict_semantics": (
        "CI 重叠/排除是描述性读数不是假设检验; split-half 与 R170 placebo "
        "面的时序脆弱性结论不受本工具影响"
    ),
}


class RegimeRunCrossEraValidationError(SystemExit):
    """输入缺失/畸形 — typed fail-closed, 绝不产空报告冒充成功."""


def load_manifest_fingerprint(path: Path) -> dict[str, str]:
    """manifest → formula_fingerprint (缺失/畸形 typed 拒绝)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RegimeRunCrossEraValidationError(
            f"manifest_unreadable: {path}: {exc}"
        ) from exc
    fp = raw.get("formula_fingerprint") if isinstance(raw, dict) else None
    if not isinstance(fp, dict) or not fp:
        raise RegimeRunCrossEraValidationError(
            f"manifest_fingerprint_missing: {path}"
        )
    for key, value in fp.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            raise RegimeRunCrossEraValidationError(
                f"manifest_fingerprint_malformed: {path}: {key!r}"
            )
    return dict(fp)


def blocked_run_length_histogram(
    history_path: Path, start: str, end: str
) -> dict[str, object]:
    """窗口内连续阻断段长度直方图 (描述性语境, 非 R168 决策轴).

    run_geometry 对 blocked 日本身返回 run=0 (run 语义挂在后随 normal 日),
    段长度语境需独立遍历: 按会话序累计连续阻断段, 段被打断或窗口结束即
    计一段。窗口起点/终点截断的段按窗内长度计入 (右删失下界 — 真段可能
    更长, 与 R169 run_censoring 同款披露纪律)。
    """
    sessions, labels = load_regime_history(history_path)
    window = [s for s in sessions if start <= s <= end]
    hist: dict[str, int] = {}
    blocked_days = 0
    current = 0
    for s in window:
        label = labels.get(s, "")
        if label in ("crisis", "risk_off"):
            blocked_days += 1
            current += 1
        elif current:
            key = str(current)
            hist[key] = hist.get(key, 0) + 1
            current = 0
    if current:
        key = str(current)
        hist[key] = hist.get(key, 0) + 1
    runs_total = sum(hist.values())
    runs_ge2 = sum(n for length, n in hist.items() if int(length) >= 2)
    return {
        "sessions": len(window),
        "blocked_days": blocked_days,
        "blocked_freq": (blocked_days / len(window)) if window else 0.0,
        "run_length_hist": dict(sorted(hist.items(), key=lambda kv: int(kv[0]))),
        "runs_total": runs_total,
        "runs_ge2": runs_ge2,
        "censoring": "窗口起点/终点截断的段按窗内长度计入 (右删失下界)",
    }


def _group_table_subset(table: dict[str, object]) -> dict[str, object]:
    """t10 组表 → 跨时代并排所需字段 (n/expectancy/winrate)."""
    out: dict[str, object] = {}
    for group in _CROSS_GROUPS:
        row = table.get(group) or {}
        out[group] = {
            "n": row.get("n"),
            "expectancy": row.get("expectancy"),
            "winrate": row.get("winrate"),
        }
    return out


def _point_penalty(table: dict[str, object]) -> float | None:
    """d1 点罚分 = E(d1_blip) − E(d1_run) (None 任一侧 → None)."""
    blip = (table.get("d1_blip") or {}).get("expectancy")
    run = (table.get("d1_run") or {}).get("expectancy")
    if blip is None or run is None:
        return None
    return float(blip) - float(run)


def _era_view(ev: pd.DataFrame, history_path: Path) -> dict[str, object]:
    """单时代分析 — 100% 委托 R168 analyze 单一实现 (零统计 fork)."""
    payload = analyze(ev, history_path)
    t10 = payload["tables"]["t10"]
    return {
        "aligned_n": payload["aligned_n"],
        "court_window": payload["court_window"],
        "group_table": _group_table_subset(t10),
        "run_deltas_t10": payload["run_deltas_t10"],
        "split_half_d1": payload["split_half_d1"],
        "label_consistency": payload["label_consistency"],
    }


def _verdict(eras: dict[str, object], points: dict[str, float | None]) -> dict[str, object]:
    """判定谓词 + 陈述装配 (机械; CI 缺失走诚实不可判定路径)."""
    cur = (eras["current"].get("run_deltas_t10") or {}).get("d1_run_vs_blip") or {}
    early = (eras["early"].get("run_deltas_t10") or {}).get("d1_run_vs_blip") or {}
    cur_low, early_low = cur.get("ci_low"), early.get("ci_low")

    def _positive(value: object) -> bool:
        return value is not None and float(value) > 0

    sign_consistent = _positive(cur_low) and _positive(early_low)

    cur_point = points.get("current")
    early_ci = (early.get("ci_low"), early.get("ci_high"))
    if cur_point is None or early_ci[0] is None or early_ci[1] is None:
        excludes: bool | None = None
    else:
        excludes = early_ci[0] > cur_point or early_ci[1] < cur_point

    if cur_low is None or early_low is None:
        statement = "不可判定 (任一侧组 n<MIN_CELL_N, 配对区间缺失 — 不冒充判定)"
    elif sign_consistent:
        statement = (
            "两时代 d1 罚分方向一致 (CI 下界同越零) — R168 d1 边界获独立"
            "时代支持"
        )
    elif _positive(cur_low):
        statement = (
            "d1 罚分仅当前时代可检 (早期 CI 跨零) — R168 d1 边界为时代条件"
            "证据, 不可单独据以外推"
        )
        if excludes:
            statement += (
                "; 早期区间已排除当前观测量级 (机械读数 — 幸存者偏差使早期"
                "罚分向零偏, 见混杂披露, 不构成反证)"
            )
        else:
            statement += (
                "; 但早期区间较宽, 不能排除当前时代量级 (幸存者偏差混杂下"
                "不复制≠决定性反证)"
            )
    else:
        statement = "两时代均未检出 d1 罚分 (CI 下界均未越零)"

    return {
        "d1_penalty_sign_consistent": sign_consistent,
        "early_ci_excludes_current_point": excludes,
        "statement": statement,
    }


def cross_era_payload(
    current_ev: pd.DataFrame,
    early_ev: pd.DataFrame,
    history_path: Path,
    current_manifest: Path,
    early_manifest: Path,
) -> dict[str, object]:
    """装配跨时代 payload (纯函数; 指纹漂移 fail-closed)."""
    current_fp = load_manifest_fingerprint(current_manifest)
    early_fp = load_manifest_fingerprint(early_manifest)
    if current_fp != early_fp:
        raise RegimeRunCrossEraValidationError(
            "formula_fingerprint_mismatch: 两表公式指纹不一致, 不可比 — "
            f"current={sorted(current_fp.items())} early={sorted(early_fp.items())}"
        )
    eras = {
        "current": _era_view(current_ev, history_path),
        "early": _era_view(early_ev, history_path),
    }
    points = {
        "current": _point_penalty(eras["current"]["group_table"]),
        "early": _point_penalty(eras["early"]["group_table"]),
    }
    windows = {
        name: era["court_window"] or {}
        for name, era in eras.items()
    }
    era_structure = {}
    for name in ("current", "early"):
        window = windows[name] or {}
        start, end = window.get("start"), window.get("end")
        if start and end:
            era_structure[name] = blocked_run_length_histogram(
                history_path, start, end
            )
    payload: dict[str, object] = {
        "schema_version": 1,
        "formula_fingerprints": {
            "current": current_fp,
            "early": early_fp,
            "identical": True,
        },
        "eras": eras,
        "d1_point_penalty": points,
        "verdict": _verdict(eras, points),
        "era_structure": era_structure,
        "confounds": CONFOUNDS,
        "discipline": DISCIPLINE,
    }
    return payload


def _fmt(v: object, pct: bool = True) -> str:
    """R168 _fmt 同款显示家族 (None/NaN → '—'; pct → 百分号两位小数)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if pct:
        return f"{float(v) * 100:+.2f}%"
    return str(v)


def render_md(payload: dict[str, object], date_str: str) -> str:
    """Markdown 渲染 (缺键存活 — R158 家族; 判读纪律节固定成文)."""
    lines: list[str] = []
    lines.append(f"# R168 d1_run 对比跨时代外部验证 — {date_str}")
    lines.append("")
    lines.append("## 判定 (机械谓词装配)")
    lines.append("")
    verdict = payload.get("verdict") or {}
    lines.append(f"- statement: {verdict.get('statement') or '—'}")
    lines.append(
        f"- d1_penalty_sign_consistent: "
        f"{verdict.get('d1_penalty_sign_consistent') if verdict.get('d1_penalty_sign_consistent') is not None else '—'}"
    )
    lines.append(
        f"- early_ci_excludes_current_point: "
        f"{verdict.get('early_ci_excludes_current_point') if verdict.get('early_ci_excludes_current_point') is not None else '—'}"
    )
    lines.append("")
    points = payload.get("d1_point_penalty") or {}
    lines.append("## d1 点罚分 (E[blip] − E[run], 正 = run 罚分)")
    lines.append("")
    lines.append("| 时代 | 点罚分 |")
    lines.append("|---|---|")
    for name in ("current", "early"):
        lines.append(f"| {name} | {_fmt(points.get(name))} |")
    lines.append("")
    lines.append("## 组表并排 (t10, 生产对齐)")
    lines.append("")
    eras = payload.get("eras") or {}
    lines.append("| 组 | current n | current E | current 胜率 | early n | early E | early 胜率 |")
    lines.append("|---|---|---|---|---|---|---|")
    cur_table = (eras.get("current") or {}).get("group_table") or {}
    early_table = (eras.get("early") or {}).get("group_table") or {}
    extras = sorted((set(cur_table) | set(early_table)) - set(_CROSS_GROUPS))
    groups = [g for g in _CROSS_GROUPS if g in cur_table or early_table] + extras
    if not groups:
        groups = ["(缺组表)"]
    for group in groups:
        c = cur_table.get(group) or {}
        e = early_table.get(group) or {}
        lines.append(
            f"| {group} | {c.get('n') if c.get('n') is not None else '—'} "
            f"| {_fmt(c.get('expectancy'))} | {_fmt(c.get('winrate'))} "
            f"| {e.get('n') if e.get('n') is not None else '—'} "
            f"| {_fmt(e.get('expectancy'))} | {_fmt(e.get('winrate'))} |"
        )
    lines.append("")
    lines.append("## 配对差 CI 并排 (t10, 正 = run 罚分)")
    lines.append("")
    lines.append("| 对比 | current CI90 | early CI90 |")
    lines.append("|---|---|---|")
    for key in ("d1_run_vs_blip", "d2_run_vs_blip", "d3p_run_vs_blip"):
        c = ((eras.get("current") or {}).get("run_deltas_t10") or {}).get(key) or {}
        e = ((eras.get("early") or {}).get("run_deltas_t10") or {}).get(key) or {}
        c_lo, c_hi = c.get("ci_low"), c.get("ci_high")
        e_lo, e_hi = e.get("ci_low"), e.get("ci_high")
        c_txt = (
            f"[{_fmt(c_lo)}, {_fmt(c_hi)}]"
            if c_lo is not None and c_hi is not None
            else "—"
        )
        e_txt = (
            f"[{_fmt(e_lo)}, {_fmt(e_hi)}]"
            if e_lo is not None and e_hi is not None
            else "—"
        )
        lines.append(f"| {key} | {c_txt} | {e_txt} |")
    lines.append("")
    era_structure = payload.get("era_structure")
    lines.append("## 时代阻断结构 (描述性语境)")
    lines.append("")
    if not era_structure:
        lines.append("| (缺 era_structure) | — | — | — | — | — |")
    else:
        lines.append("| 时代 | sessions | blocked_days | freq | 段直方图 | runs≥2 |")
        lines.append("|---|---|---|---|---|---|")
        for name in ("current", "early"):
            st = era_structure.get(name) or {}
            hist = st.get("run_length_hist") or {}
            hist_txt = (
                ", ".join(f"len={k}×{v}" for k, v in hist.items()) if hist else "—"
            )
            lines.append(
                f"| {name} | {st.get('sessions') if st.get('sessions') is not None else '—'} "
                f"| {st.get('blocked_days') if st.get('blocked_days') is not None else '—'} "
                f"| {_fmt(st.get('blocked_freq'))} | {hist_txt} "
                f"| {st.get('runs_ge2') if st.get('runs_ge2') is not None else '—'} |"
            )
    lines.append("")
    confounds = payload.get("confounds")
    lines.append("## 混杂披露 (判读前必读)")
    lines.append("")
    if not confounds:
        lines.append("(缺 confounds)")
    else:
        for key, item in confounds.items():
            lines.append(f"- **{key}**: {item.get('finding', '—')}")
            lines.append(f"  - 含义: {item.get('implication', '—')}")
    lines.append("")
    discipline = payload.get("discipline") or {}
    if discipline:
        lines.append("## 纪律")
        lines.append("")
        for key, text in discipline.items():
            lines.append(f"- {text}")
        lines.append("")
    fps = payload.get("formula_fingerprints") or {}
    lines.append(
        f"公式指纹一致性: {fps.get('identical') if fps else '—'} "
        f"(两表 manifest formula_fingerprint 逐字段比对, 不一致即 typed 拒绝)"
    )
    lines.append("")
    return "\n".join(lines)


def _attach_digest(
    payload: dict[str, object],
    current_table: Path,
    early_table: Path,
    current_rows: int,
    early_rows: int,
) -> None:
    """双表内容指纹 + 行数 (R141 数据内容证据家族)."""

    def _file_digest(path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    payload["digest"] = {
        "current_table": _file_digest(current_table),
        "early_table": _file_digest(early_table),
        "current_rows": current_rows,
        "early_rows": early_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="R168 d1_run 对比跨时代外部验证 (纯诊断)"
    )
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_DEFAULT)
    parser.add_argument("--early-court-table", type=Path, default=EARLY_TABLE_DEFAULT)
    parser.add_argument("--regime-history", type=Path, default=REGIME_HISTORY_DEFAULT)
    parser.add_argument(
        "--current-manifest", type=Path, default=CURRENT_MANIFEST_DEFAULT
    )
    parser.add_argument(
        "--early-manifest", type=Path, default=EARLY_MANIFEST_DEFAULT
    )
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR_DEFAULT)
    parser.add_argument("--date", type=str, default=None, help="报告日期标签 (默认今日; 测试注入)")
    args = parser.parse_args(argv)

    for label, path in (
        ("court_table", args.court_table),
        ("early_court_table", args.early_court_table),
        ("regime_history", args.regime_history),
        ("current_manifest", args.current_manifest),
        ("early_manifest", args.early_manifest),
    ):
        if not path.exists():
            raise RegimeRunCrossEraValidationError(f"{label}_missing: {path}")

    current_ev = pd.read_csv(args.court_table)
    early_ev = pd.read_csv(args.early_court_table)
    payload = cross_era_payload(
        current_ev,
        early_ev,
        args.regime_history,
        args.current_manifest,
        args.early_manifest,
    )
    date_str = args.date or date.today().strftime("%Y%m%d")
    payload["report_date"] = date_str
    _attach_digest(
        payload,
        args.court_table,
        args.early_court_table,
        int(len(current_ev)),
        int(len(early_ev)),
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    md_path = args.out_dir / f"{REPORT_STEM}_{date_str}.md"
    json_path = args.out_dir / f"{REPORT_STEM}_{date_str}.json"
    md_path.write_text(render_md(payload, date_str), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str),
        encoding="utf-8",
    )
    verdict = payload.get("verdict") or {}
    points = payload.get("d1_point_penalty") or {}
    print(
        f"{REPORT_STEM}: cur_penalty={_fmt(points.get('current'))} "
        f"early_penalty={_fmt(points.get('early'))} · "
        f"sign_consistent={verdict.get('d1_penalty_sign_consistent')} · "
        f"{verdict.get('statement')} → {md_path}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
