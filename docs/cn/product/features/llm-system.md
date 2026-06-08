# 7. LLM 系统

> 本节对应主文档 §7,包含多模型支持、调用框架。

## 7.1 多模型支持

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 16+ LLM 提供商 | ✅ | OpenAI/Anthropic/DeepSeek/Groq/Google/Ollama/Zhipu 等 |
| 2 | 并行 Provider 执行计划 | ✅ | `src/utils/llm.py` — 多 Provider 并行调用 |
| 3 | Provider 路由 | ✅ | `src/utils/llm_provider_routing.py` |
| 4 | 双 Provider 模式 | ✅ | 主/备 Provider 配置 |
| 5 | Ollama 本地模型支持 | ✅ | `src/utils/ollama.py` — 自动下载模型 |
| 6 | 模型目录管理 | ✅ | `src/llm/model_catalog_helpers.py` |

## 7.2 调用框架

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 统一 LLM 调用接口 | ✅ | `src/utils/llm.py: call_llm()` — 唯一 LLM 入口 |
| 2 | JSON 输出助手 | ✅ | `src/utils/llm_json_helpers.py` |
| 3 | LLM 调用指标收集 | ✅ | `src/monitoring/llm_metrics.py` — 完整的调用统计 |
| 4 | 指标摘要脚本 | ✅ | `scripts/summarize_llm_metrics.py` |
| 5 | 模型选择工具 | ✅ | `scripts/model_selection.py` |
| 6 | 模型列表工具 | ✅ | `scripts/list-models.py` |

---

**相关章节**: [8. Agent 系统](./agents.md) | [6. 数据基础设施](./data-infrastructure.md)
