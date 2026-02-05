# 第二章：第一次运行

## 学习目标

完成本章节学习后，你将能够成功运行第一个股票分析示例，理解命令行输出的各个部分含义，解读各智能体的分析结果，以及掌握基本的故障排查方法。这个「Hello World」示例是使用系统的起点，预计学习时间为 15-30 分钟。

## 2.1 运行第一个分析

### 单只股票分析

在完成环境配置后，我们来运行第一个分析示例。执行以下命令分析苹果公司（AAPL）的股票：

```bash
poetry run python src/main.py --ticker AAPL
```

命令执行后，系统会经历以下阶段。首先是「初始化阶段」，系统会加载必要的模块和配置。然后是「数据获取阶段」，系统从金融数据 API 获取 AAPL 的相关数据。接着是「分析阶段」，18 个智能体会依次分析数据。最后是「输出阶段」，系统展示分析结果。

整个过程可能需要 1-3 分钟，取决于网络速度和 LLM 响应时间。首次运行时可能稍慢，因为需要下载模型缓存。

### 理解输出结构

命令执行完成后，你会看到详细的输出结果。让我们逐部分理解。

**标题区**显示基本信息：

```
AI Hedge Fund Analysis
======================

Analyzing ticker: AAPL
Using model: gpt-4o
```

这里显示了分析的股票代码（AAPL）和使用的模型（gpt-4o）。

**数据加载状态**：

```
Initializing market data...
 ✓ Data loaded successfully
```

如果看到「✓ Data loaded successfully」，表示数据获取成功。如果看到错误信息，请检查网络连接和 API 密钥配置。

**智能体分析区**是输出的核心部分，每个智能体会展示：

```
Warren Buffett (Value Investor)...
Signal: BUY (Confidence: 85%)
Reasoning: Excellent company with strong moat, consistent free cash 
flow generation, and dominant market position in key segments.
```

每个智能体的输出包含三个要素：信号（Signal）表示推荐操作，置信度（Confidence）表示确定程度（0-100），推理（Reasoning）是支持决策的详细理由。

**风险评估区**：

```
Risk Manager Assessment...
Risk Level: MEDIUM
Recommended Position Size: 3% of portfolio
Stop Loss: 5%
```

风险管理者会评估整体风险水平，并给出推荐的仓位和止损设置。

**最终决策区**：

```
Portfolio Manager Decision...
Final Decision: BUY
Recommended Quantity: 100 shares
Estimated Allocation: 2.5% of portfolio
```

投资组合管理者综合所有输入，生成最终的交易建议。

## 2.2 多股票分析

### 基本用法

系统支持同时分析多只股票：

```bash
poetry run python src/main.py --ticker AAPL,MSFT,NVDA
```

多股票分析时，系统会依次分析每只股票，最后给出投资组合层面的建议。分析时间约为单只股票的 N 倍（N 为股票数量）。

### 指定时间范围

你可以指定分析的时间范围：

```bash
poetry run python src/main.py --ticker AAPL --start-date 2024-01-01 --end-date 2024-03-01
```

时间范围会影响系统获取的数据，进而影响分析结果。通常建议使用 1-3 个月的数据进行分析。

### 选择特定智能体

默认情况下，系统会运行所有 18 个智能体。你可以选择特定的智能体子集：

```bash
poetry run python src/main.py --ticker AAPL --analysts warren_buffett,ben_graham,technical_analyst
```

可选的智能体标识符包括：`warren_buffett`（沃伦·巴菲特）、`charlie_munger`（查理·芒格）、`ben_graham`（本杰明·格雷厄姆）、`peter_lynch`（彼得·林奇）、`cathie_wood`（凯茜·伍德）等。

## 2.3 使用不同模型

### 模型选择

系统支持多种 LLM 提供商。默认使用 OpenAI 的 GPT-4o 模型：

```bash
poetry run python src/main.py --ticker AAPL --model openai
```

使用 Anthropic Claude 模型：

```bash
poetry run python src/main.py --ticker AAPL --model anthropic
```

使用 Groq 高速推理：

```bash
poetry run python src/main.py --ticker AAPL --model groq
```

### 本地 Ollama 模型

如果已安装 Ollama，可以使用本地模型：

```bash
poetry run python src/main.py --ticker AAPL --ollama
```

使用本地模型的优势是不需要网络连接，数据完全不离开本地环境。劣势是响应速度可能较慢，且需要本地有足够的计算资源。

## 2.4 输出格式

### 文本格式（默认）

默认的文本格式适合命令行交互使用，输出包含丰富的颜色和格式化：

```
Bullish 信号显示为绿色
Bearish 信号显示为红色  
Neutral 信号显示为黄色
```

### JSON 格式

如果需要程序化处理结果，可以使用 JSON 格式：

```bash
poetry run python src/main.py --ticker AAPL --output json
```

JSON 输出示例：

```json
{
    "status": "success",
    "data": {
        "analysis_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "results": [
            {
                "ticker": "AAPL",
                "signals": {
                    "warren_buffett": {
                        "decision": "BUY",
                        "confidence": 85,
                        "reasoning": "..."
                    }
                }
            }
        ]
    }
}
```

## 2.5 常见问题排查

### 问题一：分析卡住不动

如果分析过程卡住，可能的原因包括网络连接问题或 LLM 服务超时。排查步骤如下：

第一步，按 `Ctrl+C` 中止当前命令。第二步，检查网络连接是否正常。第三步，验证 API 密钥是否有效。第四步，尝试使用其他 LLM 提供商。

### 问题二：数据获取失败

如果看到数据获取相关的错误信息，可能的原因包括 API 密钥配置问题或股票代码错误。排查步骤如下：

第一步，确认股票代码是否正确（如 AAPL、MSFT）。第二步，检查 `.env` 文件中的 `FINANCIAL_DATASETS_API_KEY` 是否配置。第三步，确认网络可以访问金融数据 API。第四步，尝试使用免费股票（如 AAPL、MSFT）测试。

### 问题三：输出显示不完整

如果输出被截断或不完整，可能是终端显示问题。排查步骤如下：

第一步，尝试调整终端窗口大小。第二步，使用 ` --show-reasoning` 参数查看详细推理。第三步，将输出重定向到文件：`python src/main.py --ticker AAPL > output.txt`。

## 2.6 练习题

### 练习 2.1：单股票分析

**任务**：分析苹果公司（AAPL）的股票。

**步骤**：进入项目目录，执行分析命令，等待分析完成，阅读和理解输出结果。

**成功标准**：能够看到完整的分析输出，包括至少 10 个智能体的分析结果。

### 练习 2.2：多股票比较分析

**任务**：比较分析三只科技股。

**步骤**：选择三只科技股（如 AAPL、MSFT、GOOGL），执行多股票分析命令，比较各智能体对不同股票的评价差异。

**成功标准**：能够完成多股票分析，并能指出不同股票在各智能体评价中的差异。

### 练习 2.3：智能体风格对比

**任务**：对比价值投资和成长投资风格对同一股票的评价。

**步骤**：使用 `--analysts` 参数选择特定智能体（如 `warren_buffett` 和 `cathie_wood`），分别运行分析，比较两者的决策和推理差异。

**成功标准**：能够清晰描述价值投资风格和成长投资风格的分析视角差异。

## 2.7 输出解读示例

### 示例一：巴菲特智能体输出解读

```
Warren Buffett (Value Investor)...
Signal: BUY (Confidence: 85%)
Reasoning: Excellent company with strong moat, consistent free cash 
flow generation, and dominant market position in key segments.
```

**信号解读**：85% 的置信度表示巴菲特智能体对这个决策有较高信心。「Strong moat」（护城河）是巴菲特投资哲学的核心概念，指公司拥有的持久竞争优势。「Free cash flow」（自由现金流）是评估公司价值的重要指标。「Dominant market position」表示公司在关键市场占据领导地位。

### 示例二：技术分析师输出解读

```
Technical Analyst...
Signal: HOLD (Confidence: 60%)
Reasoning: Price is approaching major resistance level at $185. 
RSI indicates overbought conditions. Waiting for clearer signal.
```

**信号解读**：60% 的置信度表示技术分析师对当前市场状况不太确定。「Resistance level」（阻力位）是技术分析中的重要概念，指价格可能遇到卖压的位置。「RSI」（相对强弱指数）是动量指标，用于判断股票是否处于超买或超卖状态。

### 示例三：风险评估输出解读

```
Risk Manager Assessment...
Risk Level: MEDIUM
Recommended Position Size: 3% of portfolio
Stop Loss: 5%
```

**信号解读**：风险等级为「中等」表示当前市场环境风险适中。推荐 3% 的仓位意味着如果你的总投资组合为 10 万美元，则建议在这只股票上投资不超过 3000 美元。止损设置为 5% 表示如果股价下跌超过 5%，应该卖出以限制损失。

## 2.8 知识检测

完成本章节学习后，请自检以下能力：

**概念理解**方面，你能够说明智能体输出中「信号」「置信度」「推理」各自的含义，能够解释风险评估中「仓位」「止损」的作用，能够区分不同智能体风格的分析视角差异。

**动手能力**方面，你能够独立运行单股票和多股票分析，你能够选择特定的智能体进行分析，你能够使用不同的输出格式。

**问题解决**方面，你能够根据错误信息判断问题类型，你能够通过切换模型解决响应问题，你能够通过查阅文档解决使用中的疑问。

---

## 进阶思考

完成基础练习后，思考以下问题。不同智能体对同一股票可能给出不同甚至相反的建议，你应该如何权衡？置信度高的建议是否一定比置信度低的建议更可靠？如何利用多智能体的分析结果形成自己的投资决策？

下一章节我们将学习命令行工具的更多高级用法。
