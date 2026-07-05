"""P-3 实盘对账 — 预测 vs 实际闭环.

系统产出 delivery_value 预测 (T+30 edge via calibration bucket), 但此前无闭环验证
"预测准不准"。本模块读用户交易日志 (CSV), 对每笔成交找买入日的模型预测 (该 ticker
在买入日报告里的 score_b → 分桶 → 桶 T+30 均收), 对比实际收益 (sell/buy-1),
输出 per-trade 误差 + 聚合 (MAE, 方向准确率)。

这是**realized evidence 路径** — 唯一能把 value_claim 从 delivery_value 升级到
realized_value 的机制 (外部真实结果), 也合法重置 self-gen streak。

交易日志 v1 格式 (CSV, 5 列; 用户可从券商导出适配)::

    ticker,buy_date,buy_price,sell_date,sell_price
    000001,20260101,10.50,20260131,11.20

设计原则:
  - **预测侧用当前 calibration** — 假设用户对账近期交易 vs 当前模型知识 (简化 v1;
    历史 calibration 快照留待后续)。文档化此假设。
  - **buy_date 找该日 auto_screening 报告的 ticker score_b**; 找不到 → unmatched
  - **方向准确率** — predicted 与 actual 同号 (都正/都负) 占比; MAE = 平均 |error|

CLI: ``--reconcile <trade_log.csv>`` (由 src/cli/dispatcher.py 分发)。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.isotonic_calibration import MIN_BUCKET_SAMPLES
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ReconciliationRow:
    """单笔交易的对账结果。"""

    ticker: str
    buy_date: str
    #: 模型预测的 T+30 收益 (买入日 score_b 分桶的 T+30 均收); None = 买入日报告无该 ticker
    predicted_return: float | None = None
    #: R-7: 同分桶的 T+30 中位数预测 (稳健中心, 免异常值); None = 无成熟 T+30
    predicted_return_median: float | None = None
    #: R-5.C: isotonic-calibrated prediction. None when matched trades < 20
    # (insufficient evidence) or when the underlying bucket has no T+30 mean.
    predicted_return_isotonic: float | None = None
    actual_return: float = 0.0  # sell_price/buy_price - 1
    error: float | None = None  # actual - predicted; None when predicted is None
    directional_match: bool | None = None  # sign(predicted) == sign(actual); None when predicted None
    #: c318/autodev-loop-90: median 方向匹配 (sign(predicted_median) == sign(actual)).
    #: 与 directional_match 平行但独立 — 当 mean 被 outlier 拉高/拉低而 median 反向时,
    #: 操作者能看到两个中心方向不一致 (例: 低 bucket mean +5.8% ✓ vs median -2.35% ✗).
    #: None 当 predicted_median is None (无成熟 T+30 样本), 与 directional_match=None 语义对齐.
    directional_match_median: bool | None = None
    #: NS-18/c286: 为什么本笔 unmatched (predicted=None). 区分两种原因让操作者能 self-audit:
    #:   "报告无该标的"      — buy_date 报告里找不到该 ticker (score_b lookup 返回 None)
    #:   "分桶无样本 (X桶)"  — ticker 找到但其 score_b 分桶在 calibration 里 0 mature 样本
    #: None = matched (有预测). 之前两种 unmatched 都显示成裸 "—", 操作者无法区分.
    unmatched_reason: str | None = None


@dataclass
class ReconciliationReport:
    """实盘对账汇总。"""

    rows: list[ReconciliationRow] = field(default_factory=list)
    matched_count: int = 0  # 有预测 + 有实际的 trade 数
    unmatched_count: int = 0  # 买入日报告无该 ticker (predicted=None)
    mae: float | None = None  # 平均绝对误差 (仅 matched, mean-based)
    #: R-7: median-based MAE (用 predicted_return_median). 低于 mae → 中位数是更好的预测中心
    mae_median: float | None = None
    #: R-5.C: isotonic-calibrated MAE (用 predicted_return_isotonic).
    #: None when matched_count < 20 (证据不足, 不强行校准) or no valid pairs.
    mae_isotonic: float | None = None
    #: R-5.C: 是否有足够样本做 isotonic 校准 (matched >= MIN_BUCKET_SAMPLES).
    #: False 时 mae_isotonic 保持 None, 渲染输出"证据不足"诚实标注.
    calibration_sufficient: bool = True
    directional_accuracy: float | None = None  # 方向准确率 (仅 matched, mean-based)
    #: c318/autodev-loop-90: median-based 方向准确率 (用 predicted_return_median 方向).
    #: 与 directional_accuracy 平行 — 当两个中心方向准确率分歧时, 操作者能看到
    #: outlier 对 mean 方向预测的虚高影响. None 当 matched_count=0.
    directional_accuracy_median: float | None = None
    #: NS-22: 完整性警告 (如 unmatched>50% 提示 trade_log 列错位 / 日期未对齐 / 错报告目录)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Trade-log loader (v1 CSV format)
# ---------------------------------------------------------------------------


def _load_trade_log(path: Path) -> list[dict[str, Any]]:
    """读取交易日志 CSV (v1: ticker,buy_date,buy_price,sell_date,sell_price)。

    NS-22: 支持 header-based 列映射 (broker 导出常带额外前导列如 账户/序号,
    纯 positional 解析会静默错位 → 垃圾 MAE)。若首行含可识别 header 关键词
    (中英文), 按表头名映射列索引; 否则回退 positional [0..4] (向后兼容)。

    缺失文件 → 空列表 (优雅降级)。跳过表头与空行。
    """
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []

    # NS-22: header 检测 — 首行含可识别字段名则按表头映射列, 容忍额外前导列
    header_colmap = _resolve_trade_log_columns(rows[0])
    data_start = 1 if header_colmap is not None else 0
    colmap = header_colmap or {"ticker": 0, "buy_date": 1, "buy_price": 2, "sell_date": 3, "sell_price": 4}
    max_idx = max(colmap.values())

    trades: list[dict[str, Any]] = []
    for row in rows[data_start:]:
        if len(row) <= max_idx:
            continue  # 列数不足, 跳过 (不静默错位)
        ticker = row[colmap["ticker"]].strip()
        buy_date = row[colmap["buy_date"]].strip()
        buy_price_raw = row[colmap["buy_price"]].strip()
        sell_date = row[colmap["sell_date"]].strip()
        sell_price_raw = row[colmap["sell_price"]].strip()
        if not ticker or not buy_date:
            continue
        try:
            buy_price = float(buy_price_raw)
            sell_price = float(sell_price_raw)
        except ValueError:
            continue  # 表头残行或格式错
        trades.append(
            {
                "ticker": str(ticker),
                "buy_date": str(buy_date).replace("-", ""),
                "buy_price": buy_price,
                "sell_date": str(sell_date).replace("-", ""),
                "sell_price": sell_price,
            }
        )
    return trades


#: NS-22: 各字段的可识别 header 关键词 (中英文, case-insensitive, substring match)
_HEADER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ticker": ("ticker", "symbol", "代码", "股票代码", "股票"),
    "buy_date": ("buy_date", "buy date", "买入日期", "买入日"),
    "buy_price": ("buy_price", "buy price", "买入价", "买入价格"),
    "sell_date": ("sell_date", "sell date", "卖出日期", "卖出日"),
    "sell_price": ("sell_price", "sell price", "卖出价", "卖出价格"),
}


def _resolve_trade_log_columns(header_row: list[str]) -> dict[str, int] | None:
    """NS-22: 若首行含足量可识别 header 关键词, 返回 字段→列索引 映射; 否则 None。

    要求至少识别出 ticker + buy_price (核心字段), 避免把偶然命中的数据行误判为 header。
    """
    normalized = [str(c).strip().lower() for c in header_row]
    found: dict[str, int] = {}
    for field_name, keywords in _HEADER_KEYWORDS.items():
        for idx, cell in enumerate(normalized):
            if any(kw in cell for kw in keywords):
                found[field_name] = idx
                break
    # 核心字段必须命中才视为 header (sell_date/sell_price 未命中时用 positional 默认)
    if "ticker" in found and "buy_price" in found:
        found.setdefault("buy_date", 1)
        found.setdefault("sell_date", 3)
        found.setdefault("sell_price", 4)
        return found
    return None


# ---------------------------------------------------------------------------
# Prediction-side helpers
# ---------------------------------------------------------------------------


def _score_b_on_date(history: list[dict[str, Any]], ticker: str, date_str: str) -> float | None:
    """Find the ticker's score_b in the auto_screening report on date_str.

    history is load_auto_screening_history output (newest-first).
    Returns None if the ticker isn't in that date's report.
    """
    for item in history:
        if str(item.get("date", "")).replace("-", "") != date_str:
            continue
        payload = item.get("payload", {}) or {}
        recs = payload.get("recommendations") or []
        for rec in recs:
            if str(rec.get("ticker", "")) == ticker:
                try:
                    return float(rec.get("score_b", 0.0))
                except (TypeError, ValueError):
                    return None
        return None  # report found for date, but ticker not in it
    return None


def _predicted_t30(score_b: float, calibration) -> float | None:  # calibration: CalibrationSummary
    """Look up the model's predicted T+30 return for a score_b via bucket avg."""
    from src.screening.confidence_calibration import _find_bucket

    bucket_info = _find_bucket(score_b)
    if bucket_info is None:
        return None
    label = bucket_info[0]
    for b in calibration.buckets:
        if b.label == label:
            return b.t30_avg_return
    return None


def _predicted_t30_median(score_b: float, calibration) -> float | None:  # calibration: CalibrationSummary
    """Look up the model's predicted T+30 return for a score_b via bucket MEDIAN.

    R-7: companion to :func:`_predicted_t30` (which uses the outlier-fragile
    arithmetic mean). Uses the bucket's ``t30_median_return`` (R-6) so a single
    extreme winner (e.g. 688008 +112%) doesn't inflate the predicted edge.
    Reconcile surfaces both centers; if median-MAE < mean-MAE, the robust center
    is the better predictor.
    """
    from src.screening.confidence_calibration import _find_bucket

    bucket_info = _find_bucket(score_b)
    if bucket_info is None:
        return None
    label = bucket_info[0]
    for b in calibration.buckets:
        if b.label == label:
            return b.t30_median_return
    return None


# ---------------------------------------------------------------------------
# Core reconciliation
# ---------------------------------------------------------------------------


def compute_reconciliation(
    *,
    trade_log_path: Path,
    reports_dir: Path | None = None,
) -> ReconciliationReport:
    """对账交易日志 vs 模型预测 (当前 calibration)。

    Args:
        trade_log_path: 交易日志 CSV 路径 (v1 5-列格式)
        reports_dir: 报告目录 (None 时用 ``resolve_report_dir()``)

    Returns:
        :class:`ReconciliationReport`
    """
    from src.screening.confidence_calibration import compute_calibration
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        load_tracking_history,
        resolve_report_dir,
    )
    from src.screening.isotonic_calibration import (
        apply_isotonic,
        fit_isotonic,
        is_bucket_insufficient,
    )

    search_dir = reports_dir or resolve_report_dir()
    trades = _load_trade_log(trade_log_path)
    if not trades:
        return ReconciliationReport()

    # Current calibration (v1 assumption: reconcile against current model knowledge)
    tracking_records = load_tracking_history(search_dir)
    calibration = compute_calibration(tracking_records)

    history = load_auto_screening_history(lookback_days=60, report_dir=search_dir)

    rows: list[ReconciliationRow] = []
    matched = 0
    unmatched = 0
    abs_errors: list[float] = []
    abs_errors_median: list[float] = []
    directional_hits = 0
    # R-5.C: collect (predicted, actual) pairs for isotonic fit.
    # Delayed until after the loop so we can decide sufficiency once.
    iso_pairs: list[tuple[float, float]] = []

    # c318: median-direction hits (parallel to mean-direction directional_hits)
    directional_hits_median = 0

    for trade in trades:
        ticker = trade["ticker"]
        buy_date = trade["buy_date"]
        buy_price = trade["buy_price"]
        sell_price = trade["sell_price"]
        # actual return in PERCENT to match calibration's t30_avg_return convention
        actual = (sell_price / buy_price - 1.0) * 100.0 if buy_price else 0.0

        score_b = _score_b_on_date(history, ticker, buy_date)
        predicted = _predicted_t30(score_b, calibration) if score_b is not None else None
        # R-7: median-based prediction (robust center). Computed even when mean is
        # available, so both centers surface per row; matched/MAE keyed on mean
        # (preserves existing contract — median is a parallel diagnostic).
        predicted_median = _predicted_t30_median(score_b, calibration) if score_b is not None else None
        # NS-18/c286: 确定 unmatched 原因 (predicted is None 的两种情况).
        # score_b is None → buy_date 报告无该标的; score_b 有但 predicted None →
        # 该 score_b 分桶在 calibration 里 0 mature 样本 (dogfood 20260702: 600000
        # score_b=0.7 落 中高 桶, 该桶 0 样本). 区分让操作者能 self-audit 裸 "—".
        from src.screening.confidence_calibration import (
            _find_bucket as _find_cal_bucket,
        )

        if score_b is None:
            _unmatched_reason: str | None = "报告无该标的"
        elif predicted is None:
            _bucket_info = _find_cal_bucket(score_b)
            _bucket_label = _bucket_info[0] if _bucket_info is not None else "未知"
            _unmatched_reason = f"分桶无样本 ({_bucket_label})"
        else:
            _unmatched_reason = None

        if predicted is not None:
            matched += 1
            error = actual - predicted
            abs_errors.append(abs(error))
            if predicted_median is not None:
                abs_errors_median.append(abs(actual - predicted_median))
            dmatch = (predicted > 0) == (actual > 0)
            if dmatch:
                directional_hits += 1
            # c318: median-direction match (parallel to mean-direction dmatch).
            # 仅当 predicted_median 有值才计算; 否则 None (与 directional_match=None
            # 当 predicted=None 语义对齐). 当 mean 被 outlier 拉高/拉低而 median
            # 反向时, dmatch_median 会与 dmatch 分歧 — 这是操作者需要看到的信号.
            dmatch_median: bool | None = None
            if predicted_median is not None:
                dmatch_median = (predicted_median > 0) == (actual > 0)
                if dmatch_median:
                    directional_hits_median += 1
            rows.append(
                ReconciliationRow(
                    ticker=ticker,
                    buy_date=buy_date,
                    predicted_return=predicted,
                    predicted_return_median=predicted_median,
                    actual_return=actual,
                    error=error,
                    directional_match=dmatch,
                    directional_match_median=dmatch_median,
                )
            )
            # collect pair for isotonic fit (predicted → actual)
            iso_pairs.append((predicted, actual))
        else:
            unmatched += 1
            rows.append(
                ReconciliationRow(
                    ticker=ticker,
                    buy_date=buy_date,
                    predicted_return=None,
                    predicted_return_median=predicted_median,
                    actual_return=actual,
                    error=None,
                    directional_match=None,
                    directional_match_median=None,
                    unmatched_reason=_unmatched_reason,
                )
            )

    mae = (sum(abs_errors) / len(abs_errors)) if abs_errors else None
    mae_median = (sum(abs_errors_median) / len(abs_errors_median)) if abs_errors_median else None
    directional_accuracy = (directional_hits / matched) if matched else None
    # c318: median 方向准确率 (matched 笔中 median 方向命中比例).
    directional_accuracy_median = (directional_hits_median / matched) if matched else None

    # R-5.C #3 + #4: isotonic calibration with n<20 honest "证据不足" gate.
    # 只有 matched >= MIN_BUCKET_SAMPLES 才拟合保序回归; 否则保持 mae_isotonic=None,
    # 在渲染输出"证据不足"标注, 不假装校准有效.
    mae_isotonic: float | None = None
    calibration_sufficient = not is_bucket_insufficient(matched, MIN_BUCKET_SAMPLES)
    if calibration_sufficient and iso_pairs:
        # fit on (predicted, actual) — xs are predicted returns, ys are actuals.
        # PAV finds the monotone mapping that best explains actuals given predicts;
        # a calibrated prediction at the low end should not exceed one at the high end.
        xs = [p[0] for p in iso_pairs]
        ys = [p[1] for p in iso_pairs]
        iso_model = fit_isotonic(xs, ys, min_samples=MIN_BUCKET_SAMPLES)
        if not iso_model.insufficient:
            calibrated = apply_isotonic(iso_model, xs)
            abs_errors_isotonic = [abs(a - c) if c is not None else 0.0 for a, c in zip(ys, calibrated)]
            # only count rows where calibration produced a value
            valid = [c is not None for c in calibrated]
            if any(valid):
                mae_isotonic = sum(abs_errors_isotonic[i] for i, v in enumerate(valid) if v) / sum(valid)
            # backfill per-row calibrated predictions for transparency
            for row, cal in zip(rows, calibrated):
                if row.predicted_return is not None and cal is not None:
                    row.predicted_return_isotonic = cal

    # NS-22: 完整性警告 — 未匹配 >50% 提示 trade_log 可能列错位/日期未对齐/错报告目录
    warnings: list[str] = []
    total = matched + unmatched
    if total >= 4 and unmatched / total > 0.5:
        warnings.append(f"未匹配率 {unmatched}/{total} > 50% — 检查 trade_log 列对齐 (broker 导出前导列)、" "buy_date 与报告日期对齐、reports_dir 是否正确; 高未匹配率下的 MAE/方向准确率不可信")
    # R-5.C #4: 诚实标注 — matched < 20 → isotonic 不可信, 明确告知用户
    if not calibration_sufficient:
        warnings.append(f"匹配交易 {matched} < {MIN_BUCKET_SAMPLES} — 证据不足, isotonic 校准未执行; " f"收集更多交易后再比较 MAE(保序). 当前 MAE/MAE(中位) 仅供参考, 样本量小不可定论")

    return ReconciliationReport(
        rows=rows,
        matched_count=matched,
        unmatched_count=unmatched,
        mae=mae,
        mae_median=mae_median,
        mae_isotonic=mae_isotonic,
        calibration_sufficient=calibration_sufficient,
        directional_accuracy=directional_accuracy,
        directional_accuracy_median=directional_accuracy_median,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_reconciliation(report: ReconciliationReport) -> str:
    """渲染实盘对账结果 (per-trade 表 + 聚合统计)。"""
    if not report.rows:
        return f"\n{Fore.CYAN}🧾 实盘对账 (预测 vs 实际){Style.RESET_ALL}\n  无交易日志数据\n"

    lines = [f"\n{Fore.CYAN}🧾 实盘对账 (预测 vs 实际){Style.RESET_ALL}", ""]
    # c318: 加 `方向(中位)` 列 — 与 `方向` (mean-based) 平行, 让操作者看到两个中心
    # 方向是否一致. 当 mean ✓ 但 median ✗ (outlier 拉高 mean) 时, 操作者能立即识别
    # mean 方向预测的虚高, 而不是误以为模型方向判断正确.
    lines.append(f"  {'标的':<8} {'买入日':<10} {'预测T+30':>9} {'中位T+30':>9} {'实际':>9} {'误差':>9}  {'方向':>5} {'方向(中位)':>9}")
    lines.append(f"  {'─' * 8} {'─' * 10} {'─' * 9} {'─' * 9} {'─' * 9} {'─' * 9}  {'─' * 5} {'─' * 9}")

    for row in report.rows:
        # values stored in PERCENT (match calibration t30_avg_return convention)
        pred = f"{row.predicted_return:+.1f}%" if row.predicted_return is not None else "—"
        # c287: per-row median prediction (R-7 robust center). 低 bucket dogfood
        # 实测 mean +5.8% vs median -2.35% — mean 被 outlier 拉高, 大多数低分票实际
        # 亏钱. 之前 median 只在 aggregate MAE(中位) 出现, 数据行只显示 mean, 操作者
        # 误读"低分桶预测 +5.8%". 现 per-row 列出中位让操作者看到 outlier 影响.
        pred_med = f"{row.predicted_return_median:+.1f}%" if row.predicted_return_median is not None else "—"
        act = f"{row.actual_return:+.1f}%"
        if row.error is not None:
            err = f"{row.error:+.1f}%"
        else:
            err = "—"
        if row.directional_match is None:
            dstr = "—"
        elif row.directional_match:
            dstr = f"{Fore.GREEN}✓{Style.RESET_ALL}"
        else:
            dstr = f"{Fore.RED}✗{Style.RESET_ALL}"
        # c318: median-direction ✓/✗ (parallel to mean-direction dstr above).
        # None when predicted_median is None (无成熟 T+30 样本) — 显示 "—" 与 mean
        # unmatched 行对齐. 注意 ANSI color 长度不计入显示宽度, f-string >5/>9 用
        # 实际字符长度 (✓/✗ 各 1 字符 + ANSI reset), 因此显示对齐正常.
        if row.directional_match_median is None:
            dstr_med = "—"
        elif row.directional_match_median:
            dstr_med = f"{Fore.GREEN}✓{Style.RESET_ALL}"
        else:
            dstr_med = f"{Fore.RED}✗{Style.RESET_ALL}"
        # NS-18/c286: unmatched 行附原因 (区分 报告无该标的 / 分桶无样本), 让操作者
        # 能 self-audit 裸 "—". matched 行不附 (保持紧凑).
        reason_str = ""
        if row.predicted_return is None and row.unmatched_reason:
            reason_str = f"  {Fore.YELLOW}({row.unmatched_reason}){Style.RESET_ALL}"
        lines.append(f"  {row.ticker:<8} {row.buy_date:<10} {pred:>9} {pred_med:>9} {act:>9} {err:>9}  {dstr:>5} {dstr_med:>9}{reason_str}")

    lines.append("")
    if report.matched_count:
        mae_str = f"{report.mae:.1f}%" if report.mae is not None else "—"
        mae_median_str = f"{report.mae_median:.1f}%" if report.mae_median is not None else "—"
        # R-5.C #4: 诚实标注 — matched < 20 时 MAE(保序) 显示"证据不足"而非 0 或 —
        # 明确告知用户当前样本量不够, 不要把保序校准的缺失误读为"无改善".
        if report.calibration_sufficient:
            mae_iso_str = f"{report.mae_isotonic:.1f}%" if report.mae_isotonic is not None else "—"
        else:
            mae_iso_str = f"{Fore.YELLOW}证据不足 (<{MIN_BUCKET_SAMPLES}笔){Style.RESET_ALL}"
        da_str = f"{report.directional_accuracy * 100:.0f}%" if report.directional_accuracy is not None else "—"
        # c318: median 方向准确率 (parallel to mean-based da_str).
        da_med_str = f"{report.directional_accuracy_median * 100:.0f}%" if report.directional_accuracy_median is not None else "—"
        # R-7 + R-5.C: 三中心 MAE 并列 — mean / median / isotonic.
        # mean: 现有 baseline; median: 抗 outlier; isotonic: 单调校准后.
        # 用户可自行比较哪个 MAE 最低, 即为该数据集上最佳预测中心.
        # c318: 同时并列 mean/median 方向准确率 — 当 median 方向准确率 > mean 时,
        # 说明 outlier 干扰了 mean 方向预测, median 是更稳的方向信号.
        lines.append(f"  {Fore.CYAN}聚合:{Style.RESET_ALL} 对账 {report.matched_count} 笔" f" (未匹配 {report.unmatched_count})  |  MAE={mae_str}  |  MAE(中位)={mae_median_str}" f"  |  MAE(保序)={mae_iso_str}  |  方向准确率={da_str}  |  方向准确率(中位)={da_med_str}")
    else:
        lines.append(f"  {Fore.YELLOW}无匹配交易 (买入日报告未含日志中的标的){Style.RESET_ALL}")

    # R-5.C #4: 把"证据不足"警告以显著方式再次展示 (除了 warnings 列表, 聚合行也提示)
    if not report.calibration_sufficient and report.matched_count > 0:
        lines.append(f"  {Fore.YELLOW}⚠ isotonic 校准未执行: 匹配交易 {report.matched_count} < " f"{MIN_BUCKET_SAMPLES} 笔, 证据不足. 收集更多交易后再比较 MAE(保序).{Style.RESET_ALL}")

    lines.append(f"  {Fore.WHITE}⚠ 预测侧用当前 calibration (v1 假设); 实际 = sell/buy-1。" f"仅供研究, 不构成投资建议。{Style.RESET_ALL}")
    return "\n".join(lines)


__all__ = [
    "ReconciliationRow",
    "ReconciliationReport",
    "compute_reconciliation",
    "render_reconciliation",
]
