"""排序记分牌 (scorecard) 契约测试 — --auto Top10 切片的诚实自评.

设计 (v3 展示层规格, 2026-08-16):
- tracking_history 近期每日只记录 Top10 本身, 无池级对照 → 记分牌的诚实形态
  是切片胜率/均值 + 切片内排序诊断 (日内 Spearman IC + 前3 vs 后7), 而不是
  编造全池基准。
- verdict 三态: positive 需 IC 显著为正且切片均值为正; ic_t <= -2 为 negative;
  其余为 no_positive_evidence; 样本不足时 insufficient, 不给点估计。
- 所有空态必须有确定性渲染文案, 未知不编造。
"""

from __future__ import annotations

import math

from src.screening.scorecard import (
    compute_bucket_stats,
    compute_scorecard,
    format_bucket_header,
    format_scorecard_lines,
)


def _rec(
    date: str,
    score: float,
    t5: float | None,
    ticker: str = "000001",
) -> dict:
    return {
        "ticker": ticker,
        "recommended_date": date,
        "recommendation_score": score,
        "next_5day_return": t5,
    }


def _day(date: str, scores: list[float], t5s: list[float | None]) -> list[dict]:
    """一个推荐日: scores 与 t5s 等长, ticker 按序号生成。"""
    return [
        _rec(date, s, r, ticker=f"{600000 + i}")
        for i, (s, r) in enumerate(zip(scores, t5s))
    ]


# ---------------------------------------------------------------------------
# compute_scorecard — 基本统计
# ---------------------------------------------------------------------------


class TestComputeScorecard:
    def test_basic_stats_and_window(self):
        # 12 个推荐日 × 10 只, 分数与 T+5 收益完全单调同向 → 切片胜率/均值可手算。
        records: list[dict] = []
        for d in range(12):
            date = f"202607{d + 1:02d}"
            scores = [0.40 - 0.01 * i for i in range(10)]
            # 前 5 只盈利 (递减 +6%..+2%), 后 5 只亏损 (递减 -1%..-5%)
            t5s = [6.0, 5.0, 4.0, 3.0, 2.0, -1.0, -2.0, -3.0, -4.0, -5.0]
            records.extend(_day(date, scores, t5s))

        report = compute_scorecard(records, min_mature_dates=10)

        assert report.available is True
        assert report.n_dates == 12
        assert report.n_mature == 120
        assert report.window_start == "20260701"
        assert report.window_end == "20260712"
        assert math.isclose(report.slice_win_rate, 0.5)
        assert math.isclose(report.slice_mean_return, 0.5)  # 均值 = (6+5+4+3+2-1-2-3-4-5)/10
        # 前3 全胜, 后7 = 2 胜 5 负
        assert math.isclose(report.head_win_rate, 1.0)
        assert math.isclose(report.rest_win_rate, 2 / 7)
        # 分数与收益单调同向 → IC = +1
        assert math.isclose(report.mean_daily_ic, 1.0, abs_tol=1e-9)
        assert report.ic_dates == 12

    def test_per_date_pool_records_truncated_to_top_slice(self):
        # 2024 时代的记录每天有 300 只 (全池) — 只有按分数前 10 计入切片。
        day_pool: list[dict] = []
        for i in range(300):
            day_pool.append(_rec("20240315", 0.10 + 0.002 * i, t5=1.0, ticker=f"{i:06d}"))
        # 再加 11 个成熟日, 让窗口达到 min_mature_dates
        records = list(day_pool)
        for d in range(11):
            records.extend(_day(f"202404{d + 1:02d}", [0.40 - 0.01 * i for i in range(10)], [1.0] * 10))

        report = compute_scorecard(records, min_mature_dates=10)

        # 首日 300 条只取分数前 10 → 全胜; 其余 11 日全胜
        assert report.n_mature == 120
        assert math.isclose(report.slice_win_rate, 1.0)

    def test_unmatured_records_excluded(self):
        records: list[dict] = []
        for d in range(12):
            date = f"202607{d + 1:02d}"
            scores = [0.40 - 0.01 * i for i in range(10)]
            t5s = [1.0] * 10 if d < 10 else [None] * 10
            records.extend(_day(date, scores, t5s))

        report = compute_scorecard(records, min_mature_dates=10)

        # 只有 10 个成熟日进窗口, 未成熟的两天被剔除出窗口
        assert report.n_dates == 10
        assert report.n_mature == 100

    def test_insufficient_mature_dates_no_point_estimates(self):
        records = _day("20260701", [0.4, 0.35], [1.0, -1.0]) + _day(
            "20260702", [0.4, 0.35], [1.0, -1.0]
        )

        report = compute_scorecard(records, min_mature_dates=10)

        assert report.available is False
        assert report.verdict == "insufficient"
        assert report.slice_win_rate is None
        assert report.slice_mean_return is None

    def test_empty_records_unavailable(self):
        report = compute_scorecard([])
        assert report.available is False
        assert report.verdict == "insufficient"
        assert report.reason

    def test_verdict_negative_on_consistent_reverse(self):
        # 分数与收益稳定反向 (高分必亏) 12 日 → IC = -1, t 巨大负。
        records: list[dict] = []
        for d in range(12):
            date = f"202607{d + 1:02d}"
            scores = [0.40 - 0.01 * i for i in range(10)]
            t5s = [-6.0, -5.0, -4.0, -3.0, -2.0, 1.0, 2.0, 3.0, 4.0, 5.0]
            records.extend(_day(date, scores, t5s))

        report = compute_scorecard(records, min_mature_dates=10)

        assert report.available is True
        assert report.verdict == "negative"
        assert math.isclose(report.mean_daily_ic, -1.0, abs_tol=1e-9)

    def test_verdict_positive_requires_ic_t_and_mean(self):
        records: list[dict] = []
        for d in range(12):
            date = f"202607{d + 1:02d}"
            scores = [0.40 - 0.01 * i for i in range(10)]
            t5s = [6.0, 5.0, 4.0, 3.0, 2.0, 1.0, -1.0, -2.0, -3.0, -4.0]
            records.extend(_day(date, scores, t5s))

        report = compute_scorecard(records, min_mature_dates=10)

        assert report.verdict == "positive"

    def test_verdict_no_positive_evidence_when_ic_insignificant(self):
        # 单日 IC 交替 +1/-1 → 均 IC = 0、t = 0, 即使切片均值为正也不判 positive。
        records: list[dict] = []
        mono = [6.0, 5.0, 4.0, 3.0, 2.0, 1.0, -1.0, -2.0, -3.0, -4.0]
        for d in range(12):
            date = f"202607{d + 1:02d}"
            scores = [0.40 - 0.01 * i for i in range(10)]
            t5s = mono if d % 2 == 0 else list(reversed(mono))
            records.extend(_day(date, scores, t5s))

        report = compute_scorecard(records, min_mature_dates=10)

        assert math.isclose(report.mean_daily_ic, 0.0, abs_tol=1e-9)
        assert math.isclose(report.ic_t_stat, 0.0, abs_tol=1e-9)
        assert report.slice_mean_return is not None and report.slice_mean_return > 0
        assert report.verdict == "no_positive_evidence"

    def test_window_limited_to_last_n_matured_dates(self):
        records: list[dict] = []
        for d in range(20):
            date = f"202607{d + 1:02d}"
            scores = [0.40 - 0.01 * i for i in range(10)]
            t5s = [1.0] * 10
            records.extend(_day(date, scores, t5s))

        report = compute_scorecard(records, window_dates=5, min_mature_dates=3)

        assert report.n_dates == 5
        assert report.window_start == "20260716"

    def test_tied_scores_do_not_crash_ic(self):
        records: list[dict] = []
        for d in range(12):
            date = f"202607{d + 1:02d}"
            scores = [0.35] * 10  # 全并列
            t5s = [6.0, 5.0, 4.0, 3.0, 2.0, 1.0, -1.0, -2.0, -3.0, -4.0]
            records.extend(_day(date, scores, t5s))

        report = compute_scorecard(records, min_mature_dates=10)

        # 全并列 → 秩方差为 0 → IC 定义为 0, 不崩溃
        assert report.mean_daily_ic == 0.0


# ---------------------------------------------------------------------------
# compute_bucket_stats — 桶头钱数 (单一 T+5 口径)
# ---------------------------------------------------------------------------


class TestComputeBucketStats:
    def test_bucket_stats_with_payoff(self):
        records = [
            # 桶 较低 (0.3-0.4): 3 胜 (均 +6%) 2 负 (均 -4%) → 赔率 6/4 = 1.5
            _rec("20260701", 0.35, 6.0, "000001"),
            _rec("20260701", 0.33, 6.0, "000002"),
            _rec("20260701", 0.32, 6.0, "000003"),
            _rec("20260701", 0.31, -4.0, "000004"),
            _rec("20260701", 0.30, -4.0, "000005"),
            # 桶 低 (0.4-0.5): 1 胜 1 负
            _rec("20260701", 0.45, 2.0, "000006"),
            _rec("20260701", 0.42, -2.0, "000007"),
        ]

        stats = compute_bucket_stats(records)

        low = stats["较低 (0.3-0.4)"]
        assert low.n_mature == 5
        assert math.isclose(low.win_rate, 0.6)
        assert math.isclose(low.mean_return, 2.0)
        assert math.isclose(low.avg_win, 6.0)
        assert math.isclose(low.avg_loss, -4.0)
        assert math.isclose(low.payoff, 1.5)

        lo = stats["低 (0.4-0.5)"]
        assert lo.n_mature == 2
        assert math.isclose(lo.payoff, 1.0)

        # 没有记录的桶不出现
        assert "高 (>0.8)" not in stats

    def test_bucket_no_mature_stats_none(self):
        stats = compute_bucket_stats([_rec("20260701", 0.35, None)])

        low = stats["较低 (0.3-0.4)"]
        assert low.n_mature == 0
        assert low.win_rate is None
        assert low.mean_return is None
        assert low.payoff is None

    def test_all_losses_payoff_none(self):
        stats = compute_bucket_stats(
            [_rec("20260701", 0.35, -3.0), _rec("20260701", 0.33, -5.0)]
        )

        low = stats["较低 (0.3-0.4)"]
        assert low.avg_win is None  # 无盈利笔 → 赔率未定义
        assert low.payoff is None
        assert math.isclose(low.avg_loss, -4.0)

    def test_score_outside_all_buckets_ignored(self):
        # score_b 越界 (例如 -5) 不属于任何桶 → 不计入
        stats = compute_bucket_stats([_rec("20260701", -5.0, 1.0)])
        assert stats == {}


# ---------------------------------------------------------------------------
# format_* — 确定性文案 (空态矩阵)
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_scorecard_lines_available(self):
        records: list[dict] = []
        for d in range(12):
            date = f"202607{d + 1:02d}"
            records.extend(
                _day(date, [0.40 - 0.01 * i for i in range(10)], [6.0, 5.0, 4.0, 3.0, 2.0, 1.0, -1.0, -2.0, -3.0, -4.0])
            )
        report = compute_scorecard(records, min_mature_dates=10)

        lines = format_scorecard_lines(report)

        joined = "\n".join(lines)
        assert "胜率" in joined and "IC" in joined
        assert "前3" in joined
        assert "未扣费" in joined  # 冷读收口: 毛收益口径必须自明
        assert "--daily-action" in joined  # 边界声明常驻

    def test_scorecard_lines_insufficient_discloses(self):
        report = compute_scorecard(_day("20260701", [0.4], [1.0]), min_mature_dates=10)

        lines = format_scorecard_lines(report)

        assert len(lines) == 1
        assert "样本不足" in lines[0]

    def test_scorecard_lines_empty_records(self):
        report = compute_scorecard([])
        lines = format_scorecard_lines(report)
        assert any("不可用" in ln for ln in lines)

    def test_verdict_wording_per_state(self):
        mono = [6, 5, 4, 3, 2, 1, -1, -2, -3, -4]

        def _mk(t5s: list[float]) -> list[dict]:
            records: list[dict] = []
            for d in range(12):
                date = f"202607{d + 1:02d}"
                records.extend(
                    _day(date, [0.40 - 0.01 * i for i in range(10)], t5s)
                )
            return records

        pos = format_scorecard_lines(compute_scorecard(_mk(mono), min_mature_dates=10))
        assert any("正向证据" in ln for ln in pos)

        neg = format_scorecard_lines(
            compute_scorecard(_mk(list(reversed(mono))), min_mature_dates=10)
        )
        assert any("反向" in ln for ln in neg)

        # 交替正反 IC → 均值 IC=0 → 无正向证据
        alternating: list[dict] = []
        for d in range(12):
            alternating.extend(
                _day(
                    f"202607{d + 1:02d}",
                    [0.40 - 0.01 * i for i in range(10)],
                    mono if d % 2 == 0 else list(reversed(mono)),
                )
            )
        neutral = format_scorecard_lines(compute_scorecard(alternating, min_mature_dates=10))
        assert any("无正向证据" in ln for ln in neutral)

    def test_bucket_header_full_low_sample_and_null(self):
        # n=2 < 5 → 不给点估计 (样本不足)
        low_n = compute_bucket_stats(
            [_rec("20260701", 0.35, 6.0), _rec("20260701", 0.31, -4.0)]
        )
        header_low_n = format_bucket_header(low_n["较低 (0.3-0.4)"])
        assert "样本不足" in header_low_n
        assert "胜率" not in header_low_n

        # 5 <= n < 20 → 点估计 + ⚠少样本
        enough = [_rec("20260701", 0.35, 6.0 if i % 2 == 0 else -4.0) for i in range(6)]
        mid_n = compute_bucket_stats(enough)
        header_mid = format_bucket_header(mid_n["较低 (0.3-0.4)"])
        assert "胜率" in header_mid and "赔率" in header_mid
        assert "未扣费" in header_mid  # 均值是毛收益, 扣费判断读者自己能做
        assert "少样本" in header_mid

        null_header = format_bucket_header(
            type(low_n["较低 (0.3-0.4)"])(
                label="高 (>0.8)", window_start=None, window_end=None,
                n_records=0, n_mature=0, win_rate=None, mean_return=None,
                avg_win=None, avg_loss=None, payoff=None,
            )
        )
        assert "不提供估计" in null_header
