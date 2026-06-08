# 第四章：故障排除手册

> **📚 本章难度**：⭐⭐⭐（进阶）
> **⏱️ 预计学习时间**：2-3 小时
> **🎯 适用场景**：生产环境问题排查、系统调试、性能优化

---

## 学习目标

完成本章节学习后，你将能够：

### 基础目标（必掌握）⭐

- [ ] 理解系统问题的分类体系和诊断框架的设计思想
- [ ] 能够识别和区分 **配置问题**、**网络问题**、**数据问题**、**资源问题** 和 **逻辑问题**
- [ ] 掌握常见错误的诊断流程，能够快速定位问题根源
- [ ] 配置和使用日志系统，能够从日志中提取关键信息
- [ ] 理解 **熔断器模式** 和 **优雅降级** 的基本概念

### 进阶目标（建议掌握）⭐⭐

- [ ] 设计并实现一个可扩展的诊断框架
- [ ] 编写自动化诊断脚本，提高问题排查效率
- [ ] 掌握远程调试技术，能够在生产环境中调试问题
- [ ] 实现性能监控和分析，识别系统瓶颈
- [ ] 设计完整的故障恢复流程，减少系统停机时间

### 专家目标（挑战）⭐⭐⭐

- [ ] 建立生产环境的监控告警体系，实现问题的早期发现
- [ ] 制定团队的故障排查最佳实践文档和检查清单
- [ ] 诊断和解决复杂的级联故障和性能问题
- [ ] 设计高可用架构，提高系统的容错能力

---

## 4.1 问题分类与诊断框架

### 4.1.1 核心设计思想

在开始学习具体的问题排查方法之前，我们需要先理解：**为什么要建立系统的问题分类和诊断框架？**

**设计背景**

生产环境中的故障千变万化，如果我们每次都从头开始排查，效率会非常低。专家和新手的核心区别在于：

| 对比维度 | 新手 | 专家 |
|---------|------|------|
| 问题识别 | 看到现象，不知道属于哪类 | 立即识别问题类型，匹配已知模式 |
| 排查策略 | 尝试各种方法，盲目摸索 | 有系统的排查流程，从高概率原因开始 |
| 决策速度 | 慢，容易遗漏重要步骤 | 快，基于经验和模式识别 |
| 知识复用 | 每次都重新思考 | 直接应用已验证的解决方案 |

**核心价值**

建立诊断框架的价值在于：

1. **认知效率提升** - 通过分类快速缩小排查范围
2. **知识复用** - 将专家经验固化为可复用的流程
3. **团队协作** - 统一的问题描述和排查语言
4. **自动化基础** - 为自动化诊断提供理论基础

---

### 4.1.2 问题分类体系

系统故障可以按照以下维度分类，每种类型都有特定的症状和排查方向：

#### 问题类型概览

| 问题类型 | 典型症状 | 发生时机 | 排查难度 |
|---------|---------|---------|---------|
| **配置问题** | 启动失败、认证错误 | 系统启动或首次调用 | ⭐ 容易 |
| **网络问题** | 超时、连接失败、间歇性错误 | 运行过程中 | ⭐⭐ 中等 |
| **数据问题** | 数据格式错误、分析结果异常 | 数据处理环节 | ⭐⭐ 中等 |
| **资源问题** | 性能下降、服务中断 | 负载较高时 | ⭐⭐⭐ 困难 |
| **逻辑问题** | 功能异常、错误结果 | 特定操作或场景 | ⭐⭐⭐ 困难 |

#### 详细分类说明

**1. 配置问题（Configuration Issues）**

> 💡 **核心特征**：问题在系统启动时就能被发现，通常与环境和参数设置相关

**常见症状**：
- 启动时报告 `APIKeyNotFoundError` 或 `AuthenticationError`
- 环境变量缺失或值不正确
- 配置文件格式错误或路径错误

**为什么容易发生**？
- 配置项众多，容易遗漏
- 不同环境（开发/测试/生产）配置差异
- API 密钥等敏感信息通常从环境变量读取，配置不当会导致启动失败

**2. 网络问题（Network Issues）**

> 💡 **核心特征**：表现为间歇性错误，与外部服务交互时出现问题

**常见症状**：
- API 调用超时（**Timeout**）
- 连接失败（**Connection Refused**）
- DNS（**Domain Name System**，域名系统）解析失败

**为什么容易发生**？
- 网络环境不稳定（特别是云环境）
- 外部服务可用性问题
- 请求频率过高触发速率限制

**3. 数据问题（Data Issues）**

> 💡 **核心特征**：数据获取或处理环节出现问题，可能导致分析结果异常

**常见症状**：
- **DataNotFoundError** - 数据未找到
- **DataFormatError** - 数据格式不正确
- 数据不一致或数据缺失

**为什么容易发生**？
- 数据源 API 升级导致格式变化
- 股票代码错误或日期范围超出覆盖范围
- 数据提供商的服务中断

**4. 资源问题（Resource Issues）**

> 💡 **核心特征**：系统资源不足，通常表现为性能下降或服务中断

**常见症状**：
- 内存不足（**Out of Memory**）
- CPU 过载（**High CPU Usage**）
- 磁盘空间不足（**Disk Full**）

**为什么容易发生**？
- 并发任务过多
- 数据量增长超出预期
- 内存泄漏（代码 bug 导致内存未正确释放）

**5. 逻辑问题（Logic Issues）**

> 💡 **核心特征**：代码逻辑错误，需要深入代码分析

**常见症状**：
- 功能异常
- 分析结果不符合预期
- 状态管理错误

**为什么容易发生**？
- 边界条件未考虑（空输入、极端值）
- 并发场景下的竞态条件
- 算法实现错误

---

### 4.1.3 诊断框架设计

#### 为什么需要框架化诊断？

**问题**：面对一个错误，如何系统地排查，而不是盲目尝试？

**传统方式的局限性**：
```
遇到错误 → 尝试方法 A → 失败 → 尝试方法 B → 失败 → 尝试方法 C → ...
```
这种方式效率低，容易遗漏关键信息，且难以复用经验。

**框架化诊断的优势**：
```
遇到错误 → 分类识别 → 应用诊断器 → 获取结构化诊断结果 → 执行修复
```
这种方式：
- ✅ 系统性：按固定流程排查，不会遗漏
- ✅ 可扩展：新增问题类型只需添加新的诊断器
- ✅ 可自动化：可以编程实现自动诊断
- ✅ 知识复用：诊断器积累就是专家经验库

#### 诊断框架实现

下面是一个可扩展的诊断框架实现，采用了**策略模式（Strategy Pattern）**：

```python
from enum import Enum
from typing import Dict, List, Any
from dataclasses import dataclass
from datetime import datetime

class ProblemCategory(Enum):
    """问题类型枚举"""
    CONFIGURATION = "configuration"  # 配置问题
    NETWORK = "network"              # 网络问题
    DATA = "data"                     # 数据问题
    RESOURCE = "resource"             # 资源问题
    LOGIC = "logic"                   # 逻辑问题
    UNKNOWN = "unknown"               # 未知问题

@dataclass
class DiagnosticResult:
    """诊断结果

    Attributes:
        category: 问题类型
        description: 问题描述
        evidence: 证据（用于诊断的具体信息）
        possible_causes: 可能原因列表
        recommended_actions: 建议的修复操作
        severity: 严重程度（high/medium/low）
    """
    category: ProblemCategory
    description: str
    evidence: Dict[str, Any]
    possible_causes: List[str]
    recommended_actions: List[str]
    severity: str

class DiagnosticFramework:
    """诊断框架

    这是一个可扩展的诊断系统，通过注册不同的诊断器（Diagnoser）
    来诊断各种类型的问题。

    设计模式：策略模式（Strategy Pattern）
    """

    def __init__(self):
        self.diagnosers = []
        self.diagnosis_history = []

    def register_diagnoser(self, diagnoser: 'Diagnoser'):
        """注册诊断器

        Args:
            diagnoser: 诊断器实例
        """
        self.diagnosers.append(diagnoser)

    def diagnose(self, error: Exception) -> DiagnosticResult:
        """执行诊断

        遍历所有注册的诊断器，找到能够诊断该错误的诊断器并执行诊断。

        Args:
            error: 需要诊断的异常对象

        Returns:
            DiagnosticResult: 诊断结果
        """
        for diagnoser in self.diagnosers:
            if diagnoser.can_diagnose(error):
                result = diagnoser.diagnose(error)
                self.diagnosis_history.append(result)
                return result

        # 没有找到合适的诊断器
        return DiagnosticResult(
            category=ProblemCategory.UNKNOWN,
            description=str(error),
            evidence={},
            possible_causes=["未知原因"],
            recommended_actions=["联系技术支持"],
            severity="unknown"
        )

# 诊断器基类
class Diagnoser:
    """诊断器基类"""

    def can_diagnose(self, error: Exception) -> bool:
        """判断是否可以诊断该错误

        Args:
            error: 异常对象

        Returns:
            bool: 如果可以诊断返回 True
        """
        raise NotImplementedError

    def diagnose(self, error: Exception) -> DiagnosticResult:
        """执行诊断

        Args:
            error: 异常对象

        Returns:
            DiagnosticResult: 诊断结果
        """
        raise NotImplementedError
```

#### 设计要点解析

**1. 为什么使用枚举（Enum）？**
- **优点**：类型安全，避免字符串拼写错误
- **优点**：IDE 自动补全，提高开发效率
- **优点**：便于维护和扩展

**2. 为什么使用 dataclass？**
- **优点**：简洁的类定义，自动生成 `__init__`、`__repr__` 等方法
- **优点**：类型提示明确，便于静态类型检查
- **优点**：便于序列化和反序列化（存储诊断结果）

**3. 为什么使用策略模式？**
- **优点**：开闭原则，新增诊断器无需修改框架代码
- **优点**：每个诊断器职责单一，易于测试
- **优点**：可以动态注册/注销诊断器

---

## 4.2 常见问题与解决方案

### 4.2.1 API 密钥配置问题

**典型症状**：
```
启动时报告：
- APIKeyNotFoundError: API key not found
- AuthenticationError: Invalid credentials
```

**诊断流程图**：

```
错误出现
    │
    ▼
检查 .env 文件是否存在？
    │
    ├── 否 → 创建 .env 文件：cp .env.example .env
    │
    ▼ 是
检查环境变量是否设置？
    │
    ├── 否 → 在 .env 文件中添加对应的 API_KEY
    │
    ▼ 是
检查 API 密钥是否有效？
    │
    ├── 否 → 更新为有效的 API 密钥
    │
    ▼ 是
重启服务
```

**诊断器实现**：

```python
class APIKeyDiagnoser(Diagnoser):
    """API 密钥诊断器

    用于诊断 API 密钥配置相关的问题
    """

    def can_diagnose(self, error: Exception) -> bool:
        """判断是否为 API 密钥相关错误"""
        return isinstance(error, (APIKeyNotFoundError, AuthenticationError))

    def diagnose(self, error: Exception) -> DiagnosticResult:
        """诊断 API 密钥问题"""
        evidence = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "environment_variables": self._check_env_vars(),
            "dotenv_file": self._check_dotenv_file()
        }

        possible_causes = []
        recommended_actions = []

        # 检查 .env 文件
        if evidence["dotenv_file"] == "missing":
            possible_causes.append(".env 文件不存在")
            recommended_actions.append("创建 .env 文件：cp .env.example .env")

        # 检查环境变量
        if not evidence["environment_variables"].get("OPENAI_API_KEY"):
            possible_causes.append("OPENAI_API_KEY 未设置")
            recommended_actions.append("在 .env 文件中添加 OPENAI_API_KEY")

        if not evidence["environment_variables"].get("ANTHROPIC_API_KEY"):
            possible_causes.append("ANTHROPIC_API_KEY 未设置")
            recommended_actions.append("在 .env 文件中添加 ANTHROPIC_API_KEY")

        return DiagnosticResult(
            category=ProblemCategory.CONFIGURATION,
            description="API 密钥配置问题",
            evidence=evidence,
            possible_causes=possible_causes,
            recommended_actions=recommended_actions,
            severity="high"
        )

    def _check_env_vars(self) -> Dict[str, str]:
        """检查环境变量"""
        import os
        return {
            "OPENAI_API_KEY": "SET" if os.getenv("OPENAI_API_KEY") else "NOT SET",
            "ANTHROPIC_API_KEY": "SET" if os.getenv("ANTHROPIC_API_KEY") else "NOT SET",
            "FINANCIAL_DATASETS_API_KEY": "SET" if os.getenv("FINANCIAL_DATASETS_API_KEY") else "NOT SET"
        }

    def _check_dotenv_file(self) -> str:
        """检查 .env 文件是否存在"""
        import os
        if os.path.exists(".env"):
            return "exists"
        return "missing"
```

**验证清单**：

- [ ] .env 文件存在于项目根目录
- [ ] .env 文件中包含所需的 API 密钥
- [ ] API 密钥格式正确（没有多余空格或引号）
- [ ] 重启服务使配置生效

---

### 4.2.2 LLM API 调用失败

**典型症状**：
```
运行过程中报告：
- LLMTimeoutError: Request timeout
- RateLimitError: Rate limit exceeded
- ServiceUnavailableError: Service temporarily unavailable
```

**为什么会出现这些问题？**

| 错误类型 | 根本原因 | 触发条件 |
|---------|---------|---------|
| **LLMTimeoutError** | 请求超时 | 网络不稳定、服务响应慢、请求内容过长 |
| **RateLimitError** | 触发速率限制 | 短时间内请求过多、账户配额用尽 |
| **ServiceUnavailableError** | 服务不可用 | API 服务维护、过载、故障 |

**诊断器实现**：

```python
class LLMAPIDiagnoser(Diagnoser):
    """LLM API 诊断器

    用于诊断 LLM（Large Language Model，大语言模型）API 调用相关的问题
    """

    def can_diagnose(self, error: Exception) -> bool:
        return isinstance(error, (LLMTimeoutError, RateLimitError, ServiceUnavailableError))

    def diagnose(self, error: Exception) -> DiagnosticResult:
        evidence = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "retry_count": getattr(error, 'retry_count', 0),
            "provider": getattr(error, 'provider', 'unknown'),
            "last_attempt": getattr(error, 'last_attempt', None)
        }

        possible_causes = []
        recommended_actions = []

        # 针对不同错误类型的诊断
        if isinstance(error, RateLimitError):
            possible_causes.extend([
                "API 调用频率超过限制",
                "账户配额已用尽"
            ])
            recommended_actions.extend([
                "添加 API 密钥轮换（使用多个密钥）",
                "实现请求限流（控制调用频率）",
                "升级账户配额"
            ])

        if isinstance(error, LLMTimeoutError):
            possible_causes.extend([
                "网络连接不稳定",
                "API 服务响应慢",
                "请求内容过长"
            ])
            recommended_actions.extend([
                "增加超时时间（如从 30s 增加到 60s）",
                "缩短提示词（prompt）长度",
                "尝试其他 LLM 提供商"
            ])

        if isinstance(error, ServiceUnavailableError):
            possible_causes.extend([
                "API 服务暂时不可用（维护中）",
                "API 服务过载"
            ])
            recommended_actions.extend([
                "等待一段时间后重试",
                "切换到备用 API 提供商",
                "检查 API 服务状态页面"
            ])

        return DiagnosticResult(
            category=ProblemCategory.NETWORK,
            description="LLM API 调用失败",
            evidence=evidence,
            possible_causes=possible_causes,
            recommended_actions=recommended_actions,
            severity="medium"
        )
```

**最佳实践**：

```python
# 重试机制示例
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),  # 最多重试 3 次
    wait=wait_exponential(multiplier=1, min=2, max=10)  # 指数退避
)
def call_llm_api(prompt: str):
    """调用 LLM API，带重试机制"""
    # API 调用逻辑
    pass
```

---

### 4.2.3 数据获取失败

**典型症状**：
```
数据获取环节报告：
- DataNotFoundError: Data not found for ticker
- DataFormatError: Invalid data format
- APIError: API call failed
```

**常见原因分析**：

| 原因 | 说明 | 排查方法 |
|------|------|---------|
| 股票代码错误 | 输入了不存在的股票代码 | 在财经网站验证代码有效性 |
| 日期范围错误 | 请求的日期超出数据覆盖范围 | 检查数据源支持的时间范围 |
| 数据源不支持 | 数据提供商不支持该股票或数据类型 | 尝试其他数据源 |
| API 升级 | 数据提供商 API 升级导致格式变化 | 查看数据提供商的更新日志 |

**诊断器实现**：

```python
class DataDiagnoser(Diagnoser):
    """数据获取诊断器

    用于诊断数据获取相关的问题
    """

    def can_diagnose(self, error: Exception) -> bool:
        return isinstance(error, (DataNotFoundError, DataFormatError, APIError))

    def diagnose(self, error: Exception) -> DiagnosticResult:
        evidence = {
            "error_type": type(error).__name__,
            "ticker": getattr(error, 'ticker', 'unknown'),
            "data_type": getattr(error, 'data_type', 'unknown'),
            "date_range": getattr(error, 'date_range', 'unknown')
        }

        possible_causes = []
        recommended_actions = []

        if isinstance(error, DataNotFoundError):
            possible_causes.extend([
                "股票代码无效或不存在",
                "日期范围超出数据覆盖范围",
                "数据提供商不支持该股票"
            ])
            recommended_actions.extend([
                "在财经网站（如 Yahoo Finance）验证股票代码",
                "检查日期范围是否在数据源支持范围内",
                "尝试使用备用数据源"
            ])

        if isinstance(error, DataFormatError):
            possible_causes.extend([
                "数据格式发生变化",
                "数据提供商 API 升级"
            ])
            recommended_actions.extend([
                "更新数据解析代码",
                "联系数据提供商确认 API 变更"
            ])

        if isinstance(error, APIError):
            possible_causes.extend([
                "数据源 API 调用失败",
                "网络连接问题"
            ])
            recommended_actions.extend([
                "检查网络连接",
                "验证数据源 API 密钥是否有效",
                "尝试重新获取数据"
            ])

        return DiagnosticResult(
            category=ProblemCategory.DATA,
            description="数据获取失败",
            evidence=evidence,
            possible_causes=possible_causes,
            recommended_actions=recommended_actions,
            severity="medium"
        )
```

---

## 4.3 日志分析与调试

### 4.3.1 为什么需要日志？

**日志的价值**：

| 场景 | 日志的作用 |
|------|----------|
| **开发阶段** | 追踪程序执行流程，理解代码行为 |
| **测试阶段** | 定位 bug，验证修复效果 |
| **生产环境** | 诊断问题，分析系统行为 |
| **性能优化** | 识别性能瓶颈 |
| **安全审计** | 追踪用户操作和系统访问 |

**日志的最佳实践**：

1. **分级记录**：使用不同级别（DEBUG、INFO、WARNING、ERROR）区分日志重要性
2. **结构化日志**：使用 JSON 格式便于解析和分析
3. **上下文信息**：包含请求 ID、用户 ID 等关联信息
4. **避免敏感信息**：不要记录密码、API 密钥等敏感数据

---

### 4.3.2 日志配置

```python
import logging
import logging.config
from pathlib import Path

def setup_logging(
    log_dir: Path = Path("logs"),
    level: str = "INFO",
    format: str = None
):
    """配置日志系统

    配置三个日志处理器：
    1. console: 输出到控制台
    2. file: 输出到文件（轮转）
    3. error_file: 只记录 ERROR 及以上级别的日志

    Args:
        log_dir: 日志目录
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        format: 日志格式字符串
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    # 日志格式：时间 | 级别 | 模块:函数:行号 | 消息
    log_format = format or (
        "%(asctime)s | %(levelname)-8s | "
        "%(name)s:%(funcName)s:%(lineno)d | %(message)s"
    )

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": log_format,
                "datefmt": "%Y-%m-%d %H:%M:%S"
            },
            "detailed": {
                "format": log_format,
                "datefmt": "%Y-%m-%d %H:%M:%S.%f"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stdout"
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": log_dir / "app.log",
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,      # 保留 5 个备份
                "formatter": "detailed"
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": log_dir / "error.log",
                "maxBytes": 10485760,
                "backupCount": 5,
                "formatter": "detailed",
                "level": "ERROR"
            }
        },
        "loggers": {
            "src": {
                "handlers": ["console", "file", "error_file"],
                "level": level,
                "propagate": False
            },
            "src.agents": {
                "handlers": ["console", "file"],
                "level": "DEBUG",  # 更详细的日志
                "propagate": False
            },
            "src.llm": {
                "handlers": ["console", "file"],
                "level": "DEBUG",  # LLM 调用需要详细日志
                "propagate": False
            }
        },
        "root": {
            "handlers": ["console", "file"],
            "level": level
        }
    })
```

**日志级别说明**：

| 级别 | 用途 | 示例 |
|------|------|------|
| **DEBUG** | 详细的调试信息 | 函数参数、中间结果 |
| **INFO** | 一般信息 | 系统启动、任务完成 |
| **WARNING** | 警告信息（不影响运行） | API 调用重试、缓存命中 |
| **ERROR** | 错误信息（需要关注） | API 调用失败、数据处理错误 |
| **CRITICAL** | 严重错误（可能导致系统崩溃） | 内存不足、数据库连接失败 |

---

### 4.3.3 日志分析工具

```python
import re
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

class LogAnalyzer:
    """日志分析器

    用于分析日志文件，提取关键信息，帮助诊断问题
    """

    def __init__(self, log_file: Path):
        self.log_file = log_file

    def parse_log_line(self, line: str) -> Dict:
        """解析日志行

        将日志行解析为结构化数据

        Args:
            line: 日志行

        Returns:
            解析后的字典，包含时间、级别、模块、函数、行号、消息
        """
        pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\S+) \| (\w+) \| ([\w.]+):(\w+):(\d+) \| (.+)"
        match = re.match(pattern, line)

        if match:
            return {
                "timestamp": datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f"),
                "level": match.group(2),
                "logger": match.group(3),
                "func": match.group(4),
                "lineno": int(match.group(5)),
                "message": match.group(6)
            }
        return None

    def count_by_level(self) -> Counter:
        """按级别统计日志

        Returns:
            各级别日志数量的统计
        """
        counter = Counter()
        with open(self.log_file) as f:
            for line in f:
                parsed = self.parse_log_line(line)
                if parsed:
                    counter[parsed["level"]] += 1
        return counter

    def get_error_context(
        self,
        error_time: datetime,
        context_lines: int = 10
    ) -> List[str]:
        """获取错误上下文

        获取错误发生前后的一段日志，帮助理解错误发生的上下文

        Args:
            error_time: 错误发生的时间
            context_lines: 上下文行数（前后各多少行）

        Returns:
            上下文日志列表
        """
        context = []
        with open(self.log_file) as f:
            lines = f.readlines()

        # 找到错误行
        error_idx = None
        for i, line in enumerate(lines):
            parsed = self.parse_log_line(line)
            if parsed and parsed["timestamp"] >= error_time:
                if "ERROR" in line or "Traceback" in line:
                    error_idx = i
                    break

        if error_idx is not None:
            start = max(0, error_idx - context_lines)
            end = min(len(lines), error_idx + context_lines + 1)
            context = lines[start:end]

        return context

    def analyze_errors_by_source(self) -> Dict[str, int]:
        """按来源分析错误

        统计各个模块的错误数量，帮助识别问题热点

        Returns:
            各模块错误数量的字典
        """
        errors_by_source = defaultdict(int)

        with open(self.log_file) as f:
            for line in f:
                if "ERROR" in line or "Traceback" in line:
                    parsed = self.parse_log_line(line)
                    if parsed:
                        errors_by_source[parsed["logger"]] += 1

        return dict(errors_by_source)
```

**使用示例**：

```python
# 初始化日志分析器
analyzer = LogAnalyzer(Path("logs/app.log"))

# 按级别统计
level_counts = analyzer.count_by_level()
print("日志级别统计：", level_counts)

# 按来源分析错误
errors_by_source = analyzer.analyze_errors_by_source()
print("错误来源统计：", errors_by_source)

# 获取错误上下文
error_context = analyzer.get_error_context(
    error_time=datetime.now() - timedelta(minutes=10),
    context_lines=5
)
print("错误上下文：")
for line in error_context:
    print(line.rstrip())
```

---

## 4.4 远程调试

### 4.4.1 为什么需要远程调试？

**场景**：
- 生产环境出现 bug，无法在本地复现
- 需要在服务器上调试运行中的程序
- 多人协作调试同一个问题

**传统方式的局限性**：
- 添加 `print` 语句 → 需要重新部署
- 查看日志 → 信息可能不充分
- 推测问题 → 容易误判

**远程调试的优势**：
- ✅ 实时查看变量值
- ✅ 设置断点，逐行执行
- ✅ 无需重启服务
- ✅ 可以修改代码热重载（部分情况）

---

### 4.4.2 远程调试配置

使用 **debugpy**（Python 调试器）实现远程调试：

```python
import debugpy
import os

def enable_remote_debugging(
    host: str = "0.0.0.0",
    port: int = 5678,
    wait_for_client: bool = False
):
    """启用远程调试

    使用 debugpy 启动远程调试服务器，允许 VS Code 等调试器连接

    Args:
        host: 监听地址（0.0.0.0 表示监听所有网络接口）
        port: 监听端口
        wait_for_client: 是否等待调试器连接

    使用方法：
        1. 在代码中调用此函数
        2. 在 VS Code 中配置 launch.json：
           {
               "type": "debugpy",
               "request": "attach",
               "connect": {"host": "localhost", "port": 5678}
           }
        3. 启动 VS Code 调试
    """
    if os.getenv("DEBUG_MODE") == "true":
        debugpy.listen((host, port))

        if wait_for_client:
            print(f"⏳ 等待调试器连接 {host}:{port}...")
            debugpy.wait_for_client()

        print(f"🔧 调试器已启动，监听 {host}:{port}")
```

**VS Code 配置示例**：

在 `.vscode/launch.json` 中添加：

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "远程调试",
      "type": "debugpy",
      "request": "attach",
      "connect": {
        "host": "your-server-ip",
        "port": 5678
      },
      "pathMappings": [
        {
          "localRoot": "${workspaceFolder}",
          "remoteRoot": "/path/to/app/on/server"
        }
      ]
    }
  ]
}
```

---

### 4.4.3 性能分析

#### 为什么需要性能分析？

**性能问题的影响**：
- 用户体验差：响应时间慢
- 资源浪费：CPU、内存使用率高
- 成本增加：云服务按使用量计费

**性能分析的价值**：
- 识别瓶颈：找到最耗时的函数
- 优化决策：知道优化哪个部分收益最大
- 验证效果：量化优化前后的性能提升

#### Pyroscope 配置

使用 **Pyroscope**（连续性能分析工具）进行性能分析：

```python
import pyroscope
from contextlib import contextmanager

@contextmanager
def profile_segment(segment_name: str):
    """性能分析片段

    用于分析特定代码段的性能

    Args:
        segment_name: 片段名称

    使用示例：
        with profile_segment("data_processing"):
            # 你的代码
            process_data()
    """
    pyroscope.tag({"segment": segment_name})
    try:
        yield
    finally:
        pass

# Pyroscope 配置
pyroscope.configure(
    application_name="ai-hedge-fund",
    server_address="http://localhost:4040",
    tags={"environment": os.getenv("ENV", "development")}
)

class PerformanceProfiler:
    """性能分析器

    用于分析和记录函数执行时间
    """

    def __init__(self):
        self.profiles = {}

    def profile_function(self, func_name: str):
        """函数性能分析装饰器

        自动记录函数执行时间

        Args:
            func_name: 函数名称

        使用示例：
            profiler = PerformanceProfiler()

            @profiler.profile_function("analyze_stock")
            def analyze_stock(ticker: str):
                # 函数实现
                pass
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                with pyroscope.tag({f"function.{func_name}": "running"}):
                    result = func(*args, **kwargs)
                return result
            return wrapper
        return decorator
```

#### 性能分析工具对比

| 工具 | 特点 | 适用场景 |
|------|------|----------|
| **cProfile** | Python 内置，详细 | 分析函数调用次数和时间 |
| **Py-Spy** | 采样分析，低开销 | 生产环境性能分析 |
| **Pyroscope** | 连续分析，可视化 | 长期性能监控 |
| **memory_profiler** | 内存分析 | 内存泄漏排查 |

---

## 4.5 生产环境问题处理

### 4.5.1 优雅降级与熔断器

#### 为什么需要优雅降级？

**问题**：当依赖的服务不可用时，系统应该如何处理？

**选项对比**：

| 处理方式 | 优点 | 缺点 | 适用场景 |
|---------|------|------|----------|
| **直接失败** | 实现简单 | 用户体验差，可能导致级联故障 | 关键路径，必须有准确结果 |
| **等待重试** | 可能恢复成功 | 延长响应时间，可能超时 | 暂时性故障 |
| **优雅降级** | 用户体验好 | 结果可能不准确 | 非关键功能，可以接受近似结果 |

**优雅降级的设计理念**：
> **"总比完全失败好"** - 即使某些功能不可用，系统仍能提供部分服务

**典型场景**：
- LLM API 不可用 → 使用缓存的历史分析结果
- 实时数据获取失败 → 使用最近的数据
- 推荐服务故障 → 使用默认推荐

---

### 4.5.2 熔断器模式

#### 什么是熔断器？

**熔断器模式（Circuit Breaker Pattern）**是一种设计模式，用于防止系统过载和级联故障。

**核心思想**：
> 当检测到某个服务频繁失败时，暂时断开该服务的调用，快速失败，避免影响整个系统。

#### 熔断器状态机

```
    ┌─────────┐
    │ Closed  │  (正常，请求通过)
    │  (关闭)  │
    └────┬────┘
         │ 失败次数超过阈值
         ▼
    ┌─────────┐
    │  Open   │  (熔断，快速失败)
    │  (打开)  │
    └────┬────┘
         │ 超时时间到达
         ▼
    ┌─────────┐
    │Half-Open│  (半开，试探性请求)
    │  (半开)  │
    └────┬────┘
         │
         ├── 成功 → Closed (恢复)
         └── 失败 → Open (继续熔断)
```

#### 熔断器实现

```python
from functools import wraps
from typing import Callable, Any
from datetime import datetime

class GracefulDegradation:
    """优雅降级管理器

    管理服务的降级策略和熔断器
    """

    def __init__(self):
        self.fallbacks = {}      # 降级函数注册表
        self.circuit_breakers = {}  # 熔断器注册表

    def fallback(self, service_name: str):
        """注册降级函数

        Args:
            service_name: 服务名称

        使用示例：
            degradation = GracefulDegradation()

            @degradation.fallback("llm_service")
            def llm_fallback(prompt: str):
                return "服务暂时不可用，请稍后重试"
        """
        def decorator(func: Callable) -> Callable:
            self.fallbacks[service_name] = func
            return func
        return decorator

    def with_circuit_breaker(
        self,
        service_name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60
    ):
        """熔断器装饰器

        为函数添加熔断器保护

        Args:
            service_name: 服务名称
            failure_threshold: 失败阈值（连续失败多少次后熔断）
            recovery_timeout: 恢复超时时间（秒）

        使用示例：
            degradation = GracefulDegradation()

            @degradation.with_circuit_breaker("llm_service")
            def call_llm_api(prompt: str):
                # API 调用
                pass
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                breaker = self.circuit_breakers.get(service_name)
                if not breaker:
                    breaker = CircuitBreaker(failure_threshold, recovery_timeout)
                    self.circuit_breakers[service_name] = breaker

                if breaker.is_open():
                    # 熔断器打开，执行降级
                    fallback = self.fallbacks.get(service_name)
                    if fallback:
                        return fallback(*args, **kwargs)
                    raise CircuitBreakerOpenError(f"熔断器已打开：{service_name}")

                try:
                    result = func(*args, **kwargs)
                    breaker.record_success()
                    return result
                except Exception as e:
                    breaker.record_failure()

                    # 执行降级
                    fallback = self.fallbacks.get(service_name)
                    if fallback:
                        return fallback(*args, **kwargs)
                    raise
            return wrapper
        return decorator


class CircuitBreaker:
    """熔断器实现

    熔断器有三个状态：
    - closed: 正常状态，请求通过
    - open: 熔断状态，请求快速失败
    - half_open: 半开状态，试探性请求，检查服务是否恢复
    """

    def __init__(
        self,
        failure_threshold: int,
        recovery_timeout: int
    ):
        """初始化熔断器

        Args:
            failure_threshold: 失败阈值
            recovery_timeout: 恢复超时时间（秒）
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure = None
        self.state = "closed"  # closed, open, half_open

    def record_success(self):
        """记录成功"""
        self.failures = 0
        self.state = "closed"

    def record_failure(self):
        """记录失败"""
        self.failures += 1
        self.last_failure = datetime.now()

        if self.failures >= self.failure_threshold:
            self.state = "open"

    def is_open(self) -> bool:
        """检查熔断器是否打开

        Returns:
            bool: 如果熔断器打开返回 True
        """
        if self.state == "open":
            # 检查是否可以进入半开状态
            if (datetime.now() - self.last_failure).seconds > self.recovery_timeout:
                self.state = "half_open"
                return False
            return True
        return False


class CircuitBreakerOpenError(Exception):
    """熔断器打开异常"""
    pass
```

#### 使用示例

```python
# 初始化降级管理器
degradation = GracefulDegradation()

# 注册降级函数
@degradation.fallback("llm_service")
def llm_fallback(prompt: str):
    """LLM 服务降级函数"""
    print("⚠️ LLM 服务降级：使用缓存结果")
    # 从缓存获取或返回默认值
    return get_cached_analysis(prompt)

# 使用熔断器保护函数
@degradation.with_circuit_breaker(
    service_name="llm_service",
    failure_threshold=5,
    recovery_timeout=60
)
def call_llm_api(prompt: str):
    """调用 LLM API"""
    # 实际 API 调用
    return llm_client.generate(prompt)

# 使用
try:
    result = call_llm_api("分析 AAPL 股票")
    print(result)
except CircuitBreakerOpenError as e:
    print(f"熔断器已打开：{e}")
```

---

### 4.5.3 紧急恢复步骤

#### 为什么需要紧急恢复预案？

**生产环境问题**：
- 问题可能随时发生
- 需要快速响应，减少停机时间
- 压力大，容易慌乱，忘记最佳实践

**紧急恢复预案的价值**：
- ✅ 快速行动，无需思考
- ✅ 减少人为错误
- ✅ 降低心理压力

#### 紧急恢复检查清单

```python
class EmergencyRecovery:
    """紧急恢复指南

    提供常见生产环境问题的紧急恢复步骤
    """

    RECOVERY_STEPS = {
        "high_memory": [
            "1. 检查内存使用情况：`docker stats` 或 `htop`",
            "2. 重启服务：`docker-compose restart`",
            "3. 清理缓存：`python -c \"from src.cache import clear_all; clear_all()\"`",
            "4. 如果问题持续，扩展服务器内存或限制并发数"
        ],
        "high_cpu": [
            "1. 检查 CPU 使用情况：`top -p $(pgrep -f python)`",
            "2. 分析性能瓶颈：`python -m cProfile -s cumulative src/main.py`",
            "3. 如果是特定分析导致，考虑限制并发数或优化代码",
            "4. 重启服务"
        ],
        "api_failures": [
            "1. 检查 API 提供商状态页面（status.openai.com 等）",
            "2. 验证 API 密钥是否有效（在提供商控制台检查）",
            "3. 尝试切换到备用 API 提供商",
            "4. 如果所有 API 都不可用，启用缓存模式或降级服务"
        ],
        "disk_full": [
            "1. 检查磁盘使用：`df -h`",
            "2. 清理日志文件：`rm -rf logs/*.log.*`",
            "3. 清理临时文件：`rm -rf tmp/*`",
            "4. 清理旧数据：删除过期的回测结果和缓存"
        ],
        "database_connection_failure": [
            "1. 检查数据库服务是否运行：`systemctl status postgresql`",
            "2. 验证连接配置：检查数据库 URL、用户名、密码",
            "3. 测试网络连接：`ping database-host`",
            "4. 查看数据库日志：`tail -f /var/log/postgresql/postgresql.log`"
        ]
    }

    @classmethod
    def get_recovery_steps(cls, issue_type: str) -> List[str]:
        """获取恢复步骤

        Args:
            issue_type: 问题类型

        Returns:
            恢复步骤列表
        """
        return cls.RECOVERY_STEPS.get(issue_type, [
            "请描述问题现象并联系技术支持",
            "收集以下信息：",
            "  - 问题发生时间",
            "  - 错误日志",
            "  - 系统状态（CPU、内存、磁盘）"
        ])
```

#### 生产环境问题诊断流程

```
问题发生
    │
    ▼
收集信息
    ├── 检查错误日志
    ├── 检查系统状态（CPU、内存、磁盘）
    └── 检查 API 服务状态
    │
    ▼
识别问题类型
    ├── 内存问题？
    ├── CPU 问题？
    ├── API 失败？
    ├── 磁盘满？
    └── 数据库连接失败？
    │
    ▼
执行恢复步骤
    ├── 查询紧急恢复检查清单
    └── 按步骤执行
    │
    ▼
验证恢复效果
    ├── 问题是否解决？
    ├── 服务是否正常运行？
    └── 监控指标是否正常？
    │
    ▼
    ├── 是 → 记录问题，更新文档
    └── 否 → 升级处理，联系技术支持
```

---

## 4.6 练习题

### 练习 4.1：诊断系统实现 ⭐⭐

**任务目标**：实现完整的诊断框架，能够自动诊断常见问题

**具体要求**：

1. **基础功能**：
   - [ ] 实现 `DiagnosticFramework` 类
   - [ ] 实现 `APIKeyDiagnoser`、`LLMAPIDiagnoser`、`DataDiagnoser` 三个诊断器
   - [ ] 测试每个诊断器能否正确识别和诊断对应错误

2. **扩展功能**（进阶）：
   - [ ] 添加一个新的诊断器，用于诊断网络连接问题
   - [ ] 实现诊断报告的导出功能（导出为 JSON 或 Markdown）
   - [ ] 添加诊断历史查询功能

3. **验证标准**：
   ```python
   # 测试用例示例
   framework = DiagnosticFramework()
   framework.register_diagnoser(APIKeyDiagnoser())

   # 测试 1：诊断 API 密钥问题
   error = APIKeyNotFoundError("OPENAI_API_KEY")
   result = framework.diagnose(error)
   assert result.category == ProblemCategory.CONFIGURATION
   assert len(result.recommended_actions) > 0

   # 测试 2：诊断未知问题
   error = ValueError("Unknown error")
   result = framework.diagnose(error)
   assert result.category == ProblemCategory.UNKNOWN
   ```

**参考答案框架**：

```python
# 提示：参考 4.1.3 的代码实现
# 需要补充：
# 1. 定义自定义异常类
class APIKeyNotFoundError(Exception):
    def __init__(self, key_name):
        self.key_name = key_name
        super().__init__(f"API key not found: {key_name}")

# 2. 完善诊断器实现（见 4.2 节）

# 3. 编写测试代码
def test_diagnosers():
    framework = DiagnosticFramework()
    # 注册所有诊断器
    # 编写测试用例
```

**评估标准**：
- ⭐ 基础功能完整，测试通过
- ⭐⭐ 扩展功能实现，代码质量高
- ⭐⭐⭐ 有额外的创新功能（如自动化修复建议）

---

### 练习 4.2：故障恢复演练 ⭐⭐⭐

**任务目标**：设计并执行故障恢复演练，验证恢复流程的有效性

**具体要求**：

1. **场景设计**：
   - [ ] 场景 1：模拟 LLM API 故障（通过修改 API 密钥为无效值）
   - [ ] 场景 2：模拟内存不足（创建大量对象）
   - [ ] 场景 3：模拟网络中断（断开网络或修改 DNS）

2. **演练步骤**：
   - [ ] 记录正常状态的系统指标（CPU、内存、响应时间）
   - [ ] 触发故障
   - [ ] 按照紧急恢复步骤执行恢复
   - [ ] 验证恢复效果

3. **文档记录**：
   - [ ] 记录每个场景的问题现象
   - [ ] 记录恢复过程和遇到的问题
   - [ ] 记录恢复时间和效果
   - [ ] 更新紧急恢复检查清单

**演练模板**：

```markdown
# 故障恢复演练报告

## 场景 1：LLM API 故障

**演练时间**：2024-XX-XX XX:XX
**演练人员**：XXX

### 演练步骤

1. 正常状态记录
   - CPU: XX%
   - 内存: XX%
   - 响应时间: XX ms

2. 触发故障
   - 方法：将 OPENAI_API_KEY 设置为无效值
   - 预期现象：所有 LLM 调用失败

3. 实际现象
   - 错误信息：...

4. 恢复过程
   - 步骤 1：检查 API 服务状态
   - 步骤 2：验证 API 密钥
   - 步骤 3：...

5. 恢复效果
   - 服务是否恢复：是/否
   - 恢复时间：XX 分钟
   - 经验总结：...

### 改进建议

- 建议 1：...
- 建议 2：...
```

**评估标准**：
- ⭐ 完成 1 个场景的演练
- ⭐⭐ 完成 2-3 个场景的演练，文档完整
- ⭐⭐⭐ 完成 3+ 场景的演练，提出有效改进建议

---

### 练习 4.3：监控告警系统 ⭐⭐⭐

**任务目标**：建立监控告警系统，能够自动检测异常情况并发送告警

**具体要求**：

1. **监控指标**：
   - [ ] CPU 使用率超过 80%
   - [ ] 内存使用率超过 90%
   - [ ] 磁盘使用率超过 85%
   - [ ] API 调用失败率超过 5%
   - [ ] 错误日志数量激增（5 分钟内超过 100 条）

2. **告警方式**：
   - [ ] 控制台输出
   - [ ] 发送邮件（可选）
   - [ ] 发送到 Webhook（可选）

3. **告警规则**：
   - [ ] 支持阈值配置
   - [ ] 支持告警抑制（避免重复告警）
   - [ ] 支持告警恢复通知

**实现框架**：

```python
class MonitoringSystem:
    """监控系统"""

    def __init__(self):
        self.alert_rules = []
        self.alert_history = []

    def add_alert_rule(self, rule: AlertRule):
        """添加告警规则"""
        self.alert_rules.append(rule)

    def check_metrics(self):
        """检查指标"""
        for rule in self.alert_rules:
            if rule.is_triggered():
                alert = Alert(
                    severity=rule.severity,
                    message=rule.message,
                    metrics=rule.current_metrics()
                )
                self.send_alert(alert)

    def send_alert(self, alert: Alert):
        """发送告警"""
        # 实现告警发送逻辑
        pass


class AlertRule:
    """告警规则"""

    def __init__(
        self,
        name: str,
        metric: str,
        threshold: float,
        severity: str
    ):
        self.name = name
        self.metric = metric
        self.threshold = threshold
        self.severity = severity

    def is_triggered(self) -> bool:
        """检查是否触发告警"""
        current_value = self.get_current_value()
        return current_value > self.threshold

    def get_current_value(self) -> float:
        """获取当前指标值"""
        # 实现指标获取逻辑
        pass
```

**评估标准**：
- ⭐ 实现 CPU 和内存监控
- ⭐⭐ 实现多种指标监控和邮件告警
- ⭐⭐⭐ 实现完整的监控系统，包括告警抑制和恢复通知

---

## 4.7 总结与进阶学习

### 本章核心知识点

| 知识点 | 重要性 | 应用场景 |
|--------|--------|----------|
| **问题分类体系** | ⭐⭐⭐⭐⭐ | 快速识别问题类型 |
| **诊断框架设计** | ⭐⭐⭐⭐ | 建立可扩展的诊断系统 |
| **日志分析与配置** | ⭐⭐⭐⭐⭐ | 生产环境问题排查 |
| **熔断器模式** | ⭐⭐⭐⭐ | 防止级联故障 |
| **优雅降级** | ⭐⭐⭐⭐ | 提高系统可用性 |
| **远程调试** | ⭐⭐⭐ | 生产环境调试 |
| **性能分析** | ⭐⭐⭐⭐ | 性能优化 |

### 常见误区

| 误区 | 正确理解 |
|------|----------|
| "遇到问题就重启" | 重启可以暂时缓解，但不能解决根本原因 |
| "日志越多越好" | 日志过多会降低性能，影响问题定位 |
| "熔断器影响性能" | 熔断器可以防止系统过载，提高整体可用性 |
| "只有生产环境才需要监控" | 开发环境也需要监控，可以早期发现问题 |

### 进阶学习路径

1. **深入学习设计模式**：
   - 学习更多设计模式（如观察者模式、责任链模式）
   - 理解设计模式在故障处理中的应用

2. **分布式系统可靠性**：
   - 学习 CAP 理论、分布式事务
   - 了解高可用架构设计

3. **自动化运维**：
   - 学习 Docker、Kubernetes
   - 了解 CI/CD、自动化部署

4. **监控与告警最佳实践**：
   - 学习 Prometheus、Grafana
   - 了解 APM（应用性能管理）工具

### 推荐资源

- **书籍**：
  - 《SRE：Google 运维解密》
  - 《凤凰项目：一个运维主管的 IT 之旅》
  - 《Release It!》

- **在线资源**：
  - Google Cloud 的 SRE 文档
  - Netflix 的技术博客（故障处理最佳实践）
  - Chaos Engineering（混沌工程）相关资源

---

## 4.8 自检清单

完成本章学习后，请自检以下能力：

### 基础技能
- [ ] 能够识别系统问题的类型（配置/网络/数据/资源/逻辑）
- [ ] 能够配置和使用日志系统
- [ ] 能够从日志中提取关键信息
- [ ] 理解熔断器和优雅降级的概念

### 进阶技能
- [ ] 能够设计和实现诊断框架
- [ ] 能够实现远程调试
- [ ] 能够使用性能分析工具
- [ ] 能够实现熔断器和优雅降级

### 专家技能
- [ ] 能够建立监控告警系统
- [ ] 能够制定生产环境的故障恢复预案
- [ ] 能够分析和解决复杂的级联故障
- [ ] 能够设计高可用架构

---

**🎉 恭喜！** 完成本章学习后，你已经掌握了系统故障排除的核心知识和实践技能。下一步可以：
1. 实践练习 4.1-4.3，巩固所学知识
2. 阅读 Level 4 的专家文档，深入了解系统设计
3. 参与开源项目，积累实际故障处理经验
