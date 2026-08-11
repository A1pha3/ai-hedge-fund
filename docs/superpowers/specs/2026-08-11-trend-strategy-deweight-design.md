# trend 策略降权设计（对抗审查 + 无偏实验后的化简方案）

**日期**: 2026-08-11
**状态**: 设计待审
**性质**: 一个被对抗审查从"两阶段大工程"化简为"单因子降权"的方案

## 0. 本 spec 取代了什么

本文件取代同日早先的 `2026-08-11-two-layer-factor-vocabulary-unification-design.md` 的方向。那个方向（两层因子词汇统一 + 审计器扩展 + 二维交互 + 融合 + kelly 去耦）经独立子代理对抗审查 + 两轮无偏实验后被否决。否决证据记录在 §5，供未来审计者参考，避免重走。

## 1. 问题（经无偏验证）

生产 `score_b` 的趋势策略 `trend` 占默认权重 **0.40（最大）**，但它在涨停候选日（BTST 主战场，理论上 trend 最该有效的域）**无前向预测力**：

| 验证（全 universe 涨停候选日，n=13762，exec 测度，无选择偏差） | 结果 |
|---|---|
| Spearman(trend_conf, T+10) | −0.0318（无 IC，五分位 WR 42-45% 不分离） |
| 跨窗 | H1 −0.111 / H2 +0.007 **不一致**（弱信号不稳定） |
| long(+1) 子集内部 (n=11647) | ρ=−0.0203，跨窗不一致（85% 的票上 trend 无贡献） |
| short(−1) 子集 (n=2115) | WR 53.6%（**真信号，不能动**） |

数据来源：`data/reports/trend_gate_unbiased_experiment.json`（脚本 `scripts/trend_gate_unbiased_experiment.py`，全 universe price_cache，截止涨停日切片无 look-ahead，特征契约=生产 `score_trend_strategy`）。

## 2. 决策：降权，不翻转，不融合

**降权 trend（0.40 → 接近 0），不动 direction/multiplier，不扩展审计器，不融合。**

理由（第一性原理）：
- **降权无预测力因子是零风险单调改善**——去掉噪声，让有 IC 的因子（fundamental/MR/strength gate）归一化后权重大。`_normalize_active_weights`（signal_fusion.py:77）安全处理权重归一，与 weekday/streak 当年移出 strength 同构。
- **翻转是错的**：long 内部 ρ 弱且跨窗不一致，任何方向翻转都不稳健；且会污染 short 子集的 53.6% 真信号。重蹈 NS-4 盲翻转覆辙（models.py:120 注释："翻转应在 generator 层而非 multiplier 层盲反转"）。
- **不需要 A/B 验证降权**：A/B 是为有风险的翻转准备的。降权一个已证无 IC 的因子不需要对照——它不会让任何东西变差。

## 3. 执行

1. **`DEFAULT_STRATEGY_WEIGHTS`（models.py:97）trend 0.40 → 0.0**（先置 0 最干净；如需保留趋势作为 metadata 观测可留极小值如 0.05，但默认置 0）。
2. **锚定测试**：`test_signal_fusion.py` 加守卫——trend weight=0 时 score_b 计算正常、归一化后 fundamental/MR/event 权重正确放大、不抛错。
3. **empirical dogfood 回测**：跑一次 `--auto` 历史日期，确认 score_b Top-N 排序变化方向合理（无 trend 主导后，排序应由 fundamental/MR 决定），不退化。
4. **不动**：direction 逻辑、multiplier（全 1.0）、审计器、gate、kelly、daily_action 路径。

## 4. 验收

- trend 置 0 后，offensive 套件（3441）+ btst（25）全绿，不退化。
- 锚定测试覆盖 trend=0 的 score_b 归一化。
- dogfood 回测 score_b Top-N 不出现异常（如全 0 分、全同分、排名坍缩）。

## 5. 被否决方案的否决证据（供未来审计者）

早先方向："两层因子词汇统一"——基于"两层断层是问题"。被否决：

1. **候选宇宙混淆（最致命）**：动机证据 "+3.55% vs −1.19%" 来自**不同候选宇宙**（+3.55% 是 BTST full_market detect 路径 v2 trades，−1.19% 是 --auto 推荐池 score_b Top3）。"同炉对照"无效（daily_action.py:8/319/259 铁证）。"正收益来自 gating/反向来自 trend"归因不成立。
2. **score_b 非系统性反向**：全推荐池 mean +4.19%（正），Q5 五分位 +1.04%（仍正！），仅 Top10% −1.53%。非单调倒 U = 校准问题，非"Layer2 词汇反向"。
3. **"trend 反向"非选择偏差伪象也非真反向**：全 universe 实测是无 IC（不是 MR 式全 universe 正 IC）。早先的"剔除 trend 前提"方向对，但"需要统一审计+融合"的工程量被夸大。
4. **权重措辞误导**：早先 spec 的 trend 0.56 是 08-10 单日 regime-adjusted 快照，非 DEFAULT(0.40)。
5. **gate 已有效**：gate 同池增量 alpha Wilson 分离 True（+2.38pp），不需要"融合进 score_b"。

**方法论教训**：作者自我审查保护了核心假设（"断层是问题"），独立子代理无此偏误才抓到候选宇宙混淆。empirical 无偏实验（70 秒全 universe scan）> 有偏样本推断 + 静态 spec 推理。
