# 第五章：高级风险管理

## 学习目标

完成本章节学习后，你将能够理解和实现多因子风险模型，掌握压力测试和情景分析的方法，学会尾部风险管理和极端事件应对，以及能够设计和实施完整的风险管理框架。预计学习时间为 2-3 小时。

## 5.1 多因子风险模型

### 因子模型概述

多因子模型是现代风险管理的核心工具，通过识别和量化影响资产收益的各类因子来评估风险。

```python
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List, Optional
from scipy import stats

@dataclass
class Factor:
    """风险因子"""
    name: str
    factor_loadings: np.ndarray  # 因子载荷
    factor_returns: np.ndarray   # 因子收益
    idiosyncratic_var: np.ndarray  # 特质方差

class MultiFactorModel:
    """多因子风险模型"""
    
    def __init__(
        self,
        factors: List[str],
        risk_free_rate: float = 0.02
    ):
        self.factors = factors
        self.risk_free_rate = risk_free_rate
        self.factor_data = {}
        self.loadings = None
    
    def fit(self, returns: pd.DataFrame, factor_returns: pd.DataFrame):
        """拟合因子模型"""
        # 使用 OLS 回归估计因子载荷
        X = factor_returns.values
        Y = returns.values
        
        # 添加常数项
        X_with_const = np.column_stack([np.ones(X.shape[0]), X])
        
        # 估计载荷 (Betas)
        self.loadings = np.linalg.lstsq(X_with_const, Y, rcond=None)[0]
        
        # 计算特质收益和方差
        predicted = X_with_const @ self.loadings
        residuals = Y - predicted
        self.idiosyncratic_var = np.var(residuals, axis=0)
        
        # 估计因子收益协方差
        self.factor_cov = np.cov(factor_returns.T)
    
    def predict_risk(
        self,
        weights: np.ndarray,
        factor_loadings: Optional[np.ndarray] = None
    ) -> Dict[str, float]:
        """预测组合风险"""
        if factor_loadings is None:
            factor_loadings = self.loadings[1:].T  # 排除截距
        
        # 因子风险贡献
        portfolio_factor_loadings = weights @ factor_loadings
        systematic_risk = (
            portfolio_factor_loadings @ 
            self.factor_cov @ 
            portfolio_factor_loadings.T
        )
        
        # 特质风险
        idiosyncratic_risk = weights @ np.diag(self.idiosyncratic_var) @ weights.T
        
        # 总风险
        total_risk = systematic_risk + idiosyncratic_risk
        
        return {
            "systematic_risk": systematic_risk,
            "idiosyncratic_risk": idiosyncratic_risk,
            "total_risk": total_risk,
            "systematic_percentage": systematic_risk / total_risk if total_risk > 0 else 0
        }
    
    def factor_attribution(
        self,
        weights: np.ndarray,
        factor_loadings: Optional[np.ndarray] = None
    ) -> pd.DataFrame:
        """因子归因"""
        if factor_loadings is None:
            factor_loadings = self.loadings[1:].T
        
        portfolio_factor_loadings = weights @ factor_loadings
        
        attributions = {}
        for i, factor in enumerate(self.factors):
            loading = portfolio_factor_loadings[i]
            factor_vol = np.sqrt(self.factor_cov[i, i])
            
            attributions[factor] = {
                "loading": loading,
                "volatility": factor_vol,
                "contribution": loading * factor_vol * loading
            }
        
        return pd.DataFrame(attributions).T
```

### 常见因子

```python
class FactorBuilder:
    """因子构建器"""
    
    FACTOR_DEFINITIONS = {
        "market": {
            "description": "市场因子（CAPM）",
            "compute": lambda prices, benchmark: prices.pct_change() - benchmark.pct_change()
        },
        "size": {
            "description": "规模因子（SMB - Small Minus Big）",
            "compute": lambda large, small: (small.pct_change() - large.pct_change())
        },
        "value": {
            "description": "价值因子（HML - High Minus Low）",
            "compute": lambda high_bv, low_bv: (low_bv.pct_change() - high_bv.pct_change())
        },
        "momentum": {
            "description": "动量因子",
            "compute": lambda prices: prices.pct_change(periods=252)  # 年动量
        },
        "volatility": {
            "description": "低波动率因子",
            "compute": lambda returns: -returns.rolling(252).std()  # 负波动率
        }
    }
    
    @classmethod
    def build_factor(
        cls,
        factor_name: str,
        data: Dict[str, pd.DataFrame]
    ) -> pd.Series:
        """构建单个因子"""
        if factor_name not in cls.FACTOR_DEFINITIONS:
            raise ValueError(f"Unknown factor: {factor_name}")
        
        definition = cls.FACTOR_DEFINITIONS[factor_name]
        return definition["compute"](**data)
    
    @classmethod
    def build_all_factors(
        cls,
        data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """构建所有因子"""
        factors = {}
        for factor_name in cls.FACTOR_DEFINITIONS:
            try:
                factors[factor_name] = cls.build_factor(factor_name, data)
            except Exception as e:
                print(f"Warning: Failed to build factor {factor_name}: {e}")
        
        return pd.DataFrame(factors)
```

## 5.2 压力测试与情景分析

### 历史情景测试

```python
class HistoricalStressTest:
    """历史压力测试"""
    
    STRESS_PERIODS = {
        "2008_crisis": {
            "start": "2008-09-01",
            "end": "2009-03-31",
            "description": "2008 年金融危机"
        },
        "covid_crash": {
            "start": "2020-02-20",
            "end": "2020-03-23",
            "description": "2020 年 COVID-19 崩盘"
        },
        "dot_com_bubble": {
            "start": "2000-03-10",
            "end": "2002-10-09",
            "description": "2000 年互联网泡沫破裂"
        }
    }
    
    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio
        self.results = {}
    
    def run_stress_test(
        self,
        prices: pd.DataFrame
    ) -> Dict[str, Dict[str, float]]:
        """运行历史压力测试"""
        results = {}
        
        for period_name, period_info in self.STRESS_PERIODS.items():
            try:
                start_price = prices.loc[period_info["start"]:].iloc[0]["close"]
                end_price = prices.loc[:period_info["end"]].iloc[-1]["close"]
                
                period_return = (end_price - start_price) / start_price
                
                # 应用情景到当前组合
                current_allocation = self.portfolio.get_allocation()
                stressed_allocation = {
                    ticker: alloc * (1 + period_return)
                    for ticker, alloc in current_allocation.items()
                }
                
                # 计算压力测试结果
                results[period_name] = {
                    "period_return": period_return,
                    "description": period_info["description"],
                    "stressed_allocation": stressed_allocation,
                    "stressed_value_change": sum(stressed_allocation.values()) - sum(current_allocation.values())
                }
            except Exception as e:
                results[period_name] = {
                    "error": str(e)
                }
        
        self.results = results
        return results
```

### 假设情景测试

```python
class HypotheticalScenarioTest:
    """假设情景测试"""
    
    SCENARIOS = {
        "market_crash_20": {
            "description": "市场下跌 20%",
            "market_shock": -0.20,
            "correlations_change": {
                "market": 1.0,
                "volatility": 0.5,
                "bonds": -0.3
            }
        },
        "interest_rate_hike": {
            "description": "利率上升 2%",
            "rate_change": 0.02,
            "impact": {
                "growth_stocks": -0.15,
                "value_stocks": -0.05,
                "bonds": -0.10,
                "REITs": -0.20
            }
        },
        "inflation_spike": {
            "description": "通胀飙升",
            "inflation_change": 0.05,
            "impact": {
                "commodities": 0.10,
                "TIPS": 0.05,
                "growth_stocks": -0.08,
                "bonds": -0.12
            }
        }
    }
    
    def run_scenario(
        self,
        scenario_name: str,
        portfolio: Portfolio
    ) -> Dict[str, float]:
        """运行假设情景"""
        scenario = self.SCENARIOS[scenario_name]
        
        # 获取当前配置
        current_allocation = portfolio.get_allocation()
        
        # 计算情景影响
        impacted_allocation = {}
        for asset_class, allocation in current_allocation.items():
            impact = scenario.get("impact", {}).get(asset_class, 0)
            impacted_allocation[asset_class] = allocation * (1 + impact)
        
        # 计算总影响
        original_value = sum(current_allocation.values())
        new_value = sum(impacted_allocation.values())
        
        return {
            "scenario": scenario_name,
            "description": scenario["description"],
            "original_value": original_value,
            "stressed_value": new_value,
            "value_change": new_value - original_value,
            "percentage_change": (new_value - original_value) / original_value if original_value > 0 else 0,
            "impacted_allocation": impacted_allocation
        }
```

### 蒙特卡洛模拟

```python
class MonteCarloSimulation:
    """蒙特卡洛模拟"""
    
    def __init__(
        self,
        returns: np.ndarray,
        n_simulations: int = 10000,
        confidence_level: float = 0.95
    ):
        self.returns = returns
        self.n_simulations = n_simulations
        self.confidence_level = confidence_level
        self.simulated_paths = None
    
    def run_simulation(
        self,
        initial_value: float,
        n_periods: int = 252,
        drift: Optional[float] = None,
        volatility: Optional[float] = None
    ):
        """运行蒙特卡洛模拟"""
        if drift is None:
            drift = np.mean(self.returns)
        if volatility is None:
            volatility = np.std(self.returns)
        
        # 生成随机路径
        dt = 1 / 252
        random_shocks = np.random.standard_normal((self.n_simulations, n_periods))
        
        price_paths = np.zeros((self.n_simulations, n_periods + 1))
        price_paths[:, 0] = initial_value
        
        for t in range(1, n_periods + 1):
            price_paths[:, t] = price_paths[:, t-1] * np.exp(
                (drift - 0.5 * volatility**2) * dt + 
                volatility * np.sqrt(dt) * random_shocks[:, t-1]
            )
        
        self.simulated_paths = price_paths
        return price_paths
    
    def compute_var(self) -> Dict[str, float]:
        """计算风险价值 (VaR)"""
        if self.simulated_paths is None:
            raise ValueError("Please run simulation first")
        
        final_values = self.simulated_paths[:, -1]
        
        # 使用历史模拟法
        var_percentile = (1 - self.confidence_level) * 100
        var_value = np.percentile(final_values, var_percentile)
        
        return {
            "var_value": var_value,
            "confidence_level": self.confidence_level,
            "var_percentage": (var_value - self.simulated_paths[:, 0].mean()) / self.simulated_paths[:, 0].mean()
        }
    
    def compute_expected_shortfall(self) -> float:
        """计算期望损失 (ES / CVaR)"""
        if self.simulated_paths is None:
            raise ValueError("Please run simulation first")
        
        final_values = self.simulated_paths[:, -1]
        var_percentile = (1 - self.confidence_level) * 100
        var_value = np.percentile(final_values, var_percentile)
        
        # ES 是所有低于 VaR 的情景的平均损失
        tail_losses = final_values[final_values <= var_value]
        expected_shortfall = np.mean(tail_losses)
        
        return expected_shortfall
    
    def compute_probability_of_loss(self) -> float:
        """计算亏损概率"""
        if self.simulated_paths is None:
            raise ValueError("Please run simulation first")
        
        final_values = self.simulated_paths[:, -1]
        return np.mean(final_values < self.simulated_paths[:, 0])
```

## 5.3 尾部风险管理

### 极端损失保护

```python
class TailRiskProtection:
    """尾部风险管理"""
    
    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio
    
    def compute_tail_risk_metrics(self) -> Dict[str, float]:
        """计算尾部风险指标"""
        returns = self.portfolio.get_returns()
        
        # 计算偏度和峰度
        skewness = stats.skew(returns)
        kurtosis = stats.kurtosis(returns)
        
        # 计算下行风险
        negative_returns = returns[returns < 0]
        downside_risk = np.std(negative_returns) * np.sqrt(252)
        
        # 计算 Sortino 比率
        excess_return = np.mean(returns) * 252 - 0.02
        sortino_ratio = excess_return / downside_risk if downside_risk > 0 else 0
        
        # 计算最大单日损失
        max_drawdown = np.min(returns)
        
        return {
            "skewness": skewness,
            "kurtosis": kurtosis,
            "downside_risk": downside_risk,
            "sortino_ratio": sortino_ratio,
            "max_daily_loss": max_drawdown,
            "fat_tailed": kurtosis > 3  # 正态分布的峰度为 3
        }
    
    def recommend_protection(
        self,
        risk_budget: Dict[str, float] = None
    ) -> Dict[str, Any]:
        """推荐保护策略"""
        metrics = self.compute_tail_risk_metrics()
        recommendations = []
        
        if metrics["fat_tailed"]:
            recommendations.append({
                "type": "期权保护",
                "description": "购买看跌期权或领口策略",
                "expected_cost": "组合价值的 1-3%"
            })
        
        if abs(metrics["skewness"]) > 0.5:
            recommendations.append({
                "type": "尾部对冲",
                "description": "使用 VIX 或其他波动率产品",
                "expected_cost": "组合价值的 0.5-2%"
            })
        
        if metrics["sortino_ratio"] < 0.5:
            recommendations.append({
                "type": "分散化增强",
                "description": "增加低相关性资产",
                "expected_impact": "降低下行风险 20-30%"
            })
        
        return {
            "tail_risk_metrics": metrics,
            "recommendations": recommendations
        }
```

### 动态止损策略

```python
class AdaptiveStopLoss:
    """自适应止损策略"""
    
    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio
    
    def compute_volatility_adjusted_stop(
        self,
        entry_price: float,
        atr: float,
        volatility_multiplier: float = 2.0,
        market_condition: str = "normal"
    ) -> Dict[str, float]:
        """计算波动率调整止损"""
        # 根据市场状况调整参数
        condition_adjustments = {
            "trending_up": {"multiplier": 2.5, "trailing": True},
            "trending_down": {"multiplier": 1.5, "trailing": True},
            "volatile": {"multiplier": 3.0, "trailing": False},
            "calm": {"multiplier": 1.5, "trailing": False},
            "normal": {"multiplier": 2.0, "trailing": True}
        }
        
        adjustment = condition_adjustments.get(market_condition, condition_adjustments["normal"])
        
        # 初始止损
        stop_distance = atr * adjustment["multiplier"]
        initial_stop = entry_price - stop_distance
        
        # 追踪止损
        if adjustment["trailing"]:
            trailing_stop = self._compute_trailing_stop(entry_price, atr, adjustment["multiplier"])
        else:
            trailing_stop = initial_stop
        
        return {
            "initial_stop": initial_stop,
            "trailing_stop": trailing_stop,
            "stop_distance": stop_distance,
            "stop_percentage": stop_distance / entry_price,
            "condition_adjusted": adjustment
        }
    
    def _compute_trailing_stop(
        self,
        current_price: float,
        atr: float,
        multiplier: float
    ) -> float:
        """计算追踪止损"""
        highest_price = self.portfolio.get_highest_price()
        stop_distance = atr * multiplier
        return highest_price - stop_distance
```

## 5.4 风险管理框架设计

### 综合风控系统

```python
class RiskManagementSystem:
    """综合风险管理"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.risk_limits = config.get("risk_limits", {})
        self.risk_metrics = {}
        
        # 初始化各风险模块
        self.var_calculator = VaRCalculator()
        self.stress_tester = StressTestEngine()
        self.tail_risk = TailRiskProtection()
        self.portfolio = Portfolio()
    
    def assess_portfolio_risk(
        self,
        portfolio: Portfolio,
        factor_model: MultiFactorModel = None
    ) -> Dict[str, Any]:
        """综合风险评估"""
        risk_report = {
            "timestamp": datetime.now(),
            "status": "OK",
            "warnings": [],
            "violations": []
        }
        
        # 1. 计算 VaR
        var_metrics = self.var_calculator.compute_var(
            portfolio.get_returns(),
            confidence_level=self.risk_limits.get("var_confidence", 0.95)
        )
        risk_report["var"] = var_metrics
        
        # 检查 VaR 限制
        var_limit = self.risk_limits.get("var_limit", 0.02)
        if var_metrics["var_percentage"] > var_limit:
            risk_report["violations"].append({
                "type": "VaR 突破",
                "current": var_metrics["var_percentage"],
                "limit": var_limit
            })
        
        # 2. 压力测试
        stress_results = self.stress_tester.run_all_scenarios(portfolio)
        risk_report["stress_tests"] = stress_results
        
        # 3. 尾部风险
        tail_metrics = self.tail_risk.compute_tail_risk_metrics()
        risk_report["tail_risk"] = tail_metrics
        
        # 4. 集中度检查
        concentration = self._check_concentration(portfolio)
        risk_report["concentration"] = concentration
        
        # 5. 流动性检查
        liquidity = self._check_liquidity(portfolio)
        risk_report["liquidity"] = liquidity
        
        # 6. 生成整体状态
        if risk_report["violations"]:
            risk_report["status"] = "VIOLATION"
        elif len(risk_report["warnings"]) > 2:
            risk_report["status"] = "WARNING"
        
        return risk_report
    
    def _check_concentration(self, portfolio: Portfolio) -> Dict:
        """检查集中度"""
        allocation = portfolio.get_allocation()
        
        violations = []
        for ticker, weight in allocation.items():
            if weight > self.risk_limits.get("single_position_limit", 0.10):
                violations.append({
                    "ticker": ticker,
                    "weight": weight,
                    "limit": self.risk_limits.get("single_position_limit", 0.10)
                })
        
        return {
            "max_weight": max(allocation.values()) if allocation else 0,
            "violations": violations,
            "passed": len(violations) == 0
        }
    
    def _check_liquidity(self, portfolio: Portfolio) -> Dict:
        """检查流动性"""
        allocation = portfolio.get_allocation()
        
        illiquid_positions = []
        for ticker, weight in allocation.items():
            # 假设权重超过 5% 的头寸需要更高流动性
            if weight > 0.05:
                avg_daily_volume = get_average_daily_volume(ticker)
                if avg_daily_volume is None or volume_too_low(weight, avg_daily_volume):
                    illiquid_positions.append({
                        "ticker": ticker,
                        "weight": weight,
                        "concern": "流动性可能不足"
                    })
        
        return {
            "illiquid_positions": illiquid_positions,
            "passed": len(illiquid_positions) == 0
        }
```

## 5.5 练习题

### 练习 5.1：多因子风险模型

**任务**：实现完整的多因子风险模型。

**步骤**：首先定义主要因子，然后估计因子载荷和因子协方差，接着计算组合的系统风险和特质风险，最后进行因子归因分析。

### 练习 5.2：压力测试系统

**任务**：实现全面的压力测试框架。

**要求**：支持历史情景和假设情景，包含蒙特卡洛模拟，生成可视化的压力测试报告。

### 练习 5.3：综合风控系统

**任务**：设计和实现完整的风险管理框架。

**要求**：整合 VaR、压力测试、尾部风险、集中度检查等多个维度，生成综合风险报告。
