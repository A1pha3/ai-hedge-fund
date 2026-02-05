# 第一章：智能体开发指南

## 学习目标

完成本章节学习后，你将能够理解智能体的标准化接口和实现模式，掌握创建新智能体的完整流程，学会设计有效的提示词和分析框架，以及能够将新智能体集成到系统中。预计学习时间为 2-3 小时。

## 1.1 智能体架构概述

### 核心接口定义

每个智能体都需要实现统一的接口规范。系统定义了智能体的基本结构和行为标准，确保所有智能体能够以一致的方式工作。

智能体的核心接口包含三个关键方法：`analyze()` 方法接收分析请求，调用 LLM 进行推理，并返回结构化的分析结果。`get_prompt()` 方法负责构建发送给 LLM 的提示词，这是智能体分析和决策的核心。`parse_response()` 方法解析 LLM 的原始输出，将其转换为标准化的信号格式。

### 智能体基类

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from langchain.schema import BaseMessage

class BaseAgent(ABC):
    """智能体基类"""
    
    # 子类需要覆盖这些属性
    agent_id: str
    agent_name: str
    agent_description: str
    investment_style: str
    
    @abstractmethod
    def analyze(
        self,
        ticker: str,
        data: Dict[str, Any],
        model_provider: str = "openai"
    ) -> Dict[str, Any]:
        """
        执行分析
        
        Args:
            ticker: 股票代码
            data: 分析所需的数据
            model_provider: LLM 提供商
            
        Returns:
            包含 signal, confidence, reasoning 的字典
        """
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """获取系统提示词"""
        pass
    
    @abstractmethod
    def parse_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 响应"""
        pass
```

### 信号输出规范

所有智能体的输出必须符合标准化的信号格式：

```python
from pydantic import BaseModel
from typing import Literal
from enum import Enum

class TradingSignal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class AgentSignal(BaseModel):
    """标准化智能体信号"""
    signal: TradingSignal  # 交易信号
    confidence: int  # 置信度 0-100
    reasoning: str  # 推理说明
    metadata: Dict[str, Any] = {}  # 可选元数据
```

## 1.2 创建新智能体

### 步骤一：创建智能体文件

在 `src/agents/` 目录下创建新的智能体文件。文件命名遵循 `{投资风格}.py` 的格式：

```python
# src/agents/momentum_trader.py

"""
动量交易智能体

基于价格动量和趋势强度进行技术分析的智能体。
"""

from typing import Dict, Any, Optional
from langchain.schema import BaseMessage, HumanMessage
from src.agents.base import BaseAgent
from src.agents.signal import AgentSignal, TradingSignal

class MomentumTraderAgent(BaseAgent):
    """动量交易智能体"""
    
    agent_id = "momentum_trader"
    agent_name = "动量交易者"
    agent_description = """
        基于价格动量和趋势强度进行技术分析的智能体。
        关注价格动量、趋势持续性和相对强度指标。
    """
    investment_style = "Technical Analysis"
    
    def __init__(self, llm_provider):
        self.llm_provider = llm_provider
    
    def analyze(
        self,
        ticker: str,
        data: Dict[str, Any],
        model_provider: str = "openai"
    ) -> Dict[str, Any]:
        """执行动量分析"""
        # 获取提示词
        prompt = self._build_prompt(ticker, data)
        
        # 调用 LLM
        messages = [HumanMessage(content=prompt)]
        response = self.llm_provider.generate(
            messages=messages,
            temperature=0.3,  # 动量分析需要较低的温度以保持一致性
            max_tokens=1024
        )
        
        # 解析响应
        signal = self.parse_response(response)
        
        return {
            "signal": signal.signal.value,
            "confidence": signal.confidence,
            "reasoning": signal.reasoning,
            "metadata": {
                "ticker": ticker,
                "agent_id": self.agent_id,
                "model_provider": model_provider
            }
        }
    
    def get_system_prompt(self) -> str:
        """获取动量交易系统提示词"""
        return """
            你是是一位专业的动量交易分析师，专注于价格动量和趋势分析。

            ## 分析框架

            1. 价格动量评估
            - 短期（5-20日）与长期（50-200日）动量比较
            - 动量加速或减速的迹象
            - 动量背离识别

            2. 趋势持续性分析
            - 趋势的阶段识别（建立期、成熟期、衰竭期）
            - 趋势强度的量化评估
            - 趋势反转的早期信号

            3. 相对强度分析
            - 与市场指数的比较
            - 与行业板块的比较
            - 相对强度的新高/新低分析

            ## 输出要求

            请提供以下分析：
            - 动量信号：强烈买入/买入/中性/卖出/强烈卖出
            - 置信度：1-100 的整数
            - 详细推理：说明你的分析逻辑

            ## 重要原则

            - 动量交易的核心是「顺势而为」
            - 关注价格行为而非基本面
            - 动量加速时跟随，动量衰竭时警惕
        """
    
    def _build_prompt(self, ticker: str, data: Dict[str, Any]) -> str:
        """构建分析提示词"""
        system_prompt = self.get_system_prompt()
        
        price_data = data.get("prices", [])
        technical_indicators = data.get("technicals", {})
        
        prompt = f"""
            {system_prompt}

            ## 目标股票
            股票代码：{ticker}

            ## 技术指标数据
            - 5日动量：{technical_indicators.get('momentum_5', 'N/A')}
            - 20日动量：{technical_indicators.get('momentum_20', 'N/A')}
            - 50日均线：{technical_indicators.get('ma_50', 'N/A')}
            - 200日均线：{technical_indicators.get('ma_200', 'N/A')}
            - RSI(14)：{technical_indicators.get('rsi_14', 'N/A')}
            - MACD：{technical_indicators.get('macd', 'N/A')}
            - ATR：{technical_indicators.get('atr', 'N/A')}

            ## 最近价格走势
            最近5日收盘价：{[p.get('close', 'N/A') for p in price_data[-5:]]}

            请基于以上数据，给出你的动量分析。
        """
        return prompt
    
    def parse_response(self, response: str) -> AgentSignal:
        """解析 LLM 响应"""
        # 实现响应解析逻辑
        # 从响应文本中提取信号、置信度和推理
        pass
```

### 步骤二：注册智能体

在 `src/agents/__init__.py` 中注册新智能体：

```python
from src.agents.momentum_trader import MomentumTraderAgent

# 注册表
AGENT_REGISTRY = {
    "momentum_trader": {
        "class": MomentumTraderAgent,
        "default_config": {
            "temperature": 0.3,
            "max_tokens": 1024
        }
    },
    # ... 其他智能体
}

def get_agent(agent_id: str, llm_provider) -> BaseAgent:
    """获取智能体实例"""
    if agent_id not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {agent_id}")
    
    config = AGENT_REGISTRY[agent_id]
    return config["class"](llm_provider)
```

### 步骤三：配置集成

在配置文件或命令行参数中添加新智能体的支持：

```yaml
# agents.yaml
available_agents:
  - id: momentum_trader
    name: 动量交易者
    style: Technical Analysis
    description: 基于价格动量和趋势分析
    enabled: true
```

## 1.3 提示词工程实践

### 提示词模板设计

良好的提示词是智能体成功的关键。以下是提示词设计的最佳实践：

```python
class PromptTemplate:
    """提示词模板管理器"""
    
    TEMPLATE_STRUCTURE = """
        ## 角色定义
        {role_definition}

        ## 任务说明
        {task_description}

        ## 分析框架
        {analysis_framework}

        ## 数据输入
        {data_context}

        ## 输出格式
        {output_format}

        ## 约束条件
        {constraints}
    """
    
    @staticmethod
    def build(
        role_definition: str,
        task_description: str,
        analysis_framework: str,
        data_context: str,
        output_format: str,
        constraints: str = ""
    ) -> str:
        """构建完整提示词"""
        return PromptTemplate.TEMPLATE_STRUCTURE.format(
            role_definition=role_definition,
            task_description=task_description,
            analysis_framework=analysis_framework,
            data_context=data_context,
            output_format=output_format,
            constraints=constraints
        )
```

### Few-shot Learning 示例

```python
FEWSHOT_EXAMPLE = """
分析以下公司股票，给出投资建议。

示例 1：
公司：Apple Inc. (AAPL)
财务数据：营收增长 8%，自由现金流充裕，PE 25
分析：优质科技公司，估值合理，增长稳定
信号：BUY，置信度：82

示例 2：
公司：XYZ Corp
财务数据：营收下降 20%，负债率高，PE 60
分析：基本面恶化，估值过高
信号：SELL，置信度：78

请分析：
公司：{ticker}
财务数据：{financial_data}
"""
```

## 1.4 智能体测试

### 单元测试框架

```python
import pytest
from src.agents.momentum_trader import MomentumTraderAgent
from src.llm.mock_provider import MockLLMProvider

class TestMomentumTraderAgent:
    """动量交易智能体测试"""
    
    @pytest.fixture
    def agent(self):
        """创建测试智能体"""
        llm_provider = MockLLMProvider()
        return MomentumTraderAgent(llm_provider)
    
    @pytest.fixture
    def sample_data(self):
        """创建测试数据"""
        return {
            "prices": [
                {"date": "2024-01-01", "close": 150.0},
                {"date": "2024-01-02", "close": 152.0},
                # ... 更多数据
            ],
            "technicals": {
                "momentum_5": 2.5,
                "momentum_20": 8.3,
                "ma_50": 148.0,
                "ma_200": 140.0,
                "rsi_14": 65.0,
                "macd": 1.2,
                "atr": 3.5
            }
        }
    
    def test_analyze_returns_valid_signal(self, agent, sample_data):
        """测试分析返回有效信号"""
        result = agent.analyze("AAPL", sample_data)
        
        assert result["signal"] in ["BUY", "SELL", "HOLD"]
        assert 1 <= result["confidence"] <= 100
        assert "reasoning" in result
        assert len(result["reasoning"]) > 50  # 推理应该足够详细
    
    def test_confidence_calibration(self, agent, sample_data):
        """测试置信度校准"""
        # 运行多次分析，置信度应该相对稳定
        results = [agent.analyze("AAPL", sample_data) for _ in range(5)]
        confidences = [r["confidence"] for r in results]
        
        # 置信度方差应该较小
        assert max(confidences) - min(confidences) < 20
```

### 集成测试

```python
class TestAgentIntegration:
    """智能体集成测试"""
    
    def test_agent_in_workflow(self):
        """测试智能体在完整工作流中的表现"""
        # 模拟完整工作流
        from src.graph.workflow import create_workflow
        
        workflow = create_workflow(
            selected_agents=["momentum_trader", "fundamental_analyst"]
        )
        
        result = workflow.run(ticker="AAPL", start_date="2024-01-01")
        
        assert result["status"] == "success"
        assert "momentum_trader" in result["signals"]
```

## 1.5 最佳实践

### 智能体设计原则

**单一职责**：每个智能体应该专注于特定的分析维度，避免功能过度膨胀。

**一致性输出**：所有智能体的输出格式应该保持一致，便于后续处理。

**可解释性**：智能体的推理过程应该清晰可追溯，便于理解和调试。

**可测试性**：智能体应该易于进行单元测试和集成测试。

### 常见问题解决

**响应不一致问题**：使用较低的温度设置（0.1-0.3），增加明确的输出格式约束。

**推理质量不佳**：提供更详细的分析框架和数据上下文，使用 few-shot examples。

**处理时间过长**：优化提示词长度，考虑缓存机制，使用流式输出。

## 1.6 练习题

### 练习 1.1：创建主题智能体

**任务**：创建一个基于 ESG（环境、社会责任、公司治理）评分的智能体。

**要求**：智能体应该能够根据 ESG 数据给出投资建议，输出符合标准信号格式，包含完整的测试用例。

### 练习 1.2：提示词优化

**任务**：优化现有智能体的提示词，提高输出质量。

**步骤**：首先分析现有提示词的问题，然后设计改进方案，最后通过 A/B 测试比较优化效果。

### 练习 1.3：智能体对比实验

**任务**：比较新智能体与现有智能体的表现。

**设计**：选择相同的市场数据和时间段，分别使用新智能体和现有智能体进行分析，比较信号差异和置信度分布。
