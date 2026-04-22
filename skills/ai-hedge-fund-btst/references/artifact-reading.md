# Artifact Reading Guide

Load this file before drafting any BTST output.

## Source priority

1. Rule-based plan: data/reports/btst_full_report_YYYYMMDD.json first, then the matching Markdown report.
2. Multi-agent plan: session_summary.json first, then the files indexed under btst_followup or artifacts.
3. Candidate semantics: btst_next_day_priority_board_latest.json and btst_next_day_trade_brief_latest.json.
4. Execution semantics: btst_premarket_execution_card_latest.json and btst_opening_watch_card_latest.json.
5. Context-only supplements: catalyst_theme_frontier_latest.*, btst_latest_close_validation_latest.*, nightly control tower artifacts.

## Read rules

- Prefer JSON when you need counts, lane labels, hierarchy, or source paths.
- Use Markdown when you need the artifact's own narrative wording, audit summary, or natural-language recommendation.
- If session_summary.json exists, treat it as the path index for btst followup artifacts.
- If btst_full_report.py returns target day N/A on the newest usable date, recompute or verify the real next trading day before writing final documents.
- If session_summary and a downstream artifact disagree, trust the downstream BTST artifact for candidate semantics and trust session_summary for file locations.

## Lane discipline

Keep these layers separate unless the artifacts explicitly merge them:

- primary or selected
- backup or secondary selected
- near_miss watch
- opportunity_pool
- research
- shadow or upstream shadow recall

Do not flatten these layers into one trade list.

## Market-context extraction

Use current-run evidence only:

- audit summary, selected count, rejected count, opportunity pool count
- regime notes, breadth, position scale, or similar risk framing if present
- catalyst or theme frontier when it directly explains sector concentration
- whether the result is narrow, divergent, concentrated, or weak relative to the artifact set in front of you

Do not add generic market commentary that is not supported by the run artifacts.

## Failure handling

- Missing session_summary.json: fall back to btst_*_latest.json or .md files in the report directory.
- Missing JSON but Markdown exists: read the Markdown and avoid unsupported precision.
- Missing reliable next trade date: compute it separately before writing, or stop if it cannot be recovered safely.
