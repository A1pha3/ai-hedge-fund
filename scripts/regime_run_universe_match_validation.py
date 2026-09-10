"""R168 d1_run 对比时代条件性的宇宙构成判别探针 (R179 Op1).

R178 跨时代外部验证判定: d1 罚分仅当前时代可检 (早期 CI 跨零), R168
d1 边界为时代条件证据 — 但「时代差」本身有两个候选机制未分: (a) 宇宙
构成差 (早期表为 fund_flow/price 交集部分宇宙, 票集与当前全宇宙不同),
(b) 时代行为差异或早期侧幸存者缺失。本工具收口第一轴: 把当前时代事件
表限制到早期表 symbol 全集 S (构成匹配视图), 用同一条 R168 d1 轴重跑 —
罚分若在匹配视图上仍可检 (配对 CI 下界越零), 构成轴排除; 若消失, R168
边界为宇宙条件证据。
钉死的正确性面:
- 三视图 (current_full / current_matched / early) 100% 委托 R168 analyze
  单一实现 — 经 R178 _era_view/_point_penalty 复用 (import 身份断言钉住,
  零统计 fork);
- 判定谓词机械: matched_penalty_preserved (匹配视图 CI 下界越零) /
  composition_explains_gap (全宇宙可检而匹配视图不可检) / 不可判定形态
  (匹配视图组 n<MIN_CELL_N, CI 缺失走诚实路径不冒充判定);
- 宇宙匹配统计披露 (票集/行集重合度, 匹配视图的样本基础显形);
- manifest 公式指纹一致性 fail-closed (复用 R178 load_manifest_fingerprint
  单一实现, 漂移 = 两表不可比);
- 幸存者偏差方向混杂披露 (R178 保留): 构成匹配只排除「可观测票集差」,
  不治愈早期侧缺席退市票 — 构成轴排除≠早期结论反转;
- 渲染缺键存活 (R158 家族) + 报告确定性 (R13 家族: 同输入两次调用逐字节
  同 payload)。
纪律 (宪法 #2): 纯诊断披露 — 本工具不判定 d1_run 规则, 只回答『R168 d1
边界的时代条件性是否为宇宙构成伪影』; 任何据此的策略变化 = 新证据世代
owner 决策。fixture 驱动测试 slot 自足 (R10 纪律), 不依赖 gitignored
本地资产; 真实数据重跑作为宿主侧证据。夜刷链第 9 成员 (当前侧随 court
重建每夜保鲜; 早期侧冻结, 数字不随新数据变化)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.regime_proximity_conditioning import (
    COURT_TABLE_DEFAULT,
    REGIME_HISTORY_DEFAULT,
    REPORT_DIR_DEFAULT,
)
from scripts.regime_run_cross_era_validation import (
    CURRENT_MANIFEST_DEFAULT,
    EARLY_MANIFEST_DEFAULT,
    EARLY_TABLE_DEFAULT,
    RegimeRunCrossEraValidationError,
    _era_view,
    _point_penalty,
    load_manifest_fingerprint,
)

REPORT_STEM = "regime_run_universe_match_validation"

_ERA_KEYS: tuple[str, ...] = ("current_full", "current_matched", "early")
_MATCH_GROUPS: tuple[str, ...] = ("d1_blip", "d1_run")

# 混杂披露 (构成轴只排除「可观测票集差」, 两类残余解释如实成文)
CONFOUNDS: dict[str, dict[str, str]] = {
    "survivorship_direction": {
        "finding": (
            "构成匹配不治愈早期侧幸存者缺失 — 早期宇宙缺退市票, 灾难结局"
            "不成比例集中在危机后入场组, 早期 d1_run 读数系统性乐观"
        ),
        "implication": (
            "『构成不解释时代差』把解释权推给 (时代行为差异 + 早期侧缺席)"
            "二元, 不在两者间判定; 构成轴排除≠R178 时代条件性结论反转"
        ),
    },
    "composition_proxy": {
        "finding": (
            "S = 早期表信号日出现过的 symbol 全集, 是交集宇宙的可观测代理"
            " (零信号票不可见); 匹配视图行集随当前窗口移动"
        ),
        "implication": (
            "匹配视图是当前时代在 S 上的条件分布, 不是早期时代的反事实;"
            "票在两时代的基本面构成亦可漂移"
        ),
    },
}

DISCIPLINE: dict[str, str] = {
    "scope": (
        "本工具只回答『R168 d1 边界的时代条件性是否为宇宙构成伪影』, 不"
        "判定 d1_run 重入规则; 任何策略变化 = 新证据世代 owner 决策 (宪法 #2)"
    ),
    "direction_semantics": (
        "run_deltas 正值 = run 罚分 (hi=blip 基线, lo=run 对照 — R168 "
        "grouped_delta 语义逐字继承); 点罚分 = E[blip] − E[run]"
    ),
    "verdict_semantics": (
        "CI 下界越零是描述性读数不是假设检验; R170 placebo 面的时序脆弱性"
        "结论不受本工具影响"
    ),
}


class RegimeRunUniverseMatchError(SystemExit):
    """输入缺失/畸形 — typed fail-closed, 绝不产空报告冒充成功."""


def _symbols(ev: pd.DataFrame, label: str) -> pd.Series:
    """事件表 → str 化 symbol 列 (缺列/全空 typed 拒绝).

    str 化保证两侧匹配与装载路径无关 (pd.read_csv 对前导零票可能推断成
    int; analyze 不消费 symbol, 此处只做集合成员资格)。
    """
    if "symbol" not in ev.columns:
        raise RegimeRunUniverseMatchError(f"{label}_symbol_column_missing")
    s = ev["symbol"].astype(str)
    if (ev["symbol"].isna()).all() or (s == "").all():
        raise RegimeRunUniverseMatchError(f"{label}_symbol_column_empty")
    return s


def universe_match_payload(
    current_ev: pd.DataFrame,
    early_ev: pd.DataFrame,
    history_path: Path,
    current_manifest: Path,
    early_manifest: Path,
) -> dict[str, object]:
    """装配宇宙构成匹配 payload (纯函数; 指纹漂移/空匹配 fail-closed)."""
    current_fp = load_manifest_fingerprint(current_manifest)
    early_fp = load_manifest_fingerprint(early_manifest)
    if current_fp != early_fp:
        raise RegimeRunUniverseMatchError(
            "formula_fingerprint_mismatch: 两表公式指纹不一致, 不可比 — "
            f"current={sorted(current_fp.items())} early={sorted(early_fp.items())}"
        )

    early_syms = _symbols(early_ev, "early")
    current_syms = _symbols(current_ev, "current")
    universe: set[str] = set(early_syms.unique())
    keep = current_syms.isin(universe)
    matched_ev = current_ev.loc[keep].copy()
    if len(matched_ev) == 0:
        raise RegimeRunUniverseMatchError(
            "matched_universe_empty: 当前表与早期票集零交集 — 构成匹配视图"
            "不可构造 (检查表装载与窗口)"
        )

    eras = {
        "current_full": _era_view(current_ev, history_path),
        "current_matched": _era_view(matched_ev, history_path),
        "early": _era_view(early_ev, history_path),
    }
    points = {name: _point_penalty(eras[name]["group_table"]) for name in _ERA_KEYS}
    verdict = _verdict(eras, points)
    payload: dict[str, object] = {
        "schema_version": 1,
        "formula_fingerprints": {
            "current": current_fp,
            "early": early_fp,
            "identical": True,
        },
        "universe_match": {
            "early_symbols": int(early_syms.nunique()),
            "current_symbols_full": int(current_syms.nunique()),
            "current_symbols_matched": int(current_syms[keep].nunique()),
            "current_rows_full": int(len(current_ev)),
            "current_rows_matched": int(len(matched_ev)),
            "matched_row_share": (
                float(keep.mean()) if len(current_ev) else None
            ),
            "matched_symbol_share": (
                float(current_syms[keep].nunique() / current_syms.nunique())
                if current_syms.nunique()
                else None
            ),
        },
        "eras": eras,
        "d1_point_penalty": points,
        "verdict": verdict,
        "confounds": CONFOUNDS,
        "discipline": DISCIPLINE,
    }
    return payload


def _verdict(
    eras: dict[str, object], points: dict[str, float | None]
) -> dict[str, object]:
    """判定谓词 + 陈述装配 (机械; CI 缺失走诚实不可判定路径)."""
    full = (eras["current_full"].get("run_deltas_t10") or {}).get("d1_run_vs_blip") or {}
    matched = (eras["current_matched"].get("run_deltas_t10") or {}).get(
        "d1_run_vs_blip"
    ) or {}
    full_low = full.get("ci_low")
    matched_low = matched.get("ci_low")

    def _positive(value: object) -> bool:
        return value is not None and float(value) > 0

    full_detectable = _positive(full_low)
    matched_preserved = _positive(matched_low)

    if not full_detectable:
        statement = (
            "当前时代全宇宙未检出 d1 罚分 (CI 下界未越零) — 无时代差可解释 "
            "(检查 R168 前提是否仍成立)"
        )
    elif matched_low is None:
        statement = (
            "不可判定 (匹配视图组 n<MIN_CELL_N, 配对区间缺失 — 不冒充判定)"
        )
    elif matched_preserved:
        statement = (
            "宇宙构成不解释时代差 — R168 d1 罚分在早期宇宙票集上复现 "
            "(匹配视图配对 CI 下界越零); 早期不复制指向时代行为差异或"
            "早期侧幸存者缺失 (构成轴排除, 见混杂披露)"
        )
    else:
        statement = (
            "宇宙构成解释时代差 — 限制到早期宇宙票集后当前时代 d1 罚分"
            "不再可检; R168 d1 边界为宇宙条件证据 (判读需结合混杂披露)"
        )

    return {
        "full_penalty_detectable": full_detectable,
        "matched_penalty_preserved": (
            matched_preserved if matched_low is not None else None
        ),
        "composition_explains_gap": (
            bool(full_detectable and not matched_preserved)
            if matched_low is not None
            else None
        ),
        "statement": statement,
    }


def _fmt(v: object, pct: bool = True) -> str:
    """R168 _fmt 同款显示家族 (None/NaN → '—'; pct → 百分号两位小数)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if pct:
        return f"{float(v) * 100:+.2f}%"
    return str(v)


def render_md(payload: dict[str, object], date_str: str) -> str:
    """Markdown 渲染 (缺键存活 — R158 家族; 判读纪律节固定成文)."""
    lines: list[str] = []
    lines.append(f"# R168 d1_run 时代条件性的宇宙构成判别 — {date_str}")
    lines.append("")
    lines.append("## 判定 (机械谓词装配)")
    lines.append("")
    verdict = payload.get("verdict") or {}
    lines.append(f"- statement: {verdict.get('statement') or '—'}")
    for key in (
        "full_penalty_detectable",
        "matched_penalty_preserved",
        "composition_explains_gap",
    ):
        value = verdict.get(key)
        lines.append(f"- {key}: {value if value is not None else '—'}")
    lines.append("")
    um = payload.get("universe_match") or {}
    lines.append("## 宇宙匹配统计 (匹配视图的样本基础)")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    for key in (
        "early_symbols",
        "current_symbols_full",
        "current_symbols_matched",
        "current_rows_full",
        "current_rows_matched",
    ):
        value = um.get(key)
        lines.append(f"| {key} | {value if value is not None else '—'} |")
    for key in ("matched_row_share", "matched_symbol_share"):
        lines.append(f"| {key} | {_fmt(um.get(key))} |")
    lines.append("")
    points = payload.get("d1_point_penalty") or {}
    lines.append("## d1 点罚分 (E[blip] − E[run], 正 = run 罚分)")
    lines.append("")
    lines.append("| 视图 | 点罚分 |")
    lines.append("|---|---|")
    for name in _ERA_KEYS:
        lines.append(f"| {name} | {_fmt(points.get(name))} |")
    lines.append("")
    lines.append("## 组表并排 (t10, 生产对齐)")
    lines.append("")
    eras = payload.get("eras") or {}
    header = "| 组 |" + "".join(f" {name} n | {name} E | {name} 胜率 |" for name in _ERA_KEYS)
    lines.append(header)
    lines.append("|---|" + "---|" * (3 * len(_ERA_KEYS)))
    tables = {
        name: (eras.get(name) or {}).get("group_table") or {} for name in _ERA_KEYS
    }
    groups = [
        g
        for g in _MATCH_GROUPS
        if any(g in tables[name] for name in _ERA_KEYS)
    ]
    if not groups:
        groups = ["(缺组表)"]
    for group in groups:
        cells: list[str] = []
        for name in _ERA_KEYS:
            row = tables[name].get(group) or {}
            cells.append(str(row.get("n")) if row.get("n") is not None else "—")
            cells.append(_fmt(row.get("expectancy")))
            cells.append(_fmt(row.get("winrate")))
        lines.append(f"| {group} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## 配对差 CI 并排 (t10, 正 = run 罚分)")
    lines.append("")
    lines.append("| 对比 | " + " | ".join(_ERA_KEYS) + " |")
    lines.append("|---|" + "---|" * len(_ERA_KEYS))
    for key in ("d1_run_vs_blip", "d2_run_vs_blip", "d3p_run_vs_blip"):
        cells: list[str] = []
        for name in _ERA_KEYS:
            d = ((eras.get(name) or {}).get("run_deltas_t10") or {}).get(key) or {}
            lo, hi = d.get("ci_low"), d.get("ci_high")
            cells.append(
                f"[{_fmt(lo)}, {_fmt(hi)}]"
                if lo is not None and hi is not None
                else "—"
            )
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
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
        description="R168 d1_run 时代条件性的宇宙构成判别 (纯诊断)"
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
            raise RegimeRunUniverseMatchError(f"{label}_missing: {path}")

    current_ev = pd.read_csv(args.court_table)
    early_ev = pd.read_csv(args.early_court_table)
    payload = universe_match_payload(
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
    um = payload.get("universe_match") or {}
    print(
        f"{REPORT_STEM}: full_penalty={_fmt(points.get('current_full'))} "
        f"matched_penalty={_fmt(points.get('current_matched'))} "
        f"(rows {um.get('current_rows_matched')}/{um.get('current_rows_full')}) · "
        f"{verdict.get('statement')} → {md_path}"
    )
    return 0


if __name__ == "__main__":
    main()
