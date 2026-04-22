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
  - Default invocation:

  ```bash
  .venv/bin/python scripts/run_paper_trading.py \
    --start-date YYYY-MM-DD \
    --end-date YYYY-MM-DD \
    --selection-target short_trade_only \
    --model-provider MiniMax \
    --model-name MiniMax-M2.7 \
    --output-dir data/reports/paper_trading_YYYYMMDD_YYYYMMDD_live_m2_7_short_trade_only_YYYYMMDD_plan
  ```

4. Read current artifacts.
  - MANDATORY: load references/artifact-reading.md before drafting.
  - Prefer session_summary.json as the source of truth for artifact paths.
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

## Optional context

- session_summary.json often contains both artifacts and btst_followup indexes. Use it before guessing filenames.
- catalyst_theme_frontier_latest.*, btst_latest_close_validation_latest.*, and nightly control tower artifacts can help explain concentration, lane pressure, or watchlist structure, but they do not replace the main BTST sources.

## Lazy loading

- Load references/artifact-reading.md before reading run outputs.
- Load references/final-doc-spec.md before drafting the 5 final files.
- Load references/trigger-examples.md only when the user asks how to invoke the skill or the request wording is ambiguous.
- Do not load 使用说明.md or scripts/install_symlink.sh during normal execution.

## Completion response

- State where the files were saved.
- Summarize the main rule-based focus and the main multi-agent focus in one short paragraph.
- Mention whether any manual intervention was required.