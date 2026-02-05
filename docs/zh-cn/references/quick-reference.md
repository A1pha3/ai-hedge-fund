# 快速参考卡

本快速参考卡提供最常用的命令、参数和代码片段，便于快速查阅。

## 命令速查

### 安装与配置

```bash
# 克隆项目
git clone https://github.com/virattt/ai-hedge-fund.git
cd ai-hedge-fund

# 安装 Poetry
curl -sSL https://install.python-poetry.org | python3 -

# 安装依赖
poetry install

# 配置 API 密钥
cp .env.example .env
# 编辑 .env 添加密钥
```

### 命令行分析

```bash
# 基本分析
poetry run python src/main.py --ticker AAPL

# 多股票分析
poetry run python src/main.py --ticker AAPL,MSFT,NVDA

# 指定时间范围
poetry run python src/main.py --ticker AAPL --start-date 2024-01-01 --end-date 2024-03-01

# 选择特定智能体
poetry run python src/main.py --ticker AAPL --analysts warren_buffett,ben_graham

# 使用特定模型
poetry run python src/main.py --ticker AAPL --model anthropic

# 使用本地 Ollama
poetry run python src/main.py --ticker AAPL --ollama

# 显示详细推理
poetry run python src/main.py --ticker AAPL --show-reasoning

# JSON 格式输出
poetry run python src/main.py --ticker AAPL --output json
```

### 回测命令

```bash
# 基本回测
poetry run python src/backtester.py --ticker AAPL

# 带参数回测
poetry run python src/backtester.py \
    --ticker AAPL,MSFT,NVDA \
    --start-date 2020-01-01 \
    --end-date 2024-01-01 \
    --initial-capital 100000 \
    --rebalance-frequency monthly
```

### Web 应用

```bash
# 启动后端
cd app
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 启动前端（新终端）
cd app
npm run dev

# 访问地址
# 前端：http://localhost:5173
# API 文档：http://localhost:8000/docs
```

## 参数速查

### main.py 参数

| 参数 | 简写 | 描述 | 默认值 |
|------|------|------|--------|
| --ticker | -t | 股票代码（必需） | - |
| --start-date | - | 开始日期 | 最近 30 天 |
| --end-date | - | 结束日期 | 今天 |
| --model | - | LLM 提供商 | openai |
| --ollama | - | 使用本地 Ollama | False |
| --analysts | - | 智能体列表 | 全部 |
| --show-reasoning | - | 显示详细推理 | False |
| --risk-tolerance | - | 风险承受能力 (1-10) | 5 |
| --max-position-size | - | 最大仓位比例 | 0.05 |
| --output | - | 输出格式 (text/json) | text |
| --help | - | 显示帮助 | - |

### backtester.py 参数

| 参数 | 描述 | 默认值 |
|------|------|--------|
| --ticker | 股票代码 | 必需 |
| --start-date | 开始日期 | 最近 1 年 |
| --end-date | 结束日期 | 今天 |
| --initial-capital | 初始资金 | 100000 |
| --rebalance-frequency | 再平衡频率 | monthly |
| --commission-rate | 佣金率 | 0.001 |
| --model | LLM 提供商 | openai |
| --ollama | 使用本地 Ollama | False |
| --analysts | 智能体列表 | 全部 |

## 智能体速查

| ID | 名称 | 风格 | 推荐场景 |
|----|------|------|----------|
| warren_buffett | 沃伦·巴菲特 | 价值投资 | 长期投资 |
| charlie_munger | 查理·芒格 | 价值投资 | 质量优先 |
| ben_graham | 本杰明·格雷厄姆 | 深度价值 | 严格筛选 |
| peter_lynch | 彼得·林奇 | 成长价值 | 日常发现 |
| cathie_wood | 凯茜·伍德 | 激进成长 | 创新领域 |
| phil_fisher | 菲利普·费雪 | 深度成长 | 深入调研 |
| bill_ackman | 比尔·阿克曼 | 激进投资 | 催化剂驱动 |
| michael_burry | 迈克尔·伯里 | 逆向投资 | 风险识别 |
| stanley_druckenmiller | 斯坦利·德鲁肯米勒 | 宏观策略 | 趋势把握 |
| technical_analyst | 技术分析师 | 技术分析 | 短期交易 |
| fundamentals_analyst | 基本面分析师 | 基本面 | 数据驱动 |
| sentiment_analyst | 情绪分析师 | 情绪分析 | 市场情绪 |
| valuation_analyst | 估值分析师 | 估值 | 估值参考 |

## 配置文件示例

### .env 配置

```bash
# LLM 提供商
OPENAI_API_KEY=sk-your-key
ANTHROPIC_API_KEY=your-key
GROQ_API_KEY=your-key
DEEPSEEK_API_KEY=your-key

# 金融数据
FINANCIAL_DATASETS_API_KEY=your-key

# 日志级别
LOG_LEVEL=INFO
```

### config.yaml 分析配置

```yaml
analysis:
  default_tickers:
    - AAPL
    - MSFT
  default_model: openai
  show_reasoning: true
  risk_tolerance: 5
  max_position_size: 0.05

backtest:
  initial_capital: 100000
  rebalance_frequency: monthly
  commission_rate: 0.001

display:
  output_format: text
```

## API 端点速查

### REST API

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | /api/analyze | 执行分析 |
| GET | /api/analyze/{id} | 获取分析结果 |
| POST | /api/backtest | 执行回测 |
| GET | /api/analysts | 获取智能体列表 |
| GET | /api/models | 获取模型列表 |
| GET | /api/health | 健康检查 |

### 请求示例

```bash
# 执行分析
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"tickers": ["AAPL"], "analysts": ["warren_buffett"]}'

# 获取分析结果
curl http://localhost:8000/api/analyze/{analysis_id}
```

## 错误代码速查

| 代码 | 错误类型 | 描述 | 解决方案 |
|------|----------|------|----------|
| 400 | Bad Request | 请求参数错误 | 检查参数格式 |
| 401 | Unauthorized | API 密钥无效 | 检查 .env 配置 |
| 429 | Rate Limit | API 调用超限 | 降低调用频率 |
| 500 | Internal Error | 服务器内部错误 | 查看日志 |
| 503 | Service Unavailable | 服务不可用 | 稍后重试 |

## 风险指标速查

| 指标 | 描述 | 解读 |
|------|------|------|
| VaR | 风险价值 | 95% 置信度下的最大损失 |
| 夏普比率 | 风险调整后收益 | 越高越好 |
| 最大回撤 | 从峰值到谷值的跌幅 | 越小越好 |
| 波动率 | 价格变动程度 | 年化表示 |
| 置信度 | 智能体确定性 | 0-100 |

## 文件路径速查

```
项目根目录/
├── src/
│   ├── main.py           # 主入口
│   ├── backtester.py     # 回测入口
│   ├── agents/           # 智能体
│   ├── data/            # 数据处理
│   ├── graph/           # 工作流
│   ├── llm/            # LLM 集成
│   └── tools/           # 工具函数
├── app/
│   ├── backend/         # FastAPI 后端
│   └── frontend/        # React 前端
├── docs/
│   └── zh-cn/          # 中文文档
├── tests/              # 测试文件
└── config/             # 配置文件
```

## Git 命令速查

```bash
# 创建功能分支
git checkout -b feature/your-feature

# 提交更改
git add .
git commit -m "feat(agents): 添加新智能体"

# 同步上游
git fetch upstream
git merge upstream/main

# 创建 PR
git push origin feature/your-feature
# 然后在 GitHub 上创建 Pull Request
```

## Docker 命令速查

```bash
# 构建镜像
docker build -t ai-hedge-fund .

# 运行容器
docker run -p 8000:8000 -p 5173:5173 ai-hedge-fund

# 查看日志
docker logs -f ai-hedge-fund

# 进入容器
docker exec -it ai-hedge-fund /bin/bash
```

## 有用链接

| 资源 | URL |
|------|-----|
| GitHub 仓库 | https://github.com/virattt/ai-hedge-fund |
| 问题跟踪 | https://github.com/virattt/ai-hedge-fund/issues |
| LangChain 文档 | https://python.langchain.com |
| LangGraph 文档 | https://langchain-ai.github.io/langgraph |
| Financial Datasets | https://financialdatasets.ai |
