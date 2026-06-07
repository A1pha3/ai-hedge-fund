"""P1-4 因子重要性排行 (IC 分析) — 按子因子历史表现输出「本周最强因子 Top 10」。

IC (Information Coefficient) 是量化研究的标准指标:
  - 衡量因子值与下期收益的相关性 (Spearman / Pearson)
  - IR (Information Ratio) = mean(IC) / std(IC) 反映 IC 的稳健性
  - ic_positive_rate = IC > 0 的天数比例, 反映胜率

模块目标: 让策略研究员快速判断「当前市场哪些因子最有效」,
为下次回测 / 调参提供数据支撑, 而非凭直觉拍脑袋。

主入口:
  - ``FactorICResult``       — 单因子 IC 分析结果 (dataclass)
  - ``compute_factor_ic``    — 给定 ``{factor_name: [value_per_period]}`` 与下期收益, 返回 ``{factor_name: FactorICResult}``
  - ``classify_significance`` — 按 IC + IR 分级 (high/medium/low/insignificant)
  - ``extract_factor_panel_from_history`` — 从 ``data/reports/auto_screening_*.json`` 抽取因子面板 + 下期收益
  - ``render_factor_ic_ranking`` — 中文文本排行表 (用于 CLI 输出)

向后兼容: 该模块不依赖网络 / 数据库, 纯函数; 测试时使用 ``compute_factor_ic`` 直接注入合成数据。
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Filename pattern reused from signal_decay_detector (避免 import 循环)
_REPORT_FILENAME_PATTERN = re.compile(r"^auto_screening_(\d{8})\_.*\.json$|^auto_screening_(\d{8})\.json$")

# 显著性分级阈值
# - high:           abs(IC) >= 0.10 AND IR >= 1.0
# - medium:         abs(IC) >= 0.05 AND IR >= 0.5
# - low:            abs(IC) >= 0.02
# - insignificant:  其它
IC_HIGH_THRESHOLD: float = 0.10
IC_MEDIUM_THRESHOLD: float = 0.05
IC_LOW_THRESHOLD: float = 0.02
IR_HIGH_THRESHOLD: float = 1.0
IR_MEDIUM_THRESHOLD: float = 0.5

#: 相关系数计算最少需要的数据点数 (< MIN_OBS 直接返回空)
MIN_OBSERVATIONS: int = 3

#: 默认最小有效因子数 (< MIN_FACTORS 整体跳过)
MIN_FACTORS: int = 3


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorICResult:
    """单因子 IC 分析结果。

    Attributes:
        factor_name: 子因子名 (e.g. "momentum_20d")
        strategy: 所属策略 (trend / mean_reversion / fundamental / event_sentiment);
            当来源不明时为 "unknown"
        ic_mean: 平均 IC (Spearman or Pearson)
        ic_std: IC 标准差 (rolling 模式下非零, 单次模式下为 0.0)
        ir: 信息比率 = ic_mean / ic_std (单次模式下 = 0.0 因为分母为 0)
        ic_positive_rate: IC > 0 的比例 (单次模式下为 0.0 / 1.0)
        n_periods: 计算窗口期数
        rank: 按 IR 降序排名 (1 = 最佳)
        significance: 显著性等级 ("high" / "medium" / "low" / "insignificant")
        method: 相关系数计算方法 ("spearman" / "pearson")
    """

    factor_name: str
    strategy: str
    ic_mean: float
    ic_std: float
    ir: float
    ic_positive_rate: float
    n_periods: int
    rank: int
    significance: str
    method: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_name": self.factor_name,
            "strategy": self.strategy,
            "ic_mean": self.ic_mean,
            "ic_std": self.ic_std,
            "ir": self.ir,
            "ic_positive_rate": self.ic_positive_rate,
            "n_periods": self.n_periods,
            "rank": self.rank,
            "significance": self.significance,
            "method": self.method,
        }


# ---------------------------------------------------------------------------
# Statistics helpers (Spearman / Pearson / 排名) — 不依赖 scipy
# ---------------------------------------------------------------------------


def _pearson_correlation(x: Sequence[float], y: Sequence[float]) -> float:
    """Pearson 线性相关系数。长度不一致 / 标准差为 0 时返回 0.0。"""
    n = len(x)
    if n != len(y) or n < 2:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for xi, yi in zip(x, y, strict=False):
        dx = xi - mean_x
        dy = yi - mean_y
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy
    if var_x <= 0.0 or var_y <= 0.0:
        return 0.0
    correlation = cov / math.sqrt(var_x * var_y)
    # Clamp to [-1, 1] 处理浮点误差
    return max(-1.0, min(1.0, correlation))


def _rank_average(values: Sequence[float]) -> list[float]:
    """返回 ``values`` 的平均秩 (处理 ties — 与 scipy.stats.rankdata 默认行为一致)。"""
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks: list[float] = [0.0] * n
    i = 0
    while i < n:
        j = i
        # 找出 ties 的范围
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based 平均秩
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def _spearman_correlation(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman 秩相关系数 (= Pearson on ranks)。"""
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    rank_x = _rank_average(list(x))
    rank_y = _rank_average(list(y))
    return _pearson_correlation(rank_x, rank_y)


def _safe_stdev(values: Sequence[float]) -> float:
    """样本标准差 (ddof=1)。空 / 单元素 / NaN 输入返回 0.0。"""
    cleaned = [v for v in values if _is_finite(v)]
    n = len(cleaned)
    if n < 2:
        return 0.0
    mean = sum(cleaned) / n
    var = sum((v - mean) ** 2 for v in cleaned) / (n - 1)
    if var < 0.0:
        return 0.0
    return math.sqrt(var)


def _is_finite(value: Any) -> bool:
    """检查 value 是否为有限 float。None / NaN / Inf / 非数值 → False。"""
    if value is None:
        return False
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(fv)


# ---------------------------------------------------------------------------
# Significance classification
# ---------------------------------------------------------------------------


def classify_significance(ic_mean: float, ir: float) -> str:
    """按 (|IC|, IR) 把因子分级。

    Args:
        ic_mean: 平均 IC (允许负值 — 用 abs 比较)
        ir: 信息比率 (单次模式可传 0.0, 此时只看 |IC|)

    Returns:
        "high" / "medium" / "low" / "insignificant"
    """
    abs_ic = abs(ic_mean)
    # ``insignificant`` 必须最先判 — 涵盖 NaN/None 路径 (传入 0.0)
    if abs_ic < IC_LOW_THRESHOLD:
        return "insignificant"
    if abs_ic >= IC_HIGH_THRESHOLD and ir >= IR_HIGH_THRESHOLD:
        return "high"
    if abs_ic >= IC_MEDIUM_THRESHOLD and ir >= IR_MEDIUM_THRESHOLD:
        return "medium"
    if abs_ic >= IC_LOW_THRESHOLD:
        return "low"
    return "insignificant"


# ---------------------------------------------------------------------------
# Main entry: compute_factor_ic
# ---------------------------------------------------------------------------


def _extract_strategy(factor_name: str) -> str:
    """根据因子名前缀推断所属策略 (无前缀 → "unknown")。"""
    prefix = factor_name.split(".", 1)[0] if "." in factor_name else factor_name.split("_", 1)[0]
    mapping = {
        "trend": "trend",
        "mean_reversion": "mean_reversion",
        "fundamental": "fundamental",
        "event_sentiment": "event_sentiment",
    }
    return mapping.get(prefix, "unknown")


def _clean_series(series: Sequence[float]) -> list[float]:
    """过滤 NaN/Inf/None — 返回有限 float 列表。"""
    out: list[float] = []
    for v in series:
        if _is_finite(v):
            out.append(float(v))
    return out


def _aligned_pair(
    x_series: Sequence[float],
    y_series: Sequence[float],
) -> tuple[list[float], list[float]]:
    """逐位配对, 任意一边非有限则丢弃该位置。"""
    xs: list[float] = []
    ys: list[float] = []
    for xv, yv in zip(x_series, y_series, strict=False):
        if _is_finite(xv) and _is_finite(yv):
            xs.append(float(xv))
            ys.append(float(yv))
    return xs, ys


def compute_factor_ic(
    factor_history: dict[str, Sequence[float]],
    return_history: Sequence[float],
    *,
    method: str = "spearman",
    rolling_window: int | None = None,
) -> dict[str, FactorICResult]:
    """对每个因子计算其与下期收益的相关系数 (IC)。

    支持两种模式:
      - **单次模式** (默认): ``factor_history[factor]`` 与 ``return_history`` 等长;
        IC = corr 整段时间序列, IR = 0.0, ic_positive_rate = 0.0 (单次不算正负)
      - **Rolling 模式** (``rolling_window > 1``): 在 ``factor_history`` 上滑动窗口,
        每个窗口计算一个 IC; IC_mean / IC_std / IR / ic_positive_rate 都从窗口 IC 序列得出

    Args:
        factor_history: ``{factor_name: [value_per_period]}``。
            各因子序列必须与 ``return_history`` 等长; 长度不一致的因子会被自动截断到最短。
        return_history: 下期收益序列 (与 factor_history 索引对齐)。
        method: "spearman" (默认, 推荐) 或 "pearson"。
        rolling_window: rolling 窗口大小, None 或 <= 1 表示单次模式。

    Returns:
        ``{factor_name: FactorICResult}`` 映射; 输入空 / 因子数 < MIN_FACTORS / 所有数据
        都不可用时返回空 dict。

    Notes:
        - 返回值按 IR 降序排, rank 字段为 1..N; NaN 因子放最后 (rank = N, IR = 0)。
        - factor_name 含 ``.`` 时, 取第一段作为 strategy 推断 (e.g. ``trend.momentum_20d``
          → strategy=trend); 推断失败 → strategy="unknown"。
    """
    method_normalized = (method or "spearman").strip().lower()
    if method_normalized not in ("spearman", "pearson"):
        method_normalized = "spearman"

    if not factor_history:
        return {}
    n_factors = len(factor_history)
    if n_factors < MIN_FACTORS:
        logger.debug("[FactorIC] 因子数 %d < MIN_FACTORS=%d, 跳过", n_factors, MIN_FACTORS)
        return {}

    if not return_history or len(return_history) < MIN_OBSERVATIONS:
        logger.debug("[FactorIC] return_history 长度 %d < MIN_OBSERVATIONS=%d, 跳过", len(return_history or []), MIN_OBSERVATIONS)
        return {}

    # 找到一致的"有效长度" = 所有因子与 return_history 都能配对的最小值
    valid_lengths = [len(seq) for seq in factor_history.values()]
    effective_len = min(min(valid_lengths), len(return_history))
    if effective_len < MIN_OBSERVATIONS:
        logger.debug("[FactorIC] 配对后有效长度 %d < MIN_OBSERVATIONS=%d, 跳过", effective_len, MIN_OBSERVATIONS)
        return {}

    correlation_fn = _spearman_correlation if method_normalized == "spearman" else _pearson_correlation

    # 截断到一致长度
    y_full = [float(v) if _is_finite(v) else float("nan") for v in return_history[:effective_len]]
    cleaned_factors: dict[str, list[float]] = {}
    for name, seq in factor_history.items():
        if not name:
            continue
        cleaned_factors[str(name)] = [float(v) if _is_finite(v) else float("nan") for v in list(seq)[:effective_len]]

    if not cleaned_factors:
        return {}

    # 移除 y 为 NaN 的整列 (与 y 配对的过滤)
    def _drop_unpaired(x: list[float], y: list[float]) -> tuple[list[float], list[float]]:
        xs, ys = [], []
        for xv, yv in zip(x, y, strict=False):
            if _is_finite(xv) and _is_finite(yv):
                xs.append(xv)
                ys.append(yv)
        return xs, ys

    use_rolling = rolling_window is not None and rolling_window > 1 and effective_len >= rolling_window

    results: dict[str, FactorICResult] = {}
    for name, x_full in cleaned_factors.items():
        if use_rolling:
            # Rolling 模式: 在每个 [t, t+window) 上计算 corr, 收集 IC 序列
            ic_values: list[float] = []
            for start in range(0, effective_len - rolling_window + 1):
                x_win = x_full[start : start + rolling_window]
                y_win = y_full[start : start + rolling_window]
                xs, ys = _drop_unpaired(x_win, y_win)
                if len(xs) < MIN_OBSERVATIONS:
                    continue
                ic_values.append(correlation_fn(xs, ys))
            if not ic_values:
                results[name] = _make_insignificant_result(name, n_periods=0, method=method_normalized)
                continue
            ic_mean = sum(ic_values) / len(ic_values)
            ic_std = _safe_stdev(ic_values)
            ir = (ic_mean / ic_std) if ic_std > 0 else 0.0
            positive = sum(1 for v in ic_values if v > 0)
            ic_positive_rate = positive / len(ic_values)
            n_periods = len(ic_values)
        else:
            # 单次模式: 整段配对后计算一个 IC
            xs, ys = _drop_unpaired(x_full, y_full)
            if len(xs) < MIN_OBSERVATIONS:
                results[name] = _make_insignificant_result(name, n_periods=len(xs), method=method_normalized)
                continue
            ic = correlation_fn(xs, ys)
            ic_mean = ic
            ic_std = 0.0  # 单次没有波动
            ir = 0.0
            ic_positive_rate = 1.0 if ic > 0 else 0.0
            n_periods = len(xs)

        significance = classify_significance(ic_mean, ir)
        results[name] = FactorICResult(
            factor_name=name,
            strategy=_extract_strategy(name),
            ic_mean=ic_mean,
            ic_std=ic_std,
            ir=ir,
            ic_positive_rate=ic_positive_rate,
            n_periods=n_periods,
            rank=0,  # 第二轮再赋
            significance=significance,
            method=method_normalized,
        )

    # 排名 — 按 IR 降序, NaN 因子放最后; ic_mean 作为 tiebreaker
    def _sort_key(result: FactorICResult) -> tuple[int, float, float]:
        nan_flag = 1 if not _is_finite(result.ir) else 0
        # nan_flag=0 排在前; ir 降序; ic_mean 降序
        return (nan_flag, -result.ir if _is_finite(result.ir) else 0.0, -abs(result.ic_mean))

    sorted_results = sorted(results.values(), key=_sort_key)
    ranked: dict[str, FactorICResult] = {}
    for idx, result in enumerate(sorted_results, 1):
        ranked[result.factor_name] = FactorICResult(
            factor_name=result.factor_name,
            strategy=result.strategy,
            ic_mean=result.ic_mean,
            ic_std=result.ic_std,
            ir=result.ir,
            ic_positive_rate=result.ic_positive_rate,
            n_periods=result.n_periods,
            rank=idx,
            significance=result.significance,
            method=result.method,
        )
    return ranked


def _make_insignificant_result(name: str, *, n_periods: int, method: str) -> FactorICResult:
    """数据不足的因子 → 返回一个 insignificant 占位 (rank 在第二轮再赋)。"""
    return FactorICResult(
        factor_name=name,
        strategy=_extract_strategy(name),
        ic_mean=0.0,
        ic_std=0.0,
        ir=0.0,
        ic_positive_rate=0.0,
        n_periods=n_periods,
        rank=0,
        significance="insignificant",
        method=method,
    )


# ---------------------------------------------------------------------------
# History extraction — 从 auto_screening_*.json 报告中提取因子面板
# ---------------------------------------------------------------------------


def _parse_date(date_str: str) -> datetime | None:
    """YYYYMMDD / YYYY-MM-DD → datetime; 失败返回 None。"""
    if not date_str:
        return None
    cleaned = str(date_str).replace("-", "").strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        return None
    try:
        return datetime.strptime(cleaned, "%Y%m%d")
    except ValueError:
        return None


def _extract_factor_value(rec: dict[str, Any], factor_name: str) -> float | None:
    """从单条 recommendation 中抽取子因子 confidence 值。

    路径约定: ``strategy_signals.<strategy>.sub_factors.<factor_name>.confidence``
    若子因子不存在或 confidence 非有限数, 返回 None。
    """
    if not isinstance(rec, dict):
        return None
    strategy_signals = rec.get("strategy_signals") or {}
    if not isinstance(strategy_signals, dict):
        return None
    for signal in strategy_signals.values():
        if not isinstance(signal, dict):
            continue
        sub_factors = signal.get("sub_factors") or {}
        if not isinstance(sub_factors, dict):
            continue
        payload = sub_factors.get(factor_name)
        if not isinstance(payload, dict):
            continue
        confidence = payload.get("confidence")
        if _is_finite(confidence):
            try:
                return float(confidence)
            except (TypeError, ValueError):
                continue
    return None


def _load_report_panel(
    report_path: Path,
    known_factors: set[str] | None = None,
) -> dict[str, Any] | None:
    """读取单份 auto_screening 报告, 返回 ``{date, factor_panel, returns_next}``。

    Returns:
        - ``date``  YYYYMMDD
        - ``factor_panel``  ``{ticker: {factor: value}}``
        - ``returns_next``  ``{ticker: t+1_return}`` (来自 tracking_history 跟踪数据, 若可用)

        报告不存在 / 损坏 → None。
    """
    try:
        raw = report_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[FactorIC] 跳过损坏报告 %s: %s", report_path.name, exc)
        return None
    if not isinstance(payload, dict):
        return None

    date_raw = str(payload.get("date", ""))
    parsed_date = _parse_date(date_raw)
    if parsed_date is None:
        return None
    date_str = parsed_date.strftime("%Y%m%d")

    recs = payload.get("recommendations") or []
    if not isinstance(recs, list) or not recs:
        return None

    factor_panel: dict[str, dict[str, float]] = {}
    factor_set: set[str] = set()
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        ticker = str(rec.get("ticker", "")).strip()
        if not ticker:
            continue
        rec_factors: dict[str, float] = {}
        signals = rec.get("strategy_signals") or {}
        if not isinstance(signals, dict):
            continue
        for signal in signals.values():
            if not isinstance(signal, dict):
                continue
            sub_factors = signal.get("sub_factors") or {}
            if not isinstance(sub_factors, dict):
                continue
            for fname, fpayload in sub_factors.items():
                if known_factors is not None and fname not in known_factors:
                    continue
                if not isinstance(fpayload, dict):
                    continue
                conf = fpayload.get("confidence")
                if _is_finite(conf):
                    try:
                        rec_factors[str(fname)] = float(conf)
                    except (TypeError, ValueError):
                        continue
        if rec_factors:
            factor_panel[ticker] = rec_factors
            factor_set.update(rec_factors.keys())

    return {
        "date": date_str,
        "factor_panel": factor_panel,
        "factor_set": factor_set,
    }


def _load_tracking_returns(
    report_dir: Path,
    trade_date: str,
) -> dict[str, float]:
    """从 ``tracking_history.json`` 加载 ``{ticker: t+1_return}`` (按 trade_date 筛选)。"""
    tracking_path = report_dir / "tracking_history.json"
    if not tracking_path.exists():
        return {}
    try:
        raw = tracking_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[FactorIC] tracking_history 读取失败: %s", exc)
        return {}
    if not isinstance(payload, dict):
        return {}
    records = payload.get("records") or payload.get("history") or []
    if not isinstance(records, list):
        return {}
    target_date = trade_date
    returns_map: dict[str, float] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        rec_date = str(rec.get("trade_date", ""))
        if rec_date != target_date:
            continue
        ticker = str(rec.get("ticker", "")).strip()
        if not ticker:
            continue
        # 优先 t+1, 缺失则退回 0
        t1 = rec.get("t1_return")
        if _is_finite(t1):
            try:
                returns_map[ticker] = float(t1)
            except (TypeError, ValueError):
                continue
    return returns_map


def extract_factor_panel_from_history(
    reports_dir: Path,
    lookback_days: int = 30,
    end_date: str | None = None,
    *,
    known_factors: set[str] | None = None,
) -> tuple[dict[str, list[float]], list[float]]:
    """从最近 ``lookback_days`` 天的 ``auto_screening_*.json`` 报告提取因子面板 + 下期收益。

    算法:
      1. 找到 reports_dir 下所有 auto_screening_*.json, 按日期升序
      2. 取 end_date 当天及之前 ``lookback_days`` 天内的报告
      3. 对每份报告, 抽取 ``{ticker: {factor: confidence}}``
      4. **对齐**: 每个因子在每天的"截面均值" → 一天一个值 (cross-section average)
         下期收益 T+1 同样取当天所有 ticker 的均值 — 这是当前最稳定的"市场级"代理
      5. 返回 ``{factor: [v_t0, v_t1, ...]}`` 和 ``[r_t0, r_t1, ...]`` (长度 = 报告数 - 1, 因为最后一天无 T+1)

    Args:
        reports_dir: ``data/reports`` 目录
        lookback_days: 回溯天数
        end_date: 结束日期 YYYYMMDD / YYYY-MM-DD; None = 最新报告日期
        known_factors: 仅提取这些因子 (None = 自动发现)

    Returns:
        ``(factor_panel, returns)`` — 长度对齐, 最后一期无 T+1 自动丢弃
    """
    reports_dir = Path(reports_dir)
    if not reports_dir.exists():
        return {}, []

    # 1. 找到所有匹配的报告
    report_files: list[tuple[datetime, Path]] = []
    for path in reports_dir.glob("auto_screening_*.json"):
        match = _REPORT_FILENAME_PATTERN.match(path.name)
        if not match:
            continue
        date_raw = match.group(1) or match.group(2)
        if not date_raw:
            continue
        parsed = _parse_date(date_raw)
        if parsed is None:
            continue
        report_files.append((parsed, path))

    if not report_files:
        return {}, []

    # 2. 推断 end_date
    if end_date is None:
        end_date = max(dt for dt, _ in report_files).strftime("%Y%m%d")
    end_dt = _parse_date(end_date)
    if end_dt is None:
        return {}, []

    # 3. 过滤窗口
    start_dt = end_dt - timedelta(days=lookback_days - 1)
    in_window = [(dt, p) for dt, p in report_files if start_dt <= dt <= end_dt]
    in_window.sort(key=lambda pair: pair[0])
    if not in_window:
        return {}, []

    # 4. 加载每份报告, 收集 cross-section 均值
    daily_factor_means: dict[str, list[float]] = {}  # factor -> [mean_t0, mean_t1, ...]
    daily_returns: list[float] = []  # [mean_t0_return, mean_t1_return, ...]

    for idx, (dt, path) in enumerate(in_window):
        date_str = dt.strftime("%Y%m%d")
        panel = _load_report_panel(path, known_factors=known_factors)
        if panel is None:
            continue
        factor_panel = panel["factor_panel"]
        if not factor_panel:
            continue
        # cross-section 均值 — 防御空 list
        for fname, values in factor_panel.items():
            for f, v in values.items():
                if not _is_finite(v):
                    continue
                daily_factor_means.setdefault(f, []).append(float(v))
        # T+1 收益: 从 tracking_history 拉 (若有)
        t1_returns = _load_tracking_returns(reports_dir, date_str)
        if t1_returns:
            r_values = [v for v in t1_returns.values() if _is_finite(v)]
            daily_returns.append(sum(r_values) / len(r_values) if r_values else float("nan"))
        else:
            # 无追踪数据 — 用 score_b 的截面均值作为代理 (粗略, 但能产生可计算序列)
            score_b_values: list[float] = []
            try:
                recs = json.loads(path.read_text(encoding="utf-8")).get("recommendations", [])
                for rec in recs:
                    if not isinstance(rec, dict):
                        continue
                    sb = rec.get("score_b")
                    if _is_finite(sb):
                        try:
                            score_b_values.append(float(sb))
                        except (TypeError, ValueError):
                            continue
            except (OSError, json.JSONDecodeError):
                pass
            if score_b_values:
                daily_returns.append(sum(score_b_values) / len(score_b_values))
            else:
                daily_returns.append(0.0)

    # 5. 对齐 — daily_factor_means 可能与 daily_returns 长度不同 (部分日期无数据); 截到最短
    if not daily_factor_means or not daily_returns:
        return {}, []
    common_len = min(len(daily_returns), *(len(seq) for seq in daily_factor_means.values()))
    if common_len < MIN_OBSERVATIONS:
        return {}, []

    aligned_factors: dict[str, list[float]] = {f: seq[:common_len] for f, seq in daily_factor_means.items()}
    aligned_returns = daily_returns[:common_len]
    return aligned_factors, aligned_returns


# ---------------------------------------------------------------------------
# Rendering — 中文 CLI 表格
# ---------------------------------------------------------------------------


_STRATEGY_CN_LABELS: dict[str, str] = {
    "trend": "趋势",
    "mean_reversion": "均值回归",
    "fundamental": "基本面",
    "event_sentiment": "事件情绪",
    "unknown": "未分类",
}

_SIGNIFICANCE_CN_LABELS: dict[str, str] = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "insignificant": "无",
}


def render_factor_ic_ranking(
    results: dict[str, FactorICResult],
    *,
    end_date: str | None = None,
    lookback_days: int = 30,
) -> str:
    """渲染中文文本排行表 (按 IR 降序)。

    Args:
        results: ``compute_factor_ic`` 的输出
        end_date: 报告日期 (用于表头)
        lookback_days: 回溯窗口 (用于表头)

    Returns:
        多行字符串, 含空数据降级信息
    """
    if not results:
        header_date = end_date or datetime.now().strftime("%Y%m%d")
        return f"━━━ 因子重要性排行 · {header_date} · 近 {lookback_days} 天 ━━━\n\n无可用因子 (数据不足或未运行 --auto)\n"

    header_date = end_date or datetime.now().strftime("%Y%m%d")
    lines: list[str] = []
    lines.append(f"━━━ 因子重要性排行 · {header_date} · 近 {lookback_days} 天 ━━━")
    lines.append("")

    # 按 rank 升序
    ordered = sorted(results.values(), key=lambda r: r.rank if r.rank > 0 else 10**9)

    header = f"{'排名':<4} | {'因子名':<22} | {'策略':<8} | {'IC':<7} | {'IR':<6} | {'胜率':<6} | {'显著性':<5}"
    lines.append(header)
    lines.append("-" * len(header))
    for r in ordered:
        ir_display = f"{r.ir:.2f}" if _is_finite(r.ir) and r.ir != 0 else "—"
        rank_display = f"{r.rank:>2d}" if r.rank > 0 else "—"
        strategy_cn = _STRATEGY_CN_LABELS.get(r.strategy, r.strategy)
        sig_cn = _SIGNIFICANCE_CN_LABELS.get(r.significance, r.significance)
        win_rate = f"{r.ic_positive_rate * 100:.0f}%" if r.ic_positive_rate else "—"
        lines.append(
            f"{rank_display:<4} | {r.factor_name:<22} | {strategy_cn:<8} | "
            f"{r.ic_mean:+.3f}  | {ir_display:<6} | {win_rate:<6} | {sig_cn:<5}"
        )

    lines.append("")
    high_count = sum(1 for r in results.values() if r.significance == "high")
    medium_count = sum(1 for r in results.values() if r.significance == "medium")
    insig_count = sum(1 for r in results.values() if r.significance == "insignificant")
    lines.append(f"按 IR 降序排列, 共 {len(results)} 个因子 (高 {high_count} / 中 {medium_count} / 无效 {insig_count})。")
    lines.append("前 1/3 建议保留; 后 1/3 建议淘汰; 无效因子在下次回测中可考虑移除。")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI entry — run_factor_ic (从 src/main.py 调用)
# ---------------------------------------------------------------------------


def run_factor_ic(lookback_days: int = 30, method: str = "spearman") -> int:
    """P1-4 因子 IC 分析 CLI 入口。

    Args:
        lookback_days: 回溯天数 (默认 30)
        method: "spearman" (默认) 或 "pearson"

    Returns:
        退出码 (0 = 成功, 1 = 数据不足)
    """
    from colorama import Fore, Style  # lazy import — 让主模块在无 colorama 环境也可 import

    from src.screening.consecutive_recommendation import resolve_report_dir

    report_dir = resolve_report_dir()
    if not report_dir.exists():
        print(f"{Fore.RED}[FactorIC] 未找到 reports 目录: {report_dir}{Style.RESET_ALL}")
        return 1

    factor_panel, returns = extract_factor_panel_from_history(
        reports_dir=report_dir,
        lookback_days=lookback_days,
    )
    if not factor_panel or not returns:
        print(f"{Fore.YELLOW}[FactorIC] 历史数据不足 (需要至少 {MIN_OBSERVATIONS} 天的 auto_screening 报告){Style.RESET_ALL}")
        print(f"  reports_dir: {report_dir}")
        return 1

    results = compute_factor_ic(
        factor_history=factor_panel,
        return_history=returns,
        method=method,
    )
    if not results:
        print(f"{Fore.YELLOW}[FactorIC] 计算失败 — 因子数 < {MIN_FACTORS} 或对齐后有效长度不足{Style.RESET_ALL}")
        return 1

    # 推断报告日期
    end_date = datetime.now().strftime("%Y%m%d")
    report_files = sorted(report_dir.glob("auto_screening_*.json"), reverse=True)
    if report_files:
        match = _REPORT_FILENAME_PATTERN.match(report_files[0].name)
        if match:
            date_raw = match.group(1) or match.group(2)
            parsed = _parse_date(date_raw)
            if parsed is not None:
                end_date = parsed.strftime("%Y%m%d")

    output = render_factor_ic_ranking(results, end_date=end_date, lookback_days=lookback_days)
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Factor IC] 因子重要性排行 (P1-4){Style.RESET_ALL}")
    print(f"  reports_dir: {Fore.WHITE}{report_dir}{Style.RESET_ALL}")
    print(f"  lookback: {lookback_days} 天  |  method: {method}")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")
    print(output, end="")
    return 0


__all__ = [
    "FactorICResult",
    "MIN_OBSERVATIONS",
    "MIN_FACTORS",
    "classify_significance",
    "compute_factor_ic",
    "extract_factor_panel_from_history",
    "render_factor_ic_ranking",
    "run_factor_ic",
]
