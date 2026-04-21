---
name: ai-hedge-fund-btst
description: 当用户在本仓库中用中文提出以下需求时触发：生成BTST次日交易文档、生成明天的BTST交易计划、生成明天的BTST全套文档、生成明天的BTST通俗说明、生成X月X日的BTST交易计划、使用X月X日收盘数据生成次日BTST文档、生成次日短线交易文档。重点匹配结构：BTST + 交易计划|全套文档|通俗说明 + 使用某日收盘数据 或 明天/次日 + 保存到默认目录 或 自定义目录。触发后先询问是否保存到 outputs/YYYYMM/，再运行规则版BTST报告、多智能体短线闭环流程，并产出5份中文Markdown文档。
---

# ai-hedge-fund-btst

This skill packages the full end-to-end BTST plan workflow for this repository:

1. Resolve the latest usable signal date from close data
2. Run the rule-based BTST report
3. Run the multi-agent LLM short-trade pipeline
4. Read the generated artifacts
5. Write five final markdown documents into the selected output directory

Important: strategy runs may be automated, but the final five markdown documents should be written by the agent from the current artifacts, not by a fixed renderer script.

## Trigger Rules

Use this skill when the user asks for either of the following intents, even if they only mention one of them:

- Generate tomorrow's BTST trading plan
- Generate tomorrow's BTST plain-language explanation

When this skill triggers, generate all five final documents unless the user explicitly narrows the scope.

## Required Opening Question

Before running anything, ask one short question:

- 是否保存到默认目录 outputs/YYYYMM/ ？

Rules:

- If the user answers `yes`, use the default directory.
- If the user provides a custom directory, use that directory instead.
- If the user gives both, prefer the explicit custom directory.

Default directory rule:

- Use `outputs/YYYYMM/`, where `YYYYMM` comes from the signal date, not the next trade date.
- Example: signal date `2026-04-16` writes to `outputs/202604/`.

## Date Resolution

If the user does not specify a date:

- Resolve the latest open trading day that already has close data available.
- Resolve the next open trading day after that signal date.

If the user specifies a signal date, use that date and compute the next open trading day from the exchange calendar.

Validation requirements:

- Confirm that close data exists for the signal date before proceeding.
- If close data is not available, stop and tell the user that the signal date is not ready.

## Runtime Environment

Use the repository virtual environment and existing scripts in this repo.

Preferred command prefix:

```bash
.venv/bin/python
```

The workflow relies on `.env` values already configured in the repository.

## Strategy Execution

### 1. Rule-Based BTST Report

Run:

```bash
.venv/bin/python scripts/btst_full_report.py
```

Expected source artifacts:

- `data/reports/btst_full_report_YYYYMMDD.md`
- `data/reports/btst_full_report_YYYYMMDD.json`

Notes:

- The script may print `target day: N/A` on the newest date. In that case, compute the next trading day separately and use the real next trading date in the final documents.

### 2. Multi-Agent LLM Closed-Loop BTST Report

Run the short-trade workflow for the resolved signal date.

Default invocation:

```bash
.venv/bin/python scripts/run_paper_trading.py \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  --selection-target short_trade_only \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir data/reports/paper_trading_YYYYMMDD_YYYYMMDD_live_m2_7_short_trade_only_YYYYMMDD_plan
```

Use the same provider and model defaults unless the user explicitly requests another route.

Expected source artifacts inside the report directory:

- `btst_next_day_trade_brief_latest.md`
- `btst_premarket_execution_card_latest.md`
- `btst_next_day_priority_board_latest.md`
- `btst_opening_watch_card_latest.md`
- `session_summary.json`

If the long-running command pauses for interactive input, ask the user for the required response and continue.

## Final Deliverables

Always write these five markdown files into the chosen output directory. Filenames use the signal date `YYYYMMDD`.

1. `BTST-YYYYMMDD.md`
2. `BTST-LLM-YYYYMMDD.md`
3. `YYYYMMDD-两套交易计划通俗说明.md`
4. `YYYYMMDD-两套交易计划论坛短版.md`
5. `BTST-YYYYMMDD-EXEC-CHECKLIST.md`

Create the output directory if it does not exist.

Do not rely on a canned text generator for these five files. Read the current run artifacts and write the documents case by case.

## Document Requirements

### 1. BTST-YYYYMMDD.md

Purpose:

- Rule-based detailed plan

Must include:

- Signal date and next trade date
- Source report paths
- Market state summary
- Main candidate list with stock code, stock name, why selected, and how to trade the next day
- Watch-only names that should not be chased
- Intraday execution rhythm and hard risk rules

Construction rules:

- Base this document on the rule report artifacts only.
- Do not list the full selected universe. Compress it into a practical main list and watch list.
- Use real factor evidence from the report. Do not invent reasons.

### 2. BTST-LLM-YYYYMMDD.md

Purpose:

- Multi-agent detailed plan

Must include:

- Signal date and next trade date
- Report directory and audit summary
- Primary entry, backup entries, near-miss watchlist, opportunity pool, research or shadow lanes when relevant
- For each formal trade candidate: stock code, stock name, why selected, and how to trade the next day
- Execution ordering and guardrails

Construction rules:

- Prioritize the LLM priority board and premarket execution card semantics.
- Keep the lane boundaries clear: primary, backup, watch, upgrade, research.
- Do not upgrade research or shadow names into formal trades unless the artifacts already did so.

### 3. YYYYMMDD-两套交易计划通俗说明.md

Purpose:

- Full plain-language explanation for a general stock forum audience

Must include:

- A clear comparison of the two strategies
- A plain-language market backdrop section covering the broad index condition, sector heat, and where capital is concentrating
- What overlaps between them
- What should be watched versus traded
- Common mistakes retail traders may make
- A calm, factual conclusion

Writing rules:

- Use plain Chinese
- Avoid unnecessary English jargon
- Do not use hype, certainty claims, or inciting language
- Do not recycle a fixed paragraph template day after day
- The explanation should reflect the actual overlap, tension, and differences in the current run
- The market backdrop should be tied to current artifacts and observable context, not generic daily commentary
- If today's result is narrower, weaker, more concentrated, or more divergent than recent runs, say that directly in natural language

### 4. YYYYMMDD-两套交易计划论坛短版.md

Purpose:

- Short post-ready version derived from the full plain-language explanation

Writing rules:

- Keep it compact and directly postable
- Preserve the same factual tone
- Include one concise market-context sentence covering index tone, hot sectors, or the current capital focus when that context materially affects execution
- Emphasize the single takeaway and the execution attitude
- Rewrite it from the current run, not by mechanically compressing yesterday's wording

### 5. BTST-YYYYMMDD-EXEC-CHECKLIST.md

Purpose:

- Intraday execution checklist for the next morning

Must include:

- Opening principles
- 09:20-09:25 checks
- 09:25-09:35 first decision point
- 09:35-10:00 second decision point
- 10:00 onward handling
- Intraday discipline rules
- Actual execution ordering

Construction rules:

- Use the multi-agent plan as the primary execution authority.
- Rule-based strong names may be listed only as peripheral observation unless the LLM plan also promotes them.

## Writing Constraints

Apply these rules across all five files:

- Use Chinese throughout.
- Use stock code plus stock name together whenever a stock is introduced.
- Do not invent stock names, reasons, or execution rules that are not supported by artifacts.
- If a field is missing, omit the claim instead of guessing.
- Keep the documents actionable and readable.
- Prefer fresh phrasing over repeated stock wording when writing the two explanation-style documents.
- Reuse structure only when helpful; do not make the通俗说明and论坛短版sound like fixed templates.

## Minimum Verification

Before finishing:

- Confirm all five files exist in the chosen directory.
- Confirm the filenames match the signal date.
- Confirm the documents mention the real next trading day, not `N/A`.

## Response Pattern After Completion

In the final response:

- State where the five files were saved.
- Summarize the main rule-based focus and the main multi-agent focus in one short paragraph.
- Mention whether any part of the run required manual intervention.