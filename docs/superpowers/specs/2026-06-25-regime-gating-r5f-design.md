# R-5.F 设计：state_type 条件化 BUY 门控（regime-conditional front-door gate）

- **日期**：2026-06-25
- **状态**：已对齐，待 owner review → 进实现计划
- **关联**：R-5.F（`docs/cn/product/feature-proposals.md` §三·5）、R-5.A（regime 胜率披露）、R-5.C（calibration 校准）、R-5.D（多时段诊断）、R-5.E（tracking_history 回填）
- **北极星指标**：用户按推荐操作 30 天后的真实 P&L > 0
- **不可违背纪律**：Phase 0 诊断（含留一时段样本外验证）是 R-5.F 走哪条分支的唯一裁判；诊断结论出来前不动 gate 代码

---

## 一、背景与动机

### 1.1 真实回测揭示的核心矛盾

`docs/cn/product/feature-proposals.md` §三·5 的真实回测证据（v2，32 日期 ~189 只真实推荐 + tushare 真实 T+30）：

- 按 `regime_gate_level` 分组：normal 43% / crisis 47% / risk_off 30% 胜率，median 都微亏到平 → **regime_gate_level 区分度弱**
- R-5.D 多时段诊断（14 日期 91 只）：2025 春震 15% / **2025 夏 100%** / 2025 秋 10% / 年末 60% / 2026 春 32% → **胜率由"上涨 vs 震荡"驱动**，不是由"危机 vs 不危机"驱动

**矛盾**：产品定位"最优秀赚钱工具 / 每天选最能赚钱的股票"，但真相是震荡市（占多数时段）推荐典型票微亏。当前 `top_n=10` 固定档位 = 在震荡市让用户买 10 只亏钱票。

### 1.2 owner 意图（本设计的产品语义来源）

owner 明确：**震荡市不一刀切禁买**——震荡市也有结构性强势板块/股票，应换一套更适合震荡市的标准把那一小撮"震荡市也能涨"的票挑出来，而不是全杀。同时 owner 已确认纪律：诊断优先 + 样本外验证，避免重蹈 v1/v2"看迹象就动手"→ 过拟合的覆辙。

### 1.3 关键代码事实（探索结论，决定设计形态）

R-5.F **不是"造一个 gate"**，而是"把已有的 gate 换到正确的信号轴上"：

| 事实 | 位置 | 含义 |
|---|---|---|
| BUY/HOLD/AVOID gate 已存在 | `src/screening/investability.py:147` `build_front_door_verdict()` | 机制已在，只需改分支条件 |
| gate 已做 regime 门控 | 同上：`if "crisis"/"risk_off" in regime: HOLD/AVOID` | 危机场已禁 BUY；缺口在 normal 内部不区分上涨/震荡 |
| 正确的信号轴已算好 | `src/screening/market_state.py` `state_type` ∈ {TREND, RANGE, MIXED, CRISIS} | TREND 判定 = `ADX>30 且 atr_ratio<0.012 且 breadth≥0.52`，即"全面上涨市"定义，对应 R-5.D 100% 胜率时段 |
| gate 挂在错误轴上 | 现用 `regime_gate_level`（normal/crisis/risk_off） | 把上涨+震荡都塞进 normal → v2 显示无区分度 |
| MARKET GATE 展示块已存在 | `src/screening/top_picks.py:93` `_render_market_gate()` | 展示 seam 已在 |
| regime 胜率数据基础已存在 | `REGIME_HISTORICAL_WINRATES`（R-5.A） | 可从 regime_gate_level 维度扩展到 state_type×bucket |

---

## 二、目标 / 非目标

### 目标
1. 让 `--top-picks` 的 BUY 门控按 `state_type` 条件化：TREND 正常推；RANGE/MIXED 只放过"震荡市历史也证明能赚"的少数票（若诊断支持），否则禁 BUY + 砍数量。
2. 震荡市在 MARKET GATE 块诚实告知用户当前市场状态与推荐稀少的理由（"不亏也是赚"）。
3. 全程诊断优先：用留一时段样本外验证决定 gate 形态，不 in-sample fit。

### 非目标（YAGNI，明确不做）
- ❌ 实时 intraday gate（日级 `detect_market_state` 够用）
- ❌ 新增多 index 风格分散信号（`style_dispersion` 已有）
- ❌ 涨停封板率/连板数等新指标（`limit_list` 现有用量够）
- ❌ **gate 内做因子权重切换**——owner 正在调因子（mean_reversion/MR 权重/trend 阈值），gate 只管"推不推/推几张"的门控，不管"因子权重"，职责正交分离，避免与 owner 工作撞车
- ❌ 改打分模型本身提高震荡市胜率（R-5.D 已否决，过拟合风险）

---

## 三、总体架构（三阶段，诊断是裁判）

```
Phase 0 诊断（只读，强制前置）
   回算每个历史报告日的 state_type → 按 state_type 分组算 T+30 胜率
   回答 3 个问题（含留一时段样本外验证）
        │
        ▼
诊断结论 ── 决定 Phase 1 走哪条分支 ──────────┐
   三问都 yes ─→ Phase 1A: regime-conditional 精选
                  (震荡市用 state_type×bucket 历史胜率做更严门控，放过少数票)
   只问1 yes ──→ Phase 1B: 震荡市禁 BUY + 砍到 top-3 (保守版)
   问1 也 no ──→ 停。诚实报告 state_type 也不 discriminative，R-5.F 不做
                                              │
Phase 2 展示（1A/1B 共用）◄─────────────────────┘
   震荡市 MARKET GATE 块告知"今天震荡，仅 N 只通过严选 / 今天没有值得买的票"
```

---

## 四、Phase 0 诊断详细设计

### 4.1 输入
- **推荐样本**：R-5.E 已回填的 ~189+ 只真实推荐（`tracking_history` / `auto_screening` 历史报告），含每只的 `score_b` / `composite_score` / 报告日期 / bucket
- **真实 T+30**：tushare 前复权真实收益（R-5.E/R-7 管线已就绪）
- **state_type 回算**：对每个历史报告日调用 `detect_market_state(date)` 取 `state_type`。`detect_market_state` 是日级的，依赖 CSI300 OHLC / breadth / limit_list / daily_basic / northbound，均为 tushare 日级历史数据，**回算可行**。

### 4.2 一次性诊断脚本
- 路径：`scripts/_diag_state_type_winrate.py`（`_` 前缀 = 一次性诊断，惯例同 `_r5a_regime_winrate.py` / `_backtest_light_stage_universe.py`，诊断完结论沉淀进产品文档后可删）
- **三问**：
  1. **总体区分度**：`state_type=TREND` 日推荐 vs `RANGE/MIXED` 日推荐，T+30 胜率与 median return 是否**显著**差异（报告样本量 n、胜率、median、简易置信区间）
  2. **震荡市赢面子集**：在 RANGE/MIXED 子集内部，按 score bucket（与现有 calibration bucket 一致）和/或因子特征（momentum_bonus / sector_bonus 符号等）细分，是否存在胜率**明显**高于震荡市平均的子集
  3. **样本外稳健性**：对问题 2 找到的子集做**留一时段法**（leave-one-period-out：每次留出一段日期，用其余日期"发现"子集规则，在留出日期上验证胜率是否仍高）。32 日期边缘，必要时用留出整段（如留出某个月）而非单日
- **样本量诚实约束**：任何子集 n < 预设下限（建议 n≥20 同 R-5.A BUY 门控）直接标"证据不足"，不强行下结论。所有胜率同时报告 median（防异常值污染，R-6/R-7 教训）。
- **输出**：诊断报告（JSON + 控制台摘要），三问各 yes/no + 数字证据。报告路径 `outputs/diag_state_type_winrate_<date>.json`。

### 4.3 诊断脚本的正确性自验
- 用**已知分布的合成数据**单测留一时段法逻辑：构造一组"已知某 bucket 在震荡市胜率高"的合成样本，验证脚本能正确识别；构造"无差异"样本，验证脚本能正确返回 no。**不能拿错的统计得出结论**。

---

## 五、Phase 1 gate 设计（改一个函数的分支）

### 5.1 改动点
`src/screening/investability.py:147` `build_front_door_verdict()`。现有 `crisis/risk_off` 分支**保留不动**，新增 `state_type` 条件化逻辑。

### 5.2 分支 1A（诊断三问都 yes → regime-conditional 精选）
- 新增数据：`STATE_TYPE_BUCKET_WINRATES`（`REGIME_HISTORICAL_WINRATES` 的扩展：从 `regime_gate_level` 整体维度 → `state_type × score_bucket` 维度）。诊断脚本产出此表，落库供 gate 查询。
- RANGE/MIXED 时，BUY 额外要求：该票所在 `state_type × bucket` 的历史 T+30 胜率 > 阈值（阈值由诊断给出，初版用保守值如 0.50，即震荡市只放"震荡市历史至少五五开"的票）。
- TREND 时：维持现有 BUY 门控（不加额外约束）。

### 5.3 分支 1B（诊断只支持问1 → 保守版）
- RANGE/MIXED 时禁 BUY（action 强制 HOLD/AVOID），`top_picks` 展示数量从 top-10 砍到 top-3，显眼标注"市场震荡，仅观察"。
- TREND 时：维持现有。

### 5.4 特征开关 / 回滚
- 环境变量 `R5F_GATE` ∈ {`on`, `off`}，默认 `on`。`off` 时完全回到现有 `regime_gate_level` 行为。
- gate 逻辑用纯函数实现（输入：recommendation + market_state + state_type_bucket_table → action），便于单测与一键回滚。

### 5.5 失败降级
`detect_market_state` 失败（数据缺失/异常）→ `state_type` 取不到 → gate 降级 `unknown`，保持现有行为（不阻断推荐），打印警告。复用 `_render_market_gate` 已有的异常处理 seam（`top_picks.py:104-113`）。

---

## 六、Phase 2 展示设计

`--top-picks` 顶部 MARKET GATE 块（`_print_market_gate_regime_advice`）扩展 state_type 分支：
- **TREND**：`✓ MARKET GATE: 上涨市 (TREND) — 正常筛选，关注 BUY 代表票`
- **RANGE/MIXED**：`⚡ MARKET GATE: 震荡市 (RANGE/MIXED) — 仅 N 只通过震荡市严选标准。不亏也是赚。`（1A）；或 `⚡ 震荡市 — 仅观察 top-3，不建议新建仓位`（1B）
- **CRISIS**：保留现有危机提示
- 0 只通过严选时：`今天没有值得买的票 — 空仓也是赚钱的一部分`

---

## 七、测试策略

- **TDD RED→GREEN**：gate 纯函数各分支（state_type × 票质量 × bucket 胜率 组合）合成数据单测；诊断统计函数（含留一时段法）已知分布合成数据单测
- **回归**：`tests/screening/` + `tests/test_top_picks.py` + investability 相关测试全绿（owner 因子改动后基线：screening 1683 + top_picks/technicals/scorer/fusion 293 全绿）
- **诊断脚本自验**：见 4.3
- **不写**：依赖真实 tushare 数据的硬编码断言（数据会变）；改为统计逻辑单测

---

## 八、决策权威矩阵

| 决策 | 权威 | 说明 |
|---|---|---|
| gate 在震荡市的行为形态（1A 精选 vs 1B 禁买） | **诊断数据** | 不是 owner 拍脑袋，是 Phase 0 结论决定 |
| 诊断三问的阈值（显著差异定义、bucket 胜率门槛） | 工程（我定） | 基于样本量与置信区间，诊断脚本内可调 |
| state_type 作为信号轴（vs 新建信号） | 工程（已定） | R-5.D 支持 + 复用现有 market_state |
| 震荡市是否一刀切 | owner（已定） | 不一刀切，找结构性机会（本设计 1A 优先） |
| 特征开关默认 on/off | 工程（默认 on，可回滚） | |

---

## 九、诊断结论 → 行动 映射（防止实现时跑偏）

| 诊断问1 | 诊断问2 | 诊断问3 | 行动 |
|---|---|---|---|
| yes | yes | yes | **Phase 1A** regime-conditional 精选（owner 偏好路径） |
| yes | yes | no | 震荡市赢面子集是 in-sample 假象 → **Phase 1B** 保守版 |
| yes | no | — | 震荡市无赢面子集 → **Phase 1B** 保守版 |
| no | — | — | state_type 也不 discriminative → **停**，诚实报告，R-5.F 不做 |

---

## 十、与 owner 当前工作的关系

owner 近期手动调因子（mean_reversion 方向/MR 权重 0.35→0.65/trend 阈值松绑，commits `ab96aae0`/`aff989be`/`0e365cdc`/`510952fe`/`e5406887`）。本设计与这些**正交**：owner 调"因子权重"（让模型更敏感），R-5.F 调"门控"（让产品在震荡市更克制）。两者方向一致（都为赚钱工具真赚钱），互不污染。owner 的因子改动会让 score 分布变化，因此 **Phase 0 诊断应基于因子改动后的最新模型推荐样本**（或明确标注诊断所用的模型版本）。

---

## 十一、开放项（实现时确认，非阻塞）

1. 留一时段法的"时段"粒度（单日 vs 整月）——取决于样本分布，诊断脚本探查后定
2. `STATE_TYPE_BUCKET_WINRATES` 的落库形式（嵌入常量 vs JSON 文件 vs calibration 表扩展）——Phase 1A 实现时按现有 calibration 基础设施选最一致的
3. 震荡市 top-3 的"3"是否动态（按 score gap 自动截断）——1B 实现时定，初版固定 3
