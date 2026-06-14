# CLI 命令速查表

> 面向 power-user 的完整 CLI 命令索引。默认前门请优先看 [`../QUICKSTART.md`](../QUICKSTART.md)。

## 数据获取与缓存
- `--preheat` — 缓存预热(5 任务并发)
- `--preheat --preheat-tasks=daily_basic,daily_prices` — 指定任务
- `--preheat --force` — 强制刷新
- `--preheat --list-tasks` — 查看可用任务

## 核心选股
- `--auto` — 全市场自动筛选
- `--auto --top-n=20` — Top N 推荐
- `--auto --trade-date=20260607` — 指定日期
- `--top` / `--top 20` — **快速查看最近一次 --auto 的 Top N 推荐**(无需重跑,秒级返回) — R20.2 新增
  - **R20.5 扩展**: `--top` 支持过滤参数（直接追加） — `--top 20 --industry=电子 --min-score=0.5 --exclude-st --min-consecutive=2 --ticker=000001 --name-contains=银行`
- `--explain 000001` — 解释推荐原因(因子明细+事件线+行业排名)
- `--screen-only` — 仅 Layer A+B 评分
- `--daily-gainers` — 每日涨幅榜筛选(独立于 --auto 的简化筛选入口)

## 市场分析
- `--market-status` — 市场温度计
- `--industry-rotation` — 行业轮动信号
- `--factor-ic` — 因子 IC 排行
- `--macro` — 宏观经济面板
- `--sector-strength` — 行业强度排序 (P10-2 行业轮动加权, 展示推荐标的的板块动量)
- `--signal-momentum` — 信号动量评分 (P10-1 跟踪 score_b 时间序列轨迹)
- `--volume-confirm` — 量价确认 (P11-2 检查成交量是否支持价格变动)

## 推荐辅助
- `--tracking-summary` — 历史推荐胜率
- `--winrate-dashboard` — 胜率看板
- `--conditional-orders` — 条件单建议
- `--compare 300750,600519,000001` — 标的对比
- `--stock-detail 300750` — 标的深度分析
- `--custom-weights --trend=0.4 --mean-reversion=0.1 --fundamental=0.3 --event-sentiment=0.2` — 自定义权重

## 数据质量与验证
- `--check-freshness` — 数据新鲜度检查 (P6-1)
- `--signal-consistency` — 信号一致性交叉校验 (P7-1)
- `--dynamic-threshold` — 动态推荐阈值 (P7-2)
- `--data-quality-audit` — 数据质量审计 (P0-10)
- `--confidence-calibration` — 置信度校准 (P0-9)

## 决策链
- `--top-picks --count=5` — **默认前门**: 代表票去重 + Buy/Hold/Avoid + T+30 edge + 样本量
- `--decision-flow` — 一键决策流水线: 选股→新鲜度→一致性→阈值→异常→预期收益→变动 (P8-1+P9-2)
- `--daily-brief` — 盘前 Top 3 决策卡（补充摘要） (P0-7)
- `--why-not 000001` — 信号冲突透明化 (P0-8)
- `--conviction-ranking` — 综合信心排名 (P0-11)
- `--expected-returns` — 预期收益估算 (P9-1)
- `--daily-delta` — 推荐日间变动 (P6-2)
- `--outlier-detect` — 异常值检测 (P8-2)

## 闭环验证
- `--verify-recommendations` — 推荐闭环验证 (P3-1)
- `--cross-picks` — 行业+个股交叉选择 (P3-3)
- `--build-portfolio` — 组合构建 (P3-4)
- `--calibrate-weights` — 策略权重校准 (P3-2)

## 组合管理
- `--rebalance` — 组合再平衡建议
- `--performance-report` — 组合绩效周报/月报
- `--attribution-daily` — 策略归因日报

## 自选池
- `--watchlist-add 000001 --name "平安银行" --tags 银行 高股息` — 添加
- `--watchlist-remove 000001` — 移除
- `--watchlist-list` — 列表
- `--watchlist-status` — 状态评分

## 报告导出与推送
- `--export-pdf` — PDF 报告导出
- `--export-conditional-orders [--broker=huatai|gtja|ths]` — 导出券商条件单格式 (P1-13)
- `--push-test --channel=wecom` — 测试推送配置
- `--weekly-report [--start-date --end-date --channel]` — 组合体检周报推送 (P2-10, 缺省本周一/五 + wecom)

## 单股分析
- `--ticker 000001,300750` — 单票分析
- `--pipeline` — 完整日度流水线

## 环境变量（power-user 调参）

> 以下 **32 个环境变量**用于运行时调优与实验开关，全部带缺省值、可不配置即可运行。**新手配置请看 [`/.env.example`](../../../.env.example)**；本节仅收录进阶调参项。阈值语义以代码常量定义为准（见各表"代码"列）。

### AKShare 运行时调优

| 变量 | 默认 | 类型 | 说明 | 代码 |
|---|---|---|---|---|
| `AKSHARE_INTRADAY_TIMEOUT_SECONDS` | `2.5` | float | 分时数据请求超时（秒） | `src/tools/akshare_api.py` |
| `AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS` | `8` | float | 个股新闻请求超时（秒） | `src/tools/akshare_api.py` |
| `AKSHARE_SESSION_POOL_SIZE` | `10` | int | HTTP 会话池大小 | `src/tools/akshare_runtime_helpers.py` |

### 候选池调优（`CANDIDATE_POOL_*`）

候选池规模与影子池（shadow pool）阈值。影子池在正式池之外额外追踪 **流动性走廊（liquidity corridor）** 与 **重新分桶（rebucket）** 两条候选轨道，阈值含义见 `src/screening/candidate_pool.py` 顶部常量。

**基础**

| 变量 | 默认 | 类型 | 说明 |
|---|---|---|---|
| `MAX_CANDIDATE_POOL_SIZE` | `300` | int | 候选池最大规模 |
| `CANDIDATE_POOL_BTST_LIQUIDITY_RANK_BUCKET` | `2500` | float | 流动性排名分桶阈值 |

**流动性走廊影子池**

| 变量 | 默认 | 类型 |
|---|---|---|
| `CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_MAX_TICKERS` | `4` | int |
| `CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE` | `3.0` | float |
| `CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_MAX_CUTOFF_SHARE` | `0.20` | float |
| `CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE` | `2.5` | float |
| `CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MAX_CUTOFF_SHARE` | `0.30` | float |
| `CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE` | `0.075` | float |
| `CANDIDATE_POOL_SHADOW_LIQUIDITY_CORRIDOR_VISIBILITY_GAP_MAX_CUTOFF_SHARE` | `0.35` | float |

**重新分桶影子池**

| 变量 | 默认 | 类型 |
|---|---|---|
| `CANDIDATE_POOL_SHADOW_REBUCKET_MAX_TICKERS` | `1` | int |
| `CANDIDATE_POOL_SHADOW_REBUCKET_MIN_GATE_SHARE` | `8.0` | float |
| `CANDIDATE_POOL_SHADOW_REBUCKET_MIN_CUTOFF_SHARE` | `0.35` | float |
| `CANDIDATE_POOL_SHADOW_REBUCKET_MAX_CUTOFF_SHARE` | `0.80` | float |
| `CANDIDATE_POOL_SHADOW_REBUCKET_FOCUS_MIN_CUTOFF_SHARE` | `0.25` | float |
| `CANDIDATE_POOL_SHADOW_REBUCKET_VISIBILITY_GAP_MIN_CUTOFF_SHARE` | `0.25` | float |

**手动关注票覆盖**（逗号分隔的 6 位代码，留空即不覆盖）

| 变量 | 默认 | 说明 |
|---|---|---|
| `CANDIDATE_POOL_SHADOW_FOCUS_TICKERS` | (空) | 通用关注票 |
| `CANDIDATE_POOL_SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS` | (空) | 流动性走廊关注票 |
| `CANDIDATE_POOL_SHADOW_FOCUS_REBUCKET_TICKERS` | (空) | 重新分桶关注票 |
| `CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_TICKERS` | (空) | 可见性缺口关注票 |
| `CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_LIQUIDITY_CORRIDOR_TICKERS` | (空) | 可见性缺口 × 走廊关注票 |
| `CANDIDATE_POOL_SHADOW_VISIBILITY_GAP_REBUCKET_TICKERS` | (空) | 可见性缺口 × 重分桶关注票 |

### BTST 策略开关

**行为开关**

| 变量 | 默认 | 说明 |
|---|---|---|
| `BTST_EXCLUDE_LIMIT_UP` | (空/off) | 设为 `1`/`true`/`yes`/`on` 时**排除涨停股**；默认**包含**（涨停股 T+1 胜率 53%，优于普通候选池） |
| `BTST_PAYOFF_REVIEW_LANE_MODE` | (空/off) | 盈亏复核通道模式 |

**0422 实验开关**（默认全部 `off`，仅用于 0422 优化轮回测对照；代码见 `src/research/artifacts.py` + `src/paper_trading/runtime_session_helpers.py`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `BTST_0422_P1_REGIME_GATE_MODE` | `off` | P1 市场状态门控 |
| `BTST_0422_P2_REGIME_GATE_MODE` | `off` | P2 市场状态门控 |
| `BTST_0422_P3_PRIOR_QUALITY_MODE` | `off` | P3 先验质量 |
| `BTST_0422_P4_PRIOR_SHRINKAGE_MODE` | `off` | P4 先验收缩 |
| `BTST_0422_P5_EXECUTION_CONTRACT_MODE` | `off` | P5 执行契约 |
| `BTST_0422_P6_RISK_BUDGET_MODE` | `off` | P6 风险预算 |
| `BTST_0422_P7_GAP_OVERLAY_MODE` | `off` | P7 缺口叠加 |

**P7 缺口阈值**（仅在 `BTST_0422_P7_GAP_OVERLAY_MODE` 开启时生效）

| 变量 | 默认 | 类型 | 说明 |
|---|---|---|---|
| `BTST_0422_P7_GAP_WARN_THRESHOLD` | `0.005` | float | 缺口告警阈值（开盘跳空比例） |
| `BTST_0422_P7_GAP_HALT_THRESHOLD` | `0.01` | float | 缺口熔断阈值 |
| `BTST_0422_P7_GAP_WARN_SIZE_DISCOUNT` | `0.5` | float | 告警时仓位折扣 |

---

**相关章节**: [9. CLI 工具](./cli-tools.md) | [优化功能](./optimizations.md)
