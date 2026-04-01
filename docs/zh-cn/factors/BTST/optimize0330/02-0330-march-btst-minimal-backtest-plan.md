# 0330 BTST 3 月最小回测方案

文档日期：2026 年 4 月 1 日  
适用对象：需要用 2026 年 3 月历史数据验证 BTST 选股策略、控制过拟合并形成后续调优节奏的研究员、策略负责人、开发者、AI 助手。  
文档定位：给当前仓库提供一套最简洁、最高信息密度、可直接执行的 BTST 回测方案。它不追求一次性解释所有问题，而是优先回答“当前策略是否真的有 edge、edge 来自哪里、下一轮该只调哪一个杠杆”。

建议搭配阅读：

1. [BTST 调参与验证作战手册](../02-btst-tuning-playbook.md)
2. [BTST 命令作战手册](../13-btst-command-cookbook.md)
3. [0330 BTST 研究执行清单](./01-0330-research-execution-checklist.md)
4. [0330 优化路线设计文](./README.md)

---

## 1. 先讲结论

可以，而且应该用 3 月历史数据做 BTST 回测，但不要把它做成“大一统长回测”。

对当前仓库，最优方案不是直接跑整月一次总收益，而是拆成 3 层：

1. 开发层：用 3 月上半月做冻结计划 replay，先判断候选供给、漏判、分数前沿是否有改善。
2. 验证层：用 3 月下旬做 closed-cycle 微窗口回测，重点看次日空间、次日收盘延续和 T+2 代理退出，而不是先看累计收益。
3. 升级层：只有当 closed-cycle 微窗口在 tradeable surface、false negative proxy 和非目标污染三项同时过关，才允许进入下一轮 live window 验证或默认升级讨论。

当前已知最强的 3 月证据，不是“baseline 能赚钱”，而是：

1. baseline 在 2026-03-23 到 2026-03-26 的 closed-cycle 窗口里 `tradeable surface=0`。
2. 同一窗口里 baseline 有 19 个 false negative proxy，`next_high_hit_rate@2%=0.7895`、`next_close_positive_rate=0.8421`，说明市场给过机会，但系统漏了很多。
3. `short_trade_boundary + catalyst_freshness_min=0.00` 的当前变体在同一 closed-cycle 窗口里释放出 6 个 tradeable near-miss，且 `next_high_hit_rate@2%=0.8333`、`next_close_positive_rate=0.8333`、`t_plus_2_close_positive_rate=0.8333`，这是目前最接近“可升级研究基线”的 3 月证据。

所以，3 月回测的核心目标不是先证明“整月赚了多少钱”，而是先证明：

1. 系统能否稳定放出可交易机会。
2. 放出来的机会是否真的有次日空间和隔夜延续。
3. 新规则是否只救目标样本，而不是把噪声一并放进来。

---

## 2. 为什么这套方案最适合当前仓库

大奖章式研究方法的核心不是复杂，而是把“发现 edge”和“确认 edge”强制分开，避免把研究自由度浪费在一个小窗口里。对当前 BTST 来说，这意味着 4 条纪律：

1. 不把 3 月当成一个单一总样本，而是切成开发样本和验证样本。
2. 不把最终收益当成唯一指标，而是先看机会质量，再看执行代理收益。
3. 不允许同时改 admission、threshold、penalty、structural conflict 多条线。
4. 不因为个别票表现好，就直接升级默认值。

当前仓库已经天然支持这套分层：

1. `scripts/run_paper_trading.py` 负责真实窗口或冻结计划 replay。
2. `scripts/analyze_btst_micro_window_regression.py` 负责 closed-cycle 微窗口回归。
3. `scripts/analyze_btst_score_construction_frontier.py`、候选入口与 penalty 相关脚本负责单主题前沿分析。
4. `selection_target_replay_input.json`、`selection_snapshot.json` 和 `daily_events.jsonl` 已经把选股、分层、执行证据拆开保存。

也就是说，当前缺的不是基础设施，而是统一研究协议。

---

## 3. 方案总览

### 3.1 时间切分

建议把 2026 年 3 月拆成两个区间：

1. 开发区间：2026-03-02 到 2026-03-13。
2. 验证区间：2026-03-23 到 2026-03-27。

原因：

1. 3 月上半月已有冻结计划 replay 产物，可低成本反复做参数与规则实验。
2. 3 月下旬已经形成 BTST 真实窗口和 closed-cycle 证据，是当前最接近真实短线语义的验证集。
3. 中间的 3 月 14 日到 3 月 22 日不必强行塞进第一版方案，否则会把研究窗口、市场结构和样本质量掺在一起，降低解释力。

### 3.2 三层验证结构

| 层级 | 目标 | 核心样本 | 是否允许调参 | 主要输出 |
| --- | --- | --- | --- | --- |
| L1 冻结 replay | 找方向、筛杠杆 | 2026-03-02 到 2026-03-13 | 允许，但每轮只动一个主题 | false negative、失败簇迁移、规则污染 |
| L2 微窗口回测 | 验证机会质量 | 2026-03-23 到 2026-03-26 closed-cycle | 不允许大范围扫网格 | tradeable surface、hit rate、T+2 代理退出 |
| L3 单日前瞻 | 验证执行语义 | 2026-03-27 forward-only | 不用于升级默认值 | 主票 / 观察票 / 执行卡片 |

### 3.3 最小结论标准

一个 BTST 变体要通过 3 月最小回测，不要求先满足“整月收益最优”，而要求同时满足：

1. L1 中主失败簇收缩，且新增样本不是大面积非目标 spillover。
2. L2 中 tradeable surface 从 0 提升到正值。
3. L2 中 `next_high_hit_rate@2%` 和 `next_close_positive_rate` 不低于 baseline false negative proxy 的保守护栏。
4. L3 中主入场票与观察票语义清晰，没有把 near-miss 直接伪装成 selected。

---

## 4. 评估指标

### 4.1 一级指标：机会质量

这是 BTST 最重要的指标组，优先级高于累计收益。

必须看：

1. `next_high_return_mean`
2. `next_high_hit_rate@2%`
3. `next_close_return_mean`
4. `next_close_positive_rate`

解释：

1. `next_high` 代表次日盘中是否给过突破确认空间。
2. `next_close` 代表次日延续是否成立。
3. 如果这两项都差，即使 T+2 某些票偶然盈利，也不应被解释成稳定 BTST edge。

### 4.2 二级指标：执行代理

当前系统还不是分钟级真回放，因此执行质量先用代理指标衡量：

1. `next_open_return`
2. `next_open_to_close_return`
3. `t_plus_2_close_return`
4. `preferred_entry_mode`

解释：

1. `next_open_return` 用来判断开盘追价是否过差。
2. `next_open_to_close_return` 用来判断盘中确认后是否仍有性价比。
3. `t_plus_2_close_return` 只是隔夜 continuation 代理，不是分钟级真实成交 PnL。

### 4.3 三级指标：研究价值

这是决定“值不值得继续调”的指标组：

1. false negative proxy 数量
2. false negative proxy 的质量分布
3. changed non-target case count
4. candidate_source 迁移情况

如果一个变体只是把噪声从 `layer_b_boundary` 挪到 `short_trade_boundary`，而没有提升 closed-cycle 质量，那不算进步。

---

## 5. 2026 年 3 月的推荐基线

### 5.1 基线 A：历史诊断基线

使用对象：需要确认旧问题到底出在哪一层。

推荐输入：

1. `data/reports/gate_experiment_w1_20260202_20260313_20260323`
2. 3 月上半月相关 `daily_events.jsonl`
3. 3 月上半月各日 `selection_snapshot.json`

用途：

1. 回看 shared Layer B 路径为什么会冷。
2. 找 3 月上半月是否已经存在与当前窗口同构的 false negative。
3. 验证当前要调的是 admission、score frontier 还是 candidate entry。

### 5.2 基线 B：当前 closed-cycle 验证基线

这是当前最重要的 3 月验证基线。

推荐目录：

1. `data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329`
2. `data/reports/btst_micro_window_regression_20260330.json`

已知结论：

1. 32 个样本里 `selected=0`、`near_miss=0`、`blocked=5`、`rejected=27`。
2. `tradeable surface=0`。
3. false negative proxy 有 19 个，质量显著高于 baseline 的直接放行结果。

这个基线的角色不是“可交易默认方案”，而是“最小反证”，即证明旧机制确实在漏票。

### 5.3 基线 C：当前最强候选变体

推荐目录：

1. `data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_catalyst_floor_zero_validation_20260329`
2. `data/reports/btst_micro_window_regression_20260330.json`

已知结论：

1. 33 个样本里 `near_miss=6`、`blocked=5`、`rejected=22`。
2. `tradeable surface=6`，全部来自 near-miss。
3. tradeable 样本的 `next_high_hit_rate@2%=0.8333`。
4. tradeable 样本的 `next_close_positive_rate=0.8333`。
5. tradeable 样本的 `t_plus_2_close_positive_rate=0.8333`。

这条基线说明：当前最值得保留的不是“继续找更多放松项”，而是把这条准入主线当成验证基座，再往 score frontier、candidate entry 和结构治理推进。

---

## 6. 最小执行流程

### Step 1：固定 3 月基线，不直接改默认值

先把下面 3 份对象当成固定基线：

1. 3 月上半月冻结 replay 样本。
2. 3 月下旬 closed-cycle baseline。
3. 3 月下旬 catalyst floor zero 变体。

先回答 3 个问题：

1. 当前主问题是 coverage、score frontier 还是 structural blocker。
2. 当前最强变体是否已经足以形成可交易曲面。
3. 还有哪些 false negative 值得继续分型。

### Step 2：每轮只选一个主题

可选主题只有这些：

1. candidate entry semantics
2. score construction frontier
3. stale / extension penalty frontier
4. targeted structural release

不建议本轮再回到 shared Layer B 大池做广泛 admission 扫描，因为 3 月下旬真实窗口已经证明当前主候选源是 `short_trade_boundary`。

### Step 3：先做 3 月上半月冻结 replay

目的：验证规则方向，不消耗真实窗口解释力。

推荐命令模板：

```bash
./.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-03-02 \
  --end-date 2026-03-13 \
  --selection-target dual_target \
  --frozen-plan-source data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/daily_events.jsonl \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir data/reports/paper_trading_20260302_20260313_btst_research_replay
```

注意：

1. 这一步主要用于规则诊断，不用于宣称收益。
2. 这一层更适合跑 replay 校准和单主题前沿分析。

### Step 4：再做 3 月下旬 closed-cycle 微窗口验证

目的：用最接近真实 BTST 的闭环窗口判断机会质量。

当前仓库已有现成产物，可先直接消费：

1. `data/reports/btst_micro_window_regression_20260330.json`
2. `data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_catalyst_floor_zero_validation_20260329`

如果要重跑或新增变体，优先复用：

```bash
./.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-03-23 \
  --end-date 2026-03-26 \
  --selection-target dual_target \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir data/reports/paper_trading_window_20260323_20260326_<variant_name>
```

然后用微窗口回归脚本统一评价。

### Step 5：最后只把 2026-03-27 当成前瞻观察层

推荐目录：

1. `data/reports/paper_trading_20260327_20260327_live_m2_7_short_trade_only_20260329`

这一步只回答：

1. 主入场票和观察票是否分层清晰。
2. 次日执行卡片是否与回测语义一致。

不回答：

1. 是否已经形成稳定可升级默认值。
2. 是否可以因为单日样本就扩展整月结论。

---

## 7. 推荐命令矩阵

### 7.1 最小必跑集

```bash
./.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-03-02 \
  --end-date 2026-03-13 \
  --selection-target dual_target \
  --frozen-plan-source data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/daily_events.jsonl \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir data/reports/paper_trading_20260302_20260313_btst_research_replay

./.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-03-23 \
  --end-date 2026-03-26 \
  --selection-target dual_target \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir data/reports/paper_trading_window_20260323_20260326_btst_baseline_refresh

./.venv/bin/python scripts/run_short_trade_boundary_variant_validation.py \
  --start-date 2026-03-23 \
  --end-date 2026-03-26 \
  --selection-target dual_target \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --variant-name catalyst_floor_zero \
  --output-dir data/reports/paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh \
  --summary-json data/reports/paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh_summary.json

./.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-03-27 \
  --end-date 2026-03-27 \
  --selection-target short_trade_only \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir data/reports/paper_trading_20260327_20260327_btst_forward_refresh

./.venv/bin/python scripts/analyze_btst_micro_window_regression.py \
  --baseline-report-dir data/reports/paper_trading_window_20260323_20260326_btst_baseline_refresh \
  --variant-report catalyst_floor_zero=data/reports/paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh \
  --forward-report short_trade_only_20260327=data/reports/paper_trading_20260327_20260327_btst_forward_refresh \
  --output-json data/reports/btst_micro_window_regression_march_refresh.json \
  --output-md data/reports/btst_micro_window_regression_march_refresh.md
```

### 7.2 单主题调优集

如果当前主题是分数构造前沿：

```bash
./.venv/bin/python scripts/analyze_btst_score_construction_frontier.py \
  data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_catalyst_floor_zero_validation_20260329 \
  --output-json data/reports/btst_score_construction_frontier_march.json \
  --output-md data/reports/btst_score_construction_frontier_march.md
```

如果当前主题是候选入口语义：

1. 优先读取 `selection_target_replay_input.json`。
2. 只做结构变体 replay，不直接回写默认值。

如果当前主题是 targeted release：

1. 只针对单票或单簇执行。
2. 必须同时检查 `changed_non_target_case_count`。

---

## 8. 升级与淘汰标准

### 8.1 允许进入下一轮的条件

一个 3 月变体只有同时满足下面 4 条，才值得继续：

1. closed-cycle `tradeable surface > 0`。
2. `next_high_hit_rate@2% >= 0.75`。
3. `next_close_positive_rate >= 0.70`。
4. 没有明显非目标污染，或污染成本远低于目标改善。

这个门槛不是理论最优，而是当前 3 月样本规模下的最低防过拟合门槛。

### 8.2 必须淘汰的信号

出现下面任一情况，应直接降级为观察项：

1. 只能靠多条参数联动才放出样本。
2. tradeable surface 增加，但 false negative 质量明显下降。
3. 结构释放会带出大量非目标样本。
4. 单票成功，但无法形成第二个独立窗口复现。

---

## 9. 当前最建议的研究顺序

基于现有 3 月证据，最合理的顺序不是继续广撒网，而是：

1. 固定 `short_trade_boundary + catalyst_freshness_min=0.00` 为当前 3 月验证基座。
2. 在这个基座上优先研究 `short_trade_boundary_score_fail` 的局部前沿，而不是重新打开 shared Layer B admission。
3. 把 `001309` 视为主推进样本，把 `300383` 视为单票影子样本，把 `300724` 维持为结构冻结样本。
4. 等新增独立窗口出现后，再判断当前 3 月发现是否具备跨窗口稳定性。

这套顺序的好处是：

1. 解释力强。
2. 过拟合风险低。
3. 与当前仓库已有 artifacts 和脚本完全对齐。

---

## 10. 一句话版方案

用 3 月上半月做冻结 replay 找方向，用 3 月下旬 closed-cycle 微窗口验证机会质量，用 3 月 27 日单日样本校验执行分层；先证明策略能稳定放出可交易机会，再讨论整月收益和默认升级。
