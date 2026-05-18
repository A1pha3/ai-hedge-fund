# btst-optimized-profile-manifest-stability-2026-05-18

## 原理
- 这次改动不是新增一个 BTST 打分因子，而是修复 **approved optimized profile 无法稳定进入 runtime** 的根因。
- 之前 `data/reports/btst_latest_optimized_profile.json` 的 `source_path` 指向临时测试目录；一旦那个临时文件不存在，`resolve_btst_optimized_profile_manifest(...)` 就会返回 `default_fallback`，导致 `ai-hedge-fund-btst` 默认流程虽然传了 optimized manifest，实际运行时仍退回 `default`。
- 现在 `publish_btst_optimized_profile_manifest(...)` 会在 manifest 同目录下固化一份 canonical source artifact（`btst_latest_optimized_profile_source.json`），manifest 永远指向这份稳定副本，而不是外部临时输出路径。

## 提升效果
- 提升点在于 **让已经批准的 optimized profile 真正可被 runtime 和 skill 吃到**，避免“看起来有 manifest，实际上落回 default”的假优化状态。
- 对胜率和盈亏比的意义，不是额外宣称一轮新的样本外 uplift，而是恢复先前已经通过 rollout/审批进入 manifest 的优化配置，让 BTST 流程不再因为 provenance 文件失效而白白丢掉已验证的优化结果。
- 对当前仓库提交态，这次修复还顺手回填了 `data/reports/btst_latest_optimized_profile_source.json`，把原先坏掉的临时 `source_path` 修回仓内稳定路径，避免当前 skill 默认 optimized-profile 路径继续 silent fallback。

## 如何验证
- 回归测试新增并覆盖了关键故障模式：
  - `tests/test_optimize_profile_script.py::test_publish_btst_optimized_profile_manifest_persists_canonical_source_for_later_resolution`
    - 先发布 manifest，再删除原始外部 report；
    - 仍要求 `resolve_btst_optimized_profile_manifest(...)` 返回 `mode="optimized"`，证明 runtime 依赖的是 canonical source，而不是易失的外部临时文件。
- 同时保留并更新了已有发布测试：
  - `tests/test_optimize_profile_script.py::test_publish_btst_optimized_profile_manifest_writes_ready_manifest`
  - 它现在也会检查 canonical source 已经落盘并与 manifest 对齐。
- 运行时侧可直接验证：
  - 当前仓库里的 `data/reports/btst_latest_optimized_profile.json` 现在能解析到稳定 `source_path`，不再因为 `optimized_profile_source_missing` 回退。

## 观察到的权衡
- 这次修复优先的是 **runtime 可靠性**，不是重新评审哪个 profile 应该晋升为新的 baseline。
- canonical source artifact 本质上是为 manifest 保存一份稳定 provenance 副本，会多出一个仓内 JSON sidecar；这是有意的，因为 BTST skill 和 paper trading runtime 需要一个不会随临时输出目录消失的证据锚点。
- 这不会绕过现有 rollout / strict-objective / win-rate-first 治理；如果候选 profile 没被批准，manifest 仍不会发布为 ready。

## 如何使用
- 以后凡是通过 `scripts/optimize_profile.py` 发布 BTST ready manifest，都会自动在 manifest 旁边生成稳定 source artifact；`ai-hedge-fund-btst` 沿用默认 `data/reports/btst_latest_optimized_profile.json` 即可。
- 对 `ai-hedge-fund-btst` 的实际含义是：
  - 当 manifest 是 `ready` 时，skill 更可靠地吃到批准过的 optimized profile；
  - 不会再因为原始 report 落在临时目录、会话目录或自定义易失路径中而退回 `default`。
