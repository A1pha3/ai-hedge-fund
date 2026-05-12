# BTST Skill Optimized-Profile Auto-Selection Design

## Problem

`ai-hedge-fund-btst` 当前虽然能稳定生成 BTST 全套文档，但它调用多智能体链路时仍默认落在：

- `selection_target = short_trade_only`
- `short_trade_target_profile_name = default`
- `short_trade_target_profile_overrides = {}`

这意味着它能吃到已经进入 live runtime 的代码级修正，但**不会自动吃到最近每日回测/调参与 rollout 验证后产出的最新优化配置**。用户的真实需求不是“把 default 配置文档化”，而是“每天自动用最新已认可优化配置跑一遍，并在次日用文档去人工验证策略表现”。

## Goal

让 `ai-hedge-fund-btst` 在生成多智能体 BTST 文档前，**默认自动选择最新可用优化配置**，并把本次实际采用的 profile / overrides / 来源依据写入运行产物和最终文档。

## Non-Goals

- 不改规则版 `btst_full_report.py` 的选股逻辑
- 不自动重写 optimize/backtest/walk-forward 流程本身
- 不让 skill 每天双跑 `default` 与 `optimized`
- 不在这次设计里处理“如何产生优化配置”本身，只处理“如何消费已产生的最新优化配置”

## Current State

### Skill layer

`ai-hedge-fund-btst` 的当前说明把多智能体流程固定为：

```bash
.venv/bin/python scripts/run_paper_trading.py \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  --selection-target short_trade_only \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir ...
```

skill 规则没有为 `--short-trade-target-profile` 或 `--short-trade-target-overrides` 预留“自动解析最新优化配置”的步骤。

### Runtime layer

`scripts/run_paper_trading.py` 已支持：

- `--short-trade-target-profile`
- `--short-trade-target-overrides`

因此“自动跟随最新优化配置”的阻塞点不在 runtime 能力不足，而在**缺少一个稳定的优化配置解析入口**，以及 skill 没有在运行前消费它。

### Artifact layer

现有最终文档和 `session_summary.json` 已记录：

- `short_trade_target_profile_name`
- `short_trade_target_profile_overrides`

但 skill 不会主动判断“这次是不是仍然跑了 default”，也不会把“为什么用了这套 profile”明确写进最终 5 份文档。

## Proposed Design

### 1. Introduce a single optimization-resolution authority

新增一个**单一权威入口**，由 skill / 文档流程在运行前读取，用来解析“今天应该用哪套最新优化配置”。

推荐形式：

- 一个 repo 内的 JSON artifact，例如：
  - `data/reports/btst_latest_optimized_profile.json`

建议结构：

```json
{
  "profile_name": "momentum_optimized",
  "profile_overrides": {
    "select_threshold": 0.48,
    "near_miss_threshold": 0.34
  },
  "source_type": "optimize_profile",
  "source_path": "data/reports/param_search_momentum_optimized_....json",
  "validated_by": "walk_forward_and_rollout",
  "trade_date": "2026-05-12",
  "status": "ready"
}
```

这份 artifact 的职责只有一个：**告诉消费方“今天应使用的最新优化配置是什么”**。  
skill 不自己扫描 `data/reports` 猜最新文件，避免把实验性产物误当正式优化结果。

### 2. Add a resolver layer before `run_paper_trading.py`

在 skill 调用 `scripts/run_paper_trading.py` 之前，先经过一个解析步骤：

1. 读取权威优化 artifact
2. 校验字段完整性：
   - `profile_name`
   - `status == ready`
   - `source_path` 存在
3. 解析出：
   - `--short-trade-target-profile`
   - `--short-trade-target-overrides`

如果解析成功，则默认把该配置注入多智能体 BTST 运行链。

### 3. Safe fallback behavior

若权威优化 artifact 缺失、损坏、字段不全，或 `status != ready`，则：

1. 回退到 `default`
2. 在运行摘要、`session_summary` 扩展字段、以及最终 5 份文档中明确写明：
   - 本次未使用最新优化配置
   - 回退原因

禁止 silent fallback。用户必须能看出这次到底是不是 optimized run。

### 4. Propagate optimization provenance into artifacts and final docs

除了让 run 真正使用 optimized profile，还要把 provenance 一路透传。

#### Runtime/session summary

建议在 `session_summary.json` 中新增或扩展：

```json
{
  "optimization_profile_resolution": {
    "mode": "optimized" | "default_fallback",
    "profile_name": "momentum_optimized",
    "profile_overrides": {...},
    "source_type": "optimize_profile",
    "source_path": "...",
    "status": "ready",
    "fallback_reason": null
  }
}
```

#### Final BTST documents

至少在以下文档里显式写出：

- `BTST-LLM-YYYYMMDD.md`
- `BTST-YYYYMMDD-EXEC-CHECKLIST.md`
- `YYYYMMDD-两套交易计划通俗说明.md`

必须可见：

- 本次运行使用的 `profile_name`
- 是否带 overrides
- 来源依据（例如 latest optimized artifact path）
- 若回退到 default，必须写清回退原因

这样用户第二天人工验证时，能把“市场实际结果”准确归因到某一套具体优化配置，而不是模糊地归因给“系统”。

### 5. Keep rule-based document boundaries unchanged

`BTST-YYYYMMDD.md` 仍保持规则版权威，不因为 optimized profile auto-selection 而改成多智能体文档。  
但在解释类文档里可以清楚说明：

- 规则版来自规则引擎
- 多智能体版来自“最新优化配置”或“default fallback”

避免两套权威混淆。

## Alternatives Considered

### A. Scan latest optimize artifacts by timestamp

优点：实现快。  
缺点：风险最高，会把实验性/半成品结果误当正式版本。  
结论：拒绝。

### B. Run both default and optimized every day

优点：信息最全。  
缺点：成本高、速度慢、职责混乱；还会让“人工验证次日效果”前多一层系统内对比。  
结论：拒绝，超出本次范围。

### C. Single authoritative optimized-profile artifact

优点：稳定、可审计、与每日回测迭代节奏一致。  
缺点：需要建立一个清晰的“认领最新优化配置”的写入点。  
结论：采纳。

## Data Flow

```text
latest optimization artifact
  -> BTST skill resolver
    -> run_paper_trading.py (--short-trade-target-profile / overrides)
      -> session_summary.json provenance
        -> btst followup artifacts
          -> 5 final BTST docs
```

## Error Handling

- 缺失权威优化 artifact：回退 default，并显式写明 fallback reason
- artifact 字段不完整：回退 default，并显式写明字段缺失
- `profile_name` 无效：停止或显式回退，不能 silent ignore
- overrides 不是 JSON object：视为解析失败，不能继续假装用了 optimized

## Testing Strategy

### Unit tests

1. resolver 读取 ready artifact 时，正确返回：
   - `profile_name`
   - `profile_overrides`
2. resolver 遇到缺失/损坏 artifact 时，返回 default fallback 与原因
3. 最终文档生成逻辑会把优化配置 provenance 写入指定文档

### Integration tests

1. 模拟 optimized artifact 存在，验证 `session_summary.json` 记录 optimized provenance
2. 模拟 fallback，验证文档和 `session_summary` 都明确写出 fallback reason
3. 验证 skill 不会再无提示地运行 `default`

## Rollout Plan

1. 先引入 optimized-profile resolver 与 provenance 透传
2. 再让 BTST skill 使用该 resolver
3. 最后补文档层文案，使次日人工验证能看到“本次到底用了哪套优化配置”

## Success Criteria

满足以下条件即可认为设计成功：

1. skill 默认不再盲跑 `default`
2. 当存在 ready 的最新优化配置时，`run_paper_trading.py` 实际使用它
3. 当不存在时，系统显式 fallback，而不是静默降级
4. 用户打开最终 BTST 文档时，能明确知道本次运行到底用了哪套 profile / overrides / 来源依据
