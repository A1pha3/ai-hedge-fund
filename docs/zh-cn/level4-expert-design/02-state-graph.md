# 第二章：状态图深度剖析

## 学习目标

完成本章节学习后，你将能够深入理解 LangGraph 状态图的工作原理，掌握状态定义和状态更新的机制，学会设计复杂的多智能体协作工作流，以及能够调试和优化状态图执行。预计学习时间为 3-4 小时。

## 2.1 LangGraph 核心概念

### 状态图基础

状态图（State Graph）是 LangGraph 的核心抽象，它将工作流建模为有向图，其中节点代表计算单元，边代表状态流动的方向。

**核心组件**：

节点（Node）是图中的基本计算单元，每个节点执行特定的功能并返回更新到状态。边（Edge）连接节点，定义状态流动的方向。普通边表示确定性的流动，条件边根据状态值决定下一个执行的节点。状态（State）是贯穿整个工作流的数据结构，包含所有分析相关的信息。检查点（Checkpoint）是工作流执行过程中的状态快照，用于状态恢复和调试。

```python
from langgraph.graph import StateGraph
from typing import TypedDict, Annotated, List
from langchain_core.messages import BaseMessage
from operator import add

# 定义状态类型
class AgentState(TypedDict):
    """分析状态定义"""
    messages: Annotated[List[BaseMessage], add]  # 消息历史
    data: Annotated[Dict[str, Any], merge_dicts]  # 分析数据
    signals: Dict[str, AgentSignal]  # 智能体信号
    metadata: Dict[str, Any]  # 元数据
    intermediate_values: Dict[str, Any]  # 中间值
```

### 状态更新机制

LangGraph 使用注释器（Annotation）来定义状态字段的更新策略。

**更新策略**：

`add` 用于列表类型，新值追加到列表末尾。

```python
messages: Annotated[List[BaseMessage], add]
```

`merge_dicts` 用于字典类型，新字典与现有字典合并。

```python
data: Annotated[Dict[str, Any], merge_dicts]
```

`operator.assign` 用于直接赋值，覆盖现有值。

```python
result: Annotated[Any, operator.assign]
```

## 2.2 系统状态图详细设计

### 状态定义

```python
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from enum import Enum
from pydantic import BaseModel
import operator

class AnalysisStatus(str, Enum):
    """分析状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class RiskLevel(str, Enum):
    """风险等级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"

class AgentSignal(BaseModel):
    """智能体信号"""
    signal: str  # BUY/SELL/HOLD
    confidence: int  # 0-100
    reasoning: str
    metadata: Dict[str, Any] = {}

class PortfolioDecision(BaseModel):
    """投资组合决策"""
    action: str  # buy/sell/short/cover/hold
    quantity: int
    confidence: int
    reasoning: str

class AgentState(TypedDict):
    """完整分析状态"""
    
    # 消息历史（追加）
    messages: Annotated[List[BaseMessage], add]
    
    # 分析配置（合并）
    config: Annotated[Dict[str, Any], merge_dicts]
    
    # 分析数据（合并）
    data: Annotated[Dict[str, Any], merge_dicts]
    
    # 智能体信号（合并）
    signals: Annotated[Dict[str, AgentSignal], merge_dicts]
    
    # 风险评估（合并）
    risk_assessment: Annotated[Dict[str, Any], merge_dicts]
    
    # 投资组合决策（覆盖）
    portfolio_decision: Annotated[Optional[PortfolioDecision], operator.assign]
    
    # 分析状态（覆盖）
    status: Annotated[AnalysisStatus, operator.assign]
    
    # 中间值（合并）
    intermediate_values: Annotated[Dict[str, Any], merge_dicts]
    
    # 错误信息（覆盖）
    error: Annotated[Optional[str], operator.assign]
```

### 节点实现

```python
from langchain_core.runnables import Runnable

class AnalysisNodes:
    """分析节点集合"""
    
    @staticmethod
    def start_node(state: AgentState) -> AgentState:
        """
        起始节点
        
        职责：
        1. 验证输入配置
        2. 初始化状态
        3. 触发数据预取
        """
        # 验证配置
        if not state.get("config", {}).get("tickers"):
            return {"error": "No tickers specified", "status": AnalysisStatus.FAILED}
        
        # 初始化状态
        initial_messages = [
            SystemMessage(content="Starting analysis workflow...")
        ]
        
        # 获取配置
        config = state["config"]
        
        return {
            "messages": initial_messages,
            "status": AnalysisStatus.RUNNING,
            "intermediate_values": {
                "start_time": datetime.now().isoformat(),
                "selected_agents": config.get("analysts", [])
            }
        }
    
    @staticmethod
    def warren_buffett_agent(state: AgentState) -> AgentState:
        """
        沃伦·巴菲特智能体节点
        
        职责：
        1. 获取财务数据
        2. 执行价值分析
        3. 生成交易信号
        """
        ticker = state["config"]["tickers"][0]  # 简化示例
        data = state.get("data", {})
        
        try:
            # 获取财务数据
            financial_data = DataService.get_financial_metrics(ticker)
            
            # 执行分析
            signal = WarrenBuffettAgent.analyze(
                ticker=ticker,
                data={
                    "financial_metrics": financial_data,
                    "prices": data.get("prices", [])
                }
            )
            
            return {
                "signals": {"warren_buffett": signal},
                "messages": [AIMessage(content=f"Buffett analysis complete: {signal.signal}")]
            }
        except Exception as e:
            return {
                "error": f"Buffett agent failed: {str(e)}",
                "signals": {"warren_buffett": None}
            }
    
    @staticmethod
    def risk_management_agent(state: AgentState) -> AgentState:
        """
        风险管理节点
        
        职责：
        1. 汇总所有智能体信号
        2. 评估整体风险
        3. 计算推荐仓位
        """
        signals = state.get("signals", {})
        portfolio = state.get("data", {}).get("portfolio", {})
        
        # 汇总信号
        signal_summary = RiskManager.summarize_signals(signals)
        
        # 风险评估
        risk_assessment = RiskManager.assess_risk(
            signals=signals,
            portfolio=portfolio,
            market_data=state.get("data", {}).get("market_data", {})
        )
        
        # 计算仓位
        position_limit = RiskManager.calculate_position_limit(
            risk_level=risk_assessment["level"],
            portfolio_value=portfolio.get("total_value", 100000)
        )
        
        return {
            "risk_assessment": {
                **risk_assessment,
                "position_limit": position_limit
            },
            "messages": [AIMessage(content=f"Risk assessment complete: {risk_assessment['level']}")]
        }
    
    @staticmethod
    def portfolio_manager(state: AgentState) -> AgentState:
        """
        投资组合管理节点
        
        职责：
        1. 综合所有输入
        2. 生成最终决策
        3. 格式化输出
        """
        signals = state.get("signals", {})
        risk = state.get("risk_assessment", {})
        config = state.get("config", {})
        
        # 综合决策
        decision = PortfolioManager.make_decision(
            signals=signals,
            risk_assessment=risk,
            constraints=config.get("constraints", {})
        )
        
        return {
            "portfolio_decision": decision,
            "status": AnalysisStatus.COMPLETED,
            "messages": [AIMessage(content=f"Portfolio decision: {decision.action}")]
        }
```

### 边定义

```python
def create_workflow() -> StateGraph:
    """创建分析工作流"""
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("start", AnalysisNodes.start_node)
    workflow.add_node("warren_buffett", AnalysisNodes.warren_buffett_agent)
    workflow.add_node("charlie_munger", AnalysisNodes.charlie_munger_agent)
    workflow.add_node("technical_analyst", AnalysisNodes.technical_analyst_agent)
    workflow.add_node("risk_management", AnalysisNodes.risk_management_agent)
    workflow.add_node("portfolio_manager", AnalysisNodes.portfolio_manager)
    
    # 设置入口
    workflow.set_entry_point("start")
    
    # 添加并行边（从 start 到所有智能体）
    workflow.add_edge("start", "warren_buffett")
    workflow.add_edge("start", "charlie_munger")
    workflow.add_edge("start", "technical_analyst")
    
    # 添加汇聚边（从所有智能体到风险管理）
    workflow.add_edge("warren_buffett", "risk_management")
    workflow.add_edge("charlie_munger", "risk_management")
    workflow.add_edge("technical_analyst", "risk_management")
    
    # 添加决策边（从风险管理到投资组合管理）
    workflow.add_edge("risk_management", "portfolio_manager")
    
    # 设置出口
    workflow.set_finish_point("portfolio_manager")
    
    return workflow
```

## 2.3 条件分支与动态工作流

### 条件边实现

```python
from langgraph.graph import END

class ConditionalEdges:
    """条件边定义"""
    
    @staticmethod
    def should_continue_after_risk(state: AgentState) -> str:
        """
        风险评估后决定下一步
        
        决策逻辑：
        - EXTREME 风险：返回 END，不执行交易
        - HIGH 风险：降低仓位后继续
        - MEDIUM/LOW 风险：正常继续
        """
        risk_level = state.get("risk_assessment", {}).get("level", "medium")
        
        if risk_level == "EXTREME":
            return "abort"  # 自定义终止处理
        
        if risk_level == "HIGH":
            return "reduced_position"  # 降低仓位分支
        
        return "continue"  # 正常继续
    
    @staticmethod
    def select_agents(state: AgentState) -> List[str]:
        """
        根据配置选择要执行的智能体
        
        返回要执行的智能体名称列表
        """
        selected = state.get("config", {}).get("analysts", [])
        
        # 过滤可用的智能体
        available_agents = ["warren_buffett", "charlie_munger", "technical_analyst"]
        
        return [a for a in available_agents if a in selected]

# 使用条件边
def create_conditional_workflow() -> StateGraph:
    workflow = StateGraph(AgentState)
    
    # ... 添加节点 ...
    
    # 添加条件边
    workflow.add_conditional_edges(
        "risk_management",
        ConditionalEdges.should_continue_after_risk,
        {
            "continue": "portfolio_manager",
            "reduced_position": "position_adjuster",
            "abort": "abort_handler"
        }
    )
    
    return workflow
```

### 动态节点生成

```python
def create_dynamic_workflow(config: WorkflowConfig) -> StateGraph:
    """
    根据配置动态创建工作流
    
    支持：
    - 动态选择要执行的智能体
    - 动态配置边连接
    - 条件性包含/排除节点
    """
    workflow = StateGraph(AgentState)
    
    # 添加固定节点
    workflow.add_node("start", AnalysisNodes.start_node)
    workflow.add_node("risk_management", AnalysisNodes.risk_management_agent)
    workflow.add_node("portfolio_manager", AnalysisNodes.portfolio_manager)
    
    # 动态添加智能体节点
    agent_factory = AgentFactory()
    
    for agent_id in config.selected_agents:
        agent_node = agent_factory.create_node(agent_id)
        workflow.add_node(agent_id, agent_node)
        
        # 连接到风险管理
        workflow.add_edge(agent_id, "risk_management")
    
    # 设置入口和出口
    workflow.set_entry_point("start")
    
    # 动态连接入口到智能体
    for agent_id in config.selected_agents:
        workflow.add_edge("start", agent_id)
    
    workflow.add_edge("risk_management", "portfolio_manager")
    workflow.set_finish_point("portfolio_manager")
    
    return workflow
```

## 2.4 检查点与状态恢复

### 检查点配置

```python
from langgraph.checkpoint import MemorySaver, CheckpointSaver

def create_workflow_with_checkpoints() -> StateGraph:
    """创建带检查点的工作流"""
    
    # 使用内存检查点存储
    checkpointer = MemorySaver()
    
    workflow = StateGraph(AgentState)
    
    # ... 添加节点和边 ...
    
    # 编译时指定检查点
    compiled = workflow.compile(
        checkpointer=checkpointer,
        debug=True  # 启用调试模式
    )
    
    return compiled
```

### 状态恢复

```python
class CheckpointManager:
    """检查点管理器"""
    
    def __init__(self, checkpointer: CheckpointSaver):
        self.checkpointer = checkpointer
    
    def save_checkpoint(
        self,
        thread_id: str,
        state: AgentState,
        checkpoint_id: str = None
    ):
        """保存检查点"""
        config = {"configurable": {"thread_id": thread_id}}
        
        self.checkpointer.put(
            config=config,
            checkpoint={"state": state},
            checkpoint_id=checkpoint_id
        )
    
    def restore_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str = None
    ) -> AgentState:
        """恢复检查点"""
        config = {"configurable": {"thread_id": thread_id}}
        
        if checkpoint_id is None:
            # 获取最新的检查点
            history = self.checkpointer.get_history(config)
            if history:
                checkpoint_id = history[0].id
        
        if checkpoint_id:
            checkpoint = self.checkpointer.get(
                config=config,
                checkpoint_id=checkpoint_id
            )
            if checkpoint:
                return checkpoint["state"]
        
        return None
    
    def list_checkpoints(self, thread_id: str) -> List[Dict]:
        """列出所有检查点"""
        config = {"configurable": {"thread_id": thread_id}}
        history = self.checkpointer.get_history(config)
        
        return [
            {
                "id": cp.id,
                "timestamp": cp.metadata.get("timestamp"),
                "status": cp.checkpoint.get("status")
            }
            for cp in history
        ]
```

## 2.5 调试与监控

### 调试工具

```python
class WorkflowDebugger:
    """工作流调试器"""
    
    def __init__(self, workflow: StateGraph):
        self.workflow = workflow
        self.execution_log = []
    
    def trace_execution(
        self,
        initial_state: AgentState,
        thread_id: str = "debug"
    ) -> Dict:
        """跟踪执行过程"""
        config = {"configurable": {"thread_id": thread_id}}
        
        # 使用 visualize 获取执行图
        graph = self.workflow.get_graph()
        
        # 记录每一步
        current_state = initial_state
        steps = []
        
        for step in range(100):  # 最多 100 步
            # 获取下一个要执行的节点
            next_step = self._get_next_step(current_state)
            
            if next_step is None:
                break
            
            # 记录步骤
            step_info = {
                "step": step + 1,
                "node": next_step,
                "input_state": current_state.copy()
            }
            
            # 执行节点
            node_func = self.workflow.nodes[next_step]
            current_state = node_func.invoke(current_state)
            
            step_info["output_state"] = current_state.copy()
            steps.append(step_info)
            
            # 检查是否完成
            if current_state.get("status") in ["completed", "failed"]:
                break
        
        return {
            "initial_state": initial_state,
            "final_state": current_state,
            "steps": steps,
            "total_steps": len(steps)
        }
    
    def _get_next_step(self, state: AgentState) -> Optional[str]:
        """获取下一步要执行的节点"""
        # 根据当前状态确定下一步
        # 简化实现：检查状态中的标记
        if not state.get("started"):
            return "start"
        
        # 检查是否所有智能体都已完成
        agents = state.get("config", {}).get("analysts", [])
        signals = state.get("signals", {})
        
        completed_agents = [a for a in agents if a in signals]
        
        if len(completed_agents) < len(agents):
            # 返回未完成的智能体
            for agent in agents:
                if agent not in signals:
                    return agent
        
        # 检查风险管理
        if not state.get("risk_assessment"):
            return "risk_management"
        
        # 检查投资组合管理
        if not state.get("portfolio_decision"):
            return "portfolio_manager"
        
        return None  # 完成
```

### 性能监控

```python
class WorkflowMonitor:
    """工作流性能监控"""
    
    def __init__(self):
        self.metrics = defaultdict(list)
    
    def monitor_execution(self, func):
        """执行监控装饰器"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            
            try:
                result = func(*args, **kwargs)
                
                duration = time.perf_counter() - start_time
                self.metrics["success"].append({
                    "timestamp": datetime.now(),
                    "duration": duration
                })
                
                return result
            except Exception as e:
                duration = time.perf_counter() - start_time
                self.metrics["failure"].append({
                    "timestamp": datetime.now(),
                    "duration": duration,
                    "error": str(e)
                })
                raise
        
        return wrapper
    
    def get_performance_report(self) -> Dict:
        """生成性能报告"""
        report = {}
        
        for metric_name, values in self.metrics.items():
            if not values:
                continue
            
            durations = [v["duration"] for v in values]
            
            report[metric_name] = {
                "count": len(values),
                "mean_duration": statistics.mean(durations),
                "median_duration": statistics.median(durations),
                "p95_duration": sorted(durations)[int(len(durations) * 0.95)],
                "max_duration": max(durations),
                "min_duration": min(durations)
            }
        
        return report
```

## 2.6 练习题

### 练习 2.1：状态图设计

**任务**：设计一个新的分析工作流状态图。

**要求**：定义完整的 AgentState 类型，实现至少 4 个智能体节点，实现条件分支逻辑，添加检查点支持。

### 练习 2.2：调试工具开发

**任务**：开发一个可视化的工作流调试工具。

**步骤**：首先实现执行跟踪功能，然后实现状态比较功能，接着实现性能指标收集，最后生成可视化报告。

### 练习 2.3：性能优化

**任务**：分析和优化工作流的执行性能。

**步骤**：首先建立性能基准测试，然后识别瓶颈节点，接着实现并行优化，最后验证优化效果。
