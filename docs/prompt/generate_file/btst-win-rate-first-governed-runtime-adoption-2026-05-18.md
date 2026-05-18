# btst-win-rate-first-governed-runtime-adoption-2026-05-18

## 原理
- 这次改动把 win-rate-first 的治理从“离线说明”推进到“运行时 provenance”层：默认 BTST 多智能体路径在遇到可用且已就绪的优化 manifest 时，可以自动套用受治理的 P5 precision gate。
- 这里的目标不是把更多名字硬塞进正式通道，而是把正式 short_trade_only 入口收紧到更严格的形式化选股 lane，让主交易候选更偏向已满足 precision 约束的执行面。
- 但这种收紧只代表运行路径更严格，不等于样本外胜率已经被证明抬升。

## 本次验证结论
- 本工作区的单日 replay 只验证了 provenance / runtime 行为：最终运行记录里能看到 governed precision 的开关与原因字段，但没有证明 manifest-backed uplift。
- 原因是这次 replay 的 approved manifest 路径缺失，运行落到了 `mode=default_fallback`，`fallback_reason=optimized_profile_manifest_missing`，因此 governed precision 的自动启用也显示为关闭，原因是 `manifest_not_optimized`。
- 所以这次证据只能支持“运行时合同和 provenance 链路正确”，不能支持“已经通过 manifest 证明了更高胜率或更高赔率”。

## 如何阅读 / 使用
- 看 `session_summary.json` 里的 `optimization_profile_resolution`：只有当它明确指向 ready 的 optimized manifest 时，才能在最终中文文档里把 governed P5 precision gate 说成这次运行实际采用的路径。
- 看下游 artifacts 里的 provenance 字段：若出现 `default_fallback`、`optimized_profile_manifest_missing`、`manifest_not_optimized`，就应把它写成保守结论，而不是写成已验证升级。
- 这份能力的正确使用方式是：把它当成“更严格的正式通道 + 更清晰的 provenance 记录”，先确认运行真的走了受治理路径，再讨论是否有后续回放或样本外提升证据。
