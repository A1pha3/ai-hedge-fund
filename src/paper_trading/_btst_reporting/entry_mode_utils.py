"""Shared entry-mode posture and execution note helpers.

Used by priority board, opening watch, and premarket card modules.
"""

from __future__ import annotations

from typing import Any


def _selected_action_posture(preferred_entry_mode: str | None) -> tuple[str, list[str]]:
    if preferred_entry_mode == "next_day_breakout_confirmation":
        return (
            "confirm_then_enter",
            [
                "只在盘中出现 breakout confirmation 时考虑执行，不做无确认追价。",
                "若盘中强度无法延续或突破失败，则直接放弃当日入场。",
            ],
        )
    if preferred_entry_mode == "intraday_confirmation_only":
        return (
            "confirm_then_reduce",
            [
                "只做盘中确认后的 intraday 机会，不把默认隔夜持有当成执行目标。",
                "若盘中给出空间后回落，应优先减仓或放弃隔夜持有。",
            ],
        )
    if preferred_entry_mode == "avoid_open_chase_confirmation":
        return (
            "avoid_open_chase",
            [
                "避免开盘直接追价，等待回踩或二次确认后再决定是否参与。",
                "若高开后强度迅速衰减，则直接放弃当日入场。",
            ],
        )
    if preferred_entry_mode == "confirm_then_hold_breakout":
        return (
            "confirm_then_hold",
            [
                "先等盘中 continuation 确认，再决定是否执行，不做无确认开盘追价。",
                "若确认后量价延续良好，可把 follow-through 持有到收盘，而不是默认盘中快速减仓。",
            ],
        )
    if preferred_entry_mode == "strong_reconfirmation_only":
        return (
            "reconfirm_only",
            [
                "历史兑现极弱，只有出现新的强确认时才允许重新评估。",
                "没有新增强度时，不把它当成可执行 BTST 对象。",
            ],
        )
    return (
        "manual_review",
        [
            "当前 entry mode 不是标准 breakout confirmation，开盘前应先人工复核。",
        ],
    )


def _selected_holding_contract_note(
    preferred_entry_mode: str | None, historical_prior: dict[str, Any] | None
) -> str | None:
    prior = dict(historical_prior or {})
    if preferred_entry_mode != "confirm_then_hold_breakout":
        return None
    if str(prior.get("execution_quality_label") or "") != "close_continuation":
        return None
    if str(prior.get("entry_timing_bias") or "") != "confirm_then_hold":
        return None
    return "默认按 BTST T+2 bias 管理，不把 T+3 连续走强当成基础预期。"


def _augment_execution_note(
    preferred_entry_mode: str | None, historical_prior: dict[str, Any] | None
) -> str | None:
    prior = dict(historical_prior or {})
    base_note = str(prior.get("execution_note") or "").strip()
    contract_note = _selected_holding_contract_note(preferred_entry_mode, prior)
    if contract_note and contract_note not in base_note:
        return f"{base_note} {contract_note}".strip() if base_note else contract_note
    return base_note or None
