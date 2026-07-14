---
难度: ⭐⭐
类型: 参考手册
预计时间: 25 分钟
前置知识:
  - 完成 [安装指南](./installation.md)
  - 理解 [每日工作流](./daily-workflow.md)
  - 配置好 `.env` 中的 `TUSHARE_TOKEN` 与默认 LLM 模型
---

# CLI 完整参考

本文档列出 A 股每日选股系统的全部命令行入口。所有命令均通过 `uv run python src/main.py` 调起，命令名与参数严格对齐 `src/cli/dispatcher.py` 与 `src/cli/input.py` 的注册项，可直接复制运行。

## 命令分类索引

| 分类 | 命令 | 一句话用途 |
|---|---|---|
| 主流程 | `--auto` | 全市场四策略融合筛选，写 `auto_screening_YYYYMMDD.json` |
| 主流程 | `--daily-action` | 凸性 setup 扫描，输出次日 BUY 信号 |
| 主流程 | `--top-picks` | 默认前门：代表票 + Buy/Hold/Avoid + T+30 证据 |
| 主流程 | `--top [N]` | 读取最近一次 `--auto` 报告的 Top N（秒级） |
| 主流程 | `--explain TICKER` | 解释单票推荐原因 |
| 主流程 | `--why-not TICKER` | 反事实解释：为何没推荐 |
| 主流程 | `--preheat` | 缓存预热 |
| 报告诊断 | `--daily-brief` | 盘前 Top 3 决策卡 |
| 报告诊断 | `--decision-flow` | 一键决策流水线 |
| 报告诊断 | `--check-freshness` | 数据新鲜度检查 |
| 报告诊断 | `--daily-delta` | 推荐日间变动 |
| 报告诊断 | `--signal-consistency` | 信号一致性交叉校验 |
| 报告诊断 | `--dynamic-threshold` | 动态推荐阈值 |
| 报告诊断 | `--outlier-detect` | 异常值检测 |
| 报告诊断 | `--expected-returns` | 预期收益估算 |
| 报告诊断 | `--signal-momentum` | 信号动量评分 |
| 报告诊断 | `--sector-strength` | 板块强度排序 |
| 报告诊断 | `--composite-score` | 综合信心评分 |
| 报告诊断 | `--volume-confirm` | 量价确认 |
| 报告诊断 | `--trend-resonance` | 多周期趋势共振 |
| 报告诊断 | `--tracking-summary` | 历史推荐胜率 |
| 报告诊断 | `--data-quality-audit` | 数据质量审计 |
| 报告诊断 | `--confidence-calibration` | 置信度校准 |
| 报告诊断 | `--conviction-ranking` | 综合信心排名 |
| 系统配置 | `--show-default-model` | 打印当前默认 LLM 模型/Provider |
| 系统配置 | `--position-check` | 持仓健康检查 |
| 系统配置 | `--market-status` | 市场温度计 |
| 系统配置 | `--industry-rotation` | 行业轮动信号 |
| 系统配置 | `--macro` | 宏观经济面板 |
| 系统配置 | `--performance-report` | 组合绩效周报/月报 |
| 系统配置 | `--strategy-report` | 策略绩效报告 |
| 系统配置 | `--weekly-report` | 组合体检周报推送 |
| 系统配置 | `--watchlist-add/remove/list/status` | 自选池管理 |
| 回测验证 | `src/backtester.py` | 上游回测器（多票） |
| 回测验证 | `scripts/backtest_exit_strategies.py` | 止损策略对比 |
| 回测验证 | `--verify-recommendations` | 推荐追踪自动回测 |
| 回测验证 | `--reconcile trade_log.csv` | 实盘对账 |
| 回测验证 | `--refresh-regime-winrates` | 重算 regime 历史胜率 |
| 回测验证 | `--flywheel-health` | 数据飞轮健康检查 |
| 回测验证 | `--winrate-dashboard` | 胜率看板 |
| 缓存管理 | `scripts/manage_data_cache.py` | 缓存统计/清空 |
| 缓存管理 | `scripts/validate_data_cache_reuse.py` | 跨进程复用验证 |
| 缓存管理 | `scripts/benchmark_data_cache_reuse.py` | 冷热启动基准 |
| 筛选 | `--daily-gainers` | 当日涨幅榜 |
| 筛选 | `--top-setups` | Phase 1 凸性 setup 检测器（shadow）⚠ 未经验证 |
| 筛选 | `--cross-picks` | 强势行业 × 行业最优个股交叉选择 |
| 筛选 | `--build-portfolio` | Top N 推荐组合构建器 |
| 筛选 | `--stock-detail` | 个股深度详情 |
| 筛选 | `--compare` | 多票对比工具 |
| 筛选 | `--custom-weights` | 自定义四策略权重重跑 |
| 流水线 | `--pipeline` | 机构化多策略流水线（Layer A + Layer B + 后续） |
| 流水线 | `--screen-only` | 仅运行 Layer A + Layer B 筛选 |
| 研究分析 | `--factor-ic` | 因子 IC 分析 |
| 研究分析 | `--calibrate-weights` | 基于因子 IC 自动调权 |
| 研究分析 | `--attribution-daily` | 日内归因分析 |
| 交易执行 | `--conditional-orders` | ATR-based 条件单建议 |
| 交易执行 | `--export-conditional-orders` | 导出券商条件单格式 |
| 交易执行 | `--rebalance` | 组合再平衡 |
| 导出推送 | `--export-pdf` | 报告 PDF 导出 |
| 导出推送 | `--push-test` | 推送通道测试 |

## 主流程命令

### `--auto`：全市场自动筛选

```bash
uv run python src/main.py --auto
uv run python src/main.py --auto --top-n=20
uv run python src/main.py --auto --trade-date=20260709
uv run python src/main.py --auto --strict-quality
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--top-n` | int | 10 | 写入报告的 Top N 推荐数 |
| `--trade-date` | YYYYMMDD | 当日 | 显式指定交易日（17:00 后才用当日） |
| `--strict-quality` | flag | off | 数据质量降级时返回退出码 3 |

输出：`data/reports/auto_screening_YYYYMMDD.json`。字段含义见 [输出报告解读](./interpreting-reports.md)。

### `--daily-action`：凸性 setup 动作

```bash
uv run python src/main.py --daily-action
uv run python src/main.py --daily-action --end-date=20260709
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--end-date` | YYYY-MM-DD / YYYYMMDD | 自动探测 | 覆盖信号日，跳过 17:00 守卫 |

从 `data/price_cache/*.csv` 直扫全市场，不依赖 `--auto` 候选池。环境变量 `DAILY_ACTION_DISABLED_SETUPS` 默认含 `oversold_bounce`，设为 `none` 可恢复全部 setup。

### `--top-picks`：默认前门

```bash
uv run python src/main.py --top-picks
uv run python src/main.py --top-picks --count=5 --lookback=5 --profit-aware
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--count` | int | 5 | 输出代表票数 |
| `--lookback` | int | 5 | T+30 命中证据回看天数 |
| `--profit-aware` | flag | off | 启用经验胜率排序（回测 47% → 62%） |

### `--top [N]`：读取最近一次报告

```bash
uv run python src/main.py --top
uv run python src/main.py --top 20
uv run python src/main.py --top 20 --industry=电子 --min-score=0.5 --exclude-st --min-consecutive=2 --ticker=000001 --name-contains=银行
```

| 过滤参数 | 类型 | 说明 |
|---|---|---|
| `--industry` | str | 申万行业子串匹配 |
| `--min-score` / `--max-score` | float | score_b 区间 |
| `--min-market-cap` / `--max-market-cap` | float | 市值区间（元） |
| `--min-consecutive` | int | 最低连续推荐天数 |
| `--ticker` | str | 精确匹配 6 位代码 |
| `--name-contains` | str | 名称子串 |
| `--exclude-st` | flag | 排除 ST/*ST |

### `--explain` 与 `--why-not`

```bash
uv run python src/main.py --explain 000001
uv run python src/main.py --why-not 000001
```

二者均读取最新 `auto_screening` 报告，不重跑评分。`--explain` 给出因子明细、事件线、行业排名；`--why-not` 给出反事实条件（差几分能进 Top）。

### `--preheat`：缓存预热

```bash
uv run python src/main.py --preheat
uv run python src/main.py --preheat --preheat-tasks=daily_basic,daily_prices
uv run python src/main.py --preheat --preheat-date=20260709 --force
uv run python src/main.py --preheat --list-tasks
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `--preheat-date` | YYYYMMDD | 指定预热日期 |
| `--preheat-tasks` | csv | 任务列表 |
| `--force` | flag | 强制刷新 |
| `--list-tasks` | flag | 列出可用任务 |

## 报告与诊断命令

下列命令大多读取最近一次 `--auto` 报告，秒级返回，不重跑评分。

| 命令 | 关键参数 | 用途 |
|---|---|---|
| `--daily-brief` | 无 | 盘前 Top 3 一句话 + 市场状态 + 行业轮动 |
| `--decision-flow` | `--top-n N` `--lookback D` | 串新鲜度→一致性→阈值→异常→预期收益→变动 |
| `--check-freshness` | `--trade-date YYYYMMDD` | 校验各数据源是否对齐到目标交易日 |
| `--daily-delta` | `--top-n N` `--delta-lookback D` | 推荐池逐日增减 |
| `--signal-consistency` | `--top-n N` | 多信号方向一致性交叉检查 |
| `--dynamic-threshold` | `--lookback D` `--target-hit-rate P` | 基于历史命中率推算 score_b 推荐阈值 |
| `--outlier-detect` | `--top-n N` `--threshold F` | 标记推荐中显著偏离历史分布的票 |
| `--expected-returns` | `--top-n N` `--lookback D` | 用历史校准曲线估算每票期望收益 |
| `--signal-momentum` | （argv 透传） | 跟踪 score_b 时间序列轨迹 |
| `--sector-strength` | （argv 透传） | 推荐标的的板块动量排序 |
| `--composite-score` | （argv 透传） | 多信号融合为单一排名分 |
| `--volume-confirm` | （argv 透传） | 成交量是否支持价格变动 |
| `--trend-resonance` | （argv 透传） | 5d / 20d / 60d 趋势同向共振 |
| `--tracking-summary` | `--tracking-lookback D` | T+1 / T+3 / T+5 历史追踪胜率 |
| `--data-quality-audit` | `--top-n N` `--threshold F` | 推荐标的数据完整性审计 |
| `--confidence-calibration` | `--top-n N` `--lookback D` | score 校准为历史命中率/预期收益 |
| `--conviction-ranking` | `--top-n N` `--lookback D` `--score-weight` `--consecutive-weight` `--quality-weight` `--calibration-weight` | 综合信心排名，四权重和须为 1.0 ± 0.01 |

## 系统与配置命令

```bash
uv run python src/main.py --show-default-model
uv run python src/main.py --position-check
uv run python src/main.py --market-status --market-date=20260709
uv run python src/main.py --industry-rotation --ir-top=5 --ir-bottom=3
uv run python src/main.py --macro
uv run python src/main.py --performance-report --period=weekly --pr-end-date=20260709
uv run python src/main.py --strategy-report
uv run python src/main.py --weekly-report --start-date=20260703 --end-date=20260709 --channel=wecom
uv run python src/main.py --watchlist-add 000001 --name "平安银行" --tags 银行 高股息
uv run python src/main.py --watchlist-list --filter-tag=银行
uv run python src/main.py --watchlist-status
```

`--show-default-model` 不需要 `--tickers`，打印 `.env` 解析出的默认 Provider 与模型名后退出。系统不再回退到 `MINIMAX_MODEL` 等变量，未显式设置时会失败而非静默降级。

## 回测与验证命令

```bash
uv run python src/backtester.py --ticker AAPL,MSFT,NVDA
uv run python scripts/backtest_exit_strategies.py
uv run python src/main.py --verify-recommendations --verify-lookback=30 --verify-detail
uv run python src/main.py --reconcile trade_log.csv
uv run python src/main.py --refresh-regime-winrates --output=out.json --min-samples=10
uv run python src/main.py --flywheel-health
uv run python src/main.py --winrate-dashboard --winrate-lookback=30
```

`--reconcile` 接受 v1 CSV：`ticker,buy_date,buy_price,sell_date,sell_price`。`--flywheel-health` 输出 JSON，供 cron 检测 `tracking_history` 是否仍在累积（防静默停滞）。

## 缓存管理

```bash
.venv/bin/python scripts/manage_data_cache.py stats
.venv/bin/python scripts/manage_data_cache.py stats --output=cache_stats.json
.venv/bin/python scripts/manage_data_cache.py clear --yes
.venv/bin/python scripts/validate_data_cache_reuse.py --trade-date 20260709 --ticker 000001
.venv/bin/python scripts/benchmark_data_cache_reuse.py
```

`clear --yes` 跳过二次确认。`validate_data_cache_reuse.py` 用于跨进程复用前校验指纹一致性。

## 筛选与组合命令

围绕 `--auto` 报告做二次筛选、对比、组合构建与权重实验的命令集合。除 `--daily-gainers` 直读 `price_cache` 外，其余均以最新 `auto_screening` 报告为输入。

### `--daily-gainers`：当日涨幅榜

```bash
uv run python src/main.py --daily-gainers
```

无额外参数。直读 `data/price_cache/*.csv` 计算当日涨幅并排序输出，不依赖 `--auto` 报告。

### `--top-setups`：Phase 1 凸性 setup 检测器（shadow）

⚠ **未经验证、仅供观察**：当前强制 shadow 模式，Phase 0 IS/OOS 验证完成前不输出 Kelly 仓位。

```bash
uv run python src/main.py --top-setups
```

从最新 `auto_screening` 报告取 Top 30 推荐，扫进攻型 alpha setup（涨停突破、超跌反弹）。分布 lookup 未填充时仅打印命中、不出 Kelly 仓位，并提示下一步操作（backfill 资金流 → 跑 Phase 0 `scripts/setup_research.py` → 回填 `distribution_lookup`）。

### `--cross-picks`：行业 × 个股交叉选择（P3-3）

```bash
uv run python src/main.py --cross-picks
uv run python src/main.py --cross-picks --cp-date=20260709 --cp-top-industries=5 --cp-picks-per-industry=3
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--cp-date` | YYYYMMDD | 当日 | 交易日期 |
| `--cp-top-industries` | int | 5 | 取强势行业数 |
| `--cp-picks-per-industry` | int | 3 | 每个行业取几个最优个股 |

### `--build-portfolio`：推荐组合构建器（P3-4）

```bash
uv run python src/main.py --build-portfolio
uv run python src/main.py --build-portfolio --pf-date=20260709 --pf-top-n=10 --pf-position-cap=0.20 --pf-industry-cap=0.30
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--pf-date` | YYYYMMDD | 当日 | 交易日期 |
| `--pf-top-n` | int | 10 | 取 Top N 推荐构建组合 |
| `--pf-position-cap` | float | 0.20 | 单票权重上限 |
| `--pf-industry-cap` | float | 0.30 | 行业集中度上限 |

### `--stock-detail`：个股深度详情

```bash
uv run python src/main.py --stock-detail 300750
uv run python src/main.py --stock-detail=300750 --sd-date=20260709
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--stock-detail` | 6 位代码 | 必填 | 个股代码，支持 `=300750` 与位置参数两种写法 |
| `--sd-date` | YYYYMMDD | 当日 | 数据快照日 |

### `--compare`：多票对比工具

```bash
uv run python src/main.py --compare 300750,600519,000001
uv run python src/main.py --compare=300750,600519 --metrics=trend_score,score_b --no-radar
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--compare` | csv | 必填 | 6 位代码列表，支持 `=` 与位置参数两种写法 |
| `--metrics` | csv | 全部 | 仅展示指定字段，逗号分隔 |
| `--no-radar` | flag | off | 跳过雷达图渲染 |

### `--custom-weights`：自定义四策略权重重跑

```bash
uv run python src/main.py --custom-weights --trend=0.4 --mean-reversion=0.3 --fundamental=0.2 --event-sentiment=0.1
uv run python src/main.py --custom-weights --trend=0.5 --mean-reversion=0.5 --top-n=20 --trade-date=20260709
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--trend` | float | 0.25 | 趋势策略权重 |
| `--mean-reversion` | float | 0.25 | 均值回归策略权重 |
| `--fundamental` | float | 0.25 | 基本面策略权重 |
| `--event-sentiment` | float | 0.25 | 事件情绪策略权重 |
| `--top-n` | int | 10 | 输出 Top N |
| `--trade-date` | YYYYMMDD | 当日 | 显式交易日 |

## 流水线命令

机构化多策略流水线，按 Layer A（基础筛选）→ Layer B（多策略打分）→ 后续（排序/写报告）顺序执行。两条命令均**必须显式传 `--trade-date`**。

### `--pipeline`：完整多策略流水线

```bash
uv run python src/main.py --pipeline --trade-date=20260709
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--trade-date` | YYYYMMDD | 必填 | 交易日期 |

### `--screen-only`：仅运行 Layer A + Layer B

```bash
uv run python src/main.py --screen-only --trade-date=20260709
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--trade-date` | YYYYMMDD | 必填 | 交易日期 |

跳过排序与报告写入，仅输出 Layer A + Layer B 候选集，便于上游脚本对接。

## 研究分析命令

### `--factor-ic`：因子 IC 分析

```bash
uv run python src/main.py --factor-ic
uv run python src/main.py --factor-ic --ic-lookback=60 --ic-method=spearman
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--ic-lookback` | int | 30 | 回看天数 |
| `--ic-method` | str | spearman | 相关系数方法（如 spearman / pearson） |

### `--calibrate-weights`：策略动态权重校准（P3-2）

```bash
uv run python src/main.py --calibrate-weights
uv run python src/main.py --calibrate-weights --calibrate-lookback=60
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--calibrate-lookback` | int | 30 | 基于过去多少天的 IC 校准权重 |

基于 `--factor-ic` 输出自动调权，结果可直接喂回 `--custom-weights`。

### `--attribution-daily`：日内归因分析

```bash
uv run python src/main.py --attribution-daily --date=20260709
uv run python src/main.py --attribution-daily --date=20260709 --positions=data/positions.json
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--date` | YYYYMMDD | 当日 | 归因交易日 |
| `--positions` | path | 运行时默认 | 持仓文件路径 |

## 交易执行命令

把推荐转化为可执行委托的辅助工具链：先 `--conditional-orders` 出建议，再用 `--export-conditional-orders` 转成券商格式，最后用 `--rebalance` 跟踪持仓漂移。

### `--conditional-orders`：条件单建议（ATR-based）

```bash
uv run python src/main.py --conditional-orders
uv run python src/main.py --conditional-orders --top-n=20 --atr-period=14 --co-lookback=60
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--top-n` | int | 20 | 取推荐 Top N 生成建议 |
| `--atr-period` | int | 14 | ATR 周期 |
| `--co-lookback` | int | 60 | 价格回看天数 |

### `--export-conditional-orders`：导出券商条件单格式（P1-13）

```bash
uv run python src/main.py --export-conditional-orders --broker=huatai
uv run python src/main.py --export-conditional-orders --broker=gtja --nav=100000
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--broker` | str | huatai | 券商格式：`huatai` / `gtja` / `ths` |
| `--nav` | float | 无 | 总资产（元）；提供时按等权计算委托手数（向下取整到 100 股），缺省每票固定 100 股 |

### `--rebalance`：组合再平衡

```bash
uv run python src/main.py --rebalance
uv run python src/main.py --rebalance --positions-path=data/positions.json --drift-threshold=0.05
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--positions-path` | path | 运行时默认 | 持仓文件路径，别名 `--positions` |
| `--drift-threshold` | float | 0.05 | 触发再平衡的权重漂移阈值 |

## 导出与推送命令

### `--export-pdf`：报告 PDF 导出

```bash
uv run python src/main.py --export-pdf
uv run python src/main.py --export-pdf --pdf-date=20260709 --pdf-output=reports/20260709.pdf
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--pdf-date` | YYYYMMDD | 当日 | 报告交易日 |
| `--pdf-output` | path | 自动 | 输出文件路径 |

### `--push-test`：推送通道测试

```bash
uv run python src/main.py --push-test --channel=wecom
uv run python src/main.py --push-test --channel=wecom --push-config=config/push.json --init
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--channel` | str | 运行时默认 | 推送通道（如 `wecom` / `dingtalk` / `email`） |
| `--push-config` | path | 运行时默认 | 推送配置文件路径 |
| `--init` | flag | off | 初始化通道配置而非发送测试消息 |

## 常见误区

| 误区 | 实际行为 |
|---|---|
| `--top 0` 期望返回空列表 | 系统会调整为 1 并打印警告 |
| 周末跑 `--auto` 期望生成周六报告 | 默认回退到最近开市日（周五） |
| `--daily-action` 期望读 `--auto` 候选池 | 直扫 `price_cache` 全市场，两套独立系统 |
| `--explain` 期望重跑评分 | 只读最近一次报告，不重跑 |
| `--conviction-ranking` 四权重和写 1.5 | 直接返回退出码 2，不执行 |
| `--weekly-report` 不传日期 | 默认本周一/五 |
| `--reconcile` 期望读 JSON | 仅接受 v1 CSV |

## 总结速查

- 日常两步：`--auto` → `--daily-action`，前者写缓存与报告，后者出次日 BUY 信号。
- 报告诊断类命令秒级返回，前提是已有当日 `auto_screening` 报告。
- 早期分发命令在 `--tickers required` 校验之前执行，因此 `--explain` / `--why-not` / `--top-picks` 不需要传 `--tickers`。
- 缓存管理脚本走 `.venv/bin/python`，不走 `uv run`，避免重复解析依赖。
