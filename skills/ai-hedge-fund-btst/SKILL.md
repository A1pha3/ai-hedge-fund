---
name: ai-hedge-fund-btst
description: 在本仓库中处理中文 BTST 次日文档请求时触发。典型触发语义：BTST + 明天/次日/某日收盘数据 + 交易计划|全套文档|通俗说明|次日短线文档；也支持默认目录或自定义目录要求。触发后先询问是否保存到 outputs/YYYYMM/，再运行规则版 btst_full_report.py 与 short_trade_only 的 paper trading 流程，并基于当次产物写出 5 份中文 Markdown。关键词：BTST，明天交易计划，次日交易计划，全套文档，通俗说明，收盘数据，默认目录，自定义目录。
---

# ai-hedge-fund-btst

This skill runs the repo's BTST next-day document workflow.

## Default behavior

- Generate all 5 final documents unless the user explicitly narrows the scope.
- Ask exactly one short opening question before any command:
  - 是否保存到默认目录 outputs/YYYYMM/？
- If the user gives a custom directory, use it.
- If the user gives both default and custom, custom wins.
- The default directory is outputs/YYYYMM/, where YYYYMM comes from the signal date, not the next trade date.

## Workflow

1. Resolve dates.
  - If the user specifies a signal date, use it.
  - Otherwise auto-resolve the latest open trade date that already has close data.
  - Always compute the real next trade date.
  - Stop if close data for the signal date is unavailable.
  - Preferred rule-report entry:

  ```bash
  .venv/bin/python scripts/btst_full_report.py [--trade-date YYYYMMDD]
  ```

2. Run the rule-based BTST report.
  - Expected artifacts:
    - data/reports/btst_full_report_YYYYMMDD.md
    - data/reports/btst_full_report_YYYYMMDD.json

3. Run the multi-agent BTST pipeline.
  - Use short_trade_only for this skill.
  - Keep MiniMax / MiniMax-M2.7 unless the user explicitly overrides model routing.
  - Default this workflow to the latest approved optimized profile manifest when it is ready.
  - For implicit short_trade_only runs that resolve a ready optimized manifest, the default BTST multi-agent path may auto-apply the governed P5 precision gate at runtime.
  - If the user supplies explicit short-trade profile inputs, treat them as an intentional bypass of manifest autoselect and do not label the run as optimized unless the artifacts explicitly support that claim.
  - Default invocation:

  ```bash
  .venv/bin/python scripts/run_paper_trading.py \
    --start-date YYYY-MM-DD \
    --end-date YYYY-MM-DD \
    --selection-target short_trade_only \
    --optimized-profile-manifest data/reports/btst_latest_optimized_profile.json \
    --model-provider MiniMax \
    --model-name MiniMax-M2.7 \
    --output-dir data/reports/paper_trading_YYYYMMDD_YYYYMMDD_live_m2_7_short_trade_only_YYYYMMDD_plan
  ```

4. Read current artifacts.
   - MANDATORY: load references/artifact-reading.md before drafting.
   - Treat session_summary.json as the source of truth for artifact paths and optimization-profile provenance.
   - Read optimization_profile_resolution from session_summary.json before inferring whether the run used the latest optimized manifest or a default fallback.
   - If session_summary.json shows default fallback, the final docs must say so explicitly instead of silently presenting the run as optimized.
   - If `data/reports/btst_round89_rollout_assessment.json`, `data/reports/btst_trend_continuation_rollout_assessment.json`, `data/reports/btst_admission_edge_replay_validation.json`, or `data/reports/btst_strict_objective_gate.json` exist, read them before describing any optimized profile as production-ready.
   - If `data/reports/p9_candidate_entry_rollout_governance_*.json`, `data/reports/btst_candidate_entry_window_scan_*.json`, or `data/reports/btst_candidate_entry_payoff_validation*.json` exist, read the newest matching files before describing any watchlist-filter / candidate-entry cleanup rule. Treat `lane_status=shadow_rollout_review_ready` as shadow-only governance evidence, not as a default-upgrade approval.
   - If `docs/prompt/generate_file/*.md` contains BTST validation docs, read the most recent BTST-relevant ones before drafting. Use them only to explain already-validated runtime / rollout behavior; never let them override current artifacts or upgrade a blocked profile into an active one.
   - Prefer JSON artifacts for structure and Markdown artifacts for prose fallback.

5. Write final documents.
  - MANDATORY: load references/final-doc-spec.md before drafting the 5 output files.
  - Create the output directory if needed.
  - Final documents must be written from current artifacts, not from a fixed template renderer.

6. Verify before finishing.
  - All requested files exist.
  - Filenames use the signal date, not the next trade date.
  - All documents mention the real next trade date, never N/A.

## Hard rules

- Final documents must be Chinese.
- Use stock_code + stock_name whenever a stock is introduced.
- Never invent stock names, reasons, rankings, or execution rules.
- Never promote opportunity pool, research, shadow, or near-miss names into formal trades unless the artifacts already promoted them.
- Use the rule report as the authority for BTST-YYYYMMDD.md.
- Use the multi-agent plan as the execution authority for BTST-LLM-YYYYMMDD.md and BTST-YYYYMMDD-EXEC-CHECKLIST.md.
- Keep market backdrop tied to current artifacts and observable run context; no generic daily market commentary.
- If a field is missing, omit the claim instead of guessing.
- If a long-running command pauses for interactive input, ask the user for the required answer and continue.
- If source artifacts cannot be produced, stop and report the blocker instead of fabricating deliverables.
- Never treat the report directory name as the source of truth when session_summary.json exists; reruns can change suffixes while session_summary keeps the real artifact index.
- Never claim an optimized-profile run unless session_summary.json or downstream artifacts support that provenance.
- If optimization_profile_resolution reports mode=default_fallback, surface the fallback state and reason where the final docs describe multi-agent execution provenance.
- If Round 89 rollout assessment, trend-continuation rollout assessment, admission-edge replay validation, or strict-objective gate artifacts say `hold` or `runtime_replay_required_before_conclusion`, surface that status explicitly instead of presenting the profile as an active upgrade.
- If candidate-entry rollout governance artifacts say `shadow_rollout_review_ready`, `blocked_pending_additional_shadow_execution_evidence`, or otherwise keep the rule out of default upgrade, describe it only as a governed shadow / review-ready entry-cleaning rule. Do not present it as an active default profile promotion.
- If candidate-entry window scan artifacts show `preserve_misfire_report_count == 0` and multi-window focus hits, you may mention that the weak-structure rule has cross-window support for shadow review, but you must still keep `300394`-style preserve anchors unfiltered and state that default adoption remains blocked.
- If candidate-entry rollout governance artifacts also show `execution_verdict=focus_ticker_execution_support_with_separation`, you may describe that as supportive shadow execution evidence: the target weak-structure ticker stayed in opportunity/rejected while other non-focus `watchlist_filter_diagnostics` names still reached selected/near_miss. Even then, keep the wording at shadow-review / blocked-default level.
- If candidate-entry payoff validation artifacts say `keep_baseline_count > 0` or recommend that baseline should remain the default, surface that explicitly: the weak-structure rule may still be useful as shadow entry cleanup, but it has not earned default promotion on actionable payoff evidence.
- If the newest candidate-entry payoff validation artifact uses `variant_structural_overrides` with `trend_acceleration <= 0.37` and shows `keep_baseline_count = 0`, `variant_supports_t1_count = 0`, and cleanup / false-negative-relief behavior, describe it as a **safer shadow refinement** of the weak-structure cleanup rule. Do not present it as a payoff-validated default upgrade, and make clear that it removed the negative actionable window without yet earning direct actionable uplift.
- If strict-objective gate artifacts show rejected or blocked names outperforming the tradeable surface, mention that rollout is still blocked by objective-fit evidence rather than framing the variant as validated.
- If validated BTST docs under `docs/prompt/generate_file/` describe win-rate-first precision tightening or rollout governance, use them to explain why a profile remains blocked or why selected-lane precision is stricter, but do not turn those docs into standalone evidence when the current run artifacts disagree.
- For governed precision adoption, final Chinese docs may mention the auto-applied P5 precision gate only when `session_summary.json` and downstream artifacts explicitly confirm that the runtime path used it.

## Optional context

- session_summary.json often contains both artifacts and btst_followup indexes. Use it before guessing filenames.
- catalyst_theme_frontier_latest.*, btst_latest_close_validation_latest.*, and nightly control tower artifacts can help explain concentration, lane pressure, or watchlist structure, but they do not replace the main BTST sources.
- candidate-entry frontier / window-scan / rollout-governance artifacts help explain whether a weak-structure entry-cleaning rule is merely research, shadow-review ready, or still blocked by preserve-misfire / rollout evidence.
- docs/prompt/generate_file/ may contain dated Chinese validation notes for approved BTST runtime / governance improvements. They are interpretation aids, not substitutes for current run outputs.

## Lazy loading

- Load references/artifact-reading.md before reading run outputs.
- Load references/final-doc-spec.md before drafting the 5 final files.
- Load references/trigger-examples.md only when the user asks how to invoke the skill or the request wording is ambiguous.
- Do not load 使用说明.md or scripts/install_symlink.sh during normal execution.

## Completion response

- State where the files were saved.
- Summarize the main rule-based focus and the main multi-agent focus in one short paragraph.
- Mention whether any manual intervention was required.
