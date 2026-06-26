# 模型打分质量调研 Design Packet（NS-4 倒挂根因调查）

**触发证据**: autodev C192 NS-4 (commit `2b69ad36`) 用真实 493 条 tracking_history
（50 日期 × ~10 只 A 股）验证模型**整体排序倒挂**：

| score bucket | T+30 胜率 | n |
|---|---|---|
| low (<0.30) | **50.5%** | 105 |
| mid_low (0.30–0.40) | 46.2% | 225 |
| mid_high (0.40–0.50) | 43.2% | 125 |
| high (≥0.50) | **39.5%** | 38 |

11pp **完美单调递减** —— 高分票（must-win 前门按 score 选的"最值得买"代表票）
真实 T+30 胜率反而最低。与 R-5.D 多时段诊断（3/5 时段亏钱）、R-5.F Phase 0
（MIXED 市场高分票 42% 最差）一致。

> **owner 决策范畴**：模型打分质量是赚钱工具的核心杠杆（Phase 0 STOP 裁决：
> "真杠杆 = 模型打分质量 + 真实数据累积"）。autodev **不越界改 factor / 权重 /
> 门控**（越界 = 过拟合）。本 packet 只负责 (1) 把根因假设列清，(2) 给出
> autodev 可自主执行的**只读诊断**菜单，(3) 列明 owner 须决策的语义分叉。
> 结论数据出来后由 owner 决定是否/如何改模型。

---

## 一、问题陈述（observable）

`--top-picks` 前门的 `composite_score`（`signal_fusion.compute_score_b`）在真实
T+30 收益上**反向预测**：score 越高 → 胜率越低。这意味着前门每天推给用户的
"最值得买"代表票，真实赢面比低分票还差。这是赚钱工具定位（产品目标 §一）
下不可接受的现状。

**症状是稳健的**：winrate 是 count-based（不受异常值污染，不像 mean —— low
bucket mean +575% 是少数极端赢家污染，但 winrate 50.5% 稳健）。11pp 单调递减
跨 4 个 bucket、493 条记录，非随机噪声。

---

## 二、根因假设（按可证伪性排序）

| # | 假设 | 类型 | 证伪方法 |
|---|---|---|---|
| H1 | **某策略因子贡献方向反了**（如 momentum 把"已涨"当看多，但 A 股短期反转效应下"已涨"反该看空；或 MR 符号错） | code bug（可修） | 调研方法 M1/M2：按 T/MR/F/E 策略贡献拆解 → 各策略 score→winrate 单调性 |
| H2 | **权重组合在当前市场反向**（如趋势权重过高但当前是震荡市，趋势票在震荡市亏） | owner 调优 | M3：按 state_type (TREND/RANGE/MIXED/CRISIS) 分组重复 M1，看倒挂是否集中在某 regime |
| H3 | **attention / consensus / stability bonus 放水**（高分票靠 bonus 堆上去而非真信号，bonus 是排序 tie-break 不是赢面信号，NS-11 已标同类） | code bug / 语义 | M4：用 pre-bonus `composite_score_gated` 重复 NS-4 单调性，对比 post-bonus |
| H4 | **样本时段偏差**（493 条集中在某段震荡/下跌市，那段时间高分会反向） | 数据范围 | M5：按 recommended_date 分段（如 2024 vs 2025），看倒挂是否特定时段；R-5.D 已显示胜率随时段 10%–100% 剧烈波动 |
| H5 | **模型本就是 mean-reversion 设计**（高分 = "该反转回调"，短期 T+30 必然回调） | 产品语义（非 bug） | owner 确认：MR 策略是定位核心吗？若是，"高分=该回调"是 by design，产品定位需重新表述 |

**优先级**: H1/H3 是可修 code bug（autodev 据证据可提修复提案，仍需 owner 确认
semantics）；H2/H4 是 owner 调优/数据范畴；H5 是产品定位决策。**先做 M1–M4 把
H1/H3 证伪或坐实**（最高 ROI），再据结论决定是否进 H2/H4/H5。

---

## 三、已排除项（不必再查）

- **价格复权污染**（NS-9 已 drain qfq，跨除权日假跳空已阻断）。
- **mock 数据注入**（NS-10 已翻 `use_mock_on_fail` 默认 False）。
- **NaN 进排序键**（NS-13 已 drain `_safe_metric` + 4 siblings）。
- **volume 死信号**（NS-12 已修 `_extract_volume_from_rec`）。
- **数据滞后**（NS-18(3) 已确认 agent 路径 D/E 已填充，非 must-win 问题）。

这些 data-quality bug 已排除，倒挂更可能在**因子语义/权重/bonus** 层（H1–H3）。

---

## 四、调研方法菜单（autodev 可自主，**只读不改 factor**）

> 全部是诊断模块，复用 `state_type_calibration` + `tracking_history` + NS-4 的
> `rank_monotonicity` 基础设施。输出到 `--top-picks` footer 或独立诊断报告，
> **不进排序、不改 gate、不改权重**。

### M1 — 策略贡献 × T+30 胜率（坐实/证伪 H1）
对每条 tracking_history 记录，用 `signal_fusion.compute_score_decomposition`
拆出 T/MR/F/E `base_contributions` + `attention_contribution` + `stability_bonus`
+ `consensus_bonus`。按**每个策略贡献分位**（如 momentum 贡献高/中/低）分组算
T+30 胜率。若某策略"贡献越高、胜率越低"→ 该策略方向可疑（H1 坐实）。

**前置依赖**: tracking_history 记录需带 decomposition 快照（当前可能只存了
`recommendation_score` 总分）。若未存，需在 NS-2 model_version payload 里补
decomposition 字段（向后兼容，旧记录该字段缺失 → 静默跳过）。**这是 owner 决策
点 D2**（是否同意扩展 tracking payload）。

### M2 — 单策略单调性（定位到具体因子）
对每个策略独立分 bucket（仅用该策略贡献排序），算 score→winrate 单调性
（复用 `rank_monotonicity` 的 verdict 逻辑）。哪个策略倒挂最严重 → 头号嫌疑。

### M3 — per-state_type 重复 M1/M2（坐实/证伪 H2）
按报告日 `market_state.state_type` (TREND/RANGE/MIXED/CRISIS) 分组重复 M1/M2。
若倒挂集中在 RANGE/MIXED → 震荡市趋势权重过高（H2，owner 调权）；若全 regime
倒挂 → 因子方向 bug（H1）。Phase 0 已有 per-state_type 基础设施。

### M4 — pre-bonus vs post-bonus 单调性（坐实/证伪 H3）
对比 `composite_score_gated`（pre-bonus，需 NS-11 落地才有此字段）与 post-bonus
`composite_score` 的 score→winrate 单调性。若 pre-bonus 单调而 post-bonus 倒挂 →
bonus 放水（H3，与 NS-11 同根）。**依赖 NS-11 owner 决策**（bonus 是否只用于排序
不喂 BUY gate）。

### M5 — 时段分段（坐实/证伪 H4）
按 recommended_date 分段（季度/月）重复 NS-4 单调性，输出倒挂是否特定时段。
R-5.D 多时段诊断已有先例（5 时段胜率 10%–100% 波动）。

---

## 五、owner 决策点（语义分叉，autodev 不能自决）

### D1 — 倒挂是 bug 还是 by design？（H5）
模型是否**有意**做 mean-reversion（高分 = 该反转）？
- **是 by design** → 产品定位需重述（"高分=该回调"对"选最能赚钱的股票"目标是
  矛盾的，需 owner 裁决定位）；T+30 horizon 可能太短（MR 票可能 T+60/T+90 才
  反转，NS-4 只测 T+30）→ 可加多周期胜率（T+10/20/30/60）看是否长周期单调。
- **是 bug** → 授权 autodev 进 H1/H3 修复（见 D3）。

### D2 — 是否同意扩展 tracking payload 存 decomposition？（M1 前置）
当前 tracking_history 只存总分。M1 需要每条记录的 T/MR/F/E 贡献分解。
- **同意** → autodev 加 decomposition 字段到 payload（NS-2 model_version 一起），
  新记录开始累积，~30 天后有样本跑 M1。
- **不同意** → M1 无法做，退回 M2/M3/M5（用总分近似）。

### D3 — 若 M1/M2 坐实某因子方向 bug，授权修复吗？（H1）
修因子符号是**改 factor semantics**，change_risk 高（blast_radius=3，影响所有
打分/排序/BUY 门控），且可能与 owner 的因子设计意图冲突。
- **授权** → autodev 出修复提案 + design packet（两选项：翻符号 / 降权重），
  owner 二次确认后实施。
- **不授权** → autodev 只报告，owner 自行调。

### D4 — NS-11 (bonus 喂 BUY gate) semantics 确认（M4 前置）
consecutive bonus / consensus bonus 应只用于排序 tie-break，还是也喂 BUY 门控？
（NS-11 backlog 已标"建议 owner 确认 semantics"）。
- **只排序** → autodev 实施 `composite_score_gated`（pre-bonus 喂 gate），解锁 M4。
- **也喂 gate** → M4 无法做，H3 证伪路径关闭。

---

## 六、推荐执行顺序（owner 选一个起点）

1. **最快证伪**: 先做 **M5（时段分段）+ M3（per-regime）** —— 用现有总分数据，
   无需 payload 扩展，~1 个 autodev campaign 可出。回答"倒挂是全市场还是特定
   regime/时段"（H2/H4）。
2. **若需深挖因子**: owner 决策 D2（payload 扩展）→ 累积数据 → M1/M2 定位
   具体策略（H1）。
3. **若怀疑 bonus**: owner 决策 D4（NS-11 semantics）→ M4 证伪 H3。
4. **产品定位**: owner 决策 D1（MR by design?）→ 决定是否加多周期胜率。

---

## 七、边界（autodev 不越界）

- **不改 factor 权重 / 符号 / 门控**（Phase 0 STOP: 越界 = 过拟合，且属 owner
  调优范畴）。
- **不修 NS-4 倒挂本身** —— NS-4 只让问题可见；本 packet 只给调研方向。
- **诊断模块只读**：输出到 footer / 报告，不进排序，不改仓位。
- **realized value 须 owner 操作**: 即便诊断出根因，"用户按推荐操作 30 天
  P&L>0"（北极星）需 owner 据诊断改模型 + 累积真实数据验证。

---

## 八、关联

- NS-4 倒挂发现: `src/screening/rank_monotonicity.py` (commit `2b69ad36`),
  memory `autodev-session-20260627-c192-ns4-rank-monotonicity`。
- 因子分解: `signal_fusion.compute_score_decomposition`（T/MR/F/E + attention
  + stability + consensus）。
- 诊断基础设施: `state_type_calibration` (per-regime), `rank_monotonicity`
  (单调性 verdict), `regime_winrate` (regime 胜率)。
- 数据: `data/reports/tracking_history.json`（493 条，50 日期，含
  `recommendation_score` + `next_30day_return` + 多 horizon return）。
- 待 owner 决策的 backlog: NS-11 (bonus semantics), NS-6 (因子归因，本 packet
  的 M1/M2 即其展开), NS-2 (model_version, D2 payload 扩展载体)。
