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

---

**相关章节**: [9. CLI 工具](./cli-tools.md) | [优化功能](./optimizations.md)
