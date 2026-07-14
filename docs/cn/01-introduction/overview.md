---
难度: ⭐⭐
类型: 核心概念
预计时间: 12 分钟
前置知识:
  - 无
---

# 项目总览

AI Hedge Fund（A 股研究分叉）是一套面向沪深市场的每日选股研究系统。它用两条独立管线完成「全市场因子筛选」和「凸性 setup 触发」两件事——前者给出 30 天投资周期的高分候选池，后者在缓存数据上扫描次日可执行的买入信号。系统**仅用于教育与量化研究，不用于实盘交易**。

入口是 `uv run python src/main.py`，命令分发集中在 `src/cli/dispatcher.py`，凸性 setup 与仓位逻辑在 `src/screening/offensive/`。数据源为 Tushare / AkShare / Baostock，需要配置 `TUSHARE_TOKEN`。

## 两条管线的边界

| 维度 | `--auto` 全市场筛选 | `--daily-action` 凸性 setup |
|---|---|---|
| 命令 | `uv run python src/main.py --auto` | `uv run python src/main.py --daily-action` |
| 触发时机 | 收盘后约 16:00 跑全流程，耗时数分钟 | 任意时刻读缓存，约 3 秒返回 |
| 数据流向 | 拉取 → 缓存 → 报告 | 只读缓存，不重新拉数据 |
| 核心流程 | 四策略因子评分 → score_b → investability 排序 → Top 10 | 凸性 setup 扫描 → Kelly 仓位 → paper trading |
| 输出工件 | `data/reports/auto_screening_YYYYMMDD.json` | `data/paper_trading_v2/ledger.sqlite3` + 终端渲染 |
| 周期假设 | 30 天投资周期 | BTST 持有 T+10；OversoldBounce 持有 T+5 |
| 评价依据 | tracking_history 的 T+1/T+3/T+5 收益 | `data/paper_trading_backtest/journal.jsonl` |

两条管线**只共享缓存数据**，决策逻辑、仓位规则、止损策略都独立。把 `--auto` 的推荐直接当成 `--daily-action` 的买入清单是错误用法。

## 一条数据如何流过系统

以一个普通交易日为例：

1. **16:30 收盘后**：跑 `uv run python src/main.py --auto`。系统从 `data/price_cache/*.csv` 与 API 拉取行情，经过 candidate_pool 快筛、四策略评分（trend / mean_reversion / fundamental / event_sentiment）、signal_fusion 融合出 `score_b`，再用 investability 排序，写入 `data/reports/auto_screening_YYYYMMDD.json`，包含 Top 10 推荐、市场状态、layer_a_count 等。
2. **缓存刷新桥接**：`src/screening/offensive/cache_refresh.py` 把 `--auto` 当日触及的涨停票注入 `price_cache`，避免下一日 `--daily-action` 因为候选池只有「好股票」而漏掉涨停小盘股。
3. **次日 09:00 前**：跑 `uv run python src/main.py --daily-action`。扫描器在 `price_cache` 上跑两种 setup：
   - **BTST 涨停突破（T+10）**：2026 H1 回测 winrate=68%，E[r]=+8.15%，三个 regime 全部赚钱，crisis 最强（+16.93%/76%）。
   - **OversoldBounce 超跌反弹（T+5）**：默认暂停。E[r]=+0.34% 但 95% CI `[-3.15%, +3.83%]` 跨 0，无法证明它赚钱；尾部亏损占比（>10% 占 20%、>15% 占 12%）也比 BTST 厚。
4. **仓位与记账**：half-Kelly，单票硬上限 10%，组合上限 60%。当前 v2 ledger 因 canonical manifest 缺少可重算的 regime 授权证据，12% regime 例外暂停。买入信号写入 `data/paper_trading_v2/ledger.sqlite3`，止损字段 `stop_would_have_triggered` 默认只进 reasoning 字符串、不影响 realized P&L。

## 关键数据资产

| 数据源 | 位置 | 深度 | 用途 |
|---|---|---|---|
| paper_trading_backtest | `data/paper_trading_backtest/journal.jsonl` | 403 条（211 BUY + 192 EXIT），2026-01-15 → 2026-07-06 | 验证 setup 有效性的第一性原理依据 |
| portfolio_state | `data/paper_trading_backtest/portfolio_state.json` | nav=2.10，realized_pnl=+110% | 2026 H1 回测净值 |
| price_cache | `data/price_cache/*.csv` | **仅 6 个月**（2026-01-12 → 2026-07-08，约 117 行/股） | 回测/扫描数据源 |
| regime_history | `data/reports/regime_history.json` | 2020-2026，1588 天 ✅ 完整 | regime 分层评分 |
| industry_index_cache | `data/industry_index_cache/*.csv` | 2020-2026，31 个行业，1577 行 ✅ 完整 | 行业轮动信号 |

⚠ `data/paper_trading/`（运行时实例，0 笔 EXIT）与 `data/paper_trading_backtest/`（回测，192 EXIT）容易混淆。查成交数据用后者。

⚠ `price_cache` 只有 6 个月深度，导致 `scripts/setup_research.py` 直接跑会 n=0；`data/reports/setup_research/phase0_report_20260708.md` 声称的 n=1762 无法从本地复现。引用 Phase 0 结论前，先用 paper_trading_backtest 交叉验证。

## 下一步阅读

- 想了解与上游 virattt/ai-hedge-fund 的差异：[项目定位与边界](positioning.md)
- 想理解为什么默认暂停 OversoldBounce、为什么止损是摆设：[设计哲学与原则](design-philosophy.md)
- 想跑通第一次 `--auto`：[快速开始](../02-user-manual/getting-started.md)
