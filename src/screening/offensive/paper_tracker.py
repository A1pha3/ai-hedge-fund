"""模拟交易追踪器 — paper trading journal + 组合状态 + drawdown 熔断。

记录每笔 action, 计算滚动 P&L, 输出 drawdown 状态供 --daily-action 调整仓位。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _execution_stop_mode() -> str:
    """解析 DAILY_ACTION_EXECUTION_STOP → 止损执行模式.

    回测验证 (2026-07-10, 81 笔 BTST) 显示: 在当前牛市样本上, 所有止损策略
    (固定/ATR/封顶) 都会**降低** E[r] 和 Sharpe — 均值回归 setup 的波动反而赚钱.
    故默认 ``none`` (止损只做披露 stop_would_have_triggered, 不影响 P&L, 与历史口径一致).

    熊市/高波动期 operator 可手动启用:
        DAILY_ACTION_EXECUTION_STOP=atr_k2   # ATR 2.0x 止损真正影响 P&L
        DAILY_ACTION_EXECUTION_STOP=atr_k3   # ATR 3.0x (更宽, 少误杀)
        DAILY_ACTION_EXECUTION_STOP=fixed8   # 固定 -8% 止损真正影响 P&L
        DAILY_ACTION_EXECUTION_STOP=none     # 默认: 止损只披露 (回测最优)

    ⚠ 启用止损会改变 paper P&L 口径, 使其与 known_distributions 的 T+N 收盘分布
    不可比. 启用前应跑 scripts/backtest_exit_strategies.py 确认当前行情下止损有利.
    """
    raw = os.environ.get("DAILY_ACTION_EXECUTION_STOP", "").strip().lower()
    if raw in {"atr_k2", "atr_k3", "fixed8"}:
        return raw
    return "none"  # 默认: 止损只披露 (回测验证的当前最优口径)

_DEFAULT_JOURNAL_DIR = Path("data/paper_trading/")


def _trading_horizon_to_calendar_days(horizon: int) -> int:
    """把 T+N 交易日换算为保守的日历日下限 (与 ``day_{horizon}`` P&L 同口径).

    close_matured 的 realized P&L 用 ``fetch_actual_returns`` 的 ``closes[horizon]``
    (索引 0 = 买入日, 第 N 个交易日收盘价). N 个交易日含 ``floor(N/5)`` 个完整周末
    (每 5 交易日 +2 休息日) → 至少 N + 2*floor(N/5) 日历日. 节假日使其更长 (真实
    backtest journal: BTST horizon=10 → BUY→T+10交易日 间距 14-22 日历日, mean 15.6).

    本函数返回保守下限 (不会晚于真实 T+N 交易日), 用于 _is_matured 预过滤 + 显示
    matures_on — 旧实现用 ``timedelta(days=horizon)`` (纯日历日) 比 T+N 交易日早
    4-12 天, 导致 operator 看到 "今日到期" 但 day_N 收盘价尚未存在 → 4-12 天空窗.

    horizon=5 → 7 日历日; horizon=10 → 14 日历日.
    """
    n = max(0, int(horizon))
    return n + 2 * (n // 5)


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
    trigger_strength: float = 0.0  # 闭合学习环: 记录 ranker 评分供回测验证
    degraded: bool = False  # 是否基于残缺数据命中


@dataclass
class PortfolioState:
    """组合 + 回撤状态。"""

    nav: float = 1.0  # 净值 (初始 1.0)
    peak: float = 1.0  # 历史净值最高点
    drawdown_pct: float = 0.0  # 当前回撤 (负数)
    open_positions: int = 0  # 当前持仓数
    # C-PORTFOLIO-CAP (20260710): 已开仓位的 kelly_pct 之和 (组合敞口%)。
    # 供 generate_daily_action 的 60% 组合上限判断 — 此前只数 open_positions (计数),
    # 不追踪敞口% → 上限每次 run 从 0 起算, 忽略 T+10 跨日持仓 → 真实敞口峰值 260%。
    open_exposure: float = 0.0
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
        # 自愈 open_positions: 历史 journal 可能因旧版 record_buy 无幂等保护而含
        # 重复 BUY 记录 (如 688629 被写 4 次), 导致持久化的 open_positions 计数虚高,
        # 污染 drawdown 熔断判断。从 journal 真值 (去重 BUY - EXIT) 重算并校正。
        self._reconcile_open_positions()
        # close_matured 最近一次平仓摘要 (供 render_daily_action 披露, 不持久化)
        self.last_closed_positions: list[dict[str, Any]] = []
        # generate_daily_action 最近一次实际扫描日期 (供 CLI 标题使用, 不持久化)
        self.last_action_trade_date: str = ""
        # generate_daily_action 数据滞后保护原因 (触发时不出新 BUY, 不持久化)
        self.last_action_stale_reason: str = ""
        # C-PORTFOLIO-CAP (20260710): 本次 run 后组合总敞口 (已开+新仓) + 因超 60%
        # 上限被跳过的剩余信号数. 供 render_daily_action 披露 (不持久化, 仅本次运行可见).
        self.last_portfolio_exposure: float = float(self._state.open_exposure)
        self.last_cap_blocked_count: int = 0
        # C-DAILY-ACTION-POSITION-VISIBILITY: 本次因敞口超限未录入的候选 (按强度排序),
        # 供 render 列出"今日可交易但暂不买入"的票. 不持久化.
        self.last_blocked_candidates: list = []

    # ---- portfolio state ----

    def _load_state(self) -> PortfolioState:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                return PortfolioState(**data)
            except Exception:
                logger.warning("paper_tracker: failed to load portfolio state from %s, starting fresh", self._state_path, exc_info=True)
        return PortfolioState()

    def _save_state(self):
        self._state_path.write_text(
            json.dumps(
                {
                    "nav": self._state.nav,
                    "peak": self._state.peak,
                    "drawdown_pct": self._state.drawdown_pct,
                    "open_positions": self._state.open_positions,
                    "open_exposure": self._state.open_exposure,
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

    def _reconcile_open_positions(self) -> None:
        """从 journal 真值重算 open_positions + open_exposure, 自愈历史重复 BUY / 旧版无字段.

        历史 journal 可能含重复 BUY 记录 (旧版 record_buy 无跨进程幂等保护时,
        多次独立进程运行会重复写入同一 (date, ticker)), 导致持久化的
        ``open_positions`` 虚高 → drawdown 熔断判断失真。

        重算口径与 ``close_matured`` (line 244-259) 一致:
            open_positions = 去重后 BUY 数 - EXIT 数
            open_exposure  = sum(去重未平仓 BUY.kelly_pct)
        (BUY 按 (date, ticker) 去重, 与 close_matured 的 seen_buy_keys 同口径)。
        只校正内存 state + 持久化; 不修改 journal 原始记录 (审计完整性)。
        """
        if not self._journal_path.exists():
            return
        journal = self._load_journal()
        exit_keys: set[tuple[str, str]] = set()
        for rec in journal:
            if rec.get("action") == "EXIT":
                exit_keys.add((str(rec.get("date", "")), str(rec.get("ticker", ""))))
        seen_buy_keys: set[tuple[str, str]] = set()
        open_count = 0
        open_exposure = 0.0
        for rec in journal:
            if rec.get("action") != "BUY":
                continue
            key = (str(rec.get("date", "")), str(rec.get("ticker", "")))
            if key in seen_buy_keys:
                continue  # 去重: 历史 journal 重复 BUY 只计一次
            seen_buy_keys.add(key)
            if key not in exit_keys:
                open_count += 1
                try:
                    open_exposure += float(rec.get("kelly_pct", 0.0) or 0.0)
                except (TypeError, ValueError):
                    pass
        if self._state.open_positions != open_count or abs(self._state.open_exposure - open_exposure) > 1e-9:
            logger.info(
                "paper_tracker: open_positions 自愈 %d → %d, open_exposure 自愈 %.4f → %.4f (journal 去重 BUY - EXIT)",
                self._state.open_positions,
                open_count,
                self._state.open_exposure,
                open_exposure,
            )
            self._state.open_positions = open_count
            self._state.open_exposure = open_exposure
            self._save_state()

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
                        "trigger_strength": action.trigger_strength,
                        "degraded": action.degraded,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def record_buy(self, trade_date: str, ticker: str, setup: str, horizon: int, entry_price: float, kelly_pct: float, soft_stop: float, hard_stop: float, invalidation: str, reasoning: str = "", trigger_strength: float = 0.0, degraded: bool = False):
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
                trigger_strength=trigger_strength,
                degraded=degraded,
            )
        )
        self._state.open_positions += 1
        # C-PORTFOLIO-CAP: 累加单仓敞口 (kelly_pct), 供 generate_daily_action
        # 的组合 60% 上限判断 — 计入已开仓, 避免 T+10 跨日持仓导致超杠杆。
        self._state.open_exposure += float(kelly_pct or 0.0)
        # autodev-32 /loop session 6: total_trades was persisted but never
        # incremented (dead field → state file always showed 0). Now counts
        # each opened BUY so the operator sees cumulative trade volume.
        self._state.total_trades += 1
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

    def open_positions_detail(self, as_of: str = "") -> list[dict[str, Any]]:
        """返回当前未平仓位明细 (供 render 披露"我买了什么 + 何时到期释放").

        C-DAILY-ACTION-POSITION-VISIBILITY (20260710): 此前 render 只显示
        ``持仓数: N`` (计数), operator 看不到自己持有哪些票、何时到期。本方法
        从 journal 真值 (去重 BUY - EXIT, 与 close_matured 同口径) 重建未平仓
        明细, 含每仓的到期日 (buy_date + T+N 交易日保守日历日下限) 与距今天数。

        到期日语义 (autodev loop 177): 与 close_matured 的 P&L 口径一致 — realized
        return 用 ``closes[horizon]`` (第 N 个交易日收盘价), 故 matures_on 也用交易日
        (``_trading_horizon_to_calendar_days``), 不能用纯日历日 (旧实现早 4-12 天,
        导致 "今日到期" 但 day_N 数据未成熟 → 4-12 天空窗).

        Args:
            as_of: 基准日 YYYYMMDD (通常为信号日), 用于算 days_to_maturity.
                   空字符串则不算 days_to_maturity.

        Returns:
            list[dict] 每项含 ticker/buy_date/setup/horizon/entry_price/kelly_pct/
            matures_on/days_to_maturity, 按 matures_on 升序 (最快到期的在前,
            让 operator 第一眼看到"哪些仓位马上释放").
        """
        journal = self._load_journal()
        exit_keys: set[tuple[str, str]] = set()
        for rec in journal:
            if rec.get("action") == "EXIT":
                exit_keys.add((str(rec.get("date", "")), str(rec.get("ticker", ""))))
        seen: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        for rec in journal:
            if rec.get("action") != "BUY":
                continue
            buy_date = str(rec.get("date", ""))
            ticker = str(rec.get("ticker", ""))
            key = (buy_date, ticker)
            if key in exit_keys or key in seen:
                continue
            seen.add(key)
            horizon = int(rec.get("horizon", 10) or 10)
            matures_on = ""
            try:
                cal_days = _trading_horizon_to_calendar_days(horizon)
                matures_dt = datetime.strptime(buy_date, "%Y%m%d").date() + timedelta(days=cal_days)
                matures_on = matures_dt.strftime("%Y%m%d")
            except ValueError:
                pass
            days_to: int | None = None
            if as_of and matures_on:
                try:
                    days_to = (datetime.strptime(matures_on, "%Y%m%d").date() - datetime.strptime(as_of, "%Y%m%d").date()).days
                except ValueError:
                    pass
            out.append(
                {
                    "ticker": ticker,
                    "buy_date": buy_date,
                    "setup": str(rec.get("setup", "")),
                    "horizon": horizon,
                    "entry_price": float(rec.get("entry_price", 0.0) or 0.0),
                    "kelly_pct": float(rec.get("kelly_pct", 0.0) or 0.0),
                    "matures_on": matures_on,
                    "days_to_maturity": days_to,
                }
            )
        out.sort(key=lambda r: (r["matures_on"] or "99999999", r["ticker"]))
        return out

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
        """到期判断: buy_date + T+N 交易日 (保守日历日下限) <= as_of.

        与 close_matured 的 P&L 口径一致: realized return 用 ``closes[horizon]`` (第 N
        个交易日收盘价), 故到期判断也用交易日而非纯日历日. 旧实现 ``timedelta(days=N)``
        把 N 个交易日当 N 个日历日, 比 T+N 交易日 (≈ N + 2*floor(N/5) 日历日, 节假日更长)
        早 4-12 天 → 过早触发 close_matured 但 day_N 收盘价未成熟 → 静默跳过 + 显示
        "今日到期" 空窗. 现用保守日历日下限 (不晚于真实 T+N 交易日), 避免过早判到期.
        """
        buy_dt = datetime.strptime(str(buy_date), "%Y%m%d").date()
        as_of_dt = datetime.strptime(str(as_of), "%Y%m%d").date()
        cal_days = _trading_horizon_to_calendar_days(horizon)
        return (buy_dt + timedelta(days=cal_days)) <= as_of_dt

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
        closed_exposure = 0.0  # C-PORTFOLIO-CAP: 本批平仓位的 kelly_pct 之和 (扣减 open_exposure)
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

            # 止损触发检测: 期间 low <= hard_stop (披露用, 不影响主 P&L 口径)
            stop_would_have_triggered = False
            execution_result: tuple[float, float] | None = None
            stop_executed = False  # DAILY_ACTION_EXECUTION_STOP 启用时是否真按止损价平仓
            prices_df = None
            if price_loader is not None:
                try:
                    # Bug fix (2026-07-12): 用 as_of 而非 buy_date 作 cutoff. _load_prices_for_ticker
                    # 按 report_date 过滤 df[date <= cutoff]; 传 buy_date 会滤掉 buy_date 之后的
                    # T+N 退出数据 → _execution_adjusted_return 永远 None (exit_idx 越界) → 回退到
                    # fetch_actual_returns 的批次最早 buy_date 锚 (非 earliest 仓位 P&L 错误).
                    # 传 as_of 保留完整窗口让 per-position 重算生效.
                    prices_df = price_loader(ticker, as_of)
                    if hard_stop > 0:
                        stop_would_have_triggered = self._check_stop_hit(prices_df, buy_date, horizon, hard_stop)
                    execution_result = self._execution_adjusted_return(prices_df, buy_date, horizon)
                    # 止损执行策略 (per-setup):
                    # - env DAILY_ACTION_EXECUTION_STOP 覆盖全局 (最高优先级)
                    # - 否则读 RiskPlan.stop_policy: BTST=disclose_only, OversoldBounce=execute(fixed8)
                    # - OversoldBounce execute: 止损触发 → 按止损价平仓替代 T+N 收盘
                    stop_mode = _execution_stop_mode()
                    if stop_mode == "none":
                        # env 没覆盖 → 检查 per-setup policy
                        setup_name = str(rec.get("setup", ""))
                        if setup_name == "oversold_bounce":
                            stop_mode = "fixed8"  # OB 默认执行 -8% 止损
                    if stop_mode != "none" and execution_result is not None:
                        stop_ret = self._stop_adjusted_return(prices_df, buy_date, horizon, stop_mode)
                        if stop_ret is not None:
                            execution_result = stop_ret  # 覆盖为止损价平仓
                            stop_executed = True
                except Exception:
                    logger.debug("close_matured: %s low 序列读取失败, 止损检测降级", ticker, exc_info=True)

            # Bug fix (2026-07-12): DEFAULT_HORIZONS=(1,3,5,10,15,20,25,30) 不含 8 → BTST T+8 的
            # fetch_actual_returns 永远无 day_8 → ret_pct=None. 旧代码此处直接 continue, 跳过
            # price_loader 已算出的 execution_result → T+8 仓位永远无法平仓. 现仅在两个数据源
            # 都无结果时才跳过 (price_loader 出 result 时正常平仓).
            if execution_result is None and ret_pct is None:
                logger.info("close_matured: %s %s 无 day_%d 收益数据且 price_loader 无结果, 跳过 (数据未成熟?)", buy_date, ticker, horizon)
                continue

            if execution_result is not None:
                realized_pnl, exit_price = execution_result
            else:
                # Bug fix: 原来用 ret_pct (来自 fetch_actual_returns, 以批次最早 buy_date
                # 为锚 → 非 earliest 仓位的 P&L 错误). 现在优先用 price_loader 按本仓位
                # 的 buy_date close-to-close 重算; 只有 price_loader 不可用时才回退到 ret_pct.
                per_pos_ret = self._close_to_close_return(prices_df if price_loader is not None else None, buy_date, horizon)
                if per_pos_ret is not None:
                    realized_pnl, exit_price = per_pos_ret
                else:
                    realized_pnl = ret_pct / 100.0  # 百分数 → 小数 (last resort)
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
                        reasoning=f"T+{horizon} 到期平仓; realized={realized_pnl:+.2%}; stop_would_trigger={stop_would_have_triggered}; stop_executed={stop_executed}",
                )
            )

            # 组合层面 P&L: 单仓位收益 × kelly 权重 (e.g. +5% × 10% = +0.5% 组合贡献)
            portfolio_pnl += realized_pnl * kelly_pct
            closed_exposure += kelly_pct
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
            # C-PORTFOLIO-CAP: 扣减已平仓位的敞口 (不低于 0, 防历史脏数据负穿).
            self._state.open_exposure = max(0.0, self._state.open_exposure - closed_exposure)
            self._state.realized_pnl_pct += portfolio_pnl
            # 驱动 drawdown: 把本批组合 P&L 一次性喂给 update_pnl → nav/peak/drawdown 演进
            self.update_pnl(portfolio_pnl)

        # 缓存最近平仓摘要供 render_daily_action 披露 (不持久化, 仅本次运行可见)
        self.last_closed_positions = closed
        return closed

    @staticmethod
    def _check_stop_hit(prices_df: Any, buy_date: str, horizon: int, hard_stop: float) -> bool:
        """检查 buy_date..T+N 交易日 期间是否有 low <= hard_stop (盘中止损触发).

        prices_df 来自 _load_prices_for_ticker, 含 'date' (datetime) + 'low' 列.
        任一日 low <= hard_stop 即视为触发 (保守: 当日盘中触及就当触发, 不要求收盘确认).

        窗口语义 (autodev-38 loop 178): horizon 是 T+N 交易日 (与 _is_matured /
        _execution_adjusted_return 同参数), 不能用 ``timedelta(days=horizon)`` (日历日)
        —— BTST h=10 日历日窗口到 +10 天 (≈7 交易日), 真实 T+10 交易日 ≈ +14 日历日,
        第 8-10 交易日的 low 跌穿会被漏掉 → stop_would_have_triggered 披露低计. 现用
        保守日历日下限 (``_trading_horizon_to_calendar_days``), 与同文件
        _execution_adjusted_return 的 ``exit_idx = trigger_idx + horizon`` (交易日索引) 一致.
        """
        if prices_df is None or len(prices_df) == 0:
            return False
        if "low" not in prices_df.columns:
            return False
        buy_dt = datetime.strptime(str(buy_date), "%Y%m%d").date()
        cal_days = _trading_horizon_to_calendar_days(horizon)
        end_dt = buy_dt + timedelta(days=cal_days)
        # 过滤到 [buy_date, buy_date + T+N 交易日保守日历日下限] 区间.
        # date 列可能为 datetime64 或字符串 — 直接尝试 .dt.date, 失败时兜底用全量 low.
        df = prices_df.copy()
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

    @staticmethod
    def _close_to_close_return(prices_df: Any, buy_date: str, horizon: int) -> tuple[float, float] | None:
        """按本仓位的 buy_date close-to-close 计算 T+N 收益 (fallback for _execution_adjusted_return).

        Bug fix: 当 _execution_adjusted_return 因缺 open 列或滑点配置失败返回 None 时,
        原来用 fetch_actual_returns 的 ret_pct (以批次最早 buy_date 为锚 → 错误).
        此方法用 price_loader 提供的 per-position 数据按 close[buy_date] → close[buy_date+N] 重算.

        Returns:
            (realized_pnl, exit_price) 或 None (数据不足时)
        """
        if prices_df is None or len(prices_df) == 0:
            return None
        if "date" not in prices_df.columns or "close" not in prices_df.columns:
            return None

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
        exit_idx = trigger_idx + int(horizon)
        if exit_idx >= len(df):
            return None

        try:
            entry_close = float(df.iloc[trigger_idx]["close"])
            exit_close = float(df.iloc[exit_idx]["close"])
        except (TypeError, ValueError):
            return None
        if entry_close <= 0 or exit_close <= 0:
            return None
        return (exit_close / entry_close) - 1.0, exit_close

    @staticmethod
    def _stop_adjusted_return(
        prices_df: Any,
        buy_date: str,
        horizon: int,
        mode: str,
    ) -> tuple[float, float] | None:
        """可选止损执行: 触止损时按止损价平仓 (替代 T+N 收盘).

        仅当 DAILY_ACTION_EXECUTION_STOP != "none" 时由 close_matured 调用.
        回测验证 (2026-07-10): 当前牛市样本上止损会降低 E[r], 故默认关闭.
        此方法让 operator 在熊市/高波动期可手动启用真实止损执行.

        入场价口径与 _execution_adjusted_return 一致: T+1 开盘 × (1+滑点).
        止损价基于此 entry_price 计算, 保证与主 P&L 口径同源.

        Args:
            prices_df: 单 ticker 价格 DataFrame (date/open/high/low/close).
            buy_date: 信号日 YYYYMMDD (T+0).
            horizon: T+N 交易日.
            mode: "atr_k2" / "atr_k3" / "fixed8".

        Returns:
            (realized_pnl, exit_price) 若止损触发; None 若未触发 (调用方用 T+N 收盘).
        """
        if prices_df is None or len(prices_df) == 0:
            return None
        required = {"date", "open", "high", "low"}
        if not required.issubset(prices_df.columns if hasattr(prices_df, "columns") else set()):
            return None

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

        from src.screening.offensive.execution_adjuster import ExecutionConfig

        slippage = ExecutionConfig().slippage_bps / 10_000.0
        # 入场价 = T+1 开盘 × (1+滑点), 与 _execution_adjusted_return 同口径
        entry_price = float(df.iloc[entry_idx]["open"]) * (1 + slippage)
        if entry_price <= 0:
            return None

        # 确定止损价
        if mode == "fixed8":
            stop_price = entry_price * 0.92
        elif mode in ("atr_k2", "atr_k3"):
            from src.screening.offensive.atr_utils import atr_stop_price, compute_atr

            k = 2.0 if mode == "atr_k2" else 3.0
            # 用 entry 前的数据算 ATR (避免未来函数)
            atr = compute_atr(df, period=20, at_idx=entry_idx)
            stop_price = atr_stop_price(entry_price, atr, k=k)
        else:
            return None

        if stop_price is None or stop_price <= 0:
            return None

        # 扫描持仓期间每日 low; 触止损即出场.
        holding = df.iloc[entry_idx : exit_idx + 1]
        for _, row in holding.iterrows():
            low = float(row.get("low", 0) or 0)
            if low <= stop_price and low > 0:
                exit_at_stop = stop_price * (1 - slippage)
                return ((exit_at_stop / entry_price) - 1.0), exit_at_stop
        return None  # 未触止损 → 调用方用 T+N 收盘

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
