"""R6 A/B strategy (loop 30) — profit_aware strategy in compute_selection_profitability_from_loaded.

目标: 给 selection-profitability 诊断加第 5 个策略 ``profit_aware``, 产出 R6 owner
决策包的核心 artifact: 默认 (score_desc) vs profit-aware (按经验 bucket winrate 重排)
在真实历史数据上的 T+5 winrate 对比.

背景 (R6 north-star blocker):
- composite_score 有负预测力 (top-3 winrate 47.3% vs 等权 59.5%, C219 n=7993);
  C219/C225 证明 low-score-bucket T+5 winrate 60% > high-bucket 45% (倒挂).
- owner 决策点 = 是否 flip 默认排序到 --profit-aware. 决策被阻: 现有 4 策略
  (score_desc/score_asc/equal_weight/random_n) 都不含 profit-aware 重排.
- route A (c296) forward-persist 了 profit-aware 键, 但只对未来记录有效.
- 本 slice (route B-lite): 在 compute_selection_profitability_from_loaded 加 profit_aware
  策略, 用 walk-forward per-bucket winrate 在现有 74 天历史上重建排序 — 产出 NOW 的
  directional artifact.

设计决策 (loop 30):
- walk-forward (非 in-sample): 每个 test day D 的 bucket winrate 只用 recommended_date
  严格早于 D 的 mature 记录算 — 无 look-ahead bias (诚实).
- bucket 复用 _score_bucket_local (low<0.30 / mid_low<0.40 / mid_high<0.50 / high≥0.50).
- 桶无先验数据 → 中性 0.5 (退化到 score tiebreaker, 当日无 edge).
- caveat (docstring 披露): 用 overall bucket winrate, 忽略 regime 维度 — 是 live
  profit-aware 键 (bucket×regime) 的近似. 决策级证据仍需 route-A 数据成熟.
- 不改默认前门 (纯诊断策略). verdict 仍比 score_desc vs equal_weight (不变); A/B
  对比 (score_desc vs profit_aware) 由调用侧/render 读取两策略 winrate 差.
"""

from __future__ import annotations

from src.screening.north_star_pnl import compute_selection_profitability_from_loaded


def _inversion_records(n_days: int = 6) -> list[dict]:
    """构造 low-bucket-empirically-outperforms-high-bucket 倒挂数据 (C219/C225 形态).

    每天 4 picks (每桶 1 个, scores 0.20/0.35/0.45/0.60), top_n=1:
    - low-bucket (0.20) 每日 +5% (赢)
    - mid buckets 每日 0%
    - high-bucket (0.60) 每日 -5% (输)
    score_desc 选 high (最高分) → 每日输; profit_aware 选 low (最高先验 winrate) → 赢.
    """
    records: list[dict] = []
    for i in range(n_days):
        day = 20240301 + i
        records.append({"recommended_date": str(day), "recommendation_score": 0.20, "next_5day_return": 5.0})
        records.append({"recommended_date": str(day), "recommendation_score": 0.35, "next_5day_return": 0.0})
        records.append({"recommended_date": str(day), "recommendation_score": 0.45, "next_5day_return": 0.0})
        records.append({"recommended_date": str(day), "recommendation_score": 0.60, "next_5day_return": -5.0})
    return records


def test_profit_aware_strategy_present_in_report() -> None:
    """profit_aware 必须出现在 strategies 里 (A/B 对比的主体)."""
    report = compute_selection_profitability_from_loaded(_inversion_records(), top_n=1, min_days=2)
    strategy_names = [s.strategy for s in report.strategies]
    assert "profit_aware" in strategy_names, f"profit_aware missing; got {strategy_names}"


def test_profit_aware_beats_score_desc_on_inversion() -> None:
    """倒挂数据上, profit_aware (按 bucket winrate 重排) 必须跑赢 score_desc (按原始分).

    这是 R6 A/B 的核心信号: 若模型分有负预测力 (high-bucket 输, low-bucket 赢),
    profit-aware 重排应把胜率从 score_desc 的水平拉上来. walk-forward 让 day 1 退化
    (无先验 → 中性 → score tiebreaker → 同 score_desc 选 high 输), day 2+ 有先验 →
    选 low 赢. 故 profit_aware winrate 严格 > score_desc winrate.
    """
    report = compute_selection_profitability_from_loaded(_inversion_records(n_days=6), top_n=1, min_days=2)
    sd = next(s for s in report.strategies if s.strategy == "score_desc")
    pa = next(s for s in report.strategies if s.strategy == "profit_aware")
    # score_desc 每日选 high-bucket (0.60 最高分) → 每日 -5% → 0% winrate
    assert sd.portfolio_winrate == 0.0, f"score_desc expected 0% on inversion; got {sd.portfolio_winrate}"
    # profit_aware day1 退化 (无先验), day2-6 选 low → 赢 → winrate > 0
    assert pa.portfolio_winrate > sd.portfolio_winrate, f"profit_aware ({pa.portfolio_winrate}) must beat score_desc ({sd.portfolio_winrate}) on inversion"


def test_profit_aware_no_lookahead_day1_uses_no_future_data() -> None:
    """walk-forward 守卫: 第一天 (按日期排序最早) 无任何先验 bucket 数据 →
    profit_aware 当日退化到中性 (不能"预知"未来 bucket winrate).
    用单日数据 (min_days=1): profit_aware 当日选票应与 score_desc 一致 (都退化到 score)."""
    # 单日, 4 picks; profit_aware 无先验 → 退化 score tiebreaker → 同 score_desc
    single_day = [
        {"recommended_date": "20240301", "recommendation_score": 0.20, "next_5day_return": 5.0},
        {"recommended_date": "20240301", "recommendation_score": 0.35, "next_5day_return": 0.0},
        {"recommended_date": "20240301", "recommendation_score": 0.45, "next_5day_return": 0.0},
        {"recommended_date": "20240301", "recommendation_score": 0.60, "next_5day_return": -5.0},
    ]
    report = compute_selection_profitability_from_loaded(single_day, top_n=1, min_days=1)
    sd = next(s for s in report.strategies if s.strategy == "score_desc")
    pa = next(s for s in report.strategies if s.strategy == "profit_aware")
    # 都选 high (0.60): score_desc 因最高分; profit_aware 因无先验退化到 score tiebreaker
    assert sd.portfolio_winrate == pa.portfolio_winrate, f"day-1 no-prior: profit_aware must degrade to score tiebreaker (same as score_desc); " f"got sd={sd.portfolio_winrate} pa={pa.portfolio_winrate}"


def test_render_selection_profitability_line_shows_profit_aware_ab() -> None:
    """render line 必须显示 默认 vs profit-aware A/B (owner 决策信号 = R6 决策包核心).

    倒挂数据上 profit_aware 跑赢 score_desc, render 必须把两者的 winrate 都摆出来
    并标注 profit-aware 的提升 (owner 据此决定是否 flip 默认到 --profit-aware).
    """
    from src.screening.north_star_pnl import render_selection_profitability_line

    report = compute_selection_profitability_from_loaded(_inversion_records(n_days=6), top_n=1, min_days=2)
    line = render_selection_profitability_line(report)
    assert line, "render must produce a line on sufficient data"
    assert "profit-aware" in line.lower() or "profit_aware" in line.lower(), f"render must surface the profit-aware A/B; got: {line!r}"
    sd = next(s for s in report.strategies if s.strategy == "score_desc")
    pa = next(s for s in report.strategies if s.strategy == "profit_aware")
    assert f"{pa.portfolio_winrate:.0%}" in line, f"render must include profit-aware winrate {pa.portfolio_winrate:.0%}; got: {line!r}"
    assert f"{sd.portfolio_winrate:.0%}" in line, f"render must include default (score_desc) winrate {sd.portfolio_winrate:.0%}; got: {line!r}"


def test_render_shows_equal_weight_benchmark_ci() -> None:
    """loop 60 (empirical dogfood on c306 footer): the equal_weight benchmark CI
    must be rendered alongside its point estimate.

    Bug found 2026-07-04 by running render_selection_profitability_line on real
    data (75 days): the line showed "默认 top-3 胜率=48% [36%-60%] ... vs 等权 60%"
    — the model strategy carried a bootstrap CI but the **benchmark it is compared
    against showed a bare point estimate**. This creates a false-precision
    asymmetry: the model looks uncertain (±12pp) while the benchmark looks exact,
    exaggerating the apparent underperformance. On real data score_desc CI
    [37%, 60%] **overlaps** the equal_weight point estimate 60%, so the
    "model_underperforms" verdict is not statistically clean at n=75.

    This is the loop-57 disease class (computed-but-unrendered) recurring on the
    c306 surface: ``test_strategy_results_carry_bootstrap_ci`` proves equal_weight
    CI IS computed, but the render dropped it.

    Fixture: constructed directly with a WIDE non-degenerate equal_weight CI
    [48%, 71%] mirroring real data (n=75), so the bare "60%" cannot trivially
    satisfy a "[X%-Y%]" substring check.
    """
    from src.screening.north_star_pnl import (
        render_selection_profitability_line,
        SelectionProfitabilityReport,
        SelectionStrategyResult,
    )

    def _strat(name: str, wr: float, lo: float, hi: float, median: float = 0.0) -> SelectionStrategyResult:
        return SelectionStrategyResult(
            strategy=name,
            portfolio_winrate=wr,
            mean_return=0.0,
            median_return=median,
            sample_days=75,
            ci_lower=lo,
            ci_upper=hi,
        )

    # Mirror real data (2026-07-04 dogfood): score_desc 48% [37%-60%],
    # equal_weight 60% [48%-71%] (CI overlaps the model's), profit_aware 57% [45%-68%].
    report = SelectionProfitabilityReport(
        has_data=True,
        horizon_field="next_5day_return",
        top_n=3,
        verdict="model_underperforms",
        strategies=(
            _strat("score_desc", 0.48, 0.373, 0.60, median=-0.33),
            _strat("score_asc", 0.63, 0.52, 0.73),
            _strat("equal_weight_all", 0.60, 0.48, 0.71),  # <-- wide CI, non-degenerate
            _strat("random_n", 0.60, 0.48, 0.71),
            _strat("profit_aware", 0.573, 0.453, 0.68, median=0.81),
        ),
    )
    ew = next(s for s in report.strategies if s.strategy == "equal_weight_all")
    line = render_selection_profitability_line(report)
    assert line, "render must produce a line"
    # The benchmark CI must appear — same _ci_bracket format as the model strategies.
    ew_ci_expected = f"[{ew.ci_lower:.0%}-{ew.ci_upper:.0%}]"
    assert ew_ci_expected in line, f"equal_weight benchmark CI {ew_ci_expected} is computed but not rendered — " f"the benchmark the verdict is measured against looks falsely exact next to " f"the model's bracketed CI (false-precision asymmetry). line={line!r}"


def test_strategy_results_carry_bootstrap_ci() -> None:
    """每策略的 SelectionStrategyResult 必须带 bootstrap CI (winrate 不确定性).

    R6 owner 决策需要知道 +9pp lift 是否显著 (CI 是否含 0/是否重叠). n=75 日
    winrate 的正态近似 SE≈5.8%, 12pp 差距约 2σ — 点估计不够, 必须 CI. 复用
    模块现有 _bootstrap_winrate_ci (M12 percentile method).
    """
    report = compute_selection_profitability_from_loaded(_inversion_records(n_days=6), top_n=1, min_days=2)
    for s in report.strategies:
        assert s.ci_lower is not None, f"{s.strategy}: ci_lower must be populated"
        assert s.ci_upper is not None, f"{s.strategy}: ci_upper must be populated"
        # monotonic + in [0,1] + brackets the point estimate
        assert 0.0 <= s.ci_lower <= s.ci_upper <= 1.0, f"{s.strategy}: CI must be monotonic in [0,1]; got [{s.ci_lower}, {s.ci_upper}]"
        assert s.ci_lower <= s.portfolio_winrate <= s.ci_upper, f"{s.strategy}: point {s.portfolio_winrate} must lie in CI [{s.ci_lower}, {s.ci_upper}]"
