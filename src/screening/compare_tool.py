"""P1-8 标的对比工具 — 2-5 只股票的多维度对比 + ASCII 雷达图。

设计目标:
  让用户在 Top N 推荐中, 对几只都满足买入条件的候选股做最终选择。
  通过 min-max 归一化 + 胜场统计, 直观展示每只股票在 5 个核心维度
  (趋势 / 均值回归 / 基本面 / 事件情绪 / 综合 score_b) 的相对强弱。

主入口:
  - ``CompareMetric``: 单标的单指标
  - ``CompareReport``: 对比报告 (tickers + 平铺 metrics + 胜场汇总)
  - ``compare_tickers``: 主入口 — 对 2-5 只标的做多维对比
  - ``render_compare_table``: 生成 ASCII 对比表 (类似 tabulate 输出)
  - ``render_radar_chart``: 生成 ASCII 雷达图 (无需 matplotlib)
  - ``run_compare_cli``: CLI 入口 (供 main.py --compare 复用)
  - ``load_latest_recommendations``: 从最新 ``auto_screening_*.json`` 报告加载推荐

注意:
  - metric_keys 缺省为五大维度: trend_score / mean_reversion_score /
    fundamental_score / event_sentiment_score / score_b
  - 缺失 ticker 视作 0.0 (允许与历史报告中的标的对比)
  - NaN / Inf 输入一律替换为 0.0 (防御 GMM-001 类 NaN 污染)
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.numeric import safe_float as _safe_float

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: 对比组允许的标的数量区间 — 至少 2 只才能做横向对比, 至多 5 只避免图表过密
MIN_COMPARE_TICKERS: int = 2
MAX_COMPARE_TICKERS: int = 5

#: metric_keys 缺省值 — 五大核心维度 (P1-8 提案)
DEFAULT_METRIC_KEYS: list[str] = [
    "trend_score",
    "mean_reversion_score",
    "fundamental_score",
    "event_sentiment_score",
    "score_b",
]

#: metric_key -> 内部 strategy 名称 (score_b 不在 strategy_signals 中, 走顶层)
_METRIC_TO_STRATEGY: dict[str, str] = {
    "trend_score": "trend",
    "mean_reversion_score": "mean_reversion",
    "fundamental_score": "fundamental",
    "event_sentiment_score": "event_sentiment",
    "score_b": "__top__",  # 标记: 从 FusedScore.score_b 读取
}

#: 中文指标标签 (雷达图 / 表格表头)
METRIC_LABELS_CN: dict[str, str] = {
    "trend_score": "趋势",
    "mean_reversion_score": "均值回归",
    "fundamental_score": "基本面",
    "event_sentiment_score": "事件情绪",
    "score_b": "综合",
}


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class CompareMetric:
    """单标的单指标的对比数据。

    Fields:
        ticker: 股票代码
        metric_name: 指标名 (``trend_score`` / ``mean_reversion_score`` /
            ``fundamental_score`` / ``event_sentiment_score`` / ``score_b``)
        raw_value: 原始数值 (direction * confidence, 范围 -100 ~ +100;
            score_b 范围 -1.0 ~ +1.0)
        normalized: min-max 归一化后的 0-100 分
        rank_in_group: 在 group 内按 ``raw_value`` 降序排名 (1 = 第一名)
    """

    ticker: str
    metric_name: str
    raw_value: float
    normalized: float
    rank_in_group: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "metric_name": self.metric_name,
            "raw_value": self.raw_value,
            "normalized": self.normalized,
            "rank_in_group": self.rank_in_group,
        }


@dataclass
class CompareReport:
    """对比报告。

    Fields:
        tickers: 参与对比的 ticker 列表 (按输入顺序)
        metrics: 平铺为列表的 ``CompareMetric`` 集合 (长度 = len(tickers) * len(metric_keys))
        summary: ``{ticker: total_wins}`` 胜场统计 — 每只标的获得第 1 名的指标数
        winner: 胜场最多的 ticker (None 表示平局或全部 0 胜)
    """

    tickers: list[str] = field(default_factory=list)
    metrics: list[CompareMetric] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    winner: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tickers": list(self.tickers),
            "metrics": [m.to_dict() for m in self.metrics],
            "summary": dict(self.summary),
            "winner": self.winner,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------




def _extract_raw_metric(recommendation: dict[str, Any], metric_name: str) -> float:
    """从单条 recommendation dict 中提取 ``metric_name`` 对应的原始分数。

    - ``score_b``: 从顶层 ``rec["score_b"]`` 读取
    - 策略类指标: 从 ``rec["strategy_signals"][strategy_name]`` 中读取
      ``direction * confidence`` (有符号分数, 范围 -100 ~ +100)
    - 缺失 / 异常 -> 0.0
    """
    if not isinstance(recommendation, dict):
        return 0.0

    if metric_name == "score_b":
        return _safe_float(recommendation.get("score_b"), 0.0)

    strategy_name = _METRIC_TO_STRATEGY.get(metric_name)
    if not strategy_name or strategy_name == "__top__":
        # 未知 metric — 视为 0
        return 0.0

    signals = recommendation.get("strategy_signals")
    if not isinstance(signals, dict):
        return 0.0
    sig = signals.get(strategy_name)
    if not isinstance(sig, dict):
        return 0.0

    direction = _safe_float(sig.get("direction"), 0.0)
    confidence = _safe_float(sig.get("confidence"), 0.0)
    # direction 是 int -1/0/1, 但允许 float 退化
    sign = 1.0 if direction > 0 else -1.0 if direction < 0 else 0.0
    return sign * confidence


def _normalize_minmax(values: list[float]) -> list[float]:
    """对一组 raw_value 做 min-max 归一化到 0-100。

    算法:
      - 全部相等 -> 全部归一化为 50.0 (中性分, 避免全 0)
      - 否则 ``(v - min) / (max - min) * 100``

    注意: 即使 group 内只有 2 只标的也安全 (max != min).
    """
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if math.isclose(vmax, vmin, abs_tol=1e-9):
        return [50.0] * len(values)
    span = vmax - vmin
    return [(v - vmin) / span * 100.0 for v in values]


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def compare_tickers(
    tickers: list[str],
    recommendations: list[dict[str, Any]],
    *,
    metric_keys: list[str] | None = None,
) -> CompareReport:
    """对 2-5 只标的做多维对比。

    算法:
      1. 将 ``tickers`` 去重保序, 校验数量在 [2, 5] 之间
      2. 对每个 ticker 构建 ``ticker -> rec`` 查询表 (后出现的同名 ticker 覆盖前者)
      3. 对每个 metric 在 group 内做 min-max 归一化 (0-100)
      4. 计算每只标的的胜场数 (按 raw_value 排第 1 的指标数)
      5. 胜场最多的 ticker 为 winner (并列时取 ticker 字典序最小)

    Args:
        tickers: 参与对比的 ticker 列表 (2-5 只)
        recommendations: 推荐列表 (通常来自最新 auto_screening 报告的
            ``recommendations`` 字段, 每条含 ``ticker`` / ``score_b`` /
            ``strategy_signals``)
        metric_keys: 对比维度, 缺省 = :data:`DEFAULT_METRIC_KEYS`

    Returns:
        :class:`CompareReport` 实例, 含平铺的 metrics / 胜场统计 / winner

    Raises:
        ValueError: 标的数量不在 [2, 5] 区间
    """
    # 1. 校验 + 去重保序
    if not isinstance(tickers, list) or not tickers:
        raise ValueError("tickers 必须为非空 list")
    # 保留首次出现顺序去重
    seen: set[str] = set()
    ordered_tickers: list[str] = []
    for raw_ticker in tickers:
        ticker = str(raw_ticker).strip()
        if not ticker:
            continue
        if ticker not in seen:
            seen.add(ticker)
            ordered_tickers.append(ticker)
    if not (MIN_COMPARE_TICKERS <= len(ordered_tickers) <= MAX_COMPARE_TICKERS):
        raise ValueError(
            f"对比标的数量必须为 {MIN_COMPARE_TICKERS}-{MAX_COMPARE_TICKERS} 只, "
            f"实际: {len(ordered_tickers)}"
        )

    # 2. 构建 ticker -> rec 查询表
    rec_by_ticker: dict[str, dict[str, Any]] = {}
    if isinstance(recommendations, list):
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            ticker = str(rec.get("ticker", "")).strip()
            if ticker:
                rec_by_ticker[ticker] = rec

    # 3. metric_keys 校验
    if metric_keys is None:
        metric_keys = list(DEFAULT_METRIC_KEYS)
    if not isinstance(metric_keys, list) or not metric_keys:
        raise ValueError("metric_keys 必须为非空 list")
    # 去重保序 + 过滤未知 metric
    seen_metrics: set[str] = set()
    resolved_metrics: list[str] = []
    for raw_metric in metric_keys:
        metric = str(raw_metric).strip()
        if not metric or metric in seen_metrics:
            continue
        seen_metrics.add(metric)
        resolved_metrics.append(metric)
    if not resolved_metrics:
        raise ValueError("metric_keys 过滤后为空")

    # 4. 计算每个 ticker 在每个 metric 上的 raw_value
    raw_grid: list[list[float]] = []  # [ticker_idx][metric_idx]
    for ticker in ordered_tickers:
        rec = rec_by_ticker.get(ticker)
        row = [_extract_raw_metric(rec or {}, metric) for metric in resolved_metrics]
        raw_grid.append(row)

    # 5. 对每列做 min-max 归一化 + 排名
    metrics_flat: list[CompareMetric] = []
    win_count: dict[str, int] = {ticker: 0 for ticker in ordered_tickers}
    for metric_idx, metric in enumerate(resolved_metrics):
        column = [row[metric_idx] for row in raw_grid]
        normalized_col = _normalize_minmax(column)
        # 排名 (按 raw_value 降序) — 使用稳定排序 + tie-break by ticker 字典序
        indexed = sorted(
            enumerate(ordered_tickers),
            key=lambda pair: (-column[pair[0]], pair[1]),
        )
        rank_lookup: dict[str, int] = {}
        for rank, (row_idx, ticker) in enumerate(indexed, start=1):
            rank_lookup[ticker] = rank
        for row_idx, ticker in enumerate(ordered_tickers):
            metrics_flat.append(
                CompareMetric(
                    ticker=ticker,
                    metric_name=metric,
                    raw_value=column[row_idx],
                    normalized=normalized_col[row_idx],
                    rank_in_group=rank_lookup[ticker],
                )
            )
            if rank_lookup[ticker] == 1:
                win_count[ticker] += 1

    # 6. winner: 胜场最多者; 并列时取 ticker 字典序最小。
    #    注意: 全部 raw_value 相等 (e.g. 全部 0) 时, 排序稳定 -> 字典序最小者排第 1,
    #    因此 winner 仍取字典序最小 ticker, 而非 None。
    max_wins = max(win_count.values()) if win_count else 0
    if max_wins == 0:
        winner: str | None = None
    else:
        candidates = [t for t, w in win_count.items() if w == max_wins]
        winner = sorted(candidates)[0] if candidates else None

    return CompareReport(
        tickers=ordered_tickers,
        metrics=metrics_flat,
        summary=win_count,
        winner=winner,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_compare_table(report: CompareReport) -> str:
    """生成 ASCII 对比表 (类似 tabulate 输出)。

    表头: 指标 / ticker1 / ticker2 / ...
    数据行: 指标名 (中文) + 归一化分数 (0-100) + (排名)
    """
    if not report.tickers or not report.metrics:
        return "[Compare] 无对比数据\n"

    lines: list[str] = []
    # 按 ticker 列 + 指标行构建矩阵
    metric_keys_in_order: list[str] = []
    seen: set[str] = set()
    for m in report.metrics:
        if m.metric_name not in seen:
            metric_keys_in_order.append(m.metric_name)
            seen.add(m.metric_name)

    # 构造 {ticker: {metric: CompareMetric}}
    matrix: dict[str, dict[str, CompareMetric]] = {ticker: {} for ticker in report.tickers}
    for m in report.metrics:
        matrix[m.ticker][m.metric_name] = m

    # 表头
    col_width = max(12, max(len(t) for t in report.tickers) + 2, 12)
    metric_col_width = max(8, max(len(METRIC_LABELS_CN.get(m, m)) for m in metric_keys_in_order) + 2)

    border = "+" + "-" * metric_col_width + "+" + ("-" * col_width + "+") * len(report.tickers)
    lines.append(border)
    header_line = "|" + "指标".center(metric_col_width) + "|"
    for ticker in report.tickers:
        header_line += ticker.center(col_width) + "|"
    lines.append(header_line)
    lines.append(border)

    # 数据行
    for metric in metric_keys_in_order:
        metric_label = METRIC_LABELS_CN.get(metric, metric)
        row = "|" + metric_label.center(metric_col_width) + "|"
        for ticker in report.tickers:
            cell = matrix[ticker].get(metric)
            if cell is None:
                row += "—".center(col_width) + "|"
            else:
                cell_text = f"{cell.normalized:.0f} (#{cell.rank_in_group})"
                row += cell_text.center(col_width) + "|"
        lines.append(row)
    lines.append(border)

    # 胜场汇总
    summary_line = "胜场: " + " | ".join(f"{t}={report.summary.get(t, 0)}" for t in report.tickers)
    lines.append(summary_line)
    if report.winner:
        lines.append(f"推荐首选: {report.winner} (胜场最多)")
    return "\n".join(lines) + "\n"


def render_radar_chart(report: CompareReport, ticker: str) -> str:
    """生成单只标的的 ASCII 雷达图。

    简化版: 在 5/3/4 边形上画各指标归一化分数 (0-100) 的折线,
    用 ``*`` 标记折线点, ``.`` 标记空缺位置。

    为了避免依赖 matplotlib / 复杂几何, 这里采用「行扫描」方式:
    - 将雷达图视为 11x31 的字符网格
    - 中心在 (5, 15)
    - 每个指标在圆周上按等角度分布
    - 指标值越大 -> 离中心越远

    雷达图坐标系: 行 0-10 (10 = 最远), 列 0-30 (15 = 中心)
    """
    if ticker not in report.tickers:
        return f"[Radar] 标的 {ticker} 不在对比组中\n"

    metric_keys_in_order: list[str] = []
    seen: set[str] = set()
    for m in report.metrics:
        if m.ticker == ticker and m.metric_name not in seen:
            metric_keys_in_order.append(m.metric_name)
            seen.add(m.metric_name)

    if not metric_keys_in_order:
        return f"[Radar] 标的 {ticker} 无指标数据\n"

    metric_map: dict[str, CompareMetric] = {}
    for m in report.metrics:
        if m.ticker == ticker:
            metric_map[m.metric_name] = m

    n_metrics = len(metric_keys_in_order)
    # 等角度分布 (从顶端 12 点钟方向顺时针)
    # 角度: -90° (top) -> 0° (right) -> 90° (bottom) -> 180° (left)
    # 但屏幕坐标 y 向下, 故需翻转
    HEIGHT, WIDTH = 11, 31
    center_x, center_y = 15, 5
    max_radius = 4.5  # 不超过边界

    # 网格初始化
    grid: list[list[str]] = [[" "] * WIDTH for _ in range(HEIGHT)]

    # 画同心圆参考线
    for r in (2, 4):
        for angle_deg in range(0, 360, 10):
            angle_rad = math.radians(angle_deg)
            x = center_x + r * math.cos(angle_rad)
            y = center_y + r * math.sin(angle_rad)
            ix, iy = int(round(x)), int(round(y))
            if 0 <= iy < HEIGHT and 0 <= ix < WIDTH:
                if grid[iy][ix] == " ":
                    grid[iy][ix] = "·"

    # 画坐标轴 (每个 metric 方向一条线)
    metric_angles: list[tuple[str, float]] = []
    for idx, metric in enumerate(metric_keys_in_order):
        # 12 点钟方向起, 顺时针
        angle_deg = -90 + (360.0 / n_metrics) * idx
        angle_rad = math.radians(angle_deg)
        metric_angles.append((metric, angle_rad))
        # 画轴线
        for r_step in range(1, int(max_radius) + 1):
            x = center_x + r_step * math.cos(angle_rad) * (max_radius / int(max_radius))
            y = center_y + r_step * math.sin(angle_rad) * (max_radius / int(max_radius))
            ix, iy = int(round(x)), int(round(y))
            if 0 <= iy < HEIGHT and 0 <= ix < WIDTH:
                if grid[iy][ix] == " ":
                    grid[iy][ix] = "·"

    # 画数据多边形
    points: list[tuple[int, int, str]] = []  # (x, y, label)
    for metric, angle_rad in metric_angles:
        cell = metric_map[metric]
        value_normalized = max(0.0, min(100.0, cell.normalized))
        radius = max_radius * (value_normalized / 100.0)
        x = center_x + radius * math.cos(angle_rad)
        y = center_y + radius * math.sin(angle_rad)
        ix, iy = int(round(x)), int(round(y))
        ix = max(0, min(WIDTH - 1, ix))
        iy = max(0, min(HEIGHT - 1, iy))
        points.append((ix, iy, METRIC_LABELS_CN.get(metric, metric)))

    # 在多边形上画点
    for ix, iy, _label in points:
        grid[iy][ix] = "*"

    # 画连接线 (简化: 不画连线, 仅标点 + 标签)
    # 中心标记
    grid[center_y][center_x] = "+"

    # 拼接为字符串
    lines = [f"[Radar] {ticker} ({report.summary.get(ticker, 0)} 胜场)"]
    lines.append("+" + "-" * WIDTH + "+")
    for row in grid:
        lines.append("|" + "".join(row) + "|")
    lines.append("+" + "-" * WIDTH + "+")

    # 标签 (按行追加, 避免与图形重叠)
    for ix, iy, label in points:
        # 显示坐标 (grid_y=0 是顶部)
        lines.append(f"  顶点 ({ix:2d},{iy:2d}) {label}: " f"norm={metric_map[[m for m, _ in metric_angles if METRIC_LABELS_CN.get(m, m) == label][0]].normalized:.1f}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


_REPORT_FILENAME_PATTERN = re.compile(r"^auto_screening_(\d{8})\.json$")


def load_latest_recommendations(
    report_dir: Path | str | None = None,
    *,
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    """从最新 (或指定日期) ``auto_screening_*.json`` 报告中加载推荐列表。

    Args:
        report_dir: 报告目录; 缺省时调用
            :func:`src.screening.consecutive_recommendation.resolve_report_dir`
        trade_date: 指定交易日期 (YYYYMMDD); ``None`` 时取最新一份报告

    Returns:
        ``recommendations`` 字段中的 dict 列表; 文件不存在 / 解析失败 -> ``[]``
    """
    if report_dir is None:
        from src.screening.consecutive_recommendation import resolve_report_dir

        resolved_dir = resolve_report_dir()
    else:
        resolved_dir = Path(report_dir)

    if not resolved_dir.exists():
        return []

    if trade_date:
        candidate = resolved_dir / f"auto_screening_{trade_date}.json"
        if not candidate.exists():
            return []
        candidates = [candidate]
    else:
        candidates = sorted(resolved_dir.glob("auto_screening_*.json"), reverse=True)
        if not candidates:
            return []

    for path in candidates:
        if not _REPORT_FILENAME_PATTERN.match(path.name):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        recs = payload.get("recommendations") or []
        if isinstance(recs, list) and recs:
            return [item for item in recs if isinstance(item, dict)]
    return []


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_compare_cli(
    tickers_arg: str,
    metrics_arg: str | None = None,
    *,
    show_radar: bool = True,
    report_dir: Path | str | None = None,
    trade_date: str | None = None,
) -> int:
    """CLI 入口 — 解析 ``--compare`` 参数并打印对比结果。

    Args:
        tickers_arg: 逗号分隔的 ticker 字符串 (e.g. "300750,600519,000001")
        metrics_arg: 逗号分隔的指标字符串 (e.g. "trend_score,score_b"),
            ``None`` 时用默认值
        show_radar: 是否为每只标的打印 ASCII 雷达图
        report_dir: 报告目录 (None -> 最新)
        trade_date: 报告日期 (None -> 最新)

    Returns:
        退出码 (0 = 成功, 1 = 错误)
    """
    from colorama import Fore, Style

    # 1. 解析 tickers
    raw_tickers = [t.strip() for t in (tickers_arg or "").split(",") if t.strip()]
    if not (MIN_COMPARE_TICKERS <= len(raw_tickers) <= MAX_COMPARE_TICKERS):
        print(
            f"{Fore.RED}[Compare] 标的数量必须为 {MIN_COMPARE_TICKERS}-{MAX_COMPARE_TICKERS} 只, "
            f"实际: {len(raw_tickers)} ({tickers_arg}){Style.RESET_ALL}"
        )
        return 1

    # 2. 解析 metric_keys
    metric_keys: list[str] | None = None
    if metrics_arg:
        metric_keys = [m.strip() for m in metrics_arg.split(",") if m.strip()]
        # 过滤未知 metric
        valid_metrics = set(DEFAULT_METRIC_KEYS)
        unknown = [m for m in metric_keys if m not in valid_metrics]
        if unknown:
            print(
                f"{Fore.RED}[Compare] 未知指标: {unknown} (合法: {sorted(valid_metrics)}){Style.RESET_ALL}"
            )
            return 1

    # 3. 加载推荐数据
    recommendations = load_latest_recommendations(report_dir=report_dir, trade_date=trade_date)
    if not recommendations:
        print(
            f"{Fore.YELLOW}[Compare] 未找到有效 auto_screening 报告 (trade_date={trade_date or 'latest'}), "
            f"请先运行 --auto{Style.RESET_ALL}"
        )
        return 1

    # 4. 执行对比
    try:
        report = compare_tickers(
            tickers=raw_tickers,
            recommendations=recommendations,
            metric_keys=metric_keys,
        )
    except ValueError as exc:
        print(f"{Fore.RED}[Compare] {exc}{Style.RESET_ALL}")
        return 1

    # 5. 打印结果
    print(f"\n{Fore.CYAN}{Style.BRIGHT}━━━ P1-8 标的对比 ━━━{Style.RESET_ALL}")
    print(f"  标的: {', '.join(report.tickers)}")
    if metric_keys:
        print(f"  指标: {', '.join(metric_keys)}")
    else:
        print(f"  指标: 全部默认 ({len(DEFAULT_METRIC_KEYS)} 项)")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'─' * 60}{Style.RESET_ALL}\n")
    print(render_compare_table(report), end="")
    if show_radar:
        print()
        for ticker in report.tickers:
            print(render_radar_chart(report, ticker))
    return 0


__all__ = [
    "MIN_COMPARE_TICKERS",
    "MAX_COMPARE_TICKERS",
    "DEFAULT_METRIC_KEYS",
    "METRIC_LABELS_CN",
    "CompareMetric",
    "CompareReport",
    "compare_tickers",
    "render_compare_table",
    "render_radar_chart",
    "load_latest_recommendations",
    "run_compare_cli",
]
