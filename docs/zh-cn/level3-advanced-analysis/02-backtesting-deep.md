# 第二章：回测系统深度解析

## 学习目标

完成本章节学习后，你将能够深入理解回测引擎的实现细节，掌握交易成本模型的精确建模方法，学会绩效归因分析的技术，以及能够识别和避免回测中的常见陷阱。预计学习时间为 2-3 小时。

## 2.1 回测引擎核心实现

### BacktestEngine 类结构

回测引擎是整个回测系统的核心组件，负责协调数据获取、策略执行和绩效计算等步骤。

```python
class BacktestEngine:
    """回测引擎"""
    
    def __init__(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        initial_capital: float = 100000,
        rebalance_frequency: str = "monthly",
        commission_rate: float = 0.001,
        slippage_model: SlippageModel = None
    ):
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.rebalance_frequency = rebalance_frequency
        self.commission_rate = commission_rate
        self.slippage_model = slippage_model or DefaultSlippageModel()
        
        # 状态初始化
        self.portfolio = Portfolio(initial_capital)
        self.trades = []
        self.portfolio_values = []
        self.performance_metrics = PerformanceMetrics()
    
    def run(self) -> BacktestResult:
        """执行回测"""
        # 1. 预取数据
        self._prefetch_data()
        
        # 2. 获取交易日历
        trading_days = self._get_trading_days()
        
        # 3. 遍历交易日
        for current_date in trading_days:
            self._process_date(current_date)
        
        # 4. 计算绩效指标
        self._compute_metrics()
        
        # 5. 生成结果
        return self._generate_result()
```

### 数据预取与缓存

```python
class DataPrefetcher:
    """数据预取器"""
    
    def __init__(self, tickers: List[str], lookback_period: int = 365):
        self.tickers = tickers
        self.lookback_period = lookback_period
        self.cache = {}
    
    def prefetch(self) -> Dict[str, Any]:
        """预取所有必要数据"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.lookback_period)
        
        # 并行预取各类数据
        with ThreadPoolExecutor(max_workers=4) as executor:
            price_future = executor.submit(self._fetch_prices)
            financial_future = executor.submit(self._fetch_financials)
            benchmark_future = executor.submit(self._fetch_benchmark)
            
            prices = price_future.result()
            financials = financial_future.result()
            benchmark = benchmark_future.result()
        
        return {
            "prices": prices,
            "financials": financials,
            "benchmark": benchmark
        }
```

### 逐日回测流程

```python
def _process_date(self, current_date: datetime):
    """处理单个交易日"""
    # 1. 获取当日数据
    current_prices = self._get_prices(current_date)
    lookback_data = self._get_lookback_data(current_date)
    
    # 2. 检查是否需要再平衡
    if self._should_rebalance(current_date):
        target_allocation = self._compute_target_allocation(lookback_data)
        self._rebalance(target_allocation, current_prices)
    
    # 3. 执行智能体分析（如果需要）
    if self._should_analyze(current_date):
        decisions = self._run_agent_analysis(lookback_data)
        self._execute_decisions(decisions, current_prices)
    
    # 4. 更新组合价值
    portfolio_value = self._compute_portfolio_value(current_prices)
    self.portfolio_values.append({
        "date": current_date,
        "value": portfolio_value
    })
```

## 2.2 交易成本模型深度实现

### 滑点模型

```python
from abc import ABC, abstractmethod
import numpy as np

class SlippageModel(ABC):
    """滑点模型基类"""
    
    @abstractmethod
    def get_slippage(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        volatility: float,
        daily_volume: float
    ) -> float:
        """计算滑点"""
        pass

class VolatilityAdjustedSlippageModel(SlippageModel):
    """波动率调整滑点模型"""
    
    def __init__(
        self,
        base_slippage: float = 0.0005,
        volatility_multiplier: float = 0.1,
        volume_multiplier: float = 0.01
    ):
        self.base_slippage = base_slippage
        self.volatility_multiplier = volatility_multiplier
        self.volume_multiplier = volume_multiplier
    
    def get_slippage(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        volatility: float,
        daily_volume: float
    ) -> float:
        """计算滑点"""
        # 波动率调整
        vol_adjustment = 1 + self.volatility_multiplier * (volatility / 0.02)
        
        # 成交量调整
        volume_ratio = quantity / daily_volume
        volume_adjustment = 1 + self.volume_multiplier * volume_ratio
        
        # 方向调整（卖出时滑点通常更大）
        side_adjustment = 1.0 if side == "BUY" else 1.1
        
        # 计算最终滑点
        total_adjustment = vol_adjustment * volume_adjustment * side_adjustment
        slippage = self.base_slippage * total_adjustment
        
        return min(slippage, 0.05)  # 设置滑点上限为 5%
```

### 市场冲击模型

```python
class MarketImpactModel:
    """市场冲击模型"""
    
    def __init__(
        self,
        impact_coefficient: float = 0.0001,
        decay_factor: float = 0.1
    ):
        self.impact_coefficient = impact_coefficient
        self.decay_factor = decay_factor
        self.pending_orders = []
    
    def estimate_impact(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        daily_volume: float
    ) -> float:
        """估算市场冲击成本"""
        # 计算订单规模占日成交量的比例
        order_ratio = quantity / daily_volume
        
        # 冲击与规模呈非线性关系
        impact = self.impact_coefficient * (order_ratio ** 0.5) * price
        
        # 买入冲击大于卖出
        if side == "BUY":
            impact *= 1.5
        
        return impact
    
    def calculate_execution_price(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        daily_volume: float
    ) -> float:
        """计算最终执行价格"""
        slippage = self.get_slippage(
            ticker, side, quantity, price,
            volatility=0.02, daily_volume=daily_volume
        )
        impact = self.estimate_impact(
            ticker, side, quantity, price, daily_volume
        )
        
        total_cost = slippage + impact
        
        if side == "BUY":
            return price * (1 + total_cost)
        else:
            return price * (1 - total_cost)
```

### 完整交易成本计算

```python
class TradingCostCalculator:
    """交易成本计算器"""
    
    def __init__(
        self,
        commission_model: CommissionModel,
        slippage_model: SlippageModel,
        spread_model: SpreadModel,
        impact_model: MarketImpactModel
    ):
        self.commission = commission_model
        self.slippage = slippage_model
        self.spread = spread_model
        self.impact = impact_model
    
    def calculate_total_cost(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        **kwargs
    ) -> Dict[str, float]:
        """计算总交易成本"""
        # 1. 佣金
        commission = self.commission.calculate(quantity, price)
        
        # 2. 滑点
        slippage = self.slippage.get_slippage(ticker, side, quantity, price, **kwargs)
        
        # 3. 点差
        spread = self.spread.get_spread(ticker, price)
        
        # 4. 市场冲击
        impact = self.impact.estimate_impact(ticker, side, quantity, price, **kwargs)
        
        total_cost = commission + slippage + spread + impact
        
        return {
            "commission": commission,
            "slippage": slippage,
            "spread": spread,
            "impact": impact,
            "total_cost": total_cost,
            "total_cost_bps": total_cost * 10000  # 以基点表示
        }
```

## 2.3 绩效归因分析

### 收益分解

```python
class PerformanceAttribution:
    """绩效归因分析"""
    
    def __init__(
        self,
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        factor_returns: pd.DataFrame
    ):
        self.portfolio = portfolio_returns
        self.benchmark = benchmark_returns
        self.factors = factor_returns
    
    def compute_attribution(self) -> Dict[str, float]:
        """计算收益归因"""
        # 总收益
        total_return = self.portfolio.sum()
        
        # 市场收益（基准贡献）
        market_contribution = self._compute_market_contribution()
        
        # 选股贡献
        stock_selection = self._compute_stock_selection()
        
        # 行业配置贡献
        sector_allocation = self._compute_sector_allocation()
        
        # 交互效应
        interaction = self._compute_interaction()
        
        return {
            "total_return": total_return,
            "market_contribution": market_contribution,
            "stock_selection": stock_selection,
            "sector_allocation": sector_allocation,
            "interaction": interaction
        }
    
    def _compute_market_contribution(self) -> float:
        """计算市场基准贡献"""
        return self.benchmark.mean() * len(self.benchmark)
    
    def _compute_stock_selection(self) -> float:
        """计算选股贡献"""
        # Brinson-Fachler 模型
        portfolio_weights = self._get_portfolio_weights()
        benchmark_weights = self._get_benchmark_weights()
        
        sector_returns = self._get_sector_returns()
        
        selection_effect = 0
        for sector in sector_returns.index:
            w_p = portfolio_weights.get(sector, 0)
            w_b = benchmark_weights.get(sector, 0)
            r_s = sector_returns[sector]
            
            selection_effect += (w_p - w_b) * (r_s - self.benchmark.mean())
        
        return selection_effect
```

### 风险归因

```python
class RiskAttribution:
    """风险归因分析"""
    
    def compute_risk_contribution(
        self,
        portfolio: Portfolio,
        covariance_matrix: np.ndarray
    ) -> pd.DataFrame:
        """计算风险贡献"""
        weights = portfolio.get_weights()
        
        # 组合波动率
        portfolio_vol = np.sqrt(weights @ covariance_matrix @ weights.T)
        
        # 各资产边际风险贡献
        marginal_contrib = covariance_matrix @ weights
        
        # 完全风险贡献
        risk_contrib = weights * marginal_contrib / portfolio_vol
        
        return pd.DataFrame({
            "weight": weights,
            "risk_contribution": risk_contrib,
            "risk_percentage": risk_contrib / portfolio_vol
        })
```

## 2.4 回测陷阱识别与避免

### 常见陷阱

**前视偏差（Look-Ahead Bias）**：在回测中使用了在实际交易时不可能获得的信息。

```python
# ❌ 错误示例：使用了未来数据
def compute_signals(prices):
    future_return = prices.shift(-1).pct_change()  # 使用了未来收益！
    signal = future_return > 0
    return signal

# ✅ 正确示例：只使用历史数据
def compute_signals(prices):
    past_return = prices.pct_change(lookback)  # 使用历史收益
    signal = past_return > threshold
    return signal
```

**幸存者偏差（Survivor Bias）**：只使用当前存在的股票进行回测。

**对策**：使用包含已退市股票的完整历史数据。

```python
# 使用 survivor-free 数据集
from src.data.survivor_free import get_survivor_free_prices

def get_backtest_data(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    """获取包含退市股票的数据"""
    return get_survivor_free_prices(tickers, start, end)
```

**过拟合（Overfitting）**：策略过度优化于历史数据。

**对策**：使用交叉验证和样本外测试。

```python
from sklearn.model_selection import TimeSeriesSplit

def walk_forward_validation(strategy, data, n_splits=5):
    """时间序列交叉验证"""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    
    results = []
    for train_idx, test_idx in tscv.split(data):
        train_data = data.iloc[train_idx]
        test_data = data.iloc[test_idx]
        
        # 训练
        strategy.fit(train_data)
        
        # 测试（样本外）
        predictions = strategy.predict(test_data)
        metrics = evaluate_predictions(predictions, test_data)
        
        results.append(metrics)
    
    return results
```

### 质量检查清单

```python
class BacktestQualityChecker:
    """回测质量检查"""
    
    def __init__(self, backtest_result: BacktestResult):
        self.result = backtest_result
        self.issues = []
    
    def check(self) -> Dict[str, Any]:
        """执行所有检查"""
        self._check_data_quality()
        self._check_survivor_bias()
        self._check_look_ahead_bias()
        self._check_overfitting()
        self._check_trading_costs()
        self._check_sample_size()
        
        return {
            "passed": len(self.issues) == 0,
            "issues": self.issues,
            "warnings": self.warnings
        }
    
    def _check_data_quality(self):
        """检查数据质量"""
        # 检查缺失值
        missing_pct = self.result.data["missing_percentage"]
        if missing_pct > 0.01:  # 超过 1%
            self.warnings.append(f"数据缺失率较高: {missing_pct:.2%}")
    
    def _check_trading_costs(self):
        """检查交易成本设置"""
        if self.result.config["commission_rate"] == 0:
            self.warnings.append("未设置交易佣金，可能高估收益")
        
        if self.result.config["slippage"] == 0:
            self.warnings.append("未设置滑点，可能高估收益")
```

## 2.5 练习题

### 练习 2.1：实现高级滑点模型

**任务**：实现一个考虑订单簿深度的高级滑点模型。

**要求**：模型应该能够根据订单规模和当前市场深度计算更精确的滑点估计。

### 练习 2.2：绩效归因分析

**任务**：对回测结果进行完整的绩效归因分析。

**步骤**：首先实现收益归因计算，然后实现风险归因计算，最后生成可视化的归因报告。

### 练习 2.3：回测质量审计

**任务**：对一个现有回测进行质量审计。

**设计**：创建一个检查清单，对回测进行全面的质量检查，识别潜在问题并提出改进建议。
