# AI对冲基金系统 - 数据质量改进计划

> **版本**: v1.0  
> **日期**: 2026-02-27  
> **状态**: 待审阅  

---

## 一、现状分析

### 1.1 发现的数据质量问题

#### 问题1: 财务指标单位不统一

**现象**:
- ROE显示为519.86%（实际应为5.1986%或数据错误）
- 净利润率显示为1281.68%（物理上不可能）
- 不同分析师看到的ROE不一致（519% vs 5%）

**根本原因**:
```python
# AKShare提供商 - 正确除以100
return_on_equity=float(row.get("净资产收益率", 0)) / 100

# Tushare提供商 - 未除以100
return_on_equity=float(row.get("roe", 0))  # 缺少 / 100

# 利润率 - 完全没有单位转换
gross_margin=float(row.get("毛利率", 0))  # 缺少 / 100
```

#### 问题2: 数据验证机制失效

**现状**:
```python
# validator.py 仅记录警告，不阻止异常数据
if not -1 <= roe <= 1:
    logger.warning(f"Metric[{i}]: ROE outside [-1, 1]")
# 异常数据继续流入系统...
```

**问题**:
- 验证器发现异常后仅记录日志
- 异常数据仍被分析师使用
- 没有数据质量评分机制

#### 问题3: 清洗器功能缺失

**现状**:
```python
# clean_financial_metrics 仅实现去重和排序
def clean_financial_metrics(metrics):
    # 去重
    # 排序
    # TODO: 处理异常值 <-- 未实现
    return metrics
```

---

## 二、改进目标

### 2.1 核心目标

| 目标 | 指标 | 验收标准 |
|------|------|----------|
| 数据准确性 | 财务指标错误率 | < 1% |
| 数据一致性 | 同一指标不同来源差异 | < 5% |
| 数据完整性 | 关键字段缺失率 | < 5% |
| 异常拦截率 | 异常数据被拦截比例 | > 95% |

### 2.2 业务目标

1. **消除虚假信号** - 防止错误数据导致错误交易决策
2. **提升分析质量** - 确保分析师基于可靠数据做出判断
3. **增强系统可信度** - 建立数据质量监控和报告机制

---

## 三、解决方案设计

### 3.1 方案概览

```
┌─────────────────────────────────────────────────────────────┐
│                    数据质量保障体系                          │
├─────────────────────────────────────────────────────────────┤
│  数据源层  →  适配层  →  验证层  →  清洗层  →  分析层        │
│     │           │          │          │          │         │
│     ▼           ▼          ▼          ▼          ▼         │
│  AKShare    格式统一    规则验证    异常修正    分析师      │
│  Tushare    单位转换    范围检查    缺失填补    使用        │
│  其他源     类型规范    逻辑校验    质量评分    数据        │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 详细方案

#### 方案A: 数据源适配器（高优先级）

**目标**: 统一不同数据源的数据格式

**实施内容**:

1. **创建数据源适配器基类**
```python
# src/data/adapters/base.py
class DataSourceAdapter(ABC):
    """数据源适配器基类"""
    
    @abstractmethod
    def adapt_financial_metrics(self, raw_data: Dict) -> FinancialMetrics:
        """将原始数据转换为标准格式"""
        pass
    
    @abstractmethod
    def get_unit_conversion_rules(self) -> Dict[str, float]:
        """返回单位转换规则 {field: multiplier}"""
        pass
```

2. **实现AKShare适配器**
```python
# src/data/adapters/akshare_adapter.py
class AKShareAdapter(DataSourceAdapter):
    """AKShare数据适配器"""
    
    def get_unit_conversion_rules(self) -> Dict[str, float]:
        return {
            # AKShare返回百分比格式，需要除以100
            "return_on_equity": 0.01,      # 15.5 → 0.155
            "gross_margin": 0.01,          # 25.5 → 0.255
            "operating_margin": 0.01,      # 15.0 → 0.15
            "net_margin": 0.01,            # 12.8 → 0.128
            "debt_to_equity": 1.0,         # 已经是小数
            "current_ratio": 1.0,          # 已经是小数
        }
    
    def adapt_financial_metrics(self, raw_data: Dict) -> FinancialMetrics:
        rules = self.get_unit_conversion_rules()
        adapted = {}
        
        for field, multiplier in rules.items():
            value = raw_data.get(field)
            if value is not None and pd.notna(value):
                adapted[field] = float(value) * multiplier
        
        return FinancialMetrics(**adapted)
```

3. **实现Tushare适配器**
```python
# src/data/adapters/tushare_adapter.py
class TushareAdapter(DataSourceAdapter):
    """Tushare数据适配器"""
    
    def get_unit_conversion_rules(self) -> Dict[str, float]:
        return {
            # Tushare返回小数格式，无需转换
            "return_on_equity": 1.0,
            "gross_margin": 1.0,
            "operating_margin": 1.0,
            "net_margin": 1.0,
            "debt_to_equity": 1.0,
            "current_ratio": 1.0,
        }
```

**预期效果**:
- 消除不同数据源之间的格式差异
- 统一输出标准格式（所有比率均为小数）
- 新增数据源只需实现适配器即可

---

#### 方案B: 增强数据验证器（高优先级）

**目标**: 建立多层验证机制，拦截异常数据

**实施内容**:

1. **定义验证规则配置**
```python
# src/data/validation_rules.py
from dataclasses import dataclass
from typing import Optional, Callable, Any

@dataclass
class ValidationRule:
    field: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allow_null: bool = True
    custom_validator: Optional[Callable[[Any], bool]] = None
    severity: str = "error"  # "error" | "warning"

# 财务指标验证规则
FINANCIAL_METRICS_RULES = [
    # ROE: 正常范围 -50% 到 +100%，极端情况可到 -100% 到 +200%
    ValidationRule(
        field="return_on_equity",
        min_value=-2.0,
        max_value=2.0,
        allow_null=True,
        severity="error"
    ),
    
    # 利润率: 正常范围 -50% 到 +100%
    ValidationRule(
        field="gross_margin",
        min_value=-0.5,
        max_value=1.0,
        allow_null=True,
        severity="error"
    ),
    ValidationRule(
        field="operating_margin",
        min_value=-0.5,
        max_value=1.0,
        allow_null=True,
        severity="error"
    ),
    ValidationRule(
        field="net_margin",
        min_value=-0.5,
        max_value=1.0,
        allow_null=True,
        severity="error"
    ),
    
    # 财务健康指标
    ValidationRule(
        field="debt_to_equity",
        min_value=0,
        max_value=10.0,
        allow_null=True,
        severity="warning"
    ),
    ValidationRule(
        field="current_ratio",
        min_value=0,
        max_value=10.0,
        allow_null=True,
        severity="warning"
    ),
    
    # 估值指标
    ValidationRule(
        field="price_to_earnings",
        min_value=0,
        max_value=1000.0,
        allow_null=True,
        severity="warning"
    ),
    ValidationRule(
        field="price_to_book",
        min_value=0,
        max_value=100.0,
        allow_null=True,
        severity="warning"
    ),
]
```

2. **实现增强验证器**
```python
# src/data/validator_v2.py
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class ValidationResult:
    is_valid: bool
    field: str
    value: Any
    rule: ValidationRule
    message: str

class EnhancedDataValidator:
    """增强型数据验证器"""
    
    def __init__(self, rules: List[ValidationRule]):
        self.rules = {rule.field: rule for rule in rules}
    
    def validate_metric(self, metric: Any) -> Tuple[bool, List[ValidationResult]]:
        """
        验证单个指标对象
        
        Returns:
            (是否通过, 验证结果列表)
        """
        results = []
        has_error = False
        
        for field_name, rule in self.rules.items():
            value = self._get_field_value(metric, field_name)
            
            # 检查null
            if value is None or (isinstance(value, float) and pd.isna(value)):
                if not rule.allow_null:
                    result = ValidationResult(
                        is_valid=False,
                        field=field_name,
                        value=value,
                        rule=rule,
                        message=f"{field_name} 不能为空"
                    )
                    results.append(result)
                    if rule.severity == "error":
                        has_error = True
                continue
            
            # 数值范围检查
            if rule.min_value is not None and value < rule.min_value:
                result = ValidationResult(
                    is_valid=False,
                    field=field_name,
                    value=value,
                    rule=rule,
                    message=f"{field_name}={value} 小于最小值 {rule.min_value}"
                )
                results.append(result)
                if rule.severity == "error":
                    has_error = True
            
            if rule.max_value is not None and value > rule.max_value:
                result = ValidationResult(
                    is_valid=False,
                    field=field_name,
                    value=value,
                    rule=rule,
                    message=f"{field_name}={value} 大于最大值 {rule.max_value}"
                )
                results.append(result)
                if rule.severity == "error":