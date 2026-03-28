# 双目标系统架构文档索引

> 文档元信息
>
> - 首次创建日期：2026-03-28
> - 最近整理时间：2026-03-28 09:45:53 CST
> - 文档目录：docs/zh-cn/product/arch/dual_target_system/

本目录集中存放本轮“双目标选股与次日短线交易目标系统”架构改造的专题文档，便于统一查找、评审和后续实现。

## 文档清单

1. [双目标选股与交易目标系统架构设计文档](./arch_dual_target_selection_system.md)
2. [次日短线目标指标与验证方案](./short_trade_target_metrics_and_validation.md)
3. [次日短线目标首版规则集规格](./short_trade_target_rule_spec.md)
4. [双目标系统数据结构与 Artifact Schema 规格](./dual_target_data_contract_and_artifact_schema.md)
5. [双目标系统实施与代码改造计划](./dual_target_implementation_plan.md)

## 使用建议

1. 先阅读架构总纲，再看指标验证、规则规格、数据契约和实施计划。
2. 评审时优先以本目录为入口，避免继续从 arch 根目录分散查找。
3. 后续若该专题继续扩展，统一放在本目录下并同步更新时间戳。
