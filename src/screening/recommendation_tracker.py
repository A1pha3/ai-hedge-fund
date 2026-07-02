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

import fcntl
import json
import logging
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from src.utils.numeric import optional_float as _optional_float
from src.utils.numeric import safe_float as _safe_float

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

#: T+N 默认阈值 (单位: 交易日数) — P5-1: 扩展到 30 天; Phase 1: 加 T+15/T+25
DEFAULT_HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 15, 20, 25, 30)

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
        next_10day_return: T+10 收益率 (%, 可正可负); 缺失时为 ``None``
        next_15day_return: T+15 收益率 (%, 可正可负); 缺失时为 ``None``
        next_20day_return: T+20 收益率 (%, 可正可负); 缺失时为 ``None``
        next_25day_return: T+25 收益率 (%, 可正可负); 缺失时为 ``None``
        next_30day_return: T+30 收益率 (%, 可正可负); 缺失时为 ``None``
        tracking_status: 状态: ``"pending"`` / ``"partial"`` / ``"complete"``
        model_version: NS-2 模型版本标识 (git short sha, 来自 auto_screening
            payload 顶层); 旧记录无此字段默认 ``""``
        score_decomposition: NS-6 因子瀑布 (per-strategy T/MR/F/E 贡献 + attention
            + stability + consensus + other + total), 来自 main.py 注入的
            ``signal_fusion.compute_score_decomposition`` 输出; 旧记录/未注入时
            ``None``, 让 ``factor_attribution`` 模块在消费侧 isinstance 校验后
            返回 insufficient (向后兼容)
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
    next_10day_return: float | None = None
    next_15day_return: float | None = None
    next_20day_return: float | None = None
    next_25day_return: float | None = None
    next_30day_return: float | None = None
    tracking_status: str = "pending"
    # NS-2: 模型版本标识 (来自 auto_screening payload 顶层), 让诊断模块按版本
    # 分组区分老/新模型效果。旧 tracking_history 记录无此字段 → 默认 ""。
    model_version: str = ""
    # NS-6: 因子瀑布 (per-strategy T/MR/F/E 贡献 + attention/stability/consensus/
    # other/total), 来自 signal_fusion.compute_score_decomposition。让 factor_
    # attribution 模块按贡献分位检测高低 winrate 倒挂。旧 tracking_history 记录
    # 无此字段 → 默认 None (而非 {}), 让消费侧 isinstance(decomp, dict) 校验失败
    # 时返回 insufficient, 保持持久化层与计算层解耦。
    score_decomposition: dict[str, Any] | None = None
    # NS-30/R6-route-A (loop 29): profit-aware 排序键字段, frozen at scoring time.
    # 让未来成熟日期的 A/B 在 compute_selection_profitability_from_loaded 里重建
    # ``--profit-aware`` 排序 (按经验 winrate 重排) on honest PIT data (评分时刻
    # winrate frozen = 正确 point-in-time, 避免 look-ahead bias). 旧记录 → None.
    # composite_score 与 recommendation_score(=score_b) 并存: profit-aware 键的
    # tiebreaker 顺序是 (-winrate, -expected_return, -bucket_sample_count,
    # -composite_score, -score_b, ticker) — 见 top_picks._apply_consecutive_bonus_and_resort.
    # 不验证 dict 内部 schema (win_rates 的 t5/t10 键等); 消费侧 (未来 A/B 策略)
    # isinstance/键存在性校验, 保持持久化层与计算层解耦 (镜像 NS-6 模式).
    composite_score: float | None = None
    win_rates: dict[str, Any] | None = None
    expected_returns: dict[str, Any] | None = None
    bucket_sample_count: int | None = None

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
            next_10day_return=_optional_float(payload.get("next_10day_return")),
            next_15day_return=_optional_float(payload.get("next_15day_return")),
            next_20day_return=_optional_float(payload.get("next_20day_return")),
            next_25day_return=_optional_float(payload.get("next_25day_return")),
            next_30day_return=_optional_float(payload.get("next_30day_return")),
            tracking_status=str(payload.get("tracking_status", "pending") or "pending"),
            model_version=str(payload.get("model_version", "") or ""),
            score_decomposition=payload.get("score_decomposition"),
            composite_score=_optional_float(payload.get("composite_score")),
            win_rates=payload.get("win_rates"),
            expected_returns=payload.get("expected_returns"),
            bucket_sample_count=payload.get("bucket_sample_count"),
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


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


def _load_auto_screening_payload(
    reports_dir: Path,
    as_of_date: str,
) -> dict[str, Any] | None:
    """读取 ``auto_screening_{as_of_date}.json`` 并返回顶层 payload dict。

    报告缺失 / 损坏 / 日期无效时返回 ``None`` (不抛异常)。
    被 :func:`load_pending_recommendations` 与
    :func:`load_pending_recommendations_with_version` 共享。
    """
    cleaned_date = str(as_of_date).replace("-", "").strip()
    if len(cleaned_date) != 8 or not cleaned_date.isdigit():
        logger.warning("[Tracking] 无效的 as_of_date: %s", as_of_date)
        return None

    report_path = reports_dir / f"auto_screening_{cleaned_date}.json"
    if not report_path.exists():
        logger.info("[Tracking] 报告不存在: %s", report_path)
        return None

    try:
        with open(report_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[Tracking] 报告解析失败 %s: %s", report_path, exc)
        return None

    if not isinstance(payload, dict):
        logger.warning("[Tracking] 报告 %s 顶层不是 dict", report_path)
        return None
    return payload


def _extract_recommendations(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """从 payload 抽取 recommendations list; 非法时返回 ``[]``。"""
    if payload is None:
        return []
    recs = payload.get("recommendations") or []
    if not isinstance(recs, list):
        logger.warning("[Tracking] recommendations 不是 list")
        return []
    return recs


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
    return _extract_recommendations(_load_auto_screening_payload(reports_dir, as_of_date))


def load_pending_recommendations_with_version(
    reports_dir: Path,
    as_of_date: str,
) -> tuple[list[dict[str, Any]], str]:
    """NS-2: 读取 Top N 推荐 + payload 顶层的 ``model_version``。

    与 :func:`load_pending_recommendations` 同源, 额外返回 payload 顶层的
    ``model_version`` (旧报告无此字段 → ``""``), 让
    :func:`update_tracking_history` 把版本写入每条 :class:`TrackingRecord`。

    Args:
        reports_dir: ``data/reports`` 目录
        as_of_date: 推荐日期 (YYYYMMDD)

    Returns:
        ``(recommendations, model_version)`` — 报告缺失/损坏时 ``([], "")``
    """
    payload = _load_auto_screening_payload(reports_dir, as_of_date)
    recs = _extract_recommendations(payload)
    version = ""
    if payload is not None:
        version = str(payload.get("model_version", "") or "")
    return recs, version


def _default_price_fetcher(ticker: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """默认价格获取 — 调用 ``src.tools.akshare_api.get_prices``。

    真实环境下会拉取 tushare / akshare; 测试时应注入 ``use_data_fetcher``。
    """
    try:
        from src.tools.akshare_api import get_prices

        prices = get_prices(ticker, start_date, end_date, period="daily")
    except Exception as exc:  # pragma: no cover - 网络路径
        logger.debug("[Tracking] 默认 fetcher 拉取 %s 失败: %s", ticker, exc)
        prices = []

    # R164: akshare 返回空 (代理/网络失败 — 生产环境 eastmoney 代理墙) 时回退到
    # TushareDataSource (已修复 R162 kwargs + R163 ticker-parse, live 路径可用)。
    # 否则 realized-returns backfill 永远拿不到数据 → calibration/reconcile 饿死。
    if not prices:
        try:
            from src.tools.ashare_data_sources import TushareDataSource

            prices = TushareDataSource.get_prices(ticker, start_date, end_date)
        except Exception as exc:  # pragma: no cover - 网络路径
            logger.debug("[Tracking] tushare 回退拉取 %s 失败: %s", ticker, exc)
            prices = []

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

    # 拉取区间需要至少 +30 个交易日; 折算为 45 个日历日以容错
    from_dt = _parse_date(cleaned_from)
    to_dt = _parse_date(cleaned_to)
    if from_dt is None or to_dt is None:
        return {}
    to_dt_extended = to_dt + timedelta(days=45)
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
    # c292 精确化 (文件级 flock 纵深): 守 read-modify-write 临界区, 防止锁外 caller
    # (backfill 脚本 / launcher Step 2) 并发导致 lost-update (后写覆盖先写, 丢 Phase 2
    # 回填的 T+30 returns)。c292 flock 守 --auto 流程内; 本锁守 tracking_history 文件
    # 本身, 不依赖 caller 协调。flock 进程退出自动释放 (crash-safe, kill -9 无 stale-lock)。
    history_path.parent.mkdir(parents=True, exist_ok=True)
    _lock_fd = os.open(history_path.with_suffix(".json.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX)  # 阻塞直到拿到排他锁
        return _update_tracking_history_locked(history_path, trade_date, history_filename, use_data_fetcher)
    finally:
        # finally 释放: 正常返回 / 异常 / Ctrl-C 都释放 fd (flock 随 fd close 自动释放)
        try:
            os.close(_lock_fd)
        except OSError:
            pass


def _update_tracking_history_locked(
    history_path: Path,
    trade_date: str,
    history_filename: str,
    use_data_fetcher: Callable[[str, str, str], list[dict[str, Any]]] | None,
) -> int:
    """update_tracking_history 的临界区主体 (调用方已持 flock)。"""
    reports_dir = history_path.parent
    history = _load_history(history_path)
    history_index: dict[tuple[str, str], dict[str, Any]] = {_record_key(r): r for r in history}

    updated_count = 0

    # ----- Phase 1: 处理 trade_date 当日报告, 加入新推荐 -----
    # NS-2: 同时读 payload 顶层的 model_version, 注入每条 TrackingRecord
    pending, model_version = load_pending_recommendations_with_version(reports_dir, trade_date)
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
        # NS-6: 落盘 main.py 注入的 score_decomposition (因子瀑布), 让
        # factor_attribution 模块按贡献分位检测高低 winrate 倒挂。rec 无此字段
        # 时 None (向后兼容旧 rec / selected_strategies 分支未注入路径).
        decomp = rec.get("score_decomposition")
        if not isinstance(decomp, dict):
            decomp = None
        # NS-30/R6-route-A (loop 29): persist profit-aware 排序键 (win_rates /
        # expected_returns / bucket_sample_count / composite_score) frozen at scoring
        # time, 让未来成熟日期 A/B 重建 --profit-aware 排序. rec 无字段时 None
        # (旧 auto_screening / 未注入路径 向后兼容). dict 字段非 dict → None 防
        # schema 污染; bucket_sample_count 仅接受数值 (排除 bool).
        _wr = rec.get("win_rates")
        _er = rec.get("expected_returns")
        _bsc = rec.get("bucket_sample_count")
        record = TrackingRecord(
            ticker=ticker,
            name=str(rec.get("name", "") or ""),
            recommended_date=trade_date,
            recommended_price=price,
            recommendation_score=score_b,
            tracking_status="pending",
            model_version=model_version,
            score_decomposition=decomp,
            composite_score=_optional_float(rec.get("composite_score")),
            win_rates=_wr if isinstance(_wr, dict) else None,
            expected_returns=_er if isinstance(_er, dict) else None,
            bucket_sample_count=int(_bsc)
            if isinstance(_bsc, (int, float)) and not isinstance(_bsc, bool)
            else None,
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
            # 已有的 T+30 收益非空 → 标记 complete, 跳过查询
            if rec.get("next_30day_return") is not None and status != "complete":
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
                    # BH-008: merge, not overwrite. A re-run whose fetcher returns a
                    # shorter series (delisted/halted ticker, data-source hiccup)
                    # would previously clobber an already-realized return with None,
                    # demoting a mature record and corrupting the win-rate pool.
                    # Only adopt a fetched value when it is present; keep the
                    # existing realized value otherwise.
                    changed = False
                    for field_key, day_key in (
                        ("next_day_return", "day_1"),
                        ("next_3day_return", "day_3"),
                        ("next_5day_return", "day_5"),
                        ("next_10day_return", "day_10"),
                        ("next_15day_return", "day_15"),
                        ("next_20day_return", "day_20"),
                        ("next_25day_return", "day_25"),
                        ("next_30day_return", "day_30"),
                    ):
                        fetched = returns.get(day_key)
                        if fetched is not None:
                            if target.get(field_key) != fetched:
                                target[field_key] = fetched
                                changed = True
                        # If fetched is None, keep the existing value (no clobber).
                    # 同步未来价字段 — 来自 fetcher 的隐含信息 (非 T+1)
                    # 保持 next_day_price 为 None (我们只关心收益率), 简化存储
                    has_t1 = target.get("next_day_return") is not None
                    has_t30 = target.get("next_30day_return") is not None
                    if has_t30:
                        target["tracking_status"] = "complete"
                    elif has_t1:
                        target["tracking_status"] = "partial"
                    else:
                        target["tracking_status"] = "pending"
                    if changed:
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


def _latest_recommended_date(history: list[dict[str, Any]]) -> datetime | None:
    """Most recent ``recommended_date`` in ``history``; None if unparseable.

    Used as a deterministic lookback anchor instead of ``datetime.now()`` so
    the window is relative to the data's own time, not the machine clock.
    See CAMPAIGN2-BH-7.
    """
    latest: datetime | None = None
    for rec in history:
        dt = _parse_date(str(rec.get("recommended_date", "") or ""))
        if dt is not None and (latest is None or dt > latest):
            latest = dt
    return latest


def _summarize_history(
    history: list[dict[str, Any]],
    lookback_days: int,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """根据 history 列表计算汇总统计。

    Args:
        history: 全部记录列表
        lookback_days: 仅统计近 N 天 (含) 的推荐; <=0 表示全部
        as_of: lookback 窗口的参考时刻。

            CAMPAIGN2-BH-7: lookback 此前锚定机器墙钟 ``datetime.now()``，
            而模块其余部分是确定性的 (基于 ``trade_date``)。回填历史推荐时，
            若墙钟已远晚于推荐日，回填记录会被静默丢出 lookback 窗口，
            即使它已有成熟 T+30 收益。显式传 ``as_of`` (通常 = 报告 trade_date)
            让统计可复现且不丢回填数据。

            R62 / BH-026: 即便调用方不传 ``as_of``（默认 None），lookback
            窗口也应锚定到历史记录的最新 ``recommended_date``（data-anchored），
            而非墙钟 ``datetime.now()``。两个 live CLI 入口（``run_tracking_summary``
            / ``--auto`` 的 ``get_tracking_summary``）此前从不传 ``as_of``，导致
            回填/历史分析（如 2026-01 backfilled tracking_history.json 在 2026-06
            墙钟下跑 ``--tracking-summary --lookback=30``）静默丢弃全部记录。
            与 R36 / R54 / R61 wall-clock-anchored lookback 同族修复对称；仅当历史
            记录无可解析日期时回退 ``datetime.now()``（live 兜底，保持旧行为）。

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
    # R62 / BH-026: 默认锚点优先级 显式 as_of > 历史记录最新 recommended_date
    # (data-anchored, 与 R36/R54/R61 同族一致) > 墙钟 now() (live 兜底)。
    if as_of is not None:
        today = as_of
    else:
        today = _latest_recommended_date(history) or datetime.now()
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

    bucket_fields = {
        1: "next_day_return",
        3: "next_3day_return",
        5: "next_5day_return",
        10: "next_10day_return",
        15: "next_15day_return",
        20: "next_20day_return",
        25: "next_25day_return",
        30: "next_30day_return",
    }
    bucket_stats = {day: _bucket(field) for day, field in bucket_fields.items()}

    summary = {
        "lookback_days": lookback_days,
        "total_recommendations": total,
        "tracked_count": bucket_stats[1][1],
    }
    for day, (wins, tracked, win_rate, avg_ret) in bucket_stats.items():
        summary[f"win_count_day{day}"] = wins
        summary[f"tracked_count_day{day}"] = tracked
        summary[f"win_rate_day{day}"] = win_rate
        summary[f"avg_return_day{day}"] = avg_ret
    return summary


def render_tracking_summary(
    history_path: Path,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    as_of: datetime | None = None,
) -> str:
    """生成追踪总结: 近 N 天推荐胜率 + 平均 T+1/T+3/T+5 收益。

    Args:
        history_path: ``tracking_history.json`` 路径
        lookback_days: 回溯天数 (默认 30)
        as_of: lookback 窗口参考时刻。

            CAMPAIGN2-BH-7: 回填历史推荐时显式传 ``as_of = 报告 trade_date``，
            否则锚点回退到默认值。

            R62 / BH-026: ``as_of=None`` 默认锚定到历史记录最新 ``recommended_date``
            (data-anchored)，而非墙钟 ``datetime.now()`` —— 回填/历史分析不再静默
            丢出窗口。详见 ``_summarize_history``。

    Returns:
        多行字符串, 含胜率与平均收益; 无数据时返回提示行。
    """
    history = _load_history(history_path)
    if not history:
        return f"暂无追踪历史 (请先运行 --auto 至少一次): {history_path}\n"

    summary = _summarize_history(history, lookback_days=lookback_days, as_of=as_of)
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
    for day in DEFAULT_HORIZONS:
        tracked = summary[f"tracked_count_day{day}"]
        if tracked > 0:
            lines.append(
                f"  T+{day} 胜率: {_fmt_pct(summary[f'win_rate_day{day}'])} "
                f"({summary[f'win_count_day{day}']}/{tracked})"
            )
        else:
            lines.append(f"  T+{day} 胜率: 数据尚未到期")
    for day in DEFAULT_HORIZONS:
        lines.append(f"  T+{day} 平均收益: {_fmt_ret(summary[f'avg_return_day{day}'])}")
    return "\n".join(lines) + "\n"


def get_tracking_summary(
    history_path: Path,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """以 dict 形式返回追踪汇总 — 便于 JSON payload 集成。

    Args:
        history_path: ``tracking_history.json`` 路径
        lookback_days: 回溯天数 (默认 30)
        as_of: lookback 窗口参考时刻。

            CAMPAIGN2-BH-7: 回填时显式传 ``as_of = 报告 trade_date`` 让窗口
            相对于数据时间而非墙钟，避免回填记录被静默丢出。

            R62 / BH-026: ``as_of=None`` 默认锚定到历史记录最新 ``recommended_date``
            (data-anchored)，而非墙钟 ``datetime.now()`` —— 回填/历史分析不再静默
            丢出窗口。详见 ``_summarize_history``。

    Returns:
        详见 ``_summarize_history``。当历史为空时, ``total_recommendations=0``。
    """
    history = _load_history(history_path)
    return _summarize_history(history, lookback_days=lookback_days, as_of=as_of)
