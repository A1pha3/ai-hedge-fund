# AGENTS.md — AI 助手项目指令

本文件给 AI 助手（zcode / claude / codex 等）提供本项目的关键上下文。
**修改代码前必读**，尤其是数据完整性部分。

## 项目概览

A 股每日选股系统。用户每天跑两个命令获取次日买入信号：
```bash
uv run python src/main.py --auto           # 收盘后跑全流程, ~4PM 后
uv run python src/main.py --daily-action   # 读缓存, ~3 秒, 输出次日 BUY 信号
```

- **`--auto`**：四策略因子评分（trend/mean_reversion/fundamental/event_sentiment）→ score_b → investability 排序 → Top 10。存 `data/reports/auto_screening_YYYYMMDD.json`。
- **`--daily-action`**：凸性 setup（BTST 涨停突破 T+10、OversoldBounce 超跌反弹 T+5）→ Kelly 仓位 → paper trading。**与 `--auto` 是两套独立系统**，只共享缓存数据。
- 入口在 `src/cli/dispatcher.py`（命令分发），核心逻辑在 `src/screening/offensive/`。

## 数据完整性（⚠ 最重要，曾因此误判）

### 真实回测成交数据（验证 setup 有效性的**第一性原理依据**）

**位置：`data/paper_trading_backtest/`**（不是 `data/paper_trading/`！）

- `journal.jsonl`：403 条记录，含 **211 笔 BUY + 192 笔 EXIT**，覆盖 2026-01-15 → 2026-07-06。
- `portfolio_state.json`：nav=2.10，realized_pnl=+110%（2026 上半年回测结果）。
- **这是验证 setup 表现、regime 分层、止损逻辑的唯一真实数据源。**
- ⚠️ **不要和 `data/paper_trading/`（运行时实例，0 笔 EXIT）混淆**。曾因此误判系统"0 笔成交"。

### 2026 实测表现（截至 2026-07-09，源自 paper_trading_backtest）

```
BTST (n=133):           winrate=68%  E[r]=+8.15%   crisis=+16.93%/76%  risk_off=+8.87%/78%  normal=+6.29%/66%
OversoldBounce (n=59):  winrate=53%  E[r]=+0.34%   crisis=-1.15%/48%   normal=+0.15%/51%   risk_off=+13.11%/100%(n=3)
```

- **BTST 三个 regime 都赚钱**，crisis 最强 → crisis 加仓有数据支持。
- **OversoldBounce 默认暂停**，但核心理由不是"crisis 亏钱"，而是统计证据不足：
  - E[r]=+0.34% 但 95% CI `[-3.15%, +3.83%]` 跨 0（t=0.19, p≈0.85）→ **无法证明它赚钱**
  - 尾部比 BTST 更毒：亏损>10% 占比 **20%** vs BTST 11%；亏损>15% 占比 **12%** vs 6%
  - 机会成本：仓位受限时有统计显著的替代品（BTST E=+8.15%）
  - crisis n=21 的 -1.15% **样本太小，不是独立决策依据**（risk_off n=3 反而 +13.11%，与 crisis 矛盾 → 分层不可靠）
- ⚠️ 样本期仅 6 个月，可能有样本期偏差；补全历史数据重跑前，这些结论是"当前最佳依据"而非定论。
- ✅ **已验证**：59 笔回测用的是完整版 setup（volume 列存在、量比条件3 生效），不是残缺版。git 证据：volume 列在 commit `7c51cef8`(07-07) 加入，回测在 07-08 跑，setup 代码当时已有完整过滤逻辑。

### price_cache（个股价格，回测/扫描数据源）

**位置：`data/price_cache/*.csv`**（每股一个文件，6 位代码命名）

- **深度限制：只有 6 个月**（2026-01-12 → 2026-07-08，约 117 行/股）。
- 这导致 `scripts/setup_research.py` 直接跑会 **n=0**（IS/OOS 切分按 2020-2026，但价格数据只有 2026）。
- `data/reports/setup_research/phase0_report_20260708.md` 声称的 n=1762 **无法从本地数据复现**——它在别处（更深历史）生成。
- ⚠️ **引用 Phase 0 报告的结论前，先与 paper_trading_backtest 真实数据交叉验证。** 曾因盲信 Phase 0（声称 OB E=+3.42%/n=1113）对 OversoldBounce 统一加仓，但真实回测（n=59/E=+0.34%/CI 跨 0）显示无 alpha 可放大 → 有害。

### 其它历史数据（深度较全）

| 数据源 | 位置 | 深度 |
|---|---|---|
| regime_history | `data/reports/regime_history.json` | 2020-2026，1588 天 ✅ 完整 |
| industry_index_cache | `data/industry_index_cache/*.csv` | 2020-2026，31 个行业，1577 行 ✅ 完整 |
| fund_flow_cache | `data/fund_flow_cache/*.csv` | 370 文件，深度不一（部分仅 1 行）⚠️ |
| tracking_history | `data/reports/tracking_history.json` | `--auto` 推荐追踪，跨日 T+1/T+3/T+5 收益 |

## 当前选股系统状态（2026-07-09）

### 凸性 setup（`--daily-action`）

- **BTST 涨停突破（T+10）**：✅ 启用。扫描器会请求 crisis/risk_off 加仓，但 v2 ledger 当前因 canonical manifest 缺少可重算的 regime 授权证据而安全降级到 10%，并披露 `regime_authorization_evidence_unavailable`；在证据完成绑定前不实际加仓。
- **OversoldBounce 超跌反弹（T+5）**：⏸️ **默认暂停**（E[r]=+0.34% 统计不显著、CI 跨 0；尾部亏损比 BTST 厚）。
  - 控制：`DAILY_ACTION_DISABLED_SETUPS` env（默认含 `oversold_bounce`）。
  - 恢复：`DAILY_ACTION_DISABLED_SETUPS=none`（补全历史数据重跑后再决定去留）。
  - ⚠️ 暂停理由不是"crisis 亏钱"（crisis n=21 太小不可靠），而是"无法证明赚钱 + 亏起来更狠 + 仓位有更好去处"。详见上文"2026 实测表现"。
- Kelly 仓位：half-Kelly，当前 v2 ledger 单票硬上限 10%，组合上限 60%；12% regime 例外暂停，待 canonical regime evidence 可由 repository 重验后恢复。
- 止损：⚠️ **当前是摆设**——`stop_would_have_triggered` 只进 reasoning 字符串，**不影响 realized P&L**（账面按 T+N close）。192 笔回测 0 笔触发（2026 行情好）。

### 因子评分（`--auto`）

- 四策略 → score_b → composite_score → investability 排序。
- `profit_aware` 排序模式默认关闭（代码注释称 composite_score 有负预测值，但未经本环境验证）。

### 样本外验证闭环（logger → backfill → panel）

**为什么存在**：完整 setup（全过滤 + composite 强度排序）**无法在 2020–2026 重放**——历史 `fund_flow_cache`/`industry_index_cache` 太浅、强度排序依赖 composite 特征，回放不出真实候选。跨周期裸涨停信号验证显示 2026 的 68% 胜率是 **regime-favorable（顺行情）而非 cycle-robust**（2022/2024 熊年 E[r] 转负）。所以：**唯一诚实的做法是从今往后逐日累积样本外证据**，而不是盲信不可复现的 Phase 0 回测。

**数据流**（两条命令天然衔接，无需人工干预）：

```
--daily-action  →  log_setup_outputs()   →  data/reports/setup_output_log/YYYYMMDD.jsonl   （当日每票信号快照, 幂等覆盖）
--auto          →  backfill_panel()       →  data/reports/setup_output_panel.jsonl          （新 bar 到位即回填 T+1..T+10）
```

- **logger**（`setup_output_log.py`）：`--daily-action` 每跑一次，把当日所有候选（含被过滤的）连同 `plan_eligible`/`degraded`/`trigger_strength`/`entry_price`/`kelly_pct`/`regime`/`block_reason` + 扁平化 metadata（pct_change / main_net_inflow / industry_pct / pre_5d_runup_pct / limit_up_pct_threshold）写成当日 JSONL。原子覆盖 = 幂等。
- **backfill**（`join_setup_outputs_with_returns.py` 的 `backfill_panel()`）：`--auto` 末尾 best-effort 调用（`try/except`，永不拖垮 `--auto`）。只加载**已记录票**的价格序列（不是全 700+ 只），join 出 T+1/T+3/T+5/T+10 前向收益，写 panel。到期才标 `realized=True`。
- **面板按 `plan_eligible`(过全过滤) vs `filtered` 分层**：这是判断「全过滤是否真的挑出 alpha」的样本外依据。样本够大前不要据此改策略参数。
- ⚠️ **panel 是样本外累积，不是回测**：`data/paper_trading_backtest/` 才是历史回测（192 EXIT）。两者别混。刚上线时 panel 里多数 `realized=False`（前向窗口未到期）属正常。

### Daily Action readiness v2 迁移与证据链

- **唯一可信新仓证据路径**：`--auto` 刷新 Daily Action 缓存 → `DailyActionRefreshResult` 冻结结果 → readiness schema v2 manifest → `load_verified_daily_action_snapshot()` 重算 PIT 指纹 → `scan_from_verified_snapshot()` → `DailyActionService.complete_run()` → ledger 写入 `verification_status="verified"`、`snapshot_id`、`setup_consumed_fingerprint`。
- **schema v1 只读迁移行为**：旧 `schema_version=1` readiness 文件没有新仓授权；loader 必须返回 `readiness_schema_unsupported`，生命周期仍可先结算到期退出，但不得创建新计划。
- **fail closed**：空/未知策略版本、伪造或空 fingerprint、字符串布尔值、manifest / candidate / ledger provenance 不匹配，都没有新仓权限。
- **部署后必须重跑 `uv run python src/main.py --auto`**，让 schema v2 manifest 与最新缓存证据重新发布；不要用旧 v1 readiness 文件授权 `--daily-action` 新仓。
- **测试隔离规则**：readiness v2 / ledger 集成测试必须把 `data/`、`data/reports/`、ledger sqlite 都建在 `tmp_path`（或测试专用生成目录）下，禁止写工作区运行时 `data/reports`、生产 ledger、`data/paper_trading_backtest/`、历史报告或 legacy ledgers。

## 已知数据/逻辑陷阱（避坑）

1. **`data/paper_trading/` vs `data/paper_trading_backtest/`**：前者是运行时（0 EXIT），后者是回测（192 EXIT）。查成交数据用后者。
2. **price_cache 只有 6 个月**：直接跑 `setup_research.py` 会 n=0。`phase0_report` 的数字不可复现。
3. **止损默认是披露用的，不执行**：`stop_would_have_triggered` 不进 P&L。回测验证（2026-07-10，81 笔 BTST）显示**所有止损策略在当前牛市样本都会降低 E[r] 和 Sharpe**（均值回归 setup 的波动反而赚钱），故默认不执行。可用 `DAILY_ACTION_EXECUTION_STOP=atr_k2|atr_k3|fixed8` 在熊市/高波动期手动启用真实止损执行（改变 P&L 口径，启用前应跑 `scripts/backtest_exit_strategies.py` 确认当前行情有利）。
4. **`known_distributions.py` 是硬编码常量**（n=1762 等），无自动刷新，引用前需交叉验证。
5. **`--daily-action` 扫描空间 = price_cache 文件名集合**：曾因只含候选池"好股票"而漏掉涨停小盘股（已用涨停注入修复，见 `cache_refresh.py`）。
6. **BTST 涨停判定是板块自适应的**（2026-07-10 修复）：`limit_up_pct_for_ticker` 按前缀取阈值——主板 9.5%，科创/创业 19.5%，北交所 29.0%。旧固定 9.5% 会把 20% 板的非涨停大涨日误判为涨停。`execution_adjuster.is_limit_up_unbuyable_next_day` 也同步修复。
7. **BTST 资金流条件在浅数据下降级**（2026-07-10 修复）：`fund_flow_cache` 普遍浅（<5 天）时，BTST 的「资金流 >20d 均值」条件无法判定 → `degraded=True`，渲染时标 `⚠残缺`。运行时检测口径比回测分布更宽松，operator 须知晓。
8. **setup-output panel 是样本外累积、不是回测**（2026-07-15 新增）：`data/reports/setup_output_panel.jsonl` 由 `--daily-action` 逐日记录 + `--auto` 回填前向收益生成，用于验证「全过滤挑 alpha」是否成立。别和 `data/paper_trading_backtest/` 的历史回测混淆。样本够大前**不要据此改策略参数**；刚上线多数 `realized=False` 属正常。跨周期裸信号已证明 2026 胜率是顺行情、非周期稳健。
9. **完整 setup 无法在 2020–2026 重放**（2026-07-15 记录）：历史 fund_flow/industry 数据太浅 + composite 强度排序不可回放。引用「跨周期回测」结论前先确认它用的是裸信号还是全 setup；全 setup 的跨周期数字目前拿不到，只能靠 panel 前向累积。

## 关键文件速查

| 模块 | 文件 |
|---|---|
| 命令分发 | `src/cli/dispatcher.py`（`--daily-action` 在 `_resolve_daily_action`） |
| 凸性 setup 主逻辑 | `src/screening/offensive/daily_action.py`（`generate_daily_action`） |
| Setup 定义 | `src/screening/offensive/setups/btst_breakout.py`、`oversold_bounce.py` |
| Kelly 仓位 | `src/screening/offensive/kelly.py` |
| Paper tracker | `src/screening/offensive/paper_tracker.py`（成交记录、止损、drawdown） |
| 缓存刷新 | `src/screening/offensive/cache_refresh.py`（`--auto` → `--daily-action` 桥梁；已排除北交所） |
| 样本外 logger | `src/screening/offensive/setup_output_log.py`（`--daily-action` 逐日写信号快照） |
| 样本外 backfill | `scripts/join_setup_outputs_with_returns.py`（`backfill_panel()`；`--auto` 末尾回填前向收益 → panel） |
| 面板体检（只读） | `scripts/panel_health_check.py`（plan_eligible vs filtered Welch t 检验；`--auto` 末尾打印一行摘要，realized≥30/组≥5 时出结论） |
| 跨周期裸信号验证 | `scripts/validate_btst_setup_cross_cycle.py`、`scripts/validate_auto300_gate_removal.py` |
| ATR 止损工具 | `src/screening/offensive/atr_utils.py`（Wilder ATR + 止损价计算） |
| 涨停板块判定 | `src/tools/ashare_board_utils.py`（`limit_up_pct_for_ticker`：主板9.5%/科创创业19.5%/北交所29%） |
| 止损策略回测 | `scripts/backtest_exit_strategies.py`（对比 no_stop/固定/ATR 止损的 E[r]/Sharpe） |
| 回测框架 | `scripts/setup_research.py`（Phase 0，需深历史数据） |
| 因子评分 | `src/screening/`（candidate_pool / strategy_scorer / signal_fusion / investability） |

## 测试

```bash
uv run pytest tests/offensive/ -v          # 凸性 setup + paper tracker 全套
uv run pytest tests/test_main_auto_cache_refresh.py -v  # auto 缓存刷新回归
uv run pytest tests/offensive/test_daily_action_cache_refresh.py -v  # 涨停注入
```
