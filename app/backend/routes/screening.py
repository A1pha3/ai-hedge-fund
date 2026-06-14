"""Web 端一键选股端点 — 包装 ``--auto`` 模式为简单的 HTTP API。

P1-5: 用户希望在 Web 端一键运行全市场自动筛选, 获得与 CLI ``--auto``
完全一致的 payload (推荐 / 市场状态 / 行业轮动 / 连续推荐 / 批量统计)。

本端点不重新实现核心筛选逻辑, 而是直接复用
:func:`src.main.compute_auto_screening_results` 纯函数。

P1-8: 新增 ``GET /api/screening/compare`` 端点 — 对 2-5 只标的做
多维度对比, 复用 :func:`src.screening.compare_tool.compare_tickers`。
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.backend.routes._common import safe_route
from src.main import compute_auto_screening_results

router = APIRouter(prefix="/api/screening", tags=["screening"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: 单次请求最长执行时间 — 防止 Web 请求挂死
DEFAULT_TIMEOUT_SECONDS: float = 60.0

#: trade_date 格式校验 — YYYYMMDD 或 YYYY-MM-DD
_TRADE_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$|^(\d{4})-(\d{2})-(\d{2})$")

#: top_n 合法区间
MIN_TOP_N: int = 1
MAX_TOP_N: int = 100

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ScreeningRequest(BaseModel):
    """一键选股请求体。

    Attributes:
        trade_date: 交易日期 (``YYYYMMDD`` 或 ``YYYY-MM-DD``),
            ``None`` 表示取最新可用交易日 (即 ``datetime.now()`` 当天)
        top_n: 返回 Top N 推荐 (1-100, 默认 20)
        score_threshold: 最小 ``score_b`` 阈值 (默认 0.0, 不过滤)
        strategies: 启用的策略列表, ``None`` 表示全部四策略
            (trend / mean_reversion / fundamental / event_sentiment)
        use_explain: 是否在响应中附加因子明细 (默认 True)
    """

    trade_date: str | None = None
    top_n: int = Field(default=20, ge=MIN_TOP_N, le=MAX_TOP_N)
    score_threshold: float = Field(default=0.0, ge=-1.0, le=1.0)
    strategies: list[str] | None = None
    use_explain: bool = True


class ScreeningResponse(BaseModel):
    """一键选股响应体。

    字段命名与 CLI ``--auto`` 报告 JSON 一致, 便于 Web 前端与 CLI
    共享同一份解析代码。
    """

    trade_date: str
    recommendations: list[dict] = Field(default_factory=list)
    market_state: dict | None = None
    tracking_summary: dict | None = None
    consecutive_recommendation: dict | None = None
    industry_rotation: list[dict] | None = None
    execution_time_seconds: float
    batch_data_fetcher: dict | None = None
    signal_decay_summary: dict | None = None
    sector_concentration_warnings: list[str] | None = None
    layer_a_count: int = 0
    total_scored: int = 0
    high_pool_count: int = 0
    top_n: int = 0
    meta: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_trade_date(raw: str | None) -> str:
    """将 ``YYYYMMDD`` / ``YYYY-MM-DD`` 统一为 ``YYYYMMDD`` 格式。

    Raises:
        HTTPException 422: 格式非法
    """
    if raw is None or not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=422, detail="trade_date 不能为空")
    cleaned = raw.strip()
    if not _TRADE_DATE_RE.match(cleaned):
        raise HTTPException(status_code=422, detail=f"trade_date 格式无效: {raw!r} (期望 YYYYMMDD 或 YYYY-MM-DD)")
    # 统一为 YYYYMMDD
    return cleaned.replace("-", "")


def _resolve_default_trade_date() -> str:
    """解析默认 trade_date — 取当前日期 YYYYMMDD。

    注意: 不查交易日历 (避免引入 akshare 依赖, 加重请求);
    若当天为非交易日, 由 ``compute_auto_screening_results`` 内部
    通过数据获取失败来体现。
    """
    return datetime.now().strftime("%Y%m%d")


def _check_tushare_token() -> None:
    """检查 tushare token 是否配置 — 缺失时返回 503。

    Raises:
        HTTPException 503: tushare token 缺失
    """
    token = os.environ.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_API_KEY")
    if not token:
        raise HTTPException(status_code=503, detail="TUSHARE_TOKEN 未配置, 无法运行 A 股一键选股")


def _sanitize_nan(value: Any) -> Any:
    """递归清洗 NaN/Inf 字段, 替换为 None, 保证 JSON 合法。

    ``json.dumps`` 默认会把 ``NaN`` / ``Inf`` 序列化为非标准 JSON (无引号),
    严格 JSON parser (前端 ``JSON.parse``) 会拒绝。统一转为 ``None``。
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: _sanitize_nan(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_nan(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize_nan(v) for v in value]
    return value


def _apply_score_threshold(
    recommendations: list[dict],
    threshold: float,
) -> list[dict]:
    """按 ``score_b >= threshold`` 过滤推荐列表。

    处理 None / NaN / 非数字 score_b 视为不通过 (保守过滤)。
    """
    if threshold <= 0.0:
        return recommendations
    out: list[dict] = []
    for rec in recommendations:
        raw = rec.get("score_b")
        try:
            fv = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isnan(fv) or math.isinf(fv):
            continue
        if fv >= threshold:
            out.append(rec)
    return out


def _attach_explain(
    recommendations: list[dict],
    enabled: bool,
) -> list[dict]:
    """根据 ``use_explain`` 决定是否在响应中保留因子明细。

    当前 ``compute_auto_screening_results`` 已通过 ``strategy_signals``
    内嵌每个策略的 ``sub_factors``, 因此 ``use_explain=False`` 时
    需剔除 ``sub_factors`` 以减小 payload 体积。
    """
    if enabled:
        return recommendations
    trimmed: list[dict] = []
    for rec in recommendations:
        rec_copy = dict(rec)
        signals = rec_copy.get("strategy_signals")
        if isinstance(signals, dict):
            # 必须更新 signals[_name] — 仅重绑定局部 sig 不会影响原 dict
            new_signals: dict = {}
            for name, sig in signals.items():
                if isinstance(sig, dict):
                    new_sig = dict(sig)
                    new_sig.pop("sub_factors", None)
                    new_signals[name] = new_sig
                else:
                    new_signals[name] = sig
            rec_copy["strategy_signals"] = new_signals
        trimmed.append(rec_copy)
    return trimmed


def _validate_strategies(strategies: list[str] | None) -> list[str] | None:
    """校验 strategies 字段, 拒绝非法值。

    合法值: ``trend`` / ``mean_reversion`` / ``fundamental`` / ``event_sentiment``
    """
    if strategies is None:
        return None
    valid = {"trend", "mean_reversion", "fundamental", "event_sentiment"}
    invalid = [s for s in strategies if s not in valid]
    if invalid:
        raise HTTPException(status_code=422, detail=f"未知策略: {invalid} (合法: {sorted(valid)})")
    return strategies


def _load_latest_auto_screening_payload(trade_date: str | None = None) -> dict[str, Any]:
    reports_dir = Path(__file__).resolve().parents[3] / "data" / "reports"
    if trade_date:
        candidates = [reports_dir / f"auto_screening_{trade_date}.json"]
    else:
        candidates = sorted(reports_dir.glob("auto_screening_*.json"), reverse=True)
    for path in candidates:
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"读取选股报告失败: {path.name} ({exc})")
    raise HTTPException(status_code=404, detail=f"未找到 auto_screening 报告 (trade_date={trade_date or 'latest'})")


def _build_screening_response(
    payload: dict[str, Any],
    *,
    trade_date: str,
    score_threshold: float,
    use_explain: bool,
    strategies: list[str] | None,
    execution_time_seconds: float,
) -> ScreeningResponse:
    raw_recs = payload.get("recommendations", []) or []
    recs = _apply_score_threshold(raw_recs, score_threshold)
    recs = _attach_explain(recs, use_explain)
    return ScreeningResponse(
        trade_date=trade_date,
        recommendations=_sanitize_nan(recs),
        market_state=_sanitize_nan(payload.get("market_state")),
        tracking_summary=_sanitize_nan(payload.get("tracking_summary")),
        consecutive_recommendation=_sanitize_nan(payload.get("consecutive_recommendation")),
        industry_rotation=_sanitize_nan(payload.get("industry_rotation")),
        execution_time_seconds=round(execution_time_seconds, 3),
        batch_data_fetcher=_sanitize_nan(payload.get("batch_data_fetcher")),
        signal_decay_summary=_sanitize_nan(payload.get("signal_decay_summary")),
        sector_concentration_warnings=payload.get("sector_concentration_warnings") or [],
        layer_a_count=int(payload.get("layer_a_count", 0) or 0),
        total_scored=int(payload.get("total_scored", 0) or 0),
        high_pool_count=int(payload.get("high_pool_count", 0) or 0),
        top_n=int(payload.get("top_n", len(recs)) or len(recs)),
        meta={
            "score_threshold": score_threshold,
            "use_explain": use_explain,
            "strategies": strategies or ["trend", "mean_reversion", "fundamental", "event_sentiment"],
            "data_dir": str(Path(__file__).resolve().parents[3] / "data" / "reports"),
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    path="/auto",
    response_model=ScreeningResponse,
    responses={
        200: {"description": "成功 — 返回完整推荐 payload"},
        422: {"description": "参数校验失败 (trade_date 格式非法 / 策略非法)"},
        503: {"description": "TUSHARE_TOKEN 缺失 / 候选池为空"},
        504: {"description": "执行超时 (默认 60s)"},
        500: {"description": "其他内部错误"},
    },
)
async def run_auto_screening(req: ScreeningRequest) -> ScreeningResponse:
    """Web 端一键运行全市场自动筛选。

    等价于 CLI::

        uv run python src/main.py --auto --top-n N

    返回完整的推荐结果 + 市场状态 + 行业轮动 + 连续推荐 + 信号衰减
    + 批量获取层统计 + 推荐标的追踪汇总。

    Notes:
        1. 默认超时 60s — 防止 Web 请求挂死
        2. NaN/Inf 字段会被统一替换为 ``None`` (保证 JSON 严格合法)
        3. 复用 :func:`src.main.compute_auto_screening_results` 纯函数
    """
    _check_tushare_token()
    strategies = _validate_strategies(req.strategies)

    # trade_date 解析
    if req.trade_date:
        trade_date = _normalize_trade_date(req.trade_date)
    else:
        trade_date = _resolve_default_trade_date()

    # 复用 main 纯函数 — 顶部已 import, 便于测试 patch
    start = time.monotonic()
    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(
                compute_auto_screening_results,
                trade_date,
                req.top_n,
                selected_strategies=strategies,
            ),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"一键选股超时 (>{DEFAULT_TIMEOUT_SECONDS}s)")
    except ValueError as exc:
        # 候选池为空 — 503 而非 500 (上游数据问题)
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        # 其他内部错误
        raise HTTPException(status_code=500, detail=f"一键选股失败: {exc}")

    return _build_screening_response(
        payload,
        trade_date=trade_date,
        score_threshold=req.score_threshold,
        use_explain=req.use_explain,
        strategies=strategies,
        execution_time_seconds=time.monotonic() - start,
    )


@router.get(
    path="/latest",
    response_model=ScreeningResponse,
    responses={
        200: {"description": "成功 — 返回最近一次 auto_screening payload"},
        404: {"description": "未找到 auto_screening 报告"},
        500: {"description": "报告读取失败"},
    },
)
@safe_route
async def get_latest_screening_result(
    trade_date: str | None = Query(None, description="指定报告日期 YYYYMMDD；缺省返回最新"),
) -> ScreeningResponse:
    cleaned_date = _normalize_trade_date(trade_date) if trade_date else None
    payload = _load_latest_auto_screening_payload(trade_date=cleaned_date)
    resolved_trade_date = str(payload.get("date") or cleaned_date or _resolve_default_trade_date())
    return _build_screening_response(
        payload,
        trade_date=resolved_trade_date,
        score_threshold=0.0,
        use_explain=True,
        strategies=None,
        execution_time_seconds=0.0,
    )


# ---------------------------------------------------------------------------
# P1-8: 标的对比端点
# ---------------------------------------------------------------------------


class CompareResponse(BaseModel):
    """P1-8 标的对比响应体。

    字段命名与 CLI ``--compare`` 输出一致, 便于 Web 前端与 CLI
    共享同一份解析代码。
    """

    tickers: list[str]
    metrics: list[dict[str, Any]]
    summary: dict[str, int]
    winner: str | None = None
    report_date: str | None = None
    meta: dict = Field(default_factory=dict)


@router.get(
    path="/compare",
    response_model=CompareResponse,
    responses={
        200: {"description": "成功 — 返回对比报告"},
        422: {"description": "参数校验失败 (ticker 数量不在 2-5 / 指标非法 / 日期格式错误)"},
        404: {"description": "未找到有效的 auto_screening 报告"},
    },
)
async def compare_endpoint(
    tickers: str = Query(..., description="逗号分隔的 ticker, 2-5 只 (e.g. '300750,600519,000001')"),
    metrics: str | None = Query(None, description="逗号分隔的指标, 缺省全部 (e.g. 'trend_score,score_b')"),
    trade_date: str | None = Query(None, description="报告日期 YYYYMMDD, 缺省取最新"),
) -> CompareResponse:
    """P1-8 Web 端标的对比 API。

    复用 :func:`src.screening.compare_tool.compare_tickers` 计算多维对比,
    数据来源为 ``data/reports/auto_screening_<date>.json`` (或最新一份报告)。

    Returns:
        :class:`CompareResponse` 含 ``tickers`` / ``metrics`` / ``summary`` /
        ``winner`` / ``report_date`` 字段, 字段类型严格 JSON-safe (NaN 已转 None)。
    """
    # 延迟导入 — 避免循环依赖 + 测试时可单独 patch
    from src.screening.compare_tool import (
        compare_tickers,
        CompareReport,
        DEFAULT_METRIC_KEYS,
        load_latest_recommendations,
        MAX_COMPARE_TICKERS,
        MIN_COMPARE_TICKERS,
    )

    # 1. 解析 + 校验 tickers
    raw_tickers = [t.strip() for t in (tickers or "").split(",") if t.strip()]
    if not (MIN_COMPARE_TICKERS <= len(raw_tickers) <= MAX_COMPARE_TICKERS):
        raise HTTPException(
            status_code=422,
            detail=(
                f"tickers 数量必须为 {MIN_COMPARE_TICKERS}-{MAX_COMPARE_TICKERS} 只, "
                f"实际: {len(raw_tickers)}"
            ),
        )

    # 2. 解析 + 校验 metrics
    metric_keys: list[str] | None = None
    if metrics:
        metric_keys = [m.strip() for m in metrics.split(",") if m.strip()]
        valid_metrics = set(DEFAULT_METRIC_KEYS)
        unknown = [m for m in metric_keys if m not in valid_metrics]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"未知指标: {unknown} (合法: {sorted(valid_metrics)})",
            )

    # 3. 校验 trade_date
    if trade_date:
        cleaned = trade_date.strip().replace("-", "")
        if len(cleaned) != 8 or not cleaned.isdigit():
            raise HTTPException(
                status_code=422,
                detail=f"trade_date 格式无效: {trade_date!r} (期望 YYYYMMDD)",
            )
        resolved_date = cleaned
    else:
        resolved_date = None

    # 4. 加载推荐数据
    recommendations = load_latest_recommendations(trade_date=resolved_date)
    if not recommendations:
        raise HTTPException(
            status_code=404,
            detail=(
                f"未找到有效 auto_screening 报告 "
                f"(trade_date={trade_date or 'latest'}), 请先运行 --auto"
            ),
        )

    # 5. 执行对比
    try:
        report: CompareReport = compare_tickers(
            tickers=raw_tickers,
            recommendations=recommendations,
            metric_keys=metric_keys,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # 6. NaN 清洗 (统一 None)
    def _sanitize(value: Any) -> Any:
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return value
        if isinstance(value, dict):
            return {k: _sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_sanitize(v) for v in value]
        return value

    sanitized_metrics = [_sanitize(m.to_dict()) for m in report.metrics]

    # 7. 从 trade_date 字段提取 (load_latest_recommendations 不返回日期,
    #    从 recommendations 中尝试推断 — 若 report_date 不明则置 None)
    inferred_date: str | None = resolved_date
    if inferred_date is None and recommendations:
        for rec in recommendations:
            if isinstance(rec, dict) and isinstance(rec.get("date"), str):
                inferred_date = rec["date"].replace("-", "")
                break

    return CompareResponse(
        tickers=list(report.tickers),
        metrics=sanitized_metrics,
        summary=dict(report.summary),
        winner=report.winner,
        report_date=inferred_date,
        meta={
            "metric_keys": metric_keys or list(DEFAULT_METRIC_KEYS),
            "min_compare_tickers": MIN_COMPARE_TICKERS,
            "max_compare_tickers": MAX_COMPARE_TICKERS,
        },
    )


# ---------------------------------------------------------------------------
# P1-10: 条件单建议端点
# ---------------------------------------------------------------------------


class ConditionalOrderItem(BaseModel):
    """P1-10 单条条件单建议。"""

    ticker: str
    name: str
    current_price: float | None = None
    atr: float | None = None
    suggested_buy_zone: list[float]
    suggested_buy_zone_low: float | None = None
    suggested_buy_zone_high: float | None = None
    suggested_stop_loss: float | None = None
    suggested_take_profit: float | None = None
    confidence: float | None = None
    reasoning: str = ""
    historical_hit_rate: float | None = None
    risk_reward_ratio: float | None = None
    n_sessions: int = 0
    degraded: bool = False
    atr_period: int = 14
    params: dict = Field(default_factory=dict)


class ConditionalOrdersResponse(BaseModel):
    """P1-10 条件单建议响应体。"""

    trade_date: str | None = None
    items: list[ConditionalOrderItem] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


@router.get(
    path="/conditional-orders",
    response_model=ConditionalOrdersResponse,
    responses={
        200: {"description": "成功 — 返回 Top N 条件单建议"},
        404: {"description": "未找到有效 auto_screening 报告"},
        422: {"description": "参数校验失败 (top_n 越界)"},
    },
)
async def conditional_orders_endpoint(
    top_n: int = Query(20, ge=1, le=50, description="Top N 推荐 (1-50)"),
    atr_period: int = Query(14, ge=2, le=60, description="ATR 周期 (2-60)"),
    trade_date: str | None = Query(None, description="报告日期 YYYYMMDD, 缺省取最新"),
) -> ConditionalOrdersResponse:
    """P1-10 Web 端条件单建议 API。

    复用 :func:`src.screening.compare_tool.load_latest_recommendations` 加载报告,
    再用 :func:`src.screening.conditional_order_advisor.compute_conditional_advice` 计算建议。
    价格历史来自 caller 注入的 provider (本端点默认走 fallback → 全部降级占位)。

    Returns:
        :class:`ConditionalOrdersResponse` 含 ``items`` (Top N 建议) /
        ``trade_date`` / ``meta`` 字段。
    """
    from src.screening.compare_tool import load_latest_recommendations
    from src.screening.conditional_order_advisor import (
        attach_conditional_orders_to_payload,
        DEFAULT_LOOKBACK_SESSIONS,
    )

    # 1. trade_date 校验
    resolved_date: str | None = None
    if trade_date:
        cleaned = trade_date.strip().replace("-", "")
        if len(cleaned) != 8 or not cleaned.isdigit():
            raise HTTPException(
                status_code=422,
                detail=f"trade_date 格式无效: {trade_date!r} (期望 YYYYMMDD)",
            )
        resolved_date = cleaned

    # 2. 加载推荐
    recommendations = load_latest_recommendations(trade_date=resolved_date)
    if not recommendations:
        raise HTTPException(
            status_code=404,
            detail=(
                f"未找到有效 auto_screening 报告 "
                f"(trade_date={trade_date or 'latest'}), 请先运行 --auto"
            ),
        )

    # 3. 推断 trade_date
    if resolved_date is None:
        for rec in recommendations:
            if isinstance(rec, dict) and isinstance(rec.get("date"), str):
                resolved_date = rec["date"].replace("-", "")
                break

    # 4. 调用 attach_conditional_orders_to_payload (无价格 provider → 全部降级)
    payload: dict[str, Any] = {"recommendations": recommendations}
    raw_items = attach_conditional_orders_to_payload(
        payload,
        top_n=top_n,
        atr_period=atr_period,
        lookback_sessions=DEFAULT_LOOKBACK_SESSIONS,
    )

    # 5. NaN 清洗
    def _sanitize(value: Any) -> Any:
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return value
        if isinstance(value, dict):
            return {k: _sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_sanitize(v) for v in value]
        return value

    items = [ConditionalOrderItem(**_sanitize(item)) for item in raw_items]

    return ConditionalOrdersResponse(
        trade_date=resolved_date,
        items=items,
        meta={
            "top_n": top_n,
            "atr_period": atr_period,
            "lookback_sessions": DEFAULT_LOOKBACK_SESSIONS,
            "degraded_count": sum(1 for it in items if it.degraded),
            "total_count": len(items),
        },
    )


# ---------------------------------------------------------------------------
# P2-5: 自定义策略权重端点
# ---------------------------------------------------------------------------


class CustomWeightsRequest(BaseModel):
    """P2-5 自定义策略权重请求体。

    四策略权重必须和为 1.0 (Pydantic ``consumed`` 约束在 service 层执行,
    端点层只校验单值范围 [0, 1], 避免 422 误报 sum=0.999999 的合法值)。
    """

    trend: float = Field(ge=0, le=1)
    mean_reversion: float = Field(ge=0, le=1)
    fundamental: float = Field(ge=0, le=1)
    event_sentiment: float = Field(ge=0, le=1)
    top_n: int = Field(default=20, ge=1, le=50)
    trade_date: str | None = None


@router.post(
    path="/custom-weights",
    response_model=ScreeningResponse,
    responses={
        200: {"description": "成功 — 返回按自定义权重重排的 Top N 推荐"},
        422: {"description": "参数校验失败 (权重和 != 1.0)"},
        404: {"description": "未找到有效 auto_screening 报告"},
    },
)
async def apply_custom_weights(req: CustomWeightsRequest) -> ScreeningResponse:
    """P2-5 应用自定义策略权重, 重新计算 score_b 并返回 Top N 推荐。

    数据源: ``data/reports/auto_screening_<date>.json`` (或最新一份)。

    与 ``/api/screening/auto`` 的区别: 后者使用市场状态调整后的默认权重,
    本端点使用用户自定义权重覆盖, 适合高级用户做敏感性分析 / 偏好测试。
    """
    # 1. 校验权重和 (Pydantic Field 只校验单值范围, sum 校验放在端点层)
    weight_sum = req.trend + req.mean_reversion + req.fundamental + req.event_sentiment
    if abs(weight_sum - 1.0) > 1e-6:
        raise HTTPException(
            status_code=422,
            detail=f"权重之和必须为 1.0, 当前: {weight_sum:.9f}",
        )

    # 2. 解析 trade_date
    resolved_date: str | None = None
    if req.trade_date:
        resolved_date = _normalize_trade_date(req.trade_date)

    # 3. 加载 + 重算
    from src.screening.custom_weights import (
        load_latest_recommendations,
        reweight_recommendations,
        StrategyWeights,
    )

    recs = load_latest_recommendations(trade_date=resolved_date)
    if not recs:
        raise HTTPException(
            status_code=404,
            detail=(
                f"未找到有效 auto_screening 报告 "
                f"(trade_date={req.trade_date or 'latest'}), 请先运行 --auto"
            ),
        )

    weights = StrategyWeights(
        trend=req.trend,
        mean_reversion=req.mean_reversion,
        fundamental=req.fundamental,
        event_sentiment=req.event_sentiment,
    )
    reweighted = reweight_recommendations(recs, weights)
    top = reweighted[: max(1, req.top_n)]

    return ScreeningResponse(
        trade_date=resolved_date or _resolve_default_trade_date(),
        recommendations=_sanitize_nan(top),
        market_state=None,
        tracking_summary=None,
        consecutive_recommendation=None,
        industry_rotation=None,
        execution_time_seconds=0.0,
        batch_data_fetcher=None,
        signal_decay_summary=None,
        sector_concentration_warnings=[],
        layer_a_count=0,
        total_scored=len(recs),
        high_pool_count=0,
        top_n=len(top),
        meta={
            "weights": weights.to_dict(),
            "total_recommendations": len(recs),
            "applied_top_n": req.top_n,
        },
    )


# ---------------------------------------------------------------------------
# P2-4: 历史推荐胜率看板端点
# ---------------------------------------------------------------------------


class WinRateDashboardResponse(BaseModel):
    """P2-4 历史推荐胜率看板响应体。"""

    period_days: int = 30
    total_days: int = 0
    total_recommendations: int = 0
    avg_t1_win_rate: float | None = None
    avg_t1_return: float | None = None
    avg_t3_win_rate: float | None = None
    avg_t3_return: float | None = None
    avg_t5_win_rate: float | None = None
    avg_t5_return: float | None = None
    trend: str = "stable"
    daily: list[dict] = Field(default_factory=list)


@router.get(
    path="/winrate-dashboard",
    response_model=WinRateDashboardResponse,
    responses={
        200: {"description": "成功 — 返回近 N 天推荐胜率趋势 + 平均收益率曲线"},
    },
)
async def get_winrate_dashboard(
    lookback_days: int = Query(30, ge=1, le=365, description="回溯天数 (默认 30)"),
) -> WinRateDashboardResponse:
    """P2-4 历史推荐胜率看板 API。

    从 P1-3 ``tracking_history.json`` 读取历史推荐和实际收益,
    按日聚合 T+1/T+3/T+5 胜率和平均收益率, 并判定趋势方向。

    Returns:
        :class:`WinRateDashboardResponse` 含汇总统计和日度趋势数据。
    """
    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.screening.winrate_dashboard import compute_winrate_dashboard

    report_dir = resolve_report_dir()
    history_path = report_dir / "tracking_history.json"

    summary = compute_winrate_dashboard(history_path, lookback_days=lookback_days)

    # Convert DailyWinRate list to list of dicts for Pydantic serialization
    daily_dicts = [_sanitize_nan(d.to_dict()) for d in summary.daily]

    return WinRateDashboardResponse(
        period_days=summary.period_days,
        total_days=summary.total_days,
        total_recommendations=summary.total_recommendations,
        avg_t1_win_rate=_sanitize_nan(summary.avg_t1_win_rate),
        avg_t1_return=_sanitize_nan(summary.avg_t1_return),
        avg_t3_win_rate=_sanitize_nan(summary.avg_t3_win_rate),
        avg_t3_return=_sanitize_nan(summary.avg_t3_return),
        avg_t5_win_rate=_sanitize_nan(summary.avg_t5_win_rate),
        avg_t5_return=_sanitize_nan(summary.avg_t5_return),
        trend=summary.trend,
        daily=daily_dicts,
    )


# ---------------------------------------------------------------------------
# P2-6: 标的深度分析详情页端点
# ---------------------------------------------------------------------------


class StockDetailResponse(BaseModel):
    """P2-6 标的深度分析详情响应体。"""

    ticker: str
    name: str
    industry_sw: str
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    roe: float | None = None
    revenue_growth: float | None = None
    profit_growth: float | None = None
    dividend_yield: float | None = None
    price: float = 0.0
    change_pct: float = 0.0
    ma5: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    rsi_14: float | None = None
    macd_signal: str = "neutral"
    atr_pct: float | None = None
    money_flow_net: float | None = None
    north_money_net: float | None = None
    dragon_tiger: bool = False
    recommendation_count_30d: int = 0
    latest_score_b: float | None = None
    latest_decision: str | None = None
    consecutive_days: int = 0
    decay_level: str = "none"
    industry_rank: int | None = None
    industry_total: int | None = None


@router.get(
    path="/stock-detail/{ticker}",
    response_model=StockDetailResponse,
    responses={
        200: {"description": "成功 — 返回标的深度分析报告"},
        404: {"description": "未找到有效的 auto_screening 报告"},
    },
)
async def get_stock_detail(
    ticker: str,
    trade_date: str | None = Query(None, description="报告日期 YYYYMMDD, 缺省取最新"),
) -> StockDetailResponse:
    """P2-6 标的深度分析 API。

    聚合 auto_screening 报告中单只标的的全部数据: 基本面 + 技术面 + 资金流 +
    系统历史 (推荐次数 / 连续推荐 / 信号衰减) + 同行业排名。

    不调用外部 API — 完全基于已有报告数据聚合。

    Returns:
        :class:`StockDetailResponse` 含所有分析维度。
    """
    from src.screening.compare_tool import load_latest_recommendations
    from src.screening.stock_detail import compute_stock_detail

    # 1. trade_date 校验
    resolved_date: str | None = None
    if trade_date:
        cleaned = trade_date.strip().replace("-", "")
        if len(cleaned) != 8 or not cleaned.isdigit():
            raise HTTPException(
                status_code=422,
                detail=f"trade_date 格式无效: {trade_date!r} (期望 YYYYMMDD)",
            )
        resolved_date = cleaned

    # 2. 加载推荐
    recommendations = load_latest_recommendations(trade_date=resolved_date)
    if not recommendations:
        raise HTTPException(
            status_code=404,
            detail=(
                f"未找到有效 auto_screening 报告 "
                f"(trade_date={trade_date or 'latest'}), 请先运行 --auto"
            ),
        )

    # 3. 计算详情
    detail = compute_stock_detail(
        ticker=ticker,
        recommendations=recommendations,
        trade_date=resolved_date,
    )

    # 4. NaN 清洗 + 响应
    d = detail.to_dict()
    sanitized = _sanitize_nan(d)
    return StockDetailResponse(**sanitized)
