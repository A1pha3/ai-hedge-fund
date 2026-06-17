# 6. 数据基础设施

> 本节对应主文档 §6,包含数据源、缓存系统、数据质量。

## 6.1 数据源

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | Tushare 数据源 (A 股) | ✅ | `src/tools/tushare_api.py` — 日线/分钟线/财务/龙虎榜/北向资金 |
| 2 | AKShare 数据源 (A 股) | ✅ | `src/tools/akshare_api.py` — 行情/分钟/资金流/龙虎榜 |
| 3 | Financial Datasets (美股) | ✅ | `src/tools/api.py` — 美股数据源 |
| 4 | 数据路由器 | ✅ | `src/data/router.py` — 自动识别 A 股/美股路由到对应数据源 |
| 5 | Tushare 批量获取 | ✅ | `src/tools/tushare_batch_fetch_helpers.py` |
| 6 | 申万行业分类 | ✅ | `src/tools/tushare_sw_industry_helpers.py` |

## 6.2 缓存系统

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | SQLite 磁盘缓存 | ✅ | `src/data/enhanced_cache.py` — 持久化缓存 |
| 2 | LRU 内存缓存 | ✅ | 热点数据内存缓存 |
| 3 | 缓存基准测试 | ✅ | `src/data/cache_benchmark.py` — 缓存命中率分析 |
| 4 | 缓存管理 CLI | ✅ | `scripts/manage_data_cache.py` — 查看/清理缓存 |
| 5 | 可配置缓存路径 | ✅ | `DISK_CACHE_PATH` 环境变量 |

## 6.3 数据质量

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 数据验证器 (V2) | ✅ | `src/data/validator_v2.py` — 增强验证框架 |
| 2 | 验证规则集 | ✅ | `src/data/validation_rules.py` |
| 3 | 数据清洗 | ✅ | `src/data/cleaner.py` |
| 4 | 健康检查 | ✅ | `src/data/health.py` — 当前活跃健康监控（DataSourceHealth / HealthMonitor）；~~`src/data/health_checker.py`~~ 已删除（零调用方 orphan） |
| 5 | 质量监控 | ⛔ 已移除 | ~~`src/data/quality_monitor.py`~~（R20 删除：零调用方，详见 [../../architecture/data-layer.md](../../architecture/data-layer.md)） |
| 6 | 数据快照 | ✅ | `src/data/snapshot.py` — Markdown + JSON 双格式快照 |

---

**相关章节**: [1. 核心筛选流水线](./core-pipeline.md) | [7. LLM 系统](./llm-system.md)
