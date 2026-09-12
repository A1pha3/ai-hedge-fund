"""gap 前向影子 — T+1 开盘跳空归属事实记录 (宪章杠杆 A 前向影子记录机).

宪章杠杆 A (gap>5% 执行面剔除) 的证据链是: 判定包 (R194) → owner 决策 →
前向影子 (纸面记录『本会买但跳过』的高开入场) → 政策。本模块是前向影子的
事实记录面: 每个 paper journal BUY 在 T+1 会话的开盘 gap 一旦可观测即落一条
append-only 记录, 影子期数据齐备后供配对读数包消费。

宪法 #2 纯披露: 只记录 T+1 开盘 gap 的事实归属, 不改变任何买卖行为;
前向影子的启动与政策化本身仍属 owner 决策。

PIT 语义 (首观察赢):
- 每个 ``(signal_date, ticker)`` 只在首次可观测时落一条记录, 之后数据修订
  不改写 —— T+1 执行现实是"当时看到什么", 一周后回填的 bar 不改变 T+1
  竞价事实 (与 _execution_adjusted_return 消费同一 price_cache 帧同源)。
- 全价格帧不可得 → 视为数据未就绪, 重试不落盘 (帧可能晚到)。
- T+1 会话 bar 缺失 (停牌/数据洞) → 永久事实记录, ``gap_status`` 具名,
  ``would_skip=None`` —— 绝不把不可观测伪装成可交易性判定。

口径边界 (如实): gap 基于运行的 price_cache 帧 (qfq), 与 court 研究口径
(raw + pre_close 围栏) 在跨除权会话上可有小幅分歧 (AGENTS 陷阱 15);
记录的是本系统执行视角的 gap 真相。
"""

from __future__ import annotations

import json
import math
from numbers import Real
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from src.screening.offensive.gap_disclosure import GAP_HIGH_THRESHOLD

GAP_SHADOW_FILENAME = "gap_shadow.jsonl"

# gap_status 具名值 (消费方按状态分派, 字符串漂移即测试红)
GAP_STATUS_OBSERVED = "observed"
GAP_STATUS_T1_BAR_MISSING = "t1_bar_missing"
GAP_STATUS_PREV_CLOSE_MISSING = "prev_close_missing"
GAP_STATUS_NON_POSITIVE_PRICE = "non_positive_price"

# 记录体必需键 (缺任一 = 结构损坏, fail-closed)
_REQUIRED_RECORD_KEYS = ("signal_date", "ticker", "gap_status")


class GapShadowJournalError(Exception):
    """影子 journal 结构损坏 (fail-closed, 绝不静默覆盖损坏事实)."""


def _finite_positive(value: Any) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


def open_gap_pct(prev_close: Any, t1_open: Any) -> float | None:
    """T+1 开盘 gap = t1_open/prev_close − 1; 输入不可信时 None (不伪造)."""
    if not _finite_positive(prev_close) or not _finite_positive(t1_open):
        return None
    return float(t1_open) / float(prev_close) - 1.0


def would_skip(gap_pct: float | None, threshold: float = GAP_HIGH_THRESHOLD) -> bool | None:
    """挑战者政策 (跳过高开) 的归属判定: gap 严格 > 阈值才 skip; 不可观测 → None."""
    if gap_pct is None:
        return None
    return bool(gap_pct > threshold)


def t1_session_resolver(sessions: Sequence[Any]) -> Callable[[str], str | None]:
    """由权威会话列表 (datetime.date / 'YYYYMMDD' / 'YYYY-MM-DD') 构造解析器.

    统一归一化为紧凑 YYYYMMDD; 空日历或缺席时返回 None → 调用方按数据未就绪
    重试 (不落盘不猜测).
    """
    ordered = sorted({str(s).replace("-", "") for s in sessions if str(s)})

    def resolve(signal_date: str) -> str | None:
        later = [s for s in ordered if s > str(signal_date)]
        return later[0] if later else None

    return resolve


def _frame_date_strings(prices_df: Any) -> list[str] | None:
    """价格帧的紧凑日期串列表 (镜像 paper_tracker._execution_adjusted_return 归一化)."""
    if prices_df is None or not hasattr(prices_df, "__len__") or len(prices_df) == 0:
        return None
    if not hasattr(prices_df, "columns") or not {"date", "open", "close"}.issubset(set(prices_df.columns)):
        return None
    try:
        normalized = prices_df["date"].dt.strftime("%Y%m%d")
    except Exception:
        try:
            normalized = prices_df["date"].astype(str).str.replace("-", "", regex=False)
        except Exception:
            return None
    try:
        return [str(v) for v in normalized.tolist()]
    except Exception:
        return None


def _frame_value_at(prices_df: Any, index: int, column: str) -> Any:
    try:
        return prices_df.iloc[index][column]
    except Exception:
        return None


def build_shadow_records(
    buy_records: Iterable[dict[str, Any]],
    existing_keys: set[tuple[str, str]],
    as_of: str,
    price_loader: Callable[[str, str], Any],
    t1_session_of: Callable[[str], str | None],
    threshold: float = GAP_HIGH_THRESHOLD,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """为尚无影子记录的 BUY 构建 T+1 gap 归属记录 (纯装配, 不写盘).

    幂等键 ``(signal_date, ticker)`` 首观察赢; 全帧不可得 → 重试不落盘;
    T+1 bar / signal 日 bar 缺失 → 永久具名事实 (would_skip=None).
    返回 ``(records, summary)``; summary 计数具名, 恒等式:
    considered = already_recorded + future + retried + len(records).
    """
    records: list[dict[str, Any]] = []
    summary = {
        "considered": 0,
        "already_recorded": 0,
        "future": 0,
        "retried": 0,
        GAP_STATUS_OBSERVED: 0,
        GAP_STATUS_T1_BAR_MISSING: 0,
        GAP_STATUS_PREV_CLOSE_MISSING: 0,
        GAP_STATUS_NON_POSITIVE_PRICE: 0,
    }
    seen: set[tuple[str, str]] = set()
    for rec in buy_records:
        if not isinstance(rec, dict) or str(rec.get("action", "")) != "BUY":
            continue
        signal_date = str(rec.get("date", ""))
        ticker = str(rec.get("ticker", ""))
        key = (signal_date, ticker)
        if key in seen:
            continue  # 历史 journal 重复 BUY 只处理首条 (镜像 close_matured 口径)
        seen.add(key)
        summary["considered"] += 1
        if key in existing_keys:
            summary["already_recorded"] += 1
            continue
        if not signal_date or not ticker or str(signal_date) >= str(as_of):
            summary["future"] += 1
            continue

        base = {
            "signal_date": signal_date,
            "ticker": ticker,
            "setup": str(rec.get("setup", "")),
            "horizon": int(rec.get("horizon", 10) or 10),
            "threshold": threshold,
        }
        try:
            prices_df = price_loader(ticker, str(as_of))
        except Exception:
            prices_df = None  # 装载失败与帧缺失同语义: 数据未就绪, 重试
        dates = _frame_date_strings(prices_df)
        if dates is None:
            summary["retried"] += 1
            continue

        matches = [i for i, d in enumerate(dates) if d == signal_date]
        if not matches:
            records.append({**base, "gap_pct": None,
                            "gap_status": GAP_STATUS_PREV_CLOSE_MISSING, "would_skip": None})
            summary[GAP_STATUS_PREV_CLOSE_MISSING] += 1
            continue
        trigger_idx = matches[0]

        t1 = t1_session_of(signal_date)
        if not t1:
            summary["retried"] += 1  # 日历未就绪是接线态, 不是市场事实
            continue
        t1_matches = [i for i, d in enumerate(dates) if d == t1]
        if not t1_matches:
            records.append({**base, "gap_pct": None,
                            "gap_status": GAP_STATUS_T1_BAR_MISSING, "would_skip": None})
            summary[GAP_STATUS_T1_BAR_MISSING] += 1
            continue

        gap = open_gap_pct(
            _frame_value_at(prices_df, trigger_idx, "close"),
            _frame_value_at(prices_df, t1_matches[0], "open"),
        )
        if gap is None:
            records.append({**base, "gap_pct": None,
                            "gap_status": GAP_STATUS_NON_POSITIVE_PRICE, "would_skip": None})
            summary[GAP_STATUS_NON_POSITIVE_PRICE] += 1
            continue
        records.append({**base, "gap_pct": gap,
                        "gap_status": GAP_STATUS_OBSERVED, "would_skip": would_skip(gap, threshold)})
        summary[GAP_STATUS_OBSERVED] += 1
    return records, summary


def load_shadow_entries(path: Path | str) -> list[dict[str, Any]]:
    """读影子 journal 全部记录; 文件缺失 → []; 结构损坏 → 类型化异常 (不静默)."""
    p = Path(path)
    if not p.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GapShadowJournalError(f"gap_shadow_journal_corrupt: line {line_no}: {exc}") from exc
        if not isinstance(rec, dict) or any(k not in rec for k in _REQUIRED_RECORD_KEYS):
            raise GapShadowJournalError(f"gap_shadow_journal_corrupt: line {line_no}: schema")
        entries.append(rec)
    return entries


def shadow_keys(entries: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(str(e.get("signal_date", "")), str(e.get("ticker", ""))) for e in entries}


def append_shadow_records(path: Path | str, records: Sequence[dict[str, Any]]) -> int:
    """append-only 落盘; 有损坏既有行时先 fail-closed 再写 (绝不静默覆盖)."""
    if not records:
        return 0
    p = Path(path)
    if p.exists():
        load_shadow_entries(p)  # 损坏即抛, 不写
    with open(p, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(records)
