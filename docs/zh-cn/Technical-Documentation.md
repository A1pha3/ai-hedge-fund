# AI Hedge Fund 技术概述

> **⚠️ 注意**：本文档是整体概述，详细内容请参考分级文档体系：
> - [Level 1 入门教程](./level1-getting-started/) - 安装配置、快速开始
> - [Level 2 核心概念](./level2-core-concepts/) - 智能体系统、工作流原理
> - [Level 3 进阶分析](./level3-advanced-analysis/) - 开发指南、性能优化
> - [Level 4 专家设计](./level4-expert-design/) - 架构设计、源码解析

## 文档体系总览

本文档为 AI Hedge Fund 项目提供技术参考，补充分级文档体系的概述信息。详细学习内容请参见各层级文档。

**核心特性**：
- 18 个 AI 智能体模拟投资大师分析风格
- LangGraph 框架构建多智能体协作工作流
- 支持多种 LLM 提供商（OpenAI、Anthropic、Groq、DeepSeek、Ollama）
- 完整回测框架用于策略验证

### 三条学习路径

| 路径 | 目标人群 | 详细指南 |
|------|---------|----------|
| **用户路径** | 使用系统进行投资分析 | [Level 1 + Level 2](./level1-getting-started/) |
| **开发者路径** | 扩展和定制系统 | [Level 2 + Level 3 + Level 4](./level2-core-concepts/) |
| **研究者路径** | 理解 AI 投资决策原理 | [Level 2 + Level 3 + Level 4](./level3-advanced-analysis/) |

### 四级文档体系

| 级别 | 内容定位 | 详细文档 |
|------|---------|----------|
| **Level 1** ⭐ | 入门教程，消除恐惧 | [安装配置、第一次运行](./level1-getting-started/) |
| **Level 2** ⭐⭐ | 核心概念，建立体系 | [智能体系统、工作流、数据管理](./level2-core-concepts/) |
| **Level 3** ⭐⭐⭐ | 进阶分析，解决复杂问题 | [智能体开发、回测、部署](./level3-advanced-analysis/) |
| **Level 4** ⭐⭐⭐⭐ | 专家设计，架构决策 | [核心架构、状态图深度剖析](./level4-expert-design/) |
---

> **📚 详细章节已移至分级文档**：
> - 智能体系统详解 → [Level 2 核心概念](./level2-core-concepts/01-agents-overview.md)
> - LangGraph 工作流 → [Level 2 核心概念](./level2-core-concepts/03-workflow.md)
> - 风险管理原理 → [Level 2 核心概念](./level2-core-concepts/05-risk-management.md)
> - 回测框架详解 → [Level 2 核心概念](./level2-core-concepts/07-backtesting.md)

## 核心架构概览

### 系统架构

```
AI Hedge Fund 系统架构
├── 数据层
│   ├── Financial Datasets API
│   ├── 数据缓存与预处理
│   └── 多数据源支持
├── 智能体层（18个专业智能体）
│   ├── 价值投资类（6个）
│   ├── 成长投资类（4个）
│   ├── 专业分析类（6个）
│   └── 宏观策略类（2个）
├── 决策层
│   ├── 风险管理智能体
│   └── 投资组合管理智能体
└── 执行层（模拟）
```

### 支持的 LLM 提供商

| 提供商 | 推荐模型 | 特点 | 适用场景 |
|--------|----------|------|----------|
| OpenAI | GPT-4o, GPT-4o-mini | 综合能力强 | 日常分析 |
| Anthropic | Claude 3.5 Sonnet | 长上下文 | 复杂分析 |
| Groq | Llama 3, Mixtral | 推理速度快 | 实时交互 |
| DeepSeek | DeepSeek Chat | 价格低 | 大规模测试 |
| Ollama | 本地部署 | 完全离线 | 数据隐私 |

---

> **🔧 详细章节已移至分级文档**：
> - 安装配置 → [Level 1 入门教程](./level1-getting-started/01-installation.md)
> - 快速开始 → [Level 1 入门教程](./level1-getting-started/02-first-run.md)
> - 智能体详解 → [Level 2 核心概念](./level2-core-concepts/01-agents-overview.md)
> - 风险管理 → [Level 2 核心概念](./level2-core-concepts/05-risk-management.md)
> - 回测框架 → [Level 2 核心概念](./level2-core-concepts/07-backtesting.md)
> - 故障排除 → [Level 3 进阶分析](./level3-advanced-analysis/04-troubleshooting.md)
> - 术语表 → [references/terminology.md](./references/terminology.md)

---

## 快速参考

### 常用命令速查

| 功能 | 命令 |
|------|------|
| 安装依赖 | `poetry install` |
| 运行分析 | `poetry run python src/main.py --ticker AAPL` |
| 运行回测 | `poetry run python src/backtester.py --ticker AAPL` |
| 启动 API | `poetry run uvicorn app.backend.main:app --reload --host 0.0.0.0 --port 8000` |

### 智能体分类速查

| 类别 | 智能体 |
|------|--------|
| 价值投资 | 巴菲特、芒格、格雷厄姆、达莫达兰、伯里、帕伯莱 |
| 成长投资 | 伍德、林奇、费雪、阿克曼 |
| 专业分析 | 技术分析、基本面、估值、情绪、成长 |
| 宏观策略 | 德鲁肯米勒、朱尼亚尔瓦尔 |

---

## 版本信息

| 项目 | 信息 |
|------|------|
| 文档版本 | 1.1.0 |
| 最后更新 | 2026年2月 |
| 适用版本 | 1.0.0+ |

**更新日志**：
- v1.1.0 (2026.02)：精简重复内容，优化文档结构，添加交叉引用
- v1.0.0 (2025.01)：初始版本 |

> **📚 更多学习资源**：[返回文档体系总览](./SUMMARY.md)