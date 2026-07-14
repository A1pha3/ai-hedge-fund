---
难度: ⭐⭐⭐⭐
类型: 专家设计
预计时间: 25 分钟
前置知识:
  - [系统架构总览](./overview.md) ⭐⭐⭐
  - [三层管线架构](./three-layer-pipeline.md) ⭐⭐⭐
  - [日常使用](../02-user-manual/daily-workflow.md) ⭐⭐
---

# 凸性 setup 系统

## 核心判断

`--daily-action` 不是 `--auto` 的"下一步",而是一套完全独立的凸性(convexity)交易系统。它绕开 `--auto` 的 Layer A/B/C 候选池,直接全市场扫描涨停或超跌的极端股票,用 Phase 0 验证过的 setup 分布作 Kelly 先验算仓位,写入 paper trading v2 ledger。两条管线的目标冲突:`--auto` 要"好股票"(稳定可投标的),`--daily-action` 要"极端股票"(涨停突破、超跌反弹)。

设计原则来自 Phase A "稳定小 edge":用历史分布作先验(不动态拟合,防过拟合)、全市场扫描(不依赖候选池)、drawdown 熔断自动降仓、预提交止损 + 时间退出、每笔写 journal。这套机制真正解决的是"如何把情绪从交易决策里剥离"——预测准不准是 Layer A/B/C 的事,这里关心的是预测错的时候系统能不能机械退出,而不是靠 operator 盘中拍脑袋止损。

## 系统总览图

```mermaid
flowchart TB
    subgraph SCAN["全市场扫描"]
        S1[glob data/price_cache/*.csv<br/>拿全市场文件名集合]
        S2[逐只跑 BtstBreakoutSetup.detect<br/>+ OversoldBounceSetup.detect]
        S3[trigger_strength >= 0.50 过滤]
        S1 --> S2 --> S3
    end

    subgraph SIZE["仓位计算"]
        K1[known_distributions<br/>Phase 0 验证过的分布]
        K2[kelly.py half-Kelly<br/>winrate / avg_gain / avg_loss]
        K3[regime_size_factor<br/>crisis 1.2 / risk_off 1.1 / normal 1.0]
        K4[单票上限 10% (BTST) / 5% (OB)<br/>组合上限 60%]
        K1 --> K2 --> K3 --> K4
    end

    subgraph LEDGER["v2 ledger"]
        L1[LedgerRepository<br/>data/paper_trading_v2/ledger.sqlite3]
        L2[BUY / EXIT / SKIP<br/>+ 止损价 + reasoning]
        L3[render_daily_action_v2<br/>控制台输出]
        L1 <--> L2 --> L3
    end

    S3 --> K4
    K4 --> L2
```

注意:扫描不读 `auto_screening_*.json` 的 Top N。`--auto` 的候选池过滤掉了涨停股(因为"买入排队失败"),而 BTST setup 需要的就是涨停股。`cache_refresh.py` 在 `--auto` 收尾把涨停股注入 price_cache,这是两条管线唯一的握手点。

## 两种 setup 对比

| 维度 | BTST 涨停突破 | OversoldBounce 超跌反弹 |
|---|---|---|
| 状态 | ✅ 启用 | ⏸️ 默认暂停 (`DAILY_ACTION_DISABLED_SETUPS=none` 恢复) |
| 时间退出 | T+10 | T+5 |
| 单票上限 | 10% | 5% (无 alpha 严格限制) |
| 触发核心 | 今日涨停 + 主力净流入 + 行业涨幅 | 超跌 + trigger_strength |
| 回测 E[r] | +8.15% (n=133) | +0.34% (n=59) |
| 95% CI | 显著正 | `[-3.15%, +3.83%]` 跨 0 |
| 尾部亏损>10% 占比 | 11% | 20% |
| regime 加仓 | crisis 1.2× / risk_off 1.1× | 不加仓 (1.0×) |

**OB 暂停理由**:不是"crisis 亏钱"(crisis n=21 太小不可靠),而是统计证据不足——E[r]=+0.34% 但 CI 跨 0(t=0.19, p≈0.85),无法证明它赚钱;尾部比 BTST 更毒;仓位受限时有统计显著的替代品(BTST)。这是"无 alpha 可放大,放大仓位有害"的判断,不是"crisis 分层差"的判断。

## BTST 四条触发条件

定义在 `src/screening/offensive/setups/btst_breakout.py::BtstBreakoutSetup.detect`:

1. **今日涨停**(`limit_up_pct_for_ticker`):板块自适应阈值——主板(000/001/600/601/603/605)9.5%、科创/创业(688/300/301)19.5%、北交所(8xxxxx)29.0%。旧固定 9.5% 会把 20% 板的非涨停大涨日(如 +13.9%)误判为涨停,语义被污染。
2. **主力净流入 > 20 日均值**(`_MAIN_FLOW_LOOKBACK_DAYS=20`):去掉冗余 >0 检查(涨停日必然正流入)。历史不足 20d 时用 ≥5 天的短窗口均值,标 `degraded=True`;不足 5d 跳过。
3. **所属行业当日涨幅 > 2%**(`_INDUSTRY_PCT_MIN=2.0`):板块效应。行业数据缺失时不过滤但标 degraded,与资金流浅数据降级同模式(避免"今日无信号"实际是数据管道断了)。
4. **涨停前 5 日累计涨幅 ≤ 8%**(`_PRE_RUNUP_MAX_PCT=8.0`):防追高。2026-07 回测后从 10% 收紧——8-10% 区间 52.4%/+3.10% 弱于池均值,<8% 58%+ 明显优于 >8% 53%。

条件 1-4 任一不满足即 `_miss`(保守跳过,不进候选)。

### trigger_strength 5 因子 ranker

命中的票还要过 trigger_strength ≥ 0.50 的过滤(`_MIN_TRIGGER_STRENGTH`)。5 因子等权 + 能量耦合 bonus 0.08:

| 因子 | 取值 | 权重 | 数据依据 |
|---|---|---|---|
| weekday | Wed-Fri=1.0 / Mon-Tue=0.0 | 0.20 | Wed-Fri 78% win vs Mon-Tue 51% |
| board | 002/300=1.0 / 688/60x=0.95 / 000=0.0 | 0.20 | 002/300 83% vs SZmain 45% |
| position | Donchian 下半区=1.0 / 上半区=0.0 | 0.20 | 新鲜突破 vs 追高 |
| squeeze | 近 3 日 ATR / 前 17 日 ATR <0.8 = 1.0 | 0.20 | 波动率压缩=弹簧释放 |
| volume | 1.0-1.2x=1.0 / 0.5-0.8x=0.0 / 噪讯区=0.4 | 0.20 | 2409 涨停样本实测 |

`min(1.0, 0.20×(weekday+board+position+squeeze+volume) + energy_bonus)`。<0.50 的命中被滤掉,避免 ranker 底部的垃圾信号占用仓位配额。

## Kelly 仓位计算

入口在 `src/screening/offensive/kelly.py::compute_kelly_size`。公式(离散二元结果):

```python
kelly_fraction = winrate / |avg_loss| - (1 - winrate) / avg_gain
half_kelly = 0.5 × kelly_fraction
adjusted = half_kelly × correlation_discount × market_temperature_factor
position_pct = min(adjusted, max_pct)  # 单 setup 仓位上限
```

half-Kelly(非 full):牺牲 25% 长期收益换大幅降低破产概率和方差,对估计误差更鲁棒。`known_distributions` 是 Phase 0 验证过的分布常量(硬编码,非动态拟合——防过拟合),作为 Kelly 先验。

### regime 加仓系数

`_REGIME_SIZE_FACTORS_BY_SETUP` 按 setup 区分(2026 H1 真实回测验证):

```python
"btst_breakout":    {"crisis": 1.2, "risk_off": 1.1, "normal": 1.0}  # 三个 regime 都赚钱, crisis 最强
"oversold_bounce":  {"crisis": 1.0, "risk_off": 1.0, "normal": 1.0}  # 无 alpha 可放大
```

硬上限 `_REGIME_POSITION_CAP_MULTIPLE=1.2`:即使 crisis 触发 1.2×,单票最多 10%×1.2=12%;组合层 `_MAX_PORTFOLO_PCT=0.60` 仍兜底。

**当前状态**:v2 ledger 因 canonical manifest 缺少可重算的 regime 授权证据,安全降级到 10%,并披露 `regime_authorization_evidence_unavailable`。12% regime 例外暂停,待 canonical regime evidence 可由 repository 重验后恢复。

### 仓位硬约束

| 约束 | 值 | 代码常量 |
|---|---|---|
| 默认单票上限 | 10% | `_MAX_POSITION_PCT` |
| BTST 单票上限 | 10% | `_MAX_POSITION_PCT_BY_SETUP["btst_breakout"]` |
| OB 单票上限 | 5% | `_MAX_POSITION_PCT_BY_SETUP["oversold_bounce"]` |
| 组合上限 | 60% | `_MAX_PORTFOLO_PCT` |
| 最低入场价 | 3.0 元 | `_MIN_ENTRY_PRICE` (过滤低价股尾部亏损) |
| 最低 trigger_strength | 0.50 | `_MIN_TRIGGER_STRENGTH` |
| 买入窗口截止 | 17:00 | `_ENTRY_WINDOW_CUTOFF` |

`DAILY_ACTION_ENFORCE_OPEN_CAP=true`(默认):T+10 跨日持仓计入 60% 上限 → 敞口守上限。真实 journal 曾因 per-run 重置峰值 260%(26 仓),61 天超 60%。

## 完整 BTST 信号案例:从扫描到 BUY 计划

以 2026-07-13 (周一) 收盘后为例,假设 002XXX 当日涨停(涨幅 10.0%,主板)、主力净流入 8000 万、所属电子行业涨 3.2%、涨停前 5 日累计涨 4%:

**第一步:`_resolve_daily_action` 解析信号日**

`scan_daily_action_candidates` 探测 `data/price_cache/` 最新日期。17:00 guard:若当前时间 <17:00,信号日回退到上一交易日(避免用不完整的当日数据)。

**第二步:加载 verified snapshot(如果存在)**

`load_verified_daily_action_snapshot` 尝试读 immutable PIT (point-in-time) 快照。存在则 `scan_from_verified_snapshot` 从快照产候选,scanner 不再重开 cache 文件;不存在则 block 新入场(只推进 lifecycle,render 现有持仓 + block 原因)。

**第三步:`BtstBreakoutSetup.detect("002XXX", "20260713", context)`**

- 条件 1:`limit_up_pct_for_ticker("002XXX")` → 9.5% (主板),今日 10.0% ≥ 9.5% ✓
- 条件 2:`today_flow=8000 万 > hist_mean` (20d 均值,假设 5000 万) ✓
- 条件 3:`industry_pct=3.2% > 2.0%` ✓
- 条件 4:`pre_runup_pct=4.0% ≤ 8.0%` ✓

计算 trigger_strength:
- weekday:周一=0.0 (Mon-Tue 最差)
- board:002 开头=1.0
- position:假设涨停前 5 日 close 在下半区=1.0
- squeeze:假设近 3 日 ATR / 前 17 日 ATR=0.7 <0.8=1.0
- volume:假设今日量 / 20d 均量=1.1 (1.0-1.2x 最佳区)=1.0
- energy_bonus:position+squeeze 都 ≥0.5 → +0.08

`strength = min(1.0, 0.20×(0+1+1+1+1) + 0.08) = min(1.0, 0.88) = 0.88 ≥ 0.50` ✓

**第四步:`DailyActionService` 算 Kelly 仓位**

读 `known_distributions["btst_breakout"]`(Phase 0 常量),假设 winrate=0.68、avg_gain=+0.12、avg_loss=-0.08:

```python
kelly_raw = 0.68/0.08 - 0.32/0.12 = 8.5 - 2.67 = 5.83
half_kelly = 0.5 × 5.83 = 2.92
adjusted = 2.92 × 1.0 (corr) × regime_factor
```

读 `regime_history.json["20260713"]` → 假设 "normal" → regime_factor=1.0。但 v2 ledger 当前安全降级,position_pct = min(2.92, 0.10) = 0.10 = 10%。

**第五步:写 v2 ledger + render**

`LedgerRepository` 写 BUY 记录到 `data/paper_trading_v2/ledger.sqlite3`,含 ticker、setup、entry_price、kelly_pct=0.10、止损价(基于盘整区底部 ×0.92,但不低于 -8%)。`render_daily_action_v2` 输出:

```
BUY 002XXX btst_breakout
  entry_price: 12.50
  kelly_pct: 10.0% (capped, regime=normal)
  stop: 11.50 (盘整区底部 11.50, -8.0%)
  horizon: T+10 (20260723)
  trigger_strength: 0.88
  ⚠ regime_authorization_evidence_unavailable: 加仓降级到 10%
```

## 止损披露:为什么当前是摆设

`stop_would_have_triggered` 只进 reasoning 字符串,**不影响 realized P&L**(账面按 T+N close)。192 笔回测 0 笔触发(2026 牛市行情好)。

回测验证(2026-07-10,81 笔 BTST)显示**所有止损策略在当前牛市样本都会降低 E[r] 和 Sharpe**——均值回归 setup 的波动反而赚钱,固定 -8% 止损会在反弹前砍仓。故默认不执行。

启用方式:`DAILY_ACTION_EXECUTION_STOP=atr_k2|atr_k3|fixed8` env(改变 P&L 口径,启用前应跑 `scripts/backtest_exit_strategies.py` 确认当前行情有利)。

这是设计取舍,不是 bug:牛市样本下止损有害,熊市/高波动期才需要。止损策略是 disclosure-only 还是 execution-on,由 operator 根据行情切换。

## 回测表现解读(2026 H1, paper_trading_backtest)

```
BTST (n=133):           winrate=68%  E[r]=+8.15%
  crisis=+16.93%/76%    risk_off=+8.87%/78%    normal=+6.29%/66%
OversoldBounce (n=59):  winrate=53%  E[r]=+0.34%
  crisis=-1.15%/48%(n=21)   normal=+0.15%/51%   risk_off=+13.11%/100%(n=3)
```

**这些数字在测什么**:paper_trading_backtest/journal.jsonl 里 211 笔 BUY + 192 笔 EXIT 的真实成交,2026-01-15 → 2026-07-06,按 setup + regime 分层。

**反映系统哪部分**:BTST 的 detect 逻辑、Kelly 仓位、T+10 时间退出。**不反映**:止损执行(默认摆设)、regime 加仓(当前降级)、`--auto` 的 Layer A/B/C(两套独立系统)。

**不能推出什么**:
- 样本期仅 6 个月(2026 H1 牛市),有样本期偏差。BTST 三个 regime 都赚钱不代表熊市也赚;OB 的 crisis -1.15% n=21 太小,与 risk_off n=3 反而 +13.11% 矛盾 → 分层不可靠,不能作为独立决策依据。
- E[r]=+8.15% 不能外推到未来——它是"当前最佳依据",补全历史数据重跑后结论可能变。

## 采用顺序与边界

**先确认 `price_cache` 和 `fund_flow_cache` 已刷新**。`--daily-action` 读缓存,缓存不新鲜出的是昨日信号。17:00 guard 会回退到昨日信号日,但仅限盘前;盘后跑若缓存未刷新,会拿到前日数据。

**默认配置下 BTST 单票 10%,组合 60%**。regime 加仓当前安全降级,不要在没绑定 canonical regime evidence 前手动改 `_REGIME_POSITION_CAP_MULTIPLE`。

**OB 恢复前先跑 `scripts/setup_research.py` 补全历史数据**。当前 price_cache 只有 6 个月(见 [data-layer.md](./data-layer.md)),直接重跑 setup_research 会 n=0;Phase 0 报告声称的 n=1762 在更深历史生成,本地无法复现。补全数据后用 `DAILY_ACTION_DISABLED_SETUPS=none` 恢复 OB,再决定去留。

**止损切换口径前先回测**。`DAILY_ACTION_EXECUTION_STOP=atr_k2` 会改变 P&L 计算,启用前跑 `scripts/backtest_exit_strategies.py` 看当前行情下哪种止损有利——牛市样本下所有止损都降低 E[r],不是配置问题,是行情问题。

## 深入阅读

- [BTST 设计](../04-design/btst-breakout-design.md):5 因子 ranker 的回测细节
- [Kelly 仓位设计](../04-design/kelly-position-sizing.md):half-Kelly 的数学推导
- [风险框架](../04-design/risk-framework.md):drawdown 熔断与 regime 加仓
- [paper trading 设计](../04-design/paper-trading-design.md):v2 ledger 的审计设计
