# Final Document Spec

Load this file before drafting the 5 final BTST files.

## Output set

Use the signal date YYYYMMDD in every filename:

1. BTST-YYYYMMDD.md
2. BTST-LLM-YYYYMMDD.md
3. YYYYMMDD-两套交易计划通俗说明.md
4. YYYYMMDD-两套交易计划论坛短版.md
5. BTST-YYYYMMDD-EXEC-CHECKLIST.md

## Per-file requirements

| File | Purpose | Must include | Source priority |
| --- | --- | --- | --- |
| BTST-YYYYMMDD.md | Rule-based detailed plan | signal date, next trade date, source report paths, market state, main candidates, watch-only list, intraday rhythm, hard risk rules | btst_full_report_YYYYMMDD.json then Markdown |
| BTST-LLM-YYYYMMDD.md | Multi-agent detailed plan | signal date, next trade date, report dir, audit summary, primary or selected names, backups, near-miss or opportunity context when relevant, execution ordering, guardrails | session_summary.json + btst brief, priority board, execution card |
| YYYYMMDD-两套交易计划通俗说明.md | Full plain-language explanation | strategy comparison, plain-language market backdrop, overlap and divergence, what is for trade vs watch, common retail mistakes, calm conclusion | both rule and multi-agent artifacts |
| YYYYMMDD-两套交易计划论坛短版.md | Compact post-ready version | one clear takeaway, compact trade-vs-watch framing, one market-context sentence when materially relevant, factual tone | derive from current-run plain-language explanation, but rewrite rather than mechanically compress |
| BTST-YYYYMMDD-EXEC-CHECKLIST.md | Next-morning execution checklist | opening principles, 09:20-09:25, 09:25-09:35, 09:35-10:00, 10:00 onward, intraday discipline, actual execution order | multi-agent artifacts first; rule names only as peripheral observation unless promoted by the LLM plan |

## Global writing rules

- Write all 5 documents in Chinese.
- Use stock code plus stock name together whenever a stock is introduced.
- Never invent stock names, reasons, or execution rules.
- If a field is missing, omit it instead of guessing.
- Keep the two explanation-style files fresh; do not reuse a fixed daily paragraph template.
- If today's result is narrower, weaker, more concentrated, or more divergent than recent BTST runs, say so directly in natural language when the artifacts support it.
- Do not dump the full universe of candidates when a practical main list and watch list are enough.
- Keep the tone factual and calm; no hype, certainty claims, or inciting language.

## Document-specific boundaries

- BTST-YYYYMMDD.md must stay anchored to the rule report only.
- BTST-LLM-YYYYMMDD.md must preserve lane boundaries; do not silently upgrade research or shadow names.
- The forum short version must be directly postable, but still reflect the current run rather than yesterday's wording.
- The execution checklist must follow the multi-agent hierarchy, not a blended or manually re-ranked list.
