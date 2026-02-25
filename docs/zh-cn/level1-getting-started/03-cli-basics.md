# 第三章：命令行工具详解

## 学习目标

完成本章节学习后，你将能够：

### 基础目标（必掌握）⭐

- [ ] 理解命令行接口（CLI）的核心设计原则和使用场景
- [ ] 掌握必需参数 `--ticker` 的基本用法
- [ ] 能够使用至少 3 个常用参数执行股票分析
- [ ] 理解不同 LLM（大语言模型）提供商的特点和选择依据

### 进阶目标（建议掌握）⭐⭐

- [ ] 能够创建和使用 YAML 格式的配置文件简化操作
- [ ] 理解参数优先级和覆盖机制
- [ ] 能够根据投资需求选择合适的智能体组合
- [ ] 掌握不同输出格式（text/json）的使用场景

### 专家目标（挑战）⭐⭐⭐

- [ ] 能够设计符合个人投资风格的配置模板
- [ ] 理解命令行接口的设计权衡和扩展性
- [ ] 能够为团队制定 CLI 使用最佳实践规范

**预计学习时间**：30 分钟至 1 小时

---

## 3.1 命令行接口设计思想

### 为什么需要命令行工具？

在开始学习具体参数之前，我们需要先理解**为什么系统要提供命令行接口**。

### 设计权衡

**命令行 vs 图形界面**：

| 特性 | 命令行（CLI） | 图形界面（Web） |
|------|-------------|----------------|
| 学习曲线 | 较陡 | 平缓 |
| 效率 | 高（熟练后） | 中等 |
| 自动化 | 易于脚本化 | 困难 |
| 灵活性 | 极高 | 有限 |
| 适用场景 | 批量分析、自动化 | 交互式探索、可视化 |

**适用场景分析**：

```
选择命令行的情况：
├── 需要批量分析多只股票
├── 需要集成到自动化脚本中
├── 需要精细控制每个参数
└── 偏好键盘操作

选择 Web 界面的情况：
├── 首次使用，希望快速上手
├── 需要可视化展示结果
├── 偏好鼠标操作
└── 进行交互式探索
```

### 命令结构原理

系统采用典型的 POSIX 风格命令设计：

```bash
poetry run python src/main.py [OPTIONS]
```

**设计说明**：

1. **`poetry run`** - 使用 Poetry 虚拟环境，确保依赖隔离
2. **`python src/main.py`** - 执行 Python 脚本
3. **`[OPTIONS]`** - 可选参数，支持长格式 `--option` 和短格式 `-o`

> 💡 **为什么使用 Poetry？**
> Poetry 是现代 Python 项目的依赖管理工具，它自动处理虚拟环境和依赖安装，避免版本冲突。

---

## 3.2 必需参数

### `--ticker`：股票代码

这是**唯一必需的参数**，用于指定要分析的股票。

### 基本用法

**分析单只股票**：

```bash
poetry run python src/main.py --ticker AAPL
```

**分析多只股票**：

```bash
poetry run python src/main.py --ticker AAPL,MSFT,NVDA
```

### 参数规范

| 规则 | 说明 | 示例 |
|------|------|------|
| 分隔符 | 使用逗号（不含空格） | `AAPL,MSFT` ✅ |
| 代码格式 | 大写字母，1-5 位 | `AAPL`, `GOOGL` ✅ |
| 错误格式 | 逗号后有空格 | `AAPL, MSFT` ❌ |

### 常见股票代码

| 代码 | 公司名称 | 行业 |
|------|---------|------|
| AAPL | 苹果公司 | 消费电子 |
| MSFT | 微软公司 | 软件 |
| GOOGL | 谷歌（Alphabet） | 互联网 |
| AMZN | 亚马逊 | 电子商务 |
| TSLA | 特斯拉 | 电动汽车 |
| NVDA | 英伟达 | 半导体 |

> ⚠️ **注意事项**：本系统为 AAPL、GOOGL、MSFT、NVDA 和 TSLA 提供免费的财务数据。分析其他股票需要配置 `FINANCIAL_DATASETS_API_KEY`。

---

## 3.3 核心参数（常用）

### 时间范围参数

`--start-date` 和 `--end-date` 用于指定分析的时间范围。

**参数格式**：`YYYY-MM-DD`

**用法示例**：

```bash
# 指定开始日期
poetry run python src/main.py --ticker AAPL --start-date 2024-01-01

# 指定结束日期
poetry run python src/main.py --ticker AAPL --end-date 2024-06-30

# 同时指定起止日期
poetry run python src/main.py \
    --ticker AAPL \
    --start-date 2024-01-01 \
    --end-date 2024-06-30
```

**默认行为**：如果不指定时间范围，系统默认使用最近 30 天的数据。

### 模型选择参数

`--model` 用于指定使用的 **LLM（大语言模型）** 模型。系统支持多种主流模型提供商，包括 OpenAI、Anthropic、Google、DeepSeek、MiniMax、智谱等。

#### 基本用法

```bash
# 使用默认模型
poetry run python src/main.py --ticker AAPL

# 指定具体模型
poetry run python src/main.py --ticker AAPL --model gpt-4.1

# 分析 A 股（科创板）使用 MiniMax 原生模型
uv run python src/main.py --ticker 688363 --model MiniMax-M2.5
```

#### 可用模型列表

**OpenAI 模型**：

| 显示名称 | 命令行参数 | 特点 |
|---------|-----------|------|
| GPT-5.2 | `gpt-5.2` | 最新旗舰模型，综合能力最强 |
| GPT-4.1 | `gpt-4.1` | 平衡性好，综合能力强 |

**Anthropic 模型**：

| 显示名称 | 命令行参数 | 特点 |
|---------|-----------|------|
| Claude Opus 4.5 | `claude-opus-4-5-20251101` | 最强推理能力，适合深度分析 |
| Claude Sonnet 4.5 | `claude-sonnet-4-5-20250929` | 平衡性能与成本 |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | 快速响应，成本低 |

**Google 模型**：

| 显示名称 | 命令行参数 | 特点 |
|---------|-----------|------|
| Gemini 3 Pro | `gemini-3-pro-preview` | 多模态能力强，上下文窗口大 |

**DeepSeek 模型**：

| 显示名称 | 命令行参数 | 特点 |
|---------|-----------|------|
| DeepSeek R1 | `deepseek-reasoner` | 推理能力强，适合复杂分析 |
| DeepSeek V3 | `deepseek-chat` | 性价比高，响应速度快 |

**MiniMax 模型（原生）**：

| 显示名称 | 命令行参数 | 特点 |
|---------|-----------|------|
| MiniMax-M2.5 (原生) | `MiniMax-M2.5` | 中文理解优秀，适合 A 股分析 |
| MiniMax-M2 (原生) | `MiniMax-M2` | 成本更低，响应快速 |

**智谱 AI 模型（原生）**：

| 显示名称 | 命令行参数 | 特点 |
|---------|-----------|------|
| GLM-4.7 (智谱原生) | `glm-4.7` | 中文场景优化 |
| GLM-4.7 Air (智谱原生) | `glm-4.7-air` | 轻量版，响应更快 |
| GLM-4.7 Flash (智谱原生) | `glm-4.7-flash` | 极速响应，成本最低 |

**OpenRouter 模型（统一接口）**：

| 显示名称 | 命令行参数 | 特点 |
|---------|-----------|------|
| Grok 4 | `grok-4-0709` | xAI 最新模型 |
| GLM-4.5 | `z-ai/glm-4.5` | 通过 OpenRouter 使用 |
| GLM-4.5 Air | `z-ai/glm-4.5-air` | 轻量版 |
| Qwen 3 (235B) Thinking | `qwen/qwen3-235b-a22b-thinking-2507` | 阿里通义千问 |
| MiniMax M2.5 | `minimax/minimax-m2.5` | 通过 OpenRouter 使用 |
| MiniMax M2 | `minimax/minimax-m2` | 通过 OpenRouter 使用 |

**其他模型**：

| 显示名称 | 命令行参数 | 特点 |
|---------|-----------|------|
| GigaChat-2-Max | `GigaChat-2-Max` | 俄罗斯 Sber 模型 |

#### 使用示例

**美股分析示例**：

```bash
# 使用 GPT-4.1 分析苹果
poetry run python src/main.py --ticker AAPL --model gpt-4.1

# 使用 Claude Opus 进行深度分析
poetry run python src/main.py --ticker TSLA --model claude-opus-4-5-20251101

# 使用 Gemini 分析多只股票
poetry run python src/main.py --ticker AAPL,MSFT,GOOGL --model gemini-3-pro-preview
```

**A 股分析示例**：

```bash
# 使用 MiniMax 原生模型分析科创板股票
uv run python src/main.py --ticker 688363 --model MiniMax-M2.5

# 使用智谱 GLM 分析 A 股
uv run python src/main.py --ticker 000001 --model glm-4.7

# 使用 DeepSeek 分析创业板
uv run python src/main.py --ticker 300750 --model deepseek-reasoner
```

**批量分析示例**：

```bash
# 使用高性价比模型批量分析
poetry run python src/main.py --ticker AAPL,MSFT,NVDA --model deepseek-chat

# 使用快速模型进行初步筛选
poetry run python src/main.py --ticker 688363,688981,688012 --model glm-4.7-flash
```

#### 模型选择建议

| 场景 | 推荐模型 | 原因 |
|------|---------|------|
| **美股深度分析** | `claude-opus-4-5-20251101` | 推理能力强，适合复杂财务分析 |
| **美股常规分析** | `gpt-4.1` | 平衡性能与成本 |
| **A 股分析** | `MiniMax-M2.5` | 中文理解优秀，原生 API 稳定 |
| **快速批量筛选** | `glm-4.7-flash` | 响应极快，成本低 |
| **成本敏感** | `deepseek-chat` | 性价比高，质量可靠 |
| **最新技术** | `gpt-5.2` | 最新模型，能力最强 |

> 💡 **A 股特别提示**：
> - 分析 A 股建议使用 **MiniMax** 或 **智谱 GLM** 等中文优化模型
> - 科创板（688 开头）、创业板（300 开头）股票代码可以直接使用
> - 主板股票代码需要添加市场前缀，如 `sh000001`（上证指数）或 `sz000001`（平安银行）

> ⚠️ **环境变量配置**：
> 使用不同模型需要配置对应的 API Key：
> - OpenAI: `OPENAI_API_KEY`
> - Anthropic: `ANTHROPIC_API_KEY`
> - MiniMax: `MINIMAX_API_KEY`
> - 智谱: `ZHIPU_API_KEY`
> - DeepSeek: `DEEPSEEK_API_KEY`
> - Google: `GOOGLE_API_KEY`
> - OpenRouter: `OPENROUTER_API_KEY`

### 本地模型参数

`--ollama` 标志启用本地 **Ollama** 模型（开源的本地 LLM 运行工具）。

**用法示例**：

```bash
# 使用本地 Ollama 模型
poetry run python src/main.py --ticker AAPL --ollama
```

**前置条件**：

1. 安装 Ollama：[官方安装指南](https://ollama.com)
2. 下载模型：`ollama pull llama3`

**优缺点分析**：

| 优点 | 缺点 |
|------|------|
| ✅ 完全免费 | ❌ 需要硬件资源 |
| ✅ 数据隐私 | ❌ 模型能力通常较小 |
| ✅ 无网络延迟 | ❌ 需要手动管理模型 |

---

## 3.4 智能体系统

### `--analysts`：智能体选择

系统内置多个投资大师风格的 AI 智能体，可以自由组合。

### 为什么有多个智能体？

**单一视角的局限性**：

```
只使用技术分析：
├── ✅ 能捕捉短期趋势
├── ❌ 忽略基本面价值
└── ❌ 可能错过长期机会

只使用价值投资：
├── ✅ 关注内在价值
├── ❌ 可能错过短期机会
└── ❌ 对成长股判断不足

综合多个智能体：
├── ✅ 多维度分析
├── ✅ 减少盲区
└── ✅ 更全面的决策支持
```

### 智能体分类

根据投资风格，智能体可分为以下几类：

#### 价值投资风格

| 标识符 | 智能体名称 | 核心理念 |
|--------|-----------|---------|
| `warren_buffett` | 沃伦·巴菲特 | 以合理价格买入优秀公司 |
| `charlie_munger` | 查理·芒格 | 只买优秀公司，价格公道 |
| `ben_graham` | 本杰明·格雷厄姆 | 深度价值，安全边际 |
| `michael_burry` | 迈克尔·伯里 | 逆向投资，寻找被低估 |
| `mohnish_pabrai` | 莫尼什·帕波莱 | 低风险高回报（Dhandho） |

#### 成长投资风格

| 标识符 | 智能体名称 | 核心理念 |
|--------|-----------|---------|
| `peter_lynch` | 彼得·林奇 | 寻找生活中的"十倍股" |
| `cathie_wood` | 凯茜·伍德 | 激进成长，关注创新 |
| `phil_fisher` | 菲利普·费雪 | 深度成长，长期持有 |

#### 激进与宏观风格

| 标识符 | 智能体名称 | 核心理念 |
|--------|-----------|---------|
| `bill_ackman` | 比尔·阿克曼 | 积极投资者，推动变革 |
| `stanley_druckenmiller` | 斯坦利·德鲁肯米勒 | 宏观策略，非对称机会 |

#### 分析工具

| 标识符 | 智能体名称 | 分析方法 |
|--------|-----------|---------|
| `technical_analyst` | 技术分析师 | 技术指标分析 |
| `fundamentals_analyst` | 基本面分析师 | 财务数据分析 |
| `sentiment_analyst` | 情绪分析师 | 市场情绪分析 |
| `valuation_analyst` | 估值分析师 | 内在价值计算 |

### 智能体组合示例

**价值投资组合**：

```bash
poetry run python src/main.py \
    --ticker AAPL \
    --analysts warren_buffett,charlie_munger,ben_graham
```

**成长投资组合**：

```bash
poetry run python src/main.py \
    --ticker TSLA \
    --analysts peter_lynch,cathie_wood,phil_fisher
```

**全面分析组合**：

```bash
poetry run python src/main.py \
    --ticker AAPL \
    --analysts warren_buffett,peter_lynch,technical_analyst,fundamentals_analyst
```

> 💡 **组合建议**：
> - 初学者：使用默认所有智能体（全面视角）
> - 价值投资者：`warren_buffett + ben_graham + fundamentals_analyst`
> - 成长投资者：`peter_lynch + cathie_wood + technical_analyst`
> - 技术交易者：`technical_analyst + sentiment_analyst`

---

## 3.5 高级参数（可选）

### `--show-reasoning`：显示推理过程

此标志会显示每个智能体的详细推理步骤和判断依据。

**用法示例**：

```bash
poetry run python src/main.py --ticker AAPL --show-reasoning
```

**输出对比**：

| 模式 | 输出内容 | 适用场景 |
|------|---------|---------|
| 默认（不启用） | 最终结论和关键建议 | 快速决策 |
| 启用 | 完整推理过程 + 结论 | 深度学习、调试 |

> 📚 **学习建议**：初学者建议开启此选项，观察不同智能体的思考过程，理解投资逻辑。

### 风险管理参数

#### `--risk-tolerance`：风险承受等级

**范围**：1-10（数字越大，风险承受越高）

**等级划分**：

| 等级范围 | 风险偏好 | 特征 |
|---------|---------|------|
| 1-3 | 保守型 | 严格止损，小仓位 |
| 4-7 | 中性型 | 平衡风险收益 |
| 8-10 | 激进型 | 追求高收益，承受大波动 |

**用法示例**：

```bash
# 保守型（适合退休账户）
poetry run python src/main.py --ticker AAPL --risk-tolerance 3

# 激进型（适合高风险资金）
poetry run python src/main.py --ticker AAPL --risk-tolerance 8
```

**影响机制**：

```
风险承受度低 → 仓位更小 → 止损更严格 → 潜在收益降低
风险承受度高 → 仓位更大 → 止损更宽松 → 潜在收益提高
```

#### `--max-position-size`：最大仓位比例

**格式**：小数形式（0.10 = 10%）

**默认值**：0.05（5%）

**用法示例**：

```bash
# 设置最大仓位为 10%
poetry run python src/main.py --ticker AAPL --max-position-size 0.10
```

**风险管理逻辑**：

```
为什么限制单只股票仓位？

过度集中风险：
├── 单只股票暴跌 → 整体组合受重创
├── 公司特有风险无法分散
└── 心理压力增大

合理分散的好处：
├── 降低单一股票风险
├── 提高组合稳定性
├── 减少情绪干扰
└── 更容易坚持策略
```

### `--output`：输出格式

**可选值**：`text`（默认）、`json`

**用法示例**：

```bash
# 文本格式（默认，适合直接阅读）
poetry run python src/main.py --ticker AAPL --output text

# JSON 格式（适合程序处理）
poetry run python src/main.py --ticker AAPL --output json

# 保存到文件
poetry run python src/main.py --ticker AAPL --output json > analysis_result.json
```

**使用场景对比**：

| 格式 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| `text` | 易读、直观 | 难以程序处理 | 手工查看、学习 |
| `json` | 易于解析、结构化 | 不易读 | 自动化、数据分析 |

---

## 3.6 配置文件管理

### 为什么需要配置文件？

**命令行的局限性**：

```bash
# 每次都要重复输入这些参数...
poetry run python src/main.py \
    --ticker AAPL,MSFT,GOOGL \
    --model openai \
    --analysts warren_buffett,peter_lynch,technical_analyst \
    --risk-tolerance 5 \
    --max-position-size 0.10 \
    --show-reasoning \
    --output json
```

**配置文件的优势**：

| 优势 | 说明 |
|------|------|
| 📝 代码复用 | 一次配置，多次使用 |
| 📦 可版本控制 | 配置变更可追踪 |
| 🤝 易分享 | 团队成员使用统一配置 |
| 🎯 场景切换 | 不同风格使用不同配置 |

### 创建配置文件

配置文件使用 **YAML（YAML Ain't Markup Language）** 格式。

**示例配置文件 `config.yaml`**：

```yaml
# 分析配置
analysis:
  # 默认股票列表
  default_tickers:
    - AAPL
    - MSFT
    - GOOGL

  # 默认模型
  default_model: openai

  # 是否显示推理过程
  show_reasoning: true

  # 风险承受等级（1-10）
  risk_tolerance: 5

  # 最大仓位比例
  max_position_size: 0.05

  # 默认智能体列表（留空表示使用全部）
  default_analysts:
    - warren_buffett
    - peter_lynch
    - technical_analyst
    - fundamentals_analyst

# 回测配置
backtest:
  # 初始资金
  initial_capital: 100000

  # 再平衡频率
  rebalance_frequency: monthly

  # 手续费率
  commission_rate: 0.001

# 显示配置
display:
  # 输出格式：text 或 json
  output_format: text

  # 时间格式
  date_format: "%Y-%m-%d"
```

### 使用配置文件

```bash
# 使用项目根目录的 config.yaml
poetry run python src/main.py --ticker AAPL --config config.yaml

# 使用自定义路径的配置文件
poetry run python src/main.py --ticker AAPL --config /path/to/my_config.yaml
```

### 配置优先级机制

**优先级从高到低**：

```
命令行参数 > 配置文件 > 代码默认值
```

**示例**：

```bash
# 配置文件中：risk_tolerance = 5
# 命令行中：--risk-tolerance 8
# 结果：实际使用 8（命令行优先）
```

**优先级应用场景**：

```
场景 1：日常使用
└── 使用配置文件（如保守型配置）

场景 2：特殊分析
└── 配置文件 + 命令行参数覆盖（临时调整为激进型）

场景 3：快速测试
└── 仅命令行参数（不使用配置文件）
```

### 多场景配置管理

**场景一：保守型投资配置**

创建文件 `config_conservative.yaml`：

```yaml
analysis:
  risk_tolerance: 3
  max_position_size: 0.05
  default_analysts:
    - warren_buffett
    - ben_graham
    - fundamentals_analyst
```

**场景二：激进成长配置**

创建文件 `config_growth.yaml`：

```yaml
analysis:
  risk_tolerance: 8
  max_position_size: 0.15
  default_analysts:
    - cathie_wood
    - peter_lynch
    - technical_analyst
```

**场景三：平衡配置**

创建文件 `config_balanced.yaml`：

```yaml
analysis:
  risk_tolerance: 5
  max_position_size: 0.08
  default_analysts:
    - warren_buffett
    - peter_lynch
    - technical_analyst
    - fundamentals_analyst
    - sentiment_analyst
```

**使用方法**：

```bash
# 保守型分析
poetry run python src/main.py --ticker AAPL --config config_conservative.yaml

# 成长型分析
poetry run python src/main.py --ticker AAPL --config config_growth.yaml

# 平衡型分析（日常默认）
poetry run python src/main.py --ticker AAPL --config config_balanced.yaml
```

---

## 3.7 实用命令模板

### 快速分析模板

**最简分析**：

```bash
poetry run python src/main.py --ticker AAPL
```

**使用场景**：快速查看默认分析结果

---

### 完整分析模板

```bash
poetry run python src/main.py \
    --ticker AAPL,MSFT,NVDA \
    --start-date 2024-01-01 \
    --end-date 2024-06-30 \
    --model anthropic \
    --analysts warren_buffett,peter_lynch,technical_analyst \
    --show-reasoning \
    --risk-tolerance 5 \
    --max-position-size 0.10 \
    --output json > full_analysis.json
```

**使用场景**：
- 深度分析多只股票
- 需要详细推理过程
- 需要保存结果供后续分析

---

### 批量快速分析模板

```bash
poetry run python src/main.py \
    --ticker AAPL,MSFT,GOOGL,AMZN,TSLA \
    --model groq \
    --output text > batch_analysis.txt
```

**使用场景**：
- 批量监控多只股票
- 使用高速模型节省时间
- 快速获取市场概览

---

### 学习观察模板

```bash
poetry run python src/main.py \
    --ticker AAPL \
    --analysts warren_buffett,peter_lynch,technical_analyst \
    --show-reasoning \
    --output text
```

**使用场景**：
- 学习不同投资大师的思考方式
- 理解不同投资风格的差异
- 建立投资思维框架

---

### 本地私有分析模板

```bash
poetry run python src/main.py \
    --ticker AAPL \
    --ollama \
    --analysts warren_buffett,technical_analyst \
    --output text
```

**使用场景**：
- 数据隐私敏感
- 无网络环境
- 完全免费使用

---

## 3.8 常见问题解答

### Q1：如何选择合适的 LLM 提供商？

**决策树**：

```
你的需求是什么？
├── 最快速度
│   └── → 使用 groq
├── 最低成本
│   └── → 使用 deepseek 或 ollama
├── 最高分析质量
│   └── → 使用 anthropic
├── 平衡选择
│   └── → 使用 openai（默认）
└── 完全免费 + 隐私保护
    └── → 使用 ollama（需本地配置）
```

### Q2：如何加快分析速度？

**优化方法**（按效果从大到小排序）：

1. **减少智能体数量** - 最大的性能提升
   ```bash
   # 从 12 个智能体减少到 3 个
   --analysts warren_buffett,peter_lynch,technical_analyst
   ```

2. **使用快速模型**
   ```bash
   --model groq  # 比 openai 快 3-5 倍
   ```

3. **缩短时间范围**
   ```bash
   --start-date 2024-05-01 --end-date 2024-06-30  # 只分析 2 个月
   ```

4. **减少分析股票数量**
   ```bash
   --ticker AAPL  # 而不是 --ticker AAPL,MSFT,GOOGL,NVDA,TSLA
   ```

5. **禁用推理过程显示**
   ```bash
   # 不要使用 --show-reasoning
   ```

### Q3：如何理解不同智能体的分析差异？

**观察方法**：

1. **开启推理显示**
   ```bash
   --show-reasoning
   ```

2. **对比同一股票的智能体分析**
   ```bash
   # 价值投资视角
   --analysts warren_buffett,ben_graham

   # 成长投资视角
   --analysts peter_lynch,cathie_wood

   # 技术分析视角
   --analysts technical_analyst
   ```

3. **分析结论对比**
   - 建议买入/卖出/持有的差异
   - 目标价格的差异
   - 风险评估的差异
   - 推理逻辑的差异

### Q4：配置文件和命令行参数如何选择？

**选择指南**：

| 场景 | 推荐方式 | 原因 |
|------|---------|------|
| 一次性分析 | 仅命令行参数 | 简单直接 |
| 重复相同配置 | 配置文件 | 避免重复输入 |
| 多种投资风格 | 多个配置文件 | 快速切换场景 |
| 临时调整配置 | 配置文件 + 命令行覆盖 | 灵活高效 |

### Q5：如何保存和复用分析结果？

**方法一：保存为 JSON 文件**

```bash
# 保存到文件
poetry run python src/main.py --ticker AAPL --output json > aapl_2024.json
```

**方法二：使用配置文件记录**

在配置文件中添加注释说明：

```yaml
analysis:
  # 2024年6月保守型分析配置
  # 结果：AAPL 买入，MSFT 持有，GOOGL 卖出
  risk_tolerance: 3
  max_position_size: 0.05
```

**方法三：Git 版本控制**

```bash
# 提交配置文件
git add config.yaml
git commit -m "更新 2024 年 6 月投资策略"
```

---

## 3.9 练习与实践

### 练习 3.1：参数组合实验（难度：⭐）

**任务目标**：熟悉核心参数的使用

**步骤**：

1. 选择一只你感兴趣的股票（如 AAPL）
2. 组合使用以下参数：
   - `--start-date` 和 `--end-date`
   - `--model`（尝试不同的模型）
   - `--analysts`（选择 2-3 个智能体）
   - `--risk-tolerance`
   - `--output`

3. 运行分析并观察不同参数组合的效果

**参考命令**：

```bash
poetry run python src/main.py \
    --ticker AAPL \
    --start-date 2024-01-01 \
    --end-date 2024-06-30 \
    --model groq \
    --analysts warren_buffett,technical_analyst \
    --risk-tolerance 5 \
    --output text
```

**验证标准**：

- [ ] 命令成功执行，无错误
- [ ] 能够解释每个参数的作用
- [ ] 观察到不同模型或智能体对分析结果的影响

---

### 练习 3.2：智能体风格对比（难度：⭐⭐）

**任务目标**：理解不同投资风格的差异

**步骤**：

1. 为同一只股票（如 TSLA）运行三次分析，分别使用不同的智能体组合：

   **组合 A：价值投资风格**
   ```bash
   poetry run python src/main.py \
       --ticker TSLA \
       --analysts warren_buffett,ben_graham,charlie_munger \
       --show-reasoning \
       --output text > value_style.txt
   ```

   **组合 B：成长投资风格**
   ```bash
   poetry run python src/main.py \
       --ticker TSLA \
       --analysts peter_lynch,cathie_wood,phil_fisher \
       --show-reasoning \
       --output text > growth_style.txt
   ```

   **组合 C：技术分析风格**
   ```bash
   poetry run python src/main.py \
       --ticker TSLA \
       --analysts technical_analyst,sentiment_analyst \
       --show-reasoning \
       --output text > technical_style.txt
   ```

2. 对比三个文件的结果，记录：
   - 推荐动作（买入/持有/卖出）
   - 风险评估
   - 推理逻辑的侧重点

3. 思考问题：
   - 为什么不同风格会对同一股票得出不同结论？
   - 哪种风格更符合你的投资理念？

**验证标准**：

- [ ] 成功生成三个对比文件
- [ ] 能够清晰描述三种风格的差异
- [ ] 能够解释造成差异的根本原因

---

### 练习 3.3：配置文件创建与管理（难度：⭐⭐）

**任务目标**：掌握配置文件的使用，简化日常操作

**步骤**：

1. 创建三个配置文件，分别代表不同的投资风格：

   **文件 1：`config_conservative.yaml`（保守型）**
   ```yaml
   analysis:
     risk_tolerance: 3
     max_position_size: 0.05
     default_analysts:
       - warren_buffett
       - ben_graham
       - fundamentals_analyst
     default_model: openai
     show_reasoning: true
   ```

   **文件 2：`config_aggressive.yaml`（激进型）**
   ```yaml
   analysis:
     risk_tolerance: 8
     max_position_size: 0.15
     default_analysts:
       - cathie_wood
       - peter_lynch
       - technical_analyst
     default_model: groq
     show_reasoning: true
   ```

   **文件 3：`config_balanced.yaml`（平衡型）**
   ```yaml
   analysis:
     risk_tolerance: 5
     max_position_size: 0.08
     default_analysts:
       - warren_buffett
       - peter_lynch
       - technical_analyst
       - fundamentals_analyst
     default_model: openai
     show_reasoning: true
   ```

2. 使用不同配置文件分析同一只股票（如 AAPL）：
   ```bash
   # 保守型分析
   poetry run python src/main.py --ticker AAPL --config config_conservative.yaml

   # 激进型分析
   poetry run python src/main.py --ticker AAPL --config config_aggressive.yaml

   # 平衡型分析
   poetry run python src/main.py --ticker AAPL --config config_balanced.yaml
   ```

3. 对比三种配置下的分析结果差异

**验证标准**：

- [ ] 成功创建三个配置文件
- [ ] 配置文件语法正确（YAML 格式）
- [ ] 能够根据不同场景选择合适的配置文件
- [ ] 观察到风险参数对分析结果的影响

---

### 练习 3.4：配置优先级验证（难度：⭐⭐）

**任务目标**：理解命令行参数、配置文件、默认值之间的优先级关系

**步骤**：

1. 创建配置文件 `config_test.yaml`：
   ```yaml
   analysis:
     risk_tolerance: 3
     default_model: anthropic
     default_analysts:
       - warren_buffett
   ```

2. 测试不同组合，观察实际使用的值：

   **测试 1：仅使用配置文件**
   ```bash
   poetry run python src/main.py --ticker AAPL --config config_test.yaml
   ```
   预期结果：risk_tolerance = 3，model = anthropic

   **测试 2：命令行覆盖**
   ```bash
   poetry run python src/main.py \
       --ticker AAPL \
       --config config_test.yaml \
       --risk-tolerance 8
   ```
   预期结果：risk_tolerance = 8（命令行优先），model = anthropic（来自配置文件）

   **测试 3：仅命令行参数**
   ```bash
   poetry run python src/main.py --ticker AAPL --risk-tolerance 5
   ```
   预期结果：risk_tolerance = 5，model = openai（默认值）

3. 总结优先级规则

**验证标准**：

- [ ] 正确理解优先级：命令行 > 配置文件 > 默认值
- [ ] 能够根据需要灵活组合使用
- [ ] 理解这种设计的合理性

---

### 练习 3.5：性能优化实验（难度：⭐⭐⭐）

**任务目标**：学会优化命令行分析的性能

**步骤**：

1. **基准测试**：记录默认配置的执行时间
   ```bash
   time poetry run python src/main.py --ticker AAPL
   ```

2. **优化实验**：尝试不同的优化策略，记录每次的执行时间

   **优化 1：减少智能体数量**
   ```bash
   time poetry run python src/main.py \
       --ticker AAPL \
       --analysts warren_buffett,technical_analyst
   ```

   **优化 2：使用快速模型**
   ```bash
   time poetry run python src/main.py \
       --ticker AAPL \
       --model groq
   ```

   **优化 3：缩短时间范围**
   ```bash
   time poetry run python src/main.py \
       --ticker AAPL \
       --start-date 2024-05-01 \
       --end-date 2024-06-01
   ```

   **优化 4：综合优化**
   ```bash
   time poetry run python src/main.py \
       --ticker AAPL \
       --analysts warren_buffett,technical_analyst \
       --model groq \
       --start-date 2024-05-01 \
       --end-date 2024-06-01
   ```

3. 对比结果，绘制性能对比表

**验证标准**：

- [ ] 记录了每次优化的执行时间
- [ ] 找到了最有效的优化策略
- [ ] 理解了影响性能的主要因素
- [ ] 能够根据需求在质量和速度之间做权衡

---

## 3.10 进阶思考与探索

### 思考题 1：命令行工具的设计哲学

```
思考问题：
1. 为什么命令行工具在专业用户中依然流行？
2. 命令行和图形界面在信息密度上有何差异？
3. 如何设计"既适合新手又适合专家"的命令行工具？
```

**思考方向**：
- 信息传达效率
- 学习曲线 vs 使用效率
- 自动化和脚本能力
- 发现性（Discoverability）设计

---

### 思考题 2：参数设计权衡

```
思考问题：
1. 为什么有些参数使用长格式（--option），有些使用短格式（-o）？
2. 参数的默认值应该如何设计？
3. 什么时候应该添加新参数，什么时候应该使用配置文件？
```

**思考方向**：
- 常用性 vs 可读性
- 默认值的合理性
- 复杂度管理
- 向后兼容性

---

### 思考题 3：投资策略的标准化

```
思考问题：
1. 如何为团队制定 CLI 使用规范？
2. 不同风险偏好的用户应该使用不同的配置吗？
3. 如何设计配置文件的版本管理和协作机制？
```

**思考方向**：
- 团队协作标准
- 配置的可移植性
- 版本控制最佳实践
- 文档和培训

---

### 探索任务：创建个人配置模板

**任务**：基于你的投资理念和风险偏好，创建一个个人化的配置模板，包含：

1. 合适的风险承受度设置
2. 符合你理念的智能体组合
3. 说明文档（注释），解释每个选择的理由
4. 使用场景说明（适合什么时候使用）

**交付物**：
- 配置文件（如 `my_strategy.yaml`）
- 说明文档（如 `my_strategy.md`）

---

## 3.11 总结与下一步

### 本章要点回顾

| 要点 | 关键内容 |
|------|---------|
| 命令行接口 | 高效、灵活、易于自动化 |
| 核心参数 | `--ticker`、`--model`、`--analysts` |
| 高级参数 | 风险管理、输出格式、推理显示 |
| 配置文件 | 简化操作、场景切换、团队协作 |
| 智能体系统 | 多维度分析、风格对比 |

### 学习检查清单

完成本章学习后，请自检：

**基础能力**：
- [ ] 能够独立运行基本的股票分析
- [ ] 理解常用参数的作用和用法
- [ ] 能够选择合适的 LLM 提供商
- [ ] 知道如何使用帮助信息

**进阶能力**：
- [ ] 能够创建和使用配置文件
- [ ] 理解不同投资风格的智能体差异
- [ ] 能够根据需求组合使用参数
- [ ] 知道如何优化分析性能

**专家能力**：
- [ ] 能够设计符合个人理念的配置模板
- [ ] 理解命令行工具的设计哲学
- [ ] 能够为团队制定使用规范
- [ ] 能够诊断和解决常见问题

### 常见命令速查表

```bash
# 快速分析
poetry run python src/main.py --ticker AAPL

# 完整分析
poetry run python src/main.py \
    --ticker AAPL \
    --start-date 2024-01-01 \
    --end-date 2024-06-30 \
    --model openai \
    --analysts warren_buffett,peter_lynch \
    --show-reasoning

# 使用配置文件
poetry run python src/main.py --ticker AAPL --config my_config.yaml

# JSON 输出
poetry run python src/main.py --ticker AAPL --output json > result.json

# 本地模型
poetry run python src/main.py --ticker AAPL --ollama

# 获取帮助
poetry run python src/main.py --help
```

---

## 下一章预告

在下一章中，我们将学习 **Web 界面的使用方法**。你将了解：

- Web 界面的优势和适用场景
- 可视化分析结果的展示
- 交互式配置和参数调整
- 历史记录和结果管理

命令行和 Web 界面各有优势，掌握两者可以让你在不同场景下灵活选择最适合的工具。

---

## 附录：参考资源

### 相关文档

- [2.1 快速入门](02-quickstart.md)
- [4.1 Web 界面概述](../level2-user-guide/01-web-interface.md)
- [配置文件完整参考](../references/config-reference.md)

### 外部资源

- [YAML 官方文档](https://yaml.org/)
- [Poetry 文档](https://python-poetry.org/docs/)
- [Ollama 官方文档](https://ollama.com/docs)

---

## 版本信息

| 项目 | 信息 |
|------|------|
| 文档版本 | 2.0.0 |
| 最后更新 | 2026年2月13日 |
| 适用版本 | 1.0.0+ |
| 文档级别 | Level 1 (入门) ⭐ |

### 更新日志

**v2.0.0 (2026.02.13)** - 重大升级
- ✨ 完善学习目标设计，添加分层目标体系
- ✨ 增加命令行接口设计思想的原理解析
- ✨ 优化参数组织，分为"核心参数"和"高级参数"
- ✨ 新增智能体分类和组合推荐
- ✨ 完善练习设计，增加参考答案和难度标记
- ✨ 优化认知负荷，添加决策树和对比表格
- ✨ 完善术语管理，确保首次出现的英文术语都有中文解释

**v1.0.2 (2026.02)** - 小幅改进
- 🐛 修正部分命令参数
- 📝 增加配置文件示例

**v1.0.1 (2025.12)** - 内容补充
- 📝 增加智能体标识符表格

**v1.0.0 (2025.10)** - 初始版本
- 🎉 第一版文档发布

---

## 反馈与贡献

如果您在使用过程中发现问题或有改进建议，欢迎：

- 📝 提交 [GitHub Issues](https://github.com/virattt/ai-hedge-fund/issues)
- 💬 参与 [讨论区](https://github.com/virattt/ai-hedge-fund/discussions)
- 🤝 贡献 [Pull Request](https://github.com/virattt/ai-hedge-fund/pulls)

感谢您的反馈和贡献！
