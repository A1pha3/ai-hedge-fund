# BTST 5D15 趋势 Gate 去重 OOS 与定向补样本方法

日期：2026-05-23

## 当前判断

这轮最值得继续跟的主线仍然是趋势延续里的 catalyst 分支，但不能直接推广到实盘或 shadow rollout。

当前最强的窄 gate 是：

```text
trend_acceleration_top_20pct
+ next_open_return <= 3%
+ candidate_source == catalyst_theme
+ close_strength < 0.90
```

补完本地能补的唯一缺口后，这条线的去重结果是：

- 去重 closed cycle：11
- 5 日内触及 15% 命中率：45.45%
- 2-5 日未来最高收益均值：20.62%
- beta 可执行率：100%
- 稳定 OOS 月份数：0

它的赔率还在，但胜率没有过 55%，样本也远不到 30 个去重 closed cycle。现在只能保留为研究候选，不能进入 rollout。

## 这次修正了什么

原来的 backfill 只检查本地源文件是否包含交易日。对 `local_snapshot_missing_future_bar` 这种缺口来说，这个检查太宽：源文件即使停在交易日当天，也会被复制过去，看起来像补数成功，但样本仍然不能闭环。

现在 backfill 对未来 bar 缺口增加了约束：

```text
如果 missing_reason == local_snapshot_missing_future_bar
本地源必须包含交易日之后至少 2 个交易 bar
```

这能避免把“写入成功”误判成“样本闭环成功”。

## 定向补样本流程

下一轮继续沿这条线走时，用下面顺序，不扩大全市场暴搜：

1. 先跑 pre-execution 缺口清单

```bash
python scripts/analyze_btst_5d_15pct_trend_gate_missing_price_manifest.py \
  --report-name-contains "" \
  --gate-id catalyst_theme_close_strength_lt_0_90 \
  --top-fraction 0.20
```

这个清单不使用 `next_open_return <= 3%` 过滤缺价格样本，因为缺价格时还不知道是否可执行。它先用因子条件锁定候选，再列出缺本地价格的唯一 `ticker + trade_date`。

2. 再用本地源补价格

```bash
python scripts/backfill_btst_5d_15pct_scoped_price_snapshots.py \
  --manifest data/reports/btst_5d_15pct_trend_gate_missing_price_manifest_latest.json \
  --priority-bucket p0_gate_missing_ticker_snapshot_root \
  --priority-bucket p1_gate_missing_future_bar \
  --local-only \
  --execute \
  --force
```

3. 最后跑去重 OOS

```bash
python scripts/analyze_btst_5d_15pct_trend_gate_oos_validation.py \
  --local-price-only \
  --report-name-contains "" \
  --gate-id catalyst_theme_close_strength_lt_0_90 \
  --top-fraction 0.20 \
  --min-closed-cycle-count 30
```

## 受控扩展结果

为了补到 30 个去重 closed cycle，测试了几种只沿 catalyst 主线扩展的方案：

| gate | top_fraction | 去重 closed | 命中率 | 均值最高收益 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| close_strength < 0.90 | 20% | 11 | 45.45% | 20.62% | 保留研究，不 rollout |
| close_strength < 0.92 | 20% | 23 | 21.74% | 12.47% | 放宽后明显稀释 |
| close_strength < 0.95 | 20% | 54 | 25.93% | 11.87% | 样本够了，但质量不够 |
| close_strength < 0.90 | 30% | 14 | 35.71% | 16.38% | top30 稀释 |
| close_strength < 0.92 | 30% | 27 | 22.22% | 11.40% | 不值得继续 |
| close_strength < 0.88 | 20% | 0 | 无 | 无 | 太窄，无闭环样本 |
| close_strength < 0.88 | 30% | 1 | 0% | -2.23% | 太窄且表现差 |

结论很直接：不能靠放宽 close_strength 阈值凑样本。`0.90` 附近是当前收益质量还能保住的边界，往上放会把胜率拉回普通 catalyst 水平。

## 下一步

继续收集新交易日里的同类候选，而不是回头扩大历史搜索范围。

执行标准：

- 每新增一批报告，先更新 pre-execution manifest。
- 本地能补的价格先补齐。
- 去重 closed cycle 达到 30 前，只看研究状态。
- 达到 30 后，重新检查：
  - 去重命中率是否达到 55%
  - 均值最高收益是否达到 15%
  - 至少 2 个 OOS 月份是否通过同样阈值

这条线如果最终失败，也不是坏结果。它已经说明 catalyst 里的“低过热 close_strength”有赔率，但当前证据不足以证明高胜率；下一轮要找的是更强的确认条件，而不是把阈值放宽。
