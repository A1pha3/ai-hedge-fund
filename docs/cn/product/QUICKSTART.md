# 快速开始 + CLI 命令速查表

> 本文档对应主文档 §16(CLI 速查表) + §18(快速开始), 包含新用户首次使用的完整步骤、进阶用法、Web 端访问与常用 API 端点。
>
> **主文档**: [feature-proposals.md](../feature-proposals.md) | **完整 CLI 参考**: [cli-reference.md](./cli-reference.md) | **辅助工具**: [cli-tools.md](./cli-tools.md)

---

## 一、第一次使用

```bash
# 1. 预热缓存（盘后或首次运行前）
uv run python src/main.py --preheat

# 2. 全市场自动筛选
uv run python src/main.py --auto

# 3. 解释某只票的推荐原因
uv run python src/main.py --explain 000001

# 4. 生成 PDF 报告
AUTO_EXPORT_PDF=true uv run python src/main.py --auto

# 5. 每日定时运行
# 0 17 * * 1-5 cd /path/to/project && uv run python src/main.py --auto
```

## 二、每日工作流 (推荐)

```bash
# 1. 盘前: 市场状态 + Top 3 决策卡 + 关注池健康速览
uv run python src/main.py --daily-brief

# 2. 买入: 一键获得今日最佳买点 (含市场门控 + 行业分散检查)
uv run python src/main.py --top-picks --count=5

# 3. 监控: 持仓健康检查 (HOLD / WATCH / SELL)
uv run python src/main.py --position-check --tickers=000001,300750

# 4. 学习: 策略表现周报 (哪些策略在赚钱)
uv run python src/main.py --strategy-report --lookback=7
```

## 三、完整决策链

```bash
# 10 步完整决策流 (选股→新鲜度→一致性→动量→综合评分)
uv run python src/main.py --decision-flow --top-n=10

# 综合信心评分 (6因子融合: base+动量+行业+一致性+量价+趋势共振)
uv run python src/main.py --composite-score --top-n=20

# 趋势共振检测 (5d/20d/60d 三时间框架一致性)
uv run python src/main.py --trend-resonance --top-n=20
```

## 四、进阶用法

```bash
# 自定义权重
uv run python src/main.py --custom-weights --trend=0.5 --mean-reversion=0.1 --fundamental=0.3 --event-sentiment=0.1

# 对比多只候选
uv run python src/main.py --compare 300750,600519,000001

# 查看自选池
uv run python src/main.py --watchlist-list

# 推送日报到企微
uv run python src/main.py --preheat && uv run python src/main.py --auto --export-pdf
```

## 五、Web 端访问

```bash
# 启动后端 + 前端
./app/run.sh

# 浏览器访问
open http://localhost:5173
```

## 六、常用 API 端点

- `POST /api/screening/auto` — 一键选股
- `GET /api/screening/compare?tickers=300750,600519` — 标的对比
- `GET /api/portfolio/risk-snapshot` — 风险快照
- `GET /api/portfolio/performance-report?period=weekly` — 绩效报告

---

## 五、CLI 命令速查表

### 数据获取与缓存
- `--preheat` — 缓存预热（5 任务并发）
- `--preheat --preheat-tasks=daily_basic,daily_prices` — 指定任务
- `--preheat --force` — 强制刷新
- `--preheat --list-tasks` — 查看可用任务

### 核心选股
- `--auto` — 全市场自动筛选
- `--auto --top-n=20` — Top N 推荐
- `--auto --trade-date=20260607` — 指定日期
- `--top` / `--top 20` — **快速查看最近一次 --auto 的 Top N 推荐**（无需重跑，秒级返回）— R20.2 新增
  - **R20.5 扩展**: 支持 `--top --filter` 过滤 — `--industry=电子 --min-score=0.5 --exclude-st --min-consecutive=2 --ticker=000001 --name-contains=银行`
- `--explain 000001` — 解释推荐原因（因子明细+事件线+行业排名）
- `--screen-only` — 仅 Layer A+B 评分

### 市场分析
- `--market-status` — 市场温度计
- `--industry-rotation` — 行业轮动信号
- `--factor-ic` — 因子 IC 排行
- `--macro` — 宏观经济面板

### 推荐辅助
- `--tracking-summary` — 历史推荐胜率
- `--winrate-dashboard` — 胜率看板
- `--conditional-orders` — 条件单建议
- `--compare 300750,600519,000001` — 标的对比
- `--stock-detail 300750` — 标的深度分析
- `--custom-weights --trend=0.4 --mean-reversion=0.1 --fundamental=0.3 --event-sentiment=0.2` — 自定义权重

### 组合管理
- `--rebalance` — 组合再平衡建议
- `--performance-report` — 组合绩效周报/月报
- `--attribution-daily` — 策略归因日报

### 自选池
- `--watchlist-add 000001 --name "平安银行" --tags 银行 高股息` — 添加
- `--watchlist-remove 000001` — 移除
- `--watchlist-list` — 列表
- `--watchlist-status` — 状态评分

### 报告导出与推送
- `--export-pdf` — PDF 报告导出
- `--push-test --channel=wecom` — 测试推送配置

### 单股分析
- `--ticker 000001,300750` — 单票分析
- `--pipeline` — 完整日度流水线

---

**相关章节**: [主文档](../feature-proposals.md) | [cli-reference.md](./cli-reference.md) | [cli-tools.md](./cli-tools.md) | [changelog/](../changelog/v2.1.0-v2.1.7.md)

**最后更新**: 2026-06-09 (R20.10 文档拆分)
