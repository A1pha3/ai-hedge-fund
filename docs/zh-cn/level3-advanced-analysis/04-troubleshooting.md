# 第四章：故障排除手册

## 学习目标

完成本章节学习后，你将能够系统性地诊断和解决系统运行中的常见问题，掌握日志分析和调试技术，建立问题排查的最佳实践，以及能够快速定位和修复生产环境问题。预计学习时间为 1.5-2 小时。

## 4.1 问题分类与诊断框架

### 问题分类体系

系统故障可以分为以下几类，每类问题有特定的诊断和解决方案。

**配置问题**：API 密钥错误、环境变量缺失、配置文件错误等。这类问题通常在启动时就能被发现。

**网络问题**：API 超时、连接失败、DNS 解析失败等。这类问题通常表现为间歇性错误。

**数据问题**：数据获取失败、数据格式错误、数据不一致等。这类问题可能导致分析结果异常。

**资源问题**：内存不足、CPU 过载、磁盘空间不足等。这类问题通常会导致性能下降或服务中断。

**逻辑问题**：代码缺陷、算法错误、状态管理问题等。这类问题通常需要深入代码分析。

### 诊断框架

```python
from enum import Enum
from typing import Dict, List, Any
from dataclasses import dataclass
from datetime import datetime

class ProblemCategory(Enum):
    CONFIGURATION = "configuration"
    NETWORK = "network"
    DATA = "data"
    RESOURCE = "resource"
    LOGIC = "logic"
    UNKNOWN = "unknown"

@dataclass
class DiagnosticResult:
    """诊断结果"""
    category: ProblemCategory
    description: str
    evidence: Dict[str, Any]
    possible_causes: List[str]
    recommended_actions: List[str]
    severity: str

class DiagnosticFramework:
    """诊断框架"""
    
    def __init__(self):
        self.diagnosers = []
        self.diagnosis_history = []
    
    def register_diagnoser(self, diagnoser: 'Diagnoser'):
        """注册诊断器"""
        self.diagnosers.append(diagnoser)
    
    def diagnose(self, error: Exception) -> DiagnosticResult:
        """执行诊断"""
        for diagnoser in self.diagnosers:
            if diagnoser.can_diagnose(error):
                result = diagnoser.diagnose(error)
                self.diagnosis_history.append(result)
                return result
        
        return DiagnosticResult(
            category=ProblemCategory.UNKNOWN,
            description=str(error),
            evidence={},
            possible_causes=["未知原因"],
            recommended_actions=["联系技术支持"],
            severity="unknown"
        )
```

## 4.2 常见问题与解决方案

### API 密钥配置问题

**症状**：启动时报告 `APIKeyNotFoundError` 或 `AuthenticationError`。

**诊断步骤**：

```python
class APIKeyDiagnoser:
    """API 密钥诊断器"""
    
    def can_diagnose(self, error: Exception) -> bool:
        return isinstance(error, (APIKeyNotFoundError, AuthenticationError))
    
    def diagnose(self, error: Exception) -> DiagnosticResult:
        evidence = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "environment_variables": self._check_env_vars(),
            "dotenv_file": self._check_dotenv_file()
        }
        
        possible_causes = []
        recommended_actions = []
        
        if evidence["dotenv_file"] == "missing":
            possible_causes.append(".env 文件不存在")
            recommended_actions.append("创建 .env 文件：cp .env.example .env")
        
        if not evidence["environment_variables"].get("OPENAI_API_KEY"):
            possible_causes.append("OPENAI_API_KEY 未设置")
            recommended_actions.append("在 .env 文件中添加 OPENAI_API_KEY")
        
        return DiagnosticResult(
            category=ProblemCategory.CONFIGURATION,
            description="API 密钥配置问题",
            evidence=evidence,
            possible_causes=possible_causes,
            recommended_actions=recommended_actions,
            severity="high"
        )
    
    def _check_env_vars(self) -> Dict[str, str]:
        import os
        return {
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "NOT SET"),
            "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "NOT SET"),
            "FINANCIAL_DATASETS_API_KEY": os.getenv("FINANCIAL_DATASETS_API_KEY", "NOT SET")
        }
    
    def _check_dotenv_file(self) -> str:
        import os
        if os.path.exists(".env"):
            return "exists"
        return "missing"
```

### LLM API 调用失败

**症状**：分析过程中报告 `LLMTimeoutError`、`RateLimitError` 或 `ServiceUnavailableError`。

**诊断步骤**：

```python
class LLMAPIDiagnoser:
    """LLM API 诊断器"""
    
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
        
        if isinstance(error, RateLimitError):
            possible_causes.append("API 调用频率超过限制")
            possible_causes.append("账户配额已用尽")
            recommended_actions.append("添加 API 密钥轮换")
            recommended_actions.append("实现请求限流")
            recommended_actions.append("升级账户配额")
        
        if isinstance(error, LLMTimeoutError):
            possible_causes.append("网络连接不稳定")
            possible_causes.append("API 服务响应慢")
            possible_causes.append("请求内容过长")
            recommended_actions.append("增加超时时间")
            recommended_actions.append("缩短提示词长度")
            recommended_actions.append("尝试其他 LLM 提供商")
        
        return DiagnosticResult(
            category=ProblemCategory.NETWORK,
            description="LLM API 调用失败",
            evidence=evidence,
            possible_causes=possible_causes,
            recommended_actions=recommended_actions,
            severity="medium"
        )
```

### 数据获取失败

**症状**：报告 `DataNotFoundError`、`DataFormatError` 或 `APIError`。

**诊断步骤**：

```python
class DataDiagnoser:
    """数据获取诊断器"""
    
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
            possible_causes.append("股票代码无效")
            possible_causes.append("日期范围超出数据覆盖范围")
            possible_causes.append("数据提供商不支持该股票")
            recommended_actions.append("验证股票代码是否正确")
            recommended_actions.append("检查日期范围")
            recommended_actions.append("尝试使用备用数据源")
        
        if isinstance(error, DataFormatError):
            possible_causes.append("数据格式发生变化")
            possible_causes.append("数据提供商 API 升级")
            recommended_actions.append("更新数据解析代码")
            recommended_actions.append("联系数据提供商确认")
        
        return DiagnosticResult(
            category=ProblemCategory.DATA,
            description="数据获取失败",
            evidence=evidence,
            possible_causes=possible_causes,
            recommended_actions=recommended_actions,
            severity="medium"
        )
```

## 4.3 日志分析与调试

### 日志配置

```python
import logging
import logging.config
from pathlib import Path

def setup_logging(
    log_dir: Path = Path("logs"),
    level: str = "INFO",
    format: str = None
):
    """配置日志"""
    log_dir.mkdir(parents=True, exist_ok=True)
    
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
                "backupCount": 5,
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
                "level": "DEBUG",
                "propagate": False
            },
            "src.llm": {
                "handlers": ["console", "file"],
                "level": "DEBUG",
                "propagate": False
            }
        },
        "root": {
            "handlers": ["console", "file"],
            "level": level
        }
    })
```

### 日志分析工具

```python
import re
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

class LogAnalyzer:
    """日志分析器"""
    
    def __init__(self, log_file: Path):
        self.log_file = log_file
    
    def parse_log_line(self, line: str) -> Dict:
        """解析日志行"""
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
        """按级别统计"""
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
        """获取错误上下文"""
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
        """按来源分析错误"""
        errors_by_source = defaultdict(int)
        
        with open(self.log_file) as f:
            for line in f:
                if "ERROR" in line or "Traceback" in line:
                    parsed = self.parse_log_line(line)
                    if parsed:
                        errors_by_source[parsed["logger"]] += 1
        
        return dict(errors_by_source)
```

## 4.4 远程调试

### 远程调试配置

```python
import debugpy
import os

def enable_remote_debugging(
    host: str = "0.0.0.0",
    port: int = 5678,
    wait_for_client: bool = False
):
    """启用远程调试"""
    if os.getenv("DEBUG_MODE") == "true":
        debugpy.listen((host, port))
        
        if wait_for_client:
            print(f"Waiting for debugger connection on {host}:{port}")
            debugpy.wait_for_client()
        
        print(f"Debugger listening on {host}:{port}")
```

### 性能分析

```python
import pyroscope
from contextlib import contextmanager

@contextmanager
def profile_segment(segment_name: str):
    """性能分析片段"""
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
    """性能分析器"""
    
    def __init__(self):
        self.profiles = {}
    
    def profile_function(self, func_name: str):
        """函数性能分析装饰器"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                with pyroscope.tag({f"function.{func_name}": "running"}):
                    result = func(*args, **kwargs)
                return result
            return wrapper
        return decorator
```

## 4.5 生产环境问题处理

### 优雅降级

```python
from functools import wraps
from typing import Callable, Any

class GracefulDegradation:
    """优雅降级管理器"""
    
    def __init__(self):
        self.fallbacks = {}
        self.circuit_breakers = {}
    
    def fallback(self, service_name: str):
        """注册降级函数"""
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
        """熔断器装饰器"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                breaker = self.circuit_breakers.get(service_name)
                if not breaker:
                    breaker = CircuitBreaker(
                        failure_threshold,
                        recovery_timeout
                    )
                    self.circuit_breakers[service_name] = breaker
                
                if breaker.is_open():
                    # 熔断器打开，执行降级
                    fallback = self.fallbacks.get(service_name)
                    if fallback:
                        return fallback(*args, **kwargs)
                    raise CircuitBreakerOpenError(service_name)
                
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
    """熔断器"""
    
    def __init__(
        self,
        failure_threshold: int,
        recovery_timeout: int
    ):
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
        """检查熔断器是否打开"""
        if self.state == "open":
            if (datetime.now() - self.last_failure).seconds > self.recovery_timeout:
                self.state = "half_open"
                return False
            return True
        return False
```

### 紧急恢复步骤

```python
class EmergencyRecovery:
    """紧急恢复指南"""
    
    RECOVERY_STEPS = {
        "high_memory": [
            "1. 检查内存使用情况：docker stats 或 htop",
            "2. 重启服务：docker-compose restart",
            "3. 清理缓存：docker-compose exec app python -c \"from src.cache import clear_all; clear_all()\"",
            "4. 如果问题持续，扩展服务器内存"
        ],
        "high_cpu": [
            "1. 检查 CPU 使用情况：top -p $(pgrep -f python)",
            "2. 分析性能瓶颈：python -m cProfile -s cumulative src/main.py",
            "3. 如果是特定分析导致，考虑限制并发数",
            "4. 重启服务"
        ],
        "api_failures": [
            "1. 检查 API 提供商状态页面",
            "2. 验证 API 密钥是否有效",
            "3. 尝试切换到备用 API 提供商",
            "4. 如果所有 API 都不可用，启用缓存模式"
        ],
        "disk_full": [
            "1. 检查磁盘使用：df -h",
            "2. 清理日志文件：rm -rf logs/*.log.*",
            "3. 清理临时文件：rm -rf tmp/*",
            "4. 清理旧数据：删除过期回测结果"
        ]
    }
    
    @classmethod
    def get_recovery_steps(cls, issue_type: str) -> List[str]:
        """获取恢复步骤"""
        return cls.RECOVERY_STEPS.get(issue_type, [
            "请描述问题现象并联系技术支持"
        ])
```

## 4.6 练习题

### 练习 4.1：诊断系统实现

**任务**：实现完整的诊断框架。

**要求**：能够自动诊断常见问题，生成诊断报告，提供解决建议。

### 练习 4.2：故障恢复演练

**任务**：设计并执行故障恢复演练。

**场景**：模拟 API 故障、内存溢出、网络中断等情况，测试恢复流程。

### 练习 4.3：监控告警系统

**任务**：建立监控告警系统。

**要求**：能够自动检测异常情况，及时发送告警，提供故障诊断信息。
