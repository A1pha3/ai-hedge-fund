# Final Document Spec

Load this file before drafting the 5 core BTST files.

## Output set

Use the signal date YYYYMMDD in every filename:

1. BTST-YYYYMMDD.md
2. BTST-LLM-YYYYMMDD.md
3. YYYYMMDD-两套交易计划通俗说明.md
4. YYYYMMDD-两套交易计划论坛短版.md
5. BTST-YYYYMMDD-EXEC-CHECKLIST.md

When scheme A is active or the user explicitly requests early-runner warning outputs, also generate:

6. BTST-YYYYMMDD-EARLY-WARNING.md
7. BTST-YYYYMMDD-EARLY-WARNING-CARD.md

## Per-file requirements

| File | Purpose | Must include | Source priority |
| --- | --- | --- | --- |
| BTST-YYYYMMDD.md | Rule-based detailed plan | signal date, next trade date, source report paths, market state, main candidates, watch-only list, intraday rhythm, hard risk rules, **胜率/赔率诊断卡（Alpha）**, **执行触发/取消/升级/降级矩阵（Beta）**, **大盘-板块-赚钱效应环境卡（Gamma）** | btst_full_report_YYYYMMDD.json then Markdown |
| BTST-LLM-YYYYMMDD.md | Multi-agent detailed plan | signal date, next trade date, report dir, audit summary, primary or selected names, backups, near-miss or opportunity context when relevant, execution ordering, guardrails, **胜率/赔率诊断卡（Alpha）**, **执行触发/取消/升级/降级矩阵（Beta）**, **大盘-板块-赚钱效应环境卡（Gamma）**, actual profile_name when present, whether overrides were applied, provenance source from session_summary.json when explicitly available, explicit fallback reason when optimization_profile_resolution.mode is default_fallback, early-runner status, overlap highlighting when supported | session_summary.json + btst brief, priority board, execution card |
| YYYYMMDD-两套交易计划通俗说明.md | Full plain-language explanation | strategy comparison, plain-language market backdrop, overlap and divergence, what is for trade vs watch, common retail mistakes, calm conclusion, 用白话解释 Alpha 统计质量结论与 Gamma 市场/板块语境, actual multi-agent profile_name when present, whether overrides were applied, provenance source from session_summary.json when explicitly available, explicit fallback reason when optimization_profile_resolution.mode is default_fallback, overlap-highlighting explanation when supported | both rule and multi-agent artifacts |
| YYYYMMDD-两套交易计划论坛短版.md | Compact post-ready version | one clear takeaway, compact trade-vs-watch framing, one market-context sentence when materially relevant, 一句统计质量判断（样本/赔率/分化）, factual tone, compact overlap-highlighting note when supported | derive from current-run plain-language explanation, but rewrite rather than mechanically compress |
| BTST-YYYYMMDD-EXEC-CHECKLIST.md | Next-morning execution checklist | opening principles, 09:20-09:25, 09:25-09:35, 09:35-10:00, 10:00 onward, intraday discipline, actual execution order, **执行触发/取消/升级/降级矩阵（Beta）**（逐票展开到触发/取消/升级/降级/回补/成本约束）, actual profile_name when present, whether overrides were applied, provenance source from session_summary.json when explicitly available, explicit fallback reason when optimization_profile_resolution.mode is default_fallback, intersection-priority review when supported | multi-agent artifacts first; rule names only as peripheral observation unless promoted by the LLM plan |

### Early-warning add-on outputs

- `BTST-YYYYMMDD-EARLY-WARNING.md` must summarize early-runner priority/watchlist/second-entry lanes plus any only-early-runner supplemental watch names.
- `BTST-YYYYMMDD-EARLY-WARNING-CARD.md` must compress the early-runner state into a quick-read card for premarket scanning.
- If early-runner artifacts are `stale_fallback` or `unavailable`, these two files must still be generated when requested, but must explicitly say the overlay is reference-only or unavailable; they must not silently disappear and must not promote early-runner names into formal execution.

## Required diagnostic blocks

For `BTST-YYYYMMDD.md` / `BTST-LLM-YYYYMMDD.md`, keep these exact named blocks:

1. `胜率/赔率诊断卡（Alpha）`
   - sample size
   - Wilson interval 或 shrinkage-style caution
   - payoff / 盈亏比质量
   - 胜率与赔率是否分化
2. `执行触发/取消/升级/降级矩阵（Beta）`
   - 至少覆盖：股票、所属层、计划动作、触发条件、取消条件、观察升级条件、降级条件、回补条件（如有）、时段、成本/仓位约束
3. `大盘-板块-赚钱效应环境卡（Gamma）`
   - market gate / gate enforcement
   - 大盘风险框架
   - 板块 / 题材 / 情绪 / 赚钱效应支撑
   - 对保守 / 激进执行倾向的实际含义

If the current artifacts cannot support one of the fields above, write `artifacts not available` or `context weak` instead of generic filler. Do NOT silently omit these three required blocks.

For `BTST-YYYYMMDD-EXEC-CHECKLIST.md`, `执行触发/取消/升级/降级矩阵（Beta）` is mandatory; Alpha / Gamma evidence may be referenced in summary bullets, but the checklist does not need to repeat all three named blocks verbatim.

## Global writing rules

- Write all 5 documents in Chinese.
- Use stock code plus stock name together whenever a stock is introduced.
- Never invent stock names, reasons, or execution rules.
- If a field is missing, omit it instead of guessing, **except** for the three required blocks above; those must stay visible and explicitly say `artifacts not available` or `context weak` when support is missing.
- Keep the two explanation-style files fresh; do not reuse a fixed daily paragraph template.
- If today's result is narrower, weaker, more concentrated, or more divergent than recent BTST runs, say so directly in natural language when the artifacts support it.
- Do not dump the full universe of candidates when a practical main list and watch list are enough.
- Keep the tone factual and calm; no hype, certainty claims, or inciting language.
- If early-runner is integrated, state whether overlap highlighting is based on the exact trade date or only on stale fallback.
- If a same-day profile comparison and pretrade decision card exist, BTST-YYYYMMDD.md and BTST-LLM-YYYYMMDD.md must both include the same one-paragraph Chinese conclusion about whether today leans conservative or aggressive.
- When that shared conclusion exists, it must cite both:
  - one Alpha reason（统计质量 / 胜率赔率）
  - one Gamma reason（市场 / 板块 / gate）

## Document-specific boundaries

- BTST-YYYYMMDD.md must stay anchored to the rule report only.
- BTST-LLM-YYYYMMDD.md must preserve lane boundaries; do not silently upgrade research or shadow names.
- For BTST-LLM-YYYYMMDD.md, YYYYMMDD-两套交易计划通俗说明.md, and BTST-YYYYMMDD-EXEC-CHECKLIST.md, state only the profile/provenance details that current artifacts support; do not invent optimized provenance.
- Exact-date early-runner overlaps may be highlighted as intersection-priority watch items, but stale-fallback overlaps must stay at reference-only wording.
- For older runs without optimization_profile_resolution, use legacy short_trade_target_profile_name and short_trade_target_profile_overrides when they exist. If those legacy fields are the only profile evidence, disclose the known profile/overrides and describe provenance as unavailable or not explicit rather than fabricated.
- The forum short version must be directly postable, but still reflect the current run rather than yesterday's wording.
- The execution checklist must follow the multi-agent hierarchy, not a blended or manually re-ranked list.
- The execution checklist's per-stock matrix must be concrete enough that each row answers: `何时能做 / 何时不做 / 何时从观察升级 / 做错后如何降级 / 最多付出什么成本`。
- When a decision card exists, the shared bridge conclusion may guide framing, but it must not overwrite rule provenance in BTST-YYYYMMDD.md or silently upgrade names in BTST-LLM-YYYYMMDD.md.

## P0D additions (2026-06-04)

### operator_summary.json integration

When `operator_summary.json` exists alongside the 5 core documents:
- Treat it as the compressed run-status view; do NOT let it override canonical execution contracts.
- If `summary_status` is `degraded`, state the degradation reason before proceeding.
- If `summary_status` is `failed`, do not draft normal deliverables; surface the blocker and stop.
- The ONE-PAGER (`BTST-YYYYMMDD-ONE-PAGER.md`) is derived from `operator_summary.json`, not from re-reading multiple artifacts.

### ONE-PAGER

- Rendered from validated `operator_summary.json` only.
- Must NOT contain fields unavailable at the current `decision_phase` (e.g., no T+1 results in `post_close_plan`).
- Must say "证据不足" when `incremental_evidence.status` is insufficient — never "无增量价值".

### Profile comparison scope

- `comparison_scope` is always `doc_bundle_rendering` (P0B).
- `effective_decision_diff` is `False` until P2 wires upstream routing.
- Do NOT describe doc rendering differences as verified strategy advantages.

### Bridge markers

- The profile decision bridge uses managed HTML comment markers (`<!-- BTST_PROFILE_BRIDGE_BEGIN -->` / `<!-- BTST_PROFILE_BRIDGE_END -->`).
- Re-running replaces the existing block; no duplicate bridges.
