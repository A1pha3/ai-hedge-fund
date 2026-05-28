# BTST rollout artifact 接入报告层设计（2026-05-28）

## 背景

当前仓库已经补齐了两块基础能力：

1. `scripts/analyze_btst_shadow_profile_replay.py` 支持从 `btst_weekly_validation_*.json` 直接解析 replay source。
2. `scripts/analyze_btst_layer_c_rollout_validation.py` 能把 payoff 提升和 replay 的 formal buy 收缩合成一张 governed rollout artifact。

现在缺的不是“有没有结论”，而是“这个结论怎么稳定进 BTST 报告层”。  
如果不接到报告层，`generate_btst_doc_bundle.py`、`btst_next_day_trade_brief`、`btst_premarket_execution_card` 还是只能靠人工口述补充 rollout 状态。

> 当前假设：用户暂时不在线，本轮默认把新 artifact 接到 **BTST 报告生成层**，不直接改变选股 / 执行门控逻辑。

## 目标

1. 让 BTST brief、premarket execution card、doc bundle 都能稳定看到 `layer_c` rollout 结论。
2. 接入方式保持 **只读**；本轮不让 rollout artifact 直接反写 admission / execution。
3. 缺少 artifact 时，报告仍然能正常生成，只是显式标成 unavailable。

## 非目标

1. 本轮不把 `governed_shadow_ready` 直接升级成默认 live profile。
2. 本轮不把 `layer_c` rollout artifact 作为硬门控输入接进 `src/targets/` 或 `src/execution/`。
3. 本轮不顺手解决 `short_trade_boundary`、runner recall、boundary contract 的其他推进线。

## 备选方案

### 方案 A：接到 `src/paper_trading/btst_reporting.py`，再由 bundle 复用（推荐）

做法：

- 在 reporting 层增加一个 `rollout_validation` 解析/归一化 helper；
- `analyze_btst_next_day_trade_brief()` 与 `analyze_btst_premarket_execution_card()` 统一带出 `rollout_validation` 字段；
- `generate_btst_doc_bundle.py` 不自己做路径解析，直接消费 brief / card 中已经归一化好的字段。

优点：

- 路径解析只写一处；
- brief、card、bundle 三条文档链共享同一 payload；
- 本轮保持只读，不会误把 artifact 变成实时门控。

缺点：

- 需要同时改 `src/paper_trading` 和 `scripts/generate_btst_doc_bundle.py`。

### 方案 B：只接到 `generate_btst_doc_bundle.py`

做法：

- bundle 脚本自己去找 `btst_layer_c_rollout_validation_*.json`；
- 只在 LLM doc / checklist / early-warning 里展示 rollout 状态；
- brief / premarket card 继续保持现状。

优点：

- 改动面最小；
- 直接解决技能主输出。

缺点：

- brief / premarket card 继续缺 rollout 结论；
- bundle 会复制一套 artifact 解析逻辑，和 reporting 层脱节；
- 后续别的 BTST 报告想复用时，还得再做一次。

### 方案 C：直接接进选股 / 执行门控

做法：

- 把 `governed_shadow_ready` 之类的状态做成 profile / gate 输入；
- 让报告层只显示实际生效的门控状态。

优点：

- 最接近最终自动化。

缺点：

- 风险最高；
- 会把“结论展示”问题升级成“策略行为改变”问题；
- 当前证据还没到默认升级阶段，不适合现在做。

## 结论

采用 **方案 A**。

原因很简单：本轮的核心需求是 **让报告层稳定复用 rollout artifact**，不是改变交易行为。  
把解析逻辑收进 `src/paper_trading/btst_reporting.py`，既能覆盖 brief / card，也能让 doc bundle 走现成 payload，边界最稳。

## 设计

### 1. 新增 rollout artifact 解析 helper

位置：优先放在 `src/paper_trading/btst_reporting_utils.py`，因为这里已经承载了 BTST reporting 的公共 I/O、日期和路径 helper。

新增能力：

1. 解析显式 artifact 路径；
2. 在未显式传参时，从 `data/reports/btst_layer_c_rollout_validation_*.json` 里挑最新可用文件；
3. 归一化输出：
   - `status`
   - `primary_lane`
   - `summary`
   - `selected_hit_rate_15pct`
   - `shadow_hit_rate_15pct`
   - `selected_count_delta`
   - `execution_eligible_delta`
   - `buy_order_delta`
   - `source_json_path`
   - `source_markdown_path`

缺失或解析失败时返回：

```json
{
  "status": "unavailable",
  "summary": "rollout artifact missing",
  "source_json_path": null,
  "source_markdown_path": null
}
```

### 2. 把 rollout_validation 接进 brief / premarket payload

入口：

- `analyze_btst_next_day_trade_brief()`
- `analyze_btst_premarket_execution_card()`

两者都新增顶层字段：

```json
"rollout_validation": { ...normalized payload... }
```

要求：

1. 这是只读展示字段；
2. 不参与 primary / watch / opportunity 的分层判断；
3. brief 和 premarket card 使用同一归一化结构，避免 bundle 再做字段翻译。

### 3. 在 Markdown 里增加一个稳定但克制的 rollout section

位置建议：

- brief：放在总览 / source paths 附近，标题可用 `## Governed Rollout 观察`
- premarket card：放在 guardrails / execution posture 附近，标题可用 `## Governed Rollout Guardrail`

展示内容只保留三类：

1. 当前状态：`governed_shadow_ready / hold_for_more_validation / unavailable`
2. 一句摘要：直接复用 artifact 的 `summary`
3. 三个关键数字：
   - `selected_hit_rate_15pct -> shadow_hit_rate_15pct`
   - `execution_eligible_delta`
   - `buy_order_delta`

这部分不展开长解释，不把周级验证全文塞进日报。

### 4. doc bundle 不再自己找 artifact，只消费 followup payload

`generate_btst_doc_bundle.py` 继续保持“装配器”角色。

推荐做法：

1. 从 brief JSON 里读取 `rollout_validation`；
2. 在以下文档追加短 section：
   - `BTST-LLM-*.md`
   - `BTST-*-EXEC-CHECKLIST.md`
   - `BTST-*-EARLY-WARNING.md`
3. 文案统一引用：
   - 状态
   - 摘要
   - source path

这样 bundle 不需要知道 artifact 的发现逻辑，只关心“brief 已经给了什么”。

### 5. followup manifest 记录引用路径

`register_btst_followup_artifacts()` 里，`session_summary["btst_followup"]` 可以补两项：

- `rollout_validation_json`
- `rollout_validation_markdown`

这不是为了让 bundle 重新解析，而是为了让 report dir 的 followup manifest 把引用链记完整，后面排查产物来源更容易。

## 数据流

1. 外部先生成 `btst_layer_c_rollout_validation_*.json/.md`
2. brief / premarket builder 解析并归一化该 artifact
3. brief / card JSON 持久化 `rollout_validation`
4. followup manifest 记录 source path
5. doc bundle 直接消费 brief 里的 `rollout_validation`，把状态写进最终文档

## 错误处理

1. artifact 缺失：报告照常生成，但 `status=unavailable`
2. artifact 格式不完整：归一化时降级为 `status=unavailable`，并保留 `summary=invalid rollout artifact`
3. Markdown 渲染阶段不依赖深层字段，避免某个 delta 缺失导致整份文档失败

## 测试

### 新增或修改

1. `tests/test_generate_btst_next_day_trade_brief_script.py`
   - 有 artifact 时，brief JSON / Markdown 带出 rollout section
   - 没 artifact 时，brief 仍生成且状态为 unavailable

2. `tests/test_generate_btst_premarket_execution_card_script.py`
   - execution card 展示 rollout guardrail
   - 缺失 artifact 时不崩

3. `tests/test_generate_btst_doc_bundle_script.py`
   - bundle 文档显示 rollout 状态、摘要和 source path
   - bundle 不自己解析 artifact，只消费 brief payload

4. `tests/test_btst_report_utils.py` 或新 helper test
   - 覆盖 artifact 解析、最新文件选择、unavailable fallback

## 成功标准

1. 生成 brief / premarket / bundle 时，都能看到同一份 rollout 结论；
2. 文档里不再需要人工补“当前 governed rollout 是什么状态”；
3. rollout artifact 缺失时，不会把整条 BTST 文档链打断；
4. 本轮不改变任何选股 / 执行决策，只改变报告可见性。

## 当前停点

由于用户暂时不在线，本 spec 先按“接入 BTST 报告生成层”这个默认方向落稿。  
下一步应在用户确认后，再进入 implementation plan。
