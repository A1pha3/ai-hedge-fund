# 系统问题分析总览

> **生成时间：** 2026-04-03  
> **分析范围：** 后端核心、前端应用、基础设施配置、依赖管理  
> **分析方法：** 静态代码分析 + 架构审查

---

## 文档目录

| 文档 | 描述 |
|------|------|
| [01-core-backend.md](./01-core-backend.md) | Python 核心层问题（agents、tools、data、graph） |
| [02-web-backend.md](./02-web-backend.md) | FastAPI Web 后端问题（路由、数据库、安全） |
| [03-frontend.md](./03-frontend.md) | React 前端问题（类型安全、性能、可访问性） |
| [04-infra-config.md](./04-infra-config.md) | 基础设施与配置问题（Docker、依赖、CI/CD） |

---

## 严重性等级说明

| 等级 | 标识 | 描述 |
|------|------|------|
| 严重 | 🔴 CRITICAL | 影响系统正确性或导致数据错误，须立即处理 |
| 高危 | 🟠 HIGH | 影响稳定性、安全或性能，近期处理 |
| 中危 | 🟡 MEDIUM | 代码质量或架构问题，计划处理 |
| 低危 | 🔵 LOW | 技术债务或规范问题，酌情处理 |

---

## 问题汇总（跨模块）

| 严重性 | 数量 | 主要分布 |
|--------|------|---------|
| 🔴 CRITICAL | 8 | LLM数据伪造、安全漏洞、路径遍历 |
| 🟠 HIGH | 18 | 异常处理、线程安全、内存泄漏、性能 |
| 🟡 MEDIUM | 45+ | 类型安全、日志、架构耦合、测试覆盖 |
| 🔵 LOW | 20+ | 命名规范、注释、死代码 |

---

## 最高优先级修复清单（Top 10）

1. 🔴 **LLM 数据伪造** — agents 产生虚假交易信号，见 `debug_data_analysis.py:82`
2. 🔴 **路径遍历漏洞** — `app/backend/routes/storage.py` 未验证文件名
3. 🔴 **JWT 密钥不安全** — 未设置环境变量时使用硬编码默认密钥
4. 🔴 **AUTH_DISABLED 绕过** — 环境变量可完全绕过认证
5. 🔴 **双包管理器冲突** — `poetry.lock` + `uv.lock` 同时存在导致依赖不一致
6. 🟠 **全局代理操作线程不安全** — `akshare_api.py` 直接修改 `requests` 全局方法
7. 🟠 **无界内存缓存** — `tushare_api.py` 内存缓存无上限，长期运行会 OOM
8. 🟠 **API 密钥明文返回** — REST API 响应中暴露完整 API key 值
9. 🟠 **前端无组件缓存** — 80+ 个组件无 `React.memo`，频繁重渲染
10. 🟠 **无 CI/CD 流水线** — `.github/workflows/` 目录不存在，无自动化质量门控
