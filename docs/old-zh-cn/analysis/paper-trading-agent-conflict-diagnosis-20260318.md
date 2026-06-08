# 2026-03-18 Agent 级冲突诊断：关键近端落选者是否属于可安全释放样本

## 结论摘要

- 本轮对关键日期近端落选者的 agent 级贡献做了逐票检查。
- 结论是：大多数样本并不是“只差一点就该放行”的边缘票，而是稳定的结构性冲突票。
- 这些样本普遍具有三个特征：
  - `bc_conflict = b_positive_c_strong_bearish`
  - `decision = avoid`
  - `top_negative_agents` 中重复出现同一批负向 agent，尤其是 `valuation_analyst_agent`，其次是 `sentiment_analyst_agent`，再叠加若干稳定看空的 investor persona
- 因此，下一步不应为了提升利用率而直接放宽 `avoid` 或 Layer C 抑制，否则很容易把结构性冲突票整体放出来。

## 分析对象

数据来源：

- [ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl](ai-hedge-fund-fork/data/reports/paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317/daily_events.jsonl)

聚焦样本：

- `20260225`: `300724`, `000960`
- `20260226`: `300724`, `000960`, `600988`
- `20260227`: `000960`, `600988`
- `20260303`: `300251`, `002602`
- `20260304`: `300775`, `600111`, `300308`, `000426`, `300251`

分析目标：

- 判断这些样本是边缘 watch 样本，还是结构性被压制样本
- 识别负贡献主要来自 investor cohort、analyst cohort，还是两者同时明显为负

## 基准对照

当前 Layer C 默认参数见 [ai-hedge-fund-fork/src/execution/layer_c_aggregator.py](ai-hedge-fund-fork/src/execution/layer_c_aggregator.py)：

- `LAYER_C_INVESTOR_WEIGHT_SCALE = 0.90`
- `LAYER_C_BEARISH_INVESTOR_CONTRIBUTION_SCALE = 0.15`
- `LAYER_C_BLEND_B_WEIGHT = 0.55`
- `LAYER_C_BLEND_C_WEIGHT = 0.45`
- `LAYER_C_AVOID_SCORE_C_THRESHOLD = -0.30`

这说明当前系统已经不是原始最保守版本，而是经过一次偏边缘样本友好的 Layer C 放松后得到的结果。即便如此，下述样本仍被稳定压制。

## 逐类样本诊断

### 1. 300724：当前规则下属于边缘 watch 样本，不属于结构性冲突票

代表日期：`20260225`、`20260226`

特征：

- `decision = watch`
- `bc_conflict = null`
- `score_final` 分别为 `0.2019`、`0.2250`
- `cohort_contributions` 约为：`investor` 轻微正、`analyst` 轻微负

代表性负向 agent：

- `sentiment_analyst_agent`
- `valuation_analyst_agent`
- `michael_burry_agent`

解释：

- `300724` 不是结构性被压成 `avoid` 的类型。
- 它更像一个边缘 watch 样本，只是当时分数不足或被 re-entry 规则拦下。
- 这进一步说明：本轮修复命中的对象本身没有被 Layer C 结构性否决。

### 2. 000960：稳定的 investor-led 结构性冲突样本

代表日期：`20260225`、`20260226`、`20260227`

共同特征：

- `decision = avoid`
- `bc_conflict = b_positive_c_strong_bearish`
- `score_final` 约 `0.1893 ~ 0.1964`
- `cohort_contributions` 中 `investor` 始终明显为负，约 `-0.0565 ~ -0.0606`
- `analyst` 贡献接近零或小幅正负摆动

稳定重复的负向 agent：

- `valuation_analyst_agent`
- `fundamentals_analyst_agent`
- `bill_ackman_agent`

解释：

- `000960` 的问题不是“差一点过线”，而是 investor cohort 本身持续看空。
- 它连续三天都呈现同样结构，说明这不是瞬时噪声。

### 3. 600988：investor 与 analyst 双负的结构性冲突样本

代表日期：`20260226`、`20260227`

特征：

- `decision = avoid`
- `bc_conflict = b_positive_c_strong_bearish`
- `score_final` 约 `0.1686 ~ 0.1687`
- `cohort_contributions` 中：
  - `investor` 约 `-0.0456 ~ -0.0481`
  - `analyst` 约 `-0.0497`

稳定重复的负向 agent：

- `valuation_analyst_agent`
- `sentiment_analyst_agent`
- `bill_ackman_agent`

解释：

- 这是更强的结构性冲突票，因为 investor 和 analyst 两侧同时明显为负。
- 这种票不适合被当作“为了补利用率就应释放”的对象。

### 4. 300251 与 002602：强 investor-led 结构性冲突样本

代表日期：`20260303`

`300251`：

- `score_final = 0.1735`
- `investor = -0.0839`
- `analyst = -0.0430`
- `negative_agent_count = 14`

`002602`：

- `score_final = 0.1533`
- `investor = -0.0674`
- `analyst = -0.0667`
- `negative_agent_count = 12`

重复负向 agent：

- `valuation_analyst_agent`
- `sentiment_analyst_agent`
- `bill_ackman_agent` 或 `ben_graham_agent`

解释：

- 这两只票都不是边缘样本，尤其 `300251` 的 investor 负贡献已经很深。
- 如果为了提升利用率而整体放松 avoid，极可能把这类高冲突样本一起放出来。

### 5. 20260304 的四个近端样本：绝大多数仍是结构性冲突票

#### 300775

- `score_final = 0.2215`
- `investor = -0.0653`
- `analyst = -0.0214`
- 负向 agent 仍以 `valuation_analyst_agent`、`sentiment_analyst_agent`、`bill_ackman_agent` 为主

判断：investor-led 结构性冲突票。

#### 600111

- `score_final = 0.2145`
- `investor = -0.0720`
- `analyst = -0.0020`

判断：非常典型的 investor-led 结构性冲突票。

#### 300308

- `score_final = 0.1815`
- `investor = -0.0574`
- `analyst = -0.0314`

判断：双负结构性冲突票。

#### 000426

- `score_final = 0.1786`
- `investor = -0.0043`
- `analyst = -0.0981`

判断：这是一只少见的 analyst-led 冲突票，不是 investor-led，但仍不是边缘样本。

解释：

- `000426` 是一个重要例外，它提醒我们：并非所有落选者都由 investor cohort 主导压制。
- 但即便如此，它仍然属于明显负向的 analyst-driven 冲突样本，也不适合被轻易释放。

## 综合模式识别

从这些关键日期样本看，重复出现的模式非常稳定：

1. `valuation_analyst_agent` 几乎是所有强冲突票的头号负向贡献者
2. `sentiment_analyst_agent` 经常排在第二位
3. investor 侧反复出现的负向 persona 包括：
   - `bill_ackman_agent`
   - `ben_graham_agent`
   - `michael_burry_agent`
4. 多数票的 `negative_agent_count` 在 `9 ~ 15` 之间，不是轻微分歧，而是明显多数共识为负

这说明：

- 当前关键近端落选者大多不是“一个阈值问题”
- 而是“多个 agent 同时给出负面意见，被 Layer C 合理压制”的结果

## 业务判断

基于本轮 agent 级诊断，可以给出更强的判断：

- 目前关键日期的近端落选者，以结构性冲突票为主，不是安全的边缘补位样本池
- 因此，若单纯为了提高利用率而继续降低 watchlist 门槛、减弱 avoid 规则、或放松 Layer C 冲突判定，风险较高
- 这类改动很可能不是“补一些健康替代票”，而是“把当前被多数 agent 否决的票整体放出来” 

## 当前最合理的下一步

下一步最合理的方向不是直接做全局放宽，而是先做更精细的样本筛选：

1. 找出是否存在像历史 `600519` 一样的真实边缘样本
2. 只对这类边缘样本验证最小化释放条件
3. 将 `000960`、`600988`、`300251`、`300775`、`600111`、`300308`、`000426` 这类结构性冲突票明确排除出首轮放宽目标

## 当前结论

截至 `2026-03-18`：

- `300724` 是被 re-entry 规则正确拦下的边缘 watch 样本
- 但它之后缺失的替代票并不是一批“本该放出来”的健康候选
- 关键近端落选者大多属于稳定的结构性冲突样本
- 因此，下一阶段应该优先寻找新的边缘样本，而不是尝试整体放宽当前的 Layer C / avoid 抑制