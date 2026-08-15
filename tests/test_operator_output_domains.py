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
    # 计数全缺 → 折叠声明, 而非五连「未知」噪声
    assert "计数不可用" in text
    assert "未知" not in text
    # 阻断必须给出可操作信息: 中文原因 + 原始码 (供日志对照) + 排查入口
    assert "数据护栏阻断新计划" in text
    assert "就绪清单未发布" in text
    assert "readiness_attempt" in text
    assert "处置" in text


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


def test_readiness_block_surfaces_attempt_diagnostics():
    text = render_readiness_block(
        "daily_action_readiness_missing",
        attempt_reasons=("shared_source_capture_failed:ManifestValidationError: security rows must exactly cover frozen universe",),
    )

    assert "数据护栏阻断新计划" in text
    assert "诊断" in text
    assert "shared_source_capture_failed" in text
    assert "security rows must exactly cover frozen universe" in text


def test_readiness_block_without_attempts_keeps_original_shape():
    text = render_readiness_block("daily_action_readiness_missing")

    assert "诊断" not in text
    assert "建议" in text


def test_latest_daily_action_attempt_reasons_reads_newest_attempt(tmp_path):
    import json
    from datetime import date

    from src.cli.dispatcher import _latest_daily_action_attempt_reasons

    older = tmp_path / "daily_action_readiness_attempt_20260717_aaa.json"
    newer = tmp_path / "daily_action_readiness_attempt_20260717_bbb.json"
    older.write_text(json.dumps({"reasons": ["older_reason"]}), encoding="utf-8")
    newer.write_text(json.dumps({"reasons": ["newer_reason"]}), encoding="utf-8")
    other_day = tmp_path / "daily_action_readiness_attempt_20260716_ccc.json"
    other_day.write_text(json.dumps({"reasons": ["other_day_reason"]}), encoding="utf-8")

    import os, time
    now = time.time()
    os.utime(older, (now - 10, now - 10))
    os.utime(newer, (now, now))

    assert _latest_daily_action_attempt_reasons(tmp_path, date(2026, 7, 17)) == ("newer_reason",)
    assert _latest_daily_action_attempt_reasons(tmp_path, date(2026, 7, 18)) == ()


def test_latest_daily_action_attempt_reasons_never_raises(tmp_path):
    from datetime import date

    from src.cli.dispatcher import _latest_daily_action_attempt_reasons

    (tmp_path / "daily_action_readiness_attempt_20260717_broken.json").write_text(
        "not-json", encoding="utf-8"
    )

    assert _latest_daily_action_attempt_reasons(tmp_path, date(2026, 7, 17)) == ()


def test_auto_partial_missing_counts_keep_per_field_display():
    """部分计数缺失时逐字段显示 (缺失位置本身携带"哪个环节没产出"的信息)."""
    text = render_auto_daily_domain_summary(
        auto_status="healthy",
        layer_a_count=300,
        recommendation_count=10,
        daily_readiness={
            "status": "healthy",
            "universe_count": 626,
            "scannable_count": 81,
        },
    )
    assert "全域=626" in text
    assert "可扫描=81" in text
    assert "可计划=未知" in text
    assert "计数不可用" not in text


def test_block_reason_zh_covers_all_pipeline_emitted_codes():
    """渲染词汇表必须覆盖管线能发出的全部运行级阻断码 — fail-closed 回退
    ("数据护栏未通过") 让缺口静默, 此测试把缺口变成红灯.

    码源: dispatcher._resolve_daily_action 的 new_entry_block 赋值点 +
    daily_action_snapshot._load_manifest 的 global_reason 返回值 +
    auto_pipeline._daily_readiness_publication_payload 的 block_reasons.
    """
    from src.screening.offensive.daily_action import _block_reason_zh

    pipeline_codes = (
        # dispatcher._resolve_daily_action
        "entry_window_missed",
        "readiness_snapshot_load_failed",
        "readiness_scan_failed",
        "daily_action_readiness_missing",
        # daily_action_snapshot._load_manifest
        "readiness_manifest_invalid",
        "readiness_schema_unsupported",
        "readiness_date_mismatch",
        "readiness_manifest_not_healthy",
        # auto_pipeline._daily_readiness_publication_payload
        "readiness_attempt",
        # service 层运行级阻断 (drawdown/regime)
        "drawdown_circuit_breaker",
        "regime_gate_halt",
        "regime_authorization_evidence_unavailable",
    )
    for code in pipeline_codes:
        label = _block_reason_zh(code)
        assert label != "数据护栏未通过", f"阻断码 {code} 缺中文标签"
        assert code not in label or "（" in label  # 非 verbose 不泄漏原始码


def test_block_reason_zh_delegates_to_gate_table():
    """manifest 门控码偶经 global_reason 通道到达运行级渲染 — 查找须穿透
    门控表, 不能回退无信息泛化文案."""
    from src.screening.offensive.daily_action import _block_reason_zh

    assert _block_reason_zh("manifest_invalid") == "就绪清单无效"
    assert _block_reason_zh("totally_unknown_code") == "数据护栏未通过"
