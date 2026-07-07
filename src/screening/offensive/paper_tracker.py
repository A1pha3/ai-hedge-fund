"""模拟交易追踪器 — paper trading journal + 组合状态 + drawdown 熔断。

记录每笔 action, 计算滚动 P&L, 输出 drawdown 状态供 --daily-action 调整仓位。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_JOURNAL_DIR = Path("data/paper_trading/")


@dataclass
class TradeAction:
    """单日交易动作。"""

    date: str  # YYYYMMDD
    ticker: str
    setup: str
    horizon: int  # T+N
    action: str  # "BUY" | "HOLD" | "EXIT" | "SKIP"
    kelly_pct: float  # half-Kelly 仓位
    entry_price: float  # 买入价 (次日开盘)
    soft_stop: float  # 软止损价
    hard_stop: float  # 硬止损价
    time_exit: str  # "T+N"
    invalidation_condition: str
    reasoning: str = ""


@dataclass
class PortfolioState:
    """组合 + 回撤状态。"""

    nav: float = 1.0  # 净值 (初始 1.0)
    peak: float = 1.0  # 历史净值最高点
    drawdown_pct: float = 0.0  # 当前回撤 (负数)
    open_positions: int = 0  # 当前持仓数
    total_trades: int = 0
    realized_pnl_pct: float = 0.0  # 累计已实现收益%
    last_30d_pnl: list[float] = field(default_factory=list)


class PaperTracker:
    """模拟交易追踪器: 日志 + 组合 P&L + drawdown 熔断。"""

    def __init__(self, journal_dir: Path | str = _DEFAULT_JOURNAL_DIR):
        self._dir = Path(journal_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._journal_path = self._dir / "journal.jsonl"
        self._state_path = self._dir / "portfolio_state.json"
        self._open_path = self._dir / "open_positions.json"
        self._state = self._load_state()

    # ---- portfolio state ----

    def _load_state(self) -> PortfolioState:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                return PortfolioState(**data)
            except Exception:
                pass
        return PortfolioState()

    def _save_state(self):
        self._state_path.write_text(
            json.dumps(
                {
                    "nav": self._state.nav,
                    "peak": self._state.peak,
                    "drawdown_pct": self._state.drawdown_pct,
                    "open_positions": self._state.open_positions,
                    "total_trades": self._state.total_trades,
                    "realized_pnl_pct": self._state.realized_pnl_pct,
                    "last_30d_pnl": self._state.last_30d_pnl[-30:],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @property
    def state(self) -> PortfolioState:
        return self._state

    # ---- daily action journal ----

    def record_action(self, action: TradeAction):
        """写入交易日志, 不改变组合状态 (打开/关闭仓位在 close_matured 里处理)。"""
        with open(self._journal_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "date": action.date,
                        "ticker": action.ticker,
                        "setup": action.setup,
                        "horizon": action.horizon,
                        "action": action.action,
                        "kelly_pct": action.kelly_pct,
                        "entry_price": action.entry_price,
                        "soft_stop": action.soft_stop,
                        "hard_stop": action.hard_stop,
                        "time_exit": action.time_exit,
                        "invalidation_condition": action.invalidation_condition,
                        "reasoning": action.reasoning,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def record_buy(self, trade_date: str, ticker: str, setup: str, horizon: int, entry_price: float, kelly_pct: float, soft_stop: float, hard_stop: float, invalidation: str, reasoning: str = ""):
        """便捷方法: 记录买入 + 更新组合。"""
        self.record_action(
            TradeAction(
                date=trade_date,
                ticker=ticker,
                setup=setup,
                horizon=horizon,
                action="BUY",
                kelly_pct=kelly_pct,
                entry_price=entry_price,
                soft_stop=soft_stop,
                hard_stop=hard_stop,
                time_exit=f"T+{horizon}",
                invalidation_condition=invalidation,
                reasoning=reasoning,
            )
        )
        self._state.open_positions += 1

    def record_skip(self, date: str, ticker: str, setup: str, horizon: int, reasoning: str = ""):
        """记录跳过的 ticker (日志用, 不更新组合)。"""
        self.record_action(
            TradeAction(
                date=date,
                ticker=ticker,
                setup=setup,
                horizon=horizon,
                action="SKIP",
                kelly_pct=0.0,
                entry_price=0.0,
                soft_stop=0.0,
                hard_stop=0.0,
                time_exit="",
                invalidation_condition="",
                reasoning=reasoning,
            )
        )

    # ---- drawdown check ----

    def drawdown_action(self) -> str:
        """根据组合回撤返回动作 (与 risk_framework.drawdown_action 一致)。"""
        dd = self._state.drawdown_pct
        if dd <= -0.20:
            return "liquidate"  # -20% 清仓
        if dd <= -0.15:
            return "decrease"  # -15% 降仓
        return "normal"

    def update_pnl(self, daily_pnl_pct: float):
        """更新每日组合 P&L → 净值 + 回撤。"""
        self._state.nav *= 1 + daily_pnl_pct
        self._state.peak = max(self._state.peak, self._state.nav)
        self._state.drawdown_pct = (self._state.nav / self._state.peak) - 1
        self._state.last_30d_pnl.append(daily_pnl_pct)
        if len(self._state.last_30d_pnl) > 30:
            self._state.last_30d_pnl = self._state.last_30d_pnl[-30:]
        self._save_state()

    def reset(self):
        """重置模拟交易。"""
        self._state = PortfolioState()
        self._save_state()
