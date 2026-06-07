"""P1-3 推荐标的自动追踪 — 每次 ``--auto`` 后自动记录 Top N 标的，次日盘后自动计算实际收益。

设计目标:
- **零配置** — 用户跑 ``--auto`` 后自动累积追踪数据，无需手动触发 lookback audit
- **轻量存储** — 追加式 JSON 历史 (``tracking_history.json``)，按 ``(ticker, recommended_date)`` 幂等
- **可插拔价格源** — ``fetch_actual_returns`` 接受可注入的 ``use_data_fetcher`` 回调，便于测试
- **优雅降级** — 历史文件损坏 / 报告缺失 / 价格缺失一律返回 ``None`` 或空列表，不抛出

典型用法:

    from src.screening.recommendation_tracker import (
        update_tracking_history,
        render_tracking_summary,
    )

    # 每次 --auto 末尾调用
    updated = update_tracking_history(reports_dir, trade_date=trade_date)

    # CLI 入口
    uv run python src/main.py --tracking-summary --tracking-lookback=30
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: 历史文件名
HISTORY_FILENAME: str = "tracking_history.json"

#: 推荐日报告文件名模式
REPORT_PATTERN = re.compile(r"^auto_screening_(\d{8})\.json$")

#: 默认回溯天数
DEFAULT_LOOKBACK_DAYS: int = 30

#: T+N 默认阈值 (单位: 交易日数)
DEFAULT_HORIZONS: tuple[int, ...] = (1, 3, 5)

#: 当日报告 Top N 推荐提取数量
DEFAULT_TOP_N: int = 10


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class TrackingRecord:
    """单次推荐的追踪记录。

    Attributes:
        ticker: 6 位 A 股代码
        name: 股票名 (可能为空)
        recommended_date: 推荐日 (YYYYMMDD)
        recommended_price: 推荐日收盘价
        recommendation_score: score_b (范围 [-1, +1])
        next_day_price: T+1 收盘价; 缺失时为 ``None``
        next_day_return: T+1 收益率 (%, 可正可负); 缺失时为 ``None``
        next_3day_return: T+3 收益率 (%, 可正可负); 缺失时为 ``None``
        next_5day_return: T+5 收益率 (%, 可正可负); 缺失时为 ``None``
        tracking_status: 状态: ``"pending"`` / ``"partial"`` / ``"complete"``
    """

    ticker: str
    name: str
    recommended_date: str
    recommended_price: float
    recommendation_score: float
    next_day_price: float | None = None
    next_day_return: float | None = None
    next_3day_return: float | None = None
    next_5day_return: float | None = None
    tracking_status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TrackingRecord":
        """从 dict 反序列化 (允许字段缺失, 默认填充)。"""
        return cls(
            ticker=str(payload.get("ticker", "") or ""),
            name=str(payload.get("name", "") or ""),
            recommended_date=str(payload.get("recommended_date", "") or ""),
            recommended_price=_safe_float(payload.get("recommended_price"), default=0.0),
            recommendation_score=_safe_float(payload.get("recommendation_score"), default=0.0),
            next_day_price=_optional_float(payload.get("next_day_price")),
            next_day_return=_optional_float(payload.get("next_day_return")),
            next_3day_return=_optional_float(payload.get("next_3day_return")),
            next_5day_return=_optional_float(payload.get("next_5day_return")),
            tracking_status=str(payload.get("tracking_status", "pending") or "pending"),
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    """将 value 转为有限 float; 异常值返回 default。"""
    if value is None:
        return default
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(fv):
        return default
    return fv


def _optional_float(value: Any) -> float | None:
    """将 value 转为有限 float 或 ``None``。"""
    if value is None:
        return None
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(fv):
        return None
    return fv


def _parse_date(date_str: str) -> datetime | None:
    """YYYYMMDD / YYYY-MM-DD → ``datetime``; 失败返回 ``None``。"""
    if not date_str:
        return None
    cleaned = str(date_str).replace("-", "").strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        return None
    try:
        return datetime.strptime(cleaned, "%Y%m%d")
    except ValueError:
        return None


def _format_date(dt: datetime) -> str:
    """``datetime`` → YYYYMMDD。"""
    return dt.strftime("%Y%m%d")


def _coerce_recommended_price(rec: dict[str, Any]) -> float:
    """从推荐字典中安全提取推荐日价格, 失败返回 0.0。

    支持字段 (按优先级):
        - ``recommended_price`` (直接提供)
        - ``entry_price`` (与 lookback_audit 一致)
        - ``close`` (推荐时点的收盘价)
    """
    for key in ("recommended_price", "entry_price", "close"):
        if key in rec and rec[key] is not None:
            price = _safe_float(rec.get(key), default=0.0)
            if price > 0:
                return price
    return 0.0


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def load_pending_recommendations(
    reports_dir: Path,
    as_of_date: str,
) -> list[dict[str, Any]]:
    """从 ``data/reports/auto_screening_{as_of_date}.json`` 读取 Top N 推荐。

    Args:
        reports_dir: ``data/reports`` 目录
        as_of_date: 推荐日期 (YYYYMMDD)

    Returns:
        ``recommendations`` 字段列表 (可能为空 — 当报告缺失或损坏时)
    """
    cleaned_date = str(as_of_date).replace("-", "").strip()
    if len(cleaned_date) != 8 or not cleaned_date.isdigit():
        logger.warning("[Tracking] 无效的 as_of_date: %s", as_of_date)
        return []

    report_path = reports_dir / f"auto_screening_{cleaned_date}.json"
    if not report_path.exists():
        logger.info("[Tracking] 报告不存在: %s", report_path)
        return []

    try:
        with open(report_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[Tracking] 报告解析失败 %s: %s", report_path, exc)
        return []

    recs = payload.get("recommendations") or []
    if not isinstance(recs, list):
        logger.warning("[Tracking] 报告 %s 的 recommendations 不是 list", report_path)
        return []
    return recs


def _default_price_fetcher(ticker: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """默认价格获取 — 调用 ``src.tools.akshare_api.get_prices``。

    真实环境下会拉取 tushare / akshare; 测试时应注入 ``use_data_fetcher``。
    """
    try:
        from src.tools.akshare_api import get_prices

        prices = get_prices(ticker, start_date, end_date, period="daily")
    except Exception as exc:  # pragma: no cover - 网络路径
        logger.debug("[Tracking] 默认 fetcher 拉取 %s 失败: %s", ticker, exc)
        return []

    result: list[dict[str, Any]] = []
    for p in prices:
        # Price 是 dataclass / 对象 — 兼容 dict 和对象两种形式
        if isinstance(p, dict):
            time_str = str(p.get("time") or p.get("date") or "")
            close = p.get("close")
        else:
            time_str = str(getattr(p, "time", "") or getattr(p, "date", "") or "")
            close = getattr(p, "close", None)
        result.append({"time": time_str, "close": _safe_float(close, default=0.0)})
    return result


def fetch_actual_returns(
    tickers: list[str],
    from_date: str,
    to_date: str,
    *,
    use_data_fetcher: Callable[[str, str, str], list[dict[str, Any]]] | None = None,
) -> dict[str, dict[str, float]]:
    """从 tushare/akshare 拉取指定区间每日收盘价，计算 T+1/T+3/T+5 收益。

    Args:
        tickers: 股票代码列表
        from_date: 起始日期 (YYYYMMDD 或 YYYY-MM-DD)
        to_date: 结束日期 (YYYYMMDD 或 YYYY-MM-DD) — 须 >= from_date + 5 天
        use_data_fetcher: 可选注入 — ``(ticker, start, end) -> [{"time": ..., "close": ...}, ...]``。
            测试时应注入 mock fetcher, 避免真实网络调用。

    Returns:
        ``{ticker: {"day_1": <pct>, "day_3": <pct>, "day_5": <pct>}}`` (缺失字段为 ``None``)。
        数据不足或异常时该 ticker 不出现在结果中 (或仅含部分字段)。
    """
    fetcher = use_data_fetcher or _default_price_fetcher
    cleaned_from = str(from_date).replace("-", "").strip()
    cleaned_to = str(to_date).replace("-", "").strip()

    # 拉取区间需要至少 +5 个交易日; 折算为 10 个日历日以容错
    from_dt = _parse_date(cleaned_from)
    to_dt = _parse_date(cleaned_to)
    if from_dt is None or to_dt is None:
        return {}
    to_dt_extended = to_dt + timedelta(days=10)
    extended_to = _format_date(to_dt_extended)

    result: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        if not ticker:
            continue
        try:
            raw = fetcher(ticker, cleaned_from, extended_to) or []
        except Exception as exc:  # pragma: no cover - 异常路径
            logger.debug("[Tracking] fetcher 异常 ticker=%s: %s", ticker, exc)
            continue
        closes = _extract_sorted_closes(raw, base_date=cleaned_from)
        if not closes:
            continue
        # 基准价: 推荐日当天或之后第一个交易日
        base_close = closes[0][1]
        if base_close <= 0:
            continue
        ticker_returns: dict[str, float] = {}
        for horizon in DEFAULT_HORIZONS:
            if len(closes) > horizon:
                future_close = closes[horizon][1]
                if future_close > 0:
                    ret_pct = (future_close - base_close) / base_close * 100.0
                    ticker_returns[f"day_{horizon}"] = round(ret_pct, 4)
        if ticker_returns:
            result[ticker] = ticker_returns
    return result


def _extract_sorted_closes(
    raw: list[dict[str, Any]],
    base_date: str,
) -> list[tuple[str, float]]:
    """从 fetcher 原始数据中提取 (date, close) 列表, 按日期升序, 过滤非有限 / 零值。

    Args:
        raw: fetcher 返回的 ``[{"time": "YYYY-MM-DD", "close": float}, ...]``
        base_date: 推荐日 (YYYYMMDD); 只保留 >= base_date 的数据点

    Returns:
        按日期升序的 ``[(date_str_8, close), ...]``; 空值 / 0 / 非有限被剔除
    """
    base_dt = _parse_date(base_date)
    if base_dt is None:
        return []

    out: list[tuple[str, float]] = []
    for row in raw:
        time_str = str(row.get("time", "") or row.get("date", "") or "").strip()
        if not time_str:
            continue
        row_dt = _parse_date(time_str)
        if row_dt is None or row_dt < base_dt:
            continue
        close = _safe_float(row.get("close"), default=0.0)
        if close <= 0:
            continue
        out.append((_format_date(row_dt), close))

    out.sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------------------
# History management
# ---------------------------------------------------------------------------


def _load_history(history_path: Path) -> list[dict[str, Any]]:
    """读取 tracking_history.json; 缺失/损坏返回空列表 (优雅降级)。"""
    if not history_path.exists():
        return []
    try:
        with open(history_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[Tracking] history 解析失败 %s: %s — 重置为空", history_path, exc)
        return []
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    return records


def _save_history(history_path: Path, records: list[dict[str, Any]]) -> None:
    """写入 tracking_history.json (原子写: 写临时文件后 rename)。"""
    history_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"records": records, "updated_at": datetime.now().strftime("%Y%m%d%H%M%S")}
    tmp_path = history_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    tmp_path.replace(history_path)


def _record_key(rec: dict[str, Any]) -> tuple[str, str]:
    """record 唯一键: (ticker, recommended_date)。"""
    return (str(rec.get("ticker", "") or ""), str(rec.get("recommended_date", "") or ""))


def update_tracking_history(
    reports_dir: Path,
    trade_date: str,
    *,
    history_filename: str = HISTORY_FILENAME,
    use_data_fetcher: Callable[[str, str, str], list[dict[str, Any]]] | None = None,
) -> int:
    """更新追踪历史: 1) 读取 trade_date Top N, 2) 与历史对比, 3) 拉取价格, 4) 落盘。

    幂等: 同一 (ticker, recommended_date) 多次调用不会重复记录。

    Args:
        reports_dir: ``data/reports`` 目录
        trade_date: 当前交易日期 (YYYYMMDD)
        history_filename: 历史文件名
        use_data_fetcher: 可选注入 (测试用)

    Returns:
        本次实际写入 / 更新的记录数 (新增 + 更新 T+1/T+3/T+5 收益的合计)
    """
    history_path = reports_dir / history_filename
    history = _load_history(history_path)
    history_index: dict[tuple[str, str], dict[str, Any]] = {_record_key(r): r for r in history}

    updated_count = 0

    # ----- Phase 1: 处理 trade_date 当日报告, 加入新推荐 -----
    pending = load_pending_recommendations(reports_dir, trade_date)
    for rec in pending:
        ticker = str(rec.get("ticker", "") or "").strip()
        if not ticker:
            continue
        key = (ticker, trade_date)
        if key in history_index:
            # 已存在 (例如用户重复运行) — 跳过
            continue
        price = _coerce_recommended_price(rec)
        score_b = _safe_float(rec.get("score_b"), default=0.0)
        record = TrackingRecord(
            ticker=ticker,
            name=str(rec.get("name", "") or ""),
            recommended_date=trade_date,
            recommended_price=price,
            recommendation_score=score_b,
            tracking_status="pending",
        )
        history_index[key] = record.to_dict()
        updated_count += 1

    # ----- Phase 2: 对历史 pending / partial 记录尝试拉取收益 -----
    today_dt = _parse_date(trade_date)
    if today_dt is not None:
        to_query: list[dict[str, Any]] = []
        for rec in history_index.values():
            status = rec.get("tracking_status", "pending")
            if status == "complete":
                continue
            rec_date = str(rec.get("recommended_date", "") or "")
            rec_dt = _parse_date(rec_date)
            if rec_dt is None:
                continue
            # 至少 6 天后 (容错: 5 个自然日 + 1) 才尝试拉取
            if (today_dt - rec_dt).days < 6:
                continue
            # 已有的 T+5 收益非空 → 标记 complete
            if rec.get("next_5day_return") is not None and status != "complete":
                rec["tracking_status"] = "complete"
                continue
            to_query.append(rec)

        if to_query:
            # 按推荐日分批拉取, 减少冗余调用
            by_date: dict[str, list[str]] = {}
            for rec in to_query:
                rd = str(rec.get("recommended_date", "") or "")
                by_date.setdefault(rd, []).append(str(rec.get("ticker", "") or ""))
            for rec_date, tickers in by_date.items():
                returns_map = fetch_actual_returns(
                    tickers=tickers,
                    from_date=rec_date,
                    to_date=trade_date,
                    use_data_fetcher=use_data_fetcher,
                )
                for ticker, returns in returns_map.items():
                    key = (ticker, rec_date)
                    target = history_index.get(key)
                    if target is None:
                        continue
                    target["next_day_return"] = returns.get("day_1")
                    target["next_3day_return"] = returns.get("day_3")
                    target["next_5day_return"] = returns.get("day_5")
                    # 同步未来价字段 — 来自 fetcher 的隐含信息 (非 T+1)
                    # 保持 next_day_price 为 None (我们只关心收益率), 简化存储
                    has_t1 = target.get("next_day_return") is not None
                    has_t5 = target.get("next_5day_return") is not None
                    if has_t5:
                        target["tracking_status"] = "complete"
                    elif has_t1:
                        target["tracking_status"] = "partial"
                    else:
                        target["tracking_status"] = "pending"
                    updated_count += 1

    # ----- Phase 3: 落盘 -----
    records = list(history_index.values())
    # 按 recommended_date 降序、ticker 升序排序 — 便于阅读
    records.sort(key=lambda r: (-int(r.get("recommended_date", "0") or 0), str(r.get("ticker", ""))))
    _save_history(history_path, records)
    return updated_count


# ---------------------------------------------------------------------------
# Summary rendering
# ---------------------------------------------------------------------------


def _summarize_history(
    history: list[dict[str, Any]],
    lookback_days: int,
) -> dict[str, Any]:
    """根据 history 列表计算汇总统计。

    Args:
        history: 全部记录列表
        lookback_days: 仅统计近 N 天 (含) 的推荐; <=0 表示全部

    Returns:
        ``{
            "lookback_days": N,
            "total_recommendations": int,
            "tracked_count": int (有 T+1 收益的),
            "win_count_day1": int,
            "win_count_day3": int,
            "win_count_day5": int,
            "win_rate_day1": float | None (0-1),
            "win_rate_day3": float | None,
            "win_rate_day5": float | None,
            "avg_return_day1": float | None,
            "avg_return_day3": float | None,
            "avg_return_day5": float | None,
        }``
    """
    today = datetime.now()
    cutoff: datetime | None = None
    if lookback_days > 0:
        cutoff = today - timedelta(days=lookback_days)

    scoped: list[dict[str, Any]] = []
    for rec in history:
        rec_date = _parse_date(str(rec.get("recommended_date", "") or ""))
        if rec_date is None:
            continue
        if cutoff is not None and rec_date < cutoff:
            continue
        scoped.append(rec)

    total = len(scoped)

    def _bucket(field: str) -> tuple[int, int, float | None, float | None]:
        wins = 0
        tracked = 0
        sum_ret = 0.0
        for rec in scoped:
            v = rec.get(field)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(fv):
                continue
            tracked += 1
            sum_ret += fv
            if fv > 0:
                wins += 1
        win_rate = (wins / tracked) if tracked > 0 else None
        avg_ret = (sum_ret / tracked) if tracked > 0 else None
        return wins, tracked, win_rate, avg_ret

    win1, track1, wr1, ar1 = _bucket("next_day_return")
    win3, track3, wr3, ar3 = _bucket("next_3day_return")
    win5, track5, wr5, ar5 = _bucket("next_5day_return")

    return {
        "lookback_days": lookback_days,
        "total_recommendations": total,
        "tracked_count": track1,
        "win_count_day1": win1,
        "win_count_day3": win3,
        "win_count_day5": win5,
        "tracked_count_day1": track1,
        "tracked_count_day3": track3,
        "tracked_count_day5": track5,
        "win_rate_day1": wr1,
        "win_rate_day3": wr3,
        "win_rate_day5": wr5,
        "avg_return_day1": ar1,
        "avg_return_day3": ar3,
        "avg_return_day5": ar5,
    }


def render_tracking_summary(
    history_path: Path,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> str:
    """生成追踪总结: 近 N 天推荐胜率 + 平均 T+1/T+3/T+5 收益。

    Args:
        history_path: ``tracking_history.json`` 路径
        lookback_days: 回溯天数 (默认 30)

    Returns:
        多行字符串, 含胜率与平均收益; 无数据时返回提示行。
    """
    history = _load_history(history_path)
    if not history:
        return f"暂无追踪历史 (请先运行 --auto 至少一次): {history_path}\n"

    summary = _summarize_history(history, lookback_days=lookback_days)
    total = summary["total_recommendations"]

    if total == 0:
        return f"近 {lookback_days} 天内无推荐记录: {history_path}\n"

    lines: list[str] = []
    lines.append(f"跟踪总结 (近 {lookback_days} 天):")

    def _fmt_pct(value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value * 100:.1f}%"

    def _fmt_ret(value: float | None) -> str:
        if value is None:
            return "—"
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.2f}%"

    lines.append(f"  总推荐: {total} 只")
    # 跟踪覆盖率
    track1 = summary["tracked_count_day1"]
    track3 = summary["tracked_count_day3"]
    track5 = summary["tracked_count_day5"]
    if track1 > 0:
        lines.append(
            f"  T+1 胜率: {_fmt_pct(summary['win_rate_day1'])} "
            f"({summary['win_count_day1']}/{track1})"
        )
    else:
        lines.append("  T+1 胜率: 数据尚未到期")
    if track3 > 0:
        lines.append(
            f"  T+3 胜率: {_fmt_pct(summary['win_rate_day3'])} "
            f"({summary['win_count_day3']}/{track3})"
        )
    else:
        lines.append("  T+3 胜率: 数据尚未到期")
    if track5 > 0:
        lines.append(
            f"  T+5 胜率: {_fmt_pct(summary['win_rate_day5'])} "
            f"({summary['win_count_day5']}/{track5})"
        )
    else:
        lines.append("  T+5 胜率: 数据尚未到期")
    lines.append(f"  T+1 平均收益: {_fmt_ret(summary['avg_return_day1'])}")
    lines.append(f"  T+3 平均收益: {_fmt_ret(summary['avg_return_day3'])}")
    lines.append(f"  T+5 平均收益: {_fmt_ret(summary['avg_return_day5'])}")
    return "\n".join(lines) + "\n"


def get_tracking_summary(
    history_path: Path,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """以 dict 形式返回追踪汇总 — 便于 JSON payload 集成。

    Args:
        history_path: ``tracking_history.json`` 路径
        lookback_days: 回溯天数 (默认 30)

    Returns:
        详见 ``_summarize_history``。当历史为空时, ``total_recommendations=0``。
    """
    history = _load_history(history_path)
    return _summarize_history(history, lookback_days=lookback_days)
