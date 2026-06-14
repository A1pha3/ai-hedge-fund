"""信号衰减检查器。

Applies execution-side filters (negative news, gap risk, score decay, etc.)
that can remove or resize buy orders before intraday confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.execution.models import ExecutionPlan
from src.utils.env_helpers import get_env_float, get_env_mode

BTST_0422_P7_GAP_OVERLAY_MODE_ENV = "BTST_0422_P7_GAP_OVERLAY_MODE"
BTST_0422_P7_GAP_OVERLAY_MODES = frozenset({"off", "report", "enforce"})
BTST_0422_P7_GAP_WARN_THRESHOLD_ENV = "BTST_0422_P7_GAP_WARN_THRESHOLD"
BTST_0422_P7_GAP_HALT_THRESHOLD_ENV = "BTST_0422_P7_GAP_HALT_THRESHOLD"
BTST_0422_P7_GAP_WARN_SIZE_DISCOUNT_ENV = "BTST_0422_P7_GAP_WARN_SIZE_DISCOUNT"

DEFAULT_P7_GAP_WARN_THRESHOLD = 0.005
DEFAULT_P7_GAP_HALT_THRESHOLD = 0.01
DEFAULT_P7_GAP_WARN_SIZE_DISCOUNT = 0.5


@dataclass(frozen=True)
class P7GapOverlayConfig:
    mode: str
    warn_threshold: float
    halt_threshold: float
    warn_size_discount: float


@dataclass
class SignalDecayLoopContext:
    refreshed_scores: dict[str, float]
    atr_values: dict[str, float]
    open_gap_pct: dict[str, float]
    negative_news_tickers: set[str]
    overlay: P7GapOverlayConfig
    risk_alerts: list[str]
    p7_warned: list[str]
    p7_halted: list[str]
    p7_report_warned: list[str]
    p7_report_halted: list[str]


def _resolve_p7_gap_overlay_mode() -> str:
    normalized = get_env_mode(BTST_0422_P7_GAP_OVERLAY_MODE_ENV, "off").strip().lower()
    return normalized if normalized in BTST_0422_P7_GAP_OVERLAY_MODES else "off"


def _resolve_p7_gap_thresholds() -> tuple[float, float]:
    warn = abs(get_env_float(BTST_0422_P7_GAP_WARN_THRESHOLD_ENV, DEFAULT_P7_GAP_WARN_THRESHOLD))
    halt = abs(get_env_float(BTST_0422_P7_GAP_HALT_THRESHOLD_ENV, DEFAULT_P7_GAP_HALT_THRESHOLD))
    return warn, max(halt, warn)


def _resolve_p7_warn_size_discount() -> float:
    discount = abs(get_env_float(BTST_0422_P7_GAP_WARN_SIZE_DISCOUNT_ENV, DEFAULT_P7_GAP_WARN_SIZE_DISCOUNT))
    if discount <= 0:
        return DEFAULT_P7_GAP_WARN_SIZE_DISCOUNT
    return min(discount, 1.0)


def _resolve_p7_gap_overlay_config() -> P7GapOverlayConfig:
    warn_threshold, halt_threshold = _resolve_p7_gap_thresholds()
    return P7GapOverlayConfig(
        mode=_resolve_p7_gap_overlay_mode(),
        warn_threshold=warn_threshold,
        halt_threshold=halt_threshold,
        warn_size_discount=_resolve_p7_warn_size_discount(),
    )


def _build_gap_overlay_payload(
    *,
    mode: str,
    trade_date_t1: str,
    overlay: P7GapOverlayConfig,
    original_buy_count: int,
    retained_buy_count: int,
    warned_tickers: list[str],
    halted_tickers: list[str],
) -> dict[str, Any]:
    return {
        "mode": mode,
        "trade_date_t1": str(trade_date_t1),
        "warn_threshold": overlay.warn_threshold,
        "halt_threshold": overlay.halt_threshold,
        "warn_size_discount": overlay.warn_size_discount,
        "buy_orders_original_count": original_buy_count,
        "buy_orders_retained_count": retained_buy_count,
        "warned_count": len(warned_tickers),
        "halted_count": len(halted_tickers),
        "warned_tickers": sorted(set(warned_tickers)),
        "halted_tickers": sorted(set(halted_tickers)),
    }


def _attach_gap_overlay_payload(
    plan: ExecutionPlan,
    *,
    metrics_key: str,
    payload: dict[str, Any],
    update_buy_order_count: bool,
) -> None:
    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    risk_metrics[metrics_key] = payload
    funnel_diagnostics[metrics_key] = payload
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    if update_buy_order_count:
        counts = dict(risk_metrics.get("counts", {}) or {})
        counts["buy_order_count"] = len(plan.buy_orders)
        risk_metrics["counts"] = counts
    plan.risk_metrics = risk_metrics


def _should_cancel_gap_open(*, atr_value: Any, gap_value: Any) -> bool:
    if not isinstance(atr_value, (int, float)) or atr_value <= 0:
        return False
    return bool(gap_value > (1.5 * float(atr_value)))


def _build_warn_adjusted_order(order: Any, *, warn_size_discount: float) -> Any:
    new_shares = int(order.shares * warn_size_discount)
    new_amount = float(order.amount) * warn_size_discount
    if new_shares <= 0 or new_amount <= 0:
        return None
    return order.model_copy(
        update={
            "shares": new_shares,
            "amount": new_amount,
            "execution_ratio": float(order.execution_ratio or 0.0) * warn_size_discount,
            # NOTE: 0.0 是合法 risk_budget_ratio (无风险预算), 不能用 `or 1.0` 静默覆盖为满仓。
            "risk_budget_ratio": float(order.risk_budget_ratio if order.risk_budget_ratio is not None else 1.0) * warn_size_discount,
        }
    )


def _apply_gap_overlay(
    *,
    order: Any,
    gap_pct: float | None,
    overlay: P7GapOverlayConfig,
) -> tuple[str, Any | None]:
    if gap_pct is None or overlay.mode not in {"enforce", "report"}:
        return "none", None
    if gap_pct <= -overlay.halt_threshold:
        return ("report_halt", None) if overlay.mode == "report" else ("halt", None)
    if gap_pct > -overlay.warn_threshold:
        return "none", None
    if overlay.mode == "report":
        return "report_warn", None
    adjusted_order = _build_warn_adjusted_order(
        order,
        warn_size_discount=overlay.warn_size_discount,
    )
    if adjusted_order is None:
        return "warn_zeroed", None
    return "warn_reduce", adjusted_order


def _process_signal_decay_order(order: Any, context: SignalDecayLoopContext) -> Any | None:
    ticker = order.ticker
    if ticker in context.negative_news_tickers:
        context.risk_alerts.append(f"cancel_buy_negative_news:{ticker}")
        return None

    gap_value = context.open_gap_pct.get(ticker)
    gap_pct = float(gap_value) if isinstance(gap_value, (int, float)) else None
    if _should_cancel_gap_open(
        atr_value=context.atr_values.get(ticker),
        gap_value=context.open_gap_pct.get(ticker, 0.0),
    ):
        context.risk_alerts.append(f"cancel_buy_gap_open:{ticker}")
        return None

    gap_action, adjusted_order = _apply_gap_overlay(
        order=order,
        gap_pct=gap_pct,
        overlay=context.overlay,
    )
    if gap_action == "halt":
        context.p7_halted.append(ticker)
        context.risk_alerts.append(f"cancel_buy_gap_overlay_halt:{ticker}")
        return None
    if gap_action == "report_halt":
        context.p7_report_halted.append(ticker)
    elif gap_action == "report_warn":
        context.p7_report_warned.append(ticker)
    elif gap_action == "warn_zeroed":
        context.p7_halted.append(ticker)
        context.risk_alerts.append(f"cancel_buy_gap_overlay_warn_zeroed:{ticker}")
        return None
    elif gap_action == "warn_reduce":
        context.p7_warned.append(ticker)
        context.risk_alerts.append(f"reduce_buy_gap_overlay_warn:{ticker}")
        return adjusted_order

    refreshed_score = context.refreshed_scores.get(ticker)
    if refreshed_score is not None and refreshed_score < (order.score_final * 0.8):
        context.risk_alerts.append(f"cancel_buy_signal_decay:{ticker}")
        return None
    return order


def apply_signal_decay(
    plan: ExecutionPlan,
    trade_date_t1: str,
    refreshed_scores: dict[str, float] | None = None,
    atr_values: dict[str, float] | None = None,
    open_gap_pct: dict[str, float] | None = None,
    negative_news_tickers: set[str] | None = None,
) -> ExecutionPlan:
    refreshed_scores = refreshed_scores or {}
    atr_values = atr_values or {}
    open_gap_pct = open_gap_pct or {}
    negative_news_tickers = negative_news_tickers or set()

    p7_overlay = _resolve_p7_gap_overlay_config()

    filtered_buy_orders = []
    risk_alerts = list(plan.risk_alerts)

    original_buy_count = len(list(plan.buy_orders or []))
    loop_context = SignalDecayLoopContext(
        refreshed_scores=refreshed_scores,
        atr_values=atr_values,
        open_gap_pct=open_gap_pct,
        negative_news_tickers=negative_news_tickers,
        overlay=p7_overlay,
        risk_alerts=risk_alerts,
        p7_warned=[],
        p7_halted=[],
        p7_report_warned=[],
        p7_report_halted=[],
    )

    for order in plan.buy_orders:
        processed_order = _process_signal_decay_order(order, loop_context)
        if processed_order is not None:
            filtered_buy_orders.append(processed_order)

    plan.buy_orders = filtered_buy_orders
    plan.risk_alerts = risk_alerts

    if p7_overlay.mode == "enforce":
        _attach_gap_overlay_payload(
            plan,
            metrics_key="btst_gap_overlay_p7_enforcement",
            payload=_build_gap_overlay_payload(
                mode="enforce",
                trade_date_t1=trade_date_t1,
                overlay=p7_overlay,
                original_buy_count=original_buy_count,
                retained_buy_count=len(plan.buy_orders),
                warned_tickers=loop_context.p7_warned,
                halted_tickers=loop_context.p7_halted,
            ),
            update_buy_order_count=True,
        )

    elif p7_overlay.mode == "report":
        _attach_gap_overlay_payload(
            plan,
            metrics_key="btst_gap_overlay_p7_report",
            payload=_build_gap_overlay_payload(
                mode="report",
                trade_date_t1=trade_date_t1,
                overlay=p7_overlay,
                original_buy_count=original_buy_count,
                retained_buy_count=len(plan.buy_orders),
                warned_tickers=loop_context.p7_report_warned,
                halted_tickers=loop_context.p7_report_halted,
            ),
            update_buy_order_count=False,
        )

    return plan
