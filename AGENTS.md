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
- ⚠️ **journal 的 recorded P&L 存在锚定 bug（2026-07-18 对抗性审查定位，三方独立复现）**：生成它的回测以 `price_loader=None` 调用 `close_matured`（`scripts/backtest_paper_loop.py:134`），`fetch_actual_returns` 把每票收益锚到**本批次最早 buy_date** 而非本仓位 buy_date；且入场口径是 **T0 收盘**（不是文档声称的 T+1 开盘）、零成本。可复核 139 笔中 **42% 偏差 >0.5pp，最大 ±31.6pp**（300033 两笔不同仓位同记 -26.74%，精确复现锚定窗口）。**下表引述值因此系统性虚高**，修正后见"2026 实测表现"。另：**53/192 笔（28%）的 ticker 缓存文件已被删除，永久不可复核**——回测产物必须连同输入数据快照归档。

### 2026 实测表现（截至 2026-07-09，源自 paper_trading_backtest；2026-07-18 全量修正）

journal recorded 原值（旧引述，锚定 bug 污染）→ **全量修正值**（192/192 全部可复核，own-anchor 本仓位 T0 收盘、零成本、pct_change 链除权免疫；32 只缺失票已从 tushare 回填）：

```
BTST (n=133):  recorded +8.15%/68%  →  corrected +5.07%/60%
  crisis (21):   +16.93%/76%       →  +10.44%/67%   (仍最强)
  risk_off (9):  +8.87%/78%        →  +1.97%/56%    (优势基本消失, n=9 本就不可靠)
  normal (103):  +6.29%/66%        →  +4.24%/59%
OB (n=59):     recorded +0.34%/52%  →  corrected -0.13%/44%  (无 alpha 确认)
```

- **方向结论不变**（BTST 三 regime 都为正、crisis 最强；OB 统计不显著），但 **E[r] 系统性高估 3.1pp、胜率高估 8pp**。可执行口径（T+1 开盘 + 双边 30bps）只会更低。修正产物：`outputs/journal_corrected_stats_20260718.json`；journal 原文件未改动（锚定 bug 机制见上条警示）。
- **BTST 三个 regime 都赚钱**，crisis 最强 → crisis 加仓有数据支持（但 risk_off 的 1.1× 依据已基本消失，regime 证据绑定恢复时需重估系数）。

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

- **深度已补齐**（2026-07-17 实测）：823 票，中位 1579 行，2020-01-02 → 2026-07-17。（07-08 时曾只有 6 个月 ~117 行/股，之后做过历史回填。）
- `scripts/setup_research.py` 直接跑仍会 **n≈0**：完整 setup 需要资金流条件，而 `fund_flow_cache` 历史仍浅（见下表）——价格深度不再是瓶颈，资金流才是。
- `data/reports/setup_research/phase0_report_20260708.md` 声称的 n=1762 **无法从本地数据复现**——它在别处（更深资金流历史）生成。
- ⚠️ **引用 Phase 0 报告的结论前，先与 paper_trading_backtest 真实数据交叉验证。** 曾因盲信 Phase 0（声称 OB E=+3.42%/n=1113）对 OversoldBounce 统一加仓，但真实回测（n=59/E=+0.34%/CI 跨 0）显示无 alpha 可放大 → 有害。

### 其它历史数据（深度较全）

| 数据源 | 位置 | 深度 |
|---|---|---|
| regime_history | `data/reports/regime_history.json` | 2020-2026，`--auto` 每日追加当日 regime（2026-07-18 起有生产写入者）；此前停在 20260707，legacy 路径静默退化 normal |
| industry_index_cache | `data/industry_index_cache/*.csv` | 2020-2026，31 个行业，1577 行 ✅ 完整 |
| fund_flow_cache | `data/fund_flow_cache/*.csv` | 370 文件，深度不一（部分仅 1 行）⚠️ |
| tracking_history | `data/reports/tracking_history.json` | `--auto` 推荐追踪，跨日 T+1/T+3/T+5 收益 |

## 当前选股系统状态（2026-07-09）

### 凸性 setup（`--daily-action`）

- **BTST 涨停突破（T+10）**：✅ 启用。扫描器会请求 crisis/risk_off 加仓，但 v2 ledger 当前因 canonical manifest 缺少可重算的 regime 授权证据而安全降级到 10%，并披露 `regime_authorization_evidence_unavailable`；在证据完成绑定前不实际加仓。（2026-07-18 修复：旧实现仅在 strength=1.0 时被 clamp 拦住，strength<1 时 regime 加仓实际泄漏 +0.5~2pp/票且 provenance 谎报 normal——现 v2 扫描在证据绑定前 regime_factor 恒 1.0，候选仍带 authorization 标记用于披露。）
- **OversoldBounce 超跌反弹（T+5）**：⏸️ **默认暂停**（E[r]=+0.34% 统计不显著、CI 跨 0；尾部亏损比 BTST 厚）。
  - 控制：`DAILY_ACTION_DISABLED_SETUPS` env（默认含 `oversold_bounce`）。
  - 恢复：`DAILY_ACTION_DISABLED_SETUPS=none`（补全历史数据重跑后再决定去留）。
  - ⚠️ 暂停理由不是"crisis 亏钱"（crisis n=21 太小不可靠），而是"无法证明赚钱 + 亏起来更狠 + 仓位有更好去处"。详见上文"2026 实测表现"。
- Kelly 仓位：half-Kelly，当前 v2 ledger 单票硬上限 10%，组合上限 60%；12% regime 例外暂停，待 canonical regime evidence 可由 repository 重验后恢复。
- **Drawdown 熔断 + 行业集中度（2026-07-18 恢复，v2 迁移时曾丢失）**：组合回撤 ≤-20% 停止一切新仓、≤-15% 新仓权重减半（与 legacy `drawdown_action` 对齐）；同一入场日同行业新仓 ≤2（含当日已预留，依据：集中日 E[r] +6.3% vs 分散日 +9.7%）。
- **执行成本口径 v2.1**（2026-07-18）：v2 ledger 执行成本从零成本改为 30bps/边滑点 + 5bps 卖出印花税，与 Kelly 先验（`adjust_returns` 30bps/边）对齐；此前零成本使实盘 P&L 系统性优于证据 ~0.6pp/笔，污染 edge 衰减监测。成本版本不匹配的计划按 `cost_version_mismatch` skip（不再 raise 崩溃死锁）。
- **运行护栏**（2026-07-18）：`--end-date` 不得晚于 17:00 规则的自然信号日（未来日会永久杀掉排队计划并写入未来估值）；入场日 09:30 后不再创建当日入场计划（`entry_window_missed`，防止按不可执行的开盘价记账）；交易日历前向覆盖 <30 天时保留旧文件（防止年末日历截断静默失效）；drawdown 熔断/日历不可用/窗口阻断在默认渲染可见（不再伪装成"今日无信号"），并输出台账净值/回撤行。
- **panel 样本外闭环**（2026-07-18）：v2 scan 对象已补齐 logger 字段（trigger_strength/entry_price/metadata/kelly_pct 别名），`candidate_not_plan_eligible`（未触发的契约拒票）不再写入 panel 对照组（防止对照总体被宇宙噪声稀释成假 ✅）；`_forward_return` 已除权免疫（T+1 日内腿同日价 + 后续 pct_change 链）。
- 止损：⚠️ **当前是披露用的，不执行**——`stop_would_have_triggered` 只进 reasoning 字符串，**不影响 realized P&L**（账面按 T+N close）。⚠️ 旧述"192 笔回测 0 笔触发（2026 行情好）"**因果错误**（2026-07-18 审查定位）：生成该 journal 的回测传了 `price_loader=None`，止损检测根本没运行（0 触发是默认值不是检测结果）；独立重算持有期 raw low ≤ -8% 硬止损 **43% 会触发**。"止损不执行不伤 P&L"的有效证据是 `scripts/backtest_exit_strategies.py` 的独立止损回测（2026-07-10，81 笔 BTST：所有止损策略在当前牛市样本都降低 E[r] 和 Sharpe），不是 journal 的 0 触发。可用 `DAILY_ACTION_EXECUTION_STOP=atr_k2|atr_k3|fixed8` 在熊市/高波动期手动启用真实止损执行（改变 P&L 口径，启用前应跑 `scripts/backtest_exit_strategies.py` 确认当前行情有利）。

### 因子评分（`--auto`）

- 四策略 → score_b → composite_score → investability 排序（`profit_aware` 默认开启，`INVESTABILITY_PROFIT_AWARE=false` 回退；主键 empirical bucket 胜率，composite 末位 tie-break；bucket 证据缺失的票按 0.5 胜率/0.0 期望中性处理，不再 -inf 垫底）。
- ⚠️ **profit_aware 校准池曾 89/89 天为空**（2026-07-18 定位修复）：严格模式的 git-sha 等值过滤（历史中 27 个版本，上一 commit 的证据次日即失效）+ 98.3% 记录缺 `return_tN_date` 被 pop，导致排序实际从未脱离 composite。修复：model_version 仅作 provenance 不过滤；未标注日期的成熟 label 用交易日历推断 `realized_on`（recommended+N 个交易日）。**切换前的"profit_aware 已开启"结论需重验**——它自开启起一天都没真正生效过。
- **评分链已回溯复权**（2026-07-18）：`load_price_frame` 用 pct_change 链把 OHLC 复权到最新行口径（末行=原始价），此前 EMA/RSI/动量/布林带/ATR 从 raw close 重算，除权缺口被读成崩盘幻影（001388 型 raw -26.8% 实际 +10%；~19% 的票近 126 行内有缺口）。**修复前生成的 composite/score_b 与全部因子 IC/校准证据是在幻影污染的信号上量的，重跑前不可直接对比。**
- **因子数学修正**（2026-07-18）：① growth 趋势符号反转修复（newest-first 序列倒序回归，此前 50.8% 的票加速/减速判反）；② ADX 改 Wilder RMA（与 RSI 同平滑，此前 ewm(span) 系统性偏高、31.5% 趋势门翻转）；③ growth 钳位 score=0 区分负增长/零增长（raw_score 保留原值，此前 27.4% 零增长票被满置信看空）；④ 动量三窗改对数收益求和（消除高波动票动量高估的横截面偏差）。
- 排序证据（双确认）：composite/score_b 主键在真实 Top10 切片显著反向 — c272（47% vs 60%）+ 2026-07-18 独立复核（T+5 IC=-0.112 t=-2.49，top-3 45% vs 反选 58%）。全池 300 票日 IC 为正——顶部非单调反转。tracking 回填改用 price_cache pct_change 链（43 条幻影记录已迁移重算）。

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

### --auto 缓存刷新性能（2026-07-17 优化，~408s → ~21s）

`refresh_daily_action_caches` 的耗时曾是 --auto 大头（本地 O(全历史) 重处理，不是网络）。优化点：

- **价格幂等跳写**：当日行已存在且值未变 → 跳过全量校验 + 原子重写（证据照采，指纹不变），计数 `price_skipped_current`；原每轮 ~90s 空转写盘消除。
- **日期处理向量化**：`_fund_flow_dates`/`_price_dates` 纯字符串整列操作，替代逐值 `pd.to_datetime`（800 票 × 中位 1579 行 × 多趟）。
- **PIT 指纹快路**（`pit_evidence.py`）：`to_dict(records)` → `itertuples` 行迭代 + 零填充 ISO 日期快速路径；`_normalize_daily_batch` 与 `_daily_batch_evidence_fingerprint` 改用 `canonical_price_row_fingerprint`（免每行 DataFrame 构造）。**逐位等价已验证**：优化前后对全部真实缓存（6042 个指纹，含 daily_batch manifest 指纹）逐位一致。
- **资金流批量预取**（`DAILY_ACTION_FUND_FLOW_BATCH`，默认开）：stale 票用 `fetch_batch_fund_flow_tushare(trade_date)` 单次 API 全市场拉取替代逐票串行（~1.3s/票），命中票免网络与 rate-limit；close/pct_change 从当日 daily batch 填，main_net_pct 留 NaN（见陷阱 11）。冷缓存实测 68 票 30.6s → 6.4s；首日 ~500 票场景从 >10min 量级降到秒级。批量失败/未覆盖自动回落逐票路径。
- 复测入口：`/tmp/refresh_probe2.py`（分段计时探针，一次性诊断脚本，不入库）。

### Daily Action readiness v2 迁移与证据链

- **唯一可信新仓证据路径**：`--auto` 刷新 Daily Action 缓存 → `DailyActionRefreshResult` 冻结结果 → readiness schema v2 manifest → `load_verified_daily_action_snapshot()` 重算 PIT 指纹 → `scan_from_verified_snapshot()` → `DailyActionService.complete_run()` → ledger 写入 `verification_status="verified"`、`snapshot_id`、`setup_consumed_fingerprint`。
- **schema v1 只读迁移行为**：旧 `schema_version=1` readiness 文件没有新仓授权；loader 必须返回 `readiness_schema_unsupported`，生命周期仍可先结算到期退出，但不得创建新计划。
- **fail closed**：空/未知策略版本、伪造或空 fingerprint、字符串布尔值、manifest / candidate / ledger provenance 不匹配，都没有新仓权限。
- **部署后必须重跑 `uv run python src/main.py --auto`**，让 schema v2 manifest 与最新缓存证据重新发布；不要用旧 v1 readiness 文件授权 `--daily-action` 新仓。
- **证据捕获自愈**（2026-07-17 修复）：`end_daily_readiness_reference_capture` 在捕获窗内自行补齐缺失的 stock_basic/SW 观测，不再依赖候选池构建的副作用——此前候选池当日缓存命中时两个 fetcher 不会被调用，同日重复跑 `--auto` 必然发布失败（`typed dated reference snapshot is required`）。数据源失败仍按原样 fail closed。
- **宇宙退市过滤**（2026-07-17 修复）：`resolve_daily_action_refresh_tickers` 用 stock_basic(L) 自动剔除退市/非上市标的（数据源不可用或宇宙 <3000 只时 fail-open 不过滤，由 readiness 严格校验兜底）。此前一只退市票（002808）就会让 security/SW 精确覆盖校验把全宇宙清单整体阻断。
- **停牌证据宇宙投影**（2026-07-17 修复）：tushare 停牌列表是全市场的，而 v2 清单要求停牌证据 ⊆ 宇宙；`refresh_daily_action_caches` 在冻结结果前把停牌证据投影到宇宙内（source_fingerprint 按投影后行重导，保持自校验）。不投影时清单一律 fail-closed（`suspension evidence contains ticker outside universe`）。
- **测试隔离规则**：readiness v2 / ledger 集成测试必须把 `data/`、`data/reports/`、ledger sqlite 都建在 `tmp_path`（或测试专用生成目录）下，禁止写工作区运行时 `data/reports`、生产 ledger、`data/paper_trading_backtest/`、历史报告或 legacy ledgers。`tests/offensive/conftest.py` 的 autouse fixture 会把退市过滤的默认 loader 置为 fail-open，测试过滤器时显式传 `listed_universe_loader=`。

## 已知数据/逻辑陷阱（避坑）

1. **`data/paper_trading/` vs `data/paper_trading_backtest/`**：前者是运行时（0 EXIT），后者是回测（192 EXIT）。查成交数据用后者。
2. **price_cache 深度已补齐（2026-07-17 实测：823 票中位 1579 行，2020→2026）**，但 `setup_research.py` 仍 n≈0——瓶颈是 `fund_flow_cache` 历史浅（完整 setup 的资金流条件满足不了）。`phase0_report` 的数字仍不可复现。
3. **止损默认是披露用的，不执行**：`stop_would_have_triggered` 不进 P&L。回测验证（2026-07-10，81 笔 BTST）显示**所有止损策略在当前牛市样本都会降低 E[r] 和 Sharpe**（均值回归 setup 的波动反而赚钱），故默认不执行。可用 `DAILY_ACTION_EXECUTION_STOP=atr_k2|atr_k3|fixed8` 在熊市/高波动期手动启用真实止损执行（改变 P&L 口径，启用前应跑 `scripts/backtest_exit_strategies.py` 确认当前行情有利）。
4. **`known_distributions.py` 是硬编码常量**（n=1762 等），无自动刷新，引用前需交叉验证。
5. **`--daily-action` 扫描空间 = price_cache 文件名集合**：曾因只含候选池"好股票"而漏掉涨停小盘股（已用涨停注入修复，见 `cache_refresh.py`）。
6. **BTST 涨停判定是板块自适应的**（2026-07-10 修复）：`limit_up_pct_for_ticker` 按前缀取阈值——主板 9.5%，科创/创业 19.5%，北交所 29.0%。旧固定 9.5% 会把 20% 板的非涨停大涨日误判为涨停。`execution_adjuster.is_limit_up_unbuyable_next_day` 也同步修复。
7. **BTST 资金流条件在浅数据下降级**（2026-07-10 修复）：`fund_flow_cache` 普遍浅（<5 天）时，BTST 的「资金流 >20d 均值」条件无法判定 → `degraded=True`，渲染时标 `⚠残缺`。运行时检测口径比回测分布更宽松，operator 须知晓。
8. **setup-output panel 是样本外累积、不是回测**（2026-07-15 新增）：`data/reports/setup_output_panel.jsonl` 由 `--daily-action` 逐日记录 + `--auto` 回填前向收益生成，用于验证「全过滤挑 alpha」是否成立。别和 `data/paper_trading_backtest/` 的历史回测混淆。样本够大前**不要据此改策略参数**；刚上线多数 `realized=False` 属正常。跨周期裸信号已证明 2026 胜率是顺行情、非周期稳健。
9. **完整 setup 无法在 2020–2026 重放**（2026-07-15 记录）：历史 fund_flow/industry 数据太浅 + composite 强度排序不可回放。引用「跨周期回测」结论前先确认它用的是裸信号还是全 setup；全 setup 的跨周期数字目前拿不到，只能靠 panel 前向累积。
10. **东财 push2his 会按源 IP 行为封禁，ProxyError 有误导性**（2026-07-17 定位）：`--auto` 每日对 `push2his.eastmoney.com` 逐票数百次 fflow 请求（含 enrich 补全），东财 WAF 对本机 IP 的 `/api/qt/*` 100% 断连（TLS 正常、请求发出后 empty reply；根路径 404、push2 实时 API 200 → 定点封 API 路径，非网络故障）。报错显示 ProxyError 是因为 requests 走系统代理（Clash），**根因不在代理**。已加熔断器（`src/tools/akshare_fund_flow.py`：连续 5 次网络错误熔断 15 分钟、半开自动复位；enrich 路径同步跳过），熔断期 akshare 源由 tushare/ftshare 兜底。注意：`push2` 的 `fflow/kline/get` 只有当日实时数据，**不能**替代历史接口；分片主机 `N.push2his.*` 同被封。封禁期 ftshare 缺的日子 `close`/`main_net_pct` 补不上属预期代价，解封后（通常数小时~几天）自动恢复。
11. **东财 `main_net_pct` 口径 ≠ 主力净流入/成交额**（2026-07-17 实测）：000504 2026-07-16 tushare 推导 -13.76%（net_mf/成交额，成交额与 daily amount 吻合）vs 东财缓存 -2.83%（分母疑为流通市值）。且 2026-07-16 批次东财行 pct 与 main_net_inflow **符号大量不一致**（如 000014 inflow=-2164万 却 pct=+26.45），该列数据质量存疑。**下游 setup（BTST/OB）只消费 `main_net_inflow` 金额，不消费 pct**，影响为零；但任何新逻辑引用 pct 前必须重新核对口径。资金流批量预取路径因此 pct 留 NaN（落盘补 0.0，同逐票 tushare 惯例）。
12. **缓存目录不能放在 symlink 路径下**（2026-07-17 实测）：`atomic_write_csv` 的 `_open_parent` 用 `O_NOFOLLOW` 逐层打开目录组件，macOS 的 `/var`、`/tmp`（→ `/private/*`）会报 `[Errno 20] Not a directory: 'var'`。`tempfile.TemporaryDirectory()` 创建的目录就在其下——测试/bench 里构造缓存目录要用项目内路径或 pytest `tmp_path`（本仓库 basetemp 在工作区内）。生产 `data/` 用相对路径不受影响。
13. **readiness v2 精确覆盖 vs 现实数据滞后**（2026-07-17 记录）：v2 要求宇宙内每票都有 stock_basic(L) + 申万行业成员证据，缺一票全局 fail-closed。退市票由宇宙构建时的 stock_basic(L) 过滤解决（见"宇宙退市过滤"）；残留风险是**新上市/次新股尚未纳入申万行业指数**（stock_basic 有、SW 成员没有）——若此类票经涨停注入进入宇宙，SW 覆盖校验仍会阻断当日清单。出现时把该票加入 `EXTRA_EXCLUDED_TICKERS` 临时屏蔽，或等申万收录后自愈。
14. **质量门常量必须与管线设计对齐**（2026-07-18 定位）：`quality_decision` 曾长期 degraded，三根同类的"门与设计矛盾"：① `price_history` 的 eligible 误用全池 300，而技术阶段按设计只消费流动性前 75%（225）→ 现由 scorer 用 `note_eligible_tickers` 显式声明设计消费集；② 生产端"成功观测 0 行"（合法空）不落盘空快照，消费端误报 UNAVAILABLE → `load_event_inputs` 现依据生产端逐源证据把合法空提升回 SUCCESS（且**合法空压过 stale 回退**：今日权威空 + 昨日非空快照时以今日空为准，不再触发 required_stale_fallback）；③ `min_usable_rows=200` 与候选池 `MIN_LISTING_DAYS=60` 矛盾（次新票按设计只有 ~60 根 bar）→ 硬门槛改为 60，200 保留为 informational 的 full-factor 目标。**改质量门常量前，先确认它约束的是"异常"还是"设计状态"。**
15. **price_cache 是不复权价，跨日窗口收益必须用 pct_change 链**（2026-07-18 对抗性审查）：825 票中 173 票近 200 行内有除权缺口（close 链收益与 pct_change 偏差 >1pp）。原始价比值跨缺口产生幻影（2026H1 全市场 817 个幻影超跌票日，OB 回测成交 31% 是幻影）。**已修：setup 检测窗、panel `_forward_return`、tracking 回填、--auto 评分链（`load_price_frame` 回溯复权）全部除权免疫**；成交收益链（ledger 估值/退出、paper_tracker）仍用原始价出入场——现金分红方向一律低估收益（0.5~3pp/笔），属已知前视风险。另外 v2 ledger 的 MarketBar limit_up/limit_down 现由前收 × 板块幅度按交易所规则推导（除权日锚点偏宽，每年 ~1 天/票）。
16. **profit_aware 校准池饥饿与 None 语义**（2026-07-18 定位）：严格模式 git-sha 等值过滤（27 版本漂移）+ 98% 记录无 `return_tN_date`，校准池 89/89 天为空 → profit_aware 实际从未生效（排序静默退回 composite）。已修：sha 仅 provenance 不过滤、未标注日期用交易日历推断 realized_on。另：profit_aware 主键 None 从 -inf 改中性（0.5 胜率/0.0 期望）——旧语义让"已知 30% 胜率"排在"未知"前（方向错误）。
17. **台账初始资金的整手截断**（2026-07-18 定位并修复）：10% 单票上限 × 10 万 = 1 万，股价 >100 元即买不起一手（journal 样本 28%~46% 的价格带，含 688 高价龙头）。**已解决**：initial_cash 默认提至 100 万（`DAILY_ACTION_LEDGER_INITIAL_CASH` 可覆盖），旧 10 万台账归档于 `data/paper_trading_v2/archive/`（0 成交，无损失）；skip 原因区分 `lot_floor_zero_shares` vs `cash_capacity`。
18. **低桶细分与盈利阈值校准**（2026-07-18）：① `SCORE_BUCKETS` 的 <0.5 单桶细分为 5 桶（tracking n=8168 实证内部单调梯度：0.1-0.2 峰 62.0% → 0.4-0.5 44.7%，高桶边界不变），profit_aware 主键在 Top10 内恢复区分度（此前 ~56% 的天全落同桶）；② profitability 阈值从美股口径（ROE≥0.15/NM≥0.20/OM≥0.15，A 股 75% 满置信看空）改为 A 股全市场 ~p65-70（0.08/0.09/0.11，n≈4800 快照），0 通过率 75%→~30%，quality-first 红旗恢复选择性。


## 关键文件速查

| 模块 | 文件 |
|---|---|
| 命令分发 | `src/cli/dispatcher.py`（`--daily-action` 在 `_resolve_daily_action`） |
| 凸性 setup 主逻辑 | `src/screening/offensive/daily_action.py`（`generate_daily_action`） |
| Setup 定义 | `src/screening/offensive/setups/btst_breakout.py`、`oversold_bounce.py` |
| Kelly 仓位 | `src/screening/offensive/kelly.py` |
| Paper tracker | `src/screening/offensive/paper_tracker.py`（成交记录、止损、drawdown） |
| 缓存刷新 | `src/screening/offensive/cache_refresh.py`（`--auto` → `--daily-action` 桥梁；已排除北交所；幂等跳写 + 资金流批量预取，见性能小节） |
| PIT 证据指纹 | `src/screening/offensive/pit_evidence.py`（canonical 指纹/校验；输出是 ledger 契约，改实现必须做逐位等价验证） |
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
