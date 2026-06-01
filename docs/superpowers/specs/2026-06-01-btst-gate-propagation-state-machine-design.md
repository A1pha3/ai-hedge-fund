# BTST Gate Propagation And Execution State Machine Design

## Goal

让 BTST 主文档与执行清单在市场门控降级为 gate_locked_confirmation_only 时，不再继续使用正式执行语义；同时把这一降级结果写入结构化产物，供后续机器校验和盘后回填复用。

## Non-Goals

- 不改 selected、watch、opportunity 的选股生成逻辑。
- 不改 router、selection_snapshot 或上游目标评估数据结构。
- 不在本轮引入新的 Alpha 因子、动态成本模型或组合预算模型。
- 不把 stale early-runner 的惩罚逻辑扩展成新的上游筛选规则；本轮只保证它不能在文档层被错误升级。

## Problem Summary

当前 [scripts/generate_btst_doc_bundle.py](scripts/generate_btst_doc_bundle.py) 已经通过盘前控制塔输出 effective_trade_bias。当市场处于 halt、crisis、risk_off 或 buy_orders_cleared 条件时，控制塔会把原始 trade_allowed 降级为 gate_locked_confirmation_only。

但正文和执行清单仍然固定渲染以下章节与措辞：

- BTST-LLM 中的“正式执行层”
- EXEC-CHECKLIST 中的“正式执行顺序”
- 行级文案中的“正式执行”“正式观察”等表述

结果是同一份文档上方已经明确写出“只允许确认”，下方却仍像一份可以直接下单的正式执行单，造成语义冲突。当前 quality summary 也只记录 control_tower.reason_codes，无法直接校验这种冲突。

## Current Control Path

1. [src/paper_trading/btst_decision_enrichment.py](src/paper_trading/btst_decision_enrichment.py) 为行级对象生成 evidence_grade、data_quality、trade_bias、risk_posture、must_confirm、invalidate_if 和 action_matrix。
2. [scripts/generate_btst_doc_bundle.py](scripts/generate_btst_doc_bundle.py) 中的 _build_premarket_control_tower 基于 decision_card.trade_bias 和 selection_snapshot 的市场门控生成 effective_trade_bias。
3. 同一脚本继续渲染 BTST-LLM 与 EXEC-CHECKLIST，但章节标题和大部分执行措辞没有再读取最终门控语义，而是继续按正式执行模板输出。
4. quality summary 只校验章节是否存在，不校验章节语义是否与 control_tower 冲突。
5. review ledger 记录了 trade_bias、risk_posture、must_confirm 等字段，但没有最终 execution_state、formal_buy_allowed 或 report_mode。

## Approaches Considered

### Approach 1: Markdown-Only Wording Fix

只在 [scripts/generate_btst_doc_bundle.py](scripts/generate_btst_doc_bundle.py) 内按 effective_trade_bias 改章节标题和部分文案。

优点：改动最小，交付最快。

缺点：

- 结构化产物仍不知道最终执行状态。
- 机器校验只能扫描 Markdown 文本，容易脆弱。
- review ledger 仍不能区分“研究层 trade_bias”和“最终执行层状态”。

### Approach 2: Single Source Of Truth For Final Execution Semantics

在现有行级 enrichment 之上增加一个“最终执行语义层”，由控制塔状态和行级 trade_bias 共同决定：

- report_mode
- execution_state
- formal_buy_allowed
- state_reason_codes
- section_labels

所有 BTST-LLM、EXEC-CHECKLIST、quality summary、review ledger 和 contract 检查都从这一层读取。

优点：

- 门控语义实现硬传导。
- 结构化真源和 Markdown 同步。
- 不改上游选股逻辑，改动面仍然集中。

缺点：

- 需要补测试与 QA contract，而不是单纯改文案。

### Approach 3: Push Final Execution State Upstream

把最终状态继续写回 router 或 selection_snapshot，让更多脚本复用。

优点：跨脚本复用性更好。

缺点：

- 会扩大本轮改动面。
- 需要重新评估更多依赖脚本的兼容性。
- 超出本轮“报告质量消歧”的最小目标。

## Recommended Design

采用 Approach 2。

核心原则：

1. 选股真假不在本轮重判，只重判“这些名字在今天的报告里能否被描述成正式可执行”。
2. 盘前控制塔是最终门控输入，所有可执行章节必须服从它。
3. Markdown 章节名、行级状态、quality summary 和 review ledger 必须共享同一份最终语义，而不是各写各的。

## Final Execution Semantics Model

新增一个最终执行语义 contract，最少包含以下字段：

- report_mode：formal_execution 或 confirmation_review_only
- execution_state：blocked、watching、confirmable、orderable
- max_allowed_state_today：blocked、watching、confirmable、orderable
- formal_buy_allowed：true 或 false
- allowed_sections：formal_queue、review_queue、watch_queue、blocked_only 的子集
- state_reason_codes：继承并扩展 control_tower.reason_codes
- section_labels：当前 report_mode 下的章节标题映射

另外在控制塔与质量摘要层补充：

- veto_owner：market_gate、model_evidence、manual_review 三选一

### Report Mode Rules

- 当 control_tower.effective_trade_bias 为 gate_locked_confirmation_only 时，report_mode 必须为 confirmation_review_only。
- 当 control_tower.effective_trade_bias 为 trade_allowed 且无更高层门控阻断时，report_mode 为 formal_execution。
- 当 control_tower.effective_trade_bias 为 skip、no_trade 或 manual_review_required 时，report_mode 也不得落回 formal_execution。

### Row State Rules

formal_selected 行在不同 report_mode 下的当前状态规则：

- formal_execution 模式：
  - trade_allowed -> orderable
  - confirmation_only -> confirmable
  - skip -> blocked
- confirmation_review_only 模式：
  - trade_allowed -> confirmable
  - confirmation_only -> confirmable
  - watch_only -> watching
  - skip -> blocked

补充硬规则：

- 当 control_tower.effective_trade_bias 为 gate_locked_confirmation_only 时，当日 current state 上限固定为 confirmable。
- 当 control_tower.effective_trade_bias 为 gate_locked_confirmation_only 时，max_allowed_state_today 也必须固定为 confirmable。
- orderable 在本轮只保留为通用状态机定义里的后续状态，用于解释完整生命周期，不代表当日已有任何名字被重新放行。
- 本轮不引入新的盘中 release gate、人工 override 或二次放行器；若未来要允许 confirmable -> orderable，必须通过单独 contract 明确“谁在什么条件下有权放行”。

watch、only early-runner、second-entry 等非 formal_selected 行在本轮保持非正式执行语义：

- watch_only -> watching
- stale 或 insufficient -> blocked 或 reference-only wording

### Allowed Sections Rules

- formal_execution 模式下，formal_selected 默认允许进入 formal_queue；watch 行进入 watch_queue。
- confirmation_review_only 模式下，formal_selected 只能进入 review_queue，不得进入 formal_queue。
- stale_fallback early-runner、insufficient 或 skip 行只能进入 blocked_only 或 watch_queue，不能被渲染到 formal_queue。
- 渲染层必须优先读取 allowed_sections，而不是再通过章节名和 trade_bias 反推归属。

### Section Label Rules

在 confirmation_review_only 模式下：

- BTST-LLM 的“正式执行层”改为“确认复核队列”
- EXEC-CHECKLIST 的“正式执行顺序”改为“确认复核顺序”
- 相关行级文案不得再使用“正式执行”“正式买入”“正式观察顺序先下单”之类语义

在 formal_execution 模式下继续沿用现有正式执行命名。

## Renderer Changes

### [src/paper_trading/btst_decision_enrichment.py](src/paper_trading/btst_decision_enrichment.py)

扩展该模块，新增围绕最终执行语义的纯函数，负责：

1. 从 control_tower 解析 report_mode。
2. 根据 report_mode 与行级 trade_bias 派生 execution_state。
3. 生成 formal_buy_allowed。
4. 生成 allowed_sections。
5. 合成 state_reason_codes。
6. 提供 review ledger 可直接消费的结构。

保留现有 enrich_btst_row、build_decision_card、build_review_ledger_rows 的职责边界，不让报告脚本自己埋新的交易逻辑分支。

### [scripts/generate_btst_doc_bundle.py](scripts/generate_btst_doc_bundle.py)

修改点：

1. 在控制塔生成后，计算 report_mode 与章节标签。
2. BTST-LLM 和 EXEC-CHECKLIST 的所有可执行章节统一使用章节标签映射，而不是硬编码“正式执行层”“正式执行顺序”。
3. 增加显式 execution state machine 章节，固定展示 blocked -> watching -> confirmable -> orderable -> filled/aborted 的定义。
4. 在 confirmation_review_only 模式下，行级当前状态只能出现 blocked、watching、confirmable，不允许出现 orderable 作为当日当前状态。
5. EXEC-CHECKLIST 中逐票状态展示至少要区分 current_state 与 max_allowed_state_today，避免把“理论生命周期终点”误读成“今天已经允许下单”。
6. 原 action matrix 保留，但在 confirmation_review_only 模式下只能表达“复核后才可能进入下一状态”，不能表达已经可直接买入。
7. 渲染正式队列、复核队列、观察队列时必须先看 allowed_sections，杜绝“状态正确但章节归属错误”。

## Quality Summary Contract

扩展 [scripts/generate_btst_doc_bundle.py](scripts/generate_btst_doc_bundle.py) 输出的 quality summary，新增：

- report_mode
- execution_contract
- semantic_conflicts
- veto_owner
- source_of_truth_snapshot

其中 semantic_conflicts 至少检查：

1. control_tower 是 gate_locked_confirmation_only，但文档仍出现“正式执行层”或“正式执行顺序”。
2. confirmation_review_only 模式下仍出现正式买入语义。
3. stale_fallback early-runner 被写成可升级的当日优先复审。
4. 章节标题与 control_tower.report_mode 不一致。

另外增加一组 forbidden semantics 词表，按 report_mode 做扫描：

- confirmation_review_only 模式下至少拦截：正式买入、正式下单、正式执行、主执行顺序、直接执行。
- formal_execution 模式下不做这组词的否定校验，但仍保留 stale_fallback 与章节冲突检查。

source_of_truth_snapshot 至少包含：

- control_tower.effective_trade_bias
- report_mode
- veto_owner
- section_labels
- formal rows 的 ticker、execution_state、max_allowed_state_today、allowed_sections 摘要
- forbidden semantics 命中摘要

如果出现冲突，quality summary 必须机器可读，而不是只靠人工从 Markdown 中发现。

## Review Ledger Changes

扩展 [src/paper_trading/btst_decision_enrichment.py](src/paper_trading/btst_decision_enrichment.py) 中 build_review_ledger_rows 的输出字段，至少新增：

- report_mode
- execution_state
- max_allowed_state_today
- formal_buy_allowed
- allowed_sections
- state_reason_codes

这些字段要与文档当前态一致，后续盘后回填时才能判断：

- 这是本该直接执行的名字，还是只允许确认复核的名字
- 触发但未成交是否属于流程内状态
- 取消是否符合当日门控 contract

## Veto Owner Rules

- 当最终降级来自 market gate、regime gate 或 buy_orders_cleared 时，veto_owner 为 market_gate。
- 当最终降级来自模型证据不足、样本不足或赔率/质量问题时，veto_owner 为 model_evidence。
- 当 selection_snapshot 缺失或需要人工兜底判断时，veto_owner 为 manual_review。

这个字段先服务于结构化真源与后续 CIO 决策条，不要求本轮就渲染成复杂 prose。

## Testing Strategy

测试只扩展到当前最小行为面：

1. 在 [tests/test_generate_btst_doc_bundle_script.py](tests/test_generate_btst_doc_bundle_script.py) 先补失败测试，复现 gate_locked_confirmation_only 仍输出“正式执行层”“正式执行顺序”的当前问题。
2. 再补失败测试，要求 quality summary 和 review ledger 带出新的结构化字段。
3. 实现最小代码让上述测试转绿。
4. 保留一个对照测试，确保 gate 允许时仍使用正式执行语义，不把所有场景都降级成 confirmation_review_only。
5. 增加一个真实冲突回归夹具，数据结构以当前 20260529 gate-locked 案例为原型，锁住“控制塔已降级但正文仍像正式执行单”的问题。

真实冲突回归夹具的要求：

- 来源于真实案例的字段组合，而不是完全凭空虚构。
- 测试夹具仍以仓库内合成 JSON 写入 tmp_path 方式组织，避免对 outputs 目录产生硬依赖。
- 既验证标题，也验证 forbidden semantics、allowed_sections 和 ledger 状态字段。

## Acceptance Criteria

本轮完成后，应同时满足：

1. 当 effective_trade_bias 为 gate_locked_confirmation_only 时，BTST-LLM 不再出现“正式执行层”。
2. 当 effective_trade_bias 为 gate_locked_confirmation_only 时，EXEC-CHECKLIST 不再出现“正式执行顺序”。
3. confirmation_review_only 模式下，文档当前状态不出现 orderable。
4. confirmation_review_only 模式下，current_state 与 max_allowed_state_today 都不能超过 confirmable。
5. quality summary 能直接报告 report_mode、semantic_conflicts 与 forbidden semantics 命中情况。
6. review ledger 每行都能区分 execution_state、max_allowed_state_today 与 formal_buy_allowed。
7. gate 允许的正常交易日仍保持现有正式执行语义。
8. 每只 formal row 的 allowed_sections 与实际被渲染的章节一致。
9. quality summary 带出 veto_owner 和 source_of_truth_snapshot，可供后续控制塔或首页摘要直接消费。

## Risks And Mitigations

### Risk 1: 只改标题，不改行级语义

Mitigation：测试同时检查章节标题和结构化字段，避免做成纯文案补丁。

### Risk 2: 把所有场景都错误降级

Mitigation：增加 gate allowed 对照测试，确认 formal_execution 模式仍存在。

### Risk 3: review ledger 与文档状态脱节

Mitigation：ledger 字段直接从同一套最终执行语义 helper 生成，不重复手写。

## Open Question Resolved

本轮按“文档 + 结构化真源”执行，不把统一状态继续上推到 router 或 selection_snapshot。