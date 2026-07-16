from __future__ import annotations

from src.screening.offensive.daily_action import render_degraded_only, render_no_signal, render_readiness_block
from src.main import render_auto_daily_domain_summary


def test_default_output_distinguishes_three_no_plan_states():
    assert "系统健康，今日无信号" in render_no_signal()
    assert "仅供诊断的残缺 setup" in render_degraded_only()
    assert "数据护栏阻断新计划" in render_readiness_block()


def test_auto_default_output_separates_auto_and_daily_readiness_and_treats_regime_auth_as_disclosure():
    text = render_auto_daily_domain_summary(
        auto_status="healthy",
        layer_a_count=300,
        recommendation_count=10,
        daily_readiness={
            "status": "healthy",
            "universe_count": 626,
            "scannable_count": 81,
            "plan_eligible_count": 7,
            "degraded_count": 4,
            "block_reasons": ("regime_authorization_evidence_unavailable",),
        },
    )

    assert "Auto 评分状态" in text
    assert "Daily Action 就绪状态" in text
    assert "候选池=300" in text
    assert "推荐=10" in text
    assert "可扫描=81" in text
    assert "可计划=7" in text
    assert "残缺诊断=4" in text
    assert "10% 仓位披露" in text
    assert "致命阻断" not in text
    assert "regime_authorization_evidence_unavailable" not in text


def test_auto_attempt_output_is_clear_chinese_and_does_not_infer_cache_counts():
    text = render_auto_daily_domain_summary(
        auto_status="healthy",
        layer_a_count=300,
        recommendation_count=10,
        daily_readiness={
            "status": "blocked",
            "price_total": 652,
            "price_updated": 650,
            "block_reasons": ("readiness_attempt",),
        },
    )

    assert "Auto 评分状态：健康" in text
    assert "Daily Action 就绪状态：未就绪" in text
    assert "数据护栏阻断新计划" in text
    assert "全域=0" in text
    assert "可扫描=0" in text
    assert "readiness_attempt" not in text


def test_auto_verbose_output_may_include_raw_readiness_codes():
    text = render_auto_daily_domain_summary(
        auto_status="healthy",
        layer_a_count=300,
        recommendation_count=10,
        daily_readiness={
            "status": "blocked",
            "block_reasons": ("readiness_attempt",),
        },
        verbose=True,
    )

    assert "readiness_attempt" in text
