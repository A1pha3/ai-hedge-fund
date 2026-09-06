"""实盘选中楔子恒等三分解 — 生产买入 vs court 生产对齐宇宙 (纯诊断).

第一性原理: 宇宙对账 (R118/R121/R122) 已实证两个宇宙的期望缺口 —

    E[realized] = E[court 同票假想] + E[realized − court 假想]

其中实现差 (锚点+费用) 已被 R122 钉小 (方向一致 15/15), 缺口主体在
**选中集合自身的 court 期望** 与全体宇宙期望之间。本工具把这段楔子
按生产决策的真实结构精确分解 (单元格 = (信号日, 票), 期望均为 court
gross_ret_t10, 同锚可比):

    E[bought] − E[universe] = (E[D] − E[U])      日选择
                            + (E[B_elig] − E[D]) 日内合格选择
                            + (E[B_all] − E[B_elig]) 不合格买入

三个分量都是格子均值的 plainly difference — 恒等零残差, 不依赖 RNG。
B_all ⊆ matched (court 有此票此日); B_elig = B_all ∩ U; B_inelig =
补集, 逐格原因分类 (gate/不可成交/排除链/未成熟) — 决策时可买但 court
终态数据判不可买/被排除的格子在这里显形。

注意口径: production_aligned 官方宇宙**包含 <0.50 强度行** (与分解报告
ALL 逐字对齐) — 强度维度的 PIT 漂移 (决策时 ≥0.50、终态 <0.50) 不构成
独立的楔子分量, 由「决策时强度 vs court 终态」漂移表单独披露。

决策时强度恢复: legacy journal 行自带 ``trigger_strength``; v2 台账不存
强度 (trades 表无列), 经 (信号日, 票) join ``setup_output_log`` eligible
行恢复 — 日志缺失 (如 20260820 300009 事件期被覆盖的历史污染) 如实记
None + 缺失计数披露, 绝不以 0.0 冒充。

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2): 胜率/赔率不替代组合路径证据; 本工具零判定逻辑,
    任何据此的生产参数变化 = 策略行为变化 = 新证据世代 (owner 决策)。
  - 主面只收 horizon==10 (可执行合约); 其他 horizon 单独披露不进恒等式。
  - 未成熟 (court 终态收益缺失) 格子不冒充观测。
  - 确定性: 同输入逐字节同输出 (无 RNG)。

用法:
    uv run python scripts/realized_selection_wedge.py
    uv run python scripts/realized_selection_wedge.py --output-json PATH
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from btst_realized_vs_court import (  # noqa: E402
    CALENDAR_PATH,
    COURT_MANIFEST_PATH,
    COURT_TABLE_PATH,
    JOURNAL_PATH,
    LEDGER_PATH,
    PANEL_DIR,
    REGIME_PATH,
    REPORTS_DIR,
    STORE_LEDGER_V2,
    build_classification_inputs,
    load_journal,
    load_ledger_buys,
    normalize_day,
    reconcile,
)
from winrate_payoff_decomposition import production_aligned, strength_bucket  # noqa: E402

PRIMARY_HORIZON = 10
HORIZON_RET_COL = "gross_ret_t10"
PRIMARY_MIN_N = 30

# 不合格原因的固定判定序 (逐格可多重; 输出顺序确定性)
_INELIG_FLAG_ORDER = (
    "gate_blocked",
    "t1_unbuyable",
    "degraded",
    "st_name",
    "industry_missing",
    "excluded_ticker",
)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _truthy(value: Any) -> bool:
    """NaN/None → False; numpy bool_/str 兜底 bool() (st_name 非空即真)。"""
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return bool(value)


def eligible_universe_cells(ev: pd.DataFrame) -> dict[tuple[str, str], float]:
    """生产对齐合格宇宙 → {(信号日, 6位代码): gross_ret_t10 %}。

    单一实现复用 (production_aligned → review_btst_prior_court 过滤链);
    列缺失由其 fail-closed (SystemExit), 此处不重写过滤语义。
    """
    aligned = production_aligned(ev)
    cells: dict[tuple[str, str], float] = {}
    for _, row in aligned.iterrows():
        ret = row[HORIZON_RET_COL]
        if ret is None or (isinstance(ret, float) and math.isnan(ret)):
            continue
        day = normalize_day(row["signal_date"])
        symbol = str(row["ts_code"]).split(".")[0]
        cells[(day, symbol)] = float(ret) * 100.0
    return cells


def production_buy_days(records: Sequence[Any]) -> list[str]:
    """全部生产 BUY 的信号日集合 (含 split 未 matched 的日子 — 日选择是
    生产属性, 与 court 覆盖无关)。"""
    return sorted({str(r.signal_date) for r in records})


def classify_ineligible_reasons(court_row: Mapping[str, Any] | None) -> list[str]:
    """court 终态行 → 不合格原因列表 (固定判定序, 逐格可多重)。"""
    if court_row is None:
        return ["court_row_unavailable"]
    reasons: list[str] = []
    strength = court_row.get("trigger_strength")
    if (
        strength is None
        or (isinstance(strength, float) and math.isnan(strength))
        or float(strength) < 0.5
    ):
        reasons.append("strength_below_threshold")
    if not _truthy(court_row.get("fillable")):
        reasons.append("not_fillable")
    for flag in _INELIG_FLAG_ORDER:
        if _truthy(court_row.get(flag)):
            reasons.append(flag)
    if not _truthy(court_row.get("price_ge_3")):
        reasons.append("price_lt_3")
    ret = court_row.get(HORIZON_RET_COL)
    if ret is None or (isinstance(ret, float) and math.isnan(ret)):
        reasons.append("ret_missing")
    return reasons


def split_bought_cells(
    matched_records: Sequence[Any],
    universe_cells: Mapping[tuple[str, str], float],
    court_rows: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    horizon: int = PRIMARY_HORIZON,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """matched 买入 → (B_all, B_elig, B_inelig); 只收主 horizon 且终态收益
    已成熟的格子 (未成熟不冒充观测, 由 payload 另计)。"""
    b_all: list[dict[str, Any]] = []
    b_elig: list[dict[str, Any]] = []
    b_inelig: list[dict[str, Any]] = []
    for r in sorted(matched_records, key=lambda r: (r.signal_date, r.ticker)):
        if int(r.horizon) != horizon:
            continue
        ret = r.court_gross_ret_horizon
        if ret is None:
            continue
        key = (str(r.signal_date), str(r.ticker))
        cell: dict[str, Any] = {
            "key": key,
            "day": key[0],
            "symbol": key[1],
            "ret_pct": float(ret),
        }
        b_all.append(cell)
        if key in universe_cells:
            b_elig.append(cell)
        else:
            cell["reasons"] = classify_ineligible_reasons(court_rows.get(key))
            b_inelig.append(cell)
    return b_all, b_elig, b_inelig


def decompose_wedge(
    *,
    u_vals: Sequence[float],
    d_vals: Sequence[float],
    be_vals: Sequence[float],
    ba_vals: Sequence[float],
) -> dict[str, float | None]:
    """恒等三分解; 任一缺面 → None (绝不假装 0), 全齐时残差恒 0。"""
    day = (
        _mean(d_vals) - _mean(u_vals) if (d_vals and u_vals) else None
    )
    within = (
        _mean(be_vals) - _mean(d_vals) if (be_vals and d_vals) else None
    )
    inelig = (
        _mean(ba_vals) - _mean(be_vals) if (ba_vals and be_vals) else None
    )
    wedge = (
        _mean(ba_vals) - _mean(u_vals) if (ba_vals and u_vals) else None
    )
    residual: float | None = None
    if None not in (day, within, inelig, wedge):
        residual = wedge - (day + within + inelig)  # type: ignore[operator]
    return {
        "day_pp": day,
        "within_day_pp": within,
        "ineligible_pp": inelig,
        "wedge_pp": wedge,
        "residual_pp": residual,
    }


def per_day_rows(
    buy_days: Sequence[str],
    universe_cells: Mapping[tuple[str, str], float],
    b_elig: Sequence[Mapping[str, Any]],
    b_inelig: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """逐日表: 当日合格集 n/均值 vs 当日买入合格/不合格计数。"""
    rows: list[dict[str, Any]] = []
    for day in buy_days:
        u_day = [v for (d, _), v in sorted(universe_cells.items()) if d == day]
        be_day = [c["ret_pct"] for c in b_elig if c["day"] == day]
        bi_day = [c for c in b_inelig if c["day"] == day]
        rows.append(
            {
                "signal_date": day,
                "eligible_n": len(u_day),
                "day_mean_pct": _mean(u_day),
                "bought_elig_n": len(be_day),
                "bought_elig_mean_pct": _mean(be_day),
                "bought_inelig_n": len(bi_day),
            }
        )
    return rows


def _load_log_strengths(path: Path) -> dict[str, float]:
    """单日 setup_output_log → {ticker: 决策时强度} (eligible 行; 损坏行跳过;
    后行胜 — 镜像主日志合并的『同资格晚运行覆盖』语义)。"""
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, float] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not row.get("plan_eligible"):
            continue
        ticker = str(row.get("ticker") or "")
        value = row.get("trigger_strength")
        if (
            ticker
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0.0 <= float(value) <= 1.0
        ):
            out[ticker] = float(value)
    return out


def recover_paper_strengths(
    matched_records: Sequence[Any], log_dir: Path | str | None
) -> tuple[dict[tuple[str, str], float], int]:
    """决策时强度恢复: legacy 行用自带 trigger_strength; v2 台账行 (无强度
    列) join setup_output_log eligible 行。缺失 → 不入 map + 计数 (绝不以
    0.0 冒充 — 假漂移比无漂移更有害)。"""
    mapping: dict[tuple[str, str], float] = {}
    missing = 0
    cache: dict[str, dict[str, float]] = {}
    for r in sorted(matched_records, key=lambda r: (r.signal_date, r.ticker)):
        if str(r.store) == STORE_LEDGER_V2:
            if log_dir is None:
                missing += 1
                continue
            day_rows = cache.get(str(r.signal_date))
            if day_rows is None:
                day_rows = _load_log_strengths(Path(log_dir) / f"{r.signal_date}.jsonl")
                cache[str(r.signal_date)] = day_rows
            value = day_rows.get(str(r.ticker))
            if value is None:
                missing += 1
            else:
                mapping[(str(r.signal_date), str(r.ticker))] = value
        elif r.paper_strength is not None:
            mapping[(str(r.signal_date), str(r.ticker))] = float(r.paper_strength)
    return mapping, missing


def drift_rows(
    b_all: Sequence[Mapping[str, Any]],
    matched_records: Sequence[Any],
    paper_strengths: Mapping[tuple[str, str], float],
) -> list[dict[str, Any]]:
    """漂移面逐行: 决策时强度 vs court 终态强度 (drift = paper − court,
    正值 = 生产看到的比终态更高)。"""
    by_key = {(str(r.signal_date), str(r.ticker)): r for r in matched_records}
    rows: list[dict[str, Any]] = []
    for cell in b_all:
        r = by_key[cell["key"]]
        paper = paper_strengths.get(cell["key"])
        court = r.court_strength
        drift = (
            paper - court
            if (paper is not None and court is not None)
            else None
        )
        rows.append(
            {
                "signal_date": r.signal_date,
                "ticker": r.ticker,
                "paper_strength": paper,
                "court_strength": court,
                "strength_drift": drift,
                "court_bucket": strength_bucket(court) if court is not None else None,
                "eligible": "reasons" not in cell,
                "ineligible_reasons": cell.get("reasons", []),
            }
        )
    return rows


def _other_horizon_blocks(matched_records: Sequence[Any]) -> list[dict[str, Any]]:
    """h≠10 的 matched 买入单独披露 (不进主恒等面)。"""
    grouped: dict[int, list[float]] = {}
    for r in sorted(matched_records, key=lambda r: (r.signal_date, r.ticker)):
        if int(r.horizon) == PRIMARY_HORIZON:
            continue
        if r.court_gross_ret_horizon is not None:
            grouped.setdefault(int(r.horizon), []).append(
                float(r.court_gross_ret_horizon)
            )
    return [
        {"horizon": h, "n": len(vals), "mean_pct": _mean(vals)}
        for h, vals in sorted(grouped.items())
    ]


def build_payload(
    recon: Any,
    ev: pd.DataFrame,
    inputs: Any,
    *,
    log_dir: Path | str | None,
    report_date: str,
) -> dict[str, Any]:
    """全部读取与恒等分解 — 零判定, 零 RNG, 确定性输出。"""
    universe = eligible_universe_cells(ev)
    buy_days = production_buy_days(recon.records)
    day_set = set(buy_days)
    d_vals = [v for (d, _), v in sorted(universe.items()) if d in day_set]
    b_all, b_elig, b_inelig = split_bought_cells(
        recon.matched_records, universe, inputs.court_rows
    )
    u_vals = [v for _, v in sorted(universe.items())]
    paper_strengths, missing_strengths = recover_paper_strengths(
        recon.matched_records, log_dir
    )
    unmatured = sum(
        1
        for r in recon.matched_records
        if int(r.horizon) == PRIMARY_HORIZON and r.court_gross_ret_horizon is None
    )
    split_n = sum(1 for r in recon.records if r.classification != "matched")
    components = decompose_wedge(
        u_vals=u_vals,
        d_vals=d_vals,
        be_vals=[c["ret_pct"] for c in b_elig],
        ba_vals=[c["ret_pct"] for c in b_all],
    )
    n_primary = len(b_all)
    return {
        "report_date": report_date,
        "horizon": f"t{PRIMARY_HORIZON}",
        "caliber": {
            "returns": "gross",
            "net_conversion": "净 = 毛 − 往返 0.65% (与 winrate 分解报告同式; "
            "两报告直比须先换算同口径)",
            "universe_note": "production_aligned 宇宙含 <0.50 强度行 (与分解报告 "
            "ALL 逐字对齐)",
        },
        "total_buys": len(recon.records),
        "matched_n": len(recon.matched_records),
        "split_n": split_n,
        "faces": {
            "universe_n": len(u_vals),
            "universe_mean_pct": _mean(u_vals),
            "bought_days_eligible_n": len(d_vals),
            "bought_days_eligible_mean_pct": _mean(d_vals),
            "b_all_n": n_primary,
            "b_all_mean_pct": _mean([c["ret_pct"] for c in b_all]),
            "b_elig_n": len(b_elig),
            "b_elig_mean_pct": _mean([c["ret_pct"] for c in b_elig]),
            "b_inelig_n": len(b_inelig),
            "b_inelig_mean_pct": _mean([c["ret_pct"] for c in b_inelig]),
        },
        "components": components,
        "small_sample": n_primary < PRIMARY_MIN_N,
        "primary_min_n": PRIMARY_MIN_N,
        "unmatured_primary_n": unmatured,
        "per_day": per_day_rows(buy_days, universe, b_elig, b_inelig),
        "drift": {
            "rows": drift_rows(b_all, recon.matched_records, paper_strengths),
            "missing_decision_strength": missing_strengths,
        },
        "other_horizons": _other_horizon_blocks(recon.matched_records),
        "discipline": [
            "纯诊断 (宪法 #2): 胜率/赔率不替代组合路径证据; 本工具零判定逻辑",
            "恒等式: wedge = 日选择 + 日内合格选择 + 不合格买入 (零残差; 格子 = (信号日,票))",
            f"主面只收 horizon==10 且 court 终态收益已成熟的 matched 买入; n<{PRIMARY_MIN_N} 只披露不判定",
            "任何据此的生产参数变化 = 策略行为变化 = 新证据世代 owner 决策",
        ],
    }


def render_md(payload: Mapping[str, Any]) -> str:
    faces = payload["faces"]
    comp = payload["components"]
    lines = [
        f"# 实盘选中楔子恒等三分解 ({payload['horizon']}, {payload['report_date']})",
        "",
        "纯诊断 (宪法 #2)。回答: 选中集合的 court 期望与全体宇宙期望之间的楔子",
        "来自哪里 — 日选择 / 日内合格选择 / 不合格买入 (PIT 漂移面)。三个分量",
        "都是格子均值的差 (恒等零残差, 无 RNG); 本报告不构成任何行为授权 —",
        "参数变化 = 新证据世代 owner 决策。",
        "",
        f"口径: 毛收益口径 (court gross_ret_t10) — 净 = 毛 − 往返 0.65% "
        "(与 winrate 分解报告同式, 跨报告直比须先同口径); "
        "宇宙含 <0.50 强度行",
        "",
        f"生产 BUY {payload['total_buys']} · matched {payload['matched_n']} · "
        f"split {payload['split_n']} · 主面 n={payload['faces']['b_all_n']} "
        f"(n<{payload['primary_min_n']} 只披露不判定)"
        + (
            f" · 未成熟 (终态收益缺失) {payload['unmatured_primary_n']} 笔不冒充观测"
            if payload["unmatured_primary_n"]
            else ""
        ),
        "",
        "## 面 (格子 = (信号日, 票), 期望 = court gross_ret_t10 %)",
        "",
        "| 面 | n | 均值 % |",
        "|---|---|---|",
        f"| U 全体合格宇宙 | {faces['universe_n']} | {_fmt(faces['universe_mean_pct'])} |",
        f"| D 买入日合格集 | {faces['bought_days_eligible_n']} | {_fmt(faces['bought_days_eligible_mean_pct'])} |",
        f"| B_elig 买入合格格 | {faces['b_elig_n']} | {_fmt(faces['b_elig_mean_pct'])} |",
        f"| B_all 买入全部 (含不合格) | {faces['b_all_n']} | {_fmt(faces['b_all_mean_pct'])} |",
        f"| B_inelig 不合格买入 | {faces['b_inelig_n']} | {_fmt(faces['b_inelig_mean_pct'])} |",
        "",
        "## 恒等分解",
        "",
        "E[bought] − E[universe] = 日选择 + 日内合格选择 + 不合格买入",
        "",
        f"- 日选择 (E[D]−E[U]): {_fmt(comp['day_pp'])} pp",
        f"- 日内合格选择 (E[B_elig]−E[D]): {_fmt(comp['within_day_pp'])} pp",
        f"- 不合格买入 (E[B_all]−E[B_elig]): {_fmt(comp['ineligible_pp'])} pp",
        f"- 楔子 (E[B_all]−E[U]): {_fmt(comp['wedge_pp'])} pp · 残差 {_fmt(comp['residual_pp'])}",
        "",
        "## 逐日表",
        "",
        "| 信号日 | 合格 n | 日均值 % | 买入合格 n | 买入合格均值 % | 不合格 n |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["per_day"]:
        lines.append(
            f"| {row['signal_date']} | {row['eligible_n']} | {_fmt(row['day_mean_pct'])} "
            f"| {row['bought_elig_n']} | {_fmt(row['bought_elig_mean_pct'])} "
            f"| {row['bought_inelig_n']} |"
        )
    lines += [
        "",
        "## 决策时强度 vs court 终态 (漂移面; drift = 决策时 − 终态, 正 = 生产看到的更高)",
        "",
        f"决策时强度缺失 {payload['drift']['missing_decision_strength']} 笔"
        " (日志无 eligible 行 — 含 300009 事件型历史污染, 如实 None 不冒充)",
        "",
        "| 信号日 | 票 | 决策时 | court 终态 | drift | court 桶 | 终态资格 | 不合格原因 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in payload["drift"]["rows"]:
        lines.append(
            f"| {row['signal_date']} | {row['ticker']} | {_fmt(row['paper_strength'])} "
            f"| {_fmt(row['court_strength'])} | {_fmt(row['strength_drift'])} "
            f"| {row['court_bucket'] or '—'} | {'合格' if row['eligible'] else '不合格'} "
            f"| {','.join(row['ineligible_reasons']) or '—'} |"
        )
    others = payload.get("other_horizons") or []
    if others:
        lines += [
            "",
            "## 其他 horizon (不进主恒等面, 单独披露)",
            "",
            "| horizon | n | 均值 % |",
            "|---|---|---|",
        ]
        for item in others:
            lines.append(
                f"| t{item['horizon']} | {item['n']} | {_fmt(item['mean_pct'])} |"
            )
    lines += ["", "## 纪律", ""]
    lines += [f"- {item}" for item in payload["discipline"]]
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and math.isnan(value):
        return "—"
    return f"{value:+.2f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--journal", type=Path, default=JOURNAL_PATH)
    parser.add_argument(
        "--ledger", type=Path, default=LEDGER_PATH,
        help="v2 生产台账 (sqlite3, 只读)。缺失 → 台账纪元不计入 (fail-open)。",
    )
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_PATH)
    parser.add_argument("--court-manifest", type=Path, default=COURT_MANIFEST_PATH)
    parser.add_argument("--regime", type=Path, default=REGIME_PATH)
    parser.add_argument("--calendar", type=Path, default=CALENDAR_PATH)
    parser.add_argument("--panel-dir", type=Path, default=PANEL_DIR)
    parser.add_argument(
        "--setup-log-dir", type=Path, default=Path("data/reports/setup_output_log"),
        help="决策时强度恢复的 setup_output_log 目录 (缺失 → v2 行全记缺失)。",
    )
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args(argv)

    journal = load_journal(args.journal)
    extra_buys: list[dict[str, Any]] = (
        load_ledger_buys(args.ledger) if args.ledger.exists() else []
    )
    court_table = pd.read_csv(args.court_table)
    court_table["signal_date"] = court_table["signal_date"].map(normalize_day)
    regime_labels = {
        normalize_day(k): str(v)
        for k, v in json.loads(args.regime.read_text(encoding="utf-8")).items()
    }
    calendar_raw = json.loads(args.calendar.read_text(encoding="utf-8"))
    calendar_days = sorted({normalize_day(d) for d in calendar_raw})
    panel_dates = {
        p.name[len("daily_"): -len(".csv")]
        for p in args.panel_dir.glob("daily_*.csv")
    }
    window = _court_window_from_manifest(args.court_manifest)
    if window is None:
        raise SystemExit("court manifest 缺失或无 window — 无法定窗, fail-closed")
    window_sessions = [d for d in calendar_days if window[0] <= d <= window[1]]

    inputs = build_classification_inputs(
        court_table=court_table,
        window_sessions=window_sessions,
        regime_labels=regime_labels,
        panel_dates=panel_dates,
    )
    recon = reconcile(journal, inputs, extra_buys=extra_buys)
    stamp = date.today().strftime("%Y%m%d")
    payload = build_payload(
        recon, court_table, inputs, log_dir=args.setup_log_dir, report_date=stamp
    )

    out_json = args.output_json or (REPORTS_DIR / f"selection_wedge_{stamp}.json")
    out_md = args.output_md or (REPORTS_DIR / f"selection_wedge_{stamp}.md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    out_md.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps(payload["components"], ensure_ascii=False))
    print(f"written: {out_json} / {out_md}")
    return 0


def _court_window_from_manifest(path: Path) -> tuple[str, str] | None:
    """court manifest → (start, end); 与 btst_realized_vs_court 同源读取。"""
    from btst_realized_vs_court import _court_window_from_manifest as _impl

    return _impl(path)


if __name__ == "__main__":
    raise SystemExit(main())
