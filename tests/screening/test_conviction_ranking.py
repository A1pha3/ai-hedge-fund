"""测试 src.screening.conviction_ranking (P0-11)。"""

from __future__ import annotations

import pytest

from src.screening.confidence_calibration import CalibrationSummary, ScoreBucketStats, compute_calibration
from src.screening.conviction_ranking import (
    CONSECUTIVE_FULL_STREAK,
    DEFAULT_WEIGHTS,
    ConvictionSummary,
    _component_str,
    _conviction_color,
    _normalize_calibration,
    _normalize_completeness,
    _normalize_consecutive,
    _normalize_score,
    _rank_delta_str,
    compute_conviction_ranking,
    compute_conviction_row,
    render_conviction_ranking,
)
from src.screening.data_quality_audit import STRATEGY_ORDER
from src.utils.display import Fore, Style


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def test_normalize_score_clamps():
    assert _normalize_score(0.5) == 0.5
    assert _normalize_score(1.5) == 1.0
    assert _normalize_score(-0.5) == 0.0


def test_normalize_consecutive_boundaries():
    """streak=1 → 0.0 (首次出现, 无连续信号)。"""
    assert _normalize_consecutive(1) == 0.0
    assert _normalize_consecutive(0) == 0.0
    assert _normalize_consecutive(CONSECUTIVE_FULL_STREAK) == 1.0
    assert _normalize_consecutive(CONSECUTIVE_FULL_STREAK + 5) == 1.0  # 上限封顶


def test_normalize_consecutive_intermediate():
    """streak=2 → 0.5 (中等置信)。"""
    assert _normalize_consecutive(2) == pytest.approx(0.5, abs=1e-3)


def test_normalize_completeness_clamps():
    assert _normalize_completeness(0.7) == 0.7
    assert _normalize_completeness(1.5) == 1.0
    assert _normalize_completeness(-0.1) == 0.0


def test_normalize_calibration_none_is_neutral():
    """无样本时 calibration 视为中性 0.5 (不奖不罚)。"""
    assert _normalize_calibration(None) == 0.5


def test_normalize_calibration_clamps():
    assert _normalize_calibration(0.65) == 0.65
    assert _normalize_calibration(1.5) == 1.0
    assert _normalize_calibration(-0.2) == 0.0


# ---------------------------------------------------------------------------
# compute_conviction_row
# ---------------------------------------------------------------------------


def _make_rec(ticker: str, score: float, completeness: float = 0.8, consecutive_days: int = 1, name: str = "测试") -> dict:
    """构造测试 recommendation dict。"""
    return {
        "ticker": ticker,
        "name": name,
        "industry_sw": "电子",
        "score_b": score,
        "consecutive_days": consecutive_days,
        "strategy_signals": {
            s: {"direction": 1, "confidence": 80.0, "completeness": completeness, "sub_factors": {}}
            for s in STRATEGY_ORDER
        },
        "metrics": {},
    }


def _empty_calibration() -> CalibrationSummary:
    """无样本的校准数据。"""
    return compute_calibration([])


def _calibration_with_bucket(bucket_label_substring: str, win_rate: float, count: int = 5) -> CalibrationSummary:
    """构造一个指定桶有样本的校准数据。"""
    summary = compute_calibration([])
    for b in summary.buckets:
        if bucket_label_substring in b.label:
            b.sample_count = count
            b.t5_win_rate = win_rate
    return summary


def test_compute_conviction_row_basic():
    rec = _make_rec("000001", 0.8, completeness=0.9, consecutive_days=3)
    row = compute_conviction_row(rec, original_rank=1, calibration=_empty_calibration())
    assert row.ticker == "000001"
    assert row.original_rank == 1
    assert row.score_component == pytest.approx(0.8, abs=1e-3)
    assert row.consecutive_component == 1.0  # streak=3 → 满分
    assert row.quality_component == pytest.approx(0.9, abs=1e-3)
    assert row.calibration_component == 0.5  # 无样本 → 中性


def test_compute_conviction_row_calibration_applied():
    """有校准数据时 calibration 分量应反映桶命中率。"""
    rec = _make_rec("000001", 0.85)  # 落入"高"桶
    calib = _calibration_with_bucket("高", win_rate=0.7)
    row = compute_conviction_row(rec, original_rank=1, calibration=calib)
    assert row.calibration_component == pytest.approx(0.7, abs=1e-3)
    assert "高" in row.bucket_label
    assert row.bucket_t5_win_rate == 0.7


def test_compute_conviction_row_consecutive_one_is_zero():
    """streak=1 (首次推荐) → consecutive 分量为 0。"""
    rec = _make_rec("000001", 0.8, consecutive_days=1)
    row = compute_conviction_row(rec, original_rank=1, calibration=_empty_calibration())
    assert row.consecutive_component == 0.0


def test_compute_conviction_row_consecutive_zero_preserved_not_silently_replaced():
    """streak=0 (R20.26-A regression): `int(rec.get("consecutive_days") or 1)` 把合法的 0
    静默替换为 1, 导致 row.consecutive_days 元数据错误。consecutive_component 仍是 0
    (因为 _normalize_consecutive 把 <=1 都归零), 但 row.consecutive_days 必须保留输入值 0。
    """
    rec = _make_rec("000001", 0.8, consecutive_days=0)
    row = compute_conviction_row(rec, original_rank=1, calibration=_empty_calibration())
    assert row.consecutive_component == 0.0
    assert row.consecutive_days == 0  # 必须保留 0, 不能被 `or 1` 替换为 1


def test_compute_conviction_row_score_in_conviction_range():
    """conviction_score 应在 0-100 范围。"""
    rec = _make_rec("000001", 0.7)
    row = compute_conviction_row(rec, original_rank=1, calibration=_empty_calibration())
    assert 0.0 <= row.conviction_score <= 100.0


def test_compute_conviction_row_higher_score_higher_conviction():
    """其他条件相同时, score 越高 conviction 越高。"""
    rec_low = _make_rec("000001", 0.5, completeness=0.8, consecutive_days=2)
    rec_high = _make_rec("000002", 0.9, completeness=0.8, consecutive_days=2)
    calib = _empty_calibration()
    row_low = compute_conviction_row(rec_low, original_rank=1, calibration=calib)
    row_high = compute_conviction_row(rec_high, original_rank=2, calibration=calib)
    assert row_high.conviction_score > row_low.conviction_score


def test_compute_conviction_row_low_quality_reduces_conviction():
    """低数据质量应降低 conviction。"""
    rec_good = _make_rec("000001", 0.75, completeness=0.9)
    rec_bad = _make_rec("000002", 0.75, completeness=0.3)
    calib = _empty_calibration()
    row_good = compute_conviction_row(rec_good, original_rank=1, calibration=calib)
    row_bad = compute_conviction_row(rec_bad, original_rank=2, calibration=calib)
    assert row_good.conviction_score > row_bad.conviction_score


# ---------------------------------------------------------------------------
# compute_conviction_ranking
# ---------------------------------------------------------------------------


def test_compute_conviction_ranking_empty():
    rows = compute_conviction_ranking([], calibration=_empty_calibration())
    assert rows == []


def test_compute_conviction_ranking_sorts_by_conviction_desc():
    """结果应按 conviction_score 降序。"""
    recs = [
        _make_rec("000001", 0.7, completeness=0.9, consecutive_days=3),  # 高 conviction
        _make_rec("000002", 0.9, completeness=0.3, consecutive_days=1),  # 低 conviction (差质量)
        _make_rec("000003", 0.8, completeness=0.8, consecutive_days=2),  # 中
    ]
    rows = compute_conviction_ranking(recs, calibration=_empty_calibration())
    assert rows[0].conviction_score >= rows[1].conviction_score >= rows[2].conviction_score


def test_compute_conviction_ranking_fills_ranks():
    recs = [_make_rec(f"{i:06d}", 0.7 + i * 0.01) for i in range(3)]
    rows = compute_conviction_ranking(recs, calibration=_empty_calibration())
    assert [r.conviction_rank for r in rows] == [1, 2, 3]


def test_compute_conviction_ranking_rank_delta_computed():
    """rank_delta = conviction_rank - original_rank。"""
    # 让 quality 反转排序: 高分低质量 vs 低分高质量
    recs = [
        _make_rec("000001", 0.9, completeness=0.3, consecutive_days=1),  # original_rank=1
        _make_rec("000002", 0.6, completeness=0.9, consecutive_days=3),  # original_rank=2
    ]
    rows = compute_conviction_ranking(recs, calibration=_empty_calibration())
    # 检查 rank_delta 计算正确
    for row in rows:
        assert row.rank_delta == row.conviction_rank - row.original_rank


def test_compute_conviction_ranking_top_n_limit():
    recs = [_make_rec(f"{i:06d}", 0.7) for i in range(5)]
    rows = compute_conviction_ranking(recs, calibration=_empty_calibration(), top_n=3)
    assert len(rows) == 3


def test_compute_conviction_ranking_custom_weights():
    """自定义权重应生效: score=1.0 权重 → 高分票 conviction 更高。"""
    recs = [
        _make_rec("000001", 0.5, completeness=0.9, consecutive_days=3),
        _make_rec("000002", 0.9, completeness=0.3, consecutive_days=1),
    ]
    # score-only 权重: 第二只票 (0.9) 应排第一
    weights = {"score": 1.0, "consecutive": 0.0, "quality": 0.0, "calibration": 0.0}
    rows = compute_conviction_ranking(recs, calibration=_empty_calibration(), weights=weights)
    assert rows[0].ticker == "000002"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_conviction_ranking_empty():
    summary = ConvictionSummary(date_str="20260609", rows=[])
    out = render_conviction_ranking(summary)
    assert "未找到推荐数据" in out


def test_render_conviction_ranking_with_rows():
    recs = [_make_rec("000001", 0.75, completeness=0.8, consecutive_days=2)]
    rows = compute_conviction_ranking(recs, calibration=_empty_calibration())
    summary = ConvictionSummary(date_str="20260609", rows=rows, has_calibration_data=False)
    out = render_conviction_ranking(summary)
    assert "综合信心排名" in out
    assert "权重" in out
    assert "000001" in out
    assert "无历史校准数据" in out  # has_calibration_data=False


def test_render_conviction_ranking_with_calibration_data():
    """有校准数据时不应显示警告。"""
    recs = [_make_rec("000001", 0.85, completeness=0.8, consecutive_days=2)]
    calib = _calibration_with_bucket("高", win_rate=0.65)
    rows = compute_conviction_ranking(recs, calibration=calib)
    summary = ConvictionSummary(date_str="20260609", rows=rows, has_calibration_data=True)
    out = render_conviction_ranking(summary)
    assert "无历史校准数据" not in out


def test_render_conviction_ranking_promoted_demoted():
    """显示信心提升/下降的标的。"""
    # 反转排序: original #1 → conviction #2
    recs = [
        _make_rec("000001", 0.9, completeness=0.3, consecutive_days=1),
        _make_rec("000002", 0.6, completeness=0.9, consecutive_days=3),
    ]
    rows = compute_conviction_ranking(recs, calibration=_empty_calibration())
    summary = ConvictionSummary(date_str="20260609", rows=rows)
    out = render_conviction_ranking(summary)
    # 至少有一个 ↑ 或 ↓
    assert ("↑" in out) or ("↓" in out)


def test_render_conviction_ranking_weights_displayed():
    recs = [_make_rec("000001", 0.75)]
    rows = compute_conviction_ranking(recs, calibration=_empty_calibration())
    summary = ConvictionSummary(date_str="20260609", rows=rows)
    out = render_conviction_ranking(summary)
    assert "Score 40%" in out
    assert "连续 20%" in out


# ---------------------------------------------------------------------------
# Custom weights via dispatcher (R20.24 — CLI 参数化)
# ---------------------------------------------------------------------------


def test_dispatcher_conviction_ranking_default_weights():
    """未传 --*-weight 时使用默认 (40/20/20/20)。"""
    from src.cli.dispatcher import _resolve_conviction_ranking

    argv = ["--conviction-ranking", "--top-n=3"]
    rc = _resolve_conviction_ranking(argv)
    # 0 = 正常退出; None = 命令未匹配
    assert rc == 0


def test_dispatcher_conviction_ranking_custom_weights_via_kv():
    """--key=value 形式传自定义权重应生效。"""
    from src.cli.dispatcher import _resolve_conviction_ranking

    argv = [
        "--conviction-ranking",
        "--top-n=3",
        "--score-weight=0.30",
        "--consecutive-weight=0.10",
        "--quality-weight=0.10",
        "--calibration-weight=0.50",
    ]
    rc = _resolve_conviction_ranking(argv)
    assert rc == 0


def test_dispatcher_conviction_ranking_rejects_invalid_sum():
    """权重和 != 1.0 应返回错误退出码 2, 不渲染报告。"""
    from src.cli.dispatcher import _resolve_conviction_ranking

    argv = [
        "--conviction-ranking",
        "--score-weight=0.50",
        "--consecutive-weight=0.50",  # sum = 1.0 + default 0.40 calib = 1.40
    ]
    rc = _resolve_conviction_ranking(argv)
    assert rc == 2  # 错误退出码


def test_dispatcher_conviction_ranking_accepts_floating_point_sum():
    """权重和允许 0.99-1.01 浮点误差。"""
    from src.cli.dispatcher import _resolve_conviction_ranking

    argv = [
        "--conviction-ranking",
        "--score-weight=0.25",
        "--consecutive-weight=0.25",
        "--quality-weight=0.25",
        "--calibration-weight=0.25",  # sum = 1.00, 应被接受
    ]
    rc = _resolve_conviction_ranking(argv)
    assert rc == 0


def test_run_conviction_ranking_uses_custom_weights():
    """run_conviction_ranking 接收 weights 参数, 反映在 ConvictionSummary 中。"""
    from src.screening.conviction_ranking import (
        compute_conviction_ranking as _compute_cr,
    )
    from src.screening.confidence_calibration import compute_calibration as _cc

    recs = [_make_rec("000001", 0.8, completeness=0.9, consecutive_days=3)]
    # 自定义: 100% 给 score (其他都 0)
    custom = {"score": 1.0, "consecutive": 0.0, "quality": 0.0, "calibration": 0.0}
    calib = _cc([])
    rows = _compute_cr(recs, calibration=calib, weights=custom)
    # 100% score → conviction_score 应等于 score_b (0.8) × 100 = 80
    assert rows[0].conviction_score == pytest.approx(80.0, abs=0.1)


# ---------------------------------------------------------------------------
# Direct unit tests for rendering helpers (was 0 direct coverage)
# ---------------------------------------------------------------------------


class TestComponentStr:
    """_component_str — 0-1 value → 5-cell mini bar with color."""

    def test_full_bar_at_value_1(self) -> None:
        result = _component_str(1.0)
        assert "▌" * 5 in result
        assert "·" not in result

    def test_empty_bar_at_value_0(self) -> None:
        result = _component_str(0.0)
        assert "·" * 5 in result
        assert "▌" not in result

    def test_half_bar(self) -> None:
        result = _component_str(0.5)
        assert "▌" * 2 in result  # round(0.5*5) = round(2.5) = 2
        assert "·" * 3 in result

    def test_high_value_uses_green(self) -> None:
        result = _component_str(0.8)
        assert result.startswith(Fore.GREEN)

    def test_mid_value_uses_yellow(self) -> None:
        result = _component_str(0.5)
        assert result.startswith(Fore.YELLOW)

    def test_low_value_uses_red(self) -> None:
        result = _component_str(0.1)
        assert result.startswith(Fore.RED)

    def test_ends_with_reset(self) -> None:
        assert _component_str(0.5).endswith(Style.RESET_ALL)

    def test_clamps_above_range(self) -> None:
        # value > 1 should clamp to 5 filled cells
        result = _component_str(2.0)
        assert "▌" * 5 in result

    def test_clamps_below_range(self) -> None:
        # negative value should clamp to 0 filled cells
        result = _component_str(-0.5)
        assert "·" * 5 in result


class TestConvictionColor:
    """_conviction_color — score → color constant."""

    def test_high_score_green(self) -> None:
        assert _conviction_color(80) == Fore.GREEN

    def test_boundary_75_green(self) -> None:
        assert _conviction_color(75) == Fore.GREEN

    def test_mid_score_yellow(self) -> None:
        assert _conviction_color(65) == Fore.YELLOW

    def test_boundary_60_yellow(self) -> None:
        assert _conviction_color(60) == Fore.YELLOW

    def test_low_score_red(self) -> None:
        assert _conviction_color(50) == Fore.RED

    def test_zero_red(self) -> None:
        assert _conviction_color(0) == Fore.RED


class TestRankDeltaStr:
    """_rank_delta_str — rank delta → colored arrow string."""

    def test_negative_delta_green_up_arrow(self) -> None:
        # delta < 0 means rank improved (e.g. 5→3)
        result = _rank_delta_str(-2)
        assert Fore.GREEN in result
        assert "↑2" in result

    def test_positive_delta_red_down_arrow(self) -> None:
        # delta > 0 means rank worsened (e.g. 3→5)
        result = _rank_delta_str(3)
        assert Fore.RED in result
        assert "↓3" in result

    def test_zero_delta_yellow_dash(self) -> None:
        result = _rank_delta_str(0)
        assert Fore.YELLOW in result
        assert "—" in result

    def test_all_end_with_reset(self) -> None:
        assert _rank_delta_str(-1).endswith(Style.RESET_ALL)
        assert _rank_delta_str(1).endswith(Style.RESET_ALL)
        assert _rank_delta_str(0).endswith(Style.RESET_ALL)
