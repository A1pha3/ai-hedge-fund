## Task: Refresh Dual-Target Implementation Plan Document

你要修改的目标文档是：

- docs/zh-cn/product/arch/dual_target_system/dual_target_implementation_plan.md

你的任务不是继续做架构抽象，而是把这份文档修正为一份可以反映当前真实代码状态的“实施计划 + 落地状态对照”文档。

## Objective

把目标文档从“施工前计划”改写成“状态化实施记录”版本，并且只聚焦以下三类问题：

1. 修正错误链接
2. 修正过期结论和错误时态
3. 重写测试矩阵，并单独补充 Explainability 与 profile 抽象缺口审查

## Verified Facts

在开始修改前，必须以当前代码现状为准，并保留以下已验证事实：

1. Phase 1-6 主链路已经基本落地，不应再把整篇文档写成“尚待开工”的未来计划
2. `src/targets/models.py`、`src/targets/router.py`、`src/targets/research_target.py`、`src/targets/short_trade_target.py`、`src/targets/explainability.py` 已存在
3. `src/targets/profiles.py` 当前不存在，这是结构整理缺口，不等于 short trade 规则未实现
4. `ExecutionPlan` 已包含 `selection_targets`、`target_mode`、`dual_target_summary`，且有默认值兼容旧 payload
5. `src/paper_trading/runtime.py` 已把 `dual_target_summary` 聚合进 `session_summary.json`
6. Replay Artifacts 后端与前端已经消费 dual-target 结构，不能再写成“尚未开始接工作台”
7. Explainability 更准确的状态是“数据契约与输出已就绪，但工作台明细消费未完全产品化”

## Required Changes

你必须完成以下修改：

1. 在文档头部新增状态说明
2. 把文档定位从“施工图版本”升级为“施工顺序 + 当前落地状态对照”
3. 修复第 6 节中 `arch_optimize_implementation.md` 的错误相对路径
4. 将 Phase 1-6 全部改写为带状态标记的章节，至少包含：
	- 状态
	- 原目标
	- 当前落地说明
	- 必要时指出未完成部分
5. 重写测试章节，改成“已覆盖 / 待补强”格式
6. 重写“第一阶段开工建议”和“当前建议结论”，避免继续暗示系统尚未开工
7. 新增单独一节，专门审查：
	- Explainability 当前状态
	- profile 抽象当前状态
	- 后续优先级

## Required File References To Reflect In Document

文档中应准确体现这些代码落点：

1. `src/execution/models.py`
2. `src/targets/router.py`
3. `src/paper_trading/runtime.py`
4. `src/research/artifacts.py`
5. `src/research/review_renderer.py`
6. `app/backend/services/replay_artifact_service.py`
7. `app/frontend/src/components/settings/replay-artifacts.tsx`

## Required Tests To Mention As Already Covered

文档测试矩阵中，至少要明确这些测试已经存在：

1. `tests/targets/test_target_models.py`
2. `tests/research/test_selection_artifact_writer.py`
3. `tests/research/test_selection_review_renderer.py`
4. `tests/backtesting/test_paper_trading_runtime.py`
5. `tests/backend/test_replay_artifact_service.py`
6. `tests/backend/test_replay_artifact_routes.py`
7. `app/frontend/src/components/replay-artifacts/replay-artifacts-inspector.test.tsx`
8. `app/frontend/src/components/settings/replay-artifacts.test.tsx`

## Constraints

严格遵守以下约束：

1. 不要把已完成的主链路重新描述成未来工作
2. 不要声称 `src/targets/profiles.py` 已实现
3. 不要声称 Explainability 已经形成完整工作台能力
4. 不要扩写成新的架构设计文档；只修正文档状态、结论和测试矩阵
5. 不要改动与本任务无关的代码文件
6. 保持中文技术文档风格，避免口语化

## Output Contract

执行完成后，你的输出必须包含：

1. 改动了哪些章节
2. 修正了哪些错误结论
3. 哪些内容被重新标记为“后续优化”
4. 是否发现新的阻塞项

## Acceptance Criteria

只有同时满足以下条件，任务才算完成：

1. 目标文档不再把双目标系统整体描述为待开工
2. 错误链接已修正
3. Phase 1-6 已按当前真实状态更新
4. 测试章节已从“必须增加”改成“已覆盖 / 待补强”
5. Explainability 与 profile 抽象缺口已被单独落为审查结论
6. 文档整体仍然可读，没有明显重复和时态冲突

## Suggested Execution Order

按这个顺序执行：

1. 先修正错误链接和文档定位
2. 再更新 Phase 1-6 的状态与结论
3. 再重写测试矩阵
4. 最后补 Explainability / profile 抽象的第二轮审查
