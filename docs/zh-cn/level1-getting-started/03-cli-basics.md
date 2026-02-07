# 第三章：命令行工具详解

## 学习目标

完成本章节学习后，你将能够熟练使用命令行工具的各项参数，理解常用选项的作用和用法，掌握输出格式的配置方法，以及学会使用配置文件简化日常操作。预计学习时间为 30 分钟至 1 小时。

## 3.1 main.py 命令行接口概述

`src/main.py` 是系统的主要入口点，提供完整的命令行分析功能。命令的基本语法结构如下：

```bash
poetry run python src/main.py [OPTIONS]
```

其中 `[OPTIONS]` 代表可选的命令行参数。本节将详细介绍所有可用的命令行参数，帮助你充分发挥系统的功能。

## 3.2 必需参数

### ticker 参数

`-t/--ticker` 是唯一必需的参数，用于指定要分析的股票代码。

**基本用法**：

```bash
# 分析单只股票
poetry run python src/main.py --ticker AAPL

# 分析多只股票
poetry run python src/main.py --ticker AAPL,MSFT,NVDA
```

**参数说明**：多个股票代码用逗号分隔，不支持空格分隔。如果需要分析多个股票，应使用 `AAPL,MSFT` 而非 `AAPL, MSFT`。股票代码通常为 1-5 个大写字母。

**常见股票代码示例**：AAPL 代表苹果公司，MSFT 代表微软公司，GOOGL 代表谷歌公司，AMZN 代表亚马逊公司，TSLA 代表特斯拉公司。

## 3.3 可选参数

### 时间范围参数

`--start-date` 和 `--end-date` 用于指定分析的时间范围，格式为 `YYYY-MM-DD`。

**用法示例**：

```bash
# 指定开始日期
poetry run python src/main.py --ticker AAPL --start-date 2024-01-01

# 指定结束日期
poetry run python src/main.py --ticker AAPL --end-date 2024-03-01

# 同时指定起止日期
poetry run python src/main.py --ticker AAPL --start-date 2024-01-01 --end-date 2024-03-01
```

**说明**：如果不指定时间范围，系统默认使用最近 30 天的数据进行分析。

### 模型选择参数

`--model` 用于指定使用的 LLM 提供商，可选值包括 `openai`（默认）、`anthropic`、`groq`、`deepseek`。

**用法示例**：

```bash
# 使用 OpenAI GPT-4o（默认）
poetry run python src/main.py --ticker AAPL --model openai

# 使用 Anthropic Claude
poetry run python src/main.py --ticker AAPL --model anthropic

# 使用 Groq 高速推理
poetry run python src/main.py --ticker AAPL --model groq

# 使用 DeepSeek
poetry run python src/main.py --ticker AAPL --model deepseek
```

### 本地模型参数

`--ollama` 标志启用本地 Ollama 模型。

**用法示例**：

```bash
poetry run python src/main.py --ticker AAPL --ollama
```

**前置条件**：使用此功能需要提前安装和配置 Ollama 服务，并下载相应的模型。

### 智能体选择参数

`--analysts` 用于指定参与分析的智能体列表，默认为所有智能体。

**用法示例**：

```bash
# 选择特定智能体
poetry run python src/main.py --ticker AAPL --analysts warren_buffett,ben_graham

# 选择技术分析相关智能体
poetry run python src/main.py --ticker AAPL --analysts technical_analyst,fundamentals_analyst
```

**可用智能体标识符列表**：

| 标识符 | 智能体名称 | 投资风格 |
|--------|------------|----------|
| warren_buffett | 沃伦·巴菲特 | 价值投资 |
| charlie_munger | 查理·芒格 | 价值投资 |
| ben_graham | 本杰明·格雷厄姆 | 深度价值 |
| peter_lynch | 彼得·林奇 | 成长价值 |
| cathie_wood | 凯茜·伍德 | 激进成长 |
| phil_fisher | 菲利普·费雪 | 深度成长 |
| bill_ackman | 比尔·阿克曼 | 激进投资 |
| michael_burry | 迈克尔·伯里 | 逆向投资 |
| stanley_druckenmiller | 斯坦利·德鲁肯米勒 | 宏观策略 |
| technical_analyst | 技术分析师 | 技术分析 |
| fundamentals_analyst | 基本面分析师 | 基本面分析 |
| sentiment_analyst | 情绪分析师 | 情绪分析 |
| valuation_analyst | 估值分析师 | 估值分析 |

### 详细输出参数

`--show-reasoning` 标志显示各智能体的详细推理过程。

**用法示例**：

```bash
poetry run python src/main.py --ticker AAPL --show-reasoning
```

**输出效果**：启用此选项后，每个智能体的输出会包含更详细的分析步骤和判断依据，帮助你理解智能体的决策逻辑。

### 风险设置参数

`--risk-tolerance` 设置风险承受能力等级，范围为 1-10。

**用法示例**：

```bash
# 低风险承受（保守型）
poetry run python src/main.py --ticker AAPL --risk-tolerance 3

# 高风险承受（激进型）
poetry run python src/main.py --ticker AAPL --risk-tolerance 8
```

**影响**：风险承受能力越低，系统推荐的仓位越小，止损设置越严格。

### 仓位限制参数

`--max-position-size` 设置单只股票的最大仓位比例。

**用法示例**：

```bash
poetry run python src/main.py --ticker AAPL --max-position-size 0.10
```

**说明**：参数值为小数形式，0.10 表示 10%。默认为 0.05（5%）。

### 输出格式参数

`--output` 设置输出格式，可选值为 `text`（默认）和 `json`。

**用法示例**：

```bash
# JSON 格式输出
poetry run python src/main.py --ticker AAPL --output json

# 保存到文件
poetry run python src/main.py --ticker AAPL --output json > result.json
```

### 帮助参数

`--help` 显示所有可用的命令行参数及其说明。

**用法示例**：

```bash
poetry run python src/main.py --help
```

## 3.4 实用命令组合

### 快速分析命令

```bash
# 最简分析命令
poetry run python src/main.py --ticker AAPL
```

### 详细分析命令

```bash
# 完整分析命令
poetry run python src/main.py \
    --ticker AAPL,MSFT,NVDA \
    --start-date 2024-01-01 \
    --end-date 2024-06-30 \
    --model anthropic \
    --show-reasoning \
    --output json
```

### 指定智能体分析

```bash
# 仅价值投资风格分析
poetry run python src/main.py \
    --ticker AAPL \
    --analysts warren_buffett,charlie_munger,ben_graham \
    --output json
```

### 本地模型分析

```bash
# 使用本地 Ollama
poetry run python src/main.py \
    --ticker AAPL \
    --ollama \
    --model llama3
```

## 3.5 配置文件使用

### 创建配置文件

对于常用的配置选项，可以创建配置文件来避免每次输入大量参数。配置文件使用 YAML 格式。

创建文件 `config.yaml`：

```yaml
# 分析配置
analysis:
  default_tickers:
    - AAPL
    - MSFT
    - GOOGL
  default_model: openai
  show_reasoning: true
  risk_tolerance: 5
  max_position_size: 0.05

# 回测配置
backtest:
  initial_capital: 100000
  rebalance_frequency: monthly
  commission_rate: 0.001

# 显示配置
display:
  output_format: text
```

### 使用配置文件

```bash
# 使用默认配置文件
poetry run python src/main.py --ticker AAPL --config config.yaml

# 使用自定义配置文件
poetry run python src/main.py --ticker AAPL --config /path/to/config.yaml
```

### 配置文件优先级

系统按以下顺序读取配置：命令行参数优先级最高，会覆盖配置文件中的相同选项；项目根目录的 `config.yaml` 次之；用户主目录下的配置文件优先级最低。

## 3.6 常见用法问答

**问：如何只分析特定风格的智能体？**

使用 `--analysts` 参数指定智能体标识符。例如，分析价值投资风格：`--analysts warren_buffett,charlie_munger,ben_graham`。

**问：如何加快分析速度？**

可以采取以下方法：减少 `--analysts` 参数中的智能体数量；使用更快的 LLM 提供商（如 Groq）；使用本地 Ollama 模型（消除网络延迟）；缩短时间范围。

**问：如何保存分析结果供后续查看？**

可以使用 JSON 格式输出并重定向到文件：`poetry run python src/main.py --ticker AAPL --output json > result.json`。

**问：如何设置默认的模型和其他选项？**

创建 `config.yaml` 配置文件，设置 `analysis` 部分的所有选项。系统会自动读取默认配置文件。

## 3.7 练习题

### 练习 3.1：参数组合练习

**任务**：使用至少 5 个不同的命令行参数执行分析。

**步骤**：首先选择一只股票（如 AAPL），然后组合使用时间范围、模型选择、智能体选择、显示推理等参数，最后记录所有使用的参数。

**成功标准**：能够正确使用至少 5 个不同的参数，并能解释每个参数的作用。

### 练习 3.2：配置文件创建

**任务**：创建个人化的配置文件。

**步骤**：首先创建一个 `my_config.yaml` 文件，然后设置默认股票、模型、风险偏好等选项，接着使用配置文件运行分析，最后比较使用配置文件前后的命令差异。

**成功标准**：能够创建并正确使用配置文件，配置文件包含至少 5 个自定义选项。

### 练习 3.3：智能体风格对比

**任务**：对比不同智能体组合对同一股票的分析结果。

**步骤**：首先创建三个配置文件分别对应价值投资、成长投资、技术分析三种风格，然后分别使用这三个配置文件运行分析，最后比较三种风格的分析结果差异。

**成功标准**：能够清晰描述三种投资风格的分析视角差异，并能指出各风格的优劣势。

---

## 进阶思考

思考以下问题。命令行参数和配置文件各有优缺点，在什么场景下应该使用哪种方式？如何设计配置文件结构以支持不同用户（保守型、激进型）的个性化需求？是否可以创建一个「最佳实践」配置作为新用户的起点？

下一章节我们将学习 Web 界面的使用方法。

---

## 版本信息

| 项目 | 信息 |
|------|------|
| 文档版本 | 1.0.2 |
| 最后更新 | 2026年2月 |
| 适用版本 | 1.0.0+ |

**更新日志**：
- v1.0.2 (2026.02)：修正命令参数，增加配置文件示例
- v1.0.1 (2025.12)：增加智能体标识符表格
- v1.0.0 (2025.10)：初始版本

## 反馈与贡献

如果您在使用过程中发现问题或有改进建议，欢迎通过 GitHub Issues 提交反馈。
