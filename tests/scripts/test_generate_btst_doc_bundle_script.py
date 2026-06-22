from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_doc_bundle import (
    _build_forbidden_semantics_hits,
    _build_semantic_conflicts,
    _group_rows_by_allowed_sections,
    _render_action_matrix_sections,
    _render_llm_doc,
    compare_btst_doc_bundle_profiles,
    generate_btst_doc_bundle,
)


def _write_json(path: Path, payload: object) -> None:
    """Write one JSON fixture file for the document-bundle test."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_render_action_matrix_sections_escapes_markdown_table_cells() -> None:
    """Keep dynamic action-matrix text from breaking Markdown tables."""
    lines = _render_action_matrix_sections(
        [
            {
                "ticker": "300054",
                "name": "鼎龙股份",
                "action_matrix": [
                    {
                        "scenario": "强势|确认",
                        "action": "先等确认\n再执行",
                    }
                ],
            }
        ]
    )

    rendered = "\n".join(lines)

    assert "| 股票 | 场景 | 动作 |" in rendered
    assert "| 300054 鼎龙股份 | 强势\\|确认 | 先等确认<br>再执行 |" in rendered
    assert "强势\\|确认" in rendered
    assert "先等确认<br>再执行" in rendered


def test_render_action_matrix_sections_confirmation_review_only_uses_confirmation_title() -> None:
    """Confirmation-review checklist should not reuse the formal-execution action-matrix title."""
    lines = _render_action_matrix_sections(
        [
            {
                "ticker": "300054",
                "name": "鼎龙股份",
                "action_matrix": [],
            }
        ],
        report_mode="confirmation_review_only",
    )

    rendered = "\n".join(lines)

    assert "## 确认复核动作矩阵" in rendered
    assert "## 正式执行动作矩阵" not in rendered
    assert "| 股票 | 场景 | 动作 |" in rendered


def test_build_semantic_conflicts_checks_allowed_sections_in_confirmation_review_mode() -> None:
    """Quality QA should flag confirmation-mode rows that keep formal sections."""
    conflicts = _build_semantic_conflicts(
        report_mode="confirmation_review_only",
        rows=[
            {
                "ticker": "300054",
                "name": "鼎龙股份",
                "report_mode": "confirmation_review_only",
                "role": "formal_selected",
                "trade_bias": "trade_allowed",
                "execution_state": "confirmable",
                "max_allowed_state_today": "confirmable",
                "formal_buy_allowed": False,
                "allowed_sections": ["formal_queue"],
            }
        ],
    )

    assert "300054 鼎龙股份:expected_allowed_sections=review_queue" in conflicts


def test_build_semantic_conflicts_checks_confirmation_only_state_in_formal_execution_mode() -> None:
    """Formal-execution QA should validate confirmation-only selected rows beyond trade_allowed."""
    conflicts = _build_semantic_conflicts(
        report_mode="formal_execution",
        rows=[
            {
                "ticker": "300476",
                "name": "胜宏科技",
                "report_mode": "formal_execution",
                "role": "formal_selected",
                "trade_bias": "confirmation_only",
                "execution_state": "confirmable",
                "max_allowed_state_today": "orderable",
                "formal_buy_allowed": False,
                "allowed_sections": ["watch_queue"],
            }
        ],
    )

    assert "300476 胜宏科技:expected_allowed_sections=formal_queue" in conflicts


def test_build_forbidden_semantics_hits_uses_precise_formal_confirmation_markers() -> None:
    """Forbidden-semantics QA should hit precise formal wording, not generic status words."""
    hits = _build_forbidden_semantics_hits(
        signal_date_compact="20260529",
        report_mode="confirmation_review_only",
        docs={
            "BTST-LLM-20260529.md": "## 确认复核队列\n",
            "BTST-20260529-EXEC-CHECKLIST.md": "说明里提到了 orderable，但这不是标题。\n## 正式执行动作矩阵\n- [ ] 正式执行：`300054 鼎龙股份`\n",
        },
    )

    assert hits == [
        "BTST-20260529-EXEC-CHECKLIST.md:## 正式执行动作矩阵",
        "BTST-20260529-EXEC-CHECKLIST.md:- [ ] 正式执行：",
    ]


def test_group_rows_by_allowed_sections_separates_review_watch_and_blocked_rows() -> None:
    """Rendered sections must follow allowed_sections instead of raw selected/watch buckets."""
    grouped_rows = _group_rows_by_allowed_sections(
        [
            {
                "ticker": "300054",
                "name": "鼎龙股份",
                "allowed_sections": ["review_queue"],
            },
            {
                "ticker": "300476",
                "name": "胜宏科技",
                "allowed_sections": ["watch_queue"],
            },
            {
                "ticker": "300999",
                "name": "华润微",
                "allowed_sections": ["blocked_only"],
            },
        ]
    )

    assert grouped_rows["formal_queue"] == []
    assert [row["ticker"] for row in grouped_rows["review_queue"]] == ["300054"]
    assert [row["ticker"] for row in grouped_rows["watch_queue"]] == ["300476"]
    assert [row["ticker"] for row in grouped_rows["blocked_only"]] == ["300999"]


def test_generate_btst_doc_bundle_writes_early_runner_sections(tmp_path: Path) -> None:
    """Generate a compact BTST bundle and verify early-runner sections are included."""
    reports_root = tmp_path / "data" / "reports"
    strategy_thresholds_path = tmp_path / "config" / "btst_strategy_thresholds.json"
    _write_json(
        strategy_thresholds_path,
        {
            "min_recent_exact_streak": 4,
            "min_intersection_positive_days": 3,
            "intersection_uplift_rate_threshold": 0.2,
            "only_early_runner_max_positive_rate": 0.4,
            "second_entry_t2_advantage_threshold": 0.015,
        },
    )
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
            },
            "optimization_profile_resolution": {
                "profile_name": "momentum_optimized",
            },
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "primary_action": {
                "ticker": "300054",
                "name": "鼎龙股份",
                "preferred_entry_mode": "confirm_then_hold_breakout",
            },
            "selected_actions": [
                {
                    "ticker": "300054",
                    "name": "鼎龙股份",
                    "action_tier": "primary_entry",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "score_target": 0.5588,
                    "historical_prior": {
                        "applied_scope": "same_ticker",
                        "evaluable_count": 18,
                        "next_close_positive_rate": 0.6667,
                        "next_close_payoff_ratio": 1.42,
                        "next_close_expectancy": 0.018,
                        "sample_count": 21,
                    },
                }
            ],
            "watch_actions": [
                {
                    "ticker": "300476",
                    "name": "胜宏科技",
                    "action_tier": "watch_only",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "score_target": 0.4308,
                    "historical_prior": {
                        "applied_scope": "same_ticker",
                        "evaluable_count": 31,
                        "next_close_positive_rate": 0.9355,
                        "next_close_payoff_ratio": 2.31,
                        "next_close_expectancy": 0.026,
                        "sample_count": 34,
                    },
                }
            ],
            "opportunity_actions": [],
            "rollout_validation": {
                "status": "governed_shadow_ready",
                "primary_lane": "layer_c_formal_precision_tightening",
                "summary": "先收 formal buy。",
                "selected_hit_rate_15pct": 0.3077,
                "shadow_hit_rate_15pct": 0.3333,
                "execution_eligible_delta": -3,
                "buy_order_delta": -3,
            },
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 3200,
            "selected_count": 780,
            "near_miss_count": 760,
            "high_confidence": [
                {
                    "ticker": "603725",
                    "name": "天安新材",
                    "score": 0.8269,
                    "pct_chg": 5.56,
                }
            ],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [
                {
                    "trade_date": "2026-05-26",
                    "gate_action": "tradeable",
                    "deployment_mode": "shadow_only",
                    "early_runner_watchlist": [
                        {
                            "ticker": "300054",
                            "name": "鼎龙股份",
                            "entry_status": "filled",
                            "pre_score": 0.71,
                            "confirm_score": 0.82,
                            "preferred_entry_mode": "confirm_then_hold_breakout",
                            "historical_prior": {
                                "applied_scope": "same_ticker",
                                "evaluable_count": 18,
                                "next_close_positive_rate": 0.6667,
                                "next_close_payoff_ratio": 1.42,
                                "next_close_expectancy": 0.018,
                                "sample_count": 21,
                            },
                        }
                    ],
                    "early_runner_priority": [
                        {
                            "ticker": "300054",
                            "name": "鼎龙股份",
                            "entry_status": "filled",
                            "pre_score": 0.71,
                            "confirm_score": 0.82,
                            "preferred_entry_mode": "confirm_then_hold_breakout",
                            "historical_prior": {
                                "applied_scope": "same_ticker",
                                "evaluable_count": 18,
                                "next_close_positive_rate": 0.6667,
                                "next_close_payoff_ratio": 1.42,
                                "next_close_expectancy": 0.018,
                                "sample_count": 21,
                            },
                        },
                        {
                            "ticker": "603725",
                            "name": "天安新材",
                            "entry_status": "not_confirmed",
                            "pre_score": 0.66,
                            "confirm_score": 0.41,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "historical_prior": {
                                "applied_scope": "same_ticker",
                                "evaluable_count": 12,
                                "next_close_positive_rate": 0.58,
                                "next_close_payoff_ratio": 1.1,
                                "next_close_expectancy": 0.006,
                                "sample_count": 14,
                            },
                        },
                    ],
                    "second_entry_reentry": [
                        {
                            "ticker": "605500",
                            "name": "森林包装",
                            "entry_status": "watch_only",
                            "pre_score": 0.55,
                            "confirm_score": 0.33,
                            "preferred_entry_mode": "second_entry_reentry",
                            "historical_prior": {
                                "applied_scope": "same_ticker",
                                "evaluable_count": 11,
                                "next_close_positive_rate": 0.54,
                                "next_close_payoff_ratio": 1.08,
                                "next_close_expectancy": 0.004,
                                "sample_count": 12,
                            },
                        }
                    ],
                }
            ]
        },
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        strategy_thresholds_config_path=strategy_thresholds_path,
    )

    assert result["status"] == "generated"
    assert result["early_runner_status"] == "exact"
    assert result["early_runner_intersection_count"] == 1
    assert result["early_runner_only_count"] == 1
    assert result["early_runner_second_entry_count"] == 1
    assert result["strategy_thresholds_config_path"] == strategy_thresholds_path.resolve().as_posix()
    assert result["strategy_thresholds"]["min_recent_exact_streak"] == 4
    assert len(result["written_files"]) == 7
    llm_doc = (output_dir / "BTST-LLM-20260526.md").read_text(encoding="utf-8")
    assert "## 30 秒决策卡" in llm_doc
    assert "- 交易倾向：`confirmation_only`" in llm_doc
    assert "- 主票：`300054`" in llm_doc
    assert "- 证据等级：`B`；数据质量：`fresh`；风险姿态：`reduced`。" in llm_doc
    assert "- 必须确认：等待盘中延续确认后再执行，不做开盘无确认追价。" in llm_doc
    assert "- 失效条件：若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。" in llm_doc
    assert "证据 `B`，数据 `fresh`，倾向 `confirmation_only`，风险 `reduced`" in llm_doc
    assert "## 当前策略阈值基线" in llm_doc
    assert strategy_thresholds_path.resolve().as_posix() in llm_doc
    assert "阈值 profile：`conservative`" in llm_doc
    assert "exact 连续门槛：`4`" in llm_doc
    assert "## Early Runner 章节" in llm_doc
    assert "## Governed Rollout 观察" in llm_doc
    assert "governed_shadow_ready" in llm_doc
    assert "layer_c_formal_precision_tightening" in llm_doc
    assert "## 交集票高亮" in llm_doc
    assert "交集优先复审" in llm_doc
    assert "### 补充复审层" in llm_doc
    assert "### 回补机会层" in llm_doc
    assert "与正式 BTST 的重合票" in llm_doc
    assert "603725" in llm_doc
    assert "说明：胜率中性偏强，盈亏比站上 1.00，赚钱时大体能覆盖亏损。" in llm_doc
    checklist_doc = (output_dir / "BTST-20260526-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    assert "## 30 秒决策卡" in checklist_doc
    assert "- 主票：`300054`（鼎龙股份）。" in checklist_doc
    assert "- 交易倾向：`confirmation_only`" in checklist_doc
    assert "09:20-09:25" in checklist_doc
    assert "## 当前策略阈值基线" in checklist_doc
    assert "## 确认复核动作矩阵" in checklist_doc
    assert "### 300054 鼎龙股份" not in checklist_doc
    assert "| 股票 | 场景 | 动作 |" in checklist_doc
    assert "| 300054 鼎龙股份 | 开盘强且延续确认 | 等待盘中延续确认后再执行，不做开盘无确认追价。 |" in checklist_doc
    assert "| 300054 鼎龙股份 | 触发失效条件 | 若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。 |" in checklist_doc
    assert "## Governed Rollout 观察" in checklist_doc
    assert "execution_eligible_delta" in checklist_doc
    assert "## 交集优先复审" in checklist_doc
    assert "## 回补机会层" in checklist_doc
    assert "交集优先：`300054 鼎龙股份`" in checklist_doc
    assert "Early Runner 补充复审：`603725 天安新材`" in checklist_doc
    assert "Second Entry / Reentry：`605500 森林包装`" in checklist_doc
    assert "说明：胜率中性偏强，盈亏比站上 1.00，赚钱时大体能覆盖亏损。" in checklist_doc
    early_warning_doc = (output_dir / "BTST-20260526-EARLY-WARNING.md").read_text(encoding="utf-8")
    assert "信号日：`2026-05-26`；目标交易日：`2026-05-27`。" in early_warning_doc
    assert "## 当前策略阈值基线" in early_warning_doc
    assert "## 交集票高亮" in early_warning_doc
    assert "## Priority" in early_warning_doc
    assert "605500" in early_warning_doc
    assert "说明：胜率中性偏强，盈亏比站上 1.00，赚钱时大体能覆盖亏损。" in early_warning_doc
    early_warning_card = (output_dir / "BTST-20260526-EARLY-WARNING-CARD.md").read_text(encoding="utf-8")
    assert "信号日：`2026-05-26`；目标交易日：`2026-05-27`。" in early_warning_card
    forum_doc = (output_dir / "20260526-两套交易计划论坛短版.md").read_text(encoding="utf-8")
    assert "信号日：`2026-05-26`；目标交易日：`2026-05-27`。" in forum_doc
    assert "['" not in forum_doc


def test_generate_btst_doc_bundle_default_output_dir_uses_signal_date_and_manifest(tmp_path: Path, monkeypatch) -> None:
    import scripts.generate_btst_doc_bundle as bundle

    monkeypatch.setattr(bundle, "OUTPUTS_DIR", tmp_path / "outputs")

    from src.paper_trading import btst_trade_calendar as cal

    monkeypatch.setattr(
        cal,
        "resolve_next_trade_date_cn_sse_strict",
        lambda *_args, **_kwargs: cal.NextTradeDateResolution(
            signal_date_iso="2026-05-26",
            signal_date_compact="20260526",
            next_trade_date_iso="2026-05-27",
            next_trade_date_compact="20260527",
            calendar_source="tushare_trade_cal",
        ),
    )

    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"

    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
            },
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "primary_action": {
                "ticker": "300054",
                "name": "鼎龙股份",
                "preferred_entry_mode": "confirm_then_hold_breakout",
            },
            "selected_actions": [
                {
                    "ticker": "300054",
                    "name": "鼎龙股份",
                    "action_tier": "primary_entry",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "score_target": 0.55,
                    "historical_prior": {
                        "applied_scope": "same_ticker",
                        "evaluable_count": 10,
                        "next_close_positive_rate": 0.6,
                        "next_close_payoff_ratio": 1.2,
                        "next_close_expectancy": 0.01,
                        "sample_count": 12,
                    },
                }
            ],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 1,
            "selected_count": 1,
            "near_miss_count": 0,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [],
        },
    )

    result = bundle.generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=None,
        refresh_early_runner=False,
        include_extra_warning_docs=False,
        scheme_a_active=True,
    )

    expected_dir = (tmp_path / "outputs" / "202605" / "20260526_scheme_a").resolve()
    assert Path(result["output_dir"]) == expected_dir

    manifest = json.loads((expected_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["signal_date"] == "20260526"
    assert manifest["next_trade_date"] == "20260527"
    assert manifest["scheme_a_active"] is True


def test_generate_btst_doc_bundle_writes_review_ledger_when_requested(tmp_path: Path) -> None:
    """Write a machine-readable pre-trade review ledger only when requested."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "selected_actions": [
                {
                    "ticker": "300054",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "historical_prior": {
                        "applied_scope": "same_ticker",
                        "evaluable_count": 18,
                        "next_close_positive_rate": 0.6667,
                        "next_close_payoff_ratio": 1.42,
                    },
                }
            ],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 10,
            "selected_count": 1,
            "near_miss_count": 0,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {"daily_boards": [{"trade_date": "2026-05-26"}]},
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        write_review_ledger=True,
    )

    ledger_path = output_dir / "20260526-btst-decision-review-ledger.json"
    assert result["review_ledger_json_path"] == ledger_path.as_posix()
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert payload["signal_date"] == "2026-05-26"
    assert payload["next_trade_date"] == "2026-05-27"
    assert payload["rows"][0]["ticker"] == "300054"
    assert payload["rows"][0]["evidence_grade"] == "B"
    assert payload["rows"][0]["realized_next_close"] is None


def test_generate_btst_doc_bundle_surfaces_unavailable_rollout_fallback(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "selected_actions": [],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 10,
            "selected_count": 0,
            "near_miss_count": 0,
            "high_confidence": [],
        },
    )
    _write_json(reports_root / "btst_early_runner_v1_latest.json", {"daily_boards": []})

    output_dir = tmp_path / "outputs"
    generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
    )

    llm_doc = (output_dir / "BTST-LLM-20260526.md").read_text(encoding="utf-8")
    checklist_doc = (output_dir / "BTST-20260526-EXEC-CHECKLIST.md").read_text(encoding="utf-8")

    assert "## Governed Rollout 观察" in llm_doc
    assert "status: `unavailable`" in llm_doc
    assert "selected_hit_rate_15pct: `n/a` -> `n/a`" in llm_doc
    assert "selected_count_delta: `n/a`" in llm_doc
    assert "## Governed Rollout 观察" in checklist_doc
    assert "status: `unavailable`" in checklist_doc
    assert "selected_count_delta: `n/a`" in checklist_doc


def test_generate_btst_doc_bundle_supports_named_threshold_profiles(tmp_path: Path) -> None:
    """Resolve one named threshold profile and surface it in the generated docs."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "selected_actions": [],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 10,
            "selected_count": 0,
            "near_miss_count": 0,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {"daily_boards": [{"trade_date": "2026-05-26"}]},
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        include_extra_warning_docs=False,
        strategy_thresholds_profile="aggressive",
    )

    assert result["strategy_thresholds_profile"] == "aggressive"
    assert result["strategy_thresholds_config_path"].endswith("config/btst_strategy_thresholds_aggressive.json")
    assert result["strategy_thresholds"]["min_recent_exact_streak"] == 2
    llm_doc = (output_dir / "BTST-LLM-20260526.md").read_text(encoding="utf-8")
    assert "profile：`aggressive`" in llm_doc


def test_compare_btst_doc_bundle_profiles_writes_comparison_outputs(tmp_path: Path, monkeypatch) -> None:
    """Generate daily bundle outputs for multiple profiles and write one comparison summary."""
    output_dir = tmp_path / "outputs"

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text(
            f"# BTST {kwargs['strategy_thresholds_profile']}\n",
            encoding="utf-8",
        )
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text(
            f"# BTST-LLM {kwargs['strategy_thresholds_profile']}\n",
            encoding="utf-8",
        )
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [str(profile_output_dir / f"BTST-{signal_date}.md"), str(profile_output_dir / f"BTST-LLM-{signal_date}.md")] * (4 if kwargs["strategy_thresholds_profile"] == "conservative" else 3),
            "early_runner_status": "exact",
            "early_runner_intersection_count": 2 if kwargs["strategy_thresholds_profile"] == "conservative" else 1,
            "early_runner_only_count": 1 if kwargs["strategy_thresholds_profile"] == "conservative" else 3,
            "early_runner_second_entry_count": 0 if kwargs["strategy_thresholds_profile"] == "conservative" else 1,
            "semantic_selected_labels": ["002463 沪电股份"] if kwargs["strategy_thresholds_profile"] == "conservative" else ["300308 中际旭创"],
            "semantic_watch_labels": ["300308 中际旭创"] if kwargs["strategy_thresholds_profile"] == "conservative" else ["002475 立讯精密"],
            "early_runner_overlap_labels": ["002463 沪电股份"] if kwargs["strategy_thresholds_profile"] == "conservative" else [],
            "early_runner_only_labels": [] if kwargs["strategy_thresholds_profile"] == "conservative" else ["002916 深南电路"],
            "early_runner_second_entry_labels": [] if kwargs["strategy_thresholds_profile"] == "conservative" else ["600183 生益科技"],
        }

    monkeypatch.setattr(
        "scripts.generate_btst_doc_bundle.generate_btst_doc_bundle",
        _fake_generate,
    )

    result = compare_btst_doc_bundle_profiles(
        "20260526",
        profiles=["conservative", "aggressive"],
        output_dir=output_dir,
    )

    assert result["status"] == "compared"
    assert result["comparison"]["recommended_profile"] == "conservative"
    assert Path(result["json_path"]).exists()
    assert Path(result["md_path"]).exists()
    assert Path(result["decision_card_json_path"]).exists()
    assert Path(result["decision_card_md_path"]).exists()
    assert len(result["bridge_updated_files"]) == 4
    payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert payload["comparison"]["recommended_profile"] == "conservative"
    assert payload["decision_card"]["recommended_profile"] == "conservative"
    assert len(payload["bridge_updated_files"]) == 4
    markdown = Path(result["md_path"]).read_text(encoding="utf-8")
    assert "Profile 文档包对照" in markdown
    assert "conservative" in markdown
    assert "aggressive" in markdown
    assert "层级差异" in markdown
    assert "002463 沪电股份" in markdown
    assert "002916 深南电路" in markdown
    card_payload = json.loads(Path(result["decision_card_json_path"]).read_text(encoding="utf-8"))
    assert card_payload["action_bias"] == "偏保守执行"
    assert card_payload["dominant_reason_type"] == "intersection_advantage"
    assert card_payload["intersection_delta_vs_runner_up"] == 1
    card_markdown = Path(result["decision_card_md_path"]).read_text(encoding="utf-8")
    assert "交易前决策卡" in card_markdown
    assert "推荐 profile：`conservative`" in card_markdown
    bridge_doc = (output_dir / "conservative" / "BTST-20260526.md").read_text(encoding="utf-8")
    assert "## 今日执行倾向" in bridge_doc
    assert "今日更偏：`conservative`" in bridge_doc
    bridge_llm_doc = (output_dir / "aggressive" / "BTST-LLM-20260526.md").read_text(encoding="utf-8")
    assert "## 今日执行倾向" in bridge_llm_doc


def test_compare_btst_doc_bundle_profiles_describes_ties_without_false_edge(tmp_path: Path, monkeypatch) -> None:
    """Do not claim one profile has more or fewer early-runner evidence when all counts tie."""
    output_dir = tmp_path / "outputs"

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [
                str(profile_output_dir / f"BTST-{signal_date}.md"),
                str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
            ],
            "early_runner_status": "stale_fallback",
            "early_runner_intersection_count": 0,
            "early_runner_only_count": 0,
            "early_runner_second_entry_count": 0,
        }

    monkeypatch.setattr("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", _fake_generate)

    result = compare_btst_doc_bundle_profiles(
        "20260529",
        profiles=["conservative", "aggressive"],
        output_dir=output_dir,
    )

    reasons = result["comparison"]["recommendation_reasons"]
    assert result["comparison"]["recommended_profile"] == "conservative"
    # P0B: an honest scope disclosure is appended when no effective decision diff exists.
    assert any("完全持平" in r for r in reasons)
    assert any("P0B note" in r for r in reasons)
    assert "更多" not in "\n".join(reasons)
    assert "更少" not in "\n".join(reasons)
    assert result["comparison"]["layer_differences"] == []
    assert result["comparison"]["comparison_scope"] == "doc_bundle_rendering"
    assert result["comparison"]["effective_decision_diff"] is False
    assert result["decision_card"]["dominant_reason_type"] == "no_effective_profile_diff"
    assert result["decision_card"]["comparison_scope"] == "doc_bundle_rendering"
    assert result["decision_card"]["effective_decision_diff"] is False
    card_markdown = Path(result["decision_card_md_path"]).read_text(encoding="utf-8")
    assert "完全持平" in card_markdown
    # P0B: card markdown must include the scope declaration.
    assert "doc_bundle_rendering" in card_markdown


def test_compare_btst_doc_bundle_profiles_surfaces_market_gate_override_in_decision_card(tmp_path: Path, monkeypatch) -> None:
    """Promote market-gate override into the compact decision card when both profiles are blocked the same way.

    P0B note (2026-06-04): This test uses mock to manufacture gate override data. Real profile
    compare cannot produce effective_decision_diff=True because profiles only change doc
    rendering thresholds. The mock is retained to verify that gate override logic still fires
    correctly when the canonical artifacts genuinely reflect a blocked gate — but the
    comparison_scope must remain 'doc_bundle_rendering' and effective_decision_diff must be False.
    """
    output_dir = tmp_path / "outputs"

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [
                str(profile_output_dir / f"BTST-{signal_date}.md"),
                str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
            ],
            "early_runner_status": "exact",
            "early_runner_intersection_count": 0,
            "early_runner_only_count": 0,
            "early_runner_second_entry_count": 0,
            "report_mode": "confirmation_review_only",
            "veto_owner": "market_gate",
            "control_tower": {
                "gate": "halt",
                "buy_orders_cleared": False,
            },
        }

    monkeypatch.setattr("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", _fake_generate)

    result = compare_btst_doc_bundle_profiles(
        "20260530",
        profiles=["conservative", "aggressive"],
        output_dir=output_dir,
    )

    decision_card = result["decision_card"]
    assert decision_card["recommended_profile"] == "conservative"
    assert decision_card["action_mode"] == "confirmation_review_only"
    assert decision_card["dominant_reason_type"] == "market_gate_override"
    assert decision_card["market_gate"] == "halt"
    assert decision_card["buy_orders_cleared"] is False
    assert any("市场门控" in reason for reason in decision_card["recommendation_reasons"])


def test_compare_btst_doc_bundle_profiles_does_not_mark_market_gate_override_when_buy_orders_cleared_is_false_without_enforcement(
    tmp_path: Path, monkeypatch
) -> None:
    """P0A correctness (2026-06-04): `buy_orders_cleared=False` alone is ambiguous and must NOT trigger
    market_gate_override. Override must be derived from `enforced=True`, `veto_owner=market_gate`,
    `market_gate=halt`, or `regime_gate_level in {crisis, halt, risk_off}`.
    """
    output_dir = tmp_path / "outputs"

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [
                str(profile_output_dir / f"BTST-{signal_date}.md"),
                str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
            ],
            "early_runner_status": "exact",
            "early_runner_intersection_count": 0,
            "early_runner_only_count": 0,
            "early_runner_second_entry_count": 0,
            # normal_trade path: no enforcement, no orders cleared, but veto_owner is model_evidence.
            "report_mode": "formal_execution",
            "veto_owner": "model_evidence",
            "control_tower": {
                "gate": "normal_trade",
                "regime_gate_level": "normal",
                "enforced": False,
                "buy_orders_cleared": False,
            },
        }

    monkeypatch.setattr("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", _fake_generate)

    result = compare_btst_doc_bundle_profiles(
        "20260530",
        profiles=["conservative", "aggressive"],
        output_dir=output_dir,
    )

    decision_card = result["decision_card"]
    # P0A critical assertion: gate override must NOT activate when only `buy_orders_cleared=False` is present.
    assert decision_card["dominant_reason_type"] != "market_gate_override"
    assert "market_gate_override" not in str(decision_card.get("recommendation_reasons") or [])
    # New decision-card fields must be propagated and present.
    assert decision_card["regime_gate_level"] == "normal"
    assert decision_card["gate_enforced"] is False
    assert decision_card["buy_orders_cleared"] is False


def test_compare_btst_doc_bundle_profiles_marks_market_gate_override_when_halt_with_enforcement(
    tmp_path: Path, monkeypatch
) -> None:
    """P0A correctness (2026-06-04): `market_gate=halt` + `gate_enforced=True` must still activate override,
    even when no orders were cleared (blocked gate that had no orders to clear is a real override).
    """
    output_dir = tmp_path / "outputs"

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [
                str(profile_output_dir / f"BTST-{signal_date}.md"),
                str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
            ],
            "early_runner_status": "exact",
            "early_runner_intersection_count": 0,
            "early_runner_only_count": 0,
            "early_runner_second_entry_count": 0,
            "report_mode": "confirmation_review_only",
            "veto_owner": "market_gate",
            "control_tower": {
                "gate": "halt",
                "regime_gate_level": "crisis",
                "enforced": True,
                # No buy orders to clear (e.g., gate blocked upstream), but enforcement is real.
                "buy_orders_cleared": False,
                "buy_orders_cleared_count": 0,
            },
        }

    monkeypatch.setattr("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", _fake_generate)

    result = compare_btst_doc_bundle_profiles(
        "20260530",
        profiles=["conservative", "aggressive"],
        output_dir=output_dir,
    )

    decision_card = result["decision_card"]
    # Override must activate from `gate=halt` (or `enforced=True` or `veto_owner=market_gate`).
    assert decision_card["dominant_reason_type"] == "market_gate_override"
    assert decision_card["market_gate"] == "halt"
    assert decision_card["regime_gate_level"] == "crisis"
    assert decision_card["gate_enforced"] is True
    assert decision_card["buy_orders_cleared"] is False
    assert any("市场门控" in reason for reason in decision_card["recommendation_reasons"])


def test_compare_btst_doc_bundle_profiles_does_not_treat_risk_off_as_market_gate_value(
    tmp_path: Path, monkeypatch
) -> None:
    """P0A correctness (2026-06-04): `risk_off` is a regime_gate_level, not a market_gate value.
    Market_gate must not be set to `risk_off`; override activation flows from regime_gate_level mapping.
    """
    output_dir = tmp_path / "outputs"

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [
                str(profile_output_dir / f"BTST-{signal_date}.md"),
                str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
            ],
            "early_runner_status": "exact",
            "early_runner_intersection_count": 0,
            "early_runner_only_count": 0,
            "early_runner_second_entry_count": 0,
            "report_mode": "confirmation_review_only",
            "veto_owner": "market_gate",
            "control_tower": {
                "gate": "shadow_only",  # risk_off is NOT a market_gate value
                "regime_gate_level": "risk_off",  # this is the real signal
                "enforced": True,
                "buy_orders_cleared": False,
            },
        }

    monkeypatch.setattr("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", _fake_generate)

    result = compare_btst_doc_bundle_profiles(
        "20260530",
        profiles=["conservative", "aggressive"],
        output_dir=output_dir,
    )

    decision_card = result["decision_card"]
    # Override must activate via regime_gate_level=risk_off even though market_gate is shadow_only.
    assert decision_card["dominant_reason_type"] == "market_gate_override"
    # market_gate must not be 'risk_off' — that is a regime_gate_level value.
    assert decision_card["market_gate"] != "risk_off"
    assert decision_card["market_gate"] == "shadow_only"
    assert decision_card["regime_gate_level"] == "risk_off"



def test_p0b_comparison_scope_is_always_doc_bundle_rendering(tmp_path: Path, monkeypatch) -> None:
    """P0B (2026-06-04): comparison_scope must always be doc_bundle_rendering for current profiles."""
    output_dir = tmp_path / "outputs"

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [
                str(profile_output_dir / f"BTST-{signal_date}.md"),
                str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
            ],
            "early_runner_status": "exact",
            "early_runner_intersection_count": 1,
            "early_runner_only_count": 0,
            "early_runner_second_entry_count": 0,
            "report_mode": "formal_execution",
            "veto_owner": "model_evidence",
            "control_tower": {
                "gate": "normal_trade",
                "regime_gate_level": "normal",
                "enforced": False,
                "buy_orders_cleared": False,
            },
        }

    monkeypatch.setattr("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", _fake_generate)

    result = compare_btst_doc_bundle_profiles(
        "20260530",
        profiles=["conservative", "aggressive"],
        output_dir=output_dir,
    )

    # P0B: comparison_scope must always be doc_bundle_rendering.
    assert result["comparison"]["comparison_scope"] == "doc_bundle_rendering"
    assert result["decision_card"]["comparison_scope"] == "doc_bundle_rendering"
    # effective_decision_diff must be False (profiles don't change upstream selection).
    assert result["comparison"]["effective_decision_diff"] is False
    assert result["decision_card"]["effective_decision_diff"] is False
    # Card markdown must include the scope declaration.
    card_md = Path(result["decision_card_md_path"]).read_text(encoding="utf-8")
    assert "doc_bundle_rendering" in card_md
    # Comparison markdown must include the scope declaration.
    comp_md = Path(result["md_path"]).read_text(encoding="utf-8")
    assert "doc_bundle_rendering" in comp_md


def test_p0b_no_strategy_advantage_claimed_when_no_effective_decision_diff(tmp_path: Path, monkeypatch) -> None:
    """P0B (2026-06-04): must not describe doc rendering differences as verified strategy advantages."""
    output_dir = tmp_path / "outputs"

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [
                str(profile_output_dir / f"BTST-{signal_date}.md"),
                str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
            ],
            "early_runner_status": "exact",
            "early_runner_intersection_count": 0,
            "early_runner_only_count": 0,
            "early_runner_second_entry_count": 0,
            "report_mode": "formal_execution",
            "veto_owner": "model_evidence",
            "control_tower": {
                "gate": "normal_trade",
                "regime_gate_level": "normal",
                "enforced": False,
                "buy_orders_cleared": False,
            },
        }

    monkeypatch.setattr("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", _fake_generate)

    result = compare_btst_doc_bundle_profiles(
        "20260530",
        profiles=["conservative", "aggressive"],
        output_dir=output_dir,
    )

    reasons = result["comparison"]["recommendation_reasons"]
    # P0B: must contain honest scope disclosure when no effective decision diff.
    assert any("P0B note" in r for r in reasons)
    # Must explicitly disclaim verified strategy advantage.
    assert any("不代表已验证的策略优势" in r or "不代表策略上更优" in r for r in reasons)


def test_compare_btst_doc_bundle_profiles_bridges_top_level_main_docs_when_present(tmp_path: Path, monkeypatch) -> None:
    """Append the shared profile decision bridge into the sibling top-level BTST docs when they already exist."""
    output_dir = tmp_path / "outputs" / "20260529_profile_compare"
    main_output_dir = tmp_path / "outputs" / "20260529"
    main_output_dir.mkdir(parents=True, exist_ok=True)
    (main_output_dir / "BTST-20260529.md").write_text("# Top-level BTST\n", encoding="utf-8")
    (main_output_dir / "BTST-LLM-20260529.md").write_text("# Top-level BTST-LLM\n", encoding="utf-8")

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [
                str(profile_output_dir / f"BTST-{signal_date}.md"),
                str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
            ],
            "early_runner_status": "exact",
            "early_runner_intersection_count": 0,
            "early_runner_only_count": 0,
            "early_runner_second_entry_count": 0,
        }

    monkeypatch.setattr("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", _fake_generate)

    result = compare_btst_doc_bundle_profiles(
        "20260529",
        profiles=["conservative", "aggressive"],
        output_dir=output_dir,
    )

    top_level_rule_doc = (main_output_dir / "BTST-20260529.md").read_text(encoding="utf-8")
    top_level_llm_doc = (main_output_dir / "BTST-LLM-20260529.md").read_text(encoding="utf-8")
    assert "## 今日执行倾向" in top_level_rule_doc
    assert "## 今日执行倾向" in top_level_llm_doc
    assert (main_output_dir / "BTST-20260529.md").as_posix() in result["bridge_updated_files"]
    assert (main_output_dir / "BTST-LLM-20260529.md").as_posix() in result["bridge_updated_files"]
    # P0D: managed markers must be present.
    assert "<!-- BTST_PROFILE_BRIDGE_BEGIN -->" in top_level_rule_doc
    assert "<!-- BTST_PROFILE_BRIDGE_END -->" in top_level_rule_doc


def test_compare_btst_doc_bundle_profiles_bridge_idempotent_on_rerun(tmp_path: Path, monkeypatch) -> None:
    """P0D (2026-06-04): re-running bridge must replace, not duplicate."""
    output_dir = tmp_path / "outputs" / "20260529_profile_compare"
    main_output_dir = tmp_path / "outputs" / "20260529"
    main_output_dir.mkdir(parents=True, exist_ok=True)
    (main_output_dir / "BTST-20260529.md").write_text("# Top-level BTST\n", encoding="utf-8")
    (main_output_dir / "BTST-LLM-20260529.md").write_text("# Top-level BTST-LLM\n", encoding="utf-8")

    def _fake_generate(signal_date, **kwargs):
        profile_output_dir = Path(kwargs["output_dir"])
        profile_output_dir.mkdir(parents=True, exist_ok=True)
        (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
        (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
        return {
            "status": "generated",
            "signal_date": signal_date,
            "output_dir": str(profile_output_dir),
            "written_files": [
                str(profile_output_dir / f"BTST-{signal_date}.md"),
                str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
            ],
            "early_runner_status": "exact",
            "early_runner_intersection_count": 0,
            "early_runner_only_count": 0,
            "early_runner_second_entry_count": 0,
        }

    monkeypatch.setattr("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", _fake_generate)

    # Run once.
    compare_btst_doc_bundle_profiles("20260529", profiles=["conservative", "aggressive"], output_dir=output_dir)
    doc_after_first = (main_output_dir / "BTST-20260529.md").read_text(encoding="utf-8")
    count_first = doc_after_first.count("## 今日执行倾向")

    # Run again with same params.
    compare_btst_doc_bundle_profiles("20260529", profiles=["conservative", "aggressive"], output_dir=output_dir)
    doc_after_second = (main_output_dir / "BTST-20260529.md").read_text(encoding="utf-8")
    count_second = doc_after_second.count("## 今日执行倾向")

    # Must not duplicate the bridge section.
    assert count_second == count_first == 1
    """Mark overlaps as reference-only when early-runner falls back to an older board."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
            },
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "primary_entry": {
                "ticker": "300054",
                "name": "鼎龙股份",
                "preferred_entry_mode": "confirm_then_hold_breakout",
            },
            "selected_entries": [
                {
                    "ticker": "300054",
                    "name": "鼎龙股份",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "historical_prior": {
                        "next_close_positive_rate": 0.6667,
                    },
                }
            ],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 3200,
            "selected_count": 780,
            "near_miss_count": 760,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [
                {
                    "trade_date": "2026-05-20",
                    "gate_action": "research_only",
                    "deployment_mode": "research_only",
                    "early_runner_watchlist": [
                        {
                            "ticker": "300054",
                            "name": "鼎龙股份",
                            "entry_status": "filled",
                            "pre_score": 0.71,
                            "confirm_score": 0.82,
                        },
                        {
                            "ticker": "300476",
                            "name": "胜宏科技",
                            "entry_status": "watch_only",
                            "pre_score": 0.64,
                            "confirm_score": 0.43,
                        },
                    ],
                    "early_runner_priority": [],
                    "second_entry_reentry": [],
                }
            ]
        },
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
    )

    assert result["early_runner_status"] == "stale_fallback"
    checklist_doc = (output_dir / "BTST-20260526-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    assert "历史交集参考：`300054 鼎龙股份`" in checklist_doc
    llm_doc = (output_dir / "BTST-LLM-20260526.md").read_text(encoding="utf-8")
    assert "early-runner 状态：`stale_fallback`" in llm_doc
    assert "stale_reference" in llm_doc
    assert "不能直接当成当日交集优先" in llm_doc
    assert "只能作为参考高亮" in llm_doc
    assert "## Only Early Runner" not in llm_doc
    assert "层级 `early_runner_watchlist`" not in llm_doc
    assert llm_doc.count("300476 胜宏科技") == 1
    rule_doc = (output_dir / "BTST-20260526.md").read_text(encoding="utf-8")
    assert "不能直接当成当日交集优先" in rule_doc
    assert "stale_reference" in rule_doc
    assert "证据 `D`" in rule_doc
    assert "倾向 `watch_only`" in rule_doc
    assert "层级 `early_runner_watchlist`" not in rule_doc
    assert rule_doc.count("300476 胜宏科技") == 1


def test_generate_btst_doc_bundle_keeps_second_entry_out_of_only_early_runner_layer(tmp_path: Path) -> None:
    """Keep second-entry rows separate from only-early-runner rows in the four-layer output."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
            },
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "selected_actions": [],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 3200,
            "selected_count": 0,
            "near_miss_count": 0,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [
                {
                    "trade_date": "2026-05-26",
                    "gate_action": "tradeable",
                    "deployment_mode": "shadow_only",
                    "early_runner_watchlist": [],
                    "early_runner_priority": [
                        {
                            "ticker": "300001",
                            "name": "特锐德",
                            "entry_status": "not_confirmed",
                            "pre_score": 0.67,
                            "confirm_score": 0.42,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                        }
                    ],
                    "second_entry_reentry": [
                        {
                            "ticker": "300002",
                            "name": "神州泰岳",
                            "entry_status": "watch_only",
                            "pre_score": 0.51,
                            "confirm_score": 0.36,
                            "preferred_entry_mode": "second_entry_reentry",
                        }
                    ],
                }
            ]
        },
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
    )

    assert result["early_runner_intersection_count"] == 0
    assert result["early_runner_only_count"] == 1
    assert result["early_runner_second_entry_count"] == 1
    checklist_doc = (output_dir / "BTST-20260526-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    assert "Early Runner 补充复审：`300001 特锐德`" in checklist_doc
    assert "Second Entry / Reentry：`300002 神州泰岳`" in checklist_doc
    assert "Early Runner 补充复审：`300002 神州泰岳`" not in checklist_doc


def test_generate_btst_doc_bundle_renders_rule_front_rows_from_rule_report_fields(tmp_path: Path) -> None:
    """Render rule-front rows from rule-report fields instead of generic action-row fallbacks."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260527_20260527_live_m2_7_short_trade_only_20260528_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-27",
            "next_trade_date": "2026-05-28",
            "selection_target": "short_trade_only",
            "selected_actions": [],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260527.json",
        {
            "trade_date": "20260527",
            "next_date": "20260528",
            "pool_size": 3259,
            "selected_count": 610,
            "near_miss_count": 633,
            "high_confidence": [
                {
                    "ticker": "002012",
                    "name": "凯恩股份",
                    "score": 0.8553,
                    "pct_chg": 10.03,
                    "close_strength": 1.0,
                    "catalyst_freshness": 1.0,
                }
            ],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {"daily_boards": [{"trade_date": "2026-05-27"}]},
    )

    output_dir = tmp_path / "outputs"
    generate_btst_doc_bundle(
        "20260527",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        include_extra_warning_docs=False,
    )

    rule_doc = (output_dir / "BTST-20260527.md").read_text(encoding="utf-8")
    assert "002012 凯恩股份" in rule_doc
    assert "规则分数 `0.8553`" in rule_doc
    assert "当日涨幅 `10.03%`" in rule_doc
    assert "层级 `n/a`" not in rule_doc


def test_generate_btst_doc_bundle_surfaces_research_only_confirmation_pool(tmp_path: Path) -> None:
    """Show research-only confirmation rows when the exact-date board has no actionable early-runner lists."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260527_20260527_live_m2_7_short_trade_only_20260528_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-27",
            "next_trade_date": "2026-05-28",
            "selection_target": "short_trade_only",
            "selected_actions": [
                {
                    "ticker": "001309",
                    "name": "德明利",
                    "action_tier": "primary_entry",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "score_target": 0.5301,
                }
            ],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260527.json",
        {
            "trade_date": "20260527",
            "next_date": "20260528",
            "pool_size": 3259,
            "selected_count": 610,
            "near_miss_count": 633,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [
                {
                    "trade_date": "2026-05-27",
                    "btst_regime_gate": "halt",
                    "gate_action": "research_only",
                    "deployment_mode": "research_only",
                    "early_runner_watchlist": [],
                    "early_runner_priority": [],
                    "second_entry_reentry": [],
                    "full_report_confirmation": [
                        {
                            "ticker": "300476",
                            "name": "胜宏科技",
                            "candidate_source": "short_trade_boundary",
                            "score_target": 0.4294,
                            "preferred_entry_mode": "confirm_then_hold_breakout",
                        },
                        {
                            "ticker": "603083",
                            "name": "剑桥科技",
                            "candidate_source": "catalyst_theme",
                            "score_target": 0.4221,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                        },
                    ],
                }
            ]
        },
    )

    output_dir = tmp_path / "outputs"
    generate_btst_doc_bundle(
        "20260527",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
    )

    early_warning_doc = (output_dir / "BTST-20260527-EARLY-WARNING.md").read_text(encoding="utf-8")
    assert "## 状态" in early_warning_doc
    assert "- 请求 trade_date：`2026-05-27`。" in early_warning_doc
    assert "## Research Only 确认池" in early_warning_doc
    assert "300476 胜宏科技" in early_warning_doc
    assert "603083 剑桥科技" in early_warning_doc
    assert "证据 `D`" in early_warning_doc
    assert "数据 `insufficient`" in early_warning_doc
    assert "倾向 `watch_only`" in early_warning_doc
    assert "说明：胜率和盈亏比暂缺，只能先把它当成轻量历史先验。" in early_warning_doc
    early_warning_card = (output_dir / "BTST-20260527-EARLY-WARNING-CARD.md").read_text(encoding="utf-8")
    assert "research_only 确认池" in early_warning_card
    assert "300476" in early_warning_card
    forum_doc = (output_dir / "20260527-两套交易计划论坛短版.md").read_text(encoding="utf-8")
    assert "research-only 确认前排" in forum_doc
    assert "300476" in forum_doc
    plain_doc = (output_dir / "20260527-两套交易计划通俗说明.md").read_text(encoding="utf-8")
    assert "研究确认前排" in plain_doc
    assert "300476" in plain_doc


def test_generate_btst_doc_bundle_enriches_missing_names_from_snapshot_summary(tmp_path: Path) -> None:
    """Fill missing BTST artifact names from local data snapshots before rendering docs."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260529_20260529_live_m2_7_short_trade_only_20260601_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-29",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "selected_actions": [
                {
                    "ticker": "300408",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "score_target": 0.5349,
                    "historical_prior": {
                        "evaluable_count": 15,
                        "next_close_positive_rate": 0.8,
                        "next_close_payoff_ratio": 3.7926,
                        "next_close_return_mean": 0.0533,
                    },
                }
            ],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260529.json",
        {
            "trade_date": "20260529",
            "next_date": "20260601",
            "pool_size": 3339,
            "selected_count": 530,
            "near_miss_count": 578,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {"daily_boards": [{"trade_date": "2026-05-29"}]},
    )
    snapshot_summary = report_dir / "data_snapshots" / "300408" / "2026-05-29" / "summary.md"
    snapshot_summary.parent.mkdir(parents=True, exist_ok=True)
    snapshot_summary.write_text(
        "# 300408（三环集团）数据快照 - 2026-05-29\n\n- **股票名称**：三环集团\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "outputs"
    generate_btst_doc_bundle(
        "20260529",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        include_extra_warning_docs=False,
    )

    llm_doc = (output_dir / "BTST-LLM-20260529.md").read_text(encoding="utf-8")
    assert "300408 三环集团" in llm_doc
    assert "`300408`：" not in llm_doc


def test_generate_btst_doc_bundle_renders_win_rate_payoff_decision(tmp_path: Path) -> None:
    """Render a win-rate/payoff-first decision section that separates hold candidates from intraday-only names."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260529_20260529_live_m2_7_short_trade_only_20260601_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-29",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "selected_actions": [
                {
                    "ticker": "300408",
                    "name": "三环集团",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "score_target": 0.5349,
                    "historical_prior": {
                        "evaluable_count": 15,
                        "next_close_positive_rate": 0.8,
                        "next_close_payoff_ratio": 3.7926,
                        "next_close_return_mean": 0.0533,
                    },
                },
                {
                    "ticker": "300054",
                    "name": "鼎龙股份",
                    "preferred_entry_mode": "intraday_confirmation_only",
                    "score_target": 0.5457,
                    "historical_prior": {
                        "evaluable_count": 47,
                        "next_close_positive_rate": 0.5319,
                        "next_close_payoff_ratio": 0.8408,
                        "next_close_return_mean": -0.0012,
                    },
                },
            ],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260529.json",
        {
            "trade_date": "20260529",
            "next_date": "20260601",
            "pool_size": 3339,
            "selected_count": 530,
            "near_miss_count": 578,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {"daily_boards": [{"trade_date": "2026-05-29"}]},
    )

    output_dir = tmp_path / "outputs"
    generate_btst_doc_bundle(
        "20260529",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        include_extra_warning_docs=False,
    )

    llm_doc = (output_dir / "BTST-LLM-20260529.md").read_text(encoding="utf-8")
    checklist_doc = (output_dir / "BTST-20260529-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    assert "## 胜率/赔率优先决策" in llm_doc
    assert "第一优先：`300408 三环集团`" in llm_doc
    assert "只做盘中机会：`300054 鼎龙股份`" in llm_doc
    assert "## 胜率/赔率闸门" in checklist_doc
    assert "300054 鼎龙股份" in checklist_doc


def test_generate_btst_doc_bundle_renders_institutional_control_sections(tmp_path: Path) -> None:
    """Surface Alpha/Beta/Gamma controls from historical priors and selection snapshots."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260529_20260529_live_m2_7_short_trade_only_20260601_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    snapshot_path = report_dir / "selection_artifacts" / "2026-05-29" / "selection_snapshot.json"
    priority_board_path = report_dir / "btst_next_day_priority_board_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-29",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
                "priority_board_json": priority_board_path.as_posix(),
            },
        },
    )
    selected_row = {
        "ticker": "300408",
        "name": "三环集团",
        "preferred_entry_mode": "confirm_then_hold_breakout",
        "score_target": 0.5349,
        "confidence": 0.7396,
        "positive_tags": [
            "trend_acceleration_confirmed",
            "fresh_catalyst_support",
            "confirmed_breakout_stage",
        ],
        "top_reasons": [
            "trend_acceleration_strong",
            "catalyst_theme_short_trade_carryover",
            "confirmed_breakout",
        ],
        "candidate_reason_codes": [
            "catalyst_theme_candidate_score_ranked",
        ],
        "gate_status": {
            "data": "pass",
            "execution": "proxy_only",
            "committee": "shadow_only",
        },
        "metrics": {
            "breakout_freshness": 0.4,
            "trend_acceleration": 0.8957,
            "volume_expansion_quality": 0.25,
            "close_strength": 0.9211,
            "catalyst_freshness": 0.0,
        },
        "historical_prior": {
            "applied_scope": "same_ticker",
            "sample_count": 15,
            "evaluable_count": 15,
            "next_high_hit_threshold": 0.02,
            "next_open_return_mean": 0.0204,
            "next_high_hit_rate_at_threshold": 0.7333,
            "next_close_positive_rate": 0.8,
            "next_close_positive_count": 12,
            "next_close_negative_count": 3,
            "next_close_payoff_ratio": 3.7926,
            "next_close_expectancy": 0.0533,
            "next_high_return_mean": 0.0837,
            "next_close_return_mean": 0.0533,
            "next_open_to_close_return_mean": 0.0319,
        },
    }
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "snapshot_path": snapshot_path.as_posix(),
            "selected_actions": [selected_row],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        priority_board_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "source_paths": {"snapshot_path": snapshot_path.as_posix()},
            "priority_rows": [selected_row],
        },
    )
    _write_json(
        snapshot_path,
        {
            "trade_date": "2026-05-29",
            "market_state": {
                "regime_gate_level": "crisis",
                "breadth_ratio": 0.284187,
                "daily_return": -0.004496,
                "limit_up_count": 49,
                "limit_down_count": 49,
                "limit_up_down_ratio": 1.0,
                "position_scale": 0.75,
                "regime_gate_reasons": ["breadth_weak", "position_scale_reduced"],
            },
            "buy_orders": [
                {
                    "ticker": "300408",
                    "shares": 400,
                    "amount": 4000.0,
                    "risk_budget_ratio": 0.5,
                    "risk_budget_gate": "halt_relief",
                    "execution_contract_bucket": "halt_promoted",
                    "constraint_binding": "vol",
                }
            ],
            "funnel_diagnostics": {
                "btst_regime_gate_enforcement": {
                    "enforced": True,
                    "gate": "halt",
                    "mode": "enforce",
                    "buy_orders_cleared": True,
                    "buy_orders_cleared_count": 1,
                    "shadow_promotion_tickers": ["300408"],
                }
            },
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260529.json",
        {
            "trade_date": "20260529",
            "next_date": "20260601",
            "pool_size": 3339,
            "selected_count": 530,
            "near_miss_count": 578,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {"daily_boards": [{"trade_date": "2026-05-29"}]},
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260529",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        include_extra_warning_docs=False,
        write_review_ledger=True,
    )

    llm_doc = (output_dir / "BTST-LLM-20260529.md").read_text(encoding="utf-8")
    checklist_doc = (output_dir / "BTST-20260529-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    quality_summary_path = Path(result["quality_summary_json_path"])
    quality_summary = json.loads(quality_summary_path.read_text(encoding="utf-8"))
    ledger_payload = json.loads(
        (output_dir / "20260529-btst-decision-review-ledger.json").read_text(encoding="utf-8")
    )

    assert "## 盘前控制塔" in llm_doc
    assert "模型原始倾向：`trade_allowed`" in llm_doc
    assert "门控后有效状态：`gate_locked_confirmation_only`" in llm_doc
    assert "market_gate_downgraded_raw_trade_allowed" in llm_doc
    assert "## 盘前控制塔" in checklist_doc
    assert quality_summary_path.exists()
    assert quality_summary["control_tower"]["effective_trade_bias"] == "gate_locked_confirmation_only"
    assert quality_summary["required_sections_missing"] == []
    assert quality_summary["quality_warnings"] == ["market_gate_downgraded_raw_trade_allowed"]
    assert "## Alpha 样本稳健性与标签拆解" in llm_doc
    assert "| 股票 | 样本量 | 收缩胜率 | 盈亏比 | 分化标签 | 当前层级 |" in llm_doc
    assert "| 300408 三环集团 | 15 | 76.47% | 3.79 | 一致偏强 | 正式执行层 |" in llm_doc
    assert "## Alpha 因子证据卡" in llm_doc
    assert "正向证据：`trend_acceleration_confirmed`" in llm_doc
    assert "## Gamma 市场门控与风险预算" in llm_doc
    assert "regime_gate_level：`crisis`" in llm_doc
    assert "breadth_ratio：`28.42%`" in llm_doc
    assert "gate：`halt`" in llm_doc
    assert "300408 三环集团" in llm_doc
    assert "risk_budget_ratio `0.50`" in llm_doc
    assert "## Beta 执行硬条件与成本闸门" in checklist_doc
    assert "滑点+冲击成本" in checklist_doc
    assert "## 盘后复盘闭环" in checklist_doc
    assert ledger_payload["rows"][0]["sample_count"] == 15
    assert ledger_payload["rows"][0]["evaluable_count"] == 15
    assert ledger_payload["rows"][0]["shrunk_win_rate"] == 0.7647
    assert ledger_payload["rows"][0]["win_rate_wilson_low"] is not None
    assert ledger_payload["rows"][0]["realized_slippage"] is None
    assert ledger_payload["rows"][0]["mae"] is None
    assert ledger_payload["rows"][0]["mfe"] is None


def _generate_btst_doc_bundle_gate_outputs(tmp_path: Path, *, gate_locked: bool):
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260529_20260529_live_m2_7_short_trade_only_20260601_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    snapshot_path = report_dir / "selection_artifacts" / "2026-05-29" / "selection_snapshot.json"
    priority_board_path = report_dir / "btst_next_day_priority_board_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-29",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
                "priority_board_json": priority_board_path.as_posix(),
            },
            "btst_0422_flags": {
                "p7_gap_overlay_mode": "report",
                "p7_gap_warn_threshold": 0.005,
                "p7_gap_halt_threshold": 0.01,
                "p7_gap_warn_size_discount": 0.5,
            },
        },
    )
    selected_row = {
        "ticker": "300408",
        "name": "三环集团",
        "preferred_entry_mode": "confirm_then_hold_breakout",
        "score_target": 0.5349,
        "confidence": 0.7396,
        "positive_tags": [
            "trend_acceleration_confirmed",
            "fresh_catalyst_support",
            "confirmed_breakout_stage",
        ],
        "top_reasons": [
            "trend_acceleration_strong",
            "catalyst_theme_short_trade_carryover",
            "confirmed_breakout",
        ],
        "candidate_reason_codes": ["catalyst_theme_candidate_score_ranked"],
        "gate_status": {
            "data": "pass",
            "execution": "proxy_only",
            "committee": "shadow_only",
        },
        "metrics": {
            "breakout_freshness": 0.4,
            "trend_acceleration": 0.8957,
            "volume_expansion_quality": 0.25,
            "close_strength": 0.9211,
            "catalyst_freshness": 0.0,
        },
        "historical_prior": {
            "applied_scope": "same_ticker",
            "sample_count": 15,
            "evaluable_count": 15,
            "next_high_hit_threshold": 0.02,
            "next_open_return_mean": 0.0204,
            "next_high_hit_rate_at_threshold": 0.7333,
            "next_close_positive_rate": 0.8,
            "next_close_positive_count": 12,
            "next_close_negative_count": 3,
            "next_close_payoff_ratio": 3.7926,
            "next_close_expectancy": 0.0533,
            "next_high_return_mean": 0.0837,
            "next_close_return_mean": 0.0533,
            "next_open_to_close_return_mean": 0.0319,
        },
    }
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "snapshot_path": snapshot_path.as_posix(),
            "selected_actions": [selected_row],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        priority_board_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "source_paths": {"snapshot_path": snapshot_path.as_posix()},
            "priority_rows": [selected_row],
            "global_guardrails": ["priority board 只负责排序和分层，不改变 short-trade admission 默认语义。"],
        },
    )
    _write_json(
        snapshot_path,
        {
            "trade_date": "2026-05-29",
            "market_state": {
                "regime_gate_level": "crisis" if gate_locked else "balanced",
                "breadth_ratio": 0.284187 if gate_locked else 0.612345,
                "daily_return": -0.004496 if gate_locked else 0.0112,
                "limit_up_count": 49 if gate_locked else 83,
                "limit_down_count": 49 if gate_locked else 11,
                "limit_up_down_ratio": 1.0 if gate_locked else 7.5455,
                "position_scale": 0.75 if gate_locked else 1.0,
                "regime_gate_reasons": ["breadth_weak", "position_scale_reduced"] if gate_locked else ["breadth_supportive"],
            },
            "buy_orders": [
                {
                    "ticker": "300408",
                    "shares": 400,
                    "amount": 4000.0,
                    "risk_budget_ratio": 0.5,
                    "risk_budget_gate": "halt_relief",
                    "execution_contract_bucket": "halt_promoted",
                    "constraint_binding": "vol",
                }
            ]
            if gate_locked
            else [],
            "funnel_diagnostics": {
                "btst_regime_gate_enforcement": {
                    "enforced": gate_locked,
                    "gate": "halt" if gate_locked else "pass",
                    "mode": "enforce" if gate_locked else "observe",
                    "buy_orders_cleared": gate_locked,
                    "buy_orders_cleared_count": 1 if gate_locked else 0,
                    "shadow_promotion_tickers": ["300408"] if gate_locked else [],
                }
            },
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260529.json",
        {
            "trade_date": "20260529",
            "next_date": "20260601",
            "pool_size": 3339,
            "selected_count": 530,
            "near_miss_count": 578,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [
                {
                    "trade_date": "2026-05-29",
                    "gate_action": "tradeable",
                    "deployment_mode": "shadow_only",
                    "early_runner_watchlist": [],
                    "early_runner_priority": [],
                    "second_entry_reentry": [],
                }
            ]
        },
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260529",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        include_extra_warning_docs=False,
        write_review_ledger=True,
    )

    llm_doc = (output_dir / "BTST-LLM-20260529.md").read_text(encoding="utf-8")
    checklist_doc = (output_dir / "BTST-20260529-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    plain_doc = (output_dir / "20260529-两套交易计划通俗说明.md").read_text(encoding="utf-8")
    forum_doc = (output_dir / "20260529-两套交易计划论坛短版.md").read_text(encoding="utf-8")
    quality_summary = json.loads(Path(result["quality_summary_json_path"]).read_text(encoding="utf-8"))
    ledger_payload = json.loads((output_dir / "20260529-btst-decision-review-ledger.json").read_text(encoding="utf-8"))
    return llm_doc, checklist_doc, plain_doc, forum_doc, quality_summary, ledger_payload


def test_generate_btst_doc_bundle_gate_locked_confirmation_only_switches_to_confirmation_review_outputs(tmp_path: Path) -> None:
    """Gate-locked control-tower state should downgrade final docs and ledger into confirmation-review mode."""
    llm_doc, checklist_doc, plain_doc, forum_doc, quality_summary, ledger_payload = _generate_btst_doc_bundle_gate_outputs(
        tmp_path,
        gate_locked=True,
    )

    assert quality_summary["control_tower"]["effective_trade_bias"] == "gate_locked_confirmation_only"
    first_row = ledger_payload["rows"][0]

    assert "## 正式执行层" not in llm_doc
    assert "## 确认复核队列" in llm_doc
    assert "正式执行层先决定主顺序" not in llm_doc
    assert "确认复核队列先决定主复核顺序" in llm_doc
    assert "## 正式执行顺序" not in checklist_doc
    assert "## 确认复核顺序" in checklist_doc
    assert "## 正式执行动作矩阵" not in checklist_doc
    assert "## 确认复核动作矩阵" in checklist_doc
    assert "- [ ] 确认复核：`300408 三环集团`" in checklist_doc
    assert "- [ ] 正式观察：`300408 三环集团`" not in checklist_doc

    assert "## 全局 Guardrails" in checklist_doc
    assert "priority board 只负责排序和分层" in checklist_doc
    assert "Gap overlay (BTST 0422 P7/report):" in checklist_doc
    assert "≤ -0.5%" in checklist_doc
    assert "≤ -1.0%" in checklist_doc
    assert "Regime gate (crisis):" in checklist_doc
    assert "确认复核主线" in plain_doc
    assert "正式 BTST 决定主执行顺序" not in plain_doc
    assert "放行权归 `market_gate`" in plain_doc
    assert "确认复核主线" in forum_doc
    assert "正式 BTST 决定主票" not in forum_doc
    assert "放行权 `market_gate`" in forum_doc
    assert quality_summary.get("report_mode") == "confirmation_review_only"
    assert quality_summary.get("semantic_conflicts") == []
    assert quality_summary.get("forbidden_semantics_hits") == []
    assert quality_summary["source_of_truth_snapshot"]["formal_rows"] == [
        {
            "ticker": "300408",
            "execution_state": "confirmable",
            "max_allowed_state_today": "confirmable",
            "allowed_sections": ["review_queue"],
            "formal_buy_allowed": False,
            "release_authority": "market_gate",
        }
    ]
    assert quality_summary["source_of_truth_snapshot"]["forbidden_semantics_hits"] == []
    assert first_row.get("execution_state") == "confirmable"
    assert first_row.get("max_allowed_state_today") == "confirmable"
    assert first_row.get("formal_buy_allowed") is False
    assert first_row.get("allowed_sections") == ["review_queue"]
    assert first_row.get("release_authority") == "market_gate"
    assert first_row.get("post_close_review_state") is None
    assert first_row.get("post_close_review_transition") is None


def test_generate_btst_doc_bundle_gate_allowed_keeps_formal_execution_outputs(tmp_path: Path) -> None:
    """Gate-passed control-tower state should keep formal-execution docs and ledger outputs."""
    llm_doc, checklist_doc, plain_doc, forum_doc, quality_summary, ledger_payload = _generate_btst_doc_bundle_gate_outputs(
        tmp_path,
        gate_locked=False,
    )

    assert quality_summary["control_tower"]["effective_trade_bias"] == "trade_allowed"
    first_row = ledger_payload["rows"][0]

    assert "## 正式执行层" in llm_doc
    assert "## 确认复核队列" not in llm_doc
    assert "## 正式执行顺序" in checklist_doc
    assert "## 确认复核顺序" not in checklist_doc
    assert "## 正式执行动作矩阵" in checklist_doc
    assert "## 确认复核动作矩阵" not in checklist_doc
    assert "正式 BTST 仍以 `300408 三环集团` 这条主线为准" in plain_doc
    assert "放行权归 `already_released`" in plain_doc
    assert "明日 BTST 主线还是 `300408 三环集团`" in forum_doc
    assert "放行权 `already_released`" in forum_doc
    assert quality_summary.get("report_mode") == "formal_execution"
    assert quality_summary.get("semantic_conflicts") == []
    assert quality_summary.get("forbidden_semantics_hits") == []
    assert quality_summary["source_of_truth_snapshot"]["formal_rows"] == [
        {
            "ticker": "300408",
            "execution_state": "orderable",
            "max_allowed_state_today": "orderable",
            "allowed_sections": ["formal_queue"],
            "formal_buy_allowed": True,
            "release_authority": "already_released",
        }
    ]
    assert first_row.get("max_allowed_state_today") == "orderable"
    assert first_row.get("execution_state") == "orderable"
    assert first_row.get("formal_buy_allowed") is True
    assert first_row.get("allowed_sections") == ["formal_queue"]
    assert first_row.get("release_authority") == "already_released"


def test_generate_btst_doc_bundle_post_trade_review_loop_mentions_review_transition_backfill(tmp_path: Path) -> None:
    """Checklist should document the post-close review transition fields that close the execution loop."""
    _, checklist_doc, _, _, _, _ = _generate_btst_doc_bundle_gate_outputs(
        tmp_path,
        gate_locked=True,
    )

    assert "post_close_review_state" in checklist_doc
    assert "post_close_review_transition" in checklist_doc


def test_generate_btst_doc_bundle_gate_locked_early_warning_docs_surface_execution_contract(tmp_path: Path) -> None:
    """Early-warning docs should inherit the same gate-locked execution contract as the main BTST surfaces."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260529_20260529_live_m2_7_short_trade_only_20260601_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    snapshot_path = report_dir / "selection_artifacts" / "2026-05-29" / "selection_snapshot.json"
    priority_board_path = report_dir / "btst_next_day_priority_board_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-29",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
                "priority_board_json": priority_board_path.as_posix(),
            },
        },
    )
    selected_row = {
        "ticker": "300408",
        "name": "三环集团",
        "preferred_entry_mode": "confirm_then_hold_breakout",
        "score_target": 0.5349,
        "historical_prior": {
            "applied_scope": "same_ticker",
            "sample_count": 15,
            "evaluable_count": 15,
            "next_close_positive_rate": 0.8,
            "next_close_positive_count": 12,
            "next_close_negative_count": 3,
            "next_close_payoff_ratio": 3.7926,
            "next_close_expectancy": 0.0533,
        },
    }
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "snapshot_path": snapshot_path.as_posix(),
            "selected_actions": [selected_row],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        priority_board_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "source_paths": {"snapshot_path": snapshot_path.as_posix()},
            "priority_rows": [selected_row],
        },
    )
    _write_json(
        snapshot_path,
        {
            "trade_date": "2026-05-29",
            "market_state": {
                "regime_gate_level": "crisis",
                "breadth_ratio": 0.284187,
                "position_scale": 0.75,
            },
            "buy_orders": [
                {
                    "ticker": "300408",
                    "shares": 400,
                    "amount": 4000.0,
                }
            ],
            "funnel_diagnostics": {
                "btst_regime_gate_enforcement": {
                    "enforced": True,
                    "gate": "halt",
                    "mode": "enforce",
                    "buy_orders_cleared": True,
                    "buy_orders_cleared_count": 1,
                }
            },
        },
    )
    _write_json(reports_root / "btst_full_report_20260529.json", {"trade_date": "20260529", "next_date": "20260601", "pool_size": 1, "selected_count": 1, "near_miss_count": 0, "high_confidence": []})
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [
                {
                    "trade_date": "2026-05-29",
                    "gate_action": "tradeable",
                    "deployment_mode": "shadow_only",
                    "early_runner_watchlist": [],
                    "early_runner_priority": [],
                    "second_entry_reentry": [],
                }
            ]
        },
    )

    output_dir = tmp_path / "outputs"
    generate_btst_doc_bundle(
        "20260529",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        include_extra_warning_docs=True,
        write_review_ledger=False,
    )

    early_warning_doc = (output_dir / "BTST-20260529-EARLY-WARNING.md").read_text(encoding="utf-8")
    early_warning_card = (output_dir / "BTST-20260529-EARLY-WARNING-CARD.md").read_text(encoding="utf-8")

    assert "当前状态 `confirmable`" in early_warning_doc
    assert "当日上限 `confirmable`" in early_warning_doc
    assert "放行权 `market_gate`" in early_warning_doc
    assert "effective_trade_bias `gate_locked_confirmation_only`" in early_warning_card
    assert "release_authority `market_gate`" in early_warning_card


def test_generate_btst_doc_bundle_prefers_canonical_names_from_sibling_snapshots(tmp_path: Path) -> None:
    """Repair XD/DR-prefixed stock names by looking for canonical names in sibling snapshots."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260529_20260529_live_m2_7_short_trade_only_20260601_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-29",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "selected_actions": [
                {
                    "ticker": "600176",
                    "name": "XD中国巨",
                    "preferred_entry_mode": "intraday_confirmation_only",
                    "historical_prior": {
                        "evaluable_count": 14,
                        "next_close_positive_rate": 0.5,
                        "next_close_payoff_ratio": 0.8748,
                    },
                }
            ],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260529.json",
        {
            "trade_date": "20260529",
            "next_date": "20260601",
            "pool_size": 3339,
            "selected_count": 530,
            "near_miss_count": 578,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {"daily_boards": [{"trade_date": "2026-05-29"}]},
    )
    dirty_summary = report_dir / "data_snapshots" / "600176" / "2026-05-29" / "summary.md"
    dirty_summary.parent.mkdir(parents=True, exist_ok=True)
    dirty_summary.write_text(
        "# 600176（XD中国巨）数据快照 - 2026-05-29\n\n- **股票名称**：XD中国巨\n",
        encoding="utf-8",
    )
    clean_summary = (
        reports_root
        / "paper_trading_20260408_20260408_live_m2_7_short_trade_only_20260409_plan"
        / "data_snapshots"
        / "600176"
        / "2026-04-08"
        / "summary.md"
    )
    clean_summary.parent.mkdir(parents=True, exist_ok=True)
    clean_summary.write_text(
        "# 600176（中国巨石）数据快照 - 2026-04-08\n\n- **股票名称**：中国巨石\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "outputs"
    generate_btst_doc_bundle(
        "20260529",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        include_extra_warning_docs=False,
    )

    llm_doc = (output_dir / "BTST-LLM-20260529.md").read_text(encoding="utf-8")
    assert "600176 中国巨石" in llm_doc
    assert "XD中国巨" not in llm_doc


def test_render_llm_doc_surfaces_payoff_review_lane_when_present() -> None:
    brief = {
        "trade_date": "2026-03-27",
        "next_trade_date": "2026-03-30",
        "selection_target": "short_trade_only",
        "payoff_review_entries": [
            {
                "ticker": "300001",
                "decision": "near_miss",
                "candidate_source": "short_trade_boundary",
                "payoff_review_lane_score": 0.5,
            }
        ],
    }

    text = _render_llm_doc(
        signal_date_compact="20260327",
        brief=brief,
        priority_board={},
        session_summary={},
        semantic_selected=[],
        semantic_watch=[],
        early_runner={"status": "unavailable"},
        selection_snapshot={},
        control_tower={},
        report_mode="formal_execution",
        veto_owner="system",
        section_labels={"llm_execution_title": "正式执行层"},
        report_dir=Path("/tmp/btst"),
        strategy_thresholds={},
        strategy_thresholds_config_path="/tmp/btst_strategy_thresholds.json",
        strategy_thresholds_profile="default",
    )

    assert "## Payoff-first Review Lane" in text
    assert "300001" in text
