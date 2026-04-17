"""Shared catalyst rendering helpers used by all card renderers."""

from __future__ import annotations

from typing import Any

from src.paper_trading.btst_reporting_utils import _format_float


def _append_threshold_shortfalls_line(
    lines: list[str], threshold_shortfalls: dict[str, Any]
) -> None:
    lines.append(
        "- threshold_shortfalls: "
        + (
            ", ".join(
                f"{key}={_format_float(value)}"
                for key, value in threshold_shortfalls.items()
            )
            if threshold_shortfalls
            else "none"
        )
    )


def _append_catalyst_watch_metrics(lines: list[str], metrics: dict[str, Any]) -> None:
    lines.append(
        "- key_metrics: "
        + ", ".join(
            [
                f"breakout={_format_float(metrics.get('breakout_freshness'))}",
                f"trend={_format_float(metrics.get('trend_acceleration'))}",
                f"close={_format_float(metrics.get('close_strength'))}",
                f"sector={_format_float(metrics.get('sector_resonance'))}",
                f"catalyst={_format_float(metrics.get('catalyst_freshness'))}",
            ]
        )
    )
