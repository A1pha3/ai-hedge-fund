# 快速参考卡 ⭐

> 本快速参考卡提供最常用的命令、参数和代码片段，便于快速查阅。适合已经了解基本概念，需要快速查阅的开发者和用户。

---

## 📚 学习目标

完成本参考卡的学习后，你将能够：

### 基础目标（必掌握）

- [ ] 快速找到常用命令并正确执行
- [ ] 理解核心参数的作用和默认值
- [ ] 配置基本的环境变量和 API 密钥
- [ ] 运行基本的股票分析和回测

### 进阶目标（建议掌握）

- [ ] 根据需求选择合适的智能体（Agent）组合
- [ ] 调整风险参数以匹配投资策略
- [ ] 使用 Web API 进行集成开发
- [ ] 识别和解决常见错误

### 专家目标（挑战）

- [ ] 设计完整的多智能体交易策略
- [ ] 自定义智能体配置参数
- [ ] 优化回测参数以提升性能
- [ ] 为团队制定最佳实践指南

---

## 🔧 基础配置

### 1. 安装与初始化 ⭐

**为什么使用 Poetry？**
Poetry 是 Python 的依赖管理工具，相比 pip，它提供了更可靠的依赖解析、隔离的虚拟环境和锁定版本的功能，确保团队协作时的环境一致性。

```bash
# 1. 克隆项目
git clone https://github.com/virattt/ai-hedge-fund.git
cd ai-hedge-fund

# 2. 安装 Poetry（依赖管理工具）
curl -sSL https://install.python-poetry.org | python3 -

# 3. 安装项目依赖
poetry install

# 4. 配置 API 密钥
cp .env.example .env
# 使用编辑器打开 .env 文件，添加你的 API 密钥
```

**必需的 API 密钥**：
- **LLM（大语言模型）**提供商密钥：至少需要以下之一
  - `OPENAI_API_KEY`（OpenAI）
  - `ANTHROPIC_API_KEY`（Anthropic）
  - `GROQ_API_KEY`（Groq）
  - `DEEPSEEK_API_KEY`（DeepSeek）
- **金融数据**密钥：
  - `FINANCIAL_DATASETS_API_KEY`（金融数据集 API）

> 💡 **免费数据**：AAPL、GOOGL、MSFT、NVDA、TSLA 的数据是免费的，其他股票需要金融数据 API 密钥。

---

## 🚀 快速开始

### 2. 最小可运行示例 ⭐

```bash
# 分析单只股票（使用默认智能体和参数）
poetry run python src/main.py --ticker AAPL

# 使用本地 Ollama 运行（无需 API 密钥）
poetry run python src/main.py --ticker AAPL --ollama
```

**什么是 Ollama？**
Ollama 是一个开源工具，让你在本地运行大语言模型（LLM），无需调用云端 API，保护隐私且免费。适合开发测试和学习使用。

---

## 📊 核心功能速查

### 3. 命令行分析 ⭐⭐

**使用场景决策树**：
```
Q: 你的分析需求是什么？
├── 单股票快速分析 → 基本分析
├── 多股票批量分析 → 多股票分析
├── 特定时间段分析 → 指定时间范围
├── 使用特定投资风格 → 选择智能体
├── 使用本地模型 → 使用 Ollama
└── 需要详细推理过程 → 显示推理
```

#### 基本命令清单

```bash
# 🎯 基本分析
poetry run python src/main.py --ticker AAPL

# 📊 多股票分析（逗号分隔）
poetry run python src/main.py --ticker AAPL,MSFT,NVDA

# 📅 指定时间范围
poetry run python src/main.py \
  --ticker AAPL \
  --start-date 2024-01-01 \
  --end-date 2024-03-01

# 🧠 选择特定智能体（Agent）
poetry run python src/main.py \
  --ticker AAPL \
  --analysts warren_buffett,ben_graham

# 🤖 使用特定 LLM 模型
poetry run python src/main.py \
  --ticker AAPL \
  --model anthropic

# 💻 使用本地 Ollama
poetry run python src/main.py --ticker AAPL --ollama

# 🔍 显示详细推理过程
poetry run python src/main.py --ticker AAPL --show-reasoning

# 📄 JSON 格式输出（适合脚本处理）
poetry run python src/main.py --ticker AAPL --output json
```

---

### 4. 回测系统 ⭐⭐⭐

**回测的价值**：
回测让你用历史数据验证策略的有效性，避免在真实市场中损失资金。通过模拟过去的表现，可以评估策略的风险调整后收益、最大回撤等关键指标。

```bash
# 🎯 基本回测
poetry run python src/backtester.py --ticker AAPL

# 📊 带参数的高级回测
poetry run python src/backtester.py \
  --ticker AAPL,MSFT,NVDA \
  --start-date 2020-01-01 \
  --end-date 2024-01-01 \
  --initial-capital 100000 \
  --rebalance-frequency monthly
```

**关键参数解释**：

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `initial-capital` | 初始资金 | 100,000（十万） |
| `rebalance-frequency` | 再平衡频率 | monthly（每月） |
| `commission-rate` | 佣金率 | 0.001（0.1%） |

---

### 5. Web 应用 ⭐⭐

**REST API**（Representational State Transfer API）是一种基于 HTTP 协议的网络 API 设计风格，使用标准 HTTP 方法（GET、POST、PUT、DELETE）进行资源操作。

#### 启动 Web 应用

```bash
# 🌐 终端 1：启动后端（FastAPI）
cd app
poetry run uvicorn app.backend.main:app --reload --host 0.0.0.0 --port 8000

# 💻 终端 2：启动前端（React）
cd app/frontend
npm run dev

# 📌 访问地址
# 前端界面：http://localhost:5173
# API 文档：http://localhost:8000/docs（自动生成的 Swagger UI）
```

**技术栈说明**：
- **FastAPI**：现代、快速的 Python Web 框架，自动生成 API 文档
- **React**：Facebook 开发的前端框架，用于构建用户界面

---

## 📖 参数详解

### 6. main.py 参数表 ⭐⭐

| 参数 | 简写 | 描述 | 默认值 | 使用场景 |
|------|------|------|--------|----------|
| `--ticker` | `-t` | 股票代码（必需） | - | 必填，指定分析股票 |
| `--start-date` | - | 开始日期 | 最近 30 天 | 指定分析开始时间 |
| `--end-date` | - | 结束日期 | 今天 | 指定分析结束时间 |
| `--model` | - | **LLM** 提供商 | openai | 选择云端模型 |
| `--ollama` | - | 使用本地 Ollama | False | 无需 API 密钥 |
| `--analysts` | - | **智能体**列表 | 全部 | 选择投资风格 |
| `--show-reasoning` | - | 显示详细推理 | False | 调试和学习 |
| `--risk-tolerance` | - | 风险承受能力 (1-10) | 5 | 调整策略激进程度 |
| `--max-position-size` | - | 最大仓位比例 | 0.05 | 单股票最多占 5% |
| `--output` | - | 输出格式 | text | text（终端）或 json（脚本） |
| `--help` | - | 显示帮助 | - | 查看完整参数 |

**参数选择指南**：

```
Q: 你想如何控制风险？
├── 保守 → risk-tolerance: 1-3
├── 平衡 → risk-tolerance: 4-6（推荐）
└── 激进 → risk-tolerance: 7-10

Q: 你想输出到哪里？
├── 终端查看 → output: text
└── 脚本处理 → output: json
```

---

### 7. backtester.py 参数表 ⭐⭐

| 参数 | 描述 | 默认值 | 推荐值 |
|------|------|--------|--------|
| `--ticker` | 股票代码 | 必需 | - |
| `--start-date` | 开始日期 | 最近 1 年 | 建议 2-5 年 |
| `--end-date` | 结束日期 | 今天 | - |
| `--initial-capital` | 初始资金 | 100000 | 根据预算调整 |
| `--rebalance-frequency` | 再平衡频率 | monthly | daily（高频）或 quarterly（低频） |
| `--commission-rate` | 佣金率 | 0.001 | 根据券商调整 |
| `--model` | LLM 提供商 | openai | 根据成本选择 |
| `--ollama` | 使用本地 Ollama | False | 开发测试时启用 |
| `--analysts` | 智能体列表 | 全部 | 根据策略选择 |

---

## 🤖 智能体（Agent）速查 ⭐⭐

### 什么是智能体（Agent）？
智能体是基于著名投资大师的思维模式设计的 AI 助手，每个智能体代表一种独特的投资哲学和决策风格。通过组合不同的智能体，可以获得更全面的股票分析视角。

| ID | 名称 | 投资风格 | 推荐场景 | 风险偏好 |
|----|------|----------|----------|----------|
| **价值投资派** |
| `warren_buffett` | 沃伦·巴菲特 | 价值投资 | 长期投资、优质公司 | 低 |
| `charlie_munger` | 查理·芒格 | 价值投资 | 质量优先、合理价格 | 低 |
| `ben_graham` | 本杰明·格雷厄姆 | 深度价值 | 严格筛选、安全边际 | 极低 |
| `michael_burry` | 迈克尔·伯里 | 逆向投资 | 寻找被低估的股票 | 中高 |
| **成长投资派** |
| `peter_lynch` | 彼得·林奇 | 成长价值 | 日常发现、十倍股 | 中 |
| `cathie_wood` | 凯茜·伍德 | 激进成长 | 创新领域、颠覆性行业 | 高 |
| `phil_fisher` | 菲利普·费雪 | 深度成长 | 深入调研、长期持有 | 中高 |
| **事件驱动派** |
| `bill_ackman` | 比尔·阿克曼 | 激进投资 | 催化剂驱动、积极干预 | 高 |
| `macro` | 宏观策略 | 宏观分析 | 趋势把握、宏观机会 | 中 |
| **量化分析派** |
| `technical_analyst` | 技术分析师 | 技术分析 | 短期交易、技术指标 | 中 |
| `fundamentals_analyst` | 基本面分析师 | 基本面 | 数据驱动、财务分析 | 低 |
| `sentiment_analyst` | 情绪分析师 | 情绪分析 | 市场情绪、舆论分析 | 中 |
| `valuation_analyst` | 估值分析师 | 估值 | 估值参考、价格评估 | 低 |

**智能体组合策略**：

```bash
# 价值投资组合
--analysts warren_buffett,charlie_munger,ben_graham

# 成长价值平衡
--analysts peter_lynch,phil_fisher,warren_buffett

# 激进成长策略
--analysts cathie_wood,bill_ackman

# 全面分析（推荐）
--analysts warren_buffett,peter_lynch,cathie_wood,michael_burry
```

---

## 🔧 配置文件

### 8. 环境配置 ⭐

```bash
# .env 文件配置示例

# ================================
# LLM 提供商（至少需要一个）
# ================================
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
GROQ_API_KEY=your-groq-key
DEEPSEEK_API_KEY=your-deepseek-key

# ================================
# 金融数据（非股票池内需要）
# ================================
FINANCIAL_DATASETS_API_KEY=your-key

# ================================
# 系统配置
# ================================
LOG_LEVEL=INFO
```

**API 密钥获取指南**：
- **OpenAI**：https://platform.openai.com/api-keys
- **Anthropic**：https://console.anthropic.com/
- **Groq**：https://console.groq.com/
- **Financial Datasets**：https://financialdatasets.ai/

---

### 9. YAML 配置 ⭐⭐

```yaml
# config.yaml 配置示例

analysis:
  default_tickers:
    - AAPL
    - MSFT
  default_model: openai
  show_reasoning: true
  risk_tolerance: 5          # 1-10，5 为平衡
  max_position_size: 0.05   # 单股票最大仓位 5%

backtest:
  initial_capital: 100000
  rebalance_frequency: monthly
  commission_rate: 0.001     # 0.1% 佣金

display:
  output_format: text
```

---

## 🌐 API 速查 ⭐⭐⭐

### 10. REST API 端点

**REST API 基础**：
- **POST**：创建资源（执行分析、回测）
- **GET**：获取资源（查询结果、列表）
- **DELETE**：删除资源（取消任务）

| 方法 | 端点 | 描述 | 示例 |
|------|------|------|------|
| **POST** | `/api/analyze` | 执行分析 | 提交股票分析任务 |
| **GET** | `/api/analyze/{id}` | 获取分析结果 | 查询分析任务状态 |
| **POST** | `/api/backtest` | 执行回测 | 提交回测任务 |
| **GET** | `/api/analysts` | 获取智能体列表 | 查看可用智能体 |
| **GET** | `/api/models` | 获取模型列表 | 查看可用模型 |
| **GET** | `/api/health` | 健康检查 | 检查服务状态 |

### 11. API 请求示例

```bash
# 📊 执行分析
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "tickers": ["AAPL"],
    "analysts": ["warren_buffett", "peter_lynch"]
  }'

# 📄 获取分析结果（替换 {analysis_id} 为实际 ID）
curl http://localhost:8000/api/analyze/{analysis_id}

# 🧪 健康检查
curl http://localhost:8000/api/health
```

**Python 示例**：
```python
import requests

# 执行分析
response = requests.post(
    "http://localhost:8000/api/analyze",
    json={
        "tickers": ["AAPL", "MSFT"],
        "analysts": ["warren_buffett", "peter_lynch"],
        "model": "openai"
    }
)

analysis_id = response.json()["id"]
print(f"分析 ID: {analysis_id}")

# 获取结果
result = requests.get(f"http://localhost:8000/api/analyze/{analysis_id}")
print(result.json())
```

---

## ⚠️ 错误处理

### 12. 常见错误代码 ⭐

| 代码 | 错误类型 | 描述 | 解决方案 |
|------|----------|------|----------|
| **400** | Bad Request | 请求参数错误 | 检查 JSON 格式和参数类型 |
| **401** | Unauthorized | API 密钥无效 | 检查 `.env` 配置，确认密钥正确 |
| **429** | Rate Limit | API 调用超限 | 降低调用频率或升级订阅 |
| **500** | Internal Error | 服务器内部错误 | 查看日志，提交 Issue |
| **503** | Service Unavailable | 服务不可用 | 稍后重试，检查服务状态 |

### 13. 错误排查流程

```
遇到错误时：

1. 检查错误代码
   └── 4xx → 客户端问题（参数、密钥）
   └── 5xx → 服务器问题（服务、Bug）

2. 查看详细日志
   └── tail -f logs/app.log

3. 检查配置文件
   └── 验证 .env 和 config.yaml

4. 尝试简化请求
   └── 减少参数，逐步排查

5. 查询文档或提交 Issue
   └── https://github.com/virattt/ai-hedge-fund/issues
```

---

## 📈 风险指标

### 14. 风险指标速查 ⭐⭐⭐

**为什么需要风险指标？**
风险指标帮助你量化投资组合的风险水平，避免超出承受能力的损失。理解这些指标是成为成熟投资者的必经之路。

| 指标 | 英文全称 | 描述 | 解读 | 优秀标准 |
|------|----------|------|------|----------|
| **VaR** | Value at Risk | **风险价值**：在 95% 置信度下可能的最大损失 | 越小越好 | < 5% |
| **夏普比率** | Sharpe Ratio | **风险调整后收益**：每承担一单位风险获得的超额收益 | 越高越好 | > 1.0 |
| **最大回撤** | Max Drawdown | 从峰值到谷值的最大跌幅 | 越小越好 | < 20% |
| **波动率** | Volatility | 价格变动的剧烈程度，年化表示 | 适中为好 | 15-25% |
| **置信度** | Confidence | 智能体对决策的确定性程度 | 0-100 | > 70% |

**风险指标解读示例**：

```
示例：某策略的风险指标
├── VaR: 3.5% → 在 95% 可能性下，单日最大损失 3.5%
├── 夏普比率: 1.2 → 风险调整后收益优秀
├── 最大回撤: 12% → 从峰值最大下跌 12%（可接受）
├── 波动率: 18% → 中等波动（稳健型）
└── 置信度: 85% → 智能体高度确定

结论：这是一个稳健且收益良好的策略
```

---

## 📁 项目结构

### 15. 文件路径速查 ⭐

```
项目根目录/
├── 📦 src/                          # 源代码
│   ├── main.py                      # 主入口（CLI）
│   ├── backtester.py                # 回测入口
│   ├── agents/                      # 智能体定义
│   │   ├── value/                   # 价值投资派
│   │   ├── growth/                  # 成长投资派
│   │   └── quant/                   # 量化分析派
│   ├── data/                        # 数据处理
│   ├── graph/                       # LangGraph 工作流
│   ├── llm/                         # LLM 集成
│   └── tools/                       # 工具函数
│
├── 🌐 app/                          # Web 应用
│   ├── backend/                     # FastAPI 后端
│   └── frontend/                    # React 前端
│
├── 📚 docs/                         # 文档
│   └── zh-cn/                       # 中文文档
│
├── 🧪 tests/                        # 测试文件
│
├── ⚙️ config/                       # 配置文件
│   └── config.yaml                  # 默认配置
│
├── .env                             # 环境变量（需创建）
├── .env.example                     # 环境变量示例
├── pyproject.toml                   # Poetry 配置
└── README.md                        # 项目说明
```

---

## 🔨 开发工具

### 16. Git 命令速查 ⭐

**工作流程**：
```
开发流程：
1. 创建分支 → 2. 编写代码 → 3. 提交更改 → 4. 同步上游 → 5. 创建 PR
```

```bash
# 🌿 创建功能分支
git checkout -b feature/your-feature

# ✅ 提交更改
git add .
git commit -m "feat(agents): 添加新智能体"

# 🔄 同步上游更新
git fetch upstream
git merge upstream/main

# 📤 推送到远程
git push origin feature/your-feature

# 🔗 在 GitHub 上创建 Pull Request
```

**提交信息规范**：
- `feat:` 新功能
- `fix:` 修复 Bug
- `docs:` 文档更新
- `refactor:` 重构
- `test:` 测试

---

### 17. Docker 命令速查 ⭐⭐

**什么是 Docker？**
Docker 是一个容器化平台，让应用在任何环境中以相同方式运行。通过容器化，可以避免"在我的机器上能跑"的问题，简化部署流程。

```bash
# 🏗️ 构建镜像
docker build -t ai-hedge-fund .

# 🚀 运行容器
docker run -p 8000:8000 -p 5173:5173 ai-hedge-fund

# 📋 查看日志
docker logs -f ai-hedge-fund

# 🔍 进入容器（调试用）
docker exec -it ai-hedge-fund /bin/bash

# 🗑️ 清理容器
docker stop ai-hedge-fund
docker rm ai-hedge-fund
```

---

## 🎓 练习任务

### 练习 1：基础命令 ⭐

**任务**：运行第一次股票分析

```bash
# 1. 分析 AAPL 股票（使用默认参数）
poetry run python src/main.py --ticker AAPL

# 2. 查看输出，理解每个智能体的建议

# 3. 使用本地 Ollama 重新分析（如果已安装）
poetry run python src/main.py --ticker AAPL --ollama
```

**验证标准**：
- [ ] 成功执行命令，无错误
- [ ] 理解输出的基本信息
- [ ] 知道如何查看详细推理

---

### 练习 2：参数调整 ⭐⭐

**任务**：比较不同参数的结果

```bash
# 1. 使用不同的智能体组合
# 价值投资派
poetry run python src/main.py --ticker AAPL --analysts warren_buffett,ben_graham

# 成长投资派
poetry run python src/main.py --ticker AAPL --analysts cathie_wood,peter_lynch

# 2. 调整风险承受能力
# 保守
poetry run python src/main.py --ticker AAPL --risk-tolerance 3

# 激进
poetry run python src/main.py --ticker AAPL --risk-tolerance 8
```

**验证标准**：
- [ ] 理解不同智能体的决策风格
- [ ] 观察风险参数对结果的影响
- [ ] 能选择适合自己风格的参数

---

### 练习 3：回测系统 ⭐⭐

**任务**：运行完整的回测分析

```bash
# 1. 回测单只股票
poetry run python src/backtester.py --ticker AAPL

# 2. 回测多股票组合
poetry run python src/backtester.py \
  --ticker AAPL,MSFT,NVDA \
  --start-date 2022-01-01 \
  --end-date 2024-01-01

# 3. 理解风险指标
# 查看输出中的 VaR、夏普比率、最大回撤
```

**验证标准**：
- [ ] 成功运行回测
- [ ] 理解各项风险指标的含义
- [ ] 能判断策略的好坏

---

### 练习 4：API 集成 ⭐⭐⭐

**任务**：使用 API 构建简单的分析工具

```python
# 创建 analyze_stocks.py
import requests
import json

API_URL = "http://localhost:8000"

def analyze_stocks(tickers):
    """批量分析股票"""
    response = requests.post(
        f"{API_URL}/api/analyze",
        json={
            "tickers": tickers,
            "analysts": ["warren_buffett", "peter_lynch"]
        }
    )
    return response.json()

# 测试
result = analyze_stocks(["AAPL", "MSFT"])
print(json.dumps(result, indent=2))
```

**验证标准**：
- [ ] 成功调用 API
- [ ] 理解 API 响应结构
- [ ] 能处理异步任务

---

## 🔗 有用链接

### 16. 外部资源

| 资源 | URL | 用途 |
|------|-----|------|
| **GitHub 仓库** | https://github.com/virattt/ai-hedge-fund | 源代码和问题跟踪 |
| **问题跟踪** | https://github.com/virattt/ai-hedge-fund/issues | 报告 Bug 和功能请求 |
| **LangChain 文档** | https://python.langchain.com | LLM 应用框架 |
| **LangGraph 文档** | https://langchain-ai.github.io/langgraph | 智能体工作流框架 |
| **Financial Datasets** | https://financialdatasets.ai | 金融数据 API |
| **Poetry 文档** | https://python-poetry.org | Python 依赖管理 |
| **FastAPI 文档** | https://fastapi.tiangolo.com | Python Web 框架 |
| **React 文档** | https://react.dev | 前端框架 |
| **Ollama 文档** | https://ollama.ai | 本地 LLM 运行工具 |

---

## ✅ 自检清单

完成本参考卡的学习后，请自检以下能力：

### 基础技能 ⭐
- [ ] 能够独立运行股票分析命令
- [ ] 理解基本参数的作用
- [ ] 能够配置环境变量和 API 密钥
- [ ] 知道如何查看帮助信息

### 进阶技能 ⭐⭐
- [ ] 能够选择合适的智能体组合
- [ ] 理解风险指标的含义
- [ ] 能够运行回测并解读结果
- [ ] 能够使用 API 进行集成开发

### 专家技能 ⭐⭐⭐
- [ ] 能够设计复杂的多智能体策略
- [ ] 能够优化回测参数
- [ ] 能够诊断和解决常见问题
- [ ] 能够为他人提供指导

---

## 📝 快速备忘

### 常用参数组合

```bash
# 🎯 快速分析（单股票，默认参数）
--ticker AAPL

# 📊 多股票分析（默认智能体）
--ticker AAPL,MSFT,NVDA

# 🧠 价值投资组合
--ticker AAPL --analysts warren_buffett,ben_graham

# 💻 本地运行（无 API 成本）
--ticker AAPL --ollama

# 🔍 详细推理（学习用）
--ticker AAPL --show-reasoning

# 🚨 高风险策略
--ticker AAPL --risk-tolerance 8 --analysts cathie_wood

# 📄 输出 JSON（脚本处理）
--ticker AAPL --output json
```

---

## 💡 最佳实践

1. **从简单开始**：先用默认参数，理解基本流程
2. **本地测试**：使用 Ollama 在本地测试，节省 API 成本
3. **多样化智能体**：组合不同风格的智能体，获得全面视角
4. **风险管理**：始终关注风险指标，不要盲目追求高收益
5. **持续学习**：阅读智能体的详细文档，理解其投资哲学
6. **记录实验**：使用 Git 或文档记录有效的参数组合

---

## 🆘 遇到问题？

1. **检查文档**：先查看完整文档 [docs/zh-cn/](../)
2. **搜索问题**：在 [Issues](https://github.com/virattt/ai-hedge-fund/issues) 搜索类似问题
3. **提交 Issue**：如果没有找到答案，提交详细的 Issue
4. **查看日志**：使用 `--show-reasoning` 查看详细推理过程
5. **简化问题**：用最小示例复现问题

---

> 💡 **学习提示**：这是一个快速参考卡，不是完整的教程。如果你是第一次使用，建议先阅读完整的入门教程。

---

**文档版本**：v2.1.0
**最后更新**：2026-02-13
**维护者**：AI Hedge Fund 团队
