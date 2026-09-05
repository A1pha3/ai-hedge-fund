"""实盘 paper journal vs court 事件表 — 宇宙分裂对账 (纯诊断).

第一性原理: 全部 BTST 胜率/赔率证据 (先验校准/阈值决策/regime gate/factor
factory/持有期曲线) 都建在 court 事件表上; 生产 --daily-action 实际交易的
是 paper journal 里的信号。两个宇宙若分裂, 则「提高胜率和赔率」的一切度量
都在错靶上 — 实盘前向 12 笔全亏 (E=-9.68%) vs court production_aligned
t10 期望 (E=+1.32%/胜率 47.5%) 的剧烈背离正是这个分裂的经济后果。

本工具把每笔生产 BUY (date=信号日 T0, entry_price=T0 收盘参考锚) 确定性
归入六类:

  outside_window          T0 不在 court 窗口内
  day_excluded_regime_gap T0∈窗口交易日 ∧ T0∉regime_history
                         (court build 把缺标签日整日剔除 — 与
                          btst_court_build.main 的剔除语义同源)
  day_missing_panel_data  T0∈regime ∧ T0 无 raw 面板日文件 (数据洞, 非 detect 分歧)
  day_missing_from_court  T0∈regime ∧ 面板日存在 ∧ court 当日零行
                         (detect 重放 court-wide 不触发)
  ticker_not_in_court_day court 当日有行但无此票 (条件输入分歧: 资金流/行业)
  matched                 court 有 (ticker, T0) 行 → 附强度漂移标注 +
                         paper realized vs court gross_ret_t{h} 方向对照

口径注记 (不做等值断言 — 两条腿本就不同):
  paper realized = T+1 open×(1+slip) → close[T0+h]×(1−slip)
                   (paper_tracker._execution_adjusted_return, h=journal horizon)
  court gross_ret_t{h} = T+1 open → T+h open (合约腿, 未扣费)
  方向一致性 (同号) 是唯一可比量; realized 含滑点/扣费语义由消费方自记。

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2): 胜率/赔率不替代组合路径证据; 任何据此改参数 =
    新证据世代 owner 决策。
  - 分类只依赖注入输入 (journal/court表/regime/日历/面板日集合),
    纯函数可测; 真实数据报告宿主侧产出。
  - 确定性: 同输入逐字节同输出 (无 RNG)。

用法:
    uv run python scripts/btst_realized_vs_court.py
    uv run python scripts/btst_realized_vs_court.py --output-json PATH --output-md PATH
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

JOURNAL_PATH = Path("data/paper_trading/journal.jsonl")
LEDGER_PATH = Path("data/paper_trading_v2/ledger.sqlite3")
COURT_TABLE_PATH = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
COURT_MANIFEST_PATH = Path("data/research/btst_court/event_tables/manifest_v1.json")
REGIME_PATH = Path("data/reports/regime_history.json")
CALENDAR_PATH = Path("data/reports/trade_calendar.json")
PANEL_DIR = Path("data/research/btst_court/raw/daily")
REPORTS_DIR = Path("data/reports")

CLASSES = (
    "outside_window",
    "day_excluded_regime_gap",
    "day_missing_panel_data",
    "day_missing_from_court",
    "ticker_not_in_court_day",
    "matched",
)

_REALIZED_RE = re.compile(r"realized=([+-]?\d+(?:\.\d+)?)%")

# court 事件表可用的退出端点列 (与 gross_ret_t{3,5,8,10} 对应)
_COURT_HORIZON_COLUMNS = {3: "gross_ret_t3", 5: "gross_ret_t5", 8: "gross_ret_t8", 10: "gross_ret_t10"}


@dataclass(frozen=True)
class ClassificationInputs:
    """分类所需的全部注入事实 — 不读任何全局态."""

    window_sessions: frozenset[str]  # court 窗口内的交易日 (YYYYMMDD)
    regime_labels: Mapping[str, str]  # regime_history (YYYYMMDD → label)
    panel_dates: frozenset[str]  # raw 面板日文件覆盖的交易日
    court_by_day: Mapping[str, frozenset[str]]  # court 当日出现的 6 位代码集合
    court_rows: Mapping[tuple[str, str], Mapping[str, Any]]  # (day, 6位) → 行


@dataclass(frozen=True)
class SignalRecord:
    """一笔生产 BUY 的对账分类结果.

    ``store`` 是时代归属 (R121b): ``legacy_journal`` = v2 台账启用前的
    paper journal 信号; ``ledger_v2`` = data/paper_trading_v2 台账交易
    (2026-08-14 起唯一生产计划创建路径)。两 store 是生产 BUY 流的两个
    纪元, 单独任何一个都不是完整的生产宇宙。
    """

    signal_date: str
    ticker: str
    horizon: int
    paper_strength: float
    classification: str
    court_strength: float | None = None
    strength_drift: float | None = None
    realized_pct: float | None = None
    court_gross_ret_horizon: float | None = None
    direction_agree: bool | None = None
    store: str = "legacy_journal"


@dataclass
class Reconciliation:
    records: list[SignalRecord] = field(default_factory=list)
    class_counts: dict[str, int] = field(default_factory=lambda: {c: 0 for c in CLASSES})
    matched_records: list[SignalRecord] = field(default_factory=list)
    realized_records: list[SignalRecord] = field(default_factory=list)
    duplicate_buys_skipped: int = 0


def normalize_day(value: object) -> str:
    """YYYYMMDD | YYYY-MM-DD | int64 → 8 位字符串 (court signal_date 是 int64)."""
    text = str(value).replace("-", "").strip()
    if len(text) == 8 and text.isdigit():
        return text
    raise ValueError(f"unparseable trade date: {value!r}")


def load_journal(path: Path | str = JOURNAL_PATH) -> list[dict[str, Any]]:
    """读 paper journal JSONL — BUY/EXIT 原样返回, 坏行 fail-closed."""
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"journal line is not an object: {line[:80]}")
        records.append(payload)
    return records


STORE_LEGACY_JOURNAL = "legacy_journal"
STORE_LEDGER_V2 = "ledger_v2"

# v2 台账只读接入 (R121b): 不经 LedgerRepository — 那是写侧构造器, 会建库/
# 迁移; 对账是纯读诊断, 直接 sqlite3 mode=ro 读 trades 表。成本字段
# (commission/tax/slippage) 是台账结算的精确经济事实, realized 按净额口径。
_LEDGER_TRADES_QUERY = (
    "SELECT signal_date, ticker, state, raw_entry_price, quantity,"
    " entry_commission, entry_tax, entry_slippage,"
    " raw_exit_price, exit_commission, exit_tax, exit_slippage"
    " FROM trades"
)


def load_ledger_buys(path: Path | str = LEDGER_PATH) -> list[dict[str, Any]]:
    """读 v2 生产台账 trades 表 → 归一 BUY 记录 (含已平仓净额 realized).

    缺库抛 OSError (调用方决定 fail-open/fail-closed); 损坏行/畸形值
    fail-closed 抛 ValueError — 与 load_journal 同纪律。open 仓 realized
    为 None (未平仓不冒充已兑现)。
    """
    uri = f"file:{Path(path).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(_LEDGER_TRADES_QUERY).fetchall()
    finally:
        conn.close()
    buys: list[dict[str, Any]] = []
    for row in rows:
        (signal_date, ticker, state, entry_px, qty, entry_comm, entry_tax,
         entry_slip, exit_px, exit_comm, exit_tax, exit_slip) = row
        day = normalize_day(signal_date)
        code = str(ticker or "").strip()
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"ledger ticker unparseable: {ticker!r}")
        realized: float | None = None
        if str(state) == "closed":
            for name, value in (
                ("raw_entry_price", entry_px), ("quantity", qty),
                ("raw_exit_price", exit_px),
            ):
                if not isinstance(value, (int, float)) or value is None:
                    raise ValueError(f"ledger closed trade missing {name}: {row!r}")
            costs = lambda *xs: float(sum(x or 0.0 for x in xs))  # noqa: E731
            basis = float(entry_px) * float(qty) + costs(entry_comm, entry_tax, entry_slip)
            proceeds = float(exit_px) * float(qty) - costs(exit_comm, exit_tax, exit_slip)
            if basis <= 0:
                raise ValueError(f"ledger non-positive cost basis: {row!r}")
            realized = (proceeds / basis - 1.0) * 100.0
        buys.append(
            {
                "date": day,
                "ticker": code,
                # v2 可执行合约固定 T+10 (宪法 #2); 台账不存 horizon 列。
                "horizon": 10,
                "trigger_strength": None,
                "realized_pct": realized,
                "store": STORE_LEDGER_V2,
            }
        )
    return buys


def extract_realized(exit_record: Mapping[str, Any]) -> float | None:
    """EXIT reasoning 里的 realized=±x.x% → 百分数 float; 无则 None."""
    reasoning = str(exit_record.get("reasoning") or "")
    match = _REALIZED_RE.search(reasoning)
    if match is None:
        return None
    return float(match.group(1))


def build_classification_inputs(
    *,
    court_table: pd.DataFrame,
    window_sessions: Iterable[str],
    regime_labels: Mapping[str, str],
    panel_dates: Iterable[str],
) -> ClassificationInputs:
    """court 表 + 外部事实 → 分类索引. signal_date int64 在此归一."""
    by_day: dict[str, set[str]] = {}
    rows: dict[tuple[str, str], Mapping[str, Any]] = {}
    for _, row in court_table.iterrows():
        day = normalize_day(row["signal_date"])
        symbol = str(row["ts_code"]).split(".")[0]
        by_day.setdefault(day, set()).add(symbol)
        rows[(day, symbol)] = dict(row)
    return ClassificationInputs(
        window_sessions=frozenset(normalize_day(d) for d in window_sessions),
        regime_labels=regime_labels,
        panel_dates=frozenset(normalize_day(d) for d in panel_dates),
        court_by_day={d: frozenset(s) for d, s in by_day.items()},
        court_rows=rows,
    )


def classify_buy(
    buy: Mapping[str, Any],
    inputs: ClassificationInputs,
    realized_by_key: Mapping[tuple[str, str], float],
) -> SignalRecord:
    """单笔 BUY → 六类之一. 分类序 = 判定优先级 (window → regime → panel → day → ticker).

    ``store`` 从 BUY 记录携带 (R121b 时代归属); ``trigger_strength`` 为 None
    的来源 (v2 台账不存信号强度) → paper_strength/strength_drift 置 None,
    绝不以 0.0 冒充强度 (假漂移比无漂移更有害)。
    """
    signal_date = normalize_day(buy.get("date"))
    ticker = str(buy.get("ticker") or "")
    horizon = int(buy.get("horizon") or 10)
    raw_strength = buy.get("trigger_strength")
    paper_strength: float | None = (
        float(raw_strength) if raw_strength is not None else None
    )
    store = str(buy.get("store") or STORE_LEGACY_JOURNAL)

    classification: str
    court_row: Mapping[str, Any] | None = None
    if signal_date not in inputs.window_sessions:
        classification = "outside_window"
    elif signal_date not in inputs.regime_labels:
        classification = "day_excluded_regime_gap"
    elif signal_date not in inputs.panel_dates:
        classification = "day_missing_panel_data"
    elif not inputs.court_by_day.get(signal_date):
        classification = "day_missing_from_court"
    elif ticker not in (inputs.court_by_day.get(signal_date) or frozenset()):
        classification = "ticker_not_in_court_day"
    else:
        classification = "matched"
        court_row = inputs.court_rows[(signal_date, ticker)]

    court_strength = float(court_row["trigger_strength"]) if court_row is not None else None
    strength_drift = (
        paper_strength - court_strength
        if (court_strength is not None and paper_strength is not None)
        else None
    )
    # 台账 BUY 自带净额 realized (R121b); journal BUY 走 EXIT reasoning 映射。
    inline_realized = buy.get("realized_pct")
    realized = (
        float(inline_realized)
        if isinstance(inline_realized, (int, float))
        else realized_by_key.get((signal_date, ticker))
    )

    court_gross: float | None = None
    direction_agree: bool | None = None
    column = _COURT_HORIZON_COLUMNS.get(horizon)
    if court_row is not None and column is not None:
        value = court_row.get(column)
        if value is not None and not pd.isna(value):
            court_gross = float(value) * 100.0  # court 存小数 → 百分数
    if realized is not None and court_gross is not None:
        direction_agree = (realized > 0) == (court_gross > 0)

    return SignalRecord(
        signal_date=signal_date,
        ticker=ticker,
        horizon=horizon,
        paper_strength=paper_strength,
        classification=classification,
        court_strength=court_strength,
        strength_drift=strength_drift,
        realized_pct=realized,
        court_gross_ret_horizon=court_gross,
        direction_agree=direction_agree,
        store=store,
    )


def realized_map_from_journal(journal: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], float]:
    """EXIT 记录 (date=信号日锚) → {(信号日, ticker): realized 百分数}."""
    mapping: dict[tuple[str, str], float] = {}
    for record in journal:
        if str(record.get("action") or "").upper() != "EXIT":
            continue
        realized = extract_realized(record)
        if realized is None:
            continue
        mapping[(normalize_day(record.get("date")), str(record.get("ticker") or ""))] = realized
    return mapping


def reconcile(
    journal: Sequence[Mapping[str, Any]],
    inputs: ClassificationInputs,
    *,
    extra_buys: Sequence[Mapping[str, Any]] = (),
) -> Reconciliation:
    """journal (+ extra_buys) + 分类索引 → union 全量对账.

    BUY 幂等键 (信号日, ticker) 去重取首条; journal 先史 precedence —
    跨 store 重键时保留 journal 记录, 台账重键计入 ``duplicate_buys_skipped``
    (两 store 同键 = 时代归属异常, 计数显形而不是静默吞并)。
    """
    realized_by_key = realized_map_from_journal(journal)
    result = Reconciliation()
    seen: set[tuple[str, str]] = set()

    def _ingest(buy: Mapping[str, Any]) -> bool:
        key = (normalize_day(buy.get("date")), str(buy.get("ticker") or ""))
        if key in seen:
            return False
        seen.add(key)
        classified = classify_buy(buy, inputs, realized_by_key)
        result.records.append(classified)
        result.class_counts[classified.classification] += 1
        if classified.classification == "matched":
            result.matched_records.append(classified)
        if classified.realized_pct is not None:
            result.realized_records.append(classified)
        return True

    for record in journal:
        if str(record.get("action") or "").upper() != "BUY":
            continue
        _ingest(record)
    for buy in extra_buys:
        if not _ingest(buy):
            result.duplicate_buys_skipped += 1
    return result


def realized_stats(records: Sequence[SignalRecord]) -> dict[str, Any] | None:
    """realized-only 胜率/赔率/E (百分数口径, 与 paper journal 同源)."""
    values = [r.realized_pct for r in records if r.realized_pct is not None]
    if not values:
        return None
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v <= 0]
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    payoff = (avg_win / abs(avg_loss)) if (avg_win is not None and avg_loss) else None
    return {
        "n": len(values),
        "win_rate_pct": round(100.0 * len(wins) / len(values), 2),
        "avg_win_pct": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss_pct": round(avg_loss, 2) if avg_loss is not None else None,
        "payoff": round(payoff, 3) if payoff is not None else None,
        "expectancy_pct": round(sum(values) / len(values), 2),
    }


def stores_block(recon: Reconciliation) -> dict[str, dict[str, Any]]:
    """per-store 时代归属块 (R121b): 每个 store 的 buys/open/realized。

    ``buys`` = 该 store 计入 union 的 BUY 数; ``open_buys`` = buys − 已平仓
    (journal 僵尸 open 与台账 open 仓都显形, 不假装全部已兑现);
    ``realized_only`` = 该 store 自身口径的胜率/赔率/E (journal = EXIT
    reasoning 滑点口径, ledger = 台账结算净额口径 — 锚点本异, 分列披露)。
    """
    stores: dict[str, dict[str, Any]] = {}
    for store in (STORE_LEGACY_JOURNAL, STORE_LEDGER_V2):
        records = [r for r in recon.records if r.store == store]
        if not records:
            continue
        realized = realized_stats([r for r in records if r.realized_pct is not None])
        stores[store] = {
            "buys": len(records),
            "open_buys": len(records) - len(
                [r for r in records if r.realized_pct is not None]
            ),
            "realized_only": realized,
        }
    return stores


def summary_payload(recon: Reconciliation, *, court_window: tuple[str, str] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "class_counts": dict(recon.class_counts),
        "total_buys": len(recon.records),
        "realized_only": realized_stats(recon.realized_records),
        "stores": stores_block(recon),
        "duplicate_buys_skipped": recon.duplicate_buys_skipped,
        "matched_records": [
            {
                "signal_date": r.signal_date,
                "ticker": r.ticker,
                "horizon": r.horizon,
                "paper_strength": r.paper_strength,
                "court_strength": r.court_strength,
                "strength_drift": (
                    round(r.strength_drift, 4) if r.strength_drift is not None else None
                ),
                "realized_pct": r.realized_pct,
                "court_gross_ret_horizon_pct": (
                    round(r.court_gross_ret_horizon, 2)
                    if r.court_gross_ret_horizon is not None
                    else None
                ),
                "direction_agree": r.direction_agree,
            }
            for r in recon.matched_records
        ],
        "discipline": [
            "纯诊断 (宪法 #2): 胜率/赔率不替代组合路径证据",
            "paper realized (T+1 open 滑点→T+h close) 与 court gross (T+1 open→T+h open) 锚点本异, 只做方向对照",
            "任何据此的生产参数变化 = 新证据世代 owner 决策",
        ],
    }
    if court_window is not None:
        payload["court_window"] = {"start": court_window[0], "end": court_window[1]}
    return payload


def build_alignment_summary(
    recon: Reconciliation,
    *,
    court_window: tuple[str, str] | None,
    summary_date: str,
) -> dict[str, Any]:
    """操作员对齐行的 canonical 摘要 (R118 Op1)。

    与 :func:`summary_payload` 的差异: 不携带 matched_records/discipline 大
    载荷 — ``--daily-action`` 宇宙对齐行只消费计数与最晚分裂/匹配信号日;
    split = 分类非 matched 的全部记录 (六类语义见 ``CLASSES``)。夜刷链在
    court build 成功后单写者落盘 (undated, 原子替换), 渲染面按形状守卫
    fail-open 消费。
    """
    split_dates = [
        r.signal_date for r in recon.records if r.classification != "matched"
    ]
    matched_dates = [r.signal_date for r in recon.matched_records]
    summary: dict[str, Any] = {
        "date": summary_date,
        "total_buys": len(recon.records),
        "class_counts": dict(recon.class_counts),
        "realized_only": realized_stats(recon.realized_records),
        "stores": stores_block(recon),
        "duplicate_buys_skipped": recon.duplicate_buys_skipped,
        "latest_split_signal_date": max(split_dates) if split_dates else None,
        "latest_matched_signal_date": max(matched_dates) if matched_dates else None,
    }
    if court_window is not None:
        summary["court_window"] = {"start": court_window[0], "end": court_window[1]}
    return summary


def write_alignment_summary(path: Path, summary: dict[str, Any]) -> None:
    """canonical summary 原子落盘 (tempfile + fsync + os.replace —
    court_refresh_status._persist_status 同族纪律)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".alignment_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def render_md(payload: Mapping[str, Any]) -> str:
    counts = payload["class_counts"]
    lines = [
        "# 实盘 paper journal vs court 宇宙对账",
        "",
        "纯诊断 (宪法 #2)。每笔生产 BUY 归入六类; matched 对附强度漂移与双锚点方向对照",
        "(paper realized = T+1 open 滑点→T+h close; court gross = T+1 open→T+h open — 锚点本异, 只比方向)。",
        "",
    ]
    if "court_window" in payload:
        lines.append(
            f"court 窗口: {payload['court_window']['start']}..{payload['court_window']['end']}"
        )
        lines.append("")
    lines.append(f"生产 BUY 总数: **{payload['total_buys']}**")
    lines.append("")
    stores = payload.get("stores") or {}
    if stores:
        lines.append("| 纪元 (store) | BUY | 未平仓 | 已平仓 n | 胜率 | 期望 |")
        lines.append("|---|---|---|---|---|---|")
        store_labels = {
            STORE_LEGACY_JOURNAL: "legacy_journal (v2 前信号)",
            STORE_LEDGER_V2: "ledger_v2 (v2 生产台账)",
        }
        for key in (STORE_LEGACY_JOURNAL, STORE_LEDGER_V2):
            block = stores.get(key)
            if not isinstance(block, dict):
                continue
            realized = block.get("realized_only")
            lines.append(
                f"| {store_labels[key]} | {block.get('buys', 0)} "
                f"| {block.get('open_buys', 0)} "
                f"| {realized.get('n') if isinstance(realized, dict) else '—'} "
                f"| {realized.get('win_rate_pct') if isinstance(realized, dict) else '—'} "
                f"| {realized.get('expectancy_pct') if isinstance(realized, dict) else '—'} |"
            )
        skipped = payload.get("duplicate_buys_skipped")
        if isinstance(skipped, int) and skipped > 0:
            lines.append("")
            lines.append(f"⚠ 跨 store 重键去重 {skipped} 笔 (同 (信号日,票) 双记录 — 时代归属异常)")
        lines.append("")
    lines.append("| 分类 | 笔数 | 语义 |")
    lines.append("|---|---|---|")
    semantics = {
        "outside_window": "T0 不在 court 窗口内",
        "day_excluded_regime_gap": "T0∈窗口 ∧ regime 缺标签 — court 整日剔除",
        "day_missing_panel_data": "T0 有 regime 但无 raw 面板日 (数据洞)",
        "day_missing_from_court": "T0 面板完整但 court 零行 — detect 重放分歧",
        "ticker_not_in_court_day": "court 当日有行无此票 — 条件输入分歧",
        "matched": "court 有此票此日",
    }
    for cls in CLASSES:
        lines.append(f"| {cls} | {counts.get(cls, 0)} | {semantics[cls]} |")
    realized = payload.get("realized_only")
    if realized is not None:
        lines += [
            "",
            "## realized-only (journal 已平仓口径)",
            "",
            f"n={realized['n']} 胜率={realized['win_rate_pct']}% "
            f"avg_win={realized['avg_win_pct']}% avg_loss={realized['avg_loss_pct']}% "
            f"payoff={realized['payoff']} E={realized['expectancy_pct']}%",
        ]
    matched = payload.get("matched_records") or []
    if matched:
        lines += [
            "",
            "## matched 对照明细",
            "",
            "| 信号日 | 票 | h | paper强度 | court强度 | 漂移 | realized% | court毛益% | 方向一致 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for m in matched:
            strength_text = (
                f"{m['paper_strength']:.3f}"
                if isinstance(m.get("paper_strength"), (int, float))
                else "—"
            )
            lines.append(
                f"| {m['signal_date']} | {m['ticker']} | {m['horizon']} "
                f"| {strength_text} | "
                f"{m['court_strength'] if m['court_strength'] is not None else '—'} "
                f"| {m['strength_drift'] if m['strength_drift'] is not None else '—'} "
                f"| {m['realized_pct'] if m['realized_pct'] is not None else '—'} "
                f"| {m['court_gross_ret_horizon_pct'] if m['court_gross_ret_horizon_pct'] is not None else '—'} "
                f"| {m['direction_agree'] if m['direction_agree'] is not None else '—'} |"
            )
    lines += ["", "## 纪律", ""]
    lines += [f"- {d}" for d in payload.get("discipline", [])]
    lines.append("")
    return "\n".join(lines)


def _court_window_from_manifest(manifest_path: Path) -> tuple[str, str] | None:
    if not manifest_path.exists():
        return None
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = payload.get("window")
    if not isinstance(window, dict):
        return None
    start = normalize_day(window.get("start"))
    end = normalize_day(window.get("end"))
    return (start, end)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--journal", type=Path, default=JOURNAL_PATH)
    parser.add_argument(
        "--ledger", type=Path, default=LEDGER_PATH,
        help="v2 生产台账 (sqlite3, 只读)。缺失 → 台账纪元不计入 (fail-open, "
        "仅 legacy journal 纪元对账); 损坏 → 类型化异常 fail-closed。",
    )
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_PATH)
    parser.add_argument("--court-manifest", type=Path, default=COURT_MANIFEST_PATH)
    parser.add_argument("--regime", type=Path, default=REGIME_PATH)
    parser.add_argument("--calendar", type=Path, default=CALENDAR_PATH)
    parser.add_argument("--panel-dir", type=Path, default=PANEL_DIR)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    parser.add_argument(
        "--summary-json", type=Path, default=None,
        help="canonical 对齐摘要落盘路径 (undated 原子替换; 夜刷链单写者消费面)",
    )
    args = parser.parse_args(argv)

    journal = load_journal(args.journal)
    # v2 台账纪元 (R121b): 文件存在才计入 — 缺失 = v2 未启用形态 (合法),
    # 渲染面 stores 块缺 ledger_v2 时按 legacy-only 逐字回退旧行。
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
    payload = summary_payload(recon, court_window=window)

    from datetime import date

    stamp = date.today().strftime("%Y%m%d")
    out_json = args.output_json or (REPORTS_DIR / f"realized_vs_court_reconciliation_{stamp}.json")
    out_md = args.output_md or (REPORTS_DIR / f"realized_vs_court_reconciliation_{stamp}.md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    out_md.write_text(render_md(payload), encoding="utf-8")
    if args.summary_json is not None:
        write_alignment_summary(
            args.summary_json,
            build_alignment_summary(recon, court_window=window, summary_date=stamp),
        )
        print(f"alignment summary: {args.summary_json}")
    print(json.dumps(payload["class_counts"], ensure_ascii=False))
    print(f"realized_only: {json.dumps(payload['realized_only'], ensure_ascii=False)}")
    print(f"written: {out_json} / {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
