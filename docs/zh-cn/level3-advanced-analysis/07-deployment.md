# 第七章：生产环境部署指南

## 学习目标

完成本章节学习后，你将能够理解生产环境部署的关键考虑因素，掌握 Docker 容器化部署的方法，学会配置生产级别的环境和监控，以及能够设置安全加固措施。预计学习时间为 2-3 小时。

## 7.1 生产环境概述

### 生产环境与开发环境的区别

开发环境用于日常开发和测试，而生产环境需要满足高可用性、安全性和性能要求。生产环境部署需要考虑以下关键差异。

**可靠性要求**：开发环境可以容忍服务中断和错误，而生产环境需要 99.9% 以上的可用性。这意味着需要实现健康检查、自动重启和故障转移机制。

**安全性要求**：开发环境使用测试 API 密钥和简化配置，而生产环境需要严格的安全策略，包括 API 密钥管理、网络隔离、访问控制和审计日志。

**性能要求**：开发环境关注功能正确性，而生产环境需要优化响应延迟、吞吐量和资源利用率。性能监控和自动扩缩容是生产环境的标准配置。

**可观测性要求**：开发环境依赖本地调试，而生产环境需要完整的日志、指标和追踪系统，以便快速定位和解决问题。

### 部署架构选择

AI Hedge Fund 支持多种部署架构，选择取决于使用场景和资源限制。

**单机部署**适合个人用户和小规模使用。一个 Docker 容器运行所有服务，资源消耗较低，配置简单，但可用性有限。

**分布式部署**适合团队协作和高可用需求。将前端、后端、Ollama 分别部署在独立容器，支持水平扩展，需要 Kubernetes 或 Docker Swarm 等编排工具。

**云原生部署**适合生产环境使用。利用云服务商的托管服务（如 AWS ECS、Google Cloud Run），自动扩缩容，内置高可用，但成本较高。

## 7.2 Docker 容器化部署

### 使用 Docker Compose 部署

Docker Compose 是最简单的多服务部署方式，适合大多数生产场景。

**前置条件**：安装 Docker Engine 20.10+ 和 Docker Compose V2。

**部署步骤**：

第一步，克隆项目并进入 docker 目录：

```bash
git clone https://github.com/virattt/ai-hedge-fund.git
cd ai-hedge-fund/docker
```

第二步，复制环境变量模板并配置：

```bash
cp .env.example .env
nano .env
```

第三步，配置生产环境变量：

```bash
# 生产环境配置示例
FINANCIAL_DATASETS_API_KEY=your-production-api-key

# 选择 LLM 提供商（生产环境建议使用云端 API）
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key

# Ollama 配置（可选，本地部署）
OLLAMA_HOST=ollama
OLLAMA_BASE_URL=http://ollama:11434

# 日志级别（生产环境使用 WARNING 或 ERROR）
LOG_LEVEL=WARNING
```

第四步，启动服务：

```bash
docker-compose up -d
```

第五步，验证服务状态：

```bash
docker-compose ps

# 预期输出：
# NAME                   STATUS    PORTS
# hedge-fund-backend     Up        0.0.0.0:8000->8000/tcp
# hedge-fund-frontend    Up        0.0.0.0:5173->5173/tcp
# ollama                 Up        0.0.0.0:11434->11434/tcp
```

### Docker Compose 配置详解

**docker-compose.yml 文件结构**：

```yaml
version: '3.8'

services:
  # 后端服务
  backend:
    build:
      context: ../.
      dockerfile: docker/Dockerfile.backend
    container_name: hedge-fund-backend
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - PYTHONUNBUFFERED=1
      - OLLAMA_BASE_URL=http://ollama:11434
      - PYTHONPATH=/app
    env_file:
      - ../.env
    volumes:
      - ../.env:/app/.env:ro
    depends_on:
      - ollama
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  # 前端服务
  frontend:
    build:
      context: ../app/frontend
      dockerfile: Dockerfile
    container_name: hedge-fund-frontend
    restart: unless-stopped
    ports:
      - "5173:5173
```

### 多服务架构部署

对于需要高可用和水平扩展的生产环境，使用多服务架构。

**服务分离部署**：

```yaml
# docker-compose.prod.yml
services:
  # API 网关
  api-gateway:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - backend

  # 后端服务（多副本）
  backend:
    deploy:
      replicas: 3
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]

  # Ollama（可选，本地 LLM）
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  # Redis（会话存储和缓存）
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
```

## 7.3 生产环境配置

### 环境变量配置

生产环境需要严格配置的环境变量。

**必需配置**：

```bash
# LLM API 密钥（生产环境必须设置）
OPENAI_API_KEY=sk-prod-key-xxxxx
ANTHROPIC_API_KEY=prod-key-xxxxx

# Financial Datasets API
FINANCIAL_DATASETS_API_KEY=prod-fd-key-xxxxx

# 安全配置
JWT_SECRET=your-super-secret-jwt-key-change-in-production
ENCRYPTION_KEY=your-encryption-key-32-chars

# 日志配置
LOG_LEVEL=WARNING
LOG_FORMAT=json

# 性能配置
MAX_WORKERS=4
MAX_CONCURRENT_REQUESTS=100
REQUEST_TIMEOUT=60
```

**可选配置**：

```bash
# 监控配置
METRICS_ENABLED=true
METRICS_PORT=9090

# 告警配置
ALERT_WEBHOOK_URL=https://your-slack-webhook.com/xxx
ALERT_EMAIL=admin@example.com

# 资源限制
MEMORY_LIMIT=4G
CPU_LIMIT=2.0
```

### 配置文件最佳实践

**分层配置文件结构**：

```
config/
├── defaults.yaml        # 默认配置
├── development.yaml      # 开发环境
├── staging.yaml         # 预发布环境
└── production.yaml       # 生产环境
```

**配置加载逻辑**：

```python
# src/config/loader.py
from pathlib import Path
from functools import lru_cache
import yaml

@lru_cache()
def load_config(env: str = "production") -> dict:
    config_dir = Path(__file__).parent
    
    # 加载默认配置
    with open(config_dir / "defaults.yaml") as f:
        config = yaml.safe_load(f)
    
    # 加载环境配置
    env_file = config_dir / f"{env}.yaml"
    if env_file.exists():
        with open(env_file) as f:
            env_config = yaml.safe_load(f)
            config.update(env_config)
    
    # 覆盖环境变量
    config["api_keys"] = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        # ...
    }
    
    return config
```

### 性能调优配置

**Uvicorn 工作进程配置**：

```bash
# 使用多个 worker 处理并发请求
poetry run uvicorn app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout-keep-alive 30 \
    --max-requests 1000 \
    --max-requests-jitter 50
```

**连接池配置**：

```python
# src/db/pool.py
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,           # 最小连接数
    max_overflow=20,         # 最大额外连接
    pool_recycle=3600,       # 连接回收时间（秒）
    pool_pre_ping=True,      # 连接前检查
)
```

## 7.4 监控与告警

### 健康检查端点

生产环境必须实现健康检查接口。

```python
# app/backend/health.py
from fastapi import APIRouter
from pydantic import BaseModel
import psutil
import time

router = APIRouter()

class HealthStatus(BaseModel):
    status: str
    uptime_seconds: float
    memory_usage_mb: float
    cpu_percent: float
    active_requests: int

start_time = time.time()

@router.get("/health")
async def health_check() -> HealthStatus:
    """健康检查端点"""
    return HealthStatus(
        status="healthy",
        uptime_seconds=time.time() - start_time,
        memory_usage_mb=psutil.Process().memory_info().rss / 1024 / 1024,
        cpu_percent=psutil.cpu_percent(),
        active_requests=0,  # 从请求追踪获取
    )

@router.get("/ready")
async def readiness_check() -> dict:
    """就绪检查端点"""
    # 检查所有依赖服务
    checks = {
        "database": check_database(),
        "llm_provider": check_llm_provider(),
        "cache": check_cache(),
    }
    
    all_healthy = all(c["healthy"] for c in checks.values())
    
    return {
        "ready": all_healthy,
        "checks": checks,
    }
```

### 指标监控

**使用 Prometheus 指标**：

```python
# src/monitoring/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# 请求指标
REQUEST_COUNT = Counter(
    "hedge_fund_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "hedge_fund_request_duration_seconds",
    "HTTP request latency",
    ["endpoint"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# 业务指标
ACTIVE_AGENTS = Gauge(
    "hedge_fund_active_agents",
    "Number of currently running agents"
)

LLM_CALLS = Counter(
    "hedge_fund_llm_calls_total",
    "Total LLM API calls",
    ["provider", "model"]
)
```

### 日志配置

**结构化日志**：

```python
# src/logging/config.py
import logging
from pythonjsonlogger import jsonlogger

def setup_logging(level: str = "INFO"):
    logger = logging.getLogger("hedge_fund")
    logger.setLevel(getattr(logging, level))
    
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger
```

**日志输出示例**：

```json
{
  "timestamp": "2024-01-15T10:30:00.000Z",
  "level": "INFO",
  "name": "hedge_fund.agents.portfolio",
  "message": "Portfolio decision generated",
  "ticker": "AAPL",
  "decision": "BUY",
  "confidence": 85,
  "latency_ms": 1500
}
```

### 告警规则

**Prometheus 告警规则**：

```yaml
# prometheus/alerts.yml
groups:
  - name: hedge_fund_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(hedge_fund_requests_total{status=~"5.."}[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} in the last 5 minutes"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(hedge_fund_request_duration_seconds_bucket[5m])) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High latency detected"
          description: "P95 latency is {{ $value }} seconds"

      - alert: LLMProviderDown
        expr: hedge_fund_llm_provider_available == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "LLM provider is unavailable"
```

## 7.5 安全加固

### API 安全

**速率限制**：

```python
# src/security/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/analyze")
@limiter.limit("10/minute")
async def analyze(request: Request, ...):
    ...
```

**输入验证**：

```python
# src/security/validation.py
from pydantic import BaseModel, validator
import re

class AnalysisRequest(BaseModel):
    tickers: list[str]
    
    @validator("tickers")
    def validate_tickers(cls, v):
        # 验证股票代码格式
        pattern = re.compile(r"^[A-Z]{1,5}$")
        for ticker in v:
            if not pattern.match(ticker):
                raise ValueError(f"Invalid ticker format: {ticker}")
        return v
    
    @validator("tickers")
    def max_tickers(cls, v):
        if len(v) > 20:
            raise ValueError("Maximum 20 tickers per request")
        return v
```

### 网络安全

**CORS 配置**：

```python
# src/security/cors.py
from fastapi.middleware.cors import CORSMiddleware

origins = [
    "https://your-production-domain.com",
    "https://www.your-production-domain.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
```

**HTTPS 配置**：

```nginx
# nginx.conf
server {
    listen 443 ssl http2;
    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    
    # 安全头
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";
}
```

### 密钥管理

**使用密钥管理服务**：

```python
# src/security/secrets.py
import os
from functools import lru_cache

@lru_cache()
def get_api_key(provider: str) -> str:
    """从环境变量或密钥管理服务获取 API 密钥"""
    
    # 首先检查环境变量
    key = os.getenv(f"{provider.upper()}_API_KEY")
    if key:
        return key
    
    # 从密钥管理服务获取（如 AWS Secrets Manager）
    try:
        from src.integrations.aws_secrets import get_secret
        return get_secret(f"ai-hedge-fund/{provider.lower()}-api-key")
    except ImportError:
        pass
    
    # 从本地加密文件获取
    try:
        from src.integrations.local_vault import get_secret
        return get_secret(f"{provider.lower()}_api_key")
    except ImportError:
        pass
    
    raise ValueError(f"API key not found for provider: {provider}")
```

## 7.6 高可用配置

### 多副本部署

**Kubernetes 部署配置**：

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hedge-fund-backend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: hedge-fund-backend
  template:
    metadata:
      labels:
        app: hedge-fund-backend
    spec:
      containers:
      - name: backend
        image: ghcr.io/virattt/ai-hedge-fund:latest
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        envFrom:
        - secretRef:
            name: api-keys
        - configMapRef:
            name: app-config
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: hedge-fund-service
spec:
  selector:
    app: hedge-fund-backend
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

### 数据库和高可用

**Redis 集群配置**：

```yaml
# docker-compose.redis-cluster.yml
services:
  redis-node-1:
    image: redis:7-alpine
    command: redis-server --cluster-enabled yes --cluster-config-file nodes.conf
    ports:
      - "7001:7001"
  
  redis-node-2:
    image: redis:7-alpine
    command: redis-server --cluster-enabled yes --cluster-config-file nodes.conf
    ports:
      - "7002:7002"
  
  redis-node-3:
    image: redis:7-alpine
    command: redis-server --cluster-enabled yes --cluster-config-file nodes.conf
    ports:
      - "7003:7003"
```

## 7.7 灾难恢复

### 备份策略

**数据备份配置**：

```bash
#!/bin/bash
# scripts/backup.sh

BACKUP_DIR="/backups/ai-hedge-fund"
DATE=$(date +%Y%m%d_%H%M%S)

# 备份 Redis 数据
redis-cli BGSAVE
sleep 5
cp /data/dump.rdb ${BACKUP_DIR}/redis_${DATE}.rdb

# 备份配置
tar -czf ${BACKUP_DIR}/config_${DATE}.tar.gz /app/config/

# 清理旧备份（保留最近 7 天）
find ${BACKUP_DIR} -name "*.rdb" -mtime +7 -delete
find ${BACKUP_DIR} -name "*.tar.gz" -mtime +7 -delete

echo "Backup completed: ${DATE}"
```

### 故障转移

**HAProxy 故障转移配置**：

```haproxy
# haproxy.cfg
frontend hedge_fund_frontend
    bind *:80
    mode http
    default_backend hedge_fund_backend

backend hedge_fund_backend
    mode http
    balance roundrobin
    option httpchk GET /health
    server backend1 10.0.0.1:8000 check weight 100
    server backend2 10.0.0.2:8000 check weight 100 backup
    server backend3 10.0.0.3:8000 check weight 100 backup
```

## 7.8 部署检查清单

### 部署前检查

| 检查项 | 状态 | 说明 |
|--------|------|------|
| API 密钥配置 | ☐ | 所有必需的环境变量已设置 |
| SSL 证书 | ☐ | 有效证书已安装 |
| 防火墙规则 | ☐ | 必要的端口已开放，不必要的已关闭 |
| 资源配额 | ☐ | CPU、内存、存储配额已设置 |
| 监控配置 | ☐ | 指标和告警已配置 |
| 日志配置 | ☐ | 日志收集和存储已设置 |
| 备份策略 | ☐ | 自动化备份已配置并测试 |
| 恢复测试 | ☐ | 恢复流程已测试验证 |

### 部署后验证

```bash
# 1. 检查服务状态
docker-compose ps
kubectl get pods

# 2. 检查健康端点
curl http://localhost:8000/health
curl http://localhost:8000/ready

# 3. 检查日志
docker-compose logs -f backend

# 4. 运行冒烟测试
poetry run pytest tests/smoke/ -v

# 5. 检查资源使用
docker stats
kubectl top pods
```

## 7.9 练习题

### 练习 7.1：Docker 部署

**任务**：使用 Docker Compose 部署系统到生产环境。

**步骤**：首先配置生产环境变量，然后自定义 docker-compose.yml，最后启动并验证服务。

**要求**：服务能够在后台稳定运行，健康检查通过。

### 练习 7.2：监控配置

**任务**：配置 Prometheus 指标和 Grafana 仪表板。

**步骤**：首先添加指标收集代码，然后配置 Prometheus 抓取规则，接着创建 Grafana 仪表板，最后设置告警规则。

**要求**：能够实时监控系统指标，收到异常告警。

### 练习 7.3：高可用部署

**任务**：配置多副本高可用部署。

**步骤**：首先配置 Kubernetes 部署，然后设置负载均衡和故障转移，接着测试副本故障恢复，最后验证高可用性。

**要求**：单个节点故障不影响服务可用性。

---

## 进阶思考

思考以下问题。如何设计零停机的部署和更新策略？如何在保证安全性的同时实现高效的密钥轮换？多区域部署如何保证数据一致性和服务可用性？

## 版本信息

| 项目 | 信息 |
|------|------|
| 文档版本 | 1.0.0 |
| 最后更新 | 2026年2月 |
| 适用版本 | 1.0.0+ |

## 反馈与贡献

如果您在部署过程中遇到问题或有改进建议，欢迎通过 GitHub Issues 提交反馈。
