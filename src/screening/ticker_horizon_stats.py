"""Per-ticker multi-horizon 胜率/赔率/期望 纯函数 helper.

从 tracking_history records 计算指定 ticker 在多个 horizon (T+5/T+10/...)
的 winrate / payoff_ratio / expectancy / sample_count.

设计原则:
- **纯函数 + loader 分离**: 重算逻辑无 I/O 副作用, loader 单独处理 JSON 读取.
  测试用合成 records 即可, 不需真实 tracking_history.
- **同口径**: 与 ``historical_prior_opportunity._summarize_next_close_payoff``
  的 T+1 winrate/payoff/expectancy 算法一致 (avg_win/avg_loss_abs 口径),
  保证 T+1 与 T+5/T+10 数字可比.
- **扩展性好**: horizons 参数化, 未来加 T+15/T+20 只需改 horizons tuple.
- **per-ticker**: 与 priority_board 的 ``next_close_*`` 同口径 (same-ticker
  historical), 不是 per-bucket (C220 ``win_rates.t5`` 是 per-bucket).

CLI 入口: ``scripts/analyze_btst_ticker_horizon_stats.py``.

关联: C219 (tracking_history 回填 7993 records + 7201 mature),
C220 (BUY gate horizon T+5/T+10 OR), C221 (signal_horizon 呈现层).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

# horizon key → tracking_history field name 映射 (与 regime_winrate_recompute 一致)
_HORIZON_TO_FIELD: dict[str, str] = {
    "t1": "next_day_return",
    "t3": "next_3day_return",
    "t5": "next_5day_return",
    "t10": "next_10day_return",
    "t15": "next_15day_return",
    "t20": "next_20day_return",
    "t25": "next_25day_return",
    "t30": "next_30day_return",
}

_DEFAULT_HORIZONS: tuple[str, ...] = ("t5", "t10")


@dataclass(frozen=True)
class TickerHorizonStats:
    """Per-ticker × per-horizon 胜率/赔率/期望 (与 next_close_* 同口径).

    Attributes:
        winrate: 0-1 (正收益比例); None 当 sample_count=0.
        payoff_ratio: avg_win / avg_loss_abs (无亏损样本时为 None).
        expectancy: mean(returns) (百分点); None 当 sample_count=0.
        sample_count: mature 样本数 (非 None return 的 records 数).
        positive_count: 正收益样本数.
        negative_count: 负收益样本数.
        avg_win: 平均正收益 (百分点); None 当无正收益样本.
        avg_loss_abs: 平均亏损绝对值 (百分点); None 当无负收益样本.
    """

    winrate: float | None
    payoff_ratio: float | None
    expectancy: float | None
    sample_count: int
    positive_count: int
    negative_count: int
    avg_win: float | None
    avg_loss_abs: float | None


def compute_ticker_horizon_stats(
    records: list[dict[str, Any]],
    ticker: str,
    *,
    horizons: tuple[str, ...] = _DEFAULT_HORIZONS,
) -> dict[str, TickerHorizonStats]:
    """从 tracking_history records 计算 per-ticker × per-horizon stats.

    纯函数: 无 I/O, 无副作用. 测试用合成 records 即可.

    Args:
        records: tracking_history record dict 列表. 每条至少含 ``ticker``
            (str) + 各 horizon return 字段 (``next_5day_return`` / ...).
            缺失 return 字段视为该 horizon 未 mature (跳过该 horizon).
            records 可以包含多个 ticker (函数会按 ticker 过滤).
        ticker: 目标股票代码 (str, 精确匹配 ``record['ticker']``).
        horizons: 计算 horizons (默认 t5/t10). 支持的 horizon 见
            ``_HORIZON_TO_FIELD`` keys.

    Returns:
        ``{horizon: TickerHorizonStats}`` — 每个 horizon 的 stats.
        无数据的 horizon 返回 ``sample_count=0`` 的空 stats (而非 None,
        方便下游渲染统一处理).

    Raises:
        KeyError: 当 horizons 含未识别的 horizon key (不在 _HORIZON_TO_FIELD).

    Example:
        >>> records = [
        ...     {"ticker": "002463", "next_5day_return": 1.5, "next_10day_return": 2.0},
        ...     {"ticker": "002463", "next_5day_return": -0.5, "next_10day_return": -1.0},
        ...     {"ticker": "688008", "next_5day_return": 0.8},
        ... ]
        >>> stats = compute_ticker_horizon_stats(records, "002463")
        >>> stats["t5"].winrate
        0.5
        >>> stats["t5"].sample_count
        2
    """
    result: dict[str, TickerHorizonStats] = {}
    for horizon in horizons:
        field = _HORIZON_TO_FIELD[horizon]  # KeyError 显式暴露非法 horizon
        returns = _collect_ticker_horizon_returns(records, ticker, field)
        result[horizon] = _summarize_returns(returns)
    return result


def _collect_ticker_horizon_returns(
    records: list[dict[str, Any]],
    ticker: str,
    field: str,
) -> list[float]:
    """从 records 过滤指定 ticker 的指定 horizon return (跳过 None/NaN/Inf).

    C251: 加 NaN/Inf guard (与 sibling ``regime_winrate_recompute._optional_float``
    对齐). ``float(NaN)`` 不抛异常 → NaN 进 returns → ``statistics.mean`` 传播 NaN
    → expectancy=NaN, winrate 分母被稀释. 用 ``math.isfinite`` 过滤 NaN/Inf.
    """
    returns: list[float] = []
    for rec in records:
        if str(rec.get("ticker") or "") != ticker:
            continue
        value = rec.get(field)
        if value is None:
            continue
        try:
            f = float(value)
        except (TypeError, ValueError):
            continue  # 非数字 return 跳过, 不污染 stats
        if not math.isfinite(f):  # NaN / Inf 跳过 (C251)
            continue
        returns.append(f)
    return returns


def _summarize_returns(returns: list[float]) -> TickerHorizonStats:
    """算 winrate/payoff/expectancy (与 next_close_* 同口径).

    复用 historical_prior_opportunity._summarize_next_close_payoff 的算法:
    - winrate = positive_count / sample_count
    - payoff_ratio = avg_win / avg_loss_abs (无亏损时 None)
    - expectancy = mean(returns)
    """
    n = len(returns)
    if n == 0:
        return TickerHorizonStats(
            winrate=None,
            payoff_ratio=None,
            expectancy=None,
            sample_count=0,
            positive_count=0,
            negative_count=0,
            avg_win=None,
            avg_loss_abs=None,
        )

    wins = [r for r in returns if r > 0]
    losses = [abs(r) for r in returns if r < 0]
    positive_count = len(wins)
    negative_count = len(losses)

    avg_win = round(statistics.mean(wins), 4) if wins else None
    avg_loss_abs = round(statistics.mean(losses), 4) if losses else None
    payoff_ratio = _compute_payoff_ratio(avg_win, avg_loss_abs)
    expectancy = round(statistics.mean(returns), 4)
    winrate = round(positive_count / n, 4)

    return TickerHorizonStats(
        winrate=winrate,
        payoff_ratio=payoff_ratio,
        expectancy=expectancy,
        sample_count=n,
        positive_count=positive_count,
        negative_count=negative_count,
        avg_win=avg_win,
        avg_loss_abs=avg_loss_abs,
    )


def _compute_payoff_ratio(avg_win: float | None, avg_loss_abs: float | None) -> float | None:
    """盈亏比 = 平均盈利 / 平均亏损绝对值 (与 historical_prior_opportunity 一致)."""
    if avg_win is None or avg_loss_abs is None or avg_loss_abs <= 0:
        return None
    return round(avg_win / avg_loss_abs, 4)


def load_tracking_records(reports_dir: Any) -> list[dict[str, Any]]:
    """加载 tracking_history.json records (loader 与纯函数分离).

    Args:
        reports_dir: reports 目录 Path (含 ``tracking_history.json``).

    Returns:
        records list. 文件不存在或无 ``records`` key 时返回空 list.
    """
    from pathlib import Path

    reports_path = Path(reports_dir)
    tracking_file = reports_path / "tracking_history.json"
    if not tracking_file.is_file():
        return []

    import json

    try:
        data = json.loads(tracking_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    records = data.get("records") if isinstance(data, dict) else None
    return records if isinstance(records, list) else []
