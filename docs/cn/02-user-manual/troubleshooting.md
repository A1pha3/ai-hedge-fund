---
难度: ⭐
类型: 入门教程
预计时间: 20 分钟
前置知识:
  - 已按 [安装指南](./installation.md) 配置环境
  - 跑过至少一次 [每日工作流](./daily-workflow.md)
---

# 故障排除

本文档按「症状 → 原因 → 解决」结构组织，覆盖 A 股每日选股系统的常见故障。先按诊断决策树定位问题层级，再查症状速查表找具体解法。

## 学习目标

读完本文档后，你能：

- 用 5 步诊断树把故障定位到数据 / 缓存 / 配置 / 模型 / 逻辑某一层
- 识别 8 类高频错误信息并按给定步骤恢复
- 区分「运行时停滞」与「设计性降级」（如 `⚠残缺`、`regime_authorization_evidence_unavailable`）
- 知道何时该清缓存、何时该改环境变量、何时该跑回测验证

## 诊断决策树

遇到异常时按下列顺序判断，命中即停：

```text
1. 命令是否报错退出？
   ├─ 是 → 跳到「症状 A：命令报错」
   └─ 否 → 继续
2. 输出是否为空或 n=0？
   ├─ 是 → 跳到「症状 B：输出为空」
   └─ 否 → 继续
3. 输出是否带 ⚠ 标记或 unavailable / blocked 字样？
   ├─ 是 → 跳到「症状 C：带降级标记」
   └─ 否 → 继续
4. P&L 或胜率与预期不符？
   ├─ 是 → 跳到「症状 D：P&L 异常」
   └─ 否 → 继续
5. 数据日期是否落后？
   ├─ 是 → 跳到「症状 E：数据滞后」
   └─ 否 → 查「症状速查表」逐项核对
```

## 检查清单

按命令分组列出，逐条勾选确认环境正常：

- `--auto`
  - [ ] `.env` 中 `TUSHARE_TOKEN` 已设置且未过期
  - [ ] `.env` 中默认 LLM 模型变量已显式设置（不依赖回退）
  - [ ] 系统时间在收盘后 17:00 之后（或显式传 `--trade-date`）
  - [ ] `data/price_cache/` 目录可写
- `--daily-action`
  - [ ] `data/price_cache/*.csv` 至少有一只票的最新交易日数据
  - [ ] `data/reports/regime_history.json` 存在且包含目标交易日
  - [ ] 未设置 `DAILY_ACTION_DISABLED_SETUPS=btst_breakout`
- 回测类
  - [ ] `data/paper_trading_backtest/journal.jsonl` 存在（不是 `data/paper_trading/`）
  - [ ] `data/price_cache/` 有 6 个月以上深度（否则 `setup_research.py` 会 n=0）

## 症状 A：命令报错退出

### A1 `--auto` 报 `LLM model not configured`

**原因**：系统不再回退到 `MINIMAX_MODEL` 等变量，未显式设置默认模型会直接失败而非静默降级。

**解决**：

```bash
uv run python src/main.py --show-default-model
```

若输出为空或报错，编辑 `.env` 显式设置默认 Provider 与模型变量（具体变量名查 `.env.example`），再重跑 `--show-default-model` 确认解析成功。

### A2 `--top` / `--explain` / `--why-not` 报 `No auto_screening report found`

**原因**：这些命令读取最近一次 `--auto` 报告，未跑过 `--auto` 或报告目录被清空。

**解决**：

```bash
ls data/reports/auto_screening_*.json
uv run python src/main.py --auto
```

### A3 `--conviction-ranking` 返回退出码 2

**原因**：四权重和不在 1.0 ± 0.01 区间。

**解决**：调整 `--score-weight` / `--consecutive-weight` / `--quality-weight` / `--calibration-weight`，使其和为 1.0。

### A4 `--reconcile` 报 `Usage: --reconcile <trade_log.csv>`

**原因**：未传 CSV 路径，或路径不存在。仅接受 v1 CSV 格式 `ticker,buy_date,buy_price,sell_date,sell_price`。

**解决**：检查路径是否存在；CSV 表头必须包含上述 5 列。

## 症状 B：输出为空或 n=0

### B1 `scripts/setup_research.py` 跑出来 n=0

**原因**：`data/price_cache/` 只有 6 个月深度（2026-01-12 → 2026-07-08，约 117 行/股），但 IS/OOS 切分按 2020-2026 划分，导致落空。`phase0_report_20260708.md` 声称的 n=1762 在本地数据上无法复现——它在更深历史数据下生成。

**解决**：补全 2020-2026 的历史价格数据后再跑；补全前不要盲信 Phase 0 结论。先用 `paper_trading_backtest` 真实数据交叉验证。

### B2 `--daily-action` 输出空（无候选）

**原因**：可能是市场当日无 setup 命中（正常），也可能是 verified snapshot 缺失导致 `new_entries_blocked`。

**解决**：

1. 查输出末尾是否有 `new_entries_blocked: verified snapshot unavailable`。
2. 若有，运行 readiness 流水线恢复 verified snapshot。
3. 若无，查 `data/price_cache/` 最新交易日是否为目标信号日：
   ```bash
   uv run python src/main.py --check-freshness --trade-date=20260709
   ```

### B3 `--expected-returns` 报 `No recommendations found`

**原因**：最新 `auto_screening` 报告的 `recommendations` 字段为空。

**解决**：先跑 `--auto`，确认报告里 `recommendations` 非空。

## 症状 C：带降级标记

### C1 daily-action 输出 `⚠残缺`

**原因**：`fund_flow_cache` 普遍浅（< 5 天），BTST 的「资金流 > 20d 均值」条件无法判定，`degraded=True`。运行时检测口径比回测分布更宽松。

**解决**：该信号未通过完整过滤，operator 须人工复核资金流；或先 backfill 资金流数据再重跑。不要按完整 BTST 信号同等信任。

### C2 daily-action 输出 `regime_authorization_evidence_unavailable`

**原因**：v2 ledger 的 canonical manifest 缺少可重算的 regime 授权证据，安全降级到 10%，不实际加仓。

**解决**：在证据完成绑定前，所有候选仓位均为基础值。这是设计性安全降级，不需要立即修复；若需要恢复 12% regime 例外，按 `LedgerRepository` 文档补全 canonical regime evidence。

### C3 daily-action 输出 `new_entries_blocked`

**原因**：verified PIT snapshot 缺失或不健康，新仓规划被阻断，但持仓生命周期（到期结算 / EXIT / MTM）仍照常推进。

**解决**：运行 readiness 流水线恢复 verified snapshot：

```bash
uv run python src/main.py --flywheel-health
```

检查 `tracking_history` 是否仍在累积，再按 readiness 文档补全 snapshot。

## 症状 D：P&L 异常

### D1 回测胜率与 phase0_report 不符

**原因**：`phase0_report` 用更深历史数据生成（n=1762），本地 `price_cache` 只有 6 个月，两套样本不可比。

**解决**：以 `data/paper_trading_backtest/journal.jsonl` 的真实回测（211 笔 BUY + 192 笔 EXIT）为第一性依据，不要盲信 Phase 0 的数字。

### D2 止损字段显示触发但 P&L 不变

**原因**：当前版本 `stop_would_have_triggered` 只进 reasoning 字符串，不影响 realized P&L（账面按 T+N close）。回测验证所有止损策略在当前牛市样本都会降低 E[r] 和 Sharpe。

**解决**：这是设计行为，不是 bug。若需启用真实止损执行：

```bash
uv run python scripts/backtest_exit_strategies.py  # 先确认当前行情有利
DAILY_ACTION_EXECUTION_STOP=atr_k2 uv run python src/main.py --daily-action
```

### D3 误用 `data/paper_trading/` 查成交数据

**原因**：`data/paper_trading/` 是运行时实例（0 笔 EXIT），`data/paper_trading_backtest/` 才是回测（192 EXIT）。

**解决**：查成交数据始终用 `data/paper_trading_backtest/journal.jsonl` 与 `portfolio_state.json`（nav=2.10，realized_pnl=+110%）。

## 症状 E：数据滞后

### E1 `--daily-action` 提示 `price_cache 最新交易日落后于最新 --auto 报告交易日`

**原因**：stale guard 检测到 `--auto` 报告的交易日比 `price_cache` 最新交易日新，为避免使用过期信号，本次不输出新 BUY。

**解决**：先跑 `--auto` 刷新 `price_cache`，再跑 `--daily-action`。

### E2 `--check-freshness` 报数据未对齐

**原因**：某个数据源（`price_cache` / `fund_flow_cache` / `industry_index_cache`）未刷新到目标交易日。

**解决**：

```bash
uv run python src/main.py --preheat --force
uv run python src/main.py --auto
```

`fund_flow_cache` 部分文件深度仅 1 行属正常现象（部分票刚入池），不影响主流程。

### E3 周末跑命令生成周六报告

**原因**：默认规则下，`--auto` 与 `--daily-action` 都不会生成周六、周日这种伪交易日，会先应用 17:00 数据就绪规则，再回退到最近开市日。

**解决**：周日运行会落到上周五数据；周一 17:00 前仍用上周五；周一 17:00 后切到周一。这是预期行为，不需要修复。

## 症状速查表

| 症状 | 可能原因 | 验证步骤 |
|---|---|---|
| BTST 误把 20% 板非涨停大涨日判为涨停 | 旧固定 9.5% 阈值 | 确认 `src/tools/ashare_board_utils.py` 的 `limit_up_pct_for_ticker` 已按板块取阈值（主板 9.5% / 科创创业 19.5% / 北交所 29.0%） |
| tushare batch_size>10 时 sub-factor 跳过 | batch 接口截断到 50-76 行（< 126 阈值） | 把 batch_size 降到 ≤ 10，或改用单票查询 |
| tushare 返回 `vol` 字段评分器报错 | 评分器期望 `volume` | 在 `tushare_api.py` 的 `pro.daily()` 调用后 rename `vol` → `volume` |
| `--top 0` 系统异常 | 系统会自动调整为 1 并打印警告 | 传 `--top 1` 或更大值 |
| `--preheat` 部分任务失败 | 单个数据源故障 | `--list-tasks` 查可用任务，单独跑失败任务 |
| `--watchlist-add` 报标签无效 | 标签空格分隔但未引号 | `--tags "银行 高股息"` 或 `--tags 银行 高股息` 均可，注意 shell 解析 |

## 常见问题

**Q：`--auto` 跑了 10 分钟还没结束，正常吗？**

A：正常。全市场筛选需要拉取并评分数千只票，耗时数分钟。若超过 30 分钟，查网络是否被 tushare 限流。

**Q：daily-action 输出的 `position_pct` 和我手工算的 half-Kelly 不一致？**

A：`position_pct` 受四重约束：half-Kelly × regime 因子 × 回撤因子 × trigger_strength 调节，再受单票硬上限 10% 和组合上限 60% 截断。当前 regime 加仓暂停，所有仓位为基础值。

**Q：可以同时跑 `--auto` 和 `--daily-action` 吗？**

A：可以但无意义。`--daily-action` 直扫 `price_cache`，不依赖 `--auto` 候选池。建议先 `--auto` 刷缓存，再 `--daily-action`。

**Q：清缓存会丢历史回测数据吗？**

A：`scripts/manage_data_cache.py clear --yes` 只清运行时缓存，不影响 `data/paper_trading_backtest/` 的回测 journal。但仍建议清前先备份。

## 下一步

- 读懂输出字段后看 [输出报告解读](./interpreting-reports.md) 了解字段细节
- 命令完整用法查 [CLI 完整参考](./cli-reference.md)
- 术语含义查 [术语表](./glossary.md)
- 系统设计原理查 [系统架构总览](../03-architecture/overview.md)
