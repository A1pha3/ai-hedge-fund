# Artifact Reading Guide

Load this file before drafting any BTST output.

## Source priority

0. **operator_summary.json** (P0D 2026-06-04): 如果存在且 `schema_version=1`，优先读取此文件获取运行状态、市场门控、执行语义、early-runner 状态和 artifact 路径索引。
   - `summary_status=degraded` 时先说明降级原因再继续。
   - `summary_status=failed` 时停止正常流程，报告 blocker。
   - 此文件不存在或不支持时，回退到以下 1-5 的逐文件读取流程。
   - **不得**让 `operator_summary.json` 覆盖 canonical execution contract；它只是派生视图。
1. Rule-based plan: data/reports/btst_full_report_YYYYMMDD.json first, then the matching Markdown report.
2. Multi-agent plan: session_summary.json first, then the files indexed under btst_followup or artifacts.
3. Candidate semantics: btst_next_day_priority_board_latest.json and btst_next_day_trade_brief_latest.json.
4. Execution semantics: btst_premarket_execution_card_latest.json and btst_opening_watch_card_latest.json.
5. Context-only supplements: catalyst_theme_frontier_latest.*, btst_latest_close_validation_latest.*, nightly control tower artifacts.

## Read rules

- Prefer JSON when you need counts, lane labels, hierarchy, or source paths.
- Use Markdown when you need the artifact's own narrative wording, audit summary, or natural-language recommendation.
- If session_summary.json exists, treat it as the path index for btst followup artifacts and the authority for multi-agent provenance.
- Read optimization_profile_resolution from session_summary.json before inferring optimized-profile provenance. Prefer it over directory names or human assumptions when deciding whether the run used the latest optimized manifest or default fallback.
- If optimization_profile_resolution is missing, fall back to legacy short_trade_target_profile_name and short_trade_target_profile_overrides fields without inventing optimized provenance that the artifacts do not prove.
- Do not claim an optimized run unless session_summary.json or downstream artifacts actually support it. If fallback happened, surface the fallback reason where relevant in the final docs.
- If btst_full_report.py returns target day N/A on the newest usable date, recompute or verify the real next trading day before writing final documents.
- If session_summary and a downstream artifact disagree, trust the downstream BTST artifact for candidate semantics and trust session_summary for file locations.

## Alpha 统计提取

必须从当前 run artifacts 提取或明确缺失：

- `sample_size`：样本笔数 / 票数 / 事件数；没有就写 `artifacts not available`。
- `interval_or_shrinkage_caution`：
  - 优先读取 Wilson interval、置信区间或 artifacts 已给出的统计区间。
  - 若无显式区间但有样本量与胜率，只能给“样本偏小，需收缩看待点估计”这类谨慎语。
  - 若连样本量都拿不到，直接写 `统计区间 artifacts not available`。
- `payoff_quality`：盈亏比、平均赚亏结构、期望值、回撤/尾部代价等现成字段。
- `win_rate_vs_payoff_divergence`：明确判断“高胜率但赔率弱 / 胜率一般但赔率更厚 / 两者一致 / 无法判断”。

禁止把单一胜率数字直接写成稳定 edge；必须同时交代样本与赔率质量。

## Beta 执行提取

从 `btst_premarket_execution_card_latest.json`、`btst_opening_watch_card_latest.json` 和同层 execution artifacts 中抽取：

- `entry_trigger`：什么确认后才能执行。
- `cancel_trigger`：什么情况下直接不做。
- `downgrade_or_upgrade_rule`：何时从正式执行层降为观察，或从优先复审回到仅观察。
- `time_window`：如 09:20-09:25 / 09:25-09:35 / 09:35-10:00 / 10:00 onward。
- `cost_constraints`：追价、滑点、仓位、槽位、成交成本上限等 artifacts 已支持的约束。

若某项 execution 语义拿不到，不要用泛化交易常识补位；直接写 `相关 execution artifacts not available`。

## Lane discipline

Keep these layers separate unless the artifacts explicitly merge them:

- primary or selected
- backup or secondary selected
- near_miss watch
- opportunity_pool
- research
- shadow or upstream shadow recall

Do not flatten these layers into one trade list.

## Gamma 环境提取

Use current-run evidence only:

- market gate / gate enforcement / report_mode
- audit summary, selected count, rejected count, opportunity pool count
- regime notes, breadth, position scale, or similar risk framing if present
- sector / theme frontier, concentration, leader-follower structure
- 赚钱效应、情绪、承接、强弱切换等 artifacts 已给出的语义
- whether the result is narrow, divergent, concentrated, weak, or sentiment-supported relative to the artifact set in front of you

If the current run cannot support market / sector / 赚钱效应 commentary, say one of:

- `大盘环境 artifacts not available`
- `板块 / 题材 context weak`
- `赚钱效应 / 情绪 artifacts not available`

Do not add generic market commentary that is not supported by the run artifacts.

## Failure handling

- Missing session_summary.json: fall back to btst_*_latest.json or .md files in the report directory.
- Missing JSON but Markdown exists: read the Markdown and avoid unsupported precision.
- Missing reliable next trade date: compute it separately before writing, or stop if it cannot be recovered safely.
