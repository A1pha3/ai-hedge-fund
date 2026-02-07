# 第八章：LLM 集成架构

## 学习目标

完成本章节学习后，你将能够理解系统与大型语言模型集成的整体架构，掌握不同 LLM 提供商的特点和配置方法，了解提示词工程的基本原则和实践技巧，以及学会如何优化 LLM 调用以提高效率和降低成本。预计学习时间为 1.5-2 小时。

## 8.1 LLM 集成概述

### 为什么需要 LLM

AI Hedge Fund 系统的核心创新在于使用大型语言模型（LLM）来模拟人类投资分析师的思考过程。传统的量化投资策略通常使用预定义的规则和数学模型，而本系统利用 LLM 的推理能力，能够处理非结构化的信息、进行复杂的逻辑推理、生成详细的分析解释。

LLM 在系统中扮演几个关键角色：分析市场数据并生成投资建议、理解复杂的投资理论和概念、根据不同风格调整分析角度、以及生成易于理解的推理说明。

### 支持的 LLM 提供商

系统支持多种 LLM 提供商，以满足不同用户的需求：

**OpenAI**：提供 GPT-4o 和 GPT-4o-mini 模型。GPT-4o 是目前最强大的模型之一，在复杂推理任务上表现出色。GPT-4o-mini 是轻量级版本，速度更快、成本更低，适合简单任务。

**Anthropic**：提供 Claude 系列模型。Claude 在长上下文处理方面有优势，适合需要分析大量文档的场景。

**Groq**：提供高速推理服务。Groq 的特点是响应速度极快，适合对延迟敏感的应用场景。

**DeepSeek**：提供具有竞争力的价格，适合大规模测试和成本敏感的用户。

**Ollama**：支持本地部署，数据完全不离开本地环境，适合对数据隐私有严格要求的用户。

## 8.2 架构设计

### 分层架构

LLM 集成采用分层架构设计：

**接口层**：定义统一的 LLM 调用接口，屏蔽不同提供商的差异。

**实现层**：为每个提供商实现具体的连接和调用逻辑。

**配置层**：管理 API 密钥、模型参数等配置信息。

**缓存层**：缓存 LLM 响应，减少重复调用。

### 统一接口设计

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from langchain.schema import BaseMessage

class LLMProvider(ABC):
    """LLM 提供商抽象基类"""
    
    @abstractmethod
    def generate(
        self,
        messages: List[BaseMessage],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """生成文本响应"""
        pass
    
    @abstractmethod
    def get_model_info(self) -> Dict[str, str]:
        """获取模型信息"""
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """健康检查"""
        pass
```

### 配置管理

```python
# 配置示例
LLM_CONFIGS = {
    "openai": {
        "model": "gpt-4o",
        "temperature": 0.7,
        "max_tokens": 4096,
    },
    "anthropic": {
        "model": "claude-3-sonnet-20240229",
        "temperature": 0.7,
        "max_tokens": 4096,
    },
    "groq": {
        "model": "llama2-70b-4096",
        "temperature": 0.7,
        "max_tokens": 4096,
    }
}
```

## 8.3 提示词工程

### 提示词设计原则

提示词（Prompt）是用户与大语言模型交互的核心。设计良好的提示词能够显著提高模型输出的质量和一致性。

**明确任务**：清晰说明期望模型完成的任务，避免模糊的描述。

**提供上下文**：给予模型足够的背景信息，帮助它理解任务场景。

**结构化输出**：指定期望的输出格式，便于后续解析。

**示例引导**：提供示例来说明期望的输出形式。

### 投资分析师提示词示例

```python
# Warren Buffett 风格分析提示词
BUFFETT_PROMPT = """
你是一位经验丰富的价值投资者，遵循沃伦·巴菲特的投资哲学。

## 投资理念
- 只投资于你能理解的业务（能力圈）
- 寻找具有宽阔经济护城河的公司
- 关注自由现金流而非会计利润
- 追求长期投资，而非短期交易

## 分析框架
请分析以下公司，重点关注：
1. 经济护城河：公司的竞争优势来源及其持久性
2. 自由现金流：公司产生现金的能力
3. 管理质量：管理层的能力和诚信
4. 安全边际：当前价格与内在价值的差距

## 输出要求
- 信号：BUY（买入）、SELL（卖出）、HOLD（持有）
- 置信度：1-100 的整数
- 推理：详细说明你的分析逻辑和依据

## 公司信息
{company_info}

## 财务数据
{financial_data}

请以上述框架为基础，给出你的分析结果。
"""
```

### 提示词优化技巧

**Few-shot Learning**：在提示词中提供 1-3 个示例，帮助模型理解期望的输出格式。

```python
FEWSHOT_PROMPT = """
分析以下公司股票，给出投资建议。

示例 1：
公司：AAPL
财务数据：营收增长 8%，PE 比率 25，自由现金流充裕
分析：优质公司，估值合理
信号：BUY，置信度：80

示例 2：
公司：XYZ
财务数据：营收下降 15%，PE 比率 50，负债率高
分析：基本面恶化，估值过高
信号：SELL，置信度：75

请分析：
公司：{ticker}
财务数据：{financial_data}
"""
```

**Chain-of-Thought**：引导模型逐步思考，提高推理质量。

```python
COT_PROMPT = """
请按以下步骤分析公司：

步骤 1：评估公司的核心竞争力
[模型的思考过程]

步骤 2：分析财务健康状况
[模型的思考过程]

步骤 3：判断估值水平
[模型的思考过程]

步骤 4：综合给出最终建议
信号：{signal}，置信度：{confidence}

推理：{reasoning}
"""
```

## 8.4 性能优化

### 并发调用

当需要调用多个智能体时，可以并发执行以提高效率：

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def run_agents_concurrently(agents: List[Agent]):
    """并发运行多个智能体"""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=len(agents)) as executor:
        tasks = [
            loop.run_in_executor(executor, agent.analyze)
            for agent in agents
        ]
        results = await asyncio.gather(*tasks)
    return results
```

### 响应缓存

对于相同的查询，可以缓存 LLM 响应：

```python
from functools import lru_cache
import hashlib

def cache_key(prompt: str, model: str) -> str:
    """生成缓存键"""
    return hashlib.md5(f"{prompt}:{model}".encode()).hexdigest()

def cached_llm_call(prompt: str, model: str) -> str:
    """带缓存的 LLM 调用"""
    key = cache_key(prompt, model)
    if key in cache:
        return cache[key]
    result = llm_provider.generate(prompt, model=model)
    cache[key] = result
    return result
```

### 批处理优化

对于需要分析多只股票的场景，可以使用批量提示：

```python
BATCH_PROMPT = """
请同时分析以下三家公司，给出投资建议。

公司 1：AAPL
财务数据：{aapl_data}
分析：{aapl_analysis}
信号：{aapl_signal}，置信度：{aapl_confidence}

公司 2：MSFT
财务数据：{msft_data}
分析：{msft_analysis}
信号：{msft_signal}，置信度：{msft_confidence}

公司 3：GOOGL
财务数据：{googl_data}
分析：{googl_analysis}
信号：{googl_signal}，置信度：{googl_confidence}
"""
```

## 8.5 成本管理

### API 调用成本概览

不同 LLM 提供商的定价差异很大：

| 提供商 | 模型 | 输入价格（$） | 输出价格（$） |
|--------|------|---------------|---------------|
| OpenAI | GPT-4o | 5/1M | 15/1M |
| OpenAI | GPT-4o-mini | 0.15/1M | 0.6/1M |
| Anthropic | Claude-3-Sonnet | 3/1M | 15/1M |
| Groq | Llama2-70B | 0.7/1M | 0.8/1M |

### 成本优化策略

**模型选择**：根据任务复杂度选择合适的模型。简单任务使用轻量级模型，复杂任务使用高级模型。

**提示词优化**：精简提示词长度，减少不必要的 tokens。

**缓存策略**：缓存相同查询的响应，避免重复调用。

**并发限制**：限制并发调用数量，避免超出速率限制。

```python
# 成本估算示例
def estimate_cost(prompt_tokens: int, completion_tokens: int, provider: str) -> float:
    """估算 API 调用成本"""
    rates = {
        "openai": {"input": 0.000005, "output": 0.000015},
        "anthropic": {"input": 0.000003, "output": 0.000015},
    }
    rate = rates[provider]
    return prompt_tokens * rate["input"] + completion_tokens * rate["output"]

# 示例：1000 tokens 输入，500 tokens 输出
cost = estimate_cost(1000, 500, "openai")
print(f"预估成本：${cost:.6f}")
```

## 8.6 故障处理

### 重试机制

对于临时性错误（如网络超时、服务暂时不可用），实现指数退避重试：

```python
import time
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
def llm_call_with_retry(prompt: str) -> str:
    """带重试的 LLM 调用"""
    try:
        return llm_provider.generate(prompt)
    except (TimeoutError, ServiceUnavailableError) as e:
        print(f"LLM 调用失败，准备重试: {e}")
        raise
```

### 降级策略

当首选模型不可用时，自动降级到备用模型：

```python
def call_with_fallback(prompt: str) -> str:
    """带降级策略的调用"""
    providers = ["openai", "anthropic", "groq"]
    
    for provider in providers:
        try:
            return llm_providers[provider].generate(prompt)
        except Exception as e:
            print(f"{provider} 调用失败: {e}")
            continue
    
    raise AllProvidersFailedError("所有 LLM 提供商均不可用")
```

## 8.7 练习题

### 练习 8.1：提示词优化

**任务**：优化一个投资分析提示词。

**步骤**：首先分析现有提示词的问题，然后设计改进方案，接着比较优化前后的输出质量，最后记录优化要点。

**要求**：提示词优化后输出质量显著提高，推理更加清晰有条理。

### 练习 8.2：成本分析

**任务**：分析不同 LLM 提供商的成本效益。

**实验设计**：分别使用 OpenAI GPT-4o、Anthropic Claude、Groq Llama2 运行相同的分析任务，记录输入/输出 tokens 和响应质量。

**要求**：计算各提供商的成本，评估性价比，提出成本优化建议。

### 练习 8.3：故障处理实现

**任务**：实现完整的 LLM 调用故障处理机制。

**步骤**：首先实现指数退避重试，然后实现多提供商降级，接着实现响应缓存，最后测试各种故障场景。

**要求**：系统能够在各种故障场景下优雅降级，保证服务可用性。

---

## 进阶思考

思考以下问题。不同 LLM 在投资分析任务上的表现差异有多大？如何设计一个能够自动选择最优模型的系统？提示词工程如何借鉴人类分析师的思维过程？

完成 Level 2 核心概念的学习后，你可以继续学习 Level 3 进阶分析，深入了解系统的高级功能和扩展方法。

---

## 版本信息

| 项目 | 信息 |
|------|------|
| 文档版本 | 1.0.2 |
| 最后更新 | 2026年2月 |
| 适用版本 | 1.0.0+ |

**更新日志**：
- v1.0.2 (2026.02)：完善提示词工程章节，增加 Provider 模式说明
- v1.0.1 (2025.12)：增加 Ollama 本地部署说明
- v1.0.0 (2025.10)：初始版本

## 反馈与贡献

如果您在阅读过程中发现问题或有改进建议，欢迎通过 GitHub Issues 提交反馈。
