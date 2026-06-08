# 第八章：LLM 集成架构

## 📚 学习目标

### 基础目标（必学）
完成本章节学习后，你将能够：
- 理解 LLM 集成在 AI Hedge Fund 系统中的作用和价值
- 掌握不同 LLM 提供商（OpenAI、Anthropic、Groq 等）的特点和适用场景
- 理解 LLM 调用的基本概念：Token（词元）、Temperature（温度）、max_tokens（最大生成长度）
- 能够配置和使用至少一个 LLM 提供商的 API
- 理解提示词（Prompt）的基本设计原则

**预计学习时间**：1-1.5 小时
**完成标志**：能够成功调用 LLM 生成投资分析响应

---

### 进阶目标（推荐）
在掌握基础目标的基础上，你将能够：
- 理解 LLM 集成的分层架构设计原理
- 掌握提示词工程（Prompt Engineering）的高级技巧：Few-shot Learning（少样本学习）、Chain-of-Thought（思维链）
- 实现并发调用、响应缓存等性能优化策略
- 理解不同 LLM 模型的成本结构，并进行成本优化
- 实现故障处理机制：重试、降级、熔断

**预计学习时间**：0.5-1 小时
**完成标志**：能够设计并实现完整的 LLM 调用优化方案

---

### 专家目标（挑战）
在达到进阶目标的基础上，你将能够：
- 设计自定义的 LLM 提供商适配器
- 优化 LLM 调用策略，实现智能模型选择和动态路由
- 设计并实现企业级的 LLM 调用监控系统
- 评估不同 LLM 在投资分析任务上的性能差异
- 构建多模型集成的决策系统，利用模型ensemble（集成）提升准确率

**预计学习时间**：2-3 小时（含实践）
**完成标志**：能够设计生产级别的 LLM 集成架构

---

## 8.1 LLM 集成概述

### 为什么需要 LLM

AI Hedge Fund 系统的核心创新在于使用大型语言模型（LLM）来模拟人类投资分析师的思考过程。传统的量化投资策略通常使用预定义的规则和数学模型，而本系统利用 LLM 的推理能力，能够处理非结构化的信息、进行复杂的逻辑推理、生成详细的分析解释。

**核心优势**：
- **理解能力**：LLM 能够理解自然语言描述的投资理论、财报分析、行业研究
- **推理能力**：能够进行多步骤的逻辑推理，综合多个因素做出判断
- **解释能力**：生成易于理解的推理说明，帮助投资者理解决策依据
- **适应性**：通过调整提示词，可以改变分析角度和风格

**为什么传统量化方法不够**：
传统量化方法依赖预定义的规则（如 PE < 15 时买入），但真实的投资决策需要考虑：
- 公司的商业模式和护城河
- 管理层的能力和诚信
- 宏观经济环境的影响
- 行业竞争格局的变化

这些因素难以用简单的规则编码，而 LLM 通过学习人类分析师的思维方式，能够更好地处理这些复杂场景。

### LLM 在系统中的角色

1. **分析市场数据并生成投资建议**：将结构化的财务数据转化为投资信号
2. **理解复杂的投资理论和概念**：应用价值投资、成长投资等理论框架
3. **根据不同风格调整分析角度**：如巴菲特关注护城河，林奇关注成长性
4. **生成易于理解的推理说明**：为每个投资决策提供详细解释

### 支持的 LLM 提供商

系统支持多种 LLM 提供商，以满足不同用户的需求：

| 提供商 | 模型 | 特点 | 适用场景 |
|--------|------|------|----------|
| **OpenAI** | GPT-4o | 最强大的推理能力，上下文 128K | 复杂分析、多步骤推理 |
| | GPT-4o-mini | 轻量级、速度快、成本低 | 简单任务、快速响应 |
| **Anthropic** | Claude-3-Sonnet | 长上下文（200K）、安全性强 | 分析大量文档、安全要求高 |
| | Claude-3-Haiku | 超快响应、低成本 | 实时交易、高频查询 |
| **Groq** | Llama2-70B | 硬件加速，延迟 < 1s | 对延迟极其敏感的场景 |
| **DeepSeek** | DeepSeek-Coder | 性价比极高、支持中文 | 成本敏感、中文分析 |
| **Ollama** | 本地开源模型 | 数据隐私、完全本地化 | 机密数据、离线环境 |

**核心概念说明**：

- **Token（词元）**：LLM 处理文本的基本单位。在英文中，1 Token 约等于 0.75 个单词；在中文中，1 Token 约等于 1-2 个汉字。LLM 的定价和限制都以 Token 为单位。

- **Temperature（温度）**：控制 LLM 输出随机性的参数，取值范围 0-2。
  - **低温度（0-0.3）**：输出更加确定、保守，适合需要精确答案的场景
  - **中温度（0.4-0.7）**：输出平衡，适合大多数创作和分析任务
  - **高温度（0.8-2）**：输出更加随机、有创造性，适合创意写作

- **max_tokens（最大生成长度）**：限制 LLM 生成的 Token 数量。超过此限制后，LLM 将停止生成。设置合理的 max_tokens 可以控制成本，但可能导致响应截断。

---

## 8.2 架构设计

### 为什么需要分层架构

系统采用分层架构设计，主要解决以下问题：

**问题 1：供应商锁定**
如果代码直接依赖 OpenAI API，当 OpenAI 服务中断或价格大幅上涨时，迁移到其他提供商将非常困难。

**问题 2：接口差异**
不同 LLM 提供商的 API 差异很大：
- OpenAI 使用 `messages` 数组格式
- Anthropic 使用 `prompt` 字符串格式
- Groq 使用不同的参数命名

**问题 3：配置管理混乱**
API 密钥、模型参数等配置分散在代码中，难以管理和切换。

**解决方案：分层架构**

```
┌─────────────────────────────────────┐
│   业务逻辑层（Agent、分析师）         │
│   ─────────────────────────────────  │
│   不关心具体使用哪个 LLM 提供商       │
└──────────────┬──────────────────────┘
               │ 统一接口调用
┌──────────────▼──────────────────────┐
│   接口层（LLMProvider 抽象）         │
│   ─────────────────────────────────  │
│   定义统一的 generate() 方法         │
└──────────────┬──────────────────────┘
               │ 路由到具体实现
┌──────────────▼──────────────────────┐
│   实现层（具体提供商适配器）         │
│   ─────────────────────────────────  │
│   OpenAIProvider、AnthropicProvider  │
│   GroqProvider、OllamaProvider       │
└──────────────┬──────────────────────┘
               │ HTTP 请求
┌──────────────▼──────────────────────┐
│   LLM 服务提供商（OpenAI API 等）    │
└─────────────────────────────────────┘
```

**分层架构的优势**：
1. **可替换性**：可以随时切换提供商，无需修改业务逻辑代码
2. **可扩展性**：新增提供商只需实现接口，无需修改现有代码
3. **可测试性**：可以轻松 mock LLM 响应，便于单元测试
4. **一致性**：统一的接口使得业务代码更清晰

### 统一接口设计

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from langchain.schema import BaseMessage  # BaseMessage：消息的抽象表示，包含角色和内容

class LLMProvider(ABC):
    """LLM 提供商抽象基类

    定义了所有 LLM 提供商必须实现的接口，确保系统可以无缝切换不同的 LLM 服务。
    """

    @abstractmethod
    def generate(
        self,
        messages: List[BaseMessage],  # BaseMessage：对话消息的抽象，支持多轮对话
        temperature: float = 0.7,     # 温度：控制输出随机性
        max_tokens: int = 4096,      # 最大生成长度：控制响应长度和成本
        **kwargs
    ) -> str:
        """生成文本响应

        Args:
            messages: 对话历史和当前提示
            temperature: 控制输出随机性的参数（0-2）
            max_tokens: 最大生成的 Token 数量
            **kwargs: 其他提供商特定的参数

        Returns:
            str: LLM 生成的文本响应

        Raises:
            LLMError: 调用失败时抛出
        """
        pass

    @abstractmethod
    def get_model_info(self) -> Dict[str, str]:
        """获取模型信息

        Returns:
            Dict: 包含模型名称、上下文长度、定价等信息
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查

        Returns:
            bool: 服务是否可用
        """
        pass
```

**设计模式说明**：
- **策略模式（Strategy Pattern）**：LLMProvider 是策略接口，不同的提供商是具体策略实现
- **工厂模式（Factory Pattern）**：通过 ProviderFactory 根据配置创建具体的 Provider 实例

### 配置管理

```python
# 配置示例
LLM_CONFIGS = {
    "openai": {
        "model": "gpt-4o",              # 模型名称
        "temperature": 0.7,             # 温度参数
        "max_tokens": 4096,             # 最大生成长度
        "api_key": "${OPENAI_API_KEY}", # 从环境变量读取
        "timeout": 60,                  # 请求超时时间（秒）
        "max_retries": 3,               # 最大重试次数
    },
    "anthropic": {
        "model": "claude-3-sonnet-20240229",
        "temperature": 0.7,
        "max_tokens": 4096,
        "api_key": "${ANTHROPIC_API_KEY}",
        "timeout": 60,
        "max_retries": 3,
    },
    "groq": {
        "model": "llama2-70b-4096",
        "temperature": 0.7,
        "max_tokens": 4096,
        "api_key": "${GROQ_API_KEY}",
        "timeout": 30,                  # Groq 响应更快，超时时间可更短
        "max_retries": 3,
    }
}
```

**为什么需要配置管理**：
1. **安全性**：API 密钥不应硬编码在代码中
2. **灵活性**：可以随时调整模型参数而不需要重新部署
3. **多环境支持**：开发、测试、生产环境可以使用不同的配置
4. **A/B 测试**：可以同时配置多个模型进行对比

---

## 8.3 提示词工程（Prompt Engineering）

### 为什么提示词工程如此重要

提示词工程是优化 LLM 输出质量的核心技术。同样的 LLM 模型，使用不同的提示词可能得到质量天差地别的结果。

**核心原因**：
1. **LLM 的本质**：LLM 是概率模型，它根据前面的上下文预测下一个 Token。提示词决定了模型的"上下文"，直接影响预测方向。
2. **任务定义不明确**：LLM 不知道你想让它做什么，需要通过提示词明确任务。
3. **上下文依赖**：LLM 需要足够的背景信息才能做出准确的判断。
4. **输出格式控制**：投资分析需要结构化的输出（如信号、置信度），提示词可以控制输出格式。

**为什么投资分析的提示词更难设计**：
- **领域知识复杂**：涉及财务、经济、行业等多个领域的专业知识
- **多目标优化**：需要同时考虑收益、风险、估值等多个维度
- **不确定性高**：投资决策本身就有不确定性，提示词需要引导模型进行概率思考
- **风格差异大**：不同投资风格（价值、成长、宏观）的分析框架完全不同

### 提示词设计原则

**1. 明确任务（Clear Task Specification）**

❌ **不好的示例**：
```
分析这只股票
```

✅ **好的示例**：
```
作为一名价值投资者，分析以下公司的投资价值。
请从护城河、财务健康、估值三个维度给出评估。
```

**原则**：明确角色、任务、输出格式。

---

**2. 提供上下文（Provide Context）**

❌ **不好的示例**：
```
公司：AAPL
给出投资建议
```

✅ **好的示例**：
```
公司：AAPL（苹果公司）
行业：消费电子、科技服务
当前股价：$180
PE 比率：25
自由现金流：$100B

分析该公司的投资价值。
```

**原则**：提供足够的背景信息，包括公司基本信息、财务数据、行业情况等。

---

**3. 结构化输出（Structured Output）**

❌ **不好的示例**：
```
给出分析结果
```

✅ **好的示例**：
```
请按以下格式输出：

## 投资建议
信号：[BUY/SELL/HOLD]
置信度：[0-100 的整数]

## 分析理由
1. 护城河分析：
   [详细分析]

2. 财务分析：
   [详细分析]

3. 估值分析：
   [详细分析]
```

**原则**：明确指定输出格式，便于后续解析和处理。

---

**4. 示例引导（Example-Guided）**

❌ **不好的示例**：
```
分析以下公司
```

✅ **好的示例**：
```
示例：
公司：MSFT
PE 比率：30，营收增长 15%
分析：优质公司，估值合理
信号：BUY，置信度：80

现在分析：
公司：AAPL
PE 比率：25，营收增长 8%
[请按照示例的格式和深度进行分析]
```

**原则**：通过示例展示期望的输出质量和格式。

---

### 投资分析师提示词示例

```python
# Warren Buffett 风格分析提示词
BUFFETT_PROMPT = """
你是一位经验丰富的价值投资者，遵循沃伦·巴菲特的投资哲学。

## 投资理念（请始终基于以下原则进行分析）
- 只投资于你能理解的业务（能力圈）
- 寻找具有宽阔经济护城河的公司
- 关注自由现金流而非会计利润
- 追求长期投资，而非短期交易
- 在价格低于内在价值时买入（安全边际）

## 分析框架
请分析以下公司，重点关注：

### 1. 经济护城河（Economic Moat）
公司的竞争优势来源及其持久性：
- 品牌优势？
- 网络效应？
- 转换成本？
- 成本优势？
- 监管优势？

### 2. 自由现金流（Free Cash Flow）
公司产生现金的能力：
- 自由现金流是否持续增长？
- 自由现金流占营收的比例？
- 自由现金流如何使用？（分红、回购、再投资）

### 3. 管理质量（Management Quality）
管理层的能力和诚信：
- 资本配置能力如何？
- 是否与股东利益一致？
- 历史业绩如何？

### 4. 安全边际（Margin of Safety）
当前价格与内在价值的差距：
- 内在价值估算方法？
- 当前价格是否安全？
- 需要多大的安全边际？

## 输出要求
请按以下格式输出：

### 投资信号
信号：[BUY/SELL/HOLD]
置信度：[1-100 的整数，表示判断的确定性]

### 详细分析
[分段详细说明你的分析逻辑和依据，每个要点至少 3 句话]

## 公司信息
{company_info}

## 财务数据
{financial_data}

请以上述框架为基础，给出你的分析结果。不要偏离巴菲特的投资哲学。
"""
```

**提示词设计解析**：

1. **角色设定**：明确为"价值投资者"，设定分析框架
2. **理念声明**：列出核心投资原则，确保分析风格一致
3. **结构化框架**：提供清晰的分析维度，避免遗漏
4. **输出模板**：指定输出格式，便于程序解析
5. **提醒**：最后强调"不要偏离"，强化角色设定

---

### 提示词优化技巧

#### Few-shot Learning（少样本学习）

**原理**：在提示词中提供 1-3 个示例，帮助模型理解期望的输出格式和质量。通过示例，模型可以"学习"到输出风格、深度、结构等隐性信息。

**为什么有效**：
- LLM 通过模式匹配学习，示例提供了明确的模式
- 示例可以传递难以用文字描述的隐性知识
- 减少模型的探索空间，提高输出一致性

```python
FEWSHOT_PROMPT = """
分析以下公司股票，给出投资建议。

## 示例 1
公司：AAPL
财务数据：
- 营收增长：8%
- PE 比率：25
- 自由现金流：$100B
- 负债率：30%

分析：
苹果公司具有极强的品牌护城河和生态系统锁定效应。财务健康，自由现金流充裕。当前 PE 25 倍，考虑到其持续增长能力和护城河，估值合理。

信号：BUY
置信度：80

## 示例 2
公司：XYZ
财务数据：
- 营收增长：-15%
- PE 比率：50
- 自由现金流：-$2B
- 负债率：80%

分析：
公司营收持续下滑，基本面恶化。PE 50 倍但营收负增长，估值过高。自由现金流为负，负债率高，财务风险大。

信号：SELL
置信度：75

## 待分析公司
公司：{ticker}
财务数据：
{financial_data}

[请按照示例的格式、深度和分析逻辑，对上述公司进行分析]
"""
```

**关键要点**：
- 示例要涵盖典型场景（好公司、坏公司）
- 示例的分析深度要匹配期望的输出质量
- 示例的格式要严格一致

---

#### Chain-of-Thought（思维链）

**原理**：引导模型逐步思考，将复杂任务分解为多个步骤。通过显式展示思考过程，提高推理质量。

**为什么有效**：
- 分解复杂任务，降低单步推理的难度
- 显式的思考过程便于检查和调试
- 模型在逐步思考中可以发现隐藏的逻辑关系

```python
COT_PROMPT = """
作为一名投资分析师，请按以下步骤分析公司：

## 步骤 1：评估公司的核心竞争力
请回答：
- 公司的主要业务是什么？
- 其竞争优势是什么？（品牌、技术、成本、渠道等）
- 这种优势是否可持续？

[在此处完成分析后，再进入下一步]

## 步骤 2：分析财务健康状况
请回答：
- 营收和利润的增长趋势？
- 现金流是否健康？
- 负债水平是否合理？

[在此处完成分析后，再进入下一步]

## 步骤 3：判断估值水平
请回答：
- 当前 PE、PB 等估值指标如何？
- 与历史平均水平相比如何？
- 与同行业公司相比如何？

[在此处完成分析后，再进入下一步]

## 步骤 4：综合给出最终建议
基于以上分析：
- 信号：{signal} [BUY/SELL/HOLD]
- 置信度：{confidence} [0-100]

## 推理过程总结
[用 3-5 句话总结你的分析逻辑和关键依据]
"""
```

**关键要点**：
- 每个步骤明确要回答的问题
- 步骤之间有逻辑递进关系
- 最后要求总结，强化整体逻辑

---

## 8.4 性能优化

### LLM 调用策略原理

LLM 调用性能优化的核心挑战：

1. **网络延迟**：每次调用需要往返网络，延迟通常在 0.5-3 秒
2. **模型推理时间**：复杂模型推理需要 1-5 秒
3. **速率限制**：API 提供商有每分钟调用次数限制
4. **Token 限制**：单次调用有最大 Token 数限制
5. **成本累积**：大量调用会带来显著成本

**优化策略分类**：
- **并发优化**：减少总等待时间
- **缓存优化**：减少重复调用
- **批量优化**：减少调用次数
- **选择优化**：选择合适的模型和提供商

---

### 并发调用

**原理**：当需要调用多个智能体（如多个投资分析师）时，可以并发执行以提高总效率。由于 LLM 调用是 I/O 密集型任务，等待网络响应时可以释放 CPU 资源处理其他任务。

**为什么有效**：
- 多个 LLM 调用之间相互独立，可以并行执行
- 总等待时间 = max(单个调用时间) 而非 sum(所有调用时间)
- 充分利用网络带宽和 API 提供商的并发能力

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def run_agents_concurrently(agents: List[Agent]) -> List[Dict]:
    """并发运行多个智能体

    使用线程池并发执行多个 LLM 调用，显著减少总等待时间。

    Args:
        agents: 智能体列表

    Returns:
        List[Dict]: 所有智能体的分析结果

    性能提升：
    - 串行调用 10 个智能体：10 * 2s = 20s
    - 并发调用 10 个智能体：2s（取决于最慢的一个）
    """
    loop = asyncio.get_event_loop()

    # 创建线程池，并发数等于智能体数量
    with ThreadPoolExecutor(max_workers=len(agents)) as executor:
        # 将每个智能体的分析任务提交到线程池
        tasks = [
            loop.run_in_executor(executor, agent.analyze)
            for agent in agents
        ]
        # 等待所有任务完成
        results = await asyncio.gather(*tasks)

    return results
```

**注意事项**：
- 并发数不宜过大，可能触发 API 速率限制
- 需要考虑错误处理，一个失败不应影响其他任务
- 内存使用会随并发数增加而增加

---

### 响应缓存

**原理**：对于相同的查询，缓存 LLM 响应，避免重复调用。LLM 调用是确定性的（相同输入 + 相同参数 = 相同输出），因此缓存是安全的。

**为什么有效**：
- 投资分析中，相同的公司数据可能在短时间内多次查询
- 缓存命中时，响应时间从秒级降至毫秒级
- 显著降低成本，减少 API 调用

```python
from functools import lru_cache
import hashlib
from typing import Dict

# 内存缓存，最多存储 1000 个结果
cache: Dict[str, str] = {}

def cache_key(prompt: str, model: str, temperature: float) -> str:
    """生成缓存键

    使用 MD5 哈希将提示词、模型、温度组合成唯一键。

    Args:
        prompt: 提示词内容
        model: 模型名称
        temperature: 温度参数

    Returns:
        str: 32 位十六进制哈希值
    """
    content = f"{prompt}:{model}:{temperature}"
    return hashlib.md5(content.encode()).hexdigest()

def cached_llm_call(
    prompt: str,
    model: str,
    temperature: float = 0.7
) -> str:
    """带缓存的 LLM 调用

    优先从缓存中读取结果，如果未命中则调用 LLM 并缓存结果。

    Args:
        prompt: 提示词
        model: 模型名称
        temperature: 温度参数

    Returns:
        str: LLM 响应

    性能提升：
    - 缓存命中：~1ms
    - 缓存未命中：~2000ms（首次调用）
    """
    key = cache_key(prompt, model, temperature)

    # 尝试从缓存读取
    if key in cache:
        print(f"缓存命中：{key[:8]}...")
        return cache[key]

    # 缓存未命中，调用 LLM
    print(f"调用 LLM：{model}")
    result = llm_provider.generate(prompt, model=model, temperature=temperature)

    # 缓存结果
    cache[key] = result

    return result
```

**缓存策略选择**：

| 策略 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **内存缓存** | 速度快，实现简单 | 重启丢失，容量受限 | 开发环境、短期缓存 |
| **Redis 缓存** | 持久化，容量大 | 需要额外服务 | 生产环境 |
| **数据库缓存** | 持久化，可查询 | 速度较慢 | 需要分析缓存数据 |
| **文件缓存** | 无需额外服务 | 并发性能差 | 单机应用 |

---

### 批处理优化

**原理**：将多个相关任务合并到一个 LLM 调用中，减少调用次数和 Token 开销。

**为什么有效**：
- 减少网络往返次数
- 提示词的上下文可以复用，减少重复输入
- 某些 LLM 支持批量处理，成本更低

```python
BATCH_PROMPT = """
作为投资分析师，请同时分析以下三家公司，给出投资建议。

## 分析框架
- 评估护城河和竞争优势
- 分析财务健康状况
- 判断估值合理性
- 给出投资信号和置信度

## 公司 1：AAPL
公司信息：
苹果公司，全球领先的消费电子和科技公司
主要产品：iPhone、Mac、iPad、Apple Watch

财务数据：
- 营收增长：8%
- PE 比率：25
- 自由现金流：$100B
- ROE（股本回报率）：25%

分析：
{aapl_analysis}

信号：{aapl_signal}，置信度：{aapl_confidence}

## 公司 2：MSFT
公司信息：
微软公司，全球最大的软件和云服务公司
主要业务：Azure 云服务、Office、Windows

财务数据：
- 营收增长：15%
- PE 比率：30
- 自由现金流：$60B
- ROE：40%

分析：
{msft_analysis}

信号：{msft_signal}，置信度：{msft_confidence}

## 公司 3：GOOGL
公司信息：
谷歌母公司 Alphabet，全球最大的互联网广告和搜索引擎公司
主要业务：广告、云服务、Android

财务数据：
- 营收增长：10%
- PE 比率：22
- 自由现金流：$70B
- ROE：18%

分析：
{googl_analysis}

信号：{googl_signal}，置信度：{googl_confidence}

[请按上述框架，依次分析三家公司]
"""
```

**注意事项**：
- 批量处理时，单次 Token 数可能超限，需要控制批量大小
- 批量处理时，单个错误可能影响整体
- 批量处理可能导致响应时间变长

---

## 8.5 成本管理

### API 调用成本概览

不同 LLM 提供商的定价差异很大：

| 提供商 | 模型 | 输入价格（$/1M tokens） | 输出价格（$/1M tokens） |
|--------|------|----------------------|----------------------|
| **OpenAI** | GPT-4o | $5.00 | $15.00 |
| | GPT-4o-mini | $0.15 | $0.60 |
| **Anthropic** | Claude-3-Sonnet | $3.00 | $15.00 |
| | Claude-3-Haiku | $0.25 | $1.25 |
| **Groq** | Llama2-70B | $0.70 | $0.80 |
| **DeepSeek** | DeepSeek-Coder | $0.14 | $0.28 |
| **Ollama** | 本地模型 | $0（硬件成本） | $0（硬件成本） |

**成本估算示例**：
假设每次投资分析调用使用 2000 输入 tokens + 1000 输出 tokens：

- OpenAI GPT-4o：$0.025 / 次
- OpenAI GPT-4o-mini：$0.0009 / 次
- Claude-3-Sonnet：$0.021 / 次
- Groq Llama2-70B：$0.0022 / 次

**年度成本估算**（假设每天分析 100 只股票，250 个交易日）：

| 模型 | 单次成本 | 年调用次数 | 年成本 |
|------|---------|-----------|--------|
| GPT-4o | $0.025 | 25,000 | $625 |
| GPT-4o-mini | $0.0009 | 25,000 | $22.5 |
| Claude-3-Sonnet | $0.021 | 25,000 | $525 |
| Groq Llama2-70B | $0.0022 | 25,000 | $55 |

### 成本优化策略

#### 1. 智能模型选择（Smart Model Selection）

**原理**：根据任务复杂度动态选择合适的模型，在质量和成本之间取得平衡。

**策略**：
- **简单任务**（数据格式化、简单分类）：使用 GPT-4o-mini 或 Haiku
- **中等任务**（标准投资分析）：使用 GPT-4o-mini 或 Claude-3-Sonnet
- **复杂任务**（深度推理、多步骤分析）：使用 GPT-4o 或 Claude-3-Opus

```python
def select_model(task_complexity: str) -> str:
    """根据任务复杂度选择模型

    Args:
        task_complexity: 'simple', 'medium', 'complex'

    Returns:
        str: 模型名称
    """
    model_mapping = {
        "simple": "gpt-4o-mini",
        "medium": "claude-3-sonnet",
        "complex": "gpt-4o"
    }
    return model_mapping.get(task_complexity, "gpt-4o-mini")
```

---

#### 2. 提示词压缩（Prompt Compression）

**原理**：精简提示词长度，减少不必要的 tokens。

**优化技巧**：
- 删除冗余说明
- 使用更简洁的表达
- 避免重复的上下文
- 压缩示例（使用更短的示例）

**示例对比**：

❌ **优化前**（约 800 tokens）：
```
作为一名经验丰富的投资分析师，请根据以下详细的投资分析框架，
仔细分析公司的各个方面，包括但不限于财务状况、竞争优势、
行业前景、管理层能力等多个维度，并给出详细的投资建议...
```

✅ **优化后**（约 200 tokens）：
```
作为投资分析师，从以下维度分析公司：
1. 护城河 2. 财务 3. 估值

输出格式：
信号：[BUY/SELL/HOLD]
置信度：[0-100]
分析：[3-5 句话]
```

---

#### 3. 缓存策略（Caching）

详见 8.4 节"响应缓存"。

**成本节省计算**：
假设 30% 的查询是重复的：
- 无缓存：1000 次调用 × $0.025 = $25
- 有缓存：700 次调用 × $0.025 + 300 次缓存命中 ≈ $17.5
- 节省：30%

---

#### 4. 并发限制优化（Concurrency Control）

**原理**：限制并发调用数量，避免超出速率限制导致额外的重试成本。

```python
import asyncio
from collections import defaultdict

class RateLimiter:
    """速率限制器

    避免超出 API 提供商的速率限制，减少因限制导致的重试和错误。
    """

    def __init__(self, max_concurrent: int = 10):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.call_count = defaultdict(int)
        self.reset_time = None

    async def acquire(self):
        """获取调用许可"""
        await self.semaphore.acquire()

    def release(self):
        """释放调用许可"""
        self.semaphore.release()
```

---

### 成本估算工具

```python
def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    provider: str,
    model: str
) -> float:
    """估算 API 调用成本

    Args:
        prompt_tokens: 输入 Token 数量
        completion_tokens: 输出 Token 数量
        provider: 提供商名称
        model: 模型名称

    Returns:
        float: 预估成本（美元）
    """
    # 定价表（$/1M tokens）
    pricing = {
        "openai": {
            "gpt-4o": {"input": 5.0, "output": 15.0},
            "gpt-4o-mini": {"input": 0.15, "output": 0.6}
        },
        "anthropic": {
            "claude-3-sonnet": {"input": 3.0, "output": 15.0},
            "claude-3-haiku": {"input": 0.25, "output": 1.25}
        }
    }

    rate = pricing[provider][model]
    input_cost = (prompt_tokens / 1_000_000) * rate["input"]
    output_cost = (completion_tokens / 1_000_000) * rate["output"]

    return input_cost + output_cost

# 使用示例
cost = estimate_cost(2000, 1000, "openai", "gpt-4o-mini")
print(f"预估成本：${cost:.6f}")
# 输出：预估成本：$0.000900
```

---

## 8.6 故障处理

### 为什么故障处理至关重要

LLM API 调用可能因为多种原因失败：

1. **网络问题**：网络超时、连接中断
2. **服务不可用**：API 提供商服务宕机
3. **速率限制**：超出调用次数限制
4. **认证失败**：API 密钥过期或无效
5. **模型错误**：输入参数错误或模型返回异常

在投资分析场景中，LLM 调用失败可能导致：
- 错过交易机会
- 分析不完整
- 用户体验下降
- 数据不一致

因此，健壮的故障处理机制是生产环境必须的。

---

### 重试机制（Retry Mechanism）

**原理**：对于临时性错误（如网络超时、服务暂时不可用），实现指数退避重试。指数退避可以避免在服务压力大时频繁重试导致雪崩。

**为什么指数退避**：
- 首次失败后，等待 2^1 = 2 秒重试
- 第二次失败后，等待 2^2 = 4 秒重试
- 第三次失败后，等待 2^3 = 8 秒重试
- 逐渐增加等待时间，给服务恢复的时间

```python
import time
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),  # 最多重试 3 次
    wait=wait_exponential(
        multiplier=1,    # 基础等待时间 1 秒
        min=4,          # 最小等待 4 秒
        max=10          # 最大等待 10 秒
    )
)
def llm_call_with_retry(prompt: str) -> str:
    """带重试的 LLM 调用

    使用指数退避策略，在临时性错误时自动重试。

    Args:
        prompt: 提示词

    Returns:
        str: LLM 响应

    Raises:
        LLMError: 重试 3 次后仍失败时抛出
    """
    try:
        return llm_provider.generate(prompt)
    except (TimeoutError, ServiceUnavailableError) as e:
        print(f"LLM 调用失败，准备重试: {e}")
        # tenacity 会自动重试，这里只需抛出异常
        raise
```

**重试策略选择**：

| 策略 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| **立即重试** | 网络抖动 | 简单 | 可能加剧服务压力 |
| **固定延迟** | 可预测的延迟 | 简单控制 | 可能仍然密集 |
| **指数退避** | 服务过载 | 最优恢复时间 | 实现稍复杂 |
| **抖动退避** | 高并发场景 | 避免重试风暴 | 实现复杂 |

---

### 降级策略（Fallback Strategy）

**原理**：当首选模型不可用时，自动降级到备用模型或更简单的任务。

**为什么需要降级**：
- 提高系统可用性，即使某个提供商宕机也能继续运行
- 在资源受限时，可以使用更经济的模型
- 提供不同的服务质量，平衡成本和质量

```python
from typing import List, Optional

def call_with_fallback(
    prompt: str,
    providers: List[str] = ["openai", "anthropic", "groq"]
) -> str:
    """带降级策略的调用

    依次尝试不同的提供商，直到成功或所有提供商都失败。

    Args:
        prompt: 提示词
        providers: 提供商列表，按优先级排序

    Returns:
        str: LLM 响应

    Raises:
        AllProvidersFailedError: 所有提供商都失败时抛出
    """
    last_error = None

    for provider in providers:
        try:
            print(f"尝试使用 {provider}...")
            result = llm_providers[provider].generate(prompt)
            print(f"{provider} 调用成功")
            return result
        except Exception as e:
            print(f"{provider} 调用失败: {e}")
            last_error = e
            continue

    # 所有提供商都失败
    raise AllProvidersFailedError(
        f"所有 LLM 提供商均不可用。最后错误：{last_error}"
    )

class AllProvidersFailedError(Exception):
    """所有提供商都失败时抛出"""
    pass
```

**降级策略设计**：

```
首选方案：GPT-4o（最高质量）
    │
    ├─ 失败 → 降级到 Claude-3-Sonnet
    │   │
    │   └─ 失败 → 降级到 GPT-4o-mini
    │       │
    │       └─ 失败 → 降级到本地模型
    │           │
    │           └─ 失败 → 返回缓存结果或默认值
```

---

### 熔断机制（Circuit Breaker）

**原理**：当某个提供商连续失败超过阈值时，暂时停止调用该提供商，直接进入降级或失败流程。一段时间后，尝试恢复调用。

**为什么需要熔断**：
- 避免持续调用失败的提供商，浪费时间和成本
- 防止错误级联，导致整个系统崩溃
- 提供快速失败机制，快速切换到备用方案

```python
from datetime import datetime, timedelta
from typing import Optional

class CircuitBreaker:
    """熔断器

    当提供商连续失败超过阈值时，熔断该提供商，
    一段时间后尝试恢复。
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60
    ):
        """
        Args:
            failure_threshold: 连续失败多少次后熔断
            timeout: 熔断后等待多少秒尝试恢复
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # closed, open, half-open

    def call(self, func, *args, **kwargs):
        """调用函数，带熔断保护

        Args:
            func: 要调用的函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            CircuitOpenError: 熔断器开启时抛出
        """
        if self.state == "open":
            # 检查是否可以尝试恢复
            if self._should_attempt_reset():
                self.state = "half-open"
                print("熔断器半开，尝试恢复...")
            else:
                raise CircuitOpenError(
                    f"熔断器开启，等待 {self.timeout} 秒后恢复"
                )

        try:
            result = func(*args, **kwargs)
            # 调用成功，重置失败计数
            self._on_success()
            return result
        except Exception as e:
            # 调用失败，增加失败计数
            self._on_failure()
            raise

    def _on_success(self):
        """调用成功时的处理"""
        self.failure_count = 0
        self.state = "closed"
        print("调用成功，熔断器关闭")

    def _on_failure(self):
        """调用失败时的处理"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            print(
                f"连续失败 {self.failure_count} 次，"
                f"熔断器开启"
            )

    def _should_attempt_reset(self) -> bool:
        """是否应该尝试恢复"""
        if self.last_failure_time is None:
            return True

        elapsed = datetime.now() - self.last_failure_time
        return elapsed.total_seconds() > self.timeout


class CircuitOpenError(Exception):
    """熔断器开启时抛出"""
    pass


# 使用示例
circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=60)

def safe_llm_call(prompt: str) -> str:
    """带熔断保护的 LLM 调用"""
    def _call():
        return llm_provider.generate(prompt)

    return circuit_breaker.call(_call)
```

**熔断器状态转换**：

```
┌─────────┐     连续失败    ┌─────────┐     等待 timeout    ┌─────────┐
│ Closed  │ ────────────────►│  Open   │ ──────────────────►│Half-Open│
│ (正常)  │   超过阈值        │ (熔断)  │    秒后尝试恢复    │ (半开)  │
└─────────┘                 └─────────┘                    └─────────┘
     ▲                           ▲                             │
     │                           │                             │
     │       成功后重置          │          成功               │
     └───────────────────────────┘─────────────────────────────┘
```

---

## 8.7 练习与实践

### 练习 8.1：提示词优化（基础）

**目标**：优化一个投资分析提示词，提高输出质量和一致性。

**任务步骤**：

1. **分析现有提示词**
   ```python
   # 现有提示词（有问题）
   BAD_PROMPT = "分析这只股票"
   ```

   问题清单：
   - [ ] 缺少角色设定
   - [ ] 缺少分析框架
   - [ ] 缺少输出格式
   - [ ] 缺少示例引导

2. **设计改进方案**
   - 设定投资分析师角色（价值投资/成长投资）
   - 设计分析框架（护城河/财务/估值）
   - 指定输出格式（信号/置信度/分析）
   - 添加示例（一个好公司，一个坏公司）

3. **实现改进后的提示词**
   ```python
   # 在此实现改进后的提示词
   IMPROVED_PROMPT = """
   [你的改进提示词]
   """
   ```

4. **测试对比**
   - 使用相同输入数据
   - 分别调用现有提示词和改进后的提示词
   - 对比输出质量

**检验标准**：
- [ ] 改进后的提示词输出包含信号、置信度、分析三个部分
- [ ] 分析内容至少提到护城河、财务、估值中的两个维度
- [ ] 分析逻辑清晰，至少 3 句话
- [ ] 使用相同的输入数据，输出一致性提高（连续调用 3 次，输出风格相似）

**预期输出示例**：
```
信号：BUY
置信度：80

分析：苹果公司拥有强大的品牌护城河和生态系统，用户粘性极高。
财务状况健康，自由现金流充裕。当前 PE 25 倍，考虑到持续增长
能力和护城河，估值合理。建议买入。
```

---

### 练习 8.2：成本分析与优化（进阶）

**目标**：分析不同 LLM 提供商的成本效益，设计成本优化策略。

**实验设计**：

1. **选择测试任务**
   - 使用相同的投资分析提示词（如练习 8.1 中的提示词）
   - 选择 3 只股票进行测试（如 AAPL、MSFT、GOOGL）
   - 使用相同的财务数据

2. **测试不同提供商**
   ```python
   providers = ["openai", "anthropic", "groq"]
   models = {
       "openai": ["gpt-4o", "gpt-4o-mini"],
       "anthropic": ["claude-3-sonnet", "claude-3-haiku"],
       "groq": ["llama2-70b"]
   }

   # 记录每次调用的：
   # - 输入 Token 数量
   # - 输出 Token 数量
   # - 响应时间
   # - 输出质量（人工评分 1-10）
   ```

3. **计算成本**
   ```python
   def calculate_experiment_cost():
       """
       计算每种提供商/模型的成本

       格式：
       | 提供商 | 模型 | 输入 tokens | 输出 tokens | 成本 | 响应时间 | 质量评分 |
       |--------|------|------------|------------|------|---------|---------|
       """
       pass
   ```

4. **分析性价比**
   - 计算每个提供商的"成本/质量"比
   - 计算每个提供商的"成本/时间"比
   - 评估最适合你场景的提供商

**检验标准**：
- [ ] 测试至少 3 个提供商、6 种模型配置
- [ ] 记录每次调用的输入/输出 Token 数量
- [ ] 记录响应时间和输出质量评分
- [ ] 计算每种配置的总成本和平均成本
- [ ] 给出成本优化建议（至少 3 条）

**输出模板**：
```
## 成本分析报告

### 测试概览
- 测试股票：AAPL、MSFT、GOOGL
- 测试提供商：OpenAI、Anthropic、Groq
- 总调用次数：18 次

### 成本对比
| 提供商 | 模型 | 总成本 | 平均成本 | 平均响应时间 | 平均质量评分 | 性价比 |
|--------|------|--------|---------|------------|------------|-------|
| OpenAI | GPT-4o | $... | $... | ...s | 8.5/10 | ... |
| OpenAI | GPT-4o-mini | $... | $... | ...s | 7.0/10 | ... |
| ... | ... | ... | ... | ... | ... | ... |

### 分析结论
1. [质量分析]...
2. [成本分析]...
3. [效率分析]...

### 成本优化建议
1. [建议 1]...
2. [建议 2]...
3. [建议 3]...
```

---

### 练习 8.3：故障处理机制实现（进阶）

**目标**：实现完整的 LLM 调用故障处理机制，提高系统可用性。

**任务步骤**：

1. **实现指数退避重试**
   ```python
   def llm_call_with_retry(
       prompt: str,
       max_retries: int = 3,
       base_delay: int = 2
   ) -> str:
       """
       实现指数退避重试机制

       要求：
       - 首次失败后等待 2^1 = 2 秒
       - 第二次失败后等待 2^2 = 4 秒
       - 第三次失败后等待 2^3 = 8 秒
       - 超过 max_retries 后抛出异常
       """
       pass
   ```

2. **实现多提供商降级**
   ```python
   def call_with_fallback(
       prompt: str,
       providers: List[str]
   ) -> str:
       """
       实现多提供商降级

       要求：
       - 按优先级依次尝试提供商
       - 记录每个提供商的调用结果
       - 所有提供商都失败时抛出异常
       """
       pass
   ```

3. **实现熔断器**
   ```python
   class CircuitBreaker:
       """
       实现熔断器

       要求：
       - 连续失败超过阈值后熔断
       - 熔断后等待一段时间尝试恢复
       - 恢复成功后关闭熔断
       """
       pass
   ```

4. **集成测试**
   ```python
   def test_fault_handling():
       """
       测试各种故障场景：

       场景 1：模拟网络超时（应该自动重试）
       场景 2：模拟提供商宕机（应该降级到备用提供商）
       场景 3：模拟连续失败（应该触发熔断）
       场景 4：正常调用（应该正常返回）
       """
       pass
   ```

**检验标准**：
- [ ] 指数退避重试实现正确（等待时间分别为 2s、4s、8s）
- [ ] 多提供商降级实现正确（依次尝试所有提供商）
- [ ] 熔断器实现正确（达到阈值后熔断，超时后恢复）
- [ ] 集成测试覆盖所有故障场景
- [ ] 代码有完善的错误日志记录

**测试用例**：

```python
# 测试用例示例
def test_scenarios():
    # 场景 1：网络超时
    with mock.patch('llm_provider.generate', side_effect=TimeoutError):
        result = llm_call_with_retry(prompt="test")
        assert result is not None  # 重试成功

    # 场景 2：提供商宕机
    with mock.patch('llm_providers.openai.generate', side_effect=ServiceUnavailableError):
        result = call_with_fallback(prompt="test", providers=["openai", "anthropic"])
        assert "anthropic" in result  # 降级到 anthropic

    # 场景 3：连续失败触发熔断
    cb = CircuitBreaker(failure_threshold=3)
    for i in range(5):
        try:
            cb.call(lambda: raise_exception())
        except Exception:
            pass
    assert cb.state == "open"  # 熔断器开启
```

**预期输出**：
```
=== 故障处理测试报告 ===

✅ 场景 1：网络超时 - 重试成功（2s 后）
✅ 场景 2：OpenAI 宕机 - 降级到 Anthropic
✅ 场景 3：连续失败 - 熔断器开启
✅ 场景 4：正常调用 - 熔断器恢复
✅ 场景 5：所有提供商失败 - 抛出 AllProvidersFailedError

所有测试通过！
```

---

### 练习 8.4：智能模型选择系统（专家）

**目标**：设计并实现一个能够根据任务复杂度自动选择最优模型的系统。

**任务要求**：

1. **定义任务复杂度评估标准**
   ```python
   def assess_task_complexity(
       prompt: str,
       data_size: int
   ) -> str:
       """
       评估任务复杂度

       考虑因素：
       - Prompt 长度
       - 数据规模（财务数据数量）
       - 是否需要多步推理
       - 是否需要大量上下文

       返回：'simple', 'medium', 'complex'
       """
       pass
   ```

2. **实现模型选择策略**
   ```python
   def select_optimal_model(
       task_complexity: str,
       cost_sensitivity: str = 'medium'
   ) -> str:
       """
       根据任务复杂度和成本敏感度选择模型

       策略：
       - 简单任务 + 低成本敏感 → GPT-4o-mini
       - 简单任务 + 高成本敏感 → Haiku
       - 中等任务 + 低成本敏感 → Claude-3-Sonnet
       - 中等任务 + 高成本敏感 → GPT-4o-mini
       - 复杂任务 + 低成本敏感 → GPT-4o
       - 复杂任务 + 高成本敏感 → Claude-3-Sonnet
       """
       pass
   ```

3. **实现动态调整机制**
   ```python
   class AdaptiveModelSelector:
       """
       自适应模型选择器

       特性：
       - 根据历史调用结果动态调整选择策略
       - 学习哪个模型在哪些任务上表现最好
       - 考虑实时成本和响应时间
       """
       pass
   ```

4. **性能评估**
   - 对比自动选择与固定选择的成本和质量
   - 分析模型选择策略的有效性

**检验标准**：
- [ ] 任务复杂度评估准确（至少考虑 3 个因素）
- [ ] 模型选择策略覆盖所有场景（3×3 = 9 种组合）
- [ ] 动态调整机制能够从历史数据中学习
- [ ] 性能评估包含成本、质量、响应时间三个维度
- [ ] 自动选择在成本或质量上优于固定选择

---

## 8.8 进阶思考与扩展

### 深度问题

1. **LLM 在投资分析任务上的表现差异有多大？**
   - 不同 LLM 在相同任务上的输出质量差异如何量化？
   - GPT-4o 和 Claude-3 在投资分析上的优劣对比？
   - 如何评估 LLM 输出的可信度和一致性？

2. **如何设计一个能够自动选择最优模型的系统？**
   - 除了任务复杂度，还需要考虑哪些因素？
   - 如何平衡质量、成本、速度三个维度？
   - 是否可以使用多个模型的集成（Ensemble）来提升准确率？

3. **提示词工程如何借鉴人类分析师的思维过程？**
   - 人类分析师的思维框架如何转化为提示词？
   - 如何设计能够模拟不同投资风格的提示词？
   - 提示词的可解释性和透明度如何保证？

4. **LLM 集成的未来发展方向是什么？**
   - 小模型（Small Language Models）的兴起对架构设计的影响？
   - 自定义微调模型在垂直领域的应用？
   - 多模态 LLM（分析图表、K线图）的集成？

### 扩展阅读

- **OpenAI 官方文档**：https://platform.openai.com/docs/
- **Anthropic 提示词工程指南**：https://docs.anthropic.com/claude/docs/prompt-engineering
- **LangChain LLM 集成最佳实践**：https://python.langchain.com/docs/modules/model_io/
- **论文：Large Language Models are Zero-Shot Reasoners**：Chain-of-Thought 的开创性论文

---

## 版本信息

| 项目 | 信息 |
|------|------|
| 文档版本 | 2.0.0 |
| 最后更新 | 2026年2月13日 |
| 适用版本 | 1.0.0+ |
| 文档标准 | Chinese-Technical-Documentation-Writer v1.0 |

**更新日志**：
- **v2.0.0 (2026.02.13)**：完全重构，按照 chinese-doc-writer skill 标准改进
  - 添加分层学习目标（基础/进阶/专家）
  - 完善术语管理，所有首次出现的英文术语都有中文解释
  - 增加"为什么"的原理解析，重点关注 LLM 调用策略
  - 优化认知负荷管理，改进内容结构和呈现方式
  - 完善练习设计，添加检验标准和预期输出
  - 修正中英文混排问题
- **v1.0.2 (2026.02)**：完善提示词工程章节，增加 Provider 模式说明
- **v1.0.1 (2025.12)**：增加 Ollama 本地部署说明
- **v1.0.0 (2025.10)**：初始版本

---

## 反馈与贡献

### 文档改进建议

如果您在阅读过程中发现问题或有改进建议，欢迎通过以下方式反馈：

- **GitHub Issues**：https://github.com/virattt/ai-hedge-fund/issues
- **Pull Request**：直接提交改进的代码或文档
- **讨论区**：在 GitHub Discussions 中提出问题或分享经验

### 贡献指南

我们欢迎任何形式的贡献：

1. **文档贡献**：修正错误、补充内容、翻译文档
2. **代码贡献**：修复 Bug、添加新功能、优化性能
3. **测试贡献**：编写测试用例、报告 Bug
4. **建议贡献**：提出改进建议、分享使用经验

**贡献流程**：
1. Fork 本仓库
2. 创建特性分支（`git checkout -b feature/AmazingFeature`）
3. 提交更改（`git commit -m 'Add some AmazingFeature'`）
4. 推送到分支（`git push origin feature/AmazingFeature`）
5. 创建 Pull Request

**文档改进清单**：
- [ ] 术语定义准确，首次出现有中文解释
- [ ] 代码示例完整，有注释说明
- [ ] 逻辑清晰，"为什么"解释充分
- [ ] 格式规范，中英文混排统一
- [ ] 练习有检验标准，可自我验证
- [ ] 适合目标读者水平，认知负荷合理

---

完成 Level 2 核心概念的学习后，你可以继续学习 **Level 3 进阶分析**，深入了解系统的高级功能和扩展方法。
