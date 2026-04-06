# BTST 策略综合测试计划

## 文档定位

- **适用对象**：BTST 策略开发者、回测验证负责人、超短线研究与执行协同人员
- **测试对象**：当前默认 BTST 档位 + 独立的 T+2 continuation overlay
- **核心约束**：**默认 BTST 档位不放宽、不直接并入 continuation 结果、所有新增 alpha 先停留在 `paper_only` 隔离层**

## 学习目标

阅读完本文后，应能完成以下事项：

1. 理解当前 BTST 优化后的真实验证边界，区分“结构正确”与“收益已证实”。
2. 用仓库现有测试、回测、walk-forward 和 A/B 对比能力，对 BTST 做完整历史回归验证。
3. 依据统一指标、产物和门禁标准，判断某个 BTST 优化是否可以继续保留、进入 paper overlay，或必须回滚。

## 一、测试目标与结论口径

本测试计划不只回答“代码有没有坏”，还要回答 4 个更关键的问题：

1. **逻辑是否正确**：候选池、评分、筛选、治理、回测与执行链路是否仍按预期工作。
2. **优化是否有效**：新规则在历史窗口中，是否相对 baseline 带来更好的胜率、收益分布或风险收益比。
3. **收益是否稳健**：改进是否只在单一窗口、单一标的、单一市场状态下有效，还是具有跨窗口稳定性。
4. **风险是否可控**：收益提升是否以更差的回撤、集中度、极端亏损尾部为代价。

本仓库当前最重要的判断标准是：

- **默认 BTST** 仍保持已验证默认档：`watchlist_zero_catalyst_guard_relief @ select=0.40 / near_miss=0.40`
- **continuation lane** 仍然隔离，不能把 paper overlay 的结果当作默认 BTST 已经优化成功
- **收益改进必须通过历史 A/B + walk-forward**，不能只凭单个候选案例或单次 paper 结果判断

## 二、当前被测系统状态

截至当前最新 continuation watchboard 产物，系统处于以下状态：

| 项目 | 当前状态 |
|------|----------|
| 默认 BTST 档位 | 未变更 |
| continuation lane | `observation_only` |
| capital mode | `paper_only` |
| 有效 watchlist | `["600989", "300505"]` |
| 有效 eligible | `["600988", "300505"]` |
| 有效 execution candidates | `["300505"]` |
| focus ticker | `300505` |
| lane support ratio | `0.875` |
| `300505` 的 `t+2_close_return_mean` | `0.0361` |
| 相对 watch benchmark 的 `t+2` 均值差 | `+0.0244` |

这组状态说明两件事：

1. **结构优化已经落地**：review -> gate -> execution overlay 的治理链完整可测。
2. **收益优化尚未最终证实**：`300505` 现在只是隔离的 `paper_execution_candidate`，还不能代表默认 BTST 已经获得正式收益提升。

## 三、测试范围

### 3.1 范围内

1. **Phase 1：筛选与评分基础层**
   - `candidate_pool`
   - `strategy_scorer`
   - `signal_fusion`
   - `phase2 screening`
2. **Phase 2：BTST continuation 治理层**
   - promotion review / gate
   - watchlist execution
   - eligible gate / execution
   - execution gate / overlay
   - governance board / watchboard
3. **Phase 3：回测与比较层**
   - `walk_forward`
   - `compare`
   - `rule_variant_compare`
   - pipeline mode / execution / portfolio / metrics
4. **Phase 4：历史效果验证层**
   - baseline vs continuation overlay A/B
   - 多窗口 walk-forward
   - 关键 ticker / 关键窗口 replay
   - 风险与收益质量分析

### 3.2 范围外

1. 实盘交易放量验证
2. 非 BTST 主线策略
3. 未进入仓库现有脚本或测试框架的全新实验型能力

## 四、测试分层设计

### 4.1 L0：静态与环境前置检查

目标是保证后续结果具备可重复性。

检查项：

1. Python 依赖已安装，优先使用 `uv run ...`
2. `.env` 中模型与数据源配置完整
3. 数据快照目录、`data/reports/` 输出目录可写
4. 当前默认 profile 未被意外修改
5. continuation 相关最新产物存在且能读取

建议命令：

```bash
uv run python -c "from src.targets.profiles import SHORT_TRADE_TARGET_PROFILES; print(sorted(SHORT_TRADE_TARGET_PROFILES.keys())[:5])"
uv run python -c "import json, pathlib; p=pathlib.Path('data/reports/btst_tplus2_continuation_watchboard_latest.json'); print(p.exists())"
uv run backtester --show-default-model
```

通过标准：

- 配置可解析
- 关键产物存在
- 默认 profile 名称与预期一致

### 4.2 L1：单元与逻辑回归

这一层只验证“逻辑没坏、接口没漂移、关键约束仍在”，不直接判断收益。

#### 重点测试组

| 模块 | 目标 | 现有测试 |
|------|------|----------|
| 候选池 | 候选构建、冷却期、流动性排序、日频数据聚合 | `tests/screening/test_candidate_pool.py` |
| 评分器 | 轻重信号分层、盈利质量约束、heavy-score 裁剪 | `tests/screening/test_strategy_scorer.py` |
| 筛选阶段 | 市场状态、信号融合、评分聚合、层间一致性 | `tests/screening/test_phase2_screening.py` |
| walk-forward | 滚动窗口生成、统计汇总、测试日截断 | `tests/backtesting/test_walk_forward.py` |
| A/B compare | baseline vs MVP 汇总与报告输出 | `tests/backtesting/test_compare.py` |
| variant compare | 规则变体构造、收益/耗时汇总 | `tests/backtesting/test_rule_variant_compare.py` |
| continuation 治理 | promotion / watch / eligible / execution 全链路 | `tests/test_generate_btst_tplus2_continuation_*` |

建议执行顺序：

```bash
uv run pytest tests/screening/test_candidate_pool.py tests/screening/test_strategy_scorer.py tests/screening/test_phase2_screening.py -v
uv run pytest tests/backtesting/test_walk_forward.py tests/backtesting/test_compare.py tests/backtesting/test_rule_variant_compare.py -v
uv run pytest tests/test_generate_btst_tplus2_continuation_promotion_gate_script.py tests/test_generate_btst_tplus2_continuation_watchlist_execution_script.py tests/test_generate_btst_tplus2_continuation_eligible_gate_script.py tests/test_generate_btst_tplus2_continuation_eligible_execution_script.py tests/test_generate_btst_tplus2_continuation_execution_gate_script.py tests/test_generate_btst_tplus2_continuation_execution_overlay_script.py tests/test_generate_btst_tplus2_continuation_governance_board_script.py tests/test_generate_btst_tplus2_continuation_watchboard_script.py -v
```

通过标准：

1. 所有相关测试通过
2. 默认 profile 行为未被 continuation 逻辑污染
3. watch / eligible / execution overlay 仍保持“基线 rulepack 不变、effective state 单独叠加”的模式

### 4.3 L2：脚本与产物回归

这一层验证“脚本跑完后，生成的报告与治理语义仍对”。

重点检查的产物：

- `data/reports/btst_tplus2_continuation_watchboard_latest.json`
- `data/reports/btst_tplus2_continuation_governance_board_latest.json`
- `data/reports/btst_tplus2_continuation_promotion_gate_latest.json`
- `data/reports/btst_tplus2_continuation_watchlist_execution_latest.json`
- `data/reports/btst_tplus2_continuation_eligible_gate_latest.json`
- `data/reports/btst_tplus2_continuation_eligible_execution_latest.json`
- `data/reports/btst_tplus2_continuation_execution_gate_latest.json`
- `data/reports/btst_tplus2_continuation_execution_overlay_latest.json`

必查字段：

| 字段 | 预期 |
|------|------|
| `effective_watchlist_tickers` | 包含 `300505` |
| `effective_eligible_tickers` | 包含 `300505` |
| `effective_execution_candidates` | 为 `["300505"]` |
| `entry_type` | 同一 ticker 允许出现 `promoted_validation_watch` / `promoted_watch_eligible` / `paper_execution_candidate` |
| `capital_mode` | 仍为 `paper_only` |
| `lane_stage` | 仍为 `observation_only` |
| `promotion_blocker` | 不应出现“默认 BTST 已放开”的语义漂移 |

通过标准：

1. 产物存在且字段完整
2. 没有把 continuation overlay 误写回默认档
3. operator-facing 报告可同时呈现同一 ticker 的多阶段条目

### 4.4 L3：历史窗口回放

这一层开始回答“优化是否可能带来收益改善”。

原则：

1. **先做 baseline**
2. **再做 continuation overlay / variant**
3. **同窗口、同数据范围、同模型配置比较**
4. **先看分布，再看均值**

建议窗口：

| 类别 | 目的 | 建议 |
|------|------|------|
| 短窗 | 快速发现方向性问题 | 1-2 个月 |
| 中窗 | 观察胜率与回撤结构 | 3-6 个月 |
| 扩窗 | 检查样本依赖与收益集中度 | 覆盖多个行情状态 |
| 重点窗 | 围绕 `300505`、`600988`、`600989` 的验证窗 | 使用已有 BTST 报告窗口 |

建议输出：

- Markdown 报告
- JSON payload
- 每窗指标摘要
- 关键 ticker 行为差异摘要

### 4.5 L4：A/B walk-forward 验证

这是当前最重要的一层。只有它能把“偶然有效”与“跨窗稳定有效”分开。

#### Group 定义

| 组别 | 含义 |
|------|------|
| A 组 | baseline BTST |
| B 组 | baseline BTST + continuation overlay / 待验证变体 |

#### 必须遵守的比较原则

1. 训练窗和测试窗切分一致
2. 模型、analyst roster、并发参数一致
3. 只允许比较目标变量，不允许混入无关改动
4. 不仅比较收益率，还要比较回撤、Sortino、样本数和尾部风险

仓库现有能力已经支持：

- `build_walk_forward_windows()`
- `run_walk_forward()`
- `run_ab_comparison_walk_forward()`
- `build_ab_comparison_payload()`
- `format_ab_comparison_report()`

建议命令：

```bash
uv run backtester --ab-compare --mode pipeline \
  --start-date 2025-12-01 --end-date 2026-03-04 \
  --train-months 2 --test-months 1 --step-months 1 \
  --model-provider Zhipu --model-name glm-4.7 \
  --analysts-all \
  --baseline-top-n 10 \
  --report-file data/reports/ab_walk_forward_btst_test_plan.md \
  --report-json data/reports/ab_walk_forward_btst_test_plan.json
```

如遇 provider reset 或长作业中断，使用监督脚本：

```bash
uv run python scripts/supervise_ab_compare.py \
  --start-date 2025-12-01 --end-date 2026-03-04 \
  --train-months 2 --test-months 1 --step-months 1 \
  --analyst-concurrency-limit 3 \
  --model-provider Zhipu --model-name glm-4.7 \
  --report-file data/reports/ab_walk_forward_btst_supervised.md \
  --report-json data/reports/ab_walk_forward_btst_supervised.json
```

### 4.6 L5：收益质量与风险质量复核

仅看 `avg_sortino_delta > 0` 还不够，必须附加收益质量检查。

至少复核以下问题：

1. 收益是否只由单一 ticker 驱动
2. 样本是否只集中在少数交易日
3. `next_close` 与 `t+2_close` 是否出现相反方向的“表面改善”
4. 回撤、CVaR、尾部亏损是否恶化
5. 新增 tradeable surface 是否主要来自低质量 offender 回流

建议产物：

- 窗口收益质量复盘文档
- ticker 贡献拆解表
- 失败样本模式复盘
- 决策拦截原因分布

## 五、测试矩阵

### 5.1 功能矩阵

| 维度 | 关注点 | 失败信号 |
|------|--------|----------|
| 候选池 | 候选数、流动性排序、冷却机制 | 样本明显漂移、排序反转 |
| 评分器 | light/heavy 分层、质量 cap、事件衰减 | 重信号误跑、低质量样本放大 |
| Phase 2 筛选 | 市场状态、仓位缩放、信号归一化 | 阈值无效、权重异常 |
| continuation gate | review/gate/execution 顺序 | 自动越级、默认档被污染 |
| 回测引擎 | 指标、组合轨迹、执行结果 | 指标缺失、收益曲线断裂 |
| A/B 比较 | baseline 与 variant 对比口径 | 窗口错位、统计摘要失真 |
| 产物渲染 | Markdown/JSON 可读性 | 报告缺字段、summary 不一致 |

### 5.2 市场状态矩阵

建议按以下市场状态分别抽样：

| 市场状态 | 目的 |
|----------|------|
| 趋势强化 | 验证 continuation 是否能抓住延续 |
| 震荡 | 检查 false breakout 是否回流 |
| 弱宽度 / 风险偏好下降 | 检查 guard 是否仍能抑制坏样本 |
| 单日脉冲后回落 | 检查 `t+1` 与 `t+2` 分布差异 |

### 5.3 样本结构矩阵

| 样本类型 | 代表意义 |
|----------|----------|
| `300505` | 当前最强 continuation candidate |
| `600988` | continuation lane 基准 eligible |
| `600989` | first near-cluster watch benchmark |
| 历史 recurring offenders | 验证 guard 是否失效 |
| baseline selected | 验证默认档未被副作用破坏 |

## 六、核心指标定义

### 6.1 逻辑与结构指标

| 指标 | 含义 |
|------|------|
| `window_count` | walk-forward 测试窗数量 |
| `tradeable_count` | 可交易样本规模 |
| `selected_count` / `near_miss_count` | 决策面宽度 |
| `lane_support_ratio` | continuation lane 支撑度 |
| `recent_support_ratio` | 个股近期支持度 |
| `effective_*_tickers` | 各治理层有效集合 |

### 6.2 收益指标

| 指标 | 含义 |
|------|------|
| `next_close_positive_rate` | T+1 收盘正收益率 |
| `t_plus_2_close_positive_rate` | T+2 收盘正收益率 |
| `next_close_return_mean` / `median` / `p10` | T+1 分布质量 |
| `t_plus_2_close_return_mean` / `median` / `p10` | T+2 分布质量 |
| `total_return_pct` | 窗口总收益 |
| `sharpe_ratio` / `sortino_ratio` | 风险调整后收益 |
| `max_drawdown` | 最大回撤 |
| `CVaR 95` | 极端尾部损失质量 |

### 6.3 风险质量指标

| 指标 | 用途 |
|------|------|
| 收益集中度 | 判断是否被单一 ticker 扛起 |
| executed trade days | 判断样本是否过少 |
| total executed orders | 判断交易面是否真实展开 |
| 非零 `layer_b` / `buy_order` 天数 | 判断漏斗是否恢复 |
| 失败原因分布 | 判断是阈值问题还是 veto 问题 |

## 七、推荐测试流程

### 阶段 1：快速回归

目标：先确认没有显式回归。

```bash
uv run pytest tests/screening/test_candidate_pool.py tests/screening/test_strategy_scorer.py tests/screening/test_phase2_screening.py -v
uv run pytest tests/backtesting/test_walk_forward.py tests/backtesting/test_compare.py tests/backtesting/test_rule_variant_compare.py -v
```

进入下一阶段条件：

- 无失败用例
- 无默认档字段漂移

### 阶段 2：continuation 治理回归

目标：确认 `300505` 的治理晋级链仍然成立，且仍然隔离于默认 BTST。

```bash
uv run pytest tests/test_generate_btst_tplus2_continuation_* -v
```

重点人工核查：

1. `300505` 是否仍在 watch / eligible / execution 三级有效集合中
2. `entry_type` 多条目是否保留
3. `capital_mode=paper_only` 是否未变

### 阶段 3：历史窗口 replay

目标：观察 baseline 与 continuation overlay 的方向性差异。

建议动作：

1. 先跑短窗
2. 再跑中窗
3. 再扩窗
4. 最后对重点 ticker / 重点窗做复盘文档

### 阶段 4：A/B walk-forward

目标：得到跨窗口统计，而不是单窗印象。

关注摘要：

1. `baseline_avg_sortino`
2. `mvp_avg_sortino`
3. `avg_sortino_delta`
4. `avg_max_drawdown`
5. 各窗口是否一致支持变体

### 阶段 5：收益质量复核

目标：防止“平均数改善，但实质不可用”。

必须回答：

1. 改善是广泛出现，还是集中在 1-2 个 ticker
2. 改善是 T+1 改善，还是只把收益挪到了 T+2
3. 改善是否伴随更差的回撤尾部
4. tradeable 扩容是否把历史 offender 又放回来了

## 八、通过 / 失败门禁

### 8.1 必须通过

以下任一项失败，都不应宣布“BTST 优化成功”：

1. 单元与回归测试失败
2. 默认 BTST 档位被 continuation 逻辑污染
3. continuation lane 失去 `paper_only` 隔离
4. A/B 比较中风险指标明显恶化
5. 收益改善主要来自单一窗口或单一 ticker

### 8.2 推荐升级门槛

只有同时满足以下条件，才建议把某个 continuation 结果继续向前推进：

1. L1-L4 全部通过
2. 多个 walk-forward 窗口中，B 组相对 A 组有稳定优势
3. `next_close` 或 `t+2_close` 的改善不是以明显更差的 `p10` 或回撤为代价
4. 失败样本复盘没有发现 recurring offender 大规模回流
5. 仍然保持“先 paper，再更高等级治理审批”的原则

### 8.3 明确禁止

以下情况应直接判定为**不可升级**：

1. 只凭 `300505` 单票表现就修改默认 BTST
2. 只看均值，不看分布和尾部
3. 把单窗结果外推为长期有效
4. 因为 continuation 表现好，就跳过默认档独立验证

## 九、失败排查路线

### 9.1 测试失败但产物还在

优先排查：

1. schema 是否变更
2. summary 字段是否新增或重命名
3. 默认 rulepack 与 effective overlay 是否混写

### 9.2 tradeable surface 异常扩张

优先排查：

1. threshold 是否被误放宽
2. `watchlist_zero_catalyst_*` guard 是否失效
3. heavy signal 限流与筛选裁剪是否被绕过

### 9.3 收益指标改善但回撤恶化

优先排查：

1. 是否只是把收益推迟到 T+2
2. 是否新增了少量高波动票
3. 是否出现集中度过高

### 9.4 continuation 候选消失

优先排查：

1. promotion gate / eligible gate / execution gate 条件是否漂移
2. 上游 watchboard / governance board 产物是否未刷新
3. 去重逻辑是否再次退回 ticker-only 模式

## 十、建议交付物清单

每轮正式验证结束后，至少保留以下产物：

1. 一份本轮测试配置说明
2. 一份 pytest 回归结果摘要
3. 一份 A/B walk-forward Markdown 报告
4. 一份 A/B walk-forward JSON 结果
5. 一份收益质量复盘文档
6. 一份失败样本或 offender 复盘文档
7. 一份最终结论：**保留 / 继续 paper / 回滚 / 待观察**

## 十一、执行建议

对当前系统，建议采用以下节奏：

1. **先守住默认 BTST**：继续把 `watchlist_zero_catalyst_guard_relief @ select=0.40 / near_miss=0.40` 作为稳定基线。
2. **把 continuation 当独立实验层**：围绕 `300505` 做 paper overlay 回放与 A/B 验证。
3. **优先看 walk-forward 与收益质量**：当前结构已经足够完整，下一阶段最重要的不是再加治理层，而是证明真实历史优势是否稳定。
4. **把单票成功转成多窗证据**：如果未来 `300505` 之外还能出现更多稳定 continuation 候选，再考虑更高等级的治理推进。

## 十二、最终判定模板

每轮验证建议用以下模板写结论：

```markdown
## 本轮判定

- 测试范围：
- baseline 配置：
- variant / overlay 配置：
- 关键窗口：
- 通过的回归：
- A/B 结果摘要：
- 收益质量结论：
- 风险质量结论：
- 最终建议：保留 / 继续 paper / 回滚 / 待观察
```

---

**当前建议结论**：
在当前阶段，应把 continuation 视为**结构已验证、收益待历史回归证实**的独立实验层。下一步最重要的工作不是修改默认 BTST，而是按本文计划完成多窗口 A/B walk-forward 与收益质量复核。
