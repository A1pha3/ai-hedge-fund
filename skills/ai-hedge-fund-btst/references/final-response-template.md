# Final Response Template

Load this file before sending the final Chinese reply when BTST deliverables are ready.

## Top summary

If a same-day decision card exists, the final reply must start with this exact order:

1. `今日执行倾向`
2. `核心理由`
3. `文件位置`
4. `主线摘要`
5. `方案 A 状态` (only when scheme A is active)

## Required wording rules

- Reuse the same conclusion already written in `BTST-YYYYMMDD.md` and `BTST-LLM-YYYYMMDD.md`.
- Do not invent a new conservative/aggressive judgment in the final reply.
- Keep the non-file-location summary compact. Excluding `文件位置`, aim for roughly 4-6 short bullets total; `文件位置` may use its own short list.
- The `核心理由` section should keep only the 1-2 strongest factors, but when a decision card exists it must include:
  - 1 条 **统计质量理由**（样本 / 区间谨慎 / 胜率赔率质量 / 是否分化）
  - 1 条 **市场或 gate 理由**（大盘 / 板块 / 赚钱效应 / market gate）
- `intersection advantage` / `only early-runner pressure` / `second-entry interference` can be cited only when they are one of the strongest supported factors, not as automatic filler.
- If one dimension lacks artifact support, say `artifacts not available` rather than inventing commentary.
- The `文件位置` section should list the most useful outputs first:
  - decision card
  - BTST-YYYYMMDD.md
  - BTST-LLM-YYYYMMDD.md
  - EXEC-CHECKLIST

## Minimal template

```md
**今日执行倾向**
- 今天更偏 `conservative|aggressive`

**核心理由**
- 统计质量：样本 / 区间谨慎 / 胜率赔率质量中的最关键 1 条
- 市场 / 板块 / gate：最关键 1 条

**文件位置**
- 决策卡：...
- 规则版：...
- 多智能体版：...
- 执行清单：...

**主线摘要**
- 规则版主线一句话
- 多智能体主线一句话
- 若存在决策卡，这两句不得与顶部执行倾向冲突

**方案 A 状态**
- 当前是 `exact|stale_fallback|unavailable`
- 交集票是优先复审还是历史参考
```

## Fallback

If there is no decision card, skip `今日执行倾向` and `核心理由`, then start from `文件位置`.

## P0D additions (2026-06-04)

### operator_summary.json awareness

If `operator_summary.json` exists:
- Check `summary_status` first. If `degraded`, explain the reason before any trading advice.
- If `failed`, stop normal deliverables and surface the blocker instead of continuing into trading advice.
- Reference the `decision_id` for traceability.
- Do NOT let the summary override canonical execution contracts or session_summary provenance.

### ONE-PAGER reference

- If `BTST-YYYYMMDD-ONE-PAGER.md` was generated, mention it in `文件位置` after the decision card.
- The ONE-PAGER is a quick-read summary; it does NOT replace the 5 core documents.

### Profile comparison scope

- Always state that profile comparison scope is `doc_bundle_rendering` and `effective_decision_diff` is `False`.
- Do NOT claim any profile has been verified as strategically superior.
- When writing `今日执行倾向`, if `dominant_reason_type=no_effective_profile_diff`, state that the choice defaults to conservative as risk baseline — not because it has been proven better.
- `今日执行倾向` 一旦存在，最终回复必须与决策卡、规则版文档、多智能体文档保持同一句结论；不能在回复里换成另一套保守/激进判断。

### Incremental evidence

- When mentioning early-runner contribution, check `incremental_evidence.status`.
- If `insufficient`: say "证据不足" — never "无增量价值" or "无贡献".
- If `sufficient` or `partial`: cite the sample count and win rate from the evidence.
