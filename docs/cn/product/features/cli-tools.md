# 9. CLI 工具

> 本节对应主文档 §9,包含主要运行模式。完整 CLI 速查表见 [cli-reference.md](./cli-reference.md)。

## 9.1 主要运行模式

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 单票分析模式 | ✅ | `--ticker AAPL` |
| 2 | 多票分析模式 | ✅ | `--ticker AAPL,MSFT,NVDA` |
| 3 | A 股模式 | ✅ | `--ticker 000001,000880` |
| 4 | 全市场自动筛选 | ✅ | `--auto` — Layer A → B → C 全流程 |
| 5 | 解释推荐原因 | ✅ | `--explain 000001` — 读取报告解释推荐逻辑 |
| 6 | 每日涨幅筛选 | ✅ | `--daily-gainers` |
| 7 | 流水线模式 | ✅ | `--pipeline` — 完整日度执行流水线 |
| 8 | 仅筛选模式 | ✅ | `--screen-only` — 只跑 Layer A + Layer B |
| 9 | 模型配置查看 | ✅ | `--show-default-model` |

---

**完整 CLI 速查表**: [CLI 命令速查表](./cli-reference.md)

**相关章节**: [1. 核心筛选流水线](./core-pipeline.md) | [2. 执行系统](./execution-system.md)
