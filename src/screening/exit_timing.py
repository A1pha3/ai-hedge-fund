"""Q-1 卖时机信号 — per-pick exit-timing 建议.

系统说 BUY 但不说何时 SELL——"持续时间"维度有买入无卖出。R144 把收益节奏分
早/匀/晚 (纯展示), R9 信号衰减检测分数下滑; 本模块把二者综合成可行动的卖出建议:

  - 节奏=早 → T+5–T+10 关注止盈 (fast-mover, peak early)
  - 节奏=匀 → T+20–T+30 持有 (steady grind to horizon)
  - 节奏=晚 → T+30+ 耐心持有 (late bloomer, don't exit early)
  - 叠加 R9 信号衰减 (change_pct<0) → ⚠ 提前关注

设计原则:
  - **纯函数, 零新数据** — 复用 R144 rhythm + R9 decay
  - **建议非指令** — 复用 R71-R77 disclaimer 语义 (研究参考, 非投资指令)
  - **无节奏数据 → 不发建议** (诚实, 非假信号)

CLI: ``--top-picks`` per-pick 经 ``_print_pick_entry`` 调用
``render_exit_timing(compute_exit_timing(...))``。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.display import Fore, Style


@dataclass
class ExitTimingAdvice:
    """Per-pick 卖时机建议。"""

    rhythm: str  # 早/匀/晚/—
    suggested_window: str  # "T+5–T+10 关注止盈" 等; 空 = 无建议
    decay_warning: bool  # R9 信号衰减 → 提前关注
    rationale: str  # 中文解释 (供 render / 调试)

    @property
    def available(self) -> bool:
        """是否有有效建议 (节奏未知 → False)。"""
        return bool(self.suggested_window)


def compute_exit_timing(
    *,
    rhythm: str,
    decay_change_pct: float | None,
    days_since_peak: int,
) -> ExitTimingAdvice:
    """综合节奏 + 衰减 → 卖时机建议。

    Args:
        rhythm: R144 收益节奏 (早/匀/晚/—)
        decay_change_pct: R9 分数变化 (None=首次/无前值; <0=衰减)
        days_since_peak: R9 距最高分天数 (0=今天最高)

    Returns:
        :class:`ExitTimingAdvice` (节奏="—" → suggested_window 空)
    """
    window_map = {
        "早": "T+5–T+10 关注止盈 (快涨型, 高点靠前)",
        "匀": "T+20–T+30 持有 (匀速型, 等到期限)",
        "晚": "T+30+ 耐心持有 (晚熟型, 勿过早离场)",
    }
    window = window_map.get(rhythm, "")
    decaying = decay_change_pct is not None and decay_change_pct < 0

    parts: list[str] = []
    if window:
        parts.append(window)
    if decaying:
        peak_ctx = f"距峰 {days_since_peak}d" if days_since_peak > 0 else "今日峰"
        parts.append(f"⚠ 信号衰减 ({decay_change_pct * 100:+.1f}%, {peak_ctx}) 建议提前关注")

    rationale = " | ".join(parts) if parts else "节奏未知, 无卖出建议"

    return ExitTimingAdvice(
        rhythm=rhythm,
        suggested_window=window,
        decay_warning=decaying,
        rationale=rationale,
    )


def render_exit_timing(advice: ExitTimingAdvice) -> str:
    """渲染一行卖时机建议 (无建议 → 空串)。"""
    if not advice.available and not advice.decay_warning:
        return ""
    bits: list[str] = []
    if advice.suggested_window:
        bits.append(f"{Fore.CYAN}🎯 卖时机:{Style.RESET_ALL} {advice.suggested_window}")
    if advice.decay_warning:
        bits.append(f"{Fore.RED}⚠ 信号衰减, 建议提前关注止盈/止损{Style.RESET_ALL}")
    return "  " + "  ".join(bits)


__all__ = [
    "ExitTimingAdvice",
    "compute_exit_timing",
    "render_exit_timing",
]
