"""--daily-action — Phase A 核心: 每日机械交易动作 (移除情绪决策)。

输入: 全市场 price_cache + fund_flow store + paper_trading 状态
输出: 今日的具体动作 (BUY/EXIT/SKIP) + 入场价 + 止损 + 仓位 + 风险计划

设计原则 (Phase A "稳定小 edge"):
- 用 Phase 0 验证过的 setup 分布作 Kelly 先验 (不动态拟合, 防过拟合)
- 全市场扫描 (不依赖 --auto 的 score_b 候选池 — 凸性 setup 要极端股票, 不是"好股票")
- drawdown 熔断自动降仓/清仓 (移除"亏时恐慌" 的情绪)
- 预提交止损 + 时间退出 (移除"希望/恐惧")
- 每笔写入 paper_trading journal (暴露行为偏差, 30 天后复盘)
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.screening.offensive.daily_action_service import (
    SETUP_HOLDING_SESSIONS,
    ActionItem,
    PlanCandidate,
    RegimeAuthorization,
)
from src.screening.offensive.daily_action_snapshot import VerifiedDailyActionSnapshot
from src.screening.offensive.data.fund_flow_store import FundFlowRecord
from src.screening.offensive.known_distributions import get_known_distribution
from src.screening.offensive.paper_tracker import PaperTracker, TradeAction
from src.screening.offensive.price_returns import chained_return_pct
from src.screening.offensive.risk_framework import build_risk_plan
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup
from src.screening.offensive.statistics import Distribution
from src.tools.ashare_board_utils import is_excluded_ticker
from src.utils.atomic_files import atomic_write_csv, atomic_write_json
from src.utils.date_utils import SignalSessionUnavailable, resolve_signal_session

logger = logging.getLogger(__name__)

# Phase A: 多 setup (BTST T+10 + OversoldBounce T+5), 单仓位上限, 严格风控
# 优化: per-setup 仓位上限 — BTST 有统计显著的 alpha (E=+8.15%), 可分配更大仓位;
# OversoldBounce 无可证明 alpha (E=+0.34%, CI 跨 0), 严格限制仓位.
_MAX_POSITION_PCT = 0.10  # 默认单票上限
_MAX_POSITION_PCT_BY_SETUP: dict[str, float] = {
    "btst_breakout": 0.10,       # v2 ledger stays at 10% until canonical regime evidence is bound
    "oversold_bounce": 0.05,     # OB: 无 alpha, 限制到 5% (即使恢复也低仓位)
}
_MAX_PORTFOLO_PCT = 0.60  # 组合 ≤ 60%
# 最低入场价: 低价股 (<3 元) 尾部亏损严重 (002217 @2.61 → -35.6%, 002560 @12.90 → -31.5%).
# 回测: price>=3 去掉 2 笔垃圾股, E[r] +8.15%→+8.40%, worst -35.6%→-31.5%.
_MIN_ENTRY_PRICE = 3.0
# 最低 trigger_strength: 过滤掉 ranker 底部的垃圾信号.
# 2026-07-12 (5 因子 ranker + T+10) 阈值敏感性回测 (626 只 A 股, 1308 信号):
#   ts>=0.35: n=1114, WR 61.0%, +7.16%, Sharpe 0.365 (旧值)
#   ts>=0.50: n=777,  WR 62.8%, +7.54%, Sharpe 0.383 ← 取此 (平衡 WR/收益/样本量)
#   ts>=0.55: n=634,  WR 64.0%, +7.33%, Sharpe 0.391 (Sharpe 最优但样本少)
#   ts>=0.70: n=330,  WR 65.5%, +7.78%, Sharpe 0.397 (WR 最高但仅 25% 样本)
# 0.50 在 WR (+1.8pp)、收益 (+0.38pp)、Sharpe 上均优于 0.35, 且保留 70% 样本.
_MIN_TRIGGER_STRENGTH = 0.50
_USE_TUSHARE_PRICES = True  # akshare 在本 env 代理封了
_CN_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
# 买入窗口截止: 信号日 S → 计划买入日 = S 下一交易日开盘. 在买入日当天, 超过此时刻
# 即视为窗口已过, 不再输出新 BUY (避免事后补单/盘中追单).
# 设为 17:00 (而非开盘 09:30): 与信号日 17:00 数据就绪规则统一 —— 只要当天未过 17:00,
# 用户都能看到 "昨日信号 → 今日买入" 的完整计划用于研究盘面; 17:00 后切换到次日信号,
# 旧信号的计划自动失效. paper trading 计划非实盘自动下单, 盘中可读无下单风险.
_ENTRY_WINDOW_CUTOFF = time(17, 0)

# 已验证的 setup 配置 (Phase 0 通过的 setup + 对应 known_distribution)
# (setup_name, setup_class, horizon)
_VERIFIED_SETUPS = [
    ("btst_breakout", BtstBreakoutSetup, 10),  # T+10: 用户 "未来10天" 目标; E[r]+6.57% > T+8 +5.43%; 在 DEFAULT_HORIZONS 内
    ("oversold_bounce", OversoldBounceSetup, 5),
]

# regime 仓位放大已移除 (2026-08-14, 对抗性审查 P1a): 原 crisis=1.2×/risk_off=1.1×
# 加仓表依据 data/paper_trading_backtest 192 笔成交 (crisis 76%/+16.93%), 但该口径有
# 双重缺陷 — (a) 非诚实执行 (信号日 close 入场无滑点; court 发现回放线束传 None 绕过
# _execution_adjusted_return), (b) 成交宇宙选择偏差 (只统计实际买入票, 非全触发候选).
# 诚实 court (T+1开盘+滑点, 全候选, 同窗口 2026-01→07) 结论相反: crisis 9%/-8.98% (n=11),
# risk_off 8%/-16.12% (n=13) — 灾难 regime 该阻断而非加仓. 且加仓系数表从未生效
# (_REGIME_SIZING_EVIDENCE_BOUND 恒 False), 留着只是挂着引信的错误开关.
# 见 data/reports/regime_gate_decision_pack_2026-08-09.md.

# regime gate (2026-08-14 接线, R-5.F 收口): 信号日 regime ∈ {crisis, risk_off} 不开新仓.
# 证据链:
#   1. 诚实 court (T+1开盘+滑点, 全候选, 2026H1): crisis 9%/-8.98% (n=11), risk_off
#      8%/-16.12% (n=13) 灾难; gated BTST-only NAV 1.430 vs ungated 1.133 (+26pp).
#   2. 跨期复现 (2025H2, fund_flow 可得的唯一独立窗口): gated 159 笔 51.4%/+3.97%
#      vs ungated 173 笔 50.0%/+3.71% — 牛市段零成本 (NAV 1.587 vs 1.594), 方向为正.
#   3. 止损×gate 联合网格 (两窗 × {ungated,gated} × {none,fixed8}): fixed8 止损在全部
#      4 组合降收益 (胜率 -9~12pp), gated+无止损 两窗 per-trade 全优 — gate 替代止损.
#   数据局限: 2022/2024 跨期被 fund_flow 缓存阻塞 (2025-07 起), 无法验证.
# detect 照跑 (面板继续积累危机日对照组), 仅在仓位/计划层阻断.
# 见 data/reports/regime_gate_decision_pack_2026-08-09.md,
#     data/reports/stop_loss_x_regime_gate_court_20260814.json.
_REGIME_GATE_BLOCK_REGIMES = frozenset({"crisis", "risk_off"})

# v2 ledger 可承接的 setup 白名单. PlanCandidate.__post_init__ 硬拒白名单外 setup —
# scan 层必须先拦截, 否则按文档恢复 OB (DAILY_ACTION_DISABLED_SETUPS=none) 后,
# OB 命中会在构造 PlanCandidate 时抛异常 → 当日全部新计划 (含 BTST) 被 fail-closed.
_LEDGER_ENABLED_SETUPS = ("btst_breakout",)


def _enforce_open_cap() -> bool:
    """C-PORTFOLIO-CAP (20260710): 组合上限是否计入已开仓位.

    默认 true (修复生效): generate_daily_action 的 portfolio_position_used 从
    tracker.state.open_exposure 起算, T+10 跨日持仓计入 60% 上限 → 敞口守上限.
    真实 journal 曾因 per-run 重置峰值 260% (26 仓), 61 天超 60%.

    设 DAILY_ACTION_ENFORCE_OPEN_CAP=false 可恢复旧 per-run 行为 (逃生口,
    供 owner 对比; 默认行为是修复后的正确口径).
    """
    raw = os.environ.get("DAILY_ACTION_ENFORCE_OPEN_CAP", "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


# 默认暂停的 setup (运行时不进 setup_configs, 不产生 BUY).
# OversoldBounce: 2026 实测 E[r]=+0.34% (n=59) 统计上不异于 0 (95% CI 跨 0, p≈0.85),
# 且尾部亏损比 BTST 更厚 (亏损>10% 占比 20% vs 11%); 暂停避免占用 BTST 的仓位配额.
# 可通过 DAILY_ACTION_DISABLED_SETUPS=none 恢复 (补全历史数据重跑后再决定去留).
_DEFAULT_DISABLED_SETUPS = {"oversold_bounce"}


def _env_setup_disable_list() -> set[str]:
    """解析 DAILY_ACTION_DISABLED_SETUPS → 暂停的 setup 名集合.

    默认含 ``_DEFAULT_DISABLED_SETUPS`` (当前为 oversold_bounce). env 可追加逗号分隔的
    setup 名 (如 ``"oversold_bounce,btst_breakout"``); 特殊值 ``"none"`` 清空默认
    (恢复全部 setup), 便于补全历史数据重跑后一键恢复验证.
    """
    disabled = set(_DEFAULT_DISABLED_SETUPS)
    raw = os.environ.get("DAILY_ACTION_DISABLED_SETUPS", "")
    if raw.strip().lower() == "none":
        return set()
    disabled.update(s.strip() for s in raw.split(",") if s.strip())
    return disabled


def _load_backtest_setup_performance() -> Any | None:
    """Load local paper-backtest setup performance for operator disclosure.

    This is best-effort disclosure only. ``--daily-action`` must still render if
    the local backtest artifact is absent or corrupt.
    """
    try:
        from src.screening.offensive.setup_performance import summarize_setup_performance

        regimes_by_date: dict[str, str] = {}
        regime_path = Path("data/reports/regime_history.json")
        if regime_path.exists():
            regimes_by_date = {str(k): str(v) for k, v in json.loads(regime_path.read_text(encoding="utf-8")).items()}
        return summarize_setup_performance(
            Path("data/paper_trading_backtest/journal.jsonl"),
            regimes_by_date=regimes_by_date,
        )
    except Exception:
        logger.debug("daily-action setup performance disclosure unavailable", exc_info=True)
        return None


def _format_backtest_stats(stats: Any | None) -> str:
    if stats is None or getattr(stats, "n", 0) <= 0:
        return ""
    base = f" (真实回测 n={stats.n} winrate={stats.winrate:.0%} E={stats.expected_return:+.2%})"
    # autodev-32 /loop session 6: small-n warning prevents operator from
    # over-weighting a setup based on a few lucky trades.
    if getattr(stats, "low_confidence", False):
        base += " ⚠少样本"
    return base


def _setup_policy_lines(disabled_setups: set[str] | None = None, *, explain: bool = False) -> list[str]:
    """Render active/paused setup policy with first-principles backtest evidence."""
    disabled = _env_setup_disable_list() if disabled_setups is None else set(disabled_setups)
    report = _load_backtest_setup_performance()
    by_setup = getattr(report, "by_setup", {}) if report is not None else {}

    active_parts: list[str] = []
    paused_parts: list[str] = []
    for name, _cls, _horizon in _VERIFIED_SETUPS:
        stats = by_setup.get(name)
        part = f"{_setup_display_name(name)}{_format_backtest_stats(stats)}"
        if name in disabled:
            if name == "oversold_bounce":
                # 暂停理由 = 统计不显著 + 尾部更厚 (不是 crisis 分层; n=21 太小不可靠).
                # 默认只标 "默认暂停"; 完整理由 (CI 跨 0/尾部更厚) 进 --verbose.
                if explain:
                    n = getattr(stats, "n", 0) if stats is not None else 0
                    er = getattr(stats, "expected_return", None) if stats is not None else None
                    evidence_note = f" E={er:+.2%} (n={n}, CI 跨 0 不显著)" if er is not None and n > 0 else ""
                    part = f"{part} — 默认暂停: 实测{evidence_note}, 尾部亏损比 BTST 厚"
                else:
                    part = f"{part} — 默认暂停"
            paused_parts.append(part)
        else:
            active_parts.append(part)

    lines: list[str] = []
    if active_parts:
        lines.append(f"启用 setup: {', '.join(active_parts)}")
    if paused_parts:
        lines.append(f"暂停 setup: {', '.join(paused_parts)}")
    skipped = getattr(report, "skipped_exits", 0)
    if skipped:
        lines.append(f"  提示: {skipped} 条平仓记录缺 realized 标记, 已跳过 (不影响统计完整性)")
    return lines


def _setup_display_name(setup_name: str) -> str:
    """setup 英文标识 → 中文显示名 (保留英文代号便于与文档/日志对照).

    render 输出面向 operator 阅读, 纯英文 setup 名 (btst_breakout/oversold_bounce)
    不直观. 映射为"中文名(英文代号)"格式, 既好看又能与 known_distributions / journal
    里的英文键对上. 未知 setup 原样返回.
    """
    _NAMES = {
        "btst_breakout": "涨停突破",
        "oversold_bounce": "超跌反弹",
    }
    zh = _NAMES.get(str(setup_name or "").strip())
    return f"{zh}({setup_name})" if zh else setup_name


def _load_st_tickers() -> set[str]:
    """加载 ST/*ST 股票集合 (6位代码), 用于 full_market 扫描时过滤.

    --auto 的候选池在 Layer A 第一步就过滤 ST (candidate_pool_compute_pipeline_helpers.py:159),
    但 --daily-action 的 full_market 直扫 price_cache (不经候选池), 需独立过滤.
    ST 股超跌常见, OversoldBounce 容易误命中 (如 002217 ST合力泰).

    数据源: tushare stock_basic (name 含 ST). 失败时空集 (不阻塞).
    """
    from src.tools.tushare_api import get_tushare_token

    token = get_tushare_token()
    if not token:
        return set()
    try:
        import tushare as ts

        pro = ts.pro_api(token=token)
        basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
        st_codes: set[str] = set()
        for _, row in basic.iterrows():
            name = str(row.get("name", ""))
            if "ST" in name.upper():  # 含 ST, *ST
                st_codes.add(str(row["ts_code"])[:6])
        return st_codes
    except Exception:
        logger.warning("daily_action: failed to fetch ST tickers from tushare, ST filter offline", exc_info=True)
        return set()


def _compact_trade_date(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 8 and text.isdigit():
        return text
    try:
        return pd.to_datetime(text).strftime("%Y%m%d")
    except Exception:
        logger.warning("daily_action: _compact_trade_date failed for %r, returning empty", text, exc_info=True)
        return ""


def _load_regime_history() -> dict[str, str]:
    """读取 regime_history.json → {YYYYMMDD: regime_label} (缺失返回空 dict)."""
    regime_path = Path("data/reports/regime_history.json")
    if regime_path.exists():
        try:
            return {str(k): str(v) for k, v in json.loads(regime_path.read_text(encoding="utf-8")).items()}
        except Exception:
            logger.warning("daily_action: failed to parse %s, regime lookup disabled", regime_path, exc_info=True)
    return {}


def _regime_from_history(trade_date: str) -> str:
    """从 regime_history.json 查 regime 标签; 缺失/无记录 → 'normal'."""
    if not trade_date:
        return "normal"
    return _load_regime_history().get(trade_date, "normal")


def _resolve_trade_date_and_regime(*, wall_clock_guard: bool = True) -> tuple[str, str]:
    """从 price_cache + regime_history 确定 trade_date 和 regime.

    不依赖 --auto 报告 (报告的候选池是 score_b 排序, 与凸性 setup 脱节).
    trade_date = price_cache 最新有数据的交易日; regime = regime_history.json 的标签.

    17:00 guard: A 股资金流 ~17:00 才完成当日入库, 盘中 price_cache 可能已含当日
    收盘价但资金流/其它信号未就绪. 若 price_cache 最新日 > 规则计算的信号日 (未过
    17:00 取昨天), 回退到信号日, 避免用不完整的当日数据出信号. 这与 ``--auto`` 的
    ``_resolve_default_end_date`` 用同一套 17:00 规则 (``resolve_signal_date``),
    保证两个系统的信号日对齐, 不再触发 staleness 保护.
    """
    price_dir = Path("data/price_cache")
    regimes_by_date = _load_regime_history()

    # 从任意一个 price_cache CSV 取最新日期
    latest_date = ""
    for csv in price_dir.glob("*.csv"):
        try:
            df = pd.read_csv(csv, dtype={"date": str}, usecols=["date"])
            # Vectorized date normalization — per-row _compact_trade_date calls
            # pd.to_datetime individually (~0.1ms each), costing 1541 rows × 777
            # files = 88s. Vectorized pd.to_datetime processes the entire column
            # at once, giving ~100x speedup.
            raw_dates = df["date"].dropna().astype(str).str.strip()
            # Filter out empty strings early (they become NaN via to_datetime)
            raw_dates = raw_dates[raw_dates.str.len() > 0]
            if len(raw_dates) == 0:
                continue
            mask_compact = raw_dates.str.len().eq(8) & raw_dates.str.isdigit()
            compact_dates = raw_dates[mask_compact]
            non_compact = raw_dates[~mask_compact]
            if len(non_compact) > 0:
                # errors='coerce' turns unparseable dates into NaT → drop them
                converted = pd.to_datetime(non_compact, errors="coerce").dt.strftime("%Y%m%d")
                converted = converted.dropna()
                converted = converted[converted != ""]  # drop empty results
                compact_dates = pd.concat([compact_dates, converted])
            d = compact_dates.max() if len(compact_dates) > 0 else ""
            if d and str(d) > latest_date:
                latest_date = str(d)
        except Exception:
            continue
    if not latest_date:
        latest_date = datetime.now().strftime("%Y%m%d")

    # 17:00 guard: price_cache 最新日若领先于规则信号日 (如盘前已注入当日), 回退到信号日.
    # 用统一的 resolve_signal_session (spec 8.1) 计算规则信号日, 不再内联重复 17:00 逻辑;
    # 无权威日历时 (SignalSessionUnavailable) 保持 price_cache 最新日 (与旧的空 eligible 分支一致).
    if wall_clock_guard:
        now = _current_cn_datetime()
        try:
            rule_signal = resolve_signal_session(
                now_cn=now,
                open_sessions=_load_authoritative_session_dates(),
            )
        except SignalSessionUnavailable:
            rule_signal = None
        if rule_signal is not None:
            latest_date = min(latest_date, rule_signal.strftime("%Y%m%d"))

    regime = regimes_by_date.get(latest_date, "normal")
    return latest_date, regime


def _latest_auto_report_date() -> str:
    """返回最新 auto_screening 报告日期; 缺失/解析失败时返回空字符串."""
    try:
        from src.screening.consecutive_recommendation import resolve_report_dir
        from src.screening.data_quality_audit import _find_latest_report

        latest = _find_latest_report(resolve_report_dir())
        if latest is None:
            return ""
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
            date = str(payload.get("date", "") or "").replace("-", "")
            if len(date) == 8 and date.isdigit():
                return date
        except Exception:
            pass
        stem_date = latest.stem.replace("auto_screening_", "")[:8]
        return stem_date if stem_date.isdigit() else ""
    except Exception:
        return ""


def _load_auto_topn_tickers(trade_date: str) -> set[str]:
    """加载信号日 ``--auto`` 报告的 Top-N ticker 集合 (供双信号收敛标记).

    C-DUAL-SIGNAL-CONVERGENCE (20260710): empirical dogfood 发现 BTST 命中里,
    同日也在 ``--auto`` Top-N 的子集历史胜率更高 (76% vs 66%, n=34 vs 99,
    median +7.35% vs +5.67%; ⚠ n 小未达统计显著, 仅供 operator 参考).
    两个独立方法 (BTST 动量突破 + --auto 四策略评分) 同日收敛 = 更强信号.
    本 helper 读 ``auto_screening_{trade_date}.json`` 的 recommendations ticker.

    报告缺失/无信号日 → 空集合 (收敛标记降级为不显示, 不阻塞渲染).
    """
    if not trade_date:
        return set()
    try:
        from src.screening.consecutive_recommendation import resolve_report_dir

        path = resolve_report_dir() / f"auto_screening_{trade_date}.json"
        if not path.exists():
            return set()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {str(r.get("ticker", "")).split(".")[0] for r in payload.get("recommendations", []) if r.get("ticker")}
    except Exception:
        logger.debug("daily_action: --auto Top-N 加载失败, 收敛标记降级", exc_info=True)
        return set()


def _load_ticker_to_industry_from_snapshots(
    tickers: list[str],
    *,
    snapshot_dir: Path | str = Path("data/snapshots"),
) -> dict[str, str]:
    needed = set(tickers)
    if not needed:
        return {}

    result: dict[str, str] = {}
    snapshots = Path(snapshot_dir)
    for path in sorted(snapshots.glob("candidate_pool_*.json"), reverse=True):
        if needed.issubset(result):
            break
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = []
            for key in ("recommendations", "candidates", "candidate_pool", "selected_candidates", "shadow_candidates"):
                value = payload.get(key)
                if isinstance(value, list):
                    records.extend(value)
        else:
            records = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            ticker = str(rec.get("ticker") or rec.get("ts_code") or "")[:6]
            industry = str(rec.get("industry_sw") or rec.get("industry") or "").strip()
            if ticker in needed and industry and ticker not in result:
                result[ticker] = industry
    return result


def _load_industry_day_pct_by_ticker(trade_date: str, tickers: list[str]) -> dict[str, float]:
    """Load real SW L1 one-day pct change for the scan date, keyed by ticker."""

    if not tickers:
        return {}
    try:
        from scripts.setup_research import load_industry_day_pct

        ticker_to_industry = _load_ticker_to_industry_from_snapshots(tickers)
        industry_day_pct = load_industry_day_pct()
    except Exception as exc:  # noqa: BLE001 - missing context should degrade BTST, not crash daily action
        logger.warning("加载行业日涨幅失败, BTST 行业条件将降级 (degraded=True, 不再静默全杀): %s", exc)
        return {}

    result: dict[str, float] = {}
    for ticker, industry in ticker_to_industry.items():
        value = industry_day_pct.get((industry, trade_date))
        if value is not None:
            result[ticker] = float(value)
    return result


def _load_authoritative_session_dates() -> tuple[date, ...]:
    """Load explicit local open sessions (forward-inclusive); never fetch here.

    Prefers ``trade_calendar.json`` — the real A-share open-session calendar
    (including future sessions), refreshed by ``--auto`` via
    :func:`refresh_authoritative_trade_calendar`. This is what lets the service
    compute the next-day entry and the T+10 BTST horizon.

    Falls back to ``regime_history.json`` (a *historical* regime record that can
    never contain future sessions) only when the forward calendar is absent, so
    behaviour degrades gracefully instead of crashing. ``DAILY_ACTION_CALENDAR_PATH``
    overrides both. Reading stays local and deterministic at ``--daily-action``
    time.
    """
    configured = os.environ.get("DAILY_ACTION_CALENDAR_PATH", "").strip()
    if configured:
        path = Path(configured)
    else:
        forward = Path("data/reports/trade_calendar.json")
        path = forward if forward.exists() else Path("data/reports/regime_history.json")
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_dates = payload.keys() if isinstance(payload, dict) else payload
        sessions = []
        for raw in raw_dates:
            compact = _compact_trade_date(raw)
            if compact:
                sessions.append(datetime.strptime(compact, "%Y%m%d").date())
        return tuple(sorted(set(sessions)))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning("invalid local daily-action calendar: %s", path, exc_info=True)
        return ()


def refresh_authoritative_trade_calendar(
    reports_dir: Path | str | None = None,
    *,
    start: str = "20200101",
    forward_days: int = 90,
    fetch: Callable[[str, str], list[str]] | None = None,
) -> Path | None:
    """Fetch and persist a forward-inclusive A-share open-session calendar.

    ``regime_history.json`` is historical only, so ``--daily-action`` could not
    resolve the next-day entry or the T+10 horizon and returned
    ``calendar_unavailable`` with zero plans. This writes
    ``trade_calendar.json`` spanning ``start`` .. today+``forward_days`` using
    the authoritative exchange calendar (tushare ``trade_cal``), giving the
    deterministic daily-action loader real forward sessions.

    Never overwrites an existing calendar with an empty result (a provider
    failure must not blind the next run). Returns the written path, or ``None``
    when the authoritative source produced nothing.
    """
    if fetch is None:
        from src.tools.tushare_api import get_open_trade_dates as fetch

    reports = Path(reports_dir) if reports_dir is not None else Path("data/reports")
    end = (_current_cn_datetime().date() + timedelta(days=forward_days)).strftime("%Y%m%d")
    try:
        raw_sessions = fetch(start, end)
    except Exception:
        logger.warning("trade calendar fetch failed for %s-%s", start, end, exc_info=True)
        return None
    normalized = sorted(
        {_compact_trade_date(value) for value in (raw_sessions or []) if _compact_trade_date(value)}
    )
    if not normalized:
        # Fail closed: never clobber a previously-good calendar with nothing.
        return None
    # 前向覆盖下限: 日历年尾数据商未发布次年日历时, 截断的日历照常覆盖写会让
    # T+10 horizon 在次年静默失效 (calendar_unavailable 被误读为"今日无信号").
    # 前向覆盖不足 30 天时保留旧文件并告警.
    last_session = normalized[-1]
    from datetime import datetime as _dt_cls

    last_date = _dt_cls.strptime(last_session, "%Y%m%d").date()
    min_forward = _current_cn_datetime().date() + timedelta(days=30)
    if last_date < min_forward:
        logger.warning(
            "trade calendar forward coverage too short (%s < %s), keeping existing file",
            last_date,
            min_forward,
        )
        return None
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / "trade_calendar.json"
    atomic_write_json(target, normalized)
    return target


def _resolve_next_trade_date(
    trade_date: str, sessions: tuple[date, ...] | None = None
) -> str:
    """Resolve from local authoritative sessions, failing closed on missing coverage."""
    try:
        from src.paper_trading.btst_trade_calendar import TradingSessionCalendar

        signal = datetime.strptime(_compact_trade_date(trade_date), "%Y%m%d").date()
        calendar = TradingSessionCalendar(
            _load_authoritative_session_dates() if sessions is None else sessions
        )
        if not calendar.contains_session(signal):
            return ""
        return calendar.next_session(signal).strftime("%Y%m%d")
    except (TypeError, ValueError):
        return ""


def _coerce_today_yyyymmdd(today: date | str | None) -> str:
    """Normalize an injectable "today" to ``YYYYMMDD``.

    ``None`` falls back to the real wall clock — the production default.
    Tests pass an explicit value so calendar drift can never turn them red
    (R90 family: a test that depends on wall-clock-vs-fixture arithmetic
    silently goes red once the calendar crosses the fixture date).
    """

    if today is None:
        return datetime.now().strftime("%Y%m%d")
    if isinstance(today, datetime):
        return today.strftime("%Y%m%d")
    if isinstance(today, date):
        return today.strftime("%Y%m%d")
    return str(today).replace("-", "")


def _current_cn_datetime() -> datetime:
    """Current wall time in the A-share operating timezone."""
    return datetime.now(_CN_TZ)


def _normalize_now_to_cn(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now
    return now.astimezone(_CN_TZ)


def _missed_entry_window_reason(
    trade_date: str,
    *,
    now: datetime | None = None,
    sessions: tuple[date, ...] | None = None,
) -> str:
    """Return a blocking reason when the signal's next-open entry window has passed."""
    signal_date = str(trade_date or "").strip().replace("-", "")
    if len(signal_date) != 8 or not signal_date.isdigit():
        return ""

    next_trade_date = (
        _resolve_next_trade_date(signal_date)
        if sessions is None
        else _resolve_next_trade_date(signal_date, sessions)
    )
    if len(next_trade_date) != 8 or not next_trade_date.isdigit():
        return "calendar_unavailable: 本地权威交易日历缺少信号日或下一开市日覆盖"

    now_cn = _normalize_now_to_cn(now or _current_cn_datetime())
    now_date = now_cn.strftime("%Y%m%d")
    window_has_passed = now_date > next_trade_date or (now_date == next_trade_date and now_cn.time() >= _ENTRY_WINDOW_CUTOFF)
    if not window_has_passed:
        return ""

    cutoff_label = f"{_ENTRY_WINDOW_CUTOFF.hour:02d}:{_ENTRY_WINDOW_CUTOFF.minute:02d}"
    return f"信号日 {signal_date} 对应计划买入日 {next_trade_date} 开盘, " f"当前时间 {now_cn.strftime('%Y%m%d %H:%M')} 已过 {cutoff_label} 买入窗口已错过; " "为避免盘中追单或事后补单, 本次不输出新 BUY. " f"请在 {next_trade_date} 收盘数据完成后刷新缓存, 再生成下一交易日计划"


@dataclass
class DailyAction:
    """今日单只票的动作。"""

    ticker: str
    setup: str
    action: str  # "BUY" | "SKIP"
    kelly_pct: float
    entry_price: float
    soft_stop: float
    hard_stop: float
    time_exit: str
    invalidation_condition: str
    distribution_summary: str  # "n=5374 winrate=51% cv=1.53 E=+2.6%"
    reasoning: str
    # Bug B (2026-07-10): 命中基于残缺条件 (如资金流历史 < 5 日无法判均值) 时为 True.
    # 当前 fund_flow_cache 普遍浅, 绝大多数 BTST 命中是 degraded — 运行时检测口径
    # 比 known_distributions 的深历史回测更宽松 (少了资金流均值过滤), 必须向 operator 披露.
    degraded: bool = False
    degradation_reason: str = ""
    # trigger_strength: setup detect 产出的 0-1 触发强度 (星期+板块+区间位置+波动率压缩).
    # 决定同 setup 内候选的排序, render 需展示让排序可解释. 默认 0 兼容旧构造.
    trigger_strength: float = 0.0
    # block_reason: 候选被风控过滤的具体原因 (价格/强度/行业/敞口), render 展示让 operator 知道为何没买.
    # 空字符串 = 未被过滤 (已录入或未进过滤循环).
    block_reason: str = ""
    # metadata: setup detect 产出的结构化诊断 (fund flow / pre_runup / industry / 阈值等),
    # 供 live setup 输出记录器落盘, 为将来跨周期验证攒样本外数据. 默认空 dict.
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BlockedCandidate:
    ticker: str
    reason: str
    reference_price: float
    # setup / entry_price 别名: setup_output_log._record 按 legacy 字段名取数
    # (setup/block_reason/entry_price/trigger_strength), v2 迁移后 blocked 行曾
    # 全部退化为空壳. 默认空值兼容旧构造.
    setup: str = ""
    trigger_strength: float = 0.0
    # metadata: detect 诊断 (强度分量等), 供"触发强度不足"等阻断原因下钻到
    # 具体维度. compare=False: dict 不可哈希, 且诊断不影响候选身份.
    metadata: dict = field(default_factory=dict, compare=False)

    @property
    def block_reason(self) -> str:
        return self.reason

    @property
    def entry_price(self) -> float:
        return self.reference_price


@dataclass(frozen=True)
class ScanFunnel:
    """扫描漏斗计数 (snapshot 路径): 回答"为什么只有这几只候选".

    未命中票从来不是"候选", 只在计数里可见 — 漏斗把沉默的大多数变成数字.
    prefilter 阶段标签 "涨幅≥9.5%" 是全板块公共下限的宽松预筛: 20%/30% 板的
    大涨非涨停日也计入, detect 内部才按板块自适应阈值精确判定涨停.
    多 setup 同时启用时计数按 ticker×setup 评估次数计 (当前仅 btst 启用,
    评估次数 = 票数).
    """

    scannable: int
    prefilter_passed: int
    hits: int


@dataclass(frozen=True)
class DailyActionScan:
    signal_date: date
    candidates: tuple[PlanCandidate, ...]
    blocked_candidates: tuple[BlockedCandidate, ...]
    reference_prices: tuple[tuple[str, float], ...] = ()
    snapshot_id: str | None = None
    funnel: ScanFunnel | None = None


@dataclass(frozen=True)
class PlanDetail:
    """新计划的操作员可读详情 — 渲染层只格式化, 不再自行取数.

    由 complete_daily_action_v2 从 PlanCandidate (trigger_strength/metadata) +
    冻结先验分布 + 交易日历 (T+N 到期日) 一次性组装. 止盈止损口径 = 策略真实
    合约: 默认退出只有 T+N 时间退出; 止损价仅披露参考 (止损×gate 联合网格证
    fixed8 止损 4/4 组合降收益 → 止损执行不落地, gate 替代止损), 无止盈规则
    (凸性策略让利润奔跑到期). 见 data/reports/regime_gate_decision_pack_2026-08-09.md.
    """

    ticker: str
    setup: str
    horizon: int
    trigger_strength: float
    expected_exit_date: date | None
    distribution: Distribution | None
    # compare=False: dict 不可哈希, 且诊断不影响详情身份 (与 PlanCandidate 同例).
    metadata: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class DailyActionV2Run:
    service_run: Any
    plans: tuple[Any, ...]
    open_positions: tuple[Any, ...]
    blocked_candidates: tuple[BlockedCandidate, ...]
    reference_prices: tuple[tuple[str, float], ...]
    # plan_details: 新计划区的完整交易计划 (买入/理由/先验/退出). 可选 —
    # DailyActionService.render 等旧构造点不传, 渲染退化为单行格式.
    plan_details: tuple[PlanDetail, ...] = ()
    # funnel: 扫描漏斗计数 (snapshot 路径产出); None 时渲染省略漏斗行.
    funnel: ScanFunnel | None = None


_BLOCK_REASON_ZH = {
    "daily_action_readiness_missing": "就绪清单缺失",
    "readiness_snapshot_load_failed": "就绪快照加载失败",
    "readiness_manifest_invalid": "就绪清单无效",
    "readiness_schema_unsupported": "就绪清单版本不支持",
    "readiness_date_mismatch": "就绪清单日期不匹配",
    "readiness_manifest_not_healthy": "就绪清单不健康",
    "readiness_identity_mismatch": "就绪身份不匹配",
    "snapshot_fingerprint_mismatch": "快照指纹不匹配",
    "readiness_scan_failed": "就绪快照扫描失败",
    "calendar_unavailable": "交易日历不可用",
    "incomplete_setup_data": "setup 数据不完整",
    "setup_disabled_by_default": "setup 默认暂停",
    "setup_not_ledger_enabled": "setup 未在台账启用",
    "drawdown_circuit_breaker": "组合回撤熔断",
    "entry_window_missed": "入场窗口已过（当前已过入场日 09:30，新计划将按不可执行的开盘价记账）",
    "detector_degraded": "检测器降级",
    "regime_gate_halt": "regime 闸（危机/避险日不开新仓）",
    "regime_authorization_evidence_unavailable": "regime 加仓证据暂不可验，按 10% 单票上限披露",
    "trigger_strength_below_threshold": "触发强度不足",
    "stale_price_cache": "价格缓存过期",
    "candidate_not_plan_eligible": "候选不具备计划资格",
    "entry_price_below_minimum": "入场价低于最低门槛",
    # auto_pipeline 的就绪发布未达 healthy 时, --auto 报告 payload 携带此码
    # (canonical manifest 缺位, 只有降级 attempt 记录) — 8/14 实证它曾以原始
    # snake_case 漏到 --auto 摘要, 操作员无法读.
    "readiness_attempt": "就绪清单未发布，仅有降级尝试记录",
}


def _block_reason_zh(reason: str | None, *, verbose: bool = False) -> str:
    if not reason:
        return "未知数据护栏"
    # 运行级阻断码与 manifest 门控码共用一张渲染词汇表 (与 _run_block_reason_zh
    # 同序): 门控码偶会经 global_reason 通道到达运行级渲染, 缺表时不能只回退
    # "数据护栏未通过" 这种无信息泛化文案.
    label = _BLOCK_REASON_ZH.get(str(reason)) or _DEBUG_GATE_REASON_ZH.get(str(reason), "数据护栏未通过")
    return f"{label}（{reason}）" if verbose else label


def _format_drawdown(drawdown: float) -> str:
    """回撤显示: 0 (含 -0.0) 时不带符号, 避免 '+0.0%' 误导; 否则带 +/- 符号."""
    formatted = f"{drawdown:+.1%}"
    return "0.0%" if formatted in ("+0.0%", "-0.0%") else formatted


def _disp_width(text: str) -> int:
    """CJK 感知的显示宽度: 东亚宽/全角字符计 2, 其余计 1.

    终端对齐需要按显示宽度而非字符数 — 否则「亨通光电」与「阿莱德」在
    len() 下只差 1, 在屏幕上却差 2 列, 列就永远对不齐.
    """
    import unicodedata

    return sum(
        2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text
    )


def _pad_to(text: str, width: int) -> str:
    """把 text 右补空格到指定显示宽度, 供多行同列对齐."""
    return text + " " * max(0, width - _disp_width(text))


def _render_section(title: str, rows: Sequence[str]) -> list[str]:
    """输出一节: 标题 + 缩进行; 无行时显式输出「无」.

    空节用「无」而非整节省略 — 操作员因此能区分「今天没有这类事件」与
    「这次运行没产出这类事件」两种状态, 避免把静默当成健康.
    """
    lines = [title]
    if rows:
        lines.extend(f"  {row}" for row in rows)
    else:
        lines.append("  无")
    return lines


def _weekday_zh(d: date) -> str:
    return "一二三四五六日"[d.weekday()]


# 强度分量 metadata key → 中文标签 (与 btst_breakout detect 的 strength 公式同序).
_STRENGTH_COMPONENT_LABELS = (
    ("board_score", "板块"),
    ("low_vol_score", "低波"),
    ("squeeze_score", "压缩"),
    ("volume_score", "量能"),
    ("range_score", "振幅"),
)


def _finite_float(value: Any) -> float | None:
    """metadata 取值守卫: 非数值/NaN/inf 一律视为缺失 (该段省略, 不编造)."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _format_plan_detail_rows(
    detail: PlanDetail,
    *,
    reference_price: float | None,
    planned_entry_date: date | None,
    converge: bool,
) -> list[str]:
    """新计划的完整交易计划块: 买入价位口径 / 买入理由 / 先验胜率赔率 / 退出合约.

    行首带 2 空格 — _render_section 统一再缩进 2, 渲染后共 4 列, 从属于上方
    计划首行. 逐票字段 (涨停结构/失效参考价) 来自 detect metadata, 缺失即整段
    省略, 绝不编造; setup 级冻结先验与 T+N 退出合约不依赖逐票数据, 始终展示.
    """
    md = detail.metadata or {}
    rows: list[str] = []

    # 买入价位: 策略的真实执行口径 = 入场日开盘价 (参考价只是信号日收盘);
    # 开盘涨停/停牌由 classify_open_fill fail-closed 自动跳过该计划.
    if planned_entry_date is not None:
        buy_row = f"  买入：{planned_entry_date.month}/{planned_entry_date.day}（周{_weekday_zh(planned_entry_date)}）开盘价执行"
        if reference_price:
            buy_row += f"（参考价 ~{reference_price:.2f} 为信号日收盘，非挂单价）"
        buy_row += "；开盘涨停/停牌自动放弃"
        rows.append(buy_row)

    # 买入理由: 强度 (候选排序与仓位的真实依据) + 5 分量 + 能量耦合 bonus.
    reason = f"  理由：强度 {detail.trigger_strength:.2f}"
    components = [
        f"{label} {score:.2f}"
        for key, label in _STRENGTH_COMPONENT_LABELS
        if (score := _finite_float(md.get(key))) is not None
    ]
    energy_bonus = _finite_float(md.get("energy_bonus"))
    if components:
        reason += f"（{' · '.join(components)}"
        if energy_bonus:
            reason += f" + 能量耦合 {energy_bonus:.2f}"
        reason += "）"
    if converge:
        reason += "  ⭐双信号"
    rows.append(reason)

    # 涨停结构 (逐票): 幅度/连板/涨停前 5 日/主力净流入/行业当日, 缺哪段省哪段.
    structure: list[str] = []
    pct = _finite_float(md.get("pct_change"))
    if pct is not None:
        streak_raw = _finite_float(md.get("limit_up_streak"))
        streak = int(streak_raw) if streak_raw is not None else 1
        streak_label = "首板" if streak <= 1 else f"{streak} 连板"
        structure.append(f"涨停 {pct:+.1f}%（{streak_label}）")
    pre_runup = _finite_float(md.get("pre_5d_runup_pct"))
    if pre_runup is not None:
        structure.append(f"涨停前 5 日 {pre_runup:+.1f}%")
    inflow = _finite_float(md.get("main_net_inflow"))
    if inflow is not None:
        structure.append(f"主力{'净流入' if inflow >= 0 else '净流出'} {abs(inflow) / 1e8:.1f} 亿")
    industry_pct = _finite_float(md.get("industry_pct"))
    if industry_pct is not None:
        structure.append(f"行业当日 {industry_pct:+.1f}%")
    if structure:
        rows.append(f"  {' · '.join(structure)}")

    # 先验胜率赔率: 冻结分布 (驱动仓位的那套数字 — 展示口径 = 决策口径).
    dist = detail.distribution
    if dist is not None:
        payoff = dist.avg_gain / abs(dist.avg_loss) if dist.avg_loss else None
        payoff_text = f" · 盈亏比 {payoff:.1f}（盈 {dist.avg_gain:+.1%} / 亏 {dist.avg_loss:+.1%}）" if payoff else ""
        rows.append(
            f"  先验（T+{detail.horizon} 全池回测 n={dist.n}）：胜率 {dist.winrate:.0%}"
            f"{payoff_text} · 期望 {dist.expected_return:+.1%}"
            f"（95% CI {dist.ci_low:+.1%}~{dist.ci_high:+.1%}）"
        )

    # 退出合约: 默认退出只有 T+N 时间退出 (到期无条件卖出), 无止盈规则
    # (凸性策略让利润奔跑到期).
    if detail.expected_exit_date is not None:
        exit_label = f"预计 {detail.expected_exit_date.month}/{detail.expected_exit_date.day}（周{_weekday_zh(detail.expected_exit_date)}）到期"
    else:
        exit_label = f"第 {detail.horizon} 个持有交易日到期"
    rows.append(f"  退出：T+{detail.horizon} 时间退出（{exit_label}，无条件卖出）— 本策略默认退出")

    # 失效参考价: 仅披露参考 — 止损×gate 联合网格证 fixed8 止损 4/4 组合降收益,
    # paper P&L 不按止损出场; 供人工跟单自行参考. 盘整区底部过远时 detect 会用
    # 兜底 pct 截断 (stop_price > range_low), 此时明示"兜底"以免把止损线误读成
    # 真实底部 (真实例: 600487 20260814 底部 45.60 vs 兜底线 57.94).
    range_low = _finite_float(md.get("range_low"))
    range_stop_pct = _finite_float(md.get("range_based_stop_pct"))
    if range_low is not None and range_stop_pct is not None and reference_price:
        stop_price = reference_price * (1 + range_stop_pct)
        if range_low < stop_price - 0.01:
            anchor = f"{range_stop_pct:+.1%} 兜底，真实盘整区底部 {range_low:.2f} 过远"
        else:
            anchor = f"盘整区底部 {range_low:.2f}，{range_stop_pct:+.1%}"
        rows.append(
            f"  失效参考：跌破 {stop_price:.2f}（{anchor}）"
            f"— 仅披露参考，回测证明不执行止损更优"
        )
    return rows


# ---------------------------------------------------------------------------
# 诊断明细 (--verbose) 翻译层
# 每行 = 对象 + 中文含义 + [原始审计码附录]. 原始码是日志/事件 payload 的
# 对照键, 必须在附录中原样保留 (key=value); 未知码 fail-closed 回退为原文
# 显示 (不崩溃、不吞信息) — 新增枚举值无需同步改这里也能安全渲染.
# ---------------------------------------------------------------------------

# ActionItem.reason (入场/退出/生命周期) + 影子退出评估 reason, 按业务含义措辞.
_DEBUG_REASON_ZH = {
    # 计划/入场
    "entry_planned": "新计划已登记",
    "entry_filled": "计划已按开盘价成交",
    "entry_expired": "计划已过入场日未成交，自动作废",
    "entry_not_due": "未到入场日，计划继续等待",
    "entry_queue_unknown": "入场日开盘队列状态未知，按计划未成交处理",
    "entry_unexecutable": "入场日开盘不可成交（涨停/停牌等），计划跳过",
    "entry_calendar_unavailable": "交易日历不可用，计划无法结算",
    "cost_version_mismatch": "执行成本版本与登记时不一致，计划跳过",
    "higher_priority_pending": "有更高优先级计划未结算，本计划等待",
    "portfolio_capacity": "组合敞口达上限，计划跳过",
    "ticker_capacity": "单票仓位达上限，计划跳过",
    "lot_floor_zero_shares": "目标金额不足一手（100 股），计划跳过",
    "cash_capacity": "现金不足，计划跳过",
    # 退出
    "maximum_holding_session": "持有期届满，计划到期开盘退出",
    "pending_exit": "已标记退出，等待强制退出日结算",
    "exit_filled": "已按开盘价完成退出",
    "unexecutable_proxy": "当日不可成交（停牌/跌停），退出延期",
    "unknown_queue": "当日成交状态未知，退出延期",
    "forced_realization_stale": "延期超上限，按最后可得价强制了结",
    # 影子退出评估
    "hold": "未触发退出条件",
    "close_below_trailing_line": "收盘跌破移动退出线",
    "insufficient_data": "数据不足，无法评估",
}

_DEBUG_EXECUTION_ZH = {
    "pending": "待成交",
    "paper": "模拟执行",
    "broker_confirmed": "券商确认执行",
}

_DEBUG_SOURCE_ZH = {
    "pending": "待成交",
    "synthetic_open": "模拟开盘成交",
    "manual_confirmation": "人工确认成交",
    "broker_import": "券商导入成交",
}

# manifest/快照门控拦截码 (service 层 _snapshot_eligible_candidates /
# _manifest_eligible_candidates 产出). fingerprint_mismatch:* 等内嵌动态值的
# 码不在此表 — 回退原文, 附录本就保留完整内容.
_DEBUG_GATE_REASON_ZH = {
    "candidate_date_mismatch": "候选信号日与快照不一致",
    "candidate_snapshot_mismatch": "候选快照身份不匹配",
    "candidate_setup_mismatch": "候选 setup 与快照不一致",
    "candidate_not_plan_eligible": "候选不具备计划资格",
    "candidate_consumed_fingerprint_mismatch": "候选输入指纹与快照不匹配",
    "snapshot_date_mismatch": "快照日期与信号日不一致",
    "snapshot_identity_missing": "快照身份缺失",
    "healthy_manifest_missing": "健康就绪清单缺失",
    "manifest_identity_mismatch": "就绪清单身份不匹配",
    "manifest_invalid": "就绪清单无效",
    "manifest_ticker_absent": "就绪清单缺该票",
    "manifest_ticker_identity_mismatch": "清单内票据身份不匹配",
    "manifest_ticker_date_mismatch": "清单内票据日期不匹配",
    "readiness_not_trade_ready": "就绪状态不可交易",
    "manifest_fingerprint_missing": "清单指纹缺失",
    "current_fingerprint_missing": "当前缓存指纹缺失",
}


def _run_block_reason_zh(code: str) -> str:
    """运行级阻断码 → 中文: 先查渲染层阻断表, 再查门控表, 都没有回退原文."""
    return _BLOCK_REASON_ZH.get(code) or _DEBUG_GATE_REASON_ZH.get(code) or code


def _format_strength_breakdown(metadata: dict) -> str:
    """强度不足候选的分量下钻行: 5 个等权分量 (满分各 0.20) + 短板定位.

    回答"哪些因素导致强度不足" — 短板 = 得分最低的分量 (同分并列全列).
    metadata 缺分量时返回空串 (调用方整行省略, 不编造).
    """
    md = metadata or {}
    components = [
        (label, score)
        for key, label in _STRENGTH_COMPONENT_LABELS
        if (score := _finite_float(md.get(key))) is not None
    ]
    if not components:
        return ""
    text = "  强度分量：" + " · ".join(f"{label} {score:.2f}" for label, score in components)
    energy_bonus = _finite_float(md.get("energy_bonus"))
    if energy_bonus:
        text += f" + 能量耦合 {energy_bonus:.2f}"
    floor = min(score for _label, score in components)
    laggards = [f"{label} {score:.2f}" for label, score in components if score == floor]
    return f"{text} — 短板：{'、'.join(laggards)}"


def _debug_action_item_line(item: ActionItem) -> str:
    """诊断行: ticker + 中文含义 + 状态 + [原始审计码附录].

    execution/source 相同 (如 pending/pending) 时状态只显示一次, 不重复堆砌.
    """
    reason_zh = _DEBUG_REASON_ZH.get(item.reason, item.reason)
    if item.reason == "entry_planned" and item.planned_entry_date is not None:
        d = item.planned_entry_date
        reason_zh = f"新计划已登记，等待 {d.month}/{d.day}（周{_weekday_zh(d)}）开盘成交"
    execution_zh = _DEBUG_EXECUTION_ZH.get(item.execution_label, item.execution_label)
    source_zh = _DEBUG_SOURCE_ZH.get(item.source_label, item.source_label)
    state_zh = source_zh if source_zh == execution_zh else f"{execution_zh} · {source_zh}"
    return (
        f"{item.ticker}  {reason_zh}；当前{state_zh}  "
        f"[reason={item.reason} execution={item.execution_label} source={item.source_label}]"
    )


def _debug_shadow_line(trade: Any) -> str:
    """影子退出诊断行: 退出线数值 + 中文信号含义 + [原始审计码附录]."""
    line = (
        f"{trade.shadow_exit_line:.2f}"
        if trade.shadow_exit_line is not None
        else "unavailable"
    )
    would_exit = bool(trade.shadow_would_exit_next_open)
    decision_zh = "次日开盘退出" if would_exit else "继续持有"
    reason_text = str(trade.shadow_reason)
    reason_zh = _DEBUG_REASON_ZH.get(reason_text, reason_text)
    return (
        f"{trade.ticker}  影子退出线 {line} · 影子信号：{decision_zh}（{reason_zh}）  "
        f"[shadow_exit_line={line} shadow_would_exit_next_open={str(would_exit).lower()} shadow_reason={reason_text}]"
    )


# 股票标签列的对齐宽度 (显示宽): "600487 亨通光电"=15, 4 字名极限=15, 取 16 留 1 空格余量.
_LABEL_WIDTH = 16


def render_no_signal(filled_count: int = 0) -> str:
    """无新信号结论; 若当日已执行昨日计划 (填仓), 如实披露避免误导."""
    if filled_count:
        return (
            f"结论：ℹ️ 系统健康，今日无新信号（已执行 {filled_count} 笔昨日计划）\n"
            "影响：无新的次日买入计划；已有持仓生命周期仍正常处理"
        )
    return "结论：ℹ️ 系统健康，今日无信号\n影响：无新的次日买入计划；已有持仓生命周期仍正常处理"


def render_degraded_only(count: int | None = None) -> str:
    suffix = f"（{count} 个）" if count is not None else ""
    return f"结论：ℹ️ 仅供诊断的残缺 setup{suffix}，未生成可交易计划\n影响：残缺/降级命中不进入 BUY 计划，仅用于样本外诊断"


def render_readiness_block(
    reason: str | None = None,
    *,
    verbose: bool = False,
    attempt_reasons: tuple[str, ...] = (),
) -> str:
    detail = _block_reason_zh(reason, verbose=verbose)
    lines = [
        "结论：⛔ 数据护栏阻断新计划",
        f"原因：{detail}",
        "影响：新候选无法进入计划，但已有持仓的估值和退出仍正常执行",
    ]
    if attempt_reasons:
        # 就绪清单缺失时, 上一次 --auto 留下的 attempt 记录了发布失败的真实原因.
        # 仅提示"重跑 --auto"在系统性失败时无解, 必须让 operator 看到根因.
        lines.append(
            f"诊断：最近一次 --auto 发布就绪清单失败（{'; '.join(attempt_reasons)}），请先排查该原因再重跑"
        )
    lines.append(
        "建议：收盘后运行 uv run python src/main.py --auto 刷新缓存和就绪清单，再运行 --daily-action 获取次日信号"
    )
    return "\n".join(lines)


class _ScannerCompatibilityState:
    """In-memory seam for reusing legacy detection without legacy state I/O."""

    def __init__(self) -> None:
        self.last_action_stale_reason = ""
        self.last_action_trade_date = ""
        self.last_action_regime = "normal"
        self.last_blocked_candidates: list[DailyAction] = []
        self.last_scanner_blocks: list[BlockedCandidate] = []
        self.last_portfolio_exposure = 0.0
        self.state = type("ScannerPortfolio", (), {"open_exposure": 0.0})()

    def close_matured(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    def drawdown_action(self) -> str:
        return "normal"

    def open_positions_detail(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    def record_skip(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _price_frame_is_fresh(prices: pd.DataFrame, signal_date: str) -> bool:
    """Require an exact terminal bar for the authoritative signal session."""
    return bool(
        len(prices)
        and _compact_trade_date(prices.iloc[-1].get("date", "")) == signal_date
    )


def run_daily_action_v2(
    service: Any,
    scan: DailyActionScan,
    manifest: Any = None,
    *,
    verified_snapshot: VerifiedDailyActionSnapshot | None = None,
) -> DailyActionV2Run:
    """Route pure scanner output through the auditable v2 lifecycle service."""
    context = service.advance_lifecycle(scan.signal_date)
    return complete_daily_action_v2(
        service,
        context,
        scan,
        manifest=manifest,
        verified_snapshot=verified_snapshot,
    )


def _build_plan_details(
    service: Any,
    scan: DailyActionScan,
    plans: tuple[ActionItem, ...],
) -> tuple[PlanDetail, ...]:
    """把展示用 PlanDetail 接到已持久化的计划上 (按 ticker join scan.candidates).

    退出日用 service.calendar 的 nth_holding_session 计算 — 与 _evaluate_open_positions
    的真实退出结算同一口径 (entry = 第 1 个持有交易日, 第 N 个持有交易日到期).
    日历覆盖不足时 expected_exit_date=None, 渲染降级为"第 N 个持有交易日到期".
    """
    candidates_by_ticker = {candidate.ticker: candidate for candidate in scan.candidates}
    details: list[PlanDetail] = []
    for plan in plans:
        candidate = candidates_by_ticker.get(plan.ticker)
        if candidate is None:
            continue
        horizon = SETUP_HOLDING_SESSIONS.get(candidate.setup)
        if horizon is None:
            continue  # 无持有期契约的 setup 不给详情 (不臆造退出日)
        exit_date: date | None = None
        if plan.planned_entry_date is not None:
            try:
                exit_date = service.calendar.nth_holding_session(
                    plan.planned_entry_date, horizon
                )
            except (TypeError, ValueError):
                exit_date = None
        details.append(
            PlanDetail(
                ticker=plan.ticker,
                setup=candidate.setup,
                horizon=horizon,
                trigger_strength=float(candidate.trigger_strength),
                expected_exit_date=exit_date,
                distribution=get_known_distribution(candidate.setup, horizon),
                metadata=dict(candidate.metadata or {}),
            )
        )
    return tuple(details)


def complete_daily_action_v2(
    service: Any,
    context: Any,
    scan: DailyActionScan,
    manifest: Any = None,
    *,
    verified_snapshot: VerifiedDailyActionSnapshot | None = None,
    new_entry_block: str | None = None,
    shadow_prices: Any | None = None,
) -> DailyActionV2Run:
    """Build the v2 display view after lifecycle has already advanced."""
    if not all(isinstance(candidate, PlanCandidate) for candidate in scan.candidates):
        raise TypeError("DailyActionScan candidates must be PlanCandidate instances")
    service_run = service.complete_run(
        context,
        snapshot=verified_snapshot,
        candidates=scan.candidates,
        new_entry_block=new_entry_block,
        manifest=manifest,
        shadow_prices=shadow_prices,
    )
    # Idempotent reruns still display the one persisted plan for this signal date.
    displayed_tickers = {candidate.ticker for candidate in scan.candidates}
    persisted = tuple(
        ActionItem(
            plan.trade_id,
            plan.ticker,
            "entry_planned",
            "pending",
            "pending",
            planned_entry_date=plan.planned_entry_date,
            planned_weight=plan.planned_weight,
        )
        for plan in service.repository.planned_trades()
        if plan.signal_date == scan.signal_date and plan.ticker in displayed_tickers
    )
    return DailyActionV2Run(
        service_run,
        persisted,
        service_run.open_positions,
        scan.blocked_candidates,
        scan.reference_prices,
        plan_details=_build_plan_details(service, scan, persisted),
        funnel=scan.funnel,
    )


def render_daily_action_v2(run: DailyActionV2Run, *, verbose: bool = False) -> str:
    """Render the daily operator view — one track regardless of ``verbose``.

    正文永远是可读的中文业务视图: 一行「今日摘要」结论先行, 后接新计划 /
    当日成交 / 持仓退出建议 / 不可计划候选 / 生命周期事件 / 台账, 每个集合
    用统一 ``_render_section`` 渲染, 空集合显式输出「无」. 新计划区在
    ``plan_details`` 非空时每只计划附完整交易计划块 (买入价位口径 / 买入理由
    / 先验胜率赔率 / T+N 退出合约 + 失效参考价仅披露). ``verbose`` 不再
    改变正文形态, 只在末尾追加「诊断明细」区: 每行 = 对象 + 中文含义 +
    [原始审计码附录] (``reason=/execution=/source=``、``shadow_*``、
    ``block_reason(s)=``、``manifest_*`` 的 key=value 原样保留供日志对照) —
    正文与审计是两个层, 不互相污染.
    """
    from src.screening.offensive.trade_lifecycle import FillSource
    from src.tools.tushare_api import get_stock_name

    def _label(ticker: str) -> str:
        # 与 v1 render_daily_action 同款: 查不到名就退回纯代码.
        name = get_stock_name(ticker)
        return f"{ticker} {name}" if name and name != ticker else ticker

    as_of = run.service_run.trade_date
    references = dict(run.reference_prices)
    debug: list[str] = []

    # 当日成交: 只列 signal 日当天结算的 fills — 数日前入场的仓位不误标为当日开仓.
    synthetic_trades = [
        t
        for t in run.open_positions
        if t.fill_source is FillSource.SYNTHETIC_OPEN and t.entry_date == as_of
    ]
    confirmed_trades = [
        t
        for t in run.open_positions
        if t.fill_source in {FillSource.MANUAL_CONFIRMATION, FillSource.BROKER_IMPORT}
        and t.entry_date == as_of
    ]

    # ---- 摘要行: 结论先行 ----
    # 数据护栏阻断 (block_reasons) 的完整结论由 dispatcher 的 render_readiness_block
    # 在渲染后追加 (原因/影响/建议); 摘要若再输出「⛔ + 原因」会与结论重复, 所以
    # 摘要只服务正常扫描的事件概览 (只列非零事件, 全零退化为「今日无新计划」),
    # block 场景整段让位给 dispatcher 结论.
    summary = None
    if not run.service_run.block_reasons:
        parts: list[str] = []
        if run.plans:
            parts.append(f"新计划 {len(run.plans)} 只")
        if synthetic_trades or confirmed_trades:
            parts.append(f"当日成交 {len(synthetic_trades) + len(confirmed_trades)} 笔")
        if run.service_run.exit_plans:
            parts.append(f"退出计划 {len(run.service_run.exit_plans)} 只")
        if run.service_run.completed_exits:
            parts.append(f"完成退出 {len(run.service_run.completed_exits)} 只")
        if run.blocked_candidates:
            parts.append(f"不可计划 {len(run.blocked_candidates)} 只")
        summary = " · ".join(parts) or "今日无新计划"

    lines = [f"━━━ 每日动作 · 信号日 {as_of.isoformat()}（周{_weekday_zh(as_of)}）━━━", ""]
    if summary is not None:
        lines.append(f"今日摘要：{summary}")
        lines.append("")

    # ---- 新计划 ----
    # plan_details 非空时, 每只计划首行下接完整交易计划块 (买入/理由/先验/退出);
    # 旧构造点 (DailyActionService.render 等) 不传 details, 保持单行格式.
    plan_rows: list[str] = []
    details_by_ticker = {detail.ticker: detail for detail in run.plan_details}
    auto_topn = (
        _load_auto_topn_tickers(as_of.strftime("%Y%m%d")) if details_by_ticker else set()
    )
    converge_shown = False
    for plan in run.plans:
        entry = ""
        if plan.planned_entry_date is not None:
            entry = (
                f"计划 {plan.planned_entry_date.month}/{plan.planned_entry_date.day}"
                f"（周{_weekday_zh(plan.planned_entry_date)}）入场"
            )
        weight = ""
        if plan.planned_weight is not None:
            weight = f"权重 {plan.planned_weight:.1%}"
        ref = references.get(plan.ticker)
        ref_text = f"参考价 ~{ref:.2f}" if ref else "参考价缺失"
        plan_rows.append(
            "  ".join(
                part
                for part in (
                    _pad_to(_label(plan.ticker), _LABEL_WIDTH),
                    ref_text,
                    entry,
                    weight,
                )
                if part
            )
        )
        detail = details_by_ticker.get(plan.ticker)
        if detail is not None:
            converge = plan.ticker.split(".")[0] in auto_topn
            converge_shown = converge_shown or converge
            plan_rows.extend(
                _format_plan_detail_rows(
                    detail,
                    reference_price=references.get(plan.ticker),
                    planned_entry_date=plan.planned_entry_date,
                    converge=converge,
                )
            )
        if verbose:
            debug.append(_debug_action_item_line(plan))
    if converge_shown:
        plan_rows.append(
            "  ⭐双信号 = 同日也在 --auto Top-N（收敛子集历史胜率更高，"
            "但 bootstrap CI[-7%,+28%] 跨 0 未达显著，勿据此加仓）"
        )
    lines.extend(_render_section(f"新计划（{len(run.plans)} 只）", plan_rows))
    lines.append("")

    # ---- 当日成交 ----
    # raw_entry_price 类型是 Optional — 正常成交行恒有价, 但一行坏数据不该崩掉
    # 整个操作员视图: 缺价显式标注, 不编造也不抛 TypeError.
    def _fill_row(t: Any) -> str:
        price_text = f"@{t.raw_entry_price:.2f}" if t.raw_entry_price is not None else "成交价缺失"
        return f"{_pad_to(_label(t.ticker), _LABEL_WIDTH)} {price_text}"

    fill_rows: list[str] = []
    if synthetic_trades:
        fill_rows.append(f"模拟成交：{len(synthetic_trades)} 笔")
        fill_rows.extend(_fill_row(t) for t in synthetic_trades)
    else:
        fill_rows.append("模拟成交：无")
    if confirmed_trades:
        fill_rows.append(f"确认成交：{len(confirmed_trades)} 笔")
        fill_rows.extend(_fill_row(t) for t in confirmed_trades)
    else:
        fill_rows.append("确认成交：无")
    lines.extend(_render_section("当日成交", fill_rows))
    lines.append("")

    # ---- 持仓退出建议（影子, 不触发真实交易）----
    shadow_rows: list[str] = []
    for trade in run.open_positions:
        label = _pad_to(_label(trade.ticker), _LABEL_WIDTH)
        advice = "建议次日退出" if trade.shadow_would_exit_next_open else "维持持有"
        shadow_rows.append(f"{label} 影子建议：{advice}")
        if verbose:
            debug.append(_debug_shadow_line(trade))
    lines.extend(_render_section("持仓退出建议（影子，不改变默认退出）", shadow_rows))
    lines.append("")

    # ---- 不可计划候选 ----
    # 强度不足的候选附分量下钻行 (哪个维度拖累了强度); 其他原因中文表已够
    # 清楚, 保持单行. 节后的扫描漏斗行回答"为什么只有这几只".
    blocked_rows: list[str] = []
    for candidate in run.blocked_candidates:
        label = _pad_to(_label(candidate.ticker), _LABEL_WIDTH)
        if candidate.reason == "trigger_strength_below_threshold":
            gap = max(0.0, _MIN_TRIGGER_STRENGTH - candidate.trigger_strength)
            reason_text = (
                f"触发强度不足（{candidate.trigger_strength:.2f} < "
                f"{_MIN_TRIGGER_STRENGTH:.2f} 阈值，差 {gap:.2f}）"
            )
        else:
            reason_text = _block_reason_zh(candidate.reason)
        blocked_rows.append(
            f"{label} 参考价 ~{candidate.reference_price:.2f}  原因：{reason_text}"
        )
        if candidate.reason == "trigger_strength_below_threshold":
            breakdown = _format_strength_breakdown(candidate.metadata)
            if breakdown:
                blocked_rows.append(breakdown)
        if verbose:
            debug.append(
                f"{candidate.ticker}  不可计划：{_block_reason_zh(candidate.reason)}  "
                f"[block_reason={candidate.reason}]"
            )
    lines.extend(
        _render_section(f"不可计划候选（{len(run.blocked_candidates)} 只）", blocked_rows)
    )
    lines.append("")

    # ---- 扫描漏斗: 未命中票从来不是候选, 漏斗把沉默的大多数变成数字 ----
    if run.funnel is not None:
        lines.append(
            f"扫描漏斗：扫描 {run.funnel.scannable} 只 → 涨幅≥9.5% {run.funnel.prefilter_passed} 只 → "
            f"命中 {run.funnel.hits} 只 → 可计划 {len(run.plans)} 只 · 不可计划 {len(run.blocked_candidates)} 只"
        )
        lines.append("")

    # ---- 生命周期事件 ----
    lifecycle_sections = (
        ("跳过计划", run.service_run.skipped_plans),
        ("退出计划", run.service_run.exit_plans),
        ("延迟退出", run.service_run.deferred_exits),
        ("完成退出", run.service_run.completed_exits),
    )
    for title, items in lifecycle_sections:
        if not items:
            continue
        rows: list[str] = []
        for item in items:
            rows.append(_pad_to(_label(item.ticker), _LABEL_WIDTH))
            if verbose:
                debug.append(_debug_action_item_line(item))
        lines.extend(_render_section(f"{title}（{len(items)}）", rows))
        lines.append("")

    # ---- 台账 ----
    valuation = run.service_run.valuation
    stale = f" 数据过期 {len(valuation.stale_tickers)} 只" if valuation.stale_tickers else ""
    lines.append(
        f"台账：净值 {valuation.nav:,.0f} · 峰值 {valuation.peak:,.0f} · "
        f"回撤 {_format_drawdown(valuation.drawdown)}{stale}"
    )

    # ---- verbose 诊断区: 中文含义为主行, raw audit 码收进方括号附录 ----
    if run.service_run.block_reason and verbose:
        debug.append(
            f"运行阻断：{_run_block_reason_zh(run.service_run.block_reason)}  "
            f"[block_reason={run.service_run.block_reason}]"
        )
    if run.service_run.block_reasons and verbose:
        debug.append(
            f"运行阻断：{'；'.join(_run_block_reason_zh(code) for code in run.service_run.block_reasons)}  "
            f"[block_reasons={','.join(run.service_run.block_reasons)}]"
        )
    if run.service_run.blocked_tickers and verbose:
        debug.append(
            f"manifest 拦截票：{','.join(run.service_run.blocked_tickers)}  "
            f"[manifest_blocked_tickers={','.join(run.service_run.blocked_tickers)}]"
        )
    if run.service_run.ticker_gate_blocks and verbose:
        debug.append("manifest 门控拦截  [manifest_gate_blocks]")
        debug.extend(
            f"  {block.ticker}  "
            f"{'；'.join(_DEBUG_GATE_REASON_ZH.get(reason, reason) for reason in block.reasons)}  "
            f"[reasons={' | '.join(block.reasons)}]"
            for block in run.service_run.ticker_gate_blocks
        )
    if verbose and debug:
        lines.append("")
        lines.append("──────────────────── 诊断明细（--verbose）────────────────────")
        lines.extend(f"  {d}" for d in debug)

    return "\n".join(lines)


def _load_prices_for_ticker(ticker: str, report_date: str) -> pd.DataFrame:
    """加载 ticker 价格 (tushare 优先, 含报告日前的历史)。"""
    cutoff = pd.to_datetime(str(report_date).replace("-", ""), format="%Y%m%d", errors="coerce")
    cache = Path("data/price_cache") / f"{ticker}.csv"
    if cache.exists():
        df = pd.read_csv(cache, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"])
        if pd.notna(cutoff):
            df = df[df["date"] <= cutoff]
        return df.sort_values("date").reset_index(drop=True)
    # 拉取 (tushare)
    from src.tools.tushare_api import get_tushare_token

    token = get_tushare_token()
    if not token:
        return pd.DataFrame()
    import tushare as ts

    pro = ts.pro_api(token=token)
    suffix = ".SZ" if ticker.startswith(("0", "3")) else ".SH"
    raw = pro.daily(ts_code=f"{ticker}{suffix}", start_date="20200101", end_date=report_date)
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    df = (
        pd.DataFrame(
            {
                "date": pd.to_datetime(raw["trade_date"], format="%Y%m%d"),
                "close": raw["close"].astype(float),
                "open": raw["open"].astype(float),
                "high": raw["high"].astype(float),
                "low": raw["low"].astype(float),
                "pct_change": raw["pct_chg"].astype(float),
            }
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_csv(cache, df)
    if pd.notna(cutoff):
        df = df[df["date"] <= cutoff]
    return df


def generate_daily_action(
    report_path: Path | str | None = None,
    tracker: PaperTracker | None = None,
    tickers_to_scan: int = 30,
    *,
    use_data_fetcher: Any = None,
    price_loader: Any = None,
    scan_mode: str = "full_market",
    end_date: str | None = None,
    legacy_persistence: bool = True,
    legacy_capacity: bool = True,
    authoritative_sessions: tuple[date, ...] | None = None,
) -> list[DailyAction]:
    """生成今日机械动作。

    流程:
    1. 确定 trade_date + regime (full_market: price_cache 最新日; report: 报告日期)
    2. **先平到期仓位 + 回填 realized P&L** (驱动 drawdown, 保证熔断基于最新 nav)
    3. drawdown 熔断检查 (决定是否允许新仓)
    4. 扫描候选 ticker, 对每个跑所有已验证 setup 的 detect
    5. 命中票查对应 known_distribution → Kelly 仓位
    6. 风险计划 (止损 + 时间退出 + 失效条件)
    7. 写入 paper journal

    Args:
        scan_mode: "full_market" (默认, 扫 price_cache 全市场 302 ticker) 或
            "report" (读 --auto 报告的 top-N 候选, 旧模式, 测试兼容)
        use_data_fetcher: ``(ticker, start, end) -> [{"time", "close"}, ...]`` 注入
            seam, 传给 close_matured 取 T+N 收益 (测试用, 对齐 recommendation_tracker)
        price_loader: ``(ticker, report_date) -> DataFrame`` 注入 seam, 传给
            close_matured 读 low 序列检测止损触发 (测试用)
        end_date: 显式信号日覆盖 (YYYYMMDD 或 YYYY-MM-DD). 仅 full_market 模式生效;
            非空时跳过 price_cache 探测, 直接用指定日期 + regime_history 标签.
            传入已过买入窗口的旧日期会触发 _missed_entry_window_reason 保护 (设计如此).
    """
    if tracker is None:
        tracker = PaperTracker()
    _load_prices = price_loader if price_loader is not None else _load_prices_for_ticker
    tracker.last_action_stale_reason = ""

    # 1. 确定 trade_date + regime + 候选 ticker 列表
    if scan_mode == "report":
        # 旧模式: 读 --auto 报告 (测试兼容)
        if report_path is None:
            from src.screening.consecutive_recommendation import resolve_report_dir
            from src.screening.data_quality_audit import _find_latest_report

            latest = _find_latest_report(resolve_report_dir())
            if latest is None:
                return []
            report_path = latest
        with open(report_path, encoding="utf-8") as f:
            report = json.loads(f.read())
        trade_date = str(report.get("date", ""))
        recs = report.get("recommendations", [])[:tickers_to_scan]
        scan_tickers = [str(rec.get("ticker", "")) for rec in recs if rec.get("ticker")]
        regime = str(report.get("market_state", {}).get("regime_gate_level", "normal"))
    else:
        # full_market: 全市场扫描 (不依赖 --auto 报告的 score_b 候选池)
        if end_date:
            # 显式 --end-date 覆盖: 跳过 price_cache 探测 + 17:00 guard, 直接用指定日期
            trade_date = _compact_trade_date(end_date)
            regime = _regime_from_history(trade_date)
        else:
            if legacy_persistence:
                trade_date, regime = _resolve_trade_date_and_regime()
            else:
                trade_date, regime = _resolve_trade_date_and_regime(
                    wall_clock_guard=False
                )
        tracker.last_action_trade_date = trade_date
        latest_report_date = _latest_auto_report_date()
        sessions = authoritative_sessions or _load_authoritative_session_dates()
        report_compact = _compact_trade_date(latest_report_date)
        report_date_value = (
            datetime.strptime(report_compact, "%Y%m%d").date()
            if report_compact
            else None
        )
        eligible_report_sessions = (
            [session for session in sessions if session <= report_date_value]
            if report_date_value
            else []
        )
        latest_report_trade_date = (
            max(eligible_report_sessions).strftime("%Y%m%d")
            if eligible_report_sessions
            else ""
        )
        if latest_report_trade_date and trade_date and latest_report_trade_date > trade_date:
            tracker.last_action_stale_reason = f"price_cache 最新交易日 {trade_date} 落后于最新 --auto 报告交易日 {latest_report_trade_date}; " "为避免使用过期信号, 本次不输出新 BUY"
            tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=_load_prices)
            return []
        missed_window_reason = (
            _missed_entry_window_reason(trade_date)
            if legacy_persistence
            else _missed_entry_window_reason(
                trade_date, sessions=authoritative_sessions
            )
        )
        if missed_window_reason:
            tracker.last_action_stale_reason = missed_window_reason
            tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=_load_prices)
            return []
        all_cache_tickers = sorted(p.stem for p in Path("data/price_cache").glob("*.csv"))
        # 永久排除票 (退市/数据残缺, 如 000004): 残留 csv 会被 glob 拾起,
        # 每天以 industry_data_missing 进"不可计划候选"制造噪声. 在此根除.
        if any(is_excluded_ticker(t) for t in all_cache_tickers):
            all_cache_tickers = [t for t in all_cache_tickers if not is_excluded_ticker(t)]
        # ST 过滤 (安全: --auto 候选池在 Layer A 过滤 ST, full_market 直扫需独立过滤)
        st_tickers = _load_st_tickers()
        if st_tickers:
            excluded = [t for t in all_cache_tickers if t in st_tickers]
            if excluded:
                logger.info("full_market 扫描排除 %d 只 ST 股: %s", len(excluded), excluded[:5])
            scan_tickers = [t for t in all_cache_tickers if t not in st_tickers]
        else:
            scan_tickers = all_cache_tickers
        recs = []  # report 模式专用

    tracker.last_action_trade_date = trade_date
    tracker.last_action_regime = regime

    # 2. 先平到期仓位 + 回填 realized P&L → 驱动 drawdown (闭环核心)
    tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=_load_prices)

    # 3. drawdown 熔断
    dd_action = tracker.drawdown_action()
    if dd_action == "liquidate":
        return []

    # 4. 资金流 store
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    store = FundFlowStore(cache_dir="data/fund_flow_cache/")

    # 5. 预加载每个已验证 setup 的 known_distribution (跳过被 DAILY_ACTION_DISABLED_SETUPS 暂停的)
    # OversoldBounce 默认暂停: 2026 实测 E[r]≈0 (crisis 亏钱), 避免占用仓位/资金流配额.
    # 可设 DAILY_ACTION_DISABLED_SETUPS=none 恢复 (补全历史数据重跑后再决定去留).
    disabled_setups = _env_setup_disable_list()
    setup_configs = []
    for name, cls, horizon in _VERIFIED_SETUPS:
        if name in disabled_setups:
            logger.info("setup %s 已通过 DAILY_ACTION_DISABLED_SETUPS 暂停, 跳过", name)
            continue
        dist = get_known_distribution(name, horizon)
        if dist is None:
            logger.warning("无 %s T+%d 已知分布, 跳过该 setup", name, horizon)
            continue
        setup_configs.append((name, cls(), horizon, dist))
    if not setup_configs:
        logger.warning("无任何已验证 setup 的 known_distribution, --daily-action 无法出信号")
        return []

    needs_industry_day_pct = any(name == "btst_breakout" for name, *_rest in setup_configs)
    industry_day_pct_by_ticker = _load_industry_day_pct_by_ticker(trade_date, scan_tickers) if needs_industry_day_pct else {}

    # 加载 ticker→行业映射 (供行业集中度限制用)
    _ticker_industry_map = _load_ticker_to_industry_from_snapshots(scan_tickers) if scan_tickers else {}

    # C-HELD-DEDUP: 排除已开仓 ticker, 防止"仓位释放后买以下候选"里出现当前已持有的票
    # (重复检测: 同一涨停日对已持仓票同样触发 setup, 不去重则 operator 看到候选即已持仓).
    held_tickers: set[str] = {str(p["ticker"]) for p in tracker.open_positions_detail()} if tracker else set()

    ranked_candidates: list[tuple[float, float, float, int, DailyAction]] = []
    for ticker in scan_tickers:
        if not ticker:
            continue
        if ticker in held_tickers:
            logger.debug("ticker %s 已持仓, 跳过候选检测 (去重)", ticker)
            continue
        prices = _load_prices(ticker, trade_date)
        if prices is None or len(prices) == 0:
            continue

        if not legacy_persistence and not _price_frame_is_fresh(prices, trade_date):
            terminal_close = prices.iloc[-1].get("close", 0.0)
            reference_price = (
                float(terminal_close) if pd.notna(terminal_close) else 0.0
            )
            tracker.last_scanner_blocks.append(
                BlockedCandidate(ticker, "stale_price_cache", reference_price)
            )
            continue

        last_row = prices.iloc[-1]
        pct = float(last_row.get("pct_change", 0.0) or 0.0)

        # 快速预过滤: 只有涨停日 (pct >= 9.5) 或超跌日才需要读 fund_flow.
        # 效率优化: 78%+ 的 ticker 不是涨停日, 跳过昂贵的 fund_flow CSV 读取.
        # 超跌判定用 pct_change 链式复合 (除权免疫); 链条断裂时不跳过 (交给 detect 判定).
        drop30 = chained_return_pct(prices, len(prices) - 31, len(prices) - 1) if len(prices) >= 31 else None
        needs_flow = pct >= 9.5 or (len(prices) >= 31 and (drop30 is None or drop30 <= -20))
        flow_records = store.get_range(ticker, "20200101", trade_date) if needs_flow else []

        # 对每个已验证 setup 跑 detect
        for setup_name, setup_obj, horizon, known_dist in setup_configs:
            # 快速预过滤 (避免对全量 ticker 跑慢 detect).
            # 用主板下限 9.5% 故意宽松: 它是所有板块涨停的公共下限 (科创/创业 20%,
            # 北交所 30% 都 ≥9.5%), 保证不漏任何潜在涨停股; 真正的板块自适应阈值
            # (limit_up_pct_for_ticker) 在 setup.detect 里按 ticker 精确判定.
            if setup_name == "btst_breakout" and pct < 9.5:
                continue  # BTST 只看涨停日
            if setup_name == "oversold_bounce":
                # OversoldBounce: 近30日跌幅需>20% (否则 detect 必 miss)
                # 与 detect 同口径: pct_change 链式复合 (除权免疫); 链条断裂放行给 detect.
                if len(prices) < 31:
                    continue
                drop30 = chained_return_pct(prices, len(prices) - 31, len(prices) - 1)
                if drop30 is not None and drop30 > -20:
                    continue

            industry_pct = industry_day_pct_by_ticker.get(ticker) if setup_name == "btst_breakout" else 0.0
            ctx = {
                "prices": prices,
                "fund_flow_records": flow_records,
                "industry_day_pct": industry_pct,
                "regime": regime,
            }
            result = setup_obj.detect(ticker, trade_date, ctx)
            if not result.hit:
                if scan_mode == "report":
                    tracker.record_skip(trade_date, ticker, setup_name, horizon, reasoning=f"未触发 (pct={pct:.1f}%)")
                continue

            # regime gate: 信号日 crisis/risk_off 不开新仓 (与 snapshot 路径同语义).
            # 放在仓位计算前 — 被闸票不进 ranked, render 的 blocked 由门循环统一披露.
            if regime in _REGIME_GATE_BLOCK_REGIMES:
                if scan_mode == "report":
                    tracker.record_skip(trade_date, ticker, setup_name, horizon, reasoning=f"regime 闸阻断 ({regime})")
                continue

            # 仓位计算: per-setup 上限 × drawdown 降仓 × trigger_strength 调节.
            # 简化: BTST Kelly f*=5.35 永远触顶 → 直接用 setup_max_pct, 去掉装饰性 Kelly 计算.
            # trigger_strength (新 alpha ranker: weekday+board+depth) 调节强弱信号仓位.
            setup_max_pct = _MAX_POSITION_PCT_BY_SETUP.get(setup_name, _MAX_POSITION_PCT)
            drawdown_factor = 0.5 if dd_action == "decrease" else 1.0
            strength_factor = max(0.3, min(1.0, float(result.trigger_strength)))
            kelly_pct = setup_max_pct * drawdown_factor * strength_factor
            if kelly_pct <= 0:
                if scan_mode == "report":
                    tracker.record_skip(trade_date, ticker, setup_name, horizon, reasoning="仓位为 0")
                continue

            # 风险计划 (止损基于盘整区底部, 物理结构自适应)
            # btst_breakout 在 metadata 中传入 range_based_stop_pct (基于 20 日最低价)
            range_stop = result.metadata.get("range_based_stop_pct") if result.metadata else None
            hard_stop_override = range_stop if range_stop is not None else -0.08
            risk = build_risk_plan(
                invalidation_condition=result.invalidation_condition,
                avg_loss=known_dist.avg_loss,
                natural_horizon=horizon,
                setup_name=setup_name,
                hard_stop_pct=hard_stop_override,
            )
            entry_price = float(last_row["close"])
            soft_stop_price = entry_price * (1 + risk.stop_loss_pct)
            hard_stop_price = entry_price * (1 + risk.hard_stop_pct)
            dist_summary = f"n={known_dist.n} winrate={known_dist.winrate:.0%} " f"cv={known_dist.convexity_ratio:.2f} E=+{known_dist.expected_return:.1%}"

            action = DailyAction(
                ticker=ticker,
                setup=setup_name,
                action="BUY",
                kelly_pct=kelly_pct,
                entry_price=entry_price,
                soft_stop=soft_stop_price,
                hard_stop=hard_stop_price,
                time_exit=risk.time_exit,
                invalidation_condition=result.invalidation_condition,
                distribution_summary=dist_summary,
                reasoning=f"{setup_name} T+{horizon} 命中; 仓位 {kelly_pct:.1%}; regime={regime}; drawdown={dd_action}",
                trigger_strength=float(result.trigger_strength),
                degraded=bool(getattr(result, "degraded", False)),
                degradation_reason=str(getattr(result, "degradation_reason", "") or ""),
            )
            ranked_candidates.append(
                (
                    float(result.trigger_strength),
                    horizon,
                    action,
                )
            )
            break  # 同票只取第一个命中的 setup (避免重复仓位)

    # 简化排序: 只按 trigger_strength 降序 (旧 4 键排序中 expected_return/convexity
    # 是同一 setup 的常量先验, 零区分度). trigger_strength 现在是真正的 alpha ranker.
    ranked_candidates.sort(
        key=lambda item: (
            -item[0],
            item[2].ticker,
        )
    )

    actions: list[DailyAction] = []
    # C-PORTFOLIO-CAP (20260710): 组合上限必须计入已开仓位 (T+10 跨日持仓).
    # 此前 portfolio_position_used 每次 run 从 0 起算 → 真实敞口峰值 260% (26 仓),
    # 61 天超 60% 上限. 现从 open_exposure 起算 (默认), 让 "组合 ≤ 60%" 真正按组合执行.
    # DAILY_ACTION_ENFORCE_OPEN_CAP=false 时恢复旧 per-run 行为 (逃生口).
    portfolio_position_used = float(getattr(tracker.state, "open_exposure", 0.0) or 0.0) if _enforce_open_cap() else 0.0

    # 行业集中度控制: 同一信号日同一行业最多 2 个仓位.
    # 回测验证: 集中日(≥50%同行业)平均收益 +6.3% vs 分散日 +9.7% (差 3.4pp).
    # 最差日全部是高度集中的 (通信 4/6, 有色 4/6). 限制集中度降低尾部风险.
    industry_count_today: dict[str, int] = {}
    _MAX_PER_INDUstry_DAILY = 2

    # 被风控过滤的候选 (按强度已排序). 单一真相源:
    #   - render 计数总述用 len(blocked_candidates)
    #   - render 明细列表直接遍历 blocked_candidates
    # 旧实现同时维护 cap_blocked_count (int) + blocked_candidates (list), 两者永远相等 → 冗余.
    blocked_candidates: list[DailyAction] = []

    for idx, (_trigger_strength, horizon, action) in enumerate(ranked_candidates):
        # 最低 trigger_strength 过滤: 去掉 ranker 底部信号 (Mon+SZmain 等).
        # NaN guard: setup 契约返回 float, 但除零/log(0) 等可能产生 NaN.
        # Python 中 NaN < threshold 永远为 False, 必须用 math.isnan 显式拦截.
        ts = action.trigger_strength
        if math.isnan(ts) or ts < _MIN_TRIGGER_STRENGTH:
            action.block_reason = f"强度 {ts:.2f} < {_MIN_TRIGGER_STRENGTH:.2f} 阈值" if not math.isnan(ts) else f"强度 NaN (setup 计算异常), 阈值 {_MIN_TRIGGER_STRENGTH:.2f}"
            blocked_candidates.append(action)
            continue

        # 最低入场价过滤: 低价股 (<3 元) 尾部亏损严重 (002217 @2.61 → -35.6%)
        if action.entry_price < _MIN_ENTRY_PRICE:
            action.block_reason = f"价格 {action.entry_price:.2f} < {_MIN_ENTRY_PRICE:.1f} 元下限"
            blocked_candidates.append(action)
            continue

        # 行业集中度限制
        ticker_industry = _ticker_industry_map.get(action.ticker, "unknown")
        if legacy_capacity and industry_count_today.get(ticker_industry, 0) >= _MAX_PER_INDUstry_DAILY:
            action.block_reason = f"行业集中 ({ticker_industry} 已 {_MAX_PER_INDUstry_DAILY} 仓)"
            blocked_candidates.append(action)
            continue

        kelly_pct = action.kelly_pct
        if legacy_capacity and portfolio_position_used + kelly_pct > _MAX_PORTFOLO_PCT:
            kelly_pct = max(0.0, _MAX_PORTFOLO_PCT - portfolio_position_used)
        if kelly_pct <= 0:
            # 剩余敞口不够 → 本候选及之后全部因敞口上限被跳过.
            for _ts, _h, rem_action in ranked_candidates[idx:]:
                rem_action.block_reason = f"敞口 {portfolio_position_used:.0%} 达 {_MAX_PORTFOLO_PCT:.0%} 上限"
                blocked_candidates.append(rem_action)
            break

        action.kelly_pct = kelly_pct
        action.reasoning = f"{action.setup} T+{horizon} 命中; 仓位 {kelly_pct:.1%}; regime={regime}; drawdown={dd_action}"
        actions.append(action)
        portfolio_position_used += kelly_pct
        industry_count_today[ticker_industry] = industry_count_today.get(ticker_industry, 0) + 1

        if legacy_persistence:
            tracker.record_buy(
                trade_date=trade_date,
                ticker=action.ticker,
                setup=action.setup,
                horizon=horizon,
                entry_price=action.entry_price,
                kelly_pct=kelly_pct,
                soft_stop=action.soft_stop,
                hard_stop=action.hard_stop,
                invalidation=action.invalidation_condition,
                reasoning=action.reasoning,
                trigger_strength=action.trigger_strength,
                degraded=action.degraded,
            )

    # C-DAILY-ACTION-POSITION-VISIBILITY: 暴露被风控过滤的候选 (按强度已排序),
    # 让 operator 看到"今日哪些票可交易" — 上限决定买什么, 不决定看什么.
    # blocked_candidates 只含被过滤的候选 (未买入), 不含已录入 actions 的候选.
    # C-PORTFOLIO-CAP: 暴露组合敞口状态供 render 披露 (operator 须看到为何不出新仓).
    tracker.last_portfolio_exposure = portfolio_position_used
    tracker.last_blocked_candidates = blocked_candidates
    return actions


def scan_from_verified_snapshot(
    snapshot: VerifiedDailyActionSnapshot,
) -> DailyActionScan:
    """Scan setups using a verified PIT snapshot instead of cache files.

    The scanner never reopens cache files. It adapts immutable frozen snapshot
    rows into a private detector DataFrame, filters manifest-degraded setups
    before detection, filters detector-degraded hits after detection, and emits
    only structured ``PlanCandidate`` provenance for actionable hits.
    """
    # Setup policy is frozen in the verified manifest. Runtime environment
    # changes after publication must not alter the authorized scan.
    enabled_setups = {
        setup_name
        for readiness in snapshot.manifest.ticker_readiness.values()
        for setup_name, capability in readiness.capabilities.items()
        if capability.enabled
    }
    setup_configs: list[tuple[str, Any, int, Any]] = []
    for name, cls, horizon in _VERIFIED_SETUPS:
        if name not in enabled_setups:
            continue
        dist = get_known_distribution(name, horizon)
        if dist is None:
            logger.warning(
                "scan_from_verified_snapshot: no known distribution for %s T+%d",
                name,
                horizon,
            )
            continue
        setup_configs.append((name, cls(), horizon, dist))
    if not setup_configs:
        logger.warning(
            "scan_from_verified_snapshot: no verified setup configs, returning empty"
        )
        return DailyActionScan(snapshot.signal_date, (), (), (), snapshot.snapshot_id)

    trade_date = snapshot.signal_date.strftime("%Y%m%d")
    regime = snapshot.regime
    snapshot_id = snapshot.snapshot_id

    ranked: list[tuple[float, int, str, str, float, RegimeAuthorization]] = []
    blocked: list[BlockedCandidate] = []
    reference_prices: dict[str, float] = {}
    # 扫描漏斗计数: 预筛/命中在 detect 前中后各打一点, 让"沉默的大多数"
    # (未命中票) 在渲染层变成可见数字. 仅 btst 启用时 评估次数 = 票数.
    evaluated_count = 0
    prefilter_passed = 0
    hit_count = 0

    def price_frame(rows: Sequence[Any]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": row.trade_date.isoformat(),
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                    "volume": float(row.volume) if row.volume is not None else None,
                    "pct_change": float(row.pct_change) if row.pct_change is not None else None,
                }
                for row in rows
            ]
        )

    def flow_records(ticker: str, rows: Sequence[Any]) -> list[FundFlowRecord]:
        # main_net_pct=0.0 是有意的诚实哨兵, 不是静默清零: snapshot 的
        # FrozenFlowRow 只持久化 main_net_inflow (daily_action_snapshot.py),
        # 根本不带 main_net_pct —— 该字段在此数据源中不存在. 从别处补真实 pct
        # 会绕过 provenance gate (本次扫描必须只消费 verified snapshot), 故填
        # 0.0 表示 "本路径无此数据". 下游不得把它当作真实资金流比率解读.
        return [
            FundFlowRecord(
                ticker=ticker,
                date=row.trade_date.strftime("%Y%m%d"),
                close=float(row.close) if row.close is not None else 0.0,
                pct_change=float(row.pct_change) if row.pct_change is not None else 0.0,
                main_net_inflow=float(row.main_net_inflow),
                main_net_pct=0.0,
            )
            for row in rows
        ]

    for ticker in snapshot.scannable_tickers:
        # 永久排除票 (退市/数据残缺): 不进任何路径, 连 degraded 噪声都不产生.
        if is_excluded_ticker(ticker):
            continue
        for setup_name, setup_obj, horizon, known_dist in setup_configs:
            ctx = snapshot.setup_context(ticker, setup_name)
            if ctx is None:
                continue
            try:
                reference_prices[ticker] = snapshot.reference_price(ticker)
            except KeyError:
                continue
            entry_price = reference_prices[ticker]
            if not ctx.capability.plan_eligible:
                blocked.append(BlockedCandidate(ticker, "candidate_not_plan_eligible", entry_price, setup_name))
                continue

            prices = price_frame(ctx.prices)
            if prices.empty:
                continue
            last_row = prices.iloc[-1]
            pct = float(last_row.get("pct_change", 0.0) or 0.0)

            if setup_name == "btst_breakout":
                evaluated_count += 1
                if pct < 9.5:
                    continue  # BTST 只看涨停日
                prefilter_passed += 1
            if setup_name == "oversold_bounce":
                # 与 detect 同口径: pct_change 链式复合 (除权免疫); 链条断裂放行给 detect.
                if len(prices) < 31:
                    continue
                drop30 = chained_return_pct(prices, len(prices) - 31, len(prices) - 1)
                if drop30 is not None and drop30 > -20:
                    continue

            industry_pct = ctx.industry_day_pct if setup_name == "btst_breakout" else 0.0
            detect_ctx = {
                "prices": prices,
                "fund_flow_records": flow_records(ticker, ctx.fund_flow_records),
                "industry_day_pct": industry_pct,
                "regime": regime,
            }
            result = setup_obj.detect(ticker, trade_date, detect_ctx)
            if not result.hit:
                continue
            hit_count += 1
            if bool(getattr(result, "degraded", False)):
                blocked.append(BlockedCandidate(ticker, "detector_degraded", entry_price, setup_name, float(result.trigger_strength or 0.0), metadata=dict(result.metadata or {})))
                continue
            # regime gate: 信号日 crisis/risk_off 不开新仓. detect 照跑,
            # blocked 带完整 trigger_strength 诊断 — 面板继续积累危机日对照组.
            if regime in _REGIME_GATE_BLOCK_REGIMES:
                blocked.append(BlockedCandidate(ticker, "regime_gate_halt", entry_price, setup_name, float(result.trigger_strength or 0.0), metadata=dict(result.metadata or {})))
                continue

            setup_max_pct = _MAX_POSITION_PCT_BY_SETUP.get(setup_name, _MAX_POSITION_PCT)
            strength_factor = max(0.3, min(1.0, float(result.trigger_strength)))
            kelly_pct = setup_max_pct * strength_factor
            if kelly_pct <= 0:
                continue

            range_stop = result.metadata.get("range_based_stop_pct") if result.metadata else None
            hard_stop_override = range_stop if range_stop is not None else -0.08
            build_risk_plan(
                invalidation_condition=result.invalidation_condition,
                avg_loss=known_dist.avg_loss,
                natural_horizon=horizon,
                setup_name=setup_name,
                hard_stop_pct=hard_stop_override,
            )
            authorization = {
                "crisis": RegimeAuthorization.BTST_CRISIS,
                "risk_off": RegimeAuthorization.BTST_RISK_OFF,
            }.get(regime, RegimeAuthorization.NORMAL)
            ranked.append(
                (
                    float(result.trigger_strength),
                    horizon,
                    ticker,
                    setup_name,
                    kelly_pct,
                    authorization,
                    dict(result.metadata or {}),
                )
            )

    # Sort by trigger_strength desc, ticker asc — deterministic ordering.
    ranked.sort(key=lambda item: (-item[0], item[2]))

    # Apply minimum entry-price and trigger-strength thresholds (same as the
    # legacy scanner's blocked_candidates path) so the returned list matches the
    # shape operators expect: actionable candidates + filtered-out candidates.
    candidates: list[PlanCandidate] = []
    for trigger_strength, _horizon, ticker, setup_name, kelly_pct, authorization, metadata in ranked:
        ts = trigger_strength
        entry_price = reference_prices[ticker]
        if math.isnan(ts) or ts < _MIN_TRIGGER_STRENGTH:
            blocked.append(BlockedCandidate(ticker, "trigger_strength_below_threshold", entry_price, setup_name, float(ts) if not math.isnan(ts) else 0.0, metadata=dict(metadata)))
            continue
        if entry_price < _MIN_ENTRY_PRICE:
            blocked.append(BlockedCandidate(ticker, "entry_price_below_minimum", entry_price, setup_name, float(ts), metadata=dict(metadata)))
            continue
        ctx = snapshot.setup_context(ticker, setup_name)
        if ctx is None:
            blocked.append(BlockedCandidate(ticker, "candidate_not_plan_eligible", entry_price, setup_name))
            continue
        if setup_name not in _LEDGER_ENABLED_SETUPS:
            # 台账尚不能承接该 setup (如 OB): 拦截在 PlanCandidate 硬拒之前,
            # 否则异常会把当日全部新计划 (含 BTST) 一起 fail-closed.
            blocked.append(BlockedCandidate(ticker, "setup_not_ledger_enabled", entry_price, setup_name, float(ts)))
            continue
        candidates.append(
            PlanCandidate(
                ticker=ticker,
                setup=setup_name,
                setup_version="v2",
                signal_date=snapshot.signal_date,
                target_weight=kelly_pct,
                priority=len(candidates) + 1,
                snapshot_id=snapshot.snapshot_id,
                setup_consumed_fingerprint=ctx.consumed_fingerprint,
                detector_degraded=False,
                authorization=authorization,
                trigger_strength=float(trigger_strength),
                entry_price=entry_price,
                metadata=metadata,
            )
        )

    return DailyActionScan(
        snapshot.signal_date,
        tuple(candidates),
        tuple(blocked),
        tuple(sorted(reference_prices.items())),
        snapshot.snapshot_id,
        funnel=ScanFunnel(
            scannable=evaluated_count,
            prefilter_passed=prefilter_passed,
            hits=hit_count,
        ),
    )


def resolve_daily_action_signal(
    *,
    end_date: str | None = None,
    now_cn: datetime | None = None,
    open_sessions: Sequence[date] | None = None,
) -> tuple[date, str]:
    """Resolve the authoritative --daily-action signal session and regime."""
    sessions = tuple(
        _load_authoritative_session_dates()
        if open_sessions is None
        else open_sessions
    )
    selected = resolve_signal_session(
        now_cn=now_cn or _current_cn_datetime(),
        open_sessions=sessions,
        override=end_date,
    )
    compact = selected.strftime("%Y%m%d")
    return selected, _regime_from_history(compact)


def scan_daily_action_candidates(
    *,
    report_path: Path | str | None = None,
    tickers_to_scan: int = 30,
    price_loader: Any = None,
    scan_mode: str = "full_market",
    end_date: str | None = None,
    authoritative_sessions: tuple[date, ...] | None = None,
) -> DailyActionScan:
    """Scan cached market data without writing either legacy paper-trading store."""
    tracker = _ScannerCompatibilityState()

    actions = generate_daily_action(
        report_path=report_path,
        tracker=tracker,
        tickers_to_scan=tickers_to_scan,
        price_loader=price_loader,
        scan_mode=scan_mode,
        end_date=end_date,
        legacy_persistence=False,
        legacy_capacity=False,
        authoritative_sessions=authoritative_sessions,
    )
    signal_text = str(tracker.last_action_trade_date or end_date or "").replace("-", "")
    if not signal_text:
        signal_text = _current_cn_datetime().strftime("%Y%m%d")
    signal_date = datetime.strptime(signal_text, "%Y%m%d").date()
    regime = str(tracker.last_action_regime)
    authorization = {
        "crisis": RegimeAuthorization.BTST_CRISIS,
        "risk_off": RegimeAuthorization.BTST_RISK_OFF,
    }.get(regime, RegimeAuthorization.NORMAL)
    tradable = tuple(action for action in actions if not action.degraded)
    candidates = tuple(
        PlanCandidate(
            ticker=action.ticker,
            setup=action.setup,
            setup_version="v2",
            signal_date=signal_date,
            target_weight=action.kelly_pct,
            priority=priority,
            snapshot_id="legacy_unverified",
            setup_consumed_fingerprint="legacy_unverified",
            detector_degraded=bool(action.degraded),
            authorization=authorization,
            # 穿线 detect 诊断 (强度/参考价/metadata) — 渲染层的交易计划详情块
            # 与 setup_output_log 样本外面板都按这些字段取数, 缺失会退化为空壳.
            trigger_strength=float(action.trigger_strength),
            entry_price=float(action.entry_price),
            metadata=dict(action.metadata or {}),
        )
        for priority, action in enumerate(tradable, 1)
    )
    degraded = tuple(
        BlockedCandidate(action.ticker, "incomplete_setup_data", action.entry_price)
        for action in actions
        if action.degraded
    )
    blocked = degraded + tuple(tracker.last_scanner_blocks) + tuple(
        BlockedCandidate(
            action.ticker,
            action.block_reason or "scanner_policy",
            action.entry_price,
        )
        for action in tracker.last_blocked_candidates
    )
    references = tuple((action.ticker, action.entry_price) for action in actions)
    return DailyActionScan(signal_date, candidates, blocked, references)


def _render_candidate_list(
    lines: list[str],
    candidates: list[DailyAction],
    get_stock_name: Callable[[str], str],
    buy_date_label: str,
    *,
    limit: int = 10,
    auto_topn: set[str] | None = None,
) -> None:
    """渲染"今日候选"列表 (上限跳过的 BTST 命中), 让 operator 看到今天哪些票可交易.

    C-DAILY-ACTION-POSITION-VISIBILITY: 上限决定买什么, 不决定看什么. 候选按
    generate_daily_action 的强度排序 (ranked_candidates) 传入, 这里只做展示.
    超过 limit 个只显示前 limit 个 + 一行"其余 N 只略", 避免刷屏.
    C-DUAL-SIGNAL-CONVERGENCE: auto_topn 非空时, 同日也在 --auto Top-N 的候选
    标 ⭐双信号 (历史胜率更高, n 小仅供参考).
    """
    from colorama import Fore, Style

    topn = auto_topn or set()
    shown = candidates[:limit]
    for i, a in enumerate(shown, 1):
        name = get_stock_name(a.ticker)
        label = f"{a.ticker} {name}" if name and name != a.ticker else a.ticker
        converge = " ⭐双信号" if a.ticker.split(".")[0] in topn else ""
        # Bug B: degraded 命中 (如资金流历史不足) 标 ⚠残缺, 让 operator 知道
        # 这个命中未经完整 setup 条件验证 — 运行时检测口径比回测分布更宽松.
        degraded_tag = " ⚠残缺" if getattr(a, "degraded", False) else ""
        # block_reason: 精确展示该候选被过滤的具体原因 (价格/强度/行业/敞口),
        # 替代旧的笼统 "三者之一". operator 据此判断 "等价格涨上来" vs "这票废了".
        block_tag = f"  {Fore.YELLOW}⚠ {a.block_reason}{Style.RESET_ALL}" if getattr(a, "block_reason", "") else ""
        # 标注"先验(驱动Kelly)"区别于表头的"真实回测"——两套不可比的数字用用途标签区分.
        # trigger_strength 是候选排序的真实依据 (星期+板块+区间位置+波动率压缩), 需展示让排序可解释.
        lines.append(f"  {Fore.WHITE}{i}. {Fore.CYAN}{label}{Style.RESET_ALL}  [{_setup_display_name(a.setup)}]  " f"强度 {a.trigger_strength:.2f}  参考价 ~{a.entry_price:.2f}  先验(驱动Kelly) {a.distribution_summary}{converge}{degraded_tag}{block_tag}")
    rest = len(candidates) - len(shown)
    if rest > 0:
        lines.append(f"  {Fore.WHITE}...其余 {rest} 只略 (强度更低){Style.RESET_ALL}")


def render_daily_action(
    actions: list[DailyAction],
    trade_date: str,
    tracker: PaperTracker,
    *,
    closed_positions: list[dict[str, Any]] | None = None,
    explain: bool = False,
    today: date | str | None = None,
) -> str:
    """渲染机械动作 (decision support, 移除情绪)。

    Args:
        closed_positions: close_matured 返回的平仓摘要 (今日到期平仓的仓位).
            若有, 在组合状态后渲染平仓段, 让 operator 看到 realized P&L 演进.
            默认从 tracker.last_closed_positions 读 (generate_daily_action 已缓存).
        explain: 展开术语说明 + 执行规则 (默认隐藏, 用 --verbose 调出).
            跑了一周以上的 operator 已熟记规则, 默认精简去掉每天重复的 11 行噪音.
        today: "剩N天" / 到期释放日程的 as-of 基准. 默认 None = 真实 wall clock
            (生产). 测试必须显式注入, 否则日历越过持仓到期日后 release 分支
            消失、断言落空 (R90 日历漂移家族).
    """
    from colorama import Fore, Style

    # 默认从 tracker 缓存读 (generate_daily_action 调 close_matured 时已写入)
    if closed_positions is None:
        closed_positions = getattr(tracker, "last_closed_positions", None) or []

    state = tracker.state
    dd = tracker.drawdown_action()
    dd_tag = {  # risk state
        "normal": f"{Fore.GREEN}正常{Style.RESET_ALL}",
        "decrease": f"{Fore.YELLOW}-15%降仓{Style.RESET_ALL}",
        "liquidate": f"{Fore.RED}-20%清仓{Style.RESET_ALL}",
    }[dd]
    next_trade_date = _resolve_next_trade_date(trade_date)
    buy_date_label = next_trade_date or "下一交易日"

    # 累计已实现盈亏的限定语: 0 笔 EXIT 时无信息含量, 用限定语区分"待结算"与"N笔已平仓".
    closed_count = sum(1 for rec in tracker._load_journal() if rec.get("action") == "EXIT")
    realized_qualifier = "(待到期结算)" if closed_count == 0 else f"({closed_count}笔已平仓)"

    lines = [
        f"\n{Fore.CYAN}{Style.BRIGHT}📋 机械交易计划 — 信号日: {trade_date}{Style.RESET_ALL}",
        f"  计划买入日: {buy_date_label}  组合敞口: {state.open_exposure:.0%} / {_MAX_PORTFOLO_PCT:.0%} 上限" + (" ⚠超配" if state.open_exposure > _MAX_PORTFOLO_PCT + 1e-9 else ""),
    ]
    # 执行价口径 + 净值/回撤/持仓数 → --verbose (每次跑都一样的口径说明 + 初始状态无信息量).
    if explain:
        lines.append(f"  执行价口径: {buy_date_label} 开盘; 当前展示价为信号日收盘参考价")
        lines.append(f"  组合净值: {state.nav:.3f}  回撤: {_format_drawdown(state.drawdown_pct)}  风控状态: {dd_tag}")
        lines.append(f"  持仓数: {state.open_positions}  累计已实现: {state.realized_pnl_pct:+.2%} {realized_qualifier}")
    # C-PORTFOLIO-CAP: 若本次跳过新信号, 显式披露原因.
    # cap_blocked 可能由多种原因触发: 强度不足/价格过低/行业集中/敞口上限.
    # 每个候选的具体 block_reason 在候选列表里展示, 这里只做计数总述.
    blocked = list(getattr(tracker, "last_blocked_candidates", []) or [])
    cap_blocked = len(blocked)
    if cap_blocked > 0 and not actions:
        at_cap = state.open_exposure >= _MAX_PORTFOLO_PCT - 1e-9
        if at_cap:
            lines.append(f"  {Fore.YELLOW}⚠ 组合敞口已达 {_MAX_PORTFOLO_PCT:.0%} 上限 — {cap_blocked} 个新信号被跳过, 待仓位释放后恢复{Style.RESET_ALL}")
        else:
            lines.append(f"  {Fore.YELLOW}ℹ {cap_blocked} 个信号未通过风控过滤 (具体原因见候选行){Style.RESET_ALL}")
    for policy_line in _setup_policy_lines(explain=explain):
        lines.append(f"  {policy_line}")

    # C-DAILY-ACTION-POSITION-VISIBILITY: 列出当前持仓 + 到期释放日程.
    # 此前只显示 "持仓数: N" (计数), operator 看不到自己买了什么、何时到期释放.
    from src.tools.tushare_api import get_stock_name

    # as_of 用今天 (而非信号日 trade_date) — operator 关心 "从今天起还要等几天仓位释放",
    # 不是 "从信号日起过了几天". 信号日做基准会让 "剩N天" 比直觉多 2-3 天.
    today_str = _coerce_today_yyyymmdd(today)
    open_details = tracker.open_positions_detail(as_of=today_str, price_loader=_load_prices_for_ticker)
    if open_details:
        lines.append(f"\n  {Fore.WHITE}📌 当前持仓 ({len(open_details)} 只, 敞口 {state.open_exposure:.0%}):{Style.RESET_ALL}")
        for p in open_details:
            name = get_stock_name(p["ticker"]) if p["ticker"] else ""
            label = f"{p['ticker']} {name}" if name and name != p["ticker"] else p["ticker"]
            days = p["days_to_maturity"]
            if days is None:
                maturity_label = f"到期 {p['matures_on'] or '?'}"
            elif days <= 0:
                maturity_label = f"{Fore.YELLOW}今日到期{Style.RESET_ALL}"
            else:
                maturity_label = f"到期 {p['matures_on']} (剩{days}天)"
            # 浮动盈亏: operator 直觉需求 — "我的仓位现在赚了还是亏了".
            # unrealized_pct 来自 price_cache latest close, 标 "浮" 与 realized P&L 区分.
            upct = p.get("unrealized_pct")
            if upct is not None:
                upct_color = Fore.GREEN if upct >= 0 else Fore.RED
                pnl_label = f"  {upct_color}浮 {upct:+.1%}{Style.RESET_ALL}"
            else:
                pnl_label = f"  浮 --"
            lines.append(f"  - {Fore.CYAN}{label}{Style.RESET_ALL}  [{_setup_display_name(p['setup'])}]  " f"{p['buy_date']}买入 @{p['entry_price']:.2f} ({p['kelly_pct']:.0%}){pnl_label}  {maturity_label}")
        # 到期释放日程: operator 关心 "仓位何时释放 / 释放后敞口多少"
        soonest = next((p for p in open_details if p["days_to_maturity"] is not None and p["days_to_maturity"] > 0), None)
        if soonest:
            soonest_date = soonest["matures_on"]
            release_n = sum(1 for p in open_details if p["matures_on"] == soonest_date)
            release_pct = sum(p["kelly_pct"] for p in open_details if p["matures_on"] == soonest_date)
            after_exposure = max(0.0, state.open_exposure - release_pct)
            lines.append(f"  {Fore.WHITE}💡 最近到期 {soonest_date}: " f"释放 {release_n} 只/{release_pct:.0%}敞口 → 约 {after_exposure:.0%}" + (f" (仍超 {_MAX_PORTFOLO_PCT:.0%} 上限, 需继续等待)" if after_exposure > _MAX_PORTFOLO_PCT + 1e-9 else f" (降回上限内, 可恢复出新仓)") + f"{Style.RESET_ALL}")
        if explain:
            lines.append(f"  {Fore.WHITE}释放机制: 每仓在买入日 + setup horizon 天后的下一次 --daily-action 自动平仓回填 P&L (无需手动){Style.RESET_ALL}")

    # 今日平仓摘要 (闭环核心: operator 看到 realized P&L 演进 + 止损触发披露)
    if closed_positions:
        lines.append(f"\n  {Fore.WHITE}📤 今日到期平仓 ({len(closed_positions)} 只):{Style.RESET_ALL}")
        for c in closed_positions:
            pnl = c.get("realized_pnl", 0.0)
            pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
            stop_flag = ""
            if c.get("stop_would_have_triggered"):
                stop_flag = f"  {Fore.YELLOW}⚠ 期间触硬止损{Style.RESET_ALL}"
            ticker = c.get("ticker", "")
            name = get_stock_name(ticker) if ticker else ""
            ticker_label = f"{ticker} {name}" if name and name != ticker else ticker
            lines.append(f"  - {Fore.CYAN}{ticker_label}{Style.RESET_ALL}  " f"realized {pnl_color}{pnl:+.1%}{Style.RESET_ALL}  " f"exit ~{c.get('exit_price', 0.0):.2f}{stop_flag}")

    stale_reason = getattr(tracker, "last_action_stale_reason", "")
    if stale_reason:
        lines.append(f"\n  {Fore.RED}⚠ 数据滞后 — {stale_reason}{Style.RESET_ALL}")
        lines.append(f"  {Fore.YELLOW}本次不输出新 BUY; 请先刷新 data/price_cache / fund_flow_cache 后重跑。{Style.RESET_ALL}")
        return "\n".join(lines)

    if dd == "liquidate":
        lines.append(f"\n  {Fore.RED}⚠ DRAWDOWN 熔断 (-20%) — 不出新仓, 平掉所有持仓{Style.RESET_ALL}")
        return "\n".join(lines)

    # C-DUAL-SIGNAL-CONVERGENCE: 加载信号日 --auto Top-N, 标记 BTST 命中里同日
    # 也在 --auto Top-N 的票 (双信号收敛, 历史胜率更高 76% vs 66%, n 小仅供参考).
    auto_topn = _load_auto_topn_tickers(trade_date)
    all_hits = list(actions) + blocked
    converge_n = sum(1 for a in all_hits if a.ticker.split(".")[0] in auto_topn)
    if auto_topn and all_hits and converge_n:
        # C-DUAL-SIGNAL-CONVERGENCE: bootstrap 验证 (20260710) — 观察到收敛子集胜率
        # +10.8pp, 但 95% CI [-6.8%, +27.5%] 跨 0, P(无优势)=11.7% → 未达统计显著.
        # 诚实披露: 标记事实 (同日在两系统), 但不宣称"已验证更优", 防止 operator
        # 据噪声点估计加仓. 待样本累积 (n>100 收敛子集) 后重测.
        lines.append(f"  {Fore.WHITE}⭐ 双信号: {converge_n}/{len(all_hits)} 只 BTST 命中同日也在 --auto Top-N (bootstrap 未达显著 CI[-7%,+28%], 可能是噪声, 勿据此加仓){Style.RESET_ALL}")
    if not actions and not blocked:
        lines.append(f"\n  {Fore.YELLOW}今日无凸性 setup 命中 (空仓等待){Style.RESET_ALL}")
        return "\n".join(lines)

    if not actions and blocked:
        # 有命中但全部未录入 — 列出候选, 让 operator 知道今天哪些票有信号.
        # 每个候选的 block_reason 在 _render_candidate_list 里精确展示 (价格/强度/行业/敞口),
        # 这里只做总述, 不再笼统说 "三者之一".
        at_cap = state.open_exposure >= _MAX_PORTFOLO_PCT - 1e-9
        if at_cap:
            reason = f"组合敞口 {state.open_exposure:.0%} 达 {_MAX_PORTFOLO_PCT:.0%} 上限"
        else:
            reason = f"全部被风控过滤 (具体原因见每行)"
        lines.append(f"\n  {Fore.YELLOW}今日 {len(blocked)} 个 setup 命中 — {reason}, 本次暂不买入. " f"仓位释放后按强度优先买以下候选:{Style.RESET_ALL}\n")
        _render_candidate_list(lines, blocked, get_stock_name, buy_date_label, limit=12, auto_topn=auto_topn)
        lines.append(f"\n  {Fore.WHITE}(候选仅供参考; 上限保护期可不操作, 或用上限外资金自行决策){Style.RESET_ALL}")
        # 候选行含"先验(驱动Kelly)"和"强度", 与表头"真实回测"是两套独立统计 —
        # 在候选后即时标注用途, 避免跨段对照时混淆 (术语完整版用 --verbose 查看).
        if explain:
            lines.append(f"  {Fore.WHITE}说明: 先验(驱动Kelly)≠表头真实回测, 两套独立统计; 强度=排序依据; T+N=交易日, 剩N天=日历日(以今天为基准), 未到期仓位浮动盈亏为参考{Style.RESET_ALL}")
        return "\n".join(lines)

    lines.append(f"\n  {Fore.GREEN}计划 BUY ({len(actions)} 只, {buy_date_label} 开盘执行):{Style.RESET_ALL}\n")
    for i, a in enumerate(actions, 1):
        # ticker + 中文名 (get_stock_name 解析失败时回退 ticker 本身, 不重复显示)
        name = get_stock_name(a.ticker)
        ticker_label = f"{a.ticker} {name}" if name and name != a.ticker else a.ticker
        converge = " ⭐双信号" if a.ticker.split(".")[0] in auto_topn else ""
        # Bug B: degraded 命中标 ⚠残缺 + 披露原因, 让 operator 知道未经完整条件验证.
        degraded_tag = ""
        if getattr(a, "degraded", False):
            degraded_tag = f"  {Fore.YELLOW}⚠残缺: {a.degradation_reason}{Style.RESET_ALL}"
        lines.append(f"  {Fore.WHITE}{i}. {Fore.CYAN}{ticker_label}{Style.RESET_ALL}  [{_setup_display_name(a.setup)}]  " f"仓位 {a.kelly_pct:.1%}  参考价(信号日收盘) ~{a.entry_price:.2f}{converge}{degraded_tag}")
        lines.append(f"     风险价位: 软止损 {a.soft_stop:.2f} (观察) / " f"硬止损 {a.hard_stop:.2f} (披露/人工执行参考; paper P&L 不按止损出场)  " f"时间退出: {a.time_exit}")
        lines.append(f"     先验分布: {a.distribution_summary}")
        lines.append(f"     {Fore.YELLOW}失效: {a.invalidation_condition}{Style.RESET_ALL}\n")

    # C-DAILY-ACTION-POSITION-VISIBILITY: BUY 之后若还有被风控过滤的候选, 也列出来
    # (operator 想知道"今天还有哪些票可交易", 上限只限买不限看).
    if blocked:
        lines.append(f"  {Fore.WHITE}其余 {len(blocked)} 个候选 (未通过风控过滤, 具体原因见每行):{Style.RESET_ALL}")
        _render_candidate_list(lines, blocked, get_stock_name, buy_date_label, limit=8, auto_topn=auto_topn)

    if explain:
        lines.append(f"  {Fore.WHITE}术语说明:{Style.RESET_ALL}")
        lines.append(f"  - 软止损=历史平均亏损x1.5的观察线, 用于风险参考, 不是自动卖出触发")
        lines.append(f"  - 硬止损=固定-8%的风控参考线; 止损触发只做披露, paper P&L 按 T+N 收盘回填")
        lines.append(f"  - 先验分布: n=历史样本数, winrate=历史胜率, cv=凸性比, E=历史平均收益 (与表头'真实回测'两套独立统计, 各自标注用途)")
        lines.append(f"  - 强度=trigger_strength(星期25%+板块25%+区间位置25%+波动率压缩25%), 决定候选排序和仓位大小")
        lines.append(f"  - T+N=交易日; 剩N天=日历日(T+10≈14日历日); 到期按第N个交易日收盘结算P&L; 未到期仓位浮动盈亏不计入")
        # Bug B: 若本次有 degraded 命中, 集中披露让 operator 注意未经完整条件验证的信号.
        all_hits = list(actions) + list(blocked)
        degraded_hits = [a for a in all_hits if getattr(a, "degraded", False)]
        if degraded_hits:
            lines.append(f"  - {Fore.YELLOW}⚠残缺=命中缺资金流均值过滤条件 (fund_flow_cache 历史<5日), 运行时检测比回测分布更宽松; 本次 {len(degraded_hits)}/{len(all_hits)} 只命中为残缺, 补全资金流历史后复跑可收紧{Style.RESET_ALL}")

        lines.append(f"\n  {Fore.WHITE}执行规则 (按规则执行):{Style.RESET_ALL}")
        lines.append(f"  - {buy_date_label} 开盘买入 (不追涨, 涨停买不到就放弃)")
        lines.append(f"  - 只执行预先写好的买入/止损/到期规则, 不临盘主观加仓/扛单")
        lines.append(f"  - 硬止损或失效条件触发 → 规则上应当日收盘处理; 当前 journal 只记录 stop_would_trigger")
        lines.append(f"  - 到期 (setup horizon) → 无条件平 (不恋战)")
        lines.append(f"  - 回撤 -15% 自动降仓 / -20% 清仓")
    # 闭环已自动: close_matured 在 generate_daily_action 开头平到期仓并回填 P&L.
    # 此前写 "30 天后用 --paper-pnl 复盘" 是死承诺 (该命令从未实现).
    lines.append(f"\n  {Fore.WHITE}已写入 paper journal (按各 setup horizon 到期自动平仓 + 回填 realized P&L){Style.RESET_ALL}")
    return "\n".join(lines)
