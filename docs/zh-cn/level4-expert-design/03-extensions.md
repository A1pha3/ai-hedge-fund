# 第三章：扩展模式与最佳实践

## 学习目标

完成本章节学习后，你将能够掌握系统的可扩展性设计模式，学会如何添加新智能体、新数据源和新分析功能，理解代码组织和项目结构的最佳实践，以及能够遵循系统既定的扩展规范进行开发。预计学习时间为 3-4 小时。

## 3.1 扩展架构设计

### 插件系统架构

系统采用插件化架构设计，支持通过扩展来增加新功能。

**扩展点定义**：

智能体扩展点允许添加新的投资风格智能体。数据源扩展点允许集成新的金融数据提供商。工作流扩展点允许修改或增强分析流程。输出扩展点允许添加新的输出格式和报告类型。

**插件接口**：

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Type

class AgentPlugin(ABC):
    """智能体插件接口"""
    
    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """插件唯一标识"""
        pass
    
    @property
    @abstractmethod
    def plugin_name(self) -> str:
        """插件显示名称"""
        pass
    
    @property
    @abstractmethod
    def plugin_version(self) -> str:
        """插件版本"""
        pass
    
    @abstractmethod
    def get_agent_class(self) -> Type[BaseAgent]:
        """返回智能体类"""
        pass
    
    @abstractmethod
    def get_default_config(self) -> Dict[str, Any]:
        """返回默认配置"""
        pass

class DataSourcePlugin(ABC):
    """数据源插件接口"""
    
    @property
    @abstractmethod
    def source_id(self) -> str:
        """数据源标识"""
        pass
    
    @property
    @abstractmethod
    def source_name(self) -> str:
        """数据源名称"""
        pass
    
    @abstractmethod
    async def get_provider(self) -> BaseDataProvider:
        """返回数据提供者实例"""
        pass

class OutputPlugin(ABC):
    """输出插件接口"""
    
    @property
    @abstractmethod
    def output_id(self) -> str:
        """输出格式标识"""
        pass
    
    @property
    @abstractmethod
    def output_name(self) -> str:
        """输出格式名称"""
        pass
    
    @abstractmethod
    def format(self, result: AnalysisResult) -> Any:
        """格式化结果"""
        pass
```

### 插件注册系统

```python
class PluginRegistry:
    """插件注册中心"""
    
    def __init__(self):
        self._agents: Dict[str, AgentPlugin] = {}
        self._data_sources: Dict[str, DataSourcePlugin] = {}
        self._outputs: Dict[str, OutputPlugin] = {}
    
    def register_agent(self, plugin: AgentPlugin):
        """注册智能体插件"""
        if plugin.plugin_id in self._agents:
            raise ValueError(f"Agent {plugin.plugin_id} already registered")
        self._agents[plugin.plugin_id] = plugin
        print(f"Registered agent: {plugin.plugin_name} v{plugin.plugin_version}")
    
    def register_data_source(self, plugin: DataSourcePlugin):
        """注册数据源插件"""
        if plugin.source_id in self._data_sources:
            raise ValueError(f"Data source {plugin.source_id} already registered")
        self._data_sources[plugin.source_id] = plugin
        print(f"Registered data source: {plugin.source_name}")
    
    def register_output(self, plugin: OutputPlugin):
        """注册输出插件"""
        if plugin.output_id in self._outputs:
            raise ValueError(f"Output format {plugin.output_id} already registered")
        self._outputs[plugin.output_id] = plugin
        print(f"Registered output format: {plugin.output_name}")
    
    def get_agent(self, agent_id: str) -> AgentPlugin:
        """获取智能体插件"""
        return self._agents.get(agent_id)
    
    def get_data_source(self, source_id: str) -> DataSourcePlugin:
        """获取数据源插件"""
        return self._data_sources.get(source_id)
    
    def get_output(self, output_id: str) -> OutputPlugin:
        """获取输出插件"""
        return self._outputs.get(output_id)
    
    def list_agents(self) -> List[Dict[str, str]]:
        """列出所有智能体"""
        return [
            {"id": p.plugin_id, "name": p.plugin_name, "version": p.plugin_version}
            for p in self._agents.values()
        ]
    
    def load_plugins_from_entry_points(self, group: str):
        """从 entry points 加载插件"""
        try:
            import pkg_resources
            for entry_point in pkg_resources.iter_entry_points(group):
                plugin_class = entry_point.load()
                plugin = plugin_class()
                self.register_plugin(plugin)
        except ImportError:
            print("pkg_resources not available")
```

## 3.2 添加新智能体

### 智能体开发模板

```python
# src/agents/templates/new_agent.py

"""
新智能体模板

按照此模板创建新的智能体插件。
"""

from typing import Dict, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from src.agents.base import BaseAgent
from src.agents.signal import AgentSignal, TradingSignal
from src.plugins import AgentPlugin

class NewStyleAgent(BaseAgent):
    """
    新风格智能体
    
    在此添加智能体的详细描述。
    """
    
    agent_id = "new_style_agent"  # 唯一标识
    agent_name = "新风格分析者"
    agent_description = """
        在此添加智能体的详细描述。
    """
    investment_style = "New Style"  # 投资风格分类
    
    def __init__(self, llm_provider, config: Dict[str, Any] = None):
        self.llm_provider = llm_provider
        self.config = config or {}
    
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
            data: 分析数据
            model_provider: LLM 提供商
            
        Returns:
            包含 signal, confidence, reasoning 的字典
        """
        # 1. 准备数据
        prepared_data = self._prepare_data(ticker, data)
        
        # 2. 构建提示词
        prompt = self._build_prompt(ticker, prepared_data)
        
        # 3. 调用 LLM
        messages = [HumanMessage(content=prompt)]
        response = self.llm_provider.generate(
            messages=messages,
            temperature=self.config.get("temperature", 0.7),
            max_tokens=self.config.get("max_tokens", 1024)
        )
        
        # 4. 解析响应
        signal = self._parse_response(response)
        
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
        """获取系统提示词"""
        return """
            你是一位专业的[投资风格]分析师。

            ## 分析框架
            1. [分析维度1]
            2. [分析维度2]
            3. [分析维度3]

            ## 输出要求
            - 信号：BUY/SELL/HOLD
            - 置信度：1-100
            - 推理：详细说明
        """
    
    def _prepare_data(self, ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """准备分析数据"""
        # 实现数据准备逻辑
        pass
    
    def _build_prompt(self, ticker: str, data: Dict[str, Any]) -> str:
        """构建分析提示词"""
        system_prompt = self.get_system_prompt()
        # 添加具体数据
        pass
    
    def _parse_response(self, response: str) -> AgentSignal:
        """解析 LLM 响应"""
        # 实现响应解析
        pass


class NewStyleAgentPlugin(AgentPlugin):
    """新风格智能体插件"""
    
    @property
    def plugin_id(self) -> str:
        return "new_style_agent"
    
    @property
    def plugin_name(self) -> str:
        return "新风格分析者"
    
    @property
    def plugin_version(self) -> str:
        return "1.0.0"
    
    def get_agent_class(self):
        return NewStyleAgent
    
    def get_default_config(self) -> Dict[str, Any]:
        return {
            "temperature": 0.7,
            "max_tokens": 1024,
            "enabled": True
        }
```

### 插件注册

```python
# src/agents/plugins.py

# 自动注册插件
def register_plugins(registry: PluginRegistry):
    """注册所有内置插件"""
    
    # 内置智能体
    from src.agents.warren_buffett import BuffettAgent, BuffettAgentPlugin
    from src.agents.technical_analyst import TechnicalAnalystAgent, TechnicalAnalystPlugin
    
    registry.register_agent(BuffettAgentPlugin())
    registry.register_agent(TechnicalAnalystPlugin())
    
    # ... 其他内置插件


# setup.py 中的 entry points 配置
setup(
    ...
    entry_points={
        "ai_hedge_fund.agents": [
            "warren_buffett = src.agents.warren_buffett:BuffettAgentPlugin",
            "technical_analyst = src.agents.technical_analyst:TechnicalAnalystPlugin",
        ],
        "ai_hedge_fund.data_sources": [
            "financial_datasets = src.data.financial_datasets:FinancialDatasetsPlugin",
        ]
    }
)
```

## 3.3 添加新数据源

### 数据源开发模板

```python
# src/data/providers/new_provider.py

"""
新数据提供商模板

按照此模板集成新的金融数据提供商。
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import aiohttp
from src.data.providers.base import BaseDataProvider
from src.plugins import DataSourcePlugin

class NewProvider(BaseDataProvider):
    """
    新数据提供商
    
    在此添加提供商描述。
    """
    
    def __init__(self, api_key: str, base_url: str = "https://api.example.com"):
        super().__init__("new_provider", priority=100)
        self.api_key = api_key
        self.base_url = base_url
        self.session = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取 HTTP 会话"""
        if self.session is None or self.session.closed:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            self.session = aiohttp.ClientSession(headers=headers)
        return self.session
    
    async def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """获取价格数据"""
        session = await self._get_session()
        
        url = f"{self.base_url}/prices"
        params = {"symbol": ticker, "from": start_date, "to": end_date}
        
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return self._transform_prices(data)
            else:
                raise APIError(f"NewProvider error: {response.status}")
    
    async def get_financial_metrics(
        self,
        ticker: str,
        end_date: str
    ) -> Dict[str, Any]:
        """获取财务指标"""
        pass
    
    async def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """获取公司新闻"""
        pass
    
    def _transform_prices(self, raw_data: Any) -> List[Dict[str, Any]]:
        """转换原始数据为标准格式"""
        # 实现数据转换逻辑
        pass
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/health") as response:
                return response.status == 200
        except Exception:
            return False
    
    def rate_limit_info(self) -> Dict[str, Any]:
        """速率限制信息"""
        return {
            "requests_per_minute": 100,
            "requests_per_day": 10000,
            "backoff_strategy": "exponential"
        }
    
    async def close(self):
        """关闭会话"""
        if self.session and not self.session.closed:
            await self.session.close()


class NewProviderPlugin(DataSourcePlugin):
    """新数据提供商插件"""
    
    @property
    def source_id(self) -> str:
        return "new_provider"
    
    @property
    def source_name(self) -> str:
        return "New Data Provider"
    
    def get_provider(self) -> BaseDataProvider:
        from src.config import get_config
        config = get_config()
        api_key = config.get("NEW_PROVIDER_API_KEY")
        return NewProvider(api_key)
```

## 3.4 代码组织规范

### 项目结构

```
ai-hedge-fund/
├── src/
│   ├── agents/                  # 智能体模块
│   │   ├── __init__.py
│   │   ├── base.py             # 基类定义
│   │   ├── signal.py           # 信号模型
│   │   ├── plugins.py          # 插件注册
│   │   ├── value/             # 价值投资智能体
│   │   ├── growth/             # 成长投资智能体
│   │   ├── technical/          # 技术分析智能体
│   │   └── macro/             # 宏观策略智能体
│   │
│   ├── data/                   # 数据模块
│   │   ├── __init__.py
│   │   ├── providers/         # 数据提供商
│   │   ├── cache.py           # 缓存实现
│   │   └── models.py          # 数据模型
│   │
│   ├── graph/                  # 工作流模块
│   │   ├── __init__.py
│   │   ├── state.py          # 状态定义
│   │   └── workflow.py        # 工作流定义
│   │
│   ├── llm/                    # LLM 集成模块
│   │   ├── __init__.py
│   │   ├── providers/         # LLM 提供商
│   │   └── prompts/           # 提示词模板
│   │
│   ├── backtesting/            # 回测模块
│   │   ├── __init__.py
│   │   ├── engine.py          # 回测引擎
│   │   ├── portfolio.py       # 投资组合
│   │   └── metrics.py         # 绩效指标
│   │
│   ├── risk/                   # 风险管理模块
│   │   ├── __init__.py
│   │   ├── models.py          # 风险模型
│   │   └── manager.py         # 风险管理器
│   │
│   ├── api/                    # API 接口
│   │   ├── __init__.py
│   │   ├── routes.py          # 路由定义
│   │   └── schemas.py         # 请求/响应模型
│   │
│   ├── cli/                    # 命令行接口
│   │   ├── __init__.py
│   │   ├── main.py            # 主入口
│   │   └── commands/          # 命令实现
│   │
│   ├── utils/                  # 工具函数
│   │   ├── __init__.py
│   │   ├── logging.py         # 日志配置
│   │   └── validation.py       # 验证工具
│   │
│   └── config.py               # 配置管理
│
├── tests/                       # 测试目录
│   ├── __init__.py
│   ├── unit/                   # 单元测试
│   ├── integration/             # 集成测试
│   └── fixtures/               # 测试数据
│
├── config/                      # 配置目录
│   ├── prompts/                # 提示词模板
│   │   ├── buffett.yaml
│   │   ├── graham.yaml
│   │   └── ...
│   ├── agents.yaml            # 智能体配置
│   └── risk_limits.yaml       # 风险限制配置
│
├── docs/                        # 文档
│   ├── zh-cn/                  # 中文文档
│   └── en/                     # 英文文档
│
├── app/                         # Web 应用
│   ├── backend/                # FastAPI 后端
│   └── frontend/               # React 前端
│
├── scripts/                     # 运维脚本
│   ├── deploy.sh
│   ├── backup.sh
│   └── migrate.sh
│
├── tests/
│   ├── conftest.py
│   ├── test_agents/
│   ├── test_data/
│   └── test_workflow/
│
├── pyproject.toml
├── README.md
├── LICENSE
└── .env.example
```

### 编码规范

```python
# 1. 类型注解规范
from typing import Dict, List, Any, Optional, TypeVar

T = TypeVar('T')

def process_data(
    data: Dict[str, Any],
    options: Optional[Dict[str, Any]] = None,
    callback: Optional[callable] = None
) -> List[T]:
    """
    处理数据
    
    Args:
        data: 输入数据字典
        options: 处理选项
        callback: 回调函数
        
    Returns:
        处理后的列表
        
    Raises:
        ValueError: 当数据格式无效时
        ProcessingError: 当处理失败时
    """
    pass

# 2. 错误处理规范
class CustomError(Exception):
    """自定义错误基类"""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        details: Dict[str, Any] = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}

# 3. 日志规范
import logging

logger = logging.getLogger(__name__)

def process_sensitive_operation(data: Dict[str, Any]) -> Dict[str, Any]:
    """处理敏感操作"""
    logger.info(
        "Starting sensitive operation",
        extra={
            "operation_type": "sensitive",
            "data_summary": {"keys": list(data.keys())}
        }
    )
    
    try:
        result = _do_processing(data)
        logger.info("Operation completed successfully")
        return result
    except Exception as e:
        logger.error(
            f"Operation failed: {str(e)}",
            exc_info=True,
            extra={"error_type": type(e).__name__}
        )
        raise
```

## 3.5 测试规范

### 测试金字塔

```
                    ┌─────────────┐
                    │   E2E测试    │  ← 端到端测试，数量最少
                    │    5%      │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │  集成测试   │  ← 模块间协作
                    │    20%    │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │  单元测试   │  ← 核心逻辑，数量最多
                    │    75%    │
                    └─────────────┘
```

### 测试示例

```python
# tests/test_agents/test_new_agent.py

import pytest
from unittest.mock import Mock, AsyncMock, patch
from src.agents.new_agent import NewStyleAgent

class TestNewStyleAgent:
    """新风格智能体测试"""
    
    @pytest.fixture
    def agent(self):
        """创建测试智能体"""
        llm_provider = Mock()
        llm_provider.generate = AsyncMock(return_value="BUY 85 详细推理...")
        
        config = {"temperature": 0.7, "max_tokens": 1024}
        return NewStyleAgent(llm_provider, config)
    
    @pytest.fixture
    def sample_data(self):
        """创建测试数据"""
        return {
            "prices": [
                {"date": "2024-01-01", "close": 150.0},
                {"date": "2024-01-02", "close": 152.0},
            ],
            "financial_metrics": {
                "revenue_growth": 0.15,
                "pe_ratio": 25.0
            }
        }
    
    @pytest.mark.asyncio
    async def test_analyze_returns_valid_signal(self, agent, sample_data):
        """测试分析返回有效信号"""
        result = await agent.analyze("AAPL", sample_data)
        
        assert result["signal"] in ["BUY", "SELL", "HOLD"]
        assert 1 <= result["confidence"] <= 100
        assert "reasoning" in result
        assert len(result["reasoning"]) > 50
    
    @pytest.mark.asyncio
    async def test_confidence_calibration(self, agent, sample_data):
        """测试置信度校准"""
        # 运行多次，置信度应该相对稳定
        results = []
        for _ in range(5):
            result = await agent.analyze("AAPL", sample_data)
            results.append(result["confidence"])
        
        # 置信度方差应该较小
        assert max(results) - min(results) < 20
    
    @pytest.mark.asyncio
    async def test_invalid_ticker(self, agent, sample_data):
        """测试无效股票代码"""
        with pytest.raises(ValueError):
            await agent.analyze("", sample_data)
    
    def test_system_prompt_structure(self, agent):
        """测试系统提示词结构"""
        prompt = agent.get_system_prompt()
        
        assert "分析框架" in prompt
        assert "输出要求" in prompt
        assert "BUY" in prompt
        assert "SELL" in prompt
        assert "HOLD" in prompt
```

## 3.6 练习题

### 练习 3.1：插件开发

**任务**：开发一个新的智能体插件。

**要求**：实现完整的 AgentPlugin 接口，包含单元测试和集成测试，编写插件文档。

### 练习 3.2：代码审查

**任务**：对现有代码进行审查并提出改进建议。

**步骤**：首先审查代码组织和结构规范，然后检查测试覆盖率和质量，接着评估文档完整性，最后编写审查报告。

### 练习 3.3：性能测试框架

**任务**：建立系统的性能测试框架。

**要求**：定义性能测试用例，实现性能数据收集，生成性能基准报告。
