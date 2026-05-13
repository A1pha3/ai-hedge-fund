# BTST Optimized Profile Publisher Design

## Problem

BTST skill 和 `run_paper_trading.py` 已经能消费 `data/reports/btst_latest_optimized_profile.json`，但仓库里还没有稳定的“发布”步骤把最新已认可的优化结果写入这份 canonical manifest。结果是消费链路已经通了，生产链路仍然缺失，skill 最终只能回退到 `default_fallback`。

## Goal

在 BTST 参数优化流程里，自动把**最新已通过 rollout 推荐的优化配置**发布到 `data/reports/btst_latest_optimized_profile.json`，让后续 BTST 文档流程默认拿到最新已认可配置，而不是最新实验结果。

## Non-Goals

- 不让 skill 自己扫描 `data/reports/` 猜最新文件
- 不改 `run_paper_trading.py` 的 manifest 消费协议
- 不把每一次 optimize 结果都强行写成 ready manifest
- 不把未通过 rollout 推荐的实验结果覆盖掉现有 ready manifest

## Chosen approach

### 1. Publish only on explicit promotion

把 `scripts/optimize_profile.py` 作为 canonical manifest 的生产入口，但只在以下条件同时满足时发布：

1. `objective == btst`
2. 运行在 replay 模式（已有 comparison / rollout recommendation）
3. `best_params` 存在
4. `rollout_recommendation == "promote"`

这样发布的是“最新已认可配置”，不是“最新一次搜索结果”。

### 2. Preserve the last ready manifest on hold

如果当前 optimize run 的 `rollout_recommendation != "promote"`，则：

- 不覆盖 `data/reports/btst_latest_optimized_profile.json`
- 继续保留上一次 ready manifest

这是关键安全约束。否则一次失败实验会把现有可用配置清空，skill 会重新掉回 default。

### 3. Add explicit publication metadata

除了写 canonical manifest，还要在 optimize 输出 payload / Markdown 里写出本次发布结果，例如：

```json
{
  "optimized_profile_manifest_publication": {
    "status": "published" | "skipped",
    "reason": "promoted_btst_profile" | "rollout_recommendation_hold" | "...",
    "manifest_path": "data/reports/btst_latest_optimized_profile.json"
  }
}
```

这样研究侧能直接看到“这次是否更新了 skill 默认会消费的配置”。

## Manifest shape

发布出的 canonical manifest 继续沿用当前 resolver 期望的结构：

```json
{
  "profile_name": "momentum_optimized",
  "profile_overrides": {
    "select_threshold": 0.50
  },
  "source_type": "optimize_profile",
  "source_path": "data/reports/param_search_xxx.json",
  "validated_by": "btst_rollout_recommendation",
  "trade_date": "2026-05-12",
  "status": "ready"
}
```

建议新增但不影响 resolver 的附加字段：

- `rollout_recommendation`
- `rollout_recommendation_blockers`
- `comparison_summary`
- `published_at`

resolver 只依赖核心字段；附加字段用于审计。

## Trade date derivation

优先从 replay input 路径推导 trade date：

- `.../selection_artifacts/YYYY-MM-DD/selection_target_replay_input.json`

取最新 trade date 作为 manifest `trade_date`。若无法可靠解析，则写 `null`，不要伪造。

## File boundaries

- `src/paper_trading/optimized_profile_resolution.py`
  - 保持为 manifest **consumer**，不掺入生产逻辑
- `scripts/optimize_profile.py`
  - 继续负责 optimize 主流程
  - 新增 publisher 调用点与 publication metadata
- `scripts/btst_optimized_profile_manifest_helpers.py`
  - 新增小型 helper，封装：
    - 是否允许发布
    - canonical manifest payload 构建
    - trade_date 解析
    - publication status payload

## Error handling

- publisher 不满足 ready 条件时：返回 `skipped` 状态，不抛异常
- canonical manifest 输出目录不存在时：自动创建父目录
- 无法推导 trade date：`trade_date = null`
- JSON 输出路径为空：使用 `save_search_payload()` 产出的实际路径

## Testing strategy

1. helper 单测：
   - promote 时正确写出 ready manifest
   - hold 时跳过发布且不覆盖旧 manifest
   - replay input 路径可正确解析最新 trade date
2. `optimize_profile.py` 集成测试：
   - promote 时写 canonical manifest，并把 publication metadata 写入 output JSON
   - hold 时不写 canonical manifest，并把 skipped reason 写入 output JSON
   - Markdown 报告写出 publication 状态

## Success criteria

满足以下条件即可视为完成：

1. `optimize_profile.py` 在 BTST promote run 后自动更新 `data/reports/btst_latest_optimized_profile.json`
2. hold run 不会覆盖现有 ready manifest
3. optimize 输出明确写出本次是否发布 canonical manifest
4. skill 无需改提示词，就能自动消费最新已认可配置
