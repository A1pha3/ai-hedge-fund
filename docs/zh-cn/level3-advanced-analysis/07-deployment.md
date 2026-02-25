# 第七章：生产环境部署指南

**难度级别**：⭐⭐⭐（进阶）

**预计学习时间**：3-4 小时

---

## 学习目标

完成本章节学习后，你将能够：

### 基础目标（必掌握）

- [ ] 理解 **生产环境（Production Environment）** 与开发环境的核心差异
- [ ] 掌握 **Docker Compose** 的基本部署流程和配置方法
- [ ] 能够配置生产环境必需的环境变量和安全参数
- [ ] 实现基本的健康检查和日志系统

### 进阶目标（建议掌握）

- [ ] 设计高可用的多服务架构部署方案
- [ ] 配置 **Prometheus** 指标收集和告警规则
- [ ] 实现速率限制、输入验证等安全加固措施
- [ ] 使用 Kubernetes 进行多副本部署和自动扩缩容

### 专家目标（挑战）

- [ ] 设计零停机的蓝绿部署或金丝雀发布策略
- [ ] 实现自动化灾难恢复和故障转移机制
- [ ] 优化生产环境性能，达到 SLA 要求
- [ ] 制定团队的生产环境部署最佳实践文档

---

## 7.1 生产环境概述

### 7.1.1 生产环境与开发环境的区别

> 💡 **核心设计思想**
> 生产环境部署的核心目标是**保障系统的可靠性、安全性和性能**。理解这一点，有助于你在做每个配置决策时都能权衡利弊，做出正确的选择。

开发环境用于日常开发和测试，而生产环境需要满足高可用性、安全性和性能要求。以下是关键的差异分析：

#### 为什么这些差异很重要？

**场景 1：服务中断的影响**

| 环境 | 服务中断的影响 | 可接受度 |
|------|--------------|---------|
| 开发环境 | 影响个人的开发进度 | ✅ 可接受 |
| 生产环境 | 影响所有用户，可能造成经济损失 | ❌ 不可接受 |

**决策**：生产环境必须实现健康检查、自动重启和故障转移机制。

---

#### 四个维度的核心差异

| 维度 | 开发环境 | 生产环境 | 生产环境要求 |
|------|---------|---------|-------------|
| **可靠性** | 可以容忍服务中断和错误 | 需要 99.9% 以上的可用性 | 健康检查、自动重启、故障转移 |
| **安全性** | 使用测试 API 密钥和简化配置 | 严格的安全策略 | API 密钥管理、网络隔离、访问控制、审计日志 |
| **性能** | 关注功能正确性 | 优化响应延迟、吞吐量和资源利用率 | 性能监控、自动扩缩容 |
| **可观测性** | 依赖本地调试 | 完整的日志、指标和追踪系统 | 分布式追踪、集中化日志、实时监控 |

#### 可靠性详解：99.9% 的可用性意味着什么？

> 📚 **知识延伸**：可用性通常用"几个九"来表示
> - 99% 可用性 = 每年停机 3.65 天
> - 99.9% 可用性 = 每年停机 8.77 小时
> - 99.99% 可用性 = 每年停机 52.6 分钟
> - 99.999% 可用性 = 每年停机 5.26 分钟

**为什么 99.9% 的可用性是一个常见的目标？**
- 平衡了技术实现难度和业务需求
- 对于大多数应用，8 小时的年停机时间是可以接受的
- 实现更高可用性（如 99.99%）需要显著增加成本（多区域部署、更复杂的故障转移机制）

---

### 7.1.2 部署架构选择

> 🤔 **设计决策**：选择部署架构时需要考虑哪些因素？

AI Hedge Fund 支持多种部署架构。正确的架构选择取决于使用场景和资源限制。以下是决策框架：

#### 部署架构决策树

```
Q: 你的用户规模有多大？
├── 个人使用或小团队（<10 用户）
│   └── → 单机部署
│
├── 中等规模团队（10-100 用户）
│   Q: 你是否有运维团队？
│   ├── 有运维团队 → 分布式部署
│   └── 无运维团队 → 单机部署 + 托管数据库
│
└── 大规模或生产环境（100+ 用户）
    Q: 你的预算和技术能力如何？
    ├── 高预算 + 强技术团队 → 云原生部署（Kubernetes）
    └── 中低预算 + 有限技术团队 → 分布式部署（Docker Swarm）
```

---

#### 架构一：单机部署 ⭐

**适用场景**：个人用户和小规模使用

**架构图**：
```
┌─────────────────────────────┐
│         单个服务器           │
│                             │
│  ┌───────────────────────┐  │
│  │   Docker 容器         │  │
│  │  ┌─────────────────┐  │  │
│  │  │  前端 (Frontend) │  │  │
│  │  └─────────────────┘  │  │
│  │  ┌─────────────────┐  │  │
│  │  │  后端 (Backend)  │  │  │
│  │  └─────────────────┘  │  │
│  │  ┌─────────────────┐  │  │
│  │  │  Ollama (可选)   │  │  │
│  │  └─────────────────┘  │  │
│  └───────────────────────┘  │
└─────────────────────────────┘
```

**优点**：
- ✅ 资源消耗较低
- ✅ 配置简单
- ✅ 快速部署

**缺点**：
- ❌ 可用性有限（单点故障）
- ❌ 无法水平扩展
- ❌ 资源竞争（所有服务共享一台机器）

**实现方式**：Docker Compose 单个服务定义

---

#### 架构二：分布式部署 ⭐⭐

**适用场景**：团队协作和高可用需求

**架构图**：
```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  前端容器      │  │  后端容器      │  │  Ollama 容器   │
│  (Frontend)   │  │  (Backend)    │  │  (可选)       │
│              │  │              │  │              │
│  HTTP/HTTPS  │  │  API 服务     │  │  LLM 服务     │
└──────────────┘  └──────────────┘  └──────────────┘
       │                 │                 │
       └─────────────────┴─────────────────┘
                       │
              ┌────────┴────────┐
              │   负载均衡器    │
              │ (Nginx/HAProxy)│
              └─────────────────┘
                       │
              ┌────────┴────────┐
              │   外部流量      │
              └─────────────────┘
```

**优点**：
- ✅ 支持水平扩展
- ✅ 单点故障隔离
- ✅ 资源独立分配

**缺点**：
- ❌ 配置复杂度增加
- ❌ 需要编排工具（Kubernetes 或 Docker Swarm）
- ❌ 运维成本增加

**实现方式**：Kubernetes Deployment + Service，或 Docker Swarm

---

#### 架构三：云原生部署 ⭐⭐⭐

**适用场景**：生产环境使用

**架构图**：
```
                 ┌─────────────────┐
                 │   CDN (全球加速)  │
                 └────────┬────────┘
                          │
                 ┌────────┴────────┐
                 │   负载均衡器     │
                 │  (AWS ELB/GCP LB)│
                 └────────┬────────┘
                          │
    ┌─────────────────────┼─────────────────────┐
    │                     │                     │
┌───┴───┐           ┌────┴────┐          ┌────┴────┐
│区域 A │           │区域 B  │          │区域 C   │
│       │           │        │          │        │
│ 容器组 │           │ 容器组   │          │ 容器组   │
│       │           │        │          │        │
└───┬───┘           └────┬────┘          └────┬────┘
    │                     │                     │
    └─────────────────────┼─────────────────────┘
                          │
              ┌───────────┴───────────┐
              │   托管数据库/缓存       │
              │ (AWS RDS/ElastiCache)  │
              └────────────────────────┘
```

**优点**：
- ✅ 自动扩缩容
- ✅ 内置高可用（多区域）
- ✅ 托管服务（减少运维负担）
- ✅ 按需付费（成本优化）

**缺点**：
- ❌ 成本较高
- ❌ 供应商锁定（Vendor Lock-in）
- ❌ 学习曲线陡峭

**实现方式**：AWS ECS、Google Cloud Run、Azure Container Instances

---

### 练习 7.1：部署架构选择 ⭐

**任务**：根据以下场景，选择最合适的部署架构，并说明理由。

**场景 1**：你是一家初创公司的技术负责人，团队有 5 人，预算有限，预计用户规模在 50 人以内。

**场景 2**：你是一家金融科技公司的工程师，公司有完善的运维团队，用户规模约 500 人，需要 99.9% 的可用性。

**场景 3**：你是一家跨国公司的架构师，用户分布在全球，需要 99.99% 的可用性，预算充足。

**参考答案**：

| 场景 | 推荐架构 | 理由 |
|-----|---------|------|
| 场景 1 | 单机部署 | 用户规模小、预算有限、快速上线是首要目标 |
| 场景 2 | 分布式部署 | 有运维团队、需要高可用、预算可接受 |
| 场景 3 | 云原生部署 | 全球用户、极高可用性要求、预算充足 |

---

## 7.2 Docker 容器化部署

### 7.2.1 为什么使用容器化？

> 🤔 **为什么选择 Docker 而不是虚拟机？**

| 特性 | 虚拟机（VM） | 容器（Docker） |
|------|------------|----------------|
| **启动时间** | 分钟级 | 秒级 |
| **资源消耗** | 需要完整的操作系统 | 共享主机内核 |
| **大小** | GB 级别 | MB 级别 |
| **隔离性** | 强（硬件级隔离） | 中（进程级隔离） |
| **适用场景** | 需要完全隔离、运行不同操作系统 | 应用打包、微服务部署 |

**结论**：对于 AI Hedge Fund 这样的应用，容器化是更好的选择，因为：
1. 启动快，适合快速部署和扩缩容
2. 资源占用少，可以运行更多服务
3. 便携性好，确保开发、测试、生产环境一致

---

### 7.2.2 使用 Docker Compose 部署

> 📚 **前置知识**：Docker Compose 是什么？
>
> **Docker Compose** 是一个用于定义和运行多容器 Docker 应用程序的工具。通过一个 YAML 文件（docker-compose.yml），你可以配置应用程序需要的所有服务，然后使用一个命令启动所有服务。
>
> **为什么需要 Docker Compose？**
> - AI Hedge Fund 需要多个服务协同工作（前端、后端、Ollama）
> - 手动管理多个容器非常繁琐
> - Docker Compose 让多容器管理变得简单

#### 前置条件

- 安装 **Docker Engine** 20.10+
- 安装 **Docker Compose V2**

```bash
# 检查 Docker 版本
docker --version

# 检查 Docker Compose 版本
docker compose version
```

#### 部署步骤详解

**第一步：克隆项目并进入 docker 目录**

```bash
git clone https://github.com/virattt/ai-hedge-fund.git
cd ai-hedge-fund/docker
```

> 💡 **提示**：如果你已经在项目中，可以直接进入 docker 目录

---

**第二步：复制环境变量模板**

```bash
cp .env.example .env
nano .env
```

> ⚠️ **安全提示**：`.env` 文件包含敏感信息，务必不要提交到版本控制系统（已在 .gitignore 中）

---

**第三步：配置生产环境变量**

```bash
# ============================================
# 生产环境配置示例
# ============================================

# --- LLM API 密钥（生产环境必须设置） ---
# 选择 LLM 提供商（生产环境建议使用云端 API）
OPENAI_API_KEY=sk-prod-key-xxxxx
ANTHROPIC_API_KEY=prod-key-xxxxx

# --- Financial Datasets API ---
FINANCIAL_DATASETS_API_KEY=prod-fd-key-xxxxx

# --- Ollama 配置（可选，本地部署）---
OLLAMA_HOST=ollama
OLLAMA_BASE_URL=http://ollama:11434

# --- 日志配置（生产环境使用 WARNING 或 ERROR）---
LOG_LEVEL=WARNING
LOG_FORMAT=json

# --- 性能配置 ---
MAX_WORKERS=4
MAX_CONCURRENT_REQUESTS=100
REQUEST_TIMEOUT=60

# --- 安全配置 ---
JWT_SECRET=your-super-secret-jwt-key-change-in-production
ENCRYPTION_KEY=your-encryption-key-32-chars
```

> 🔐 **安全最佳实践**
>
> 1. **密钥长度**：JWT Secret 至少 32 个字符
> 2. **密钥生成**：使用随机字符串生成器，不要使用简单密码
> 3. **密钥轮换**：定期更换密钥（建议每 3-6 个月）
> 4. **密钥存储**：生产环境考虑使用密钥管理服务（如 AWS Secrets Manager）

---

**第四步：启动服务**

```bash
# 启动所有服务（后台运行）
docker compose up -d

# 查看启动日志
docker compose logs -f
```

> 📝 **命令说明**
>
> - `up`：启动服务
> - `-d`：后台运行（detached mode）
> - `logs -f`：实时查看日志（follow mode）

---

**第五步：验证服务状态**

```bash
# 查看所有容器状态
docker compose ps

# 预期输出：
# NAME                   STATUS    PORTS
# hedge-fund-backend     Up        0.0.0.0:8000->8000/tcp
# hedge-fund-frontend    Up        0.0.0.0:5173->5173/tcp
# ollama                 Up        0.0.0.0:11434->11434/tcp

# 测试健康检查端点
curl http://localhost:8000/health
```

> ✅ **验证清单**
> - 所有容器状态为 `Up`
> - 端口映射正确
> - 健康检查端点返回正常
> - 没有错误日志

---

### 7.2.3 Docker Compose 配置详解

> 🤔 **为什么需要理解配置文件？**
>
> 配置文件是部署的"蓝图"，理解它可以帮助你：
> 1. 自定义部署（修改端口、添加环境变量等）
> 2. 排查部署问题（配置错误是常见原因）
> 3. 优化资源使用（调整限制、卷挂载等）

#### docker-compose.yml 文件结构

```yaml
version: '3.8'  # Compose 文件格式版本

services:
  # ========== 后端服务 ==========
  backend:
    build:
      context: ../.                     # 构建上下文（相对于此文件的路径）
      dockerfile: docker/Dockerfile.backend
    container_name: hedge-fund-backend  # 容器名称
    restart: unless-stopped             # 重启策略（除非手动停止）
    ports:
      - "8000:8000"                     # 端口映射（主机:容器）
    environment:
      - PYTHONUNBUFFERED=1              # Python 输出不缓冲
      - OLLAMA_BASE_URL=http://ollama:11434  # Ollama 服务地址
      - PYTHONPATH=/app
    env_file:
      - ../.env                         # 从文件加载环境变量
    volumes:
      - ../.env:/app/.env:ro            # 挂载 .env 文件（只读）
    depends_on:
      - ollama                          # 依赖关系（后端依赖 Ollama）
    healthcheck:                        # 健康检查配置
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s                     # 检查间隔
      timeout: 10s                      # 超时时间
      retries: 3                        # 重试次数
      start_period: 60s                 # 容器启动后首次检查的等待时间

  # ========== 前端服务 ==========
  frontend:
    build:
      context: ../app/frontend
      dockerfile: Dockerfile
    container_name: hedge-fund-frontend
    restart: unless-stopped
    ports:
      - "5173:5173"                     # 开发服务器端口
    depends_on:
      - backend                         # 前端依赖后端

  # ========== Ollama 服务（可选）==========
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama       # 持久化 Ollama 数据
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia            # NVIDIA GPU 支持（需要 nvidia-docker）
              count: 1
              capabilities: [gpu]

volumes:
  ollama_data:                          # 命名卷（持久化数据）
```

#### 配置项详解

| 配置项 | 说明 | 为什么重要 |
|--------|------|-----------|
| `restart: unless-stopped` | 重启策略 | 确保服务崩溃后自动恢复 |
| `healthcheck` | 健康检查 | 自动检测服务健康状态，不健康时重启 |
| `depends_on` | 依赖关系 | 确保服务按正确顺序启动 |
| `volumes` | 卷挂载 | 持久化数据，避免容器重启后数据丢失 |
| `resources` | 资源限制 | 防止单个服务占用过多资源影响其他服务 |

---

### 7.2.4 多服务架构部署 ⭐⭐

> 🎯 **学习目标**：掌握多服务架构的配置，实现服务分离和独立扩展

对于需要高可用和水平扩展的生产环境，使用多服务架构。

#### 为什么需要多服务架构？

**场景对比**：

| 架构 | 单容器 | 多容器 |
|------|--------|--------|
| **故障影响** | 后端故障 → 所有服务不可用 | 后端故障 → 只影响 API 服务 |
| **扩展方式** | 必须整体扩展 | 可以独立扩展后端 |
| **资源利用** | 前端和后端共享资源 | 前端和后端独立分配资源 |
| **部署频率** | 任何更新都需要重启整个容器 | 独立更新每个服务 |

---

#### 服务分离部署配置

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  # ========== API 网关 ==========
  api-gateway:
    image: nginx:alpine                # 轻量级 Nginx 镜像
    container_name: hedge-fund-gateway
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro  # 挂载 Nginx 配置
    ports:
      - "80:80"                        # HTTP
      - "443:443"                      # HTTPS
    depends_on:
      - backend                        # 网关依赖后端
    restart: unless-stopped

  # ========== 后端服务（多副本）==========
  backend:
    build:
      context: ../.
      dockerfile: docker/Dockerfile.backend
    deploy:
      replicas: 3                      # 运行 3 个副本
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    environment:
      - PYTHONUNBUFFERED=1
      - LOG_LEVEL=WARNING
    env_file:
      - ../.env
    restart: unless-stopped

  # ========== Ollama（本地 LLM，可选）==========
  ollama:
    image: ollama/ollama:latest
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped

  # ========== Redis（会话存储和缓存）==========
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}  # 密码保护
    volumes:
      - redis_data:/data               # 持久化 Redis 数据
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
    restart: unless-stopped

volumes:
  ollama_data:
  redis_data:
```

> 💡 **关键改进点**
>
> 1. **API 网关**：统一入口，处理负载均衡和路由
> 2. **多副本**：3 个后端副本，提高可用性和并发处理能力
> 3. **Redis**：独立的缓存服务，提高性能
> 4. **资源限制**：防止资源竞争

---

#### Nginx 负载均衡配置

```nginx
# nginx.conf
events {
    worker_connections 1024;
}

http {
    upstream backend {
        # 负载均衡策略：轮询（round-robin）
        server backend:8000;
        server backend:8000;
        server backend:8000;
    }

    server {
        listen 80;
        server_name localhost;

        location / {
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # 健康检查端点
        location /health {
            proxy_pass http://backend/health;
            access_log off;
        }
    }
}
```

> 📚 **负载均衡策略对比**
>
> | 策略 | 说明 | 适用场景 |
> |------|------|----------|
> | 轮询（round-robin） | 依次分配请求 | 请求相似，服务能力相同 |
> | 最少连接（least_conn） | 分配给连接数最少的服务器 | 请求处理时间差异大 |
> | IP 哈希（ip_hash） | 同一 IP 分配到同一服务器 | 需要保持会话状态 |
> | 加权轮询（weight） | 根据权重分配 | 服务器能力不同 |

---

### 练习 7.2：Docker Compose 部署 ⭐

**任务**：使用 Docker Compose 部署 AI Hedge Fund 到生产环境。

**步骤**：
1. 克隆项目并进入 docker 目录
2. 配置生产环境变量（API 密钥、日志级别等）
3. 修改 docker-compose.yml，添加健康检查和资源限制
4. 启动服务并验证

**要求**：
- [ ] 所有容器成功启动
- [ ] 健康检查端点返回正常
- [ ] 日志级别设置为 WARNING
- [ ] 配置了至少 1 个资源限制（CPU 或内存）

**验证方法**：
```bash
# 检查容器状态
docker compose ps

# 测试健康检查
curl http://localhost:8000/health

# 查看日志（应该没有错误）
docker compose logs backend | grep -i error
```

**常见错误**：
| 错误 | 原因 | 解决方法 |
|------|------|---------|
| `Connection refused` | 服务未启动 | 检查容器状态，查看日志 |
| `API key not found` | 环境变量未配置 | 检查 .env 文件是否正确配置 |
| `Permission denied` | 端口已被占用 | 修改 docker-compose.yml 中的端口映射 |

**扩展挑战** ⭐⭐：
- 配置 Nginx 作为 API 网关
- 实现 3 个后端副本的负载均衡
- 添加 Redis 缓存服务

---

## 7.3 生产环境配置

### 7.3.1 环境变量配置

> 🔐 **核心原则**：生产环境的配置必须与开发环境严格分离

生产环境需要严格配置的环境变量。错误的配置可能导致安全漏洞或性能问题。

#### 必需配置（安全相关）

```bash
# ============================================
# LLM API 密钥（生产环境必须设置）
# ============================================
OPENAI_API_KEY=sk-prod-key-xxxxx
ANTHROPIC_API_KEY=prod-key-xxxxx

# ============================================
# Financial Datasets API
# ============================================
FINANCIAL_DATASETS_API_KEY=prod-fd-key-xxxxx

# ============================================
# 安全配置
# ============================================
# JWT 密钥（用于身份验证）
JWT_SECRET=your-super-secret-jwt-key-change-in-production

# 加密密钥（用于敏感数据加密，至少 32 字符）
ENCRYPTION_KEY=your-encryption-key-32-chars-or-more
```

> ⚠️ **安全警告**
>
> 1. **密钥强度**：使用强随机字符串，至少 32 字符
> 2. **密钥存储**：不要将密钥提交到版本控制系统
> 3. **密钥轮换**：定期更换密钥（建议每 3-6 个月）
> 4. **密钥分离**：开发和生产环境使用不同的密钥

---

#### 必需配置（性能和日志）

```bash
# ============================================
# 日志配置（生产环境）
# ============================================
# 日志级别：DEBUG < INFO < WARNING < ERROR < CRITICAL
# 生产环境使用 WARNING 或 ERROR，减少日志量
LOG_LEVEL=WARNING

# 日志格式：json（便于日志收集和分析）
LOG_FORMAT=json
```

> 💡 **为什么生产环境使用 WARNING 而不是 INFO？**
>
> - 减少日志量，降低存储成本
> - 减少日志系统负载
> - 只记录需要关注的问题

```bash
# ============================================
# 性能配置
# ============================================
# Uvicorn 工作进程数（通常设置为 CPU 核心数 * 2 + 1）
MAX_WORKERS=4

# 最大并发请求数（防止资源耗尽）
MAX_CONCURRENT_REQUESTS=100

# 请求超时时间（秒）
REQUEST_TIMEOUT=60
```

> 🤔 **如何确定 MAX_WORKERS 的值？**
>
> 经验公式：`MAX_WORKERS = CPU 核心数 * 2 + 1`
>
> 例如：
> - 2 核 CPU → 5 个 workers
> - 4 核 CPU → 9 个 workers
> - 8 核 CPU → 17 个 workers
>
> **为什么是这个公式？**
> - Uvicorn worker 是异步的，可以处理大量并发连接
> - 过多的 workers 会导致上下文切换开销
> - 过少的 workers 无法充分利用 CPU

---

#### 可选配置（监控和资源）

```bash
# ============================================
# 监控配置
# ============================================
# 启用 Prometheus 指标
METRICS_ENABLED=true

# 指标暴露端口
METRICS_PORT=9090

# ============================================
# 告警配置
# ============================================
# 告警 Webhook（如 Slack）
ALERT_WEBHOOK_URL=https://hooks.slack.com/services/xxx/xxx/xxx

# 告警邮箱
ALERT_EMAIL=admin@example.com

# ============================================
# 资源限制
# ============================================
# 内存限制（例如：4G）
MEMORY_LIMIT=4G

# CPU 限制（例如：2.0 表示 2 个 CPU 核心）
CPU_LIMIT=2.0
```

---

### 7.3.2 配置文件最佳实践

> 📚 **知识延伸**：为什么需要分层配置文件？
>
> 分层配置文件可以实现：
> 1. **环境隔离**：不同环境使用不同配置
> 2. **配置继承**：通用配置在 defaults.yaml，特定配置在各环境文件中覆盖
> 3. **配置审计**：可以追踪配置变更历史

#### 分层配置文件结构

```
config/
├── defaults.yaml        # 默认配置（所有环境共享）
├── development.yaml     # 开发环境配置
├── staging.yaml        # 预发布环境配置（测试）
└── production.yaml      # 生产环境配置
```

#### 配置加载逻辑

```python
# src/config/loader.py
"""
配置加载器

设计思路：
1. 先加载默认配置
2. 再加载环境特定配置（覆盖默认配置）
3. 最后从环境变量读取敏感信息（如 API 密钥）
"""

from pathlib import Path
from functools import lru_cache
import yaml
import os

@lru_cache()
def load_config(env: str = "production") -> dict:
    """
    加载配置

    Args:
        env: 环境名称（development, staging, production）

    Returns:
        合并后的配置字典

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 环境变量未设置
    """
    config_dir = Path(__file__).parent

    # 步骤 1：加载默认配置
    defaults_file = config_dir / "defaults.yaml"
    if not defaults_file.exists():
        raise FileNotFoundError(f"默认配置文件不存在: {defaults_file}")

    with open(defaults_file) as f:
        config = yaml.safe_load(f)

    # 步骤 2：加载环境配置（覆盖默认配置）
    env_file = config_dir / f"{env}.yaml"
    if env_file.exists():
        with open(env_file) as f:
            env_config = yaml.safe_load(f)
            if env_config:
                config.update(env_config)

    # 步骤 3：从环境变量读取敏感信息
    config["api_keys"] = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
        "FINANCIAL_DATASETS_API_KEY": os.getenv("FINANCIAL_DATASETS_API_KEY"),
    }

    # 验证必需的密钥是否存在
    missing_keys = [
        key for key, value in config["api_keys"].items()
        if not value
    ]
    if missing_keys:
        raise ValueError(
            f"以下环境变量未设置: {', '.join(missing_keys)}"
        )

    return config
```

> 💡 **为什么使用 lru_cache？**
>
> `@lru_cache()` 会缓存配置加载结果，避免每次调用都重新读取文件和解析 YAML。这对于高频调用（如每个请求都检查配置）的场景尤为重要。

---

#### 配置文件示例

**defaults.yaml**：
```yaml
# 默认配置（所有环境共享）
app:
  name: AI Hedge Fund
  version: 1.0.0

logging:
  format: json
  handlers:
    - console
    - file

performance:
  max_workers: 4
  max_concurrent_requests: 100
  request_timeout: 60

monitoring:
  metrics_enabled: false
```

**production.yaml**：
```yaml
# 生产环境配置（覆盖 defaults.yaml）
logging:
  level: WARNING  # 覆盖默认的 INFO

monitoring:
  metrics_enabled: true  # 启用指标收集
  metrics_port: 9090

# 安全配置（生产环境特有）
security:
  jwt_secret_key: ${JWT_SECRET}  # 从环境变量读取
  encryption_key: ${ENCRYPTION_KEY}
```

---

### 7.3.3 性能调优配置

> 🎯 **学习目标**：了解如何通过配置优化系统性能

#### Uvicorn 工作进程配置

```bash
# 使用多个 worker 处理并发请求
poetry run uvicorn app.backend.main:app \
    --workers 4 \                                      # 工作进程数
    --worker-class uvicorn.workers.UvicornWorker \     # Worker 类
    --bind 0.0.0.0:8000 \                             # 绑定地址
    --timeout-keep-alive 30 \                         # Keep-alive 超时
    --max-requests 1000 \                             # 每个 worker 处理的最大请求数后重启
    --max-requests-jitter 50                           # 最大请求数的随机抖动（避免所有 worker 同时重启）
```

> 🤔 **为什么需要 max-requests 和 max-requests-jitter？**
>
> **问题**：长时间运行的进程可能会出现内存泄漏
> **解决**：设置 `max-requests`，让 worker 处理一定数量请求后自动重启，释放内存
> **优化**：使用 `max-requests-jitter`，让不同 worker 在不同时间重启，避免同时重启导致服务短暂不可用

---

#### 数据库连接池配置

```python
# src/db/pool.py
"""
数据库连接池配置

为什么需要连接池？
1. 建立数据库连接是昂贵的操作（TCP 握手、身份验证等）
2. 连接池复用已建立的连接，提高性能
3. 避免过多的连接导致数据库资源耗尽
"""

from sqlalchemy.pool import QueuePool
from sqlalchemy import create_engine

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,                # 最小连接数（常驻连接）
    max_overflow=20,             # 最大额外连接数（临时连接）
    pool_recycle=3600,           # 连接回收时间（秒，避免长时间连接失效）
    pool_pre_ping=True,          # 使用连接前检查连接是否有效
    pool_timeout=30,             # 获取连接的超时时间（秒）
)
```

> 💡 **参数选择建议**
>
> | 参数 | 说明 | 建议值 |
> |------|------|--------|
> | `pool_size` | 常驻连接数 | CPU 核心数 * 2 |
> | `max_overflow` | 最大临时连接数 | pool_size 的 2-3 倍 |
> | `pool_recycle` | 连接回收时间 | 3600 秒（1 小时） |
> | `pool_pre_ping` | 连接前检查 | True（避免连接失效错误） |

---

### 练习 7.3：环境配置 ⭐

**任务**：配置生产环境变量和分层配置文件。

**步骤**：
1. 创建配置文件目录和文件（defaults.yaml、production.yaml）
2. 在 production.yaml 中配置生产环境特定的设置
3. 编写配置加载器（参考上面的示例代码）
4. 测试配置加载是否正确

**要求**：
- [ ] 配置文件结构正确
- [ ] 生产环境配置覆盖默认配置
- [ ] 敏感信息从环境变量读取
- [ ] 缺少环境变量时抛出错误

**验证方法**：
```python
# 测试配置加载
from src.config.loader import load_config

# 加载生产环境配置
config = load_config(env="production")

# 验证配置
assert config["logging"]["level"] == "WARNING"
assert config["monitoring"]["metrics_enabled"] == True
```

**扩展挑战** ⭐⭐：
- 实现配置热重载（检测配置文件变更后自动重新加载）
- 添加配置验证（检查必需字段、格式正确性等）

---

## 7.4 监控与告警

### 7.4.1 为什么需要监控？

> 💡 **核心思想**：没有监控的系统就像盲人开车

| 监控价值 | 说明 |
|---------|------|
| **问题发现**：在用户发现问题前发现异常 | 主动监控 → 快速响应 |
| **性能优化**：识别性能瓶颈，优化系统 | 数据驱动决策 |
| **容量规划**：预测资源需求，提前扩容 | 避免资源不足 |
| **故障排查**：提供问题诊断依据 | 快速定位根因 |

> 🤔 **可观测性的三个支柱**
>
> 1. **Logs（日志）**：发生了什么？（离散事件）
> 2. **Metrics（指标）**：表现如何？（数值、趋势）
> 3. **Traces（追踪）**：为什么慢？（请求链路）
>
> 本节重点讲解 Metrics，Logs 也在前面提到，Traces 将在后续章节介绍。

---

### 7.4.2 健康检查端点

> 📚 **前置知识**：健康检查 vs 就绪检查
>
> | 类型 | 检查内容 | 失败处理 |
> |------|---------|---------|
> | **健康检查（Liveness）** | 服务是否存活（进程是否崩溃） | 重启容器 |
> | **就绪检查（Readiness）** | 服务是否准备好处理请求（依赖服务是否可用） | 从负载均衡器移除 |

生产环境必须实现健康检查接口。

#### 健康检查实现

```python
# app/backend/health.py
"""
健康检查端点

为什么需要健康检查？
- Kubernetes/Docker 根据健康检查结果决定是否重启容器
- 负载均衡器根据就绪检查结果决定是否转发流量
- 监控系统根据健康检查状态设置告警
"""

from fastapi import APIRouter
from pydantic import BaseModel
import psutil
import time
from typing import Dict, Any

router = APIRouter()

class HealthStatus(BaseModel):
    """健康检查响应模型"""
    status: str                     # healthy / unhealthy
    uptime_seconds: float           # 运行时间（秒）
    memory_usage_mb: float          # 内存使用量（MB）
    cpu_percent: float             # CPU 使用率（%）
    active_requests: int            # 当前活跃请求数
    version: str                    # 应用版本

start_time = time.time()

@router.get("/health")
async def health_check() -> HealthStatus:
    """
    健康检查端点

    返回：
        服务的基本健康状态

    用途：
        - Kubernetes/Docker 健康检查
        - 负载均衡器路由判断
        - 监控系统状态查询
    """
    process = psutil.Process()

    return HealthStatus(
        status="healthy",
        uptime_seconds=time.time() - start_time,
        memory_usage_mb=process.memory_info().rss / 1024 / 1024,
        cpu_percent=process.cpu_percent(),
        active_requests=0,  # TODO: 从请求追踪中获取
        version="1.0.0"
    )


class ReadinessStatus(BaseModel):
    """就绪检查响应模型"""
    ready: bool                     # 是否就绪
    checks: Dict[str, Any]          # 各项检查结果


async def check_database() -> Dict[str, Any]:
    """检查数据库连接"""
    try:
        # TODO: 实现数据库连接检查
        return {"healthy": True, "message": "Database is healthy"}
    except Exception as e:
        return {"healthy": False, "message": str(e)}


async def check_llm_provider() -> Dict[str, Any]:
    """检查 LLM 提供商"""
    try:
        # TODO: 实现LLM 提供商检查
        return {"healthy": True, "message": "LLM provider is healthy"}
    except Exception as e:
        return {"healthy": False, "message": str(e)}


async def check_cache() -> Dict[str, Any]:
    """检查缓存服务"""
    try:
        # TODO: 实现缓存检查
        return {"healthy": True, "message": "Cache is healthy"}
    except Exception as e:
        return {"healthy": False, "message": str(e)}


@router.get("/ready")
async def readiness_check() -> ReadinessStatus:
    """
    就绪检查端点

    检查所有依赖服务的健康状态。

    返回：
        就绪状态和各项检查结果

    用途：
        - Kubernetes/Docker 就绪检查
        - 负载均衡器判断是否可以接收流量
    """
    checks = {
        "database": await check_database(),
        "llm_provider": await check_llm_provider(),
        "cache": await check_cache(),
    }

    all_healthy = all(c["healthy"] for c in checks.values())

    return ReadinessStatus(
        ready=all_healthy,
        checks=checks
    )
```

> 💡 **最佳实践**
>
> 1. **轻量级**：健康检查应该快速返回（< 1 秒）
> 2. **幂等性**：多次调用结果一致
> 3. **详细但不冗长**：提供足够的信息，但不过于详细
> 4. **版本控制**：返回应用版本，便于排查问题

---

### 7.4.3 指标监控

> 📚 **前置知识**：什么是 Prometheus？
>
> **Prometheus** 是一个开源的监控和告警系统，用于收集和存储时序数据。它的核心特性包括：
>
> - **Pull 模式**：Prometheus 主动拉取指标（而非 Push）
> - **时序数据库**：专门存储时间序列数据
> - **PromQL 查询语言**：强大的查询和聚合功能
> - **告警规则**：基于指标的告警

#### 使用 Prometheus 指标

```python
# src/monitoring/metrics.py
"""
Prometheus 指标收集

为什么需要指标？
- 量化系统性能（请求延迟、错误率等）
- 设置告警规则（异常情况自动通知）
- 容量规划（基于历史数据预测资源需求）

Prometheus 指标类型：
- Counter：只能递增的计数器（如总请求数）
- Gauge：可增可减的数值（如当前内存使用量）
- Histogram：直方图（如请求延迟分布）
- Summary：摘要（如 P95、P99 延迟）
"""

from prometheus_client import Counter, Histogram, Gauge

# ========== Counter（计数器）==========
# 只能递增，用于计数事件

# HTTP 请求总数（按方法、端点、状态码分组）
REQUEST_COUNT = Counter(
    "hedge_fund_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

# LLM API 调用总数（按提供商、模型分组）
LLM_CALLS = Counter(
    "hedge_fund_llm_calls_total",
    "Total LLM API calls",
    ["provider", "model"]
)

# ========== Histogram（直方图）==========
# 用于记录分布数据（如延迟）

# HTTP 请求延迟（单位：秒）
REQUEST_LATENCY = Histogram(
    "hedge_fund_request_duration_seconds",
    "HTTP request latency",
    ["endpoint"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]  # 分桶边界
)

# LLM 响应延迟
LLM_LATENCY = Histogram(
    "hedge_fund_llm_response_duration_seconds",
    "LLM response latency",
    ["provider", "model"],
    buckets=[1.0, 2.0, 5.0, 10.0, 20.0, 30.0]
)

# ========== Gauge（仪表盘）==========
# 可增可减，用于记录当前状态

# 当前活跃的 Agent 数量
ACTIVE_AGENTS = Gauge(
    "hedge_fund_active_agents",
    "Number of currently running agents"
)

# 当前内存使用量（MB）
MEMORY_USAGE = Gauge(
    "hedge_fund_memory_usage_mb",
    "Current memory usage in MB"
)


# ========== 使用示例 ==========

# 记录请求
import time
from fastapi import Request

async def track_request(request: Request, call_next):
    """中间件：记录请求指标"""
    start_time = time.time()

    # 处理请求
    response = await call_next(request)

    # 计算延迟
    duration = time.time() - start_time

    # 记录指标
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()

    REQUEST_LATENCY.labels(endpoint=request.url.path).observe(duration)

    return response
```

> 💡 **指标命名规范**
>
> - 使用 `snake_case`（下划线命名）
> - 应用前缀：`hedge_fund_`
> - 单位后缀：`_seconds`、`_bytes`、`_total`
> - 标签：维度信息（如 provider、model）

---

### 7.4.4 日志配置

> 📚 **前置知识**：为什么需要结构化日志？
>
> **结构化日志**（如 JSON 格式）相比普通文本日志的优势：
>
> | 特性 | 普通日志 | 结构化日志 |
> |------|---------|-----------|
| **解析** | 需要正则表达式 | 直接解析 JSON |
> **查询** | 困难（grep 模糊匹配） | 精确查询（字段匹配） |
> **聚合** | 困难 | 容易（统计字段值） |
> **可视化** | 困难 | 容易（字段可直接用于图表） |

#### 结构化日志实现

```python
# src/logging/config.py
"""
日志配置

为什么需要结构化日志？
- 便于日志收集和分析（如 ELK、Splunk）
- 支持复杂查询（如按字段过滤）
- 易于可视化（如 Grafana）
"""

import logging
from pythonjsonlogger import jsonlogger
import sys

def setup_logging(level: str = "INFO"):
    """
    配置结构化日志

    Args:
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
    """
    logger = logging.getLogger("hedge_fund")
    logger.setLevel(getattr(logging, level))

    # 清除已有的 handlers
    logger.handlers.clear()

    # 控制台输出
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # 返回 logger
    return logger


# ========== 使用示例 ==========

logger = setup_logging(level="WARNING")

def process_trade(ticker: str, action: str, price: float):
    """处理交易"""
    logger.info(
        "Trade processed",
        extra={
            "ticker": ticker,
            "action": action,
            "price": price,
            "timestamp": "2024-01-15T10:30:00Z"
        }
    )
```

#### 日志输出示例

```json
{
  "asctime": "2024-01-15T10:30:00.000Z",
  "name": "hedge_fund.agents.portfolio",
  "levelname": "INFO",
  "message": "Portfolio decision generated",
  "ticker": "AAPL",
  "decision": "BUY",
  "confidence": 85,
  "latency_ms": 1500
}
```

> 💡 **日志级别选择**
>
> | 级别 | 说明 | 使用场景 |
> |------|------|----------|
> | DEBUG | 详细调试信息 | 开发环境 |
> | INFO | 一般信息 | 开发和测试环境 |
> | WARNING | 警告信息 | 生产环境（默认） |
> | ERROR | 错误信息 | 所有环境 |
> | CRITICAL | 严重错误 | 所有环境 |

---

### 7.4.5 告警规则

> 🤔 **为什么需要告警？**
>
> 监控系统发现异常后，需要通过告警及时通知运维人员。合理的告警可以：
> - 快速响应问题，减少影响范围
> - 避免人工频繁检查监控仪表板
> - 确保问题不被忽视

#### Prometheus 告警规则配置

```yaml
# prometheus/alerts.yml
"""
告警规则配置

设计原则：
1. 告警阈值基于 SLA 要求（如 99.9% 可用性 → 错误率 < 0.1%）
2. 告警持续时长（for）避免误报（瞬时抖动不触发）
3. 告警分级（critical/warning）优先处理重要问题
"""

groups:
  - name: hedge_fund_alerts
    rules:
      # ========== 关键告警 ==========

      - alert: HighErrorRate
        expr: rate(hedge_fund_requests_total{status=~"5.."}[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} in the last 5 minutes"

      - alert: ServiceDown
        expr: up{job="hedge-fund-backend"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Service is down"
          description: "Backend service has been down for 2 minutes"

      - alert: LLMProviderDown
        expr: hedge_fund_llm_provider_available == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "LLM provider is unavailable"
          description: "Cannot reach LLM provider for 2 minutes"

      # ========== 警告告警 ==========

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(hedge_fund_request_duration_seconds_bucket[5m])) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High latency detected"
          description: "P95 latency is {{ $value }} seconds"

      - alert: HighMemoryUsage
        expr: hedge_fund_memory_usage_mb > 4096
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage"
          description: "Memory usage is {{ $value }} MB for 10 minutes"

      - alert: HighCPUUsage
        expr: rate(hedge_fund_cpu_usage_seconds[5m]) > 0.8
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage"
          description: "CPU usage is {{ $value | humanizePercentage }} for 10 minutes"
```

> 💡 **告警最佳实践**
>
> 1. **告警疲劳**：避免过多的告警，只设置真正重要的告警
> 2. **告警分级**：critical（立即处理）、warning（关注）、info（记录）
> 3. **告警静默**：在维护期间可以静默告警
> 4. **告警确认**：收到告警后需要确认，避免重复通知

---

### 练习 7.4：监控配置 ⭐⭐

**任务**：配置 Prometheus 指标和告警规则。

**步骤**：
1. 添加 Prometheus 指标收集代码（参考上面的示例）
2. 配置 Prometheus 抓取规则
3. 设置告警规则（至少 3 个）
4. 测试指标是否正常收集

**要求**：
- [ ] 实现 HTTP 请求计数器
- [ ] 实现请求延迟直方图
- [ ] 配置至少 3 个告警规则
- [ ] 指标可以在 Prometheus UI 中查询到

**验证方法**：
```bash
# 发送一些请求
curl http://localhost:8000/api/analyze?ticker=AAPL

# 查询指标
curl http://localhost:9090/api/v1/query?query=hedge_fund_requests_total

# 查看告警
curl http://localhost:9090/api/v1/alerts
```

**扩展挑战** ⭐⭐⭐：
- 配置 Grafana 仪表板，可视化关键指标
- 实现基于日志的告警（如 ELK + Elasticsearch Watcher）
- 配置告警通知（Slack、Email、PagerDuty）

---

## 7.5 安全加固

> 🔐 **核心原则**：安全是持续的过程，不是一次性的配置

### 7.5.1 API 安全

#### 速率限制

> 🤔 **为什么需要速率限制？**
>
> **目的**：防止 API 被滥用，保护系统资源
>
> **场景**：
> - 恶意用户发送大量请求，导致服务崩溃（DoS 攻击）
> - 爬虫过度调用 API，消耗配额
> - 意外的循环请求，导致资源耗尽

```python
# src/security/rate_limit.py
"""
速率限制

为什么需要速率限制？
- 防止 API 被滥用（如爬虫、DDoS）
- 保护系统资源（避免服务崩溃）
- 公平使用（防止单个用户占用过多资源）
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/analyze")
@limiter.limit("10/minute")  # 每分钟最多 10 次
async def analyze(request: Request, ticker: str):
    """
    分析股票

    速率限制：每 IP 每分钟最多 10 次请求
    """
    # ... 业务逻辑
    pass
```

> 💡 **速率限制策略**
>
> | 策略 | 说明 | 适用场景 |
> |------|------|----------|
> | 固定窗口（Fixed Window） | 固定时间段内限制请求 | 简单场景 |
> | 滑动窗口（Sliding Window） | 滚动时间窗口，更精确 | 高精度场景 |
> | 令牌桶（Token Bucket） | 类似水桶，匀速生成令牌 | 突发流量 |
> | 漏桶（Leaky Bucket） | 以恒定速率处理请求 | 流量平滑 |

---

#### 输入验证

> ⚠️ **为什么输入验证至关重要？**
>
> **常见安全漏洞**：
> - **SQL 注入**：恶意 SQL 语句导致数据泄露
> - **XSS（跨站脚本攻击）**：恶意脚本在用户浏览器中执行
> - **命令注入**：恶意系统命令执行
> - **路径遍历**：访问未授权的文件

```python
# src/security/validation.py
"""
输入验证

为什么需要输入验证？
- 防止注入攻击（SQL、XSS、命令注入等）
- 确保数据格式正确，避免运行时错误
- 限制输入大小，防止资源耗尽
"""

from pydantic import BaseModel, validator
import re

class AnalysisRequest(BaseModel):
    """分析请求模型"""
    tickers: list[str]

    @validator("tickers")
    def validate_tickers(cls, v):
        """
        验证股票代码格式

        股票代码规则：
        - 1-5 个大写字母
        - 不包含数字和特殊字符
        """
        pattern = re.compile(r"^[A-Z]{1,5}$")
        for ticker in v:
            if not pattern.match(ticker):
                raise ValueError(f"Invalid ticker format: {ticker}")
        return v

    @validator("tickers")
    def max_tickers(cls, v):
        """
        限制最大数量

        为什么限制？
        - 防止资源耗尽（LLM 调用成本、处理时间）
        - 防止滥用（批量请求）
        """
        if len(v) > 20:
            raise ValueError("Maximum 20 tickers per request")
        return v

    @validator("tickers")
    def remove_duplicates(cls, v):
        """去重"""
        return list(set(v))
```

> 💡 **验证最佳实践**
>
> 1. **验证在数据模型层**：使用 Pydantic 进行声明式验证
> 2. **白名单而非黑名单**：只允许已知的格式，拒绝其他
> 3. **长度限制**：限制输入大小，防止资源耗尽
> 4. **类型检查**：确保数据类型正确（整数、字符串等）

---

### 7.5.2 网络安全

#### CORS 配置

> 📚 **前置知识**：什么是 CORS？
>
> **CORS（跨源资源共享）** 是一种安全机制，限制浏览器从不同源（域名、协议、端口）访问资源。
>
> **为什么需要 CORS？**
> - 同源策略（Same-Origin Policy）是浏览器的基本安全机制
> - CORS 允许跨域访问（如前端在 localhost:3000，后端在 api.example.com）
> - 错误配置会导致安全漏洞（如允许所有域名访问）

```python
# src/security/cors.py
"""
CORS 配置

为什么需要 CORS？
- 前端和后端可能部署在不同域名
- 浏览器的同源策略默认阻止跨域请求
- 正确配置 CORS 允许合法的跨域访问
"""

from fastapi.middleware.cors import CORSMiddleware

# 允许的源（生产环境必须限制）
origins = [
    "https://your-production-domain.com",
    "https://www.your-production-domain.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,           # ⚠️ 生产环境不要使用 ["*"]
    allow_credentials=True,          # 允许携带 Cookie
    allow_methods=["GET", "POST"],    # 允许的 HTTP 方法
    allow_headers=["Authorization", "Content-Type"],  # 允许的请求头
)
```

> ⚠️ **安全警告**
>
> **错误配置**：
> ```python
> allow_origins=["*"]  # ❌ 危险！允许所有域名访问
> ```
>
> **正确配置**：
> ```python
> allow_origins=["https://your-production-domain.com"]  # ✅ 安全
> ```

---

#### HTTPS 配置

> 📚 **前置知识**：为什么需要 HTTPS？
>
> **HTTP vs HTTPS**
>
> | 特性 | HTTP | HTTPS |
> |------|------|-------|
> | 加密 | ❌ 明文传输 | ✅ 加密传输 |
> | 身份验证 | ❌ 可能被中间人攻击 | ✅ SSL/TLS 证书验证 |
> | 数据完整性 | ❌ 可能被篡改 | ✅ 防篡改 |
> | SEO | ❌ 搜索引擎降权 | ✅ 搜索引擎优先 |
> | 浏览器 | ❌ 标记为"不安全" | ✅ 显示锁图标 |

```nginx
# nginx.conf
"""
HTTPS 配置

为什么需要 HTTPS？
- 加密数据传输，防止窃听
- 验证服务器身份，防止中间人攻击
- 现代浏览器将 HTTP 标记为不安全
"""

server {
    listen 443 ssl http2;                  # 启用 HTTP/2（性能更好）
    ssl_certificate /etc/nginx/ssl/cert.pem;      # SSL 证书
    ssl_certificate_key /etc/nginx/ssl/key.pem;    # SSL 私钥

    # SSL 协议（禁用过时的协议）
    ssl_protocols TLSv1.2 TLSv1.3;

    # 加密套件（优先选择强加密）
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;

    # ========== 安全头 ==========

    # 防止点击劫持（Clickjacking）
    add_header X-Frame-Options DENY;

    # 防止 MIME 类型嗅探
    add_header X-Content-Type-Options nosniff;

    # 启用 XSS 保护
    add_header X-XSS-Protection "1; mode=block";

    # 强制使用 HTTPS（1 年有效期）
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";

    # 站点地图
    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# HTTP 重定向到 HTTPS
server {
    listen 80;
    server_name your-production-domain.com;
    return 301 https://$host$request_uri;
}
```

> 💡 **SSL/TLS 证书获取**
>
> | 方法 | 说明 | 适用场景 |
> |------|------|----------|
> | Let's Encrypt | 免费证书，自动续期 | 大多数场景 |
> | Cloudflare | 免费 SSL，CDN 加速 | 公网访问 |
> | 商业证书 | 付费，高级功能 | 企业级需求 |

---

### 7.5.3 密钥管理

> 🔐 **核心原则**：不要在代码中硬编码密钥，不要将密钥提交到版本控制系统

#### 使用密钥管理服务

```python
# src/security/secrets.py
"""
密钥管理

为什么需要密钥管理服务？
- 避免密钥泄露（不在代码中硬编码）
- 方便密钥轮换（定期更换密钥）
- 审计追踪（记录密钥访问历史）
"""

import os
from functools import lru_cache

@lru_cache()
def get_api_key(provider: str) -> str:
    """
    从环境变量或密钥管理服务获取 API 密钥

    Args:
        provider: 提供商名称（如 "openai", "anthropic"）

    Returns:
        API 密钥

    Raises:
        ValueError: 密钥未找到
    """
    # 策略 1：从环境变量获取（开发环境）
    key = os.getenv(f"{provider.upper()}_API_KEY")
    if key:
        return key

    # 策略 2：从密钥管理服务获取（生产环境）
    try:
        from src.integrations.aws_secrets import get_secret
        return get_secret(f"ai-hedge-fund/{provider.lower()}-api-key")
    except ImportError:
        pass

    # 策略 3：从本地加密文件获取（中间方案）
    try:
        from src.integrations.local_vault import get_secret
        return get_secret(f"{provider.lower()}_api_key")
    except ImportError:
        pass

    # 所有策略都失败
    raise ValueError(
        f"API key not found for provider: {provider}. "
        f"Please set {provider.upper()}_API_KEY environment variable."
    )
```

> 📚 **密钥管理方案对比**
>
> | 方案 | 优点 | 缺点 | 适用场景 |
> |------|------|------|----------|
> | 环境变量 | 简单，无依赖 | 不安全，不便于轮换 | 开发环境 |
> | 本地加密文件 | 安全，可版本控制 | 需要手动管理 | 小团队 |
> | AWS Secrets Manager | 安全，自动轮换 | AWS 依赖，成本 | AWS 环境 |
> | HashiCorp Vault | 强大，企业级 | 复杂，学习成本高 | 大型企业 |

---

### 练习 7.5：安全加固 ⭐⭐

**任务**：实施安全加固措施。

**步骤**：
1. 实现速率限制（每 IP 每分钟最多 10 次请求）
2. 实现输入验证（股票代码格式、数量限制）
3. 配置 CORS（只允许特定域名）
4. 配置 HTTPS（使用 Let's Encrypt）

**要求**：
- [ ] 速率限制生效（超过限制返回 429）
- [ ] 输入验证生效（无效输入返回 400）
- [ ] CORS 配置正确（不允许通配符）
- [ ] HTTPS 正常工作（访问 http 重定向到 https）

**验证方法**：
```bash
# 测试速率限制
for i in {1..15}; do
  curl http://localhost:8000/api/analyze?ticker=AAPL
done
# 应该在第 11 次请求后返回 429

# 测试输入验证
curl http://localhost:8000/api/analyze?ticker=invalid-ticker-123
# 应该返回 400 和错误信息

# 测试 HTTPS
curl -k https://localhost
# 应该重定向到 HTTPS
```

**扩展挑战** ⭐⭐⭐：
- 集成 AWS Secrets Manager
- 实现 JWT 身份验证
- 配置 Web 应用防火墙（WAF）

---

## 7.6 高可用配置

### 7.6.1 为什么需要高可用？

> 🤔 **什么是高可用（High Availability, HA）？**
>
> **高可用**是指系统在长时间内持续提供服务的能力，通常用可用性（如 99.9%）来衡量。
>
> **为什么需要高可用？**
> - 停机可能导致业务损失（如无法交易）
> - 影响用户体验（如无法访问服务）
> - 损害品牌声誉（如服务不稳定）

#### 高可用架构要素

| 要素 | 说明 | 实现方式 |
|------|------|----------|
| **冗余** | 多个副本，避免单点故障 | 多副本部署 |
| **故障检测** | 及时发现故障 | 健康检查 |
| **故障转移** | 自动切换到备用副本 | 负载均衡器 + 健康检查 |
| **数据备份** | 防止数据丢失 | 定期备份 + 多副本存储 |

---

### 7.6.2 Kubernetes 多副本部署

> 📚 **前置知识**：什么是 Kubernetes？
>
> **Kubernetes（K8s）** 是一个开源的容器编排平台，用于自动化部署、扩展和管理容器化应用。
>
> **为什么选择 Kubernetes？**
> - 自动扩缩容（根据负载自动调整副本数）
> - 自愈能力（故障容器自动重启）
> - 负载均衡（自动分配流量）
> - 滚动更新（零停机部署）

#### Kubernetes 部署配置

```yaml
# k8s/deployment.yaml
"""
Kubernetes 部署配置

为什么使用 Kubernetes？
- 自动扩缩容（根据负载调整副本数）
- 自愈能力（故障容器自动重启）
- 滚动更新（零停机部署）
- 负载均衡（自动分配流量）
"""

apiVersion: apps/v1
kind: Deployment
metadata:
  name: hedge-fund-backend
  labels:
    app: hedge-fund-backend
spec:
  replicas: 3  # 运行 3 个副本
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
        ports:
        - containerPort: 8000

        # 资源限制
        resources:
          requests:
            memory: "512Mi"   # 最小内存
            cpu: "500m"       # 最小 CPU（0.5 核心）
          limits:
            memory: "2Gi"     # 最大内存
            cpu: "2000m"      # 最大 CPU（2 核心）

        # 环境变量
        envFrom:
        - secretRef:
            name: api-keys   # 从 Secret 读取 API 密钥
        - configMapRef:
            name: app-config # 从 ConfigMap 读取配置

        # 健康检查
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30  # 容器启动后 30 秒开始检查
          periodSeconds: 10        # 每 10 秒检查一次
          failureThreshold: 3      # 连续 3 次失败后重启

        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5         # 每 5 秒检查一次
          failureThreshold: 3

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
    port: 80          # Service 端口
    targetPort: 8000  # 容器端口
  type: LoadBalancer # 负载均衡器类型
```

> 💡 **关键配置说明**
>
> | 配置 | 说明 | 推荐值 |
> |------|------|--------|
> | `replicas` | 副本数 | 3（生产环境） |
> | `resources.requests` | 最小资源 | 根据实测需求设置 |
> | `resources.limits` | 最大资源 | requests 的 2-4 倍 |
> | `livenessProbe.initialDelaySeconds` | 健康检查延迟 | 应用启动时间 + 10 秒缓冲 |
> | `readinessProbe.periodSeconds` | 就绪检查间隔 | 5-10 秒 |

---

### 7.6.3 Redis 高可用

> 📚 **前置知识**：Redis 高可用方案
>
> | 方案 | 说明 | 复杂度 | 适用场景 |
> |------|------|--------|----------|
> | 主从复制 | 一个主节点，多个从节点 | 低 | 读多写少 |
> | Redis Sentinel | 主从 + 自动故障转移 | 中 | 通用场景 |
> | Redis Cluster | 分片 + 高可用 | 高 | 大规模数据 |

#### Redis 集群配置

```yaml
# docker-compose.redis-cluster.yml
"""
Redis 高可用集群配置

为什么需要 Redis 高可用？
- 缓存失效会导致性能急剧下降
- 会话丢失会导致用户登出
- 临时数据丢失可能导致功能异常
"""

services:
  redis-node-1:
    image: redis:7-alpine
    command: redis-server --cluster-enabled yes --cluster-config-file nodes.conf --cluster-node-timeout 5000 --appendonly yes
    ports:
      - "7001:7001"  # 客户端端口
      - "17001:17001"  # 集群总线端口
    volumes:
      - redis_data_1:/data

  redis-node-2:
    image: redis:7-alpine
    command: redis-server --cluster-enabled yes --cluster-config-file nodes.conf --cluster-node-timeout 5000 --appendonly yes
    ports:
      - "7002:7002"
      - "17002:17002"
    volumes:
      - redis_data_2:/data

  redis-node-3:
    image: redis:7-alpine
    command: redis-server --cluster-enabled yes --cluster-config-file nodes.conf --cluster-node-timeout 5000 --appendonly yes
    ports:
      - "7003:7003"
      - "17003:17003"
    volumes:
      - redis_data_3:/data

volumes:
  redis_data_1:
  redis_data_2:
  redis_data_3:
```

> 💡 **Redis 集群初始化**
>
> ```bash
> # 创建集群（每个主节点 1 个从节点）
> redis-cli --cluster create \
>   127.0.0.1:7001 \
>   127.0.0.1:7002 \
>   127.0.0.1:7003 \
>   --cluster-replicas 1
> ```

---

### 练习 7.6：高可用配置 ⭐⭐⭐

**任务**：配置 Kubernetes 多副本部署和 Redis 高可用集群。

**步骤**：
1. 编写 Kubernetes Deployment 配置（3 个副本）
2. 配置健康检查（liveness 和 readiness）
3. 编写 Kubernetes Service 配置
4. 配置 Redis 集群（3 个节点）
5. 测试故障转移（手动删除一个 Pod）

**要求**：
- [ ] Kubernetes 成功部署 3 个副本
- [ ] 健康检查正常工作
- [ ] 删除一个 Pod 后自动重建
- [ ] Redis 集群成功创建

**验证方法**：
```bash
# 查看 Pod 状态
kubectl get pods

# 手动删除一个 Pod
kubectl delete pod hedge-fund-backend-xxx

# 验证 Pod 自动重建
kubectl get pods -w

# 测试 Redis 集群
redis-cli -c -p 7001 cluster nodes
```

**扩展挑战** ⭐⭐⭐⭐：
- 配置 Horizontal Pod Autoscaler（HPA）自动扩缩容
- 实现蓝绿部署（零停机更新）
- 配置多区域部署（跨可用区高可用）

---

## 7.7 灾难恢复

### 7.7.1 为什么需要灾难恢复？

> 🤔 **什么是灾难恢复（Disaster Recovery, DR）？**
>
> **灾难恢复**是指在灾难事件（如硬件故障、自然灾害、人为错误）发生后，快速恢复系统和服务的能力。
>
> **灾难类型**：
> - 硬件故障（服务器、磁盘、网络设备）
> - 软件故障（Bug、配置错误）
> - 人为错误（误删除、误配置）
> - 自然灾害（火灾、洪水、地震）
> - 网络攻击（勒索软件、DDoS）

#### RTO 和 RPO

| 指标 | 说明 | 示例 |
|------|------|------|
| **RTO（Recovery Time Objective）** | 恢复时间目标（从灾难发生到恢复服务的时间） | 4 小时 |
| **RPO（Recovery Point Objective）** | 恢复点目标（允许丢失的数据量，通常用时间表示） | 1 小时 |

> 💡 **RTO/RPO 决策**
>
> | 场景 | RTO | RPO | 成本 |
> |------|-----|-----|------|
| 冷备 | 几天到几周 | 几天到几周 | 低 |
| 温备 | 几小时 | 几小时 | 中 |
> | 热备 | 几分钟到几小时 | 几分钟到几小时 | 高 |
> | 实时复制 | 几分钟 | 接近 0 | 非常高 |

---

### 7.7.2 备份策略

> 📚 **备份类型**
>
> | 类型 | 说明 | 恢复速度 | 成本 |
> |------|------|----------|------|
> | 全量备份 | 备份所有数据 | 慢 | 高（存储空间） |
> | 增量备份 | 只备份自上次备份后变化的数据 | 快 | 低 |
> | 差异备份 | 备份自上次全量备份后变化的数据 | 中 | 中 |

#### 数据备份脚本

```bash
#!/bin/bash
# scripts/backup.sh
"""
数据备份脚本

为什么需要自动化备份？
- 避免人为遗漏（忘记备份）
- 定期执行（每天、每小时）
- 可恢复验证（自动测试备份是否可用）
"""

set -e  # 遇到错误立即退出

# 配置
BACKUP_DIR="/backups/ai-hedge-fund"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=7  # 保留最近 7 天的备份

# 创建备份目录
mkdir -p ${BACKUP_DIR}

echo "=========================================="
echo "开始备份: ${DATE}"
echo "=========================================="

# ========== 备份 Redis 数据 ==========
echo "[1/3] 备份 Redis 数据..."
redis-cli BGSAVE  # 触发后台保存
sleep 10          # 等待保存完成

# 复制 RDB 文件
docker cp hedge-fund-redis-1:/data/dump.rdb \
  ${BACKUP_DIR}/redis_${DATE}.rdb

echo "Redis 备份完成: redis_${DATE}.rdb"

# ========== 备份配置文件 ==========
echo "[2/3] 备份配置文件..."
tar -czf ${BACKUP_DIR}/config_${DATE}.tar.gz \
  /app/config/ \
  /app/.env

echo "配置备份完成: config_${DATE}.tar.gz"

# ========== 备份数据库（如果使用）==========
# echo "[3/3] 备份数据库..."
# docker exec hedge-fund-db pg_dump -U postgres hedge_fund \
#   > ${BACKUP_DIR}/db_${DATE}.sql

# ========== 清理旧备份 ==========
echo "[4/4] 清理旧备份（保留最近 ${RETENTION_DAYS} 天）..."
find ${BACKUP_DIR} -name "*.rdb" -mtime +${RETENTION_DAYS} -delete
find ${BACKUP_DIR} -name "*.tar.gz" -mtime +${RETENTION_DAYS} -delete
find ${BACKUP_DIR} -name "*.sql" -mtime +${RETENTION_DAYS} -delete

echo "旧备份清理完成"

# ========== 备份验证 ==========
echo "[5/5] 验证备份完整性..."
if [ -f "${BACKUP_DIR}/redis_${DATE}.rdb" ]; then
    echo "✅ Redis 备份验证通过"
else
    echo "❌ Redis 备份验证失败"
    exit 1
fi

if [ -f "${BACKUP_DIR}/config_${DATE}.tar.gz" ]; then
    echo "✅ 配置备份验证通过"
else
    echo "❌ 配置备份验证失败"
    exit 1
fi

echo "=========================================="
echo "备份完成: ${DATE}"
echo "=========================================="

# 上传到云存储（可选）
# aws s3 sync ${BACKUP_DIR} s3://your-backup-bucket/ai-hedge-fund/
```

> 💡 **备份最佳实践**
>
> 1. **定期备份**：每天至少一次，关键数据每小时
> 2. **异地备份**：备份数据存储在不同位置（如 AWS S3）
> 3. **备份加密**：敏感数据加密备份
> 4. **备份验证**：定期恢复备份，确保可用性
> 5. **自动化**：使用 cron 或 Kubernetes CronJob 自动执行

---

### 7.7.3 故障转移

> 🤔 **故障转移（Failover）vs 故障恢复（Failback）**
>
> | 操作 | 说明 | 触发时机 |
> |------|------|---------|
> | **故障转移** | 将流量切换到备用系统 | 主系统故障 |
> | **故障恢复** | 将流量切换回主系统 | 主系统恢复 |

#### HAProxy 故障转移配置

```haproxy
# haproxy.cfg
"""
HAProxy 负载均衡和故障转移配置

为什么需要 HAProxy？
- 健康检查：自动检测后端服务状态
- 故障转移：自动切换到健康的后端
- 负载均衡：分配流量到多个后端
"""

frontend hedge_fund_frontend
    bind *:80
    mode http
    default_backend hedge_fund_backend

backend hedge_fund_backend
    mode http
    balance roundrobin  # 轮询策略

    # 健康检查
    option httpchk GET /health
    http-check expect status 200

    # 后端服务器
    server backend1 10.0.0.1:8000 check weight 100 rise 2 fall 3
    server backend2 10.0.0.2:8000 check weight 100 rise 2 fall 3 backup
    server backend3 10.0.0.3:8000 check weight 100 rise 2 fall 3 backup
    # weight: 权重（流量分配比例）
    # rise: 成功次数（连续成功多少次后标记为健康）
    # fall: 失败次数（连续失败多少次后标记为不健康）
    # backup: 备用服务器（主服务器都故障时才使用）

# 监控统计页面
listen stats
    bind *:8404
    stats enable
    stats uri /
    stats refresh 5s
    stats auth admin:admin  # 用户名:密码
```

> 💡 **健康检查参数**
>
> | 参数 | 说明 | 推荐值 |
> |------|------|--------|
> | `inter` | 检查间隔（毫秒） | 2000（2 秒） |
> | `rise` | 成功次数 | 2 |
> | `fall` | 失败次数 | 3 |
> | `timeout check` | 检查超时（毫秒） | 2000 |

---

### 练习 7.7：灾难恢复 ⭐⭐⭐

**任务**：实施灾难恢复策略。

**步骤**：
1. 编写自动化备份脚本
2. 配置 cron 定期执行备份（每天凌晨 2 点）
3. 恢复测试（删除数据后从备份恢复）
4. 配置 HAProxy 负载均衡和故障转移
5. 测试故障转移（手动关闭一个后端服务器）

**要求**：
- [ ] 备份脚本成功执行
- [ ] 备份文件生成并验证
- [ ] 旧备份自动清理
- [ ] 恢复测试成功
- [ ] HAProxy 故障转移正常工作

**验证方法**：
```bash
# 手动执行备份脚本
bash scripts/backup.sh

# 检查备份文件
ls -lh /backups/ai-hedge-fund/

# 配置 cron
crontab -e
# 添加：0 2 * * * /path/to/scripts/backup.sh >> /var/log/backup.log 2>&1

# 测试故障转移
# 停止一个后端服务器
docker stop hedge-fund-backend-1

# 访问 HAProxy 监控页面
curl http://localhost:8404
```

**扩展挑战** ⭐⭐⭐⭐：
- 配备异地备份（如 AWS S3）
- 实现 PITR（Point-In-Time Recovery）
- 配备灾难恢复演练计划

---

## 7.8 部署检查清单

### 7.8.1 部署前检查

| 检查项 | 状态 | 说明 |
|--------|------|------|
| **API 密钥配置** | ☐ | 所有必需的环境变量已设置 |
| **SSL/TLS 证书** | ☐ | 有效证书已安装，未过期 |
| **防火墙规则** | ☐ | 必要的端口已开放，不必要的已关闭 |
| **资源配额** | ☐ | CPU、内存、存储配额已设置并验证 |
| **监控配置** | ☐ | 指标和告警已配置并测试 |
| **日志配置** | ☐ | 日志收集和存储已设置 |
| **备份策略** | ☐ | 自动化备份已配置并测试 |
| **恢复测试** | ☐ | 恢复流程已测试验证 |
| **安全加固** | ☐ | 速率限制、输入验证、CORS 已配置 |
| **健康检查** | ☐ | 健康检查端点已实现并测试 |
| **负载均衡** | ☐ | 负载均衡器已配置并测试 |
| **故障转移** | ☐ | 故障转移机制已配置并测试 |

---

### 7.8.2 部署后验证

```bash
# ============================================
# 1. 检查服务状态
# ============================================
docker compose ps
kubectl get pods
kubectl get services

# ============================================
# 2. 检查健康端点
# ============================================
curl http://localhost:8000/health
curl http://localhost:8000/ready

# 预期输出：
# {"status":"healthy","uptime_seconds":...}
# {"ready":true,"checks":{...}}

# ============================================
# 3. 检查日志
# ============================================
docker compose logs -f backend
kubectl logs -f deployment/hedge-fund-backend

# 查找错误
docker compose logs backend | grep -i error
docker compose logs backend | grep -i critical

# ============================================
# 4. 运行冒烟测试
# ============================================
poetry run pytest tests/smoke/ -v

# ============================================
# 5. 检查资源使用
# ============================================
docker stats
kubectl top pods

# ============================================
# 6. 检查监控指标
# ============================================
curl http://localhost:9090/api/v1/query?query=hedge_fund_requests_total
curl http://localhost:9090/api/v1/alerts

# ============================================
# 7. 验证 SSL/TLS
# ============================================
curl -vI https://your-production-domain.com

# 应该看到：
# SSL certificate verify ok.
# TLSv1.2 or TLSv1.3

# ============================================
# 8. 验证速率限制
# ============================================
for i in {1..15}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    http://your-production-domain.com/api/analyze?ticker=AAPL
done

# 第 11 次请求应该返回 429

# ============================================
# 9. 验证 CORS
# ============================================
curl -H "Origin: https://malicious-site.com" \
  -H "Access-Control-Request-Method: POST" \
  -X OPTIONS http://your-production-domain.com/api/analyze

# 应该返回 403 或不包含 Access-Control-Allow-Origin
```

---

### 练习 7.8：部署验证 ⭐

**任务**：完成完整的部署验证流程。

**步骤**：
1. 使用部署前检查清单逐项检查
2. 执行部署后验证的所有步骤
3. 记录所有验证结果
4. 修复发现的问题

**要求**：
- [ ] 所有部署前检查项完成
- [ ] 所有部署后验证步骤成功
- [ ] 发现的问题已修复
- [ ] 生成验证报告

**验证报告模板**：

```markdown
# 部署验证报告

## 部署信息

- 部署日期：YYYY-MM-DD HH:MM:SS
- 部署人员：XXX
- 部署环境：生产/测试/开发
- 版本号：v1.0.0

## 部署前检查

| 检查项 | 状态 | 备注 |
|--------|------|------|
| API 密钥配置 | ✅/❌ | |
| SSL/TLS 证书 | ✅/❌ | |
| ... | | |

## 部署后验证

### 服务状态
- 容器状态：✅/❌
- Pod 状态：✅/❌

### 健康检查
- /health 端点：✅/❌
- /ready 端点：✅/❌

### 日志检查
- 错误日志：✅/❌
- 严重错误：✅/❌

### 冒烟测试
- 测试用例通过率：XX%

### 资源使用
- CPU 使用率：XX%
- 内存使用率：XX%

### 监控指标
- 指标收集：✅/❌
- 告警配置：✅/❌

### SSL/TLS
- 证书有效：✅/❌
- 协议版本：TLSv1.2/TLSv1.3

### 速率限制
- 限制生效：✅/❌

### CORS
- 配置正确：✅/❌

## 发现的问题

1. 问题描述
   - 严重程度：高/中/低
   - 解决方案：...
   - 状态：已解决/未解决

2. ...

## 总体评估

- 部署状态：成功/失败/部分成功
- 建议：...

## 签字确认

- 验证人员：XXX
- 审核人员：XXX
- 日期：YYYY-MM-DD
```

---

## 7.9 综合练习：完整的生产环境部署 ⭐⭐⭐

### 任务描述

从零开始，部署一个完整的生产环境 AI Hedge Fund 系统。

### 需求清单

#### 基础功能（必须完成）
- [ ] 使用 Docker Compose 或 Kubernetes 部署
- [ ] 配置生产环境环境变量
- [ ] 实现健康检查和就绪检查
- [ ] 配置结构化日志
- [ ] 实现基本的 Prometheus 指标
- [ ] 配置至少 3 个告警规则

#### 安全功能（必须完成）
- [ ] 实现速率限制（每 IP 每分钟 10 次请求）
- [ ] 实现输入验证（股票代码格式、数量限制）
- [ ] 配置 CORS（限制允许的域名）
- [ ] 配置 HTTPS（使用 Let's Encrypt）

#### 高可用功能（建议完成）
- [ ] 配置多副本部署（至少 3 个副本）
- [ ] 配置负载均衡（Nginx 或 HAProxy）
- [ ] 配置故障转移
- [ ] 配置 Redis 高可用（主从复制或集群）

#### 灾难恢复功能（建议完成）
- [ ] 实现自动化备份脚本
- [ ] 配置定期备份（每天）
- [ ] 实现恢复测试
- [ ] 备份异地存储（可选）

### 交付物

1. **配置文件**：
   - docker-compose.yml 或 Kubernetes 配置文件
   - .env.example（环境变量模板）
   - nginx.conf 或 haproxy.cfg
   - prometheus/alerts.yml

2. **脚本文件**：
   - scripts/backup.sh
   - scripts/verify-deployment.sh

3. **文档**：
   - 部署验证报告
   - 故障排查手册

### 评估标准

| 维度 | 标准 | 分值 |
|------|------|------|
| **功能完整性** | 所有必需功能已实现 | 25% |
| **代码质量** | 可读性、可维护性、注释完整 | 20% |
| **安全性** | 所有安全措施已实施 | 25% |
| **高可用性** | 故障转移、多副本部署 | 15% |
| **文档完整性** | 文档清晰、详细 | 15% |

### 参考实现

- 代码仓库：[待补充]
- 架构设计图：[待补充]
- 常见问题解答：[待补充]

---

## 进阶思考

### 问题 1：零停机部署策略 ⭐⭐⭐

如何实现零停机的部署和更新策略？

**提示**：
- 蓝绿部署（Blue-Green Deployment）
- 金丝雀发布（Canary Release）
- 滚动更新（Rolling Update）

**扩展阅读**：
- [Kubernetes 更新策略](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [蓝绿部署 vs 金丝雀发布](https://martinfowler.com/bliki/BlueGreenDeployment.html)

---

### 问题 2：密钥轮换策略 ⭐⭐⭐

如何在保证安全性的同时实现高效的密钥轮换？

**提示**：
- 密钥版本控制
- 灰度切换（新旧密钥共存）
- 自动化轮换流程

**扩展阅读**：
- [AWS Secrets Manager 轮换](https://docs.aws.amazon.com/secretsmanager/latest/userguide/rotating-secrets.html)
- [最佳实践：密钥管理](https://owasp.org/www-community/Secrets_Management_Cheat_Sheet)

---

### 问题 3：多区域部署 ⭐⭐⭐⭐

多区域部署如何保证数据一致性和服务可用性？

**提示**：
- 数据库主从复制
- 缓存一致性（Redis Cluster）
- DNS 负载均衡
- 跨区域延迟优化

**扩展阅读**：
- [多区域部署架构](https://aws.amazon.com/blogs/architecture/multi-region-strategies/)
- [CAP 定理](https://en.wikipedia.org/wiki/CAP_theorem)

---

## 版本信息

| 项目 | 信息 |
|------|------|
| 文档版本 | 2.0.0 |
| 最后更新 | 2026 年 2 月 13 日 |
| 适用版本 | 1.0.0+ |
| 难度级别 | ⭐⭐⭐（进阶） |
| 预计学习时间 | 3-4 小时 |

---

## 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v2.0.0 | 2026-02-13 | 全面升级：添加分层学习目标、难度标记、"为什么"解释、专家思维模型、完整练习设计 |
| v1.0.0 | 2026-01-XX | 初始版本 |

---

## 反馈与贡献

如果您在部署过程中遇到问题或有改进建议，欢迎通过以下方式反馈：

- **GitHub Issues**：[提交问题](https://github.com/virattt/ai-hedge-fund/issues)
- **Pull Request**：[贡献代码](https://github.com/virattt/ai-hedge-fund/pulls)
- **讨论区**：[GitHub Discussions](https://github.com/virattt/ai-hedge-fund/discussions)

---

## 参考资源

### 官方文档
- [Docker 官方文档](https://docs.docker.com/)
- [Kubernetes 官方文档](https://kubernetes.io/docs/)
- [Prometheus 官方文档](https://prometheus.io/docs/)
- [Nginx 官方文档](https://nginx.org/en/docs/)

### 最佳实践
- [The Twelve-Factor App](https://12factor.net/)
- [Google SRE Book](https://sre.google/sre-book/table-of-contents/)
- [AWS Well-Architected Framework](https://aws.amazon.com/architecture/well-architected/)

### 工具
- [Let's Encrypt（免费 SSL）](https://letsencrypt.org/)
- [Grafana（监控仪表板）](https://grafana.com/)
- [ELK Stack（日志收集）](https://www.elastic.co/what-is/elk-stack)

---

## 附录 A：快速参考

### 常用命令

| 任务 | 命令 |
|------|------|
| 启动服务 | `docker compose up -d` |
| 查看日志 | `docker compose logs -f backend` |
| 查看状态 | `docker compose ps` |
| 停止服务 | `docker compose down` |
| 进入容器 | `docker exec -it hedge-fund-backend bash` |

### 常见错误

| 错误 | 原因 | 解决方法 |
|------|------|---------|
| `Connection refused` | 服务未启动或端口未开放 | 检查容器状态和端口映射 |
| `API key not found` | 环境变量未配置 | 检查 .env 文件 |
| `Permission denied` | 端口已被占用或权限不足 | 检查端口占用和文件权限 |
| `Out of memory` | 内存不足 | 增加内存限制或优化应用 |

### 端口说明

| 端口 | 服务 | 说明 |
|------|------|------|
| 80 | HTTP | Web 访问 |
| 443 | HTTPS | 加密 Web 访问 |
| 8000 | 后端 API | FastAPI 服务 |
| 5173 | 前端 | Vite 开发服务器 |
| 9090 | Prometheus | 指标暴露端口 |
| 11434 | Ollama | LLM 服务 |

---

## 学习路径

**下一章**：[第八章：故障排查与性能优化](./08-troubleshooting.md)

**前置知识**：
- [第二章：Docker 入门](../level1-basics/02-docker-basics.md)
- [第三章：系统架构](../level2-core/03-architecture.md)
- [第六章：监控与日志](./06-monitoring.md)

**相关资源**：
- [运维手册](../references/operations-guide.md)
- [安全最佳实践](../references/security-best-practices.md)
- [性能优化指南](../references/performance-tuning.md)
