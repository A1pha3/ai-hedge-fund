# Layer C P1 变更提交说明

文档日期：2026 年 3 月 16 日  
适用范围：默认 CLI / backtester pipeline 的 Layer C + watchlist 最小变更  
关联主文档：docs/zh-cn/analysis/layer-b-rule-variant-validation-20260312.md

---

## 1. 这次改动做了什么

本次提交不再继续扩大 Layer B，而是把最小业务变更收敛到 Layer C 与 watchlist：

1. Layer C 融合权重默认从 `0.40 / 0.60` 调整到 `0.55 / 0.45`
2. investor cohort 默认缩放到 `0.90`
3. watchlist 默认阈值从 `0.25` 下调到 `0.20`
4. avoid 阈值保持 `-0.30`，不放松结构性强负样本的拦截语义

对应代码范围：

1. `src/execution/layer_c_aggregator.py`
2. `src/execution/daily_pipeline.py`
3. `tests/execution/test_phase4_execution.py`
4. `scripts/replay_layer_c_agent_contributors.py`
5. `scripts/run_live_replay_600519_p1.sh`
6. `scripts/summarize_live_replay_600519_p1.py`
7. `scripts/update_live_replay_doc_600519_p1.py`

---

## 2. 为什么这样改

已经完成的正式 backtest 说明，profitability inactive 与 guarded mean_reversion 虽然能增加 Layer B 中游候选，但并没有改变最终收益和真实成交，反而抬高了运行成本。

后续 focused replay 与 watchlist suppression drilldown 进一步确认：

1. 新增候选大多死在 watchlist，而不是 buy orders
2. 压制主因来自 investor cohort，而不是 analyst cohort
3. `600519` 是典型的边缘阈值样本，不是结构性强负样本

因此，本次提交的目标不是继续放大 Layer B，而是只释放少量边缘样本，同时继续拦住已经被 investor 群体一致性看空的强负样本。

---

## 3. 当前证据链

### 3.1 执行层验证

1. `pytest tests/execution/test_phase4_execution.py -q` 当前为 `32 passed`
2. 已验证 investor 缩放会轻微抬升 analyst 相对影响力
3. 已验证 `score_final` 落在 `0.20 .. 0.25` 的边缘样本可以进入 watchlist

### 3.2 离线业务回归

1. 8 个结构性强负样本在当前默认参数下仍保持 `avoid` / 不穿透
2. `600519` 的两个边缘样本按预期分化：`20260224` 通过，`20260226` 仍不过线

### 3.3 Live targeted replay

2026-03-16 已完成最小 live targeted replay：

1. `20260224 / 600519`：`score_final = 0.2158`，已经跨过 `0.20` watchlist 门槛
2. `20260226 / 600519`：`score_final = 0.1962`，仍保持边缘不过线

对应产物：

1. `data/reports/live_replay_600519_20260224_p1.json`
2. `data/reports/live_replay_600519_20260226_p1.json`
3. `data/reports/live_replay_600519_p1_summary.md`

这说明当前 P1 已经拿到最小 live 业务补证：

1. 可以真实放出 `20260224 / 600519`
2. 没有把 `20260226 / 600519` 推进到更激进的通过区间

---

## 4. 当前结论

基于现有证据，P1 已经不再只是“离线 clean candidate”，而是具备以下状态：

1. 代码已落地
2. 执行层测试通过
3. 离线业务回归通过
4. 最小 live targeted replay 已完成，且结果符合保守预期

因此，当前最合理的工程定位是：

1. P1 可以进入评审，作为当前最有根据的候选默认参数
2. 它仍然不是“完整窗口、未来窗口都已验证”的最终发布结论
3. 后续残余风险主要来自样本覆盖范围，而不是当前最小补证链本身

---

## 5. 残余风险

仍需显式记录三类残余风险：

1. live replay 只覆盖 `600519` 两个目标日期，不代表更长窗口分布
2. watchlist 阈值迁移到 `0.20` 后，未来可能放出新的边缘样本，需要继续观察 funnel diagnostics
3. 外部数据链路仍可能出现偶发不稳定，例如本次 `20260224` replay 中出现过一次 AKShare 新闻抓取 TLS 警告，但未阻断主流程

---

## 6. 建议评审口径

建议 PR 或提交说明按下面口径表达：

1. 这不是继续扩大 Layer B 的改动，而是对 Layer C + watchlist 的最小保守校准
2. 目标是释放已被证明属于边缘阈值样本的 `600519`，而不是放松结构性强负样本拦截
3. 当前最小 live replay 已验证：`20260224` 真实过线，`20260226` 仍保持边缘不过线
4. 因此，本次变更可以进入评审，但仍应把“更长窗口验证待补”作为残余风险写明
