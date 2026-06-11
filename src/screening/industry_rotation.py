"""行业轮动信号 — 计算申万一级行业的动量和强度排名。

P1-2: 用户向的功能 — 从 ``--auto`` 推荐结果中提取行业维度信号，
帮助用户快速了解当前哪个行业最强、哪个最弱。

设计原则:
- **不调用外部 API** — 所有数据从 ``recommendations`` 参数中获取
- **不依赖时序数据** — 5 日动量等价于方向 (direction) * 置信度 (confidence) 加权
- **小样本剔除** — candidate_count < 2 的行业不出现在排名中
- **稳定排序** — momentum_score 相同时使用 (avg_score_b, candidate_count) 字典序

典型用法:

    from src.screening.industry_rotation import calculate_industry_rotation

    signals = calculate_industry_rotation(
        recommendations=top_results_serializable,
        trade_date=trade_date,
    )
    for s in signals[:5]:
        print(f"#{s.rank} {s.industry_name} momentum={s.momentum_score:+.1f}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.utils.numeric import coerce_score_b as _safe_score_b

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: 最低候选数门槛 — 候选数 < 此值的行业不出现在最终排名中
#: (样本太少不具代表性)
MIN_CANDIDATES_PER_INDUSTRY: int = 2

#: 评分方向映射 — 各 strategy 的 direction 字段取值 ∈ {-1, 0, +1}
#: momentum_score 公式: avg(direction_i * confidence_i) over all candidates
#: confidence 范围: 0 ~ 100

#: 默认未分类行业名 (industry_sw 缺失时归入)
UNKNOWN_INDUSTRY: str = "未知"


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class IndustrySignal:
    """单个行业的轮动信号。

    Attributes:
        industry_name: 申万一级行业名 (或自定义标签)
        industry_code: 行业代码 (如果可用；当前为 ``""``)
        momentum_score: 动量得分 (-100 ~ +100)；正值=强势，负值=弱势
        avg_score_b: 该行业候选标的的平均 score_b (-1 ~ +1)
        candidate_count: 该行业在候选池中的标的数
        north_money_flow: 北向资金净流入 (亿元, 可选 — 当前未实现)
        rank: 排名 (1=最强)
        history_presence_ratio: 历史出现率 (0.0 ~ 1.0, P5-2)
        history_avg_score_b: 历史平均 score_b (P5-2)
        history_bonus: 历史加分 (P5-2)
    """

    industry_name: str
    industry_code: str = ""
    momentum_score: float = 0.0
    avg_score_b: float = 0.0
    candidate_count: int = 0
    north_money_flow: float = 0.0
    rank: int = 0
    tickers: list[str] = field(default_factory=list)
    history_presence_ratio: float = 0.0
    history_avg_score_b: float = 0.0
    history_bonus: float = 0.0

    def to_dict(self) -> dict:
        """序列化为 dict (用于 JSON payload)。"""
        return {
            "industry_name": self.industry_name,
            "industry_code": self.industry_code,
            "momentum_score": round(self.momentum_score, 4),
            "avg_score_b": round(self.avg_score_b, 4),
            "candidate_count": self.candidate_count,
            "north_money_flow": round(self.north_money_flow, 4),
            "rank": self.rank,
            "tickers": list(self.tickers),
            "history_presence_ratio": round(self.history_presence_ratio, 4),
            "history_avg_score_b": round(self.history_avg_score_b, 4),
            "history_bonus": round(self.history_bonus, 4),
        }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------




def _extract_momentum_from_signal(signal: object) -> float:
    """从单个 ``strategy_signals`` 字典条目中提取动量贡献 (direction * confidence)。

    兼容 ``StrategySignal`` Pydantic 模型和普通 dict。

    Returns:
        direction * confidence, 其中 direction ∈ {-1, 0, +1}, confidence ∈ [0, 100].
        范围: -100 ~ +100.
    """
    if signal is None:
        return 0.0
    if isinstance(signal, dict):
        direction = signal.get("direction", 0)
        confidence = signal.get("confidence", 0)
    else:
        direction = getattr(signal, "direction", 0)
        confidence = getattr(signal, "confidence", 0)

    try:
        direction_i = int(direction) if direction is not None else 0
    except (TypeError, ValueError):
        direction_i = 0
    # 截断到 {-1, 0, +1} 防止异常数据
    direction_i = max(-1, min(1, direction_i))

    try:
        conf_f = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        conf_f = 0.0
    if math.isnan(conf_f) or math.isinf(conf_f):
        conf_f = 0.0
    conf_f = max(0.0, min(100.0, conf_f))

    return direction_i * conf_f


def _aggregate_momentum(recommendation: dict) -> float:
    """聚合单个推荐结果的 4 策略动量 → momentum_score。

    算法: 对 (trend, mean_reversion, fundamental, event_sentiment) 4 策略
    的 (direction * confidence) 求和, 然后除以 4 归一化到 [-100, +100]。

    缺策略 / 缺字段时按 0 处理, 不会抛出异常。

    Note:
        与 ``calculate_industry_rotation`` 中的行业聚合不同 — 这里
        给出的是**单标的**层面的归一化动量 (范围 [-100, +100])，
        行业级 momentum_score 是各候选的**算术平均**。
    """
    signals_obj = recommendation.get("strategy_signals") or {}
    if hasattr(signals_obj, "items"):
        items = list(signals_obj.items())
    else:
        return 0.0

    if not items:
        return 0.0

    total = 0.0
    for _name, sig in items:
        total += _extract_momentum_from_signal(sig)
    # 求和后除以策略数, 归一化到 [-100, +100]
    return total / max(1, len(items))


def _resolve_industry_name(recommendation: dict) -> str:
    """提取 industry_sw 字段。空字符串 / None / 缺失 → 返回 "未知" (但调用方会剔除)。"""
    industry = recommendation.get("industry_sw")
    if industry is None:
        return ""
    return str(industry).strip()


def _load_historical_reports(reports_dir: str, trade_date: str, lookback_days: int) -> list[dict]:
    """加载历史自动筛选报告 (P5-2)。
    
    Args:
        reports_dir: 报告目录路径
        trade_date: 当前交易日 (YYYYMMDD)
        lookback_days: 回看天数, lookback_days=1 时返回空列表
    
    Returns:
        历史报告列表, 按日期升序排列, 不包含当前日期。
        每个报告为 dict, 至少包含 "date" 和 "recommendations" 字段。
    """
    import json
    import os
    from datetime import datetime, timedelta
    
    if lookback_days <= 1:
        return []
    
    if not reports_dir or not os.path.exists(reports_dir):
        return []
    
    # 将 trade_date 转换为 datetime
    try:
        current_date = datetime.strptime(trade_date, "%Y%m%d")
    except (ValueError, TypeError):
        return []
    
    # 收集历史报告
    historical_reports = []
    for i in range(1, lookback_days):  # 排除当前日期
        past_date = current_date - timedelta(days=i)
        past_date_str = past_date.strftime("%Y%m%d")
        report_path = os.path.join(reports_dir, f"auto_screening_{past_date_str}.json")
        
        if os.path.exists(report_path):
            try:
                with open(report_path, encoding="utf-8") as f:
                    report = json.load(f)
                    if isinstance(report, dict) and "recommendations" in report:
                        report["date"] = past_date_str
                        historical_reports.append(report)
            except (json.JSONDecodeError, IOError):
                continue
    
    # 按日期升序排列
    historical_reports.sort(key=lambda r: r.get("date", ""))
    return historical_reports


def _compute_industry_history(historical_reports: list[dict]) -> dict[str, dict]:
    """从历史报告计算各行业的历史统计 (P5-2)。
    
    Args:
        historical_reports: 历史报告列表
    
    Returns:
        dict[industry_name, {"presence_count": int, "score_b_sum": float, "score_b_count": int}]
    """
    industry_history: dict[str, dict] = {}
    
    for report in historical_reports:
        recommendations = report.get("recommendations", [])
        # 按行业分组
        industries_in_report = set()
        industry_scores: dict[str, list[float]] = {}
        
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            industry = _resolve_industry_name(rec)
            if not industry or industry == UNKNOWN_INDUSTRY:
                continue
            
            industries_in_report.add(industry)
            score_b = _safe_score_b(rec.get("score_b"))
            industry_scores.setdefault(industry, []).append(score_b)
        
        # 更新统计
        for industry in industries_in_report:
            if industry not in industry_history:
                industry_history[industry] = {"presence_count": 0, "score_b_sum": 0.0, "score_b_count": 0}
            industry_history[industry]["presence_count"] += 1
            
            scores = industry_scores.get(industry, [])
            if scores:
                industry_history[industry]["score_b_sum"] += sum(scores) / len(scores)
                industry_history[industry]["score_b_count"] += 1
    
    return industry_history


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def calculate_industry_rotation(
    recommendations: list[dict],
    trade_date: str,
    lookback_days: int = 5,
    min_candidates: int = MIN_CANDIDATES_PER_INDUSTRY,
    reports_dir: str = "",
) -> list[IndustrySignal]:
    """从推荐结果列表计算行业轮动信号。

    Args:
        recommendations: 推荐结果列表, 每项至少包含:
            - ``industry_sw``: 申万行业名 (str, 缺则归 "未知" 并在最终排名中剔除)
            - ``score_b``: 融合得分 (float, 范围 [-1, +1])
            - ``strategy_signals``: dict, 每个 strategy 含 direction / confidence
            - ``ticker`` (可选, 用于展示和 to_dict 序列化)
        trade_date: 交易日期 (YYYYMMDD)
        lookback_days: 回看天数, lookback_days=1 时不使用历史数据 (P5-2)。
            当前按历史报告的日历日文件名回看, 非交易日会自然跳过。
        min_candidates: 最低候选数门槛, 候选数 < 此值不出现在排名中
        reports_dir: 报告目录路径 (P5-2), 为空时使用默认路径

    Returns:
        按 ``momentum_score`` 降序排列的 ``IndustrySignal`` 列表。
        若 ``recommendations`` 为空 / 所有行业候选数均 < ``min_candidates``,
        返回空列表。

    排序规则 (momentum_score 相同时, 按以下字典序稳定排序):
        1. avg_score_b 降序
        2. candidate_count 降序
        3. industry_name 升序 (中文 locale 无关 — 简单字符串排序, 确定性)
    """
    if not recommendations:
        return []

    # Step 0: 加载历史报告 (P5-2)
    import os
    if not reports_dir:
        reports_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "reports")
        reports_dir = os.path.abspath(reports_dir)
    
    historical_reports = _load_historical_reports(reports_dir, trade_date, lookback_days)
    industry_history = _compute_industry_history(historical_reports)
    history_days_considered = len(historical_reports)

    # Step 1: 按行业分组
    industry_groups: dict[str, list[dict]] = {}
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        industry = _resolve_industry_name(rec)
        # industry_sw 缺失归入 "未知" 组, 但最终排名会剔除
        if not industry:
            industry = UNKNOWN_INDUSTRY
        industry_groups.setdefault(industry, []).append(rec)

    if not industry_groups:
        return []

    # Step 2: 行业级聚合
    signals: list[IndustrySignal] = []
    for industry_name, recs in industry_groups.items():
        candidate_count = len(recs)
        # 行业缺失 → 排除
        if industry_name == UNKNOWN_INDUSTRY:
            continue
        # 样本数过少 → 排除
        if candidate_count < min_candidates:
            continue

        score_b_values: list[float] = []
        momentum_values: list[float] = []
        tickers: list[str] = []
        for rec in recs:
            score_b_values.append(_safe_score_b(rec.get("score_b")))
            momentum_values.append(_aggregate_momentum(rec))
            ticker = rec.get("ticker")
            if ticker is not None and str(ticker).strip():
                tickers.append(str(ticker))

        # 行业动量 = 各候选动量的算术平均 (范围 [-100, +100])
        avg_momentum = sum(momentum_values) / max(1, len(momentum_values))
        avg_score_b = sum(score_b_values) / max(1, len(score_b_values))

        # P5-2: 计算历史信号
        history_presence_ratio = 0.0
        history_avg_score_b = 0.0
        history_bonus = 0.0
        
        if industry_name in industry_history and history_days_considered > 0:
            hist = industry_history[industry_name]
            history_presence_ratio = hist["presence_count"] / history_days_considered
            if hist["score_b_count"] > 0:
                history_avg_score_b = hist["score_b_sum"] / hist["score_b_count"]
            history_bonus = history_presence_ratio * 10.0 + history_avg_score_b * 10.0

        # 最终 momentum_score 包含历史加分
        final_momentum_score = avg_momentum + history_bonus

        signals.append(
            IndustrySignal(
                industry_name=industry_name,
                momentum_score=final_momentum_score,
                avg_score_b=avg_score_b,
                candidate_count=candidate_count,
                tickers=tickers,
                history_presence_ratio=history_presence_ratio,
                history_avg_score_b=history_avg_score_b,
                history_bonus=history_bonus,
            )
        )

    if not signals:
        return []

    # Step 3: 排序 — momentum_score 降序, 稳定字典序
    # momentum_score → avg_score_b → candidate_count → industry_name
    signals.sort(
        key=lambda s: (
            -s.momentum_score,
            -s.avg_score_b,
            -s.candidate_count,
            s.industry_name,
        )
    )

    # Step 4: 分配 rank
    for idx, sig in enumerate(signals, 1):
        sig.rank = idx

    return signals


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------


def top_strong_industries(signals: list[IndustrySignal], n: int = 5) -> list[IndustrySignal]:
    """从已排序信号中取前 N 个强势行业 (rank 1..N)。"""
    return [s for s in signals if s.rank <= n]


def bottom_weak_industries(signals: list[IndustrySignal], n: int = 3) -> list[IndustrySignal]:
    """从已排序信号中取后 N 个弱势行业。

    注意: "弱势"= momentum_score 最低, 即排名末尾的 N 个。
    """
    if not signals:
        return []
    return list(reversed(signals))[:n]


def format_rotation_block(
    signals: list[IndustrySignal],
    top_n: int = 5,
    bottom_n: int = 3,
    show_history: bool = True,
) -> str:
    """生成适合 CLI 输出的行业轮动文字块。

    Args:
        signals: 行业信号列表
        top_n: 显示前 N 个强势行业
        bottom_n: 显示后 N 个弱势行业
        show_history: 是否显示历史信号 (P5-2)

    Returns:
        多行字符串, 包含"强势行业"和"弱势行业"两个小节。
        若 ``signals`` 为空, 返回提示行。
    """
    if not signals:
        return "无行业轮动信号 (候选数不足)\n"

    lines: list[str] = []
    strong = top_strong_industries(signals, n=top_n)
    weak = bottom_weak_industries(signals, n=bottom_n)
    
    # 检查是否有任何历史数据
    has_history = any(sig.history_bonus > 0 for sig in signals)

    if strong:
        lines.append("强势行业:")
        for sig in strong:
            arrow = "↑"
            base_info = f"  {sig.rank:>2}. {sig.industry_name:<8s} {arrow} {sig.momentum_score:+6.1f}  ({sig.candidate_count}只候选, avg score_b: {sig.avg_score_b:+.2f})"
            if show_history and has_history and sig.history_bonus > 0:
                history_info = f" [历史: 出现率{sig.history_presence_ratio:.0%}, 加分{sig.history_bonus:+.1f}]"
                lines.append(base_info + history_info)
            else:
                lines.append(base_info)

    if weak:
        if lines:
            lines.append("")
        lines.append("弱势行业:")
        for idx, sig in enumerate(weak, 1):
            arrow = "↓"
            base_info = f"  {idx:>2}. {sig.industry_name:<8s} {arrow} {sig.momentum_score:+6.1f} ({sig.candidate_count}只候选, avg score_b: {sig.avg_score_b:+.2f})"
            if show_history and has_history and sig.history_bonus > 0:
                history_info = f" [历史: 出现率{sig.history_presence_ratio:.0%}, 加分{sig.history_bonus:+.1f}]"
                lines.append(base_info + history_info)
            else:
                lines.append(base_info)

    return "\n".join(lines) + "\n"
