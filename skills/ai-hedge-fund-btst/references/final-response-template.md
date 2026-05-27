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
- Keep the top summary compact. It should fit in 4-6 short bullets.
- The `核心理由` section should name only the 1-2 strongest factors from:
  - intersection advantage
  - only early-runner pressure
  - second-entry interference
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
- 交集票 / only early-runner / second-entry 中最关键的 1-2 条

**文件位置**
- 决策卡：...
- 规则版：...
- 多智能体版：...
- 执行清单：...

**主线摘要**
- 规则版主线一句话
- 多智能体主线一句话

**方案 A 状态**
- 当前是 `exact|stale_fallback|unavailable`
- 交集票是优先复审还是历史参考
```

## Fallback

If there is no decision card, skip `今日执行倾向` and `核心理由`, then start from `文件位置`.
