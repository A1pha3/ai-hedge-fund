# AutoDev 项目契约

本文件定义 AutoDev 在本项目中的目标函数、授权边界和 owner-blocker 处理方式。它不是路线图，也不记录历史 backlog；AutoDev 每轮选题前应优先读取本文件，再结合 `feature-proposals.md`、测试和当前代码状态做决策。

## 北极星

本项目最高目标是：让用户用尽可能少的入口，稳定找到未来 T+5 或 T+10 天更值得买入的 A 股标的。

当前 BUY 主决策 horizon 是 T+5 或 T+10。T+30 只作为长期衰退、持有风险和 invalidation 信号，不作为默认 BUY 主决策依据。

注: crisis/risk_off regime 下 T+5 被 BUY gate 排除 (NS-23, autodev c245)。
    仅 T+10 可放行 — 全期 per-bucket T+5 winrate 不能盲目外推到 regime-specific
    (用户 2026-06-29 直接复现证据: crisis 实际 T+5 winrate=43.59% < 50%)。

## Fitness 优先级

AutoDev 评估候选工作时，优先级按下面顺序收敛：

1. 提升 T+5 / T+10 realized P&L。
2. 提升 T+5 / T+10 winrate，并优先要求 winrate > 50%。
3. 提升 T+5 / T+10 median return，并优先要求 median return > 0。
4. 减少低质量候选，保留更少、更高确信、更可解释的代表票。
5. 提高数据真实性、point-in-time 正确性、可回放性、可观测性和前门信任校准。

当多个候选都能提升工程质量时，优先选择能直接改善默认前门 `--top-picks`、BUY/HOLD/AVOID 决策、候选池质量、回测真实性或真实表现观测闭环的工作。

## AutoDev 可自主推进

以下工作属于工程拥有范围。只要可以本地验证、可回滚，且不需要外部权限，AutoDev 应自主推进到实现、验证和本地提交：

- 数据正确性修复：PIT、复权、mock 清理、缺失值、NaN/Inf、schema 契约、样本成熟度、报告损坏容错。
- 决策链可靠性：原子写、读端容错、降级可观测性、默认前门崩溃修复、报告信任披露。
- evaluator 建设：T+5/T+10 P&L、winrate、median return、rank monotonicity、factor attribution、model version comparison。
- 实验基础设施：A/B harness、shadow mode、feature flag、离线回测、诊断报告、可重复脚本。
- 用户可见诚实化：证据不足、估计值、降级状态、过期数据、研究用途边界的清晰披露。

如果一项工作不改变生产默认行为，但能让 owner 更快做出正确产品决策，AutoDev 不应因为“最终需要 owner 决策”而停止；应先把 evaluator、实验或决策包做到可审查状态。

## 需要 owner 最终决策

以下事项不由 AutoDev 单独切默认或发布：

- 因子权重、打分模型语义、投资偏好冲突和风险收益取舍。
- 默认前门行为切换，例如改变 BUY gate、默认排序语义、默认候选池大小或默认交易建议。
- push、release、deploy、真实交易、通知外部用户、访问生产凭证或生产数据。
- 认证策略、安全策略、公开 API 合约或会影响现有用户调用方式的产品取舍。

AutoDev 可以在 feature flag、shadow mode、离线路径或诊断路径中实现候选方案并给出推荐，但切换默认行为前必须等待 owner 明确批准。

## Owner-blocker 协议

遇到 owner 决策点时，AutoDev 不应直接以“需要 owner”为由停止。除非下一步确实需要外部权限、真实交易、凭证、发布或不可获得的数据，否则应先产出决策包。

决策包至少包含：

1. 当前问题与证据。
2. A/B/C/D 候选方案，或说明为什么只有一个合理方案。
3. 离线验证结果；如果验证器缺失，先补 evaluator 或说明最小验证器。
4. 按 T+5/T+10 北极星推荐的默认方案。
5. 风险、回滚方式和需要观察的指标。
6. 一个明确的 owner 问题，避免让 owner 在模糊描述中重新做分析。

只有在决策包已经产出，或下一步必须取得外部权限时，“awaiting owner”才是合法停止理由。

## 停止规则

AutoDev 可以在以下情况下停止：

- 当前预算耗尽。
- 已无正向 expected readiness delta 的候选。
- 继续推进需要 owner 批准、外部权限、生产凭证、真实交易、push/release/deploy。
- 关键 evaluator 缺失且无法在本地构造最小验证器。

AutoDev 不应因为 backlog 看起来空、剩余工作偏产品语义、或存在 owner 最终批准环节而提前停止。它应优先寻找 evaluator、shadow implementation、risk-retirement slice 或决策包。

## 输出要求

每轮 AutoDev 输出都应说明：

- 本轮如何服务 T+5/T+10 北极星。
- 为什么所选工作优于其它候选。
- 哪些证据改变了后续选择。
- 若停止，停止原因属于哪条停止规则。
