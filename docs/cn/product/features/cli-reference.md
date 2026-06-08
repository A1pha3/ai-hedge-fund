# 16. CLI 命令速查表

> 本节对应主文档 §16,提供完整的 CLI 命令索引。

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
  - **R20.5 扩展**: 支持 `--top --filter` 过滤 — `--industry=电子 --min-score=0.5 --exclude-st --min-consecutive=2 --ticker=000001 --name-contains=银行`
- `--explain 000001` — 解释推荐原因(因子明细+事件线+行业排名)
- `--screen-only` — 仅 Layer A+B 评分

## 市场分析
- `--market-status` — 市场温度计
- `--industry-rotation` — 行业轮动信号
- `--factor-ic` — 因子 IC 排行
- `--macro` — 宏观经济面板

## 推荐辅助
- `--tracking-summary` — 历史推荐胜率
- `--winrate-dashboard` — 胜率看板
- `--conditional-orders` — 条件单建议
- `--compare 300750,600519,000001` — 标的对比
- `--stock-detail 300750` — 标的深度分析
- `--custom-weights --trend=0.4 --mean-reversion=0.1 --fundamental=0.3 --event-sentiment=0.2` — 自定义权重

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
- `--push-test --channel=wecom` — 测试推送配置

## 单股分析
- `--ticker 000001,300750` — 单票分析
- `--pipeline` — 完整日度流水线

---

**相关章节**: [9. CLI 工具](./cli-tools.md) | [优化功能](./optimizations.md)
