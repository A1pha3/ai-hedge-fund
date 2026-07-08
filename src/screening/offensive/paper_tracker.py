"""模拟交易追踪器 — paper trading journal + 组合状态 + drawdown 熔断。

记录每笔 action, 计算滚动 P&L, 输出 drawdown 状态供 --daily-action 调整仓位。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

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
        # close_matured 最近一次平仓摘要 (供 render_daily_action 披露, 不持久化)
        self.last_closed_positions: list[dict[str, Any]] = []
        # generate_daily_action 最近一次实际扫描日期 (供 CLI 标题使用, 不持久化)
        self.last_action_trade_date: str = ""
        # generate_daily_action 数据滞后保护原因 (触发时不出新 BUY, 不持久化)
        self.last_action_stale_reason: str = ""

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
        """便捷方法: 记录买入 + 更新组合.

        幂等: 同一 (trade_date, ticker) 的 BUY 已存在则跳过 (对齐
        recommendation_tracker.py:457 natural-key 先例), 防止 --daily-action
        重跑同一报告日重复下单.
        """
        key = (str(trade_date), str(ticker))
        if key in self._existing_buy_keys():
            logger.debug("record_buy: %s 已存在, 跳过 (幂等)", key)
            return
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
        self._save_state()  # 持久化 open_positions (此前缺失 → 新进程读不到增量)

    def _existing_buy_keys(self) -> set[tuple[str, str]]:
        """journal 中已存在的 BUY natural-key 集合 {(trade_date, ticker)}."""
        keys: set[tuple[str, str]] = set()
        for rec in self._load_journal():
            if rec.get("action") == "BUY":
                keys.add((str(rec.get("date", "")), str(rec.get("ticker", ""))))
        return keys

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

    # ---- close matured positions (闭环核心) ----

    def _load_journal(self) -> list[dict[str, Any]]:
        """加载 journal.jsonl 全量记录 (损坏行跳过, 与 daily_brief._load_report 一致)."""
        if not self._journal_path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self._journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("paper_tracker: journal 损坏行已跳过: %s", line[:80])
        return out

    @staticmethod
    def _is_matured(buy_date: str, horizon: int, as_of: str) -> bool:
        """到期判断: buy_date + horizon 日历日 <= as_of (日历日近似, 偏保守)."""
        buy_dt = datetime.strptime(str(buy_date), "%Y%m%d").date()
        as_of_dt = datetime.strptime(str(as_of), "%Y%m%d").date()
        return (buy_dt + timedelta(days=horizon)) <= as_of_dt

    def close_matured(
        self,
        as_of: str,
        *,
        use_data_fetcher: Callable[[str, str, str], list[dict[str, Any]]] | None = None,
        price_loader: Callable[[str, str], Any] | None = None,
    ) -> list[dict[str, Any]]:
        """平掉所有到期仓位, 回填 realized P&L, 驱动 drawdown 熔断.

        闭环核心: 此前 update_pnl 无调用者 → nav 永远 1.0 → drawdown_action() 永远
        'normal'. 本方法在每次 --daily-action 运行开头被调用, 让组合状态真正演进.

        P&L 口径: T+10 收盘价 (close[D+horizon]/entry_price - 1), 与 BTST 先验分布
        (E=+2.57%) 和 north-star next_Nday_return 同口径, 保证 paper-pnl 可与先验
        对比监测 edge 衰减.

        止损披露: 期间 low <= hard_stop 时 stop_would_have_triggered=True (诚实披露
        渲染层告诉 operator 的止损规则), 但主 P&L 仍用 T+10 收盘口径 (不混入止损
        滑点这个额外变量, 保可比性).

        幂等: 已有 EXIT 记录的 (buy_date, ticker) 不重复平仓 (对齐
        recommendation_tracker.py:457 natural-key 先例).

        Args:
            as_of: 平仓基准日 (YYYYMMDD)
            use_data_fetcher: ``(ticker, start, end) -> [{"time", "close"}, ...]``
                注入 seam (测试用), 默认走 fetch_actual_returns 的 _default_price_fetcher
            price_loader: ``(ticker, report_date) -> DataFrame`` 注入 seam (测试用),
                用于读 low 序列判断止损触发; 默认 None → 不检测止损触发 (诚实降级)

        Returns:
            平仓摘要列表, 每项含 ticker/buy_date/realized_pnl/exit_price/
            stop_would_have_triggered
        """
        journal = self._load_journal()

        # 重建 open positions: action=BUY 且无对应 EXIT (幂等: 已平仓的不重平)
        exit_keys: set[tuple[str, str]] = set()
        for rec in journal:
            if rec.get("action") == "EXIT":
                key = (str(rec.get("date", "")), str(rec.get("ticker", "")))
                exit_keys.add(key)

        matured: list[dict[str, Any]] = []
        seen_buy_keys: set[tuple[str, str]] = set()  # 去重: 历史 journal 可能因旧版 record_buy 无幂等而含重复 BUY
        for rec in journal:
            if rec.get("action") != "BUY":
                continue
            buy_date = str(rec.get("date", ""))
            ticker = str(rec.get("ticker", ""))
            key = (buy_date, ticker)
            if key in exit_keys:
                continue  # 已平仓 (幂等)
            if key in seen_buy_keys:
                continue  # 历史 journal 重复 BUY (旧版无幂等) — 只处理首条
            horizon = int(rec.get("horizon", 10) or 10)
            if not self._is_matured(buy_date, horizon, as_of):
                continue  # 未到期
            matured.append(rec)
            seen_buy_keys.add(key)

        if not matured:
            return []

        # 批量取 T+N 收益 (复用 fetch_actual_returns — 与 north-star 同口径)
        from src.screening.recommendation_tracker import fetch_actual_returns

        tickers = list({str(r.get("ticker", "")) for r in matured if r.get("ticker")})
        # from_date 取最早的 buy_date, to_date = as_of
        earliest = min(str(r.get("date", as_of)) for r in matured)
        returns_map = fetch_actual_returns(
            tickers=tickers,
            from_date=earliest,
            to_date=as_of,
            use_data_fetcher=use_data_fetcher,
        )

        closed: list[dict[str, Any]] = []
        portfolio_pnl = 0.0  # 本批累计组合层面 P&L (kelly 加权)
        closed_count = 0

        for rec in matured:
            ticker = str(rec.get("ticker", ""))
            buy_date = str(rec.get("date", ""))
            horizon = int(rec.get("horizon", 10) or 10)
            entry_price = float(rec.get("entry_price", 0.0) or 0.0)
            kelly_pct = float(rec.get("kelly_pct", 0.0) or 0.0)
            hard_stop = float(rec.get("hard_stop", 0.0) or 0.0)
            if entry_price <= 0:
                logger.warning("close_matured: %s %s entry_price<=0, 跳过", buy_date, ticker)
                continue

            ticker_returns = returns_map.get(ticker, {})
            day_key = f"day_{horizon}"
            ret_pct = ticker_returns.get(day_key)  # 百分数, e.g. +5.0 = +5%
            if ret_pct is None:
                # 数据未成熟或拉取失败 — 诚实跳过, 不虚假平仓
                logger.info("close_matured: %s %s 无 day_%d 收益数据, 跳过 (数据未成熟?)", buy_date, ticker, horizon)
                continue

            # 止损触发检测: 期间 low <= hard_stop (披露用, 不影响主 P&L 口径)
            stop_would_have_triggered = False
            execution_result: tuple[float, float] | None = None
            if price_loader is not None:
                try:
                    prices_df = price_loader(ticker, buy_date)
                    if hard_stop > 0:
                        stop_would_have_triggered = self._check_stop_hit(prices_df, buy_date, horizon, hard_stop)
                    execution_result = self._execution_adjusted_return(prices_df, buy_date, horizon)
                except Exception:
                    logger.debug("close_matured: %s low 序列读取失败, 止损检测降级", ticker, exc_info=True)

            if execution_result is not None:
                realized_pnl, exit_price = execution_result
            else:
                realized_pnl = ret_pct / 100.0  # 百分数 → 小数
                exit_price = entry_price * (1 + realized_pnl)

            # 写 EXIT 记录 (幂等 key = (date, ticker) 与 BUY 对齐)
            self.record_action(
                TradeAction(
                    date=buy_date,
                    ticker=ticker,
                    setup=str(rec.get("setup", "")),
                    horizon=horizon,
                    action="EXIT",
                    kelly_pct=kelly_pct,
                    entry_price=entry_price,
                    soft_stop=float(rec.get("soft_stop", 0.0) or 0.0),
                    hard_stop=hard_stop,
                    time_exit=f"T+{horizon}",
                    invalidation_condition=str(rec.get("invalidation_condition", "")),
                    reasoning=f"T+{horizon} 到期平仓; realized={realized_pnl:+.2%}; stop_would_trigger={stop_would_have_triggered}",
                )
            )

            # 组合层面 P&L: 单仓位收益 × kelly 权重 (e.g. +5% × 10% = +0.5% 组合贡献)
            portfolio_pnl += realized_pnl * kelly_pct
            closed_count += 1
            closed.append(
                {
                    "ticker": ticker,
                    "buy_date": buy_date,
                    "realized_pnl": realized_pnl,
                    "exit_price": exit_price,
                    "stop_would_have_triggered": stop_would_have_triggered,
                }
            )

        if closed_count > 0:
            self._state.open_positions = max(0, self._state.open_positions - closed_count)
            self._state.realized_pnl_pct += portfolio_pnl
            # 驱动 drawdown: 把本批组合 P&L 一次性喂给 update_pnl → nav/peak/drawdown 演进
            self.update_pnl(portfolio_pnl)

        # 缓存最近平仓摘要供 render_daily_action 披露 (不持久化, 仅本次运行可见)
        self.last_closed_positions = closed
        return closed

    @staticmethod
    def _check_stop_hit(prices_df: Any, buy_date: str, horizon: int, hard_stop: float) -> bool:
        """检查 buy_date..buy_date+horizon 期间是否有 low <= hard_stop (盘中止损触发).

        prices_df 来自 _load_prices_for_ticker, 含 'date' (datetime) + 'low' 列.
        任一日 low <= hard_stop 即视为触发 (保守: 当日盘中触及就当触发, 不要求收盘确认).
        """
        if prices_df is None or len(prices_df) == 0:
            return False
        if "low" not in prices_df.columns:
            return False
        buy_dt = datetime.strptime(str(buy_date), "%Y%m%d").date()
        end_dt = buy_dt + timedelta(days=horizon)
        # 过滤到 [buy_date, buy_date+horizon] 区间
        df = prices_df.copy()
        if not isinstance(df["date"].dtype, type(prices_df["date"].dtype)):
            pass  # pandas dtype 比较不可靠, 直接尝试
        try:
            mask = (df["date"].dt.date >= buy_dt) & (df["date"].dt.date <= end_dt)
            window = df.loc[mask, "low"].dropna()
        except Exception:
            window = df["low"].dropna()
        if len(window) == 0:
            return False
        return bool((window <= hard_stop).any())

    @staticmethod
    def _execution_adjusted_return(prices_df: Any, buy_date: str, horizon: int) -> tuple[float, float] | None:
        """按 execution_adjuster 口径计算 next-open entry → T+N close 收益.

        返回 ``(realized_pnl, exit_price)``; OHLC 数据不足时返回 None, 调用方可
        降级到 close-to-close。这里复用 ExecutionConfig 默认滑点, 保持 paper P&L
        与 known_distribution/Kelly 先验一致。
        """
        if prices_df is None or len(prices_df) == 0:
            return None
        required = {"date", "open", "close"}
        if not required.issubset(set(prices_df.columns)):
            return None

        from src.screening.offensive.execution_adjuster import ExecutionConfig

        df = prices_df.copy()
        try:
            df["date_str"] = df["date"].dt.strftime("%Y%m%d")
        except Exception:
            df["date_str"] = df["date"].astype(str).str.replace("-", "", regex=False)
        df = df.sort_values("date_str").reset_index(drop=True)

        matches = df.index[df["date_str"] == str(buy_date)]
        if len(matches) == 0:
            return None
        trigger_idx = int(matches[0])
        entry_idx = trigger_idx + 1
        exit_idx = trigger_idx + int(horizon)
        if entry_idx >= len(df) or exit_idx >= len(df):
            return None

        try:
            entry_open = float(df.iloc[entry_idx]["open"])
            exit_close = float(df.iloc[exit_idx]["close"])
        except (TypeError, ValueError):
            return None
        if entry_open <= 0 or exit_close <= 0:
            return None

        slippage = ExecutionConfig().slippage_bps / 10_000.0
        entry_price = entry_open * (1 + slippage)
        exit_price = exit_close * (1 - slippage)
        if entry_price <= 0:
            return None
        return (exit_price / entry_price) - 1.0, exit_price

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
        """更新组合 P&L → 净值 + 回撤.

        口径: daily_pnl_pct 是本批平仓的组合贡献 (sum of realized × kelly),
        即"本批给组合带来的绝对收益占比". nav 用加法累加 (非复利), 因为每笔
        仓位的本金是组合的 kelly_pct 部分, 收益是绝对值不是复利.
        此前用 nav *= 1 + pnl 导致多笔平仓时复利膨胀 (192 笔 × ~0.8% → nav 2.77,
        实际应该 ~1.9).
        """
        self._state.nav += daily_pnl_pct
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
