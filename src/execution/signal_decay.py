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
    p7_warned: list[str] = []
    p7_halted: list[str] = []
    p7_report_warned: list[str] = []
    p7_report_halted: list[str] = []

    for order in plan.buy_orders:
        ticker = order.ticker
        if ticker in negative_news_tickers:
            risk_alerts.append(f"cancel_buy_negative_news:{ticker}")
            continue

        gap_value = open_gap_pct.get(ticker)
        gap_pct = float(gap_value) if isinstance(gap_value, (int, float)) else None

        # Existing gap-up cancellation (requires open_gap_pct to be supplied by the runtime/backtester).
        # R20.26-B BETA-007: require a *positive, finite* ATR. With atr=0.0
        # (missing ATR data — e.g. a fresh IPO, or a corrupted feed) the
        # threshold ``1.5 * 0.0 = 0.0`` and ANY positive open gap cancelled
        # the buy order, turning a volatility-relative safety gate into a
        # "cancel everything that gaps up" tripwire. Skip the check when ATR
        # is unknown / non-positive so the order survives normal opens.
        atr_value = atr_values.get(ticker)
        if isinstance(atr_value, (int, float)) and atr_value > 0 and open_gap_pct.get(ticker, 0.0) > (1.5 * float(atr_value)):
            risk_alerts.append(f"cancel_buy_gap_open:{ticker}")
            continue

        # BTST 0422 P7: gap-down overlay enforcement / reporting.
        if gap_pct is not None and p7_overlay.mode in {"enforce", "report"}:
            if gap_pct <= -p7_overlay.halt_threshold:
                if p7_overlay.mode == "report":
                    p7_report_halted.append(ticker)
                else:
                    p7_halted.append(ticker)
                    risk_alerts.append(f"cancel_buy_gap_overlay_halt:{ticker}")
                    continue
            elif gap_pct <= -p7_overlay.warn_threshold:
                if p7_overlay.mode == "report":
                    p7_report_warned.append(ticker)
                else:
                    new_shares = int(order.shares * p7_overlay.warn_size_discount)
                    new_amount = float(order.amount) * p7_overlay.warn_size_discount
                    if new_shares <= 0 or new_amount <= 0:
                        p7_halted.append(ticker)
                        risk_alerts.append(f"cancel_buy_gap_overlay_warn_zeroed:{ticker}")
                        continue
                    p7_warned.append(ticker)
                    risk_alerts.append(f"reduce_buy_gap_overlay_warn:{ticker}")
                    filtered_buy_orders.append(
                        order.model_copy(
                            update={
                                "shares": new_shares,
                                "amount": new_amount,
                                "execution_ratio": float(order.execution_ratio or 0.0) * p7_overlay.warn_size_discount,
                                # NOTE: 0.0 是合法 risk_budget_ratio (无风险预算), 不能用 `or 1.0` 静默覆盖为满仓。
                                "risk_budget_ratio": float(order.risk_budget_ratio if order.risk_budget_ratio is not None else 1.0) * p7_overlay.warn_size_discount,
                            }
                        )
                    )
                    continue

        refreshed_score = refreshed_scores.get(ticker)
        if refreshed_score is not None and refreshed_score < (order.score_final * 0.8):
            risk_alerts.append(f"cancel_buy_signal_decay:{ticker}")
            continue
        filtered_buy_orders.append(order)

    plan.buy_orders = filtered_buy_orders
    plan.risk_alerts = risk_alerts

    if p7_overlay.mode == "enforce":
        risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
        funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
        enforcement_payload: dict[str, Any] = {
            "mode": "enforce",
            "trade_date_t1": str(trade_date_t1),
            "warn_threshold": p7_overlay.warn_threshold,
            "halt_threshold": p7_overlay.halt_threshold,
            "warn_size_discount": p7_overlay.warn_size_discount,
            "buy_orders_original_count": original_buy_count,
            "buy_orders_retained_count": len(plan.buy_orders),
            "warned_count": len(p7_warned),
            "halted_count": len(p7_halted),
            "warned_tickers": sorted(set(p7_warned)),
            "halted_tickers": sorted(set(p7_halted)),
        }
        risk_metrics["btst_gap_overlay_p7_enforcement"] = enforcement_payload
        funnel_diagnostics["btst_gap_overlay_p7_enforcement"] = enforcement_payload
        risk_metrics["funnel_diagnostics"] = funnel_diagnostics
        counts = dict(risk_metrics.get("counts", {}) or {})
        counts["buy_order_count"] = len(plan.buy_orders)
        risk_metrics["counts"] = counts
        plan.risk_metrics = risk_metrics

    elif p7_overlay.mode == "report":
        risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
        funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
        report_payload: dict[str, Any] = {
            "mode": "report",
            "trade_date_t1": str(trade_date_t1),
            "warn_threshold": p7_overlay.warn_threshold,
            "halt_threshold": p7_overlay.halt_threshold,
            "warn_size_discount": p7_overlay.warn_size_discount,
            "buy_orders_original_count": original_buy_count,
            "buy_orders_retained_count": len(plan.buy_orders),
            "warned_count": len(p7_report_warned),
            "halted_count": len(p7_report_halted),
            "warned_tickers": sorted(set(p7_report_warned)),
            "halted_tickers": sorted(set(p7_report_halted)),
        }
        risk_metrics["btst_gap_overlay_p7_report"] = report_payload
        funnel_diagnostics["btst_gap_overlay_p7_report"] = report_payload
        risk_metrics["funnel_diagnostics"] = funnel_diagnostics
        plan.risk_metrics = risk_metrics

    return plan
