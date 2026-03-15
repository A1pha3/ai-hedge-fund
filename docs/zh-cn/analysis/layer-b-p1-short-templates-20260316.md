# Layer C P1 短版提交模板

文档日期：2026 年 3 月 16 日  
适用范围：需要快速整理 commit message、PR 标题与 PR description 时使用  
详细背景：docs/zh-cn/analysis/layer-b-p1-pr-summary-20260316.md

---

## 1. 推荐 Commit Message

### 单行版

```text
execution: tune Layer C P1 defaults and validate 600519 live replay
```

### 带正文版

```text
execution: tune Layer C P1 defaults and validate 600519 live replay

- change Layer C blend to 0.55/0.45 and investor scale to 0.90
- lower default watchlist threshold from 0.25 to 0.20
- keep avoid threshold at -0.30
- add resumable 600519 live replay and summary tooling
- validate 20260224 pass and 20260226 stay edge-like in live replay
```

---

## 2. 推荐 PR 标题

```text
Tune Layer C P1 defaults and add resumable 600519 live replay validation
```

---

## 3. 推荐 PR Description

```md
## Summary

This change finalizes the current P1 candidate by keeping the scope limited to Layer C and watchlist tuning rather than further expanding Layer B.

- change Layer C blend defaults to 0.55/0.45
- apply investor cohort scale 0.90 before normalization
- lower default watchlist threshold to 0.20
- keep avoid threshold at -0.30
- add resumable 600519 live replay, summary, and doc update scripts

## Why

Previous end-to-end backtests showed that Layer B rule variants increased mid-funnel volume but did not change realized orders or returns. Focused replay then showed that most extra names were suppressed by investor-cohort drag at Layer C, while 600519 behaved like a threshold-edge case.

## Validation

- execution tests: `pytest tests/execution/test_phase4_execution.py -q` => `32 passed`
- offline business regression keeps 8 structural-conflict samples blocked
- live replay `20260224 / 600519`: `score_final = 0.2158`, crosses the 0.20 watchlist threshold
- live replay `20260226 / 600519`: `score_final = 0.1962`, remains edge-like and does not cross 0.20

## Residual Risk

- live replay coverage is still limited to the two 600519 target dates
- broader-window validation is still pending
- occasional upstream data instability may still affect replay runs
```

---

## 4. 中文评审摘要

如果需要在中文评审里快速说明，可以直接使用下面这段：

```text
这次变更没有继续扩大 Layer B，而是把当前最小业务改动收敛到 Layer C 与 watchlist。默认参数改为 blend 0.55/0.45、investor scale 0.90、watchlist 0.20，avoid 阈值继续保持 -0.30。执行层测试和离线业务回归已通过，且 600519 的最小 live replay 已完成：20260224 实际过线，20260226 仍保持边缘不过线。因此，P1 现在可以作为已完成最小 live 补证的候选默认参数进入评审，但更长窗口验证仍待补。
```