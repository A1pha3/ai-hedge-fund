# BTST：Regime-aware Gap Overlay（2026-06-02）

## 0. 目标与定位
**目标**：把 202605 复盘中最强的“可执行风险源”之一——**开盘负跳空（gap down）**——落地为可审计、可回放、可逐步 rollout 的 **Soft Overlay（报告/执行清单层提示）**，优先提升 **次日收盘胜率**，同时尽量不明显恶化 5D/+15% runner 目标。

**定位**：
- v1 只改“报告/执行清单层语义”（人执行规则），不直接改交易引擎执行逻辑。
- v2 才考虑自动化 enforcement（需开盘价数据源 + 更严格的集成测试/回测验证）。

## 1. 问题复盘（202605 high_confidence top5/day）
在 202605 的 top5/day（high_confidence）样本上：
- 次日收盘 win_rate（next_close_return>0）约 **54%**（不算灾难，但不稳定）
- 5D/+15% hit-rate（max_high_t1_t5_from_open>=0.15）约 **27%**，显著低于系统目标（5D 内 55% 概率达到 +15%）
- 关键结构性拖累：**gap < 0 的样本次日胜率显著更差**，且对整体分布有决定性影响

结论：gap down 属于“交易可控”的主要风险源，可用 overlay 显著改善次日胜率。

## 2. 定义：Gap Overlay 反事实（Counterfactual）
- gap 定义：`next_open_return = (T+1 open / T close) - 1`
- 规则：对既有选股样本做反事实筛选
  - keep if `next_open_return >= cutoff`
  - 示例：cutoff = -0.5% 表示 **允许小幅低开**，但过滤更深的负跳空

### 2.1 202605 反事实结果（整体）
基于既有复盘统计（high_confidence top5/day，ok 样本 n≈90）：
- baseline：win_rate≈54.4%，hit_5d_15≈26.7%
- 仅保留 gap>=-0.5%：样本数约减半（n≈43），但 win_rate≈72.1%，hit_5d_15≈25.6%（基本不变）

**解释**：`-0.5%` 在“显著提升次日胜率”与“尽量不恶化 5D hit-rate”之间，提供了较好的折中，但会牺牲大量交易机会（这是预期代价）。

## 3. 为什么必须 Regime-aware（按市场门控分桶）
仅靠 gap overlay 无法在“坏行情月”彻底修复胜率结构。
因此 v1 推荐口径：
1) 先看 **regime gate**（市场门控：risk_off/crisis/halt 等）
2) 在允许交易的 regime 中，再用 gap overlay 做“过滤/减仓/确认性复审”

本次已补齐“可验证的按 regime 分桶评估能力”，用于证明：gap overlay 的收益主要来自 normal / crisis 桶，而 risk_off 桶应直接降级（观察或空仓）。

## 4. 落地内容（已实现，report-only）
### 4.1 月度 scorecard 支持 regime 分桶（用于证据/回放）
脚本：`scripts/analyze_btst_monthly_scorecard.py`
- 新增参数：`--daily-events-root <path>`
- 从 `paper_trading_*_plan/daily_events.jsonl` 解析 `current_plan.market_state.regime_gate_level`
- 输出：
  - `overall.regime_gate_day_counts`
  - `overall.regime_gate_buckets`
  - `overall.regime_gate_gap_overlay_counterfactual`（按 regime 的 gap 反事实）

### 4.2 报告层 guardrail（premarket card + next-day trade brief）
新增“Global Guardrails”文案（不改引擎）：
- risk_off：默认不做正式买入，仅观察/确认性复审；无修复信号则空仓
- crisis/halt：按门控降级执行，仅确认后小仓或空仓

这能把“市场门控 + gap overlay”的执行语义，稳定呈现在日常产物里，避免交易员误把 bad-regime 当 normal。

## 5. 如何复现与生成证据（建议流程）
> 注意：`--daily-events-root` 需要你本机有 paper trading 的 plan artifacts（包含 `daily_events.jsonl`）。这些通常来自真实运行/回放产物，不一定在 repo 里被追踪。

### 5.1 生成 202605 月度 scorecard（含 regime 分桶）
```bash
uv run python scripts/analyze_btst_monthly_scorecard.py \
  --month 202605 \
  --reports-dir data/reports \
  --top-n 5 \
  --gap-cutoffs -1.0%,-0.5%,-0.3%,0% \
  --daily-events-root <YOUR_DAILY_EVENTS_ROOT>
```

### 5.2 判读口径
- 先看 `overall.regime_gate_day_counts`：risk_off/crisis/halt 各自样本规模
- 再看 `overall.regime_gate_gap_overlay_counterfactual`：
  - normal/crisis：gap>=-0.5% 通常显著改善次日 win_rate
  - risk_off：样本少但往往胜率极差，应优先“降级执行/空仓”，不要用 gap overlay 试图硬修复

## 6. v1 推荐执行语义（Soft Overlay）
以 `gap>=-0.5%` 作为默认提示阈值：
- 若 gap < -0.5%：标记为 **confirmation_only / reduced posture**（确认性复审 + 减仓/不做正常开盘买）
- 若 regime_gate_level == risk_off：优先 **空仓观察**，除非出现明确修复信号

## 7. 后续路线（alpha/beta/gamma 分工）
- alpha（因子/统计/过拟合防控）：
  - 扩展样本窗（跨月、样本外）验证 gap overlay 与 regime 分桶稳健性
  - 给出“阈值与 kept-rate 的稳定区间”，避免只在 202605 过拟合
- beta（执行/微观结构/系统）：
  - 若进入 v2（自动化 enforcement），需要接入开盘价可信数据源与集成测试
  - 明确 size_discount/blocked 的执行语义与 reason_code
- gamma（风险预算/门控/rollout）：
  - 给出 risk_off/crisis/halt 的组合层降级模板（仓位上限、禁入条件、回撤闸门）
  - 定义 rollout 与回滚策略（off/report/enforce 三级开关）

## 8. 变更索引（便于 code review / 回滚）
- `scripts/analyze_btst_monthly_scorecard.py`：新增 `--daily-events-root` + regime buckets + 分 regime gap overlay 反事实
- `src/paper_trading/_btst_reporting/premarket_card.py`：新增 risk_off/crisis/halt guardrail 文案
- `src/paper_trading/_btst_reporting/brief_builder.py` + `brief_rendering.py`：next-day trade brief 新增 Global Guardrails

（以上均已配套 pytest 覆盖，且属于 report-only 变更，不改交易引擎执行结果。）
