from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_doc_bundle import (
    _render_action_matrix_sections,
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

    assert "强势\\|确认" in rendered
    assert "先等确认<br>再执行" in rendered


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
    assert "- 主票：`300054`" in checklist_doc
    assert "- 交易倾向：`confirmation_only`" in checklist_doc
    assert "## 当前策略阈值基线" in checklist_doc
    assert "## 正式执行动作矩阵" in checklist_doc
    assert "### 300054 鼎龙股份" in checklist_doc
    assert "| 开盘强且延续确认 | 等待盘中延续确认后再执行，不做开盘无确认追价。 |" in checklist_doc
    assert "| 触发失效条件 | 若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。 |" in checklist_doc
    assert "## Governed Rollout 观察" in checklist_doc
    assert "execution_eligible_delta" in checklist_doc
    assert "## 交集优先复审" in checklist_doc
    assert "## 回补机会层" in checklist_doc
    assert "交集优先：`300054 鼎龙股份`" in checklist_doc
    assert "Early Runner 补充复审：`603725 天安新材`" in checklist_doc
    assert "Second Entry / Reentry：`605500 森林包装`" in checklist_doc
    assert "说明：胜率中性偏强，盈亏比站上 1.00，赚钱时大体能覆盖亏损。" in checklist_doc
    early_warning_doc = (output_dir / "BTST-20260526-EARLY-WARNING.md").read_text(encoding="utf-8")
    assert "## 当前策略阈值基线" in early_warning_doc
    assert "## 交集票高亮" in early_warning_doc
    assert "## Priority" in early_warning_doc
    assert "605500" in early_warning_doc
    assert "说明：胜率中性偏强，盈亏比站上 1.00，赚钱时大体能覆盖亏损。" in early_warning_doc


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
    assert result["strategy_thresholds_config_path"].endswith(
        "config/btst_strategy_thresholds_aggressive.json"
    )
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
    card_payload = json.loads(Path(result["decision_card_json_path"]).read_text(encoding="utf-8"))
    assert card_payload["action_bias"] == "偏保守执行"
    assert card_payload["intersection_delta_vs_runner_up"] == 1
    card_markdown = Path(result["decision_card_md_path"]).read_text(encoding="utf-8")
    assert "交易前决策卡" in card_markdown
    assert "推荐 profile：`conservative`" in card_markdown
    bridge_doc = (output_dir / "conservative" / "BTST-20260526.md").read_text(encoding="utf-8")
    assert "## 今日执行倾向" in bridge_doc
    assert "今日更偏：`conservative`" in bridge_doc
    bridge_llm_doc = (output_dir / "aggressive" / "BTST-LLM-20260526.md").read_text(encoding="utf-8")
    assert "## 今日执行倾向" in bridge_llm_doc


def test_generate_btst_doc_bundle_marks_stale_overlap_as_reference_only(tmp_path: Path) -> None:
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
                        }
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
