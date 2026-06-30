---
name: stock-top8
description: 在本仓库中处理"未来 5-10 天内胜率和盈亏比最佳的 8 只股票"类请求时触发。典型触发语义：top 8 / 8 只股票 / 5-10 天 / 5-10 日 / 短期胜率 / 短期盈亏比 / 短期反弹票 / T+5 / T+10 / 给我 8 只 / 一周左右 horizon / 短周期选股。当用户提到"8 只"、"top8"、"5-10 天"、"短期胜率"、"短期盈亏比"、"T+5/T+10 horizon 选股"、"短期反弹"等关键词，或要求基于系统已有胜率/赔率数据输出精选股票列表时，使用本 skill。本 skill 与 ai-hedge-fund-btst（次日计划）互补，btst 走次日多智能体计划，stock-top8 走纯规则版 5-10 天 horizon 选股。
---

# stock-top8

本 skill 负责本仓库的"未来 5-10 天内胜率和盈亏比最佳的 8 只股票"短期 horizon 选股流。

## 默认目标

- 默认输出 `8` 只股票，horizon = `T+5/T+10`（5-10 个交易日），按短期胜率与盈亏比排序。
- 默认产物：1 份 Markdown 报告 + 1 份 JSON payload，落到 `outputs/YYYYMM/YYYYMMDD/stock-top8/`。
  - 这里的 `YYYYMM` 来自 `signal date`，不是 `next trade date`。
- 排序优先级：`BUY 优先 → composite_score_gated → max(T+5,T+10) edge → max(T+5,T+10) winrate → bucket_sample_count`。
- 如果 BUY 通过的票不足 8 只，按 `HOLD` (watchable) 补足；如果 HOLD 也不足，按 `AVOID` 中分数最高的补足，并明确标注"备选观察"。
- 系统默认 BUY gate 阈值真源是 `src/screening/investability.py` 中的硬编码（composite_score >= 0.5、短期 horizon winrate >= 0.55、edge > 0、backing_sample >= 20），**不要**在 skill 里另设阈值。
- 当用户没有给出保存路径时，问一句简短问题：
  - `是否保存到默认目录 outputs/YYYYMM/YYYYMMDD/stock-top8/？`
- 如果用户已经给出自定义目录，不再重复追问。

## 与 ai-hedge-fund-btst 的边界

- `ai-hedge-fund-btst`：次日（T+1）BTST 计划，走多智能体 paper trading，输出 5+2 份文档。
- `stock-top8`（本 skill）：5-10 天 horizon（T+5/T+10）短期反弹选股，走纯规则版 `compute_auto_screening_results`，输出 1 份 MD + 1 份 JSON。
- 两者**不混用**：用户要"明天怎么打"用 btst；用户要"未来一周左右胜率赔率最佳的 8 只"用本 skill。

## Alpha / Beta / Gamma 硬职责

- **Alpha（统计与赔率）**
  - 只对"这 8 只候选在 T+5/T+10 horizon 上的胜率稳定性与赔率质量"负责。
  - 必须抽取并写清：每只票的 T+5/T+10 edge + winrate、composite_score_gated、样本量、regime 历史 winrate（带 as_of 与 staleness 提示）、胜率与赔率是否分化。
  - 必须显式说明：T+5/T+10 是短期反弹 horizon（C219 n=7203 验证），T+30 是长期衰退信号（不作 BUY 依据，仅作 invalidation）。
  - 当样本量 < 20 或 regime 数据 stale 时，明确写"证据不足"或"数据可能过时"，不能把点估计包装成稳定 edge。
- **Beta（执行与降级）**
  - 只对"这 8 只怎么下、何时确认、何时取消、何时降级"负责。
  - 必须把每只票的 BUY/HOLD/AVOID 动作、signal_horizon（T+5/T+10/T+5+T+10）、失效条件、regime 降级口径写成可执行表格。
  - crisis/risk_off regime 下 BUY gate 只看 T+10（C245），所有 BUY 候选自动降级为 HOLD，必须在报告中明说。
- **Gamma（市场 / regime）**
  - 只对"当前 regime 是否支持短期反弹策略"负责。
  - 必须复述 `detect_market_state` 给出的 regime（crisis / risk_off / normal）+ market gate 状态 + regime 历史 T+5/T+10/T+30 winrate（带 as_of + staleness）。
  - 如果 regime 数据 stale（as_of 距今 > 14 天），必须显示 ⚠ 警告，不能假装数据是实时的。

## 默认优化优先级

1. **胜率 / 赔率严谨性优先（Alpha first）** — 不把低样本点估计包装成稳定 edge。
2. **BUY gate 透明性第二（Beta second）** — 每只票都写清 BUY/HOLD/AVOID 的判定依据。
3. **regime / market gate 语境第三（Gamma third）** — crisis regime 下显式降级。

## Workflow

1. 解析日期与目录。
   - 如果用户指定了 `signal date`，直接使用。
   - 如果没有指定，自动解析"已拿到收盘数据的最新交易日"。
   - 永远计算真实的 `next trade date`。
   - 如果收盘数据不可用，停止并说明 blocker，**不要**伪造报告。
   - 默认目录：`outputs/YYYYMM/YYYYMMDD/stock-top8/`。

2. 调用 `compute_auto_screening_results` 拿 payload。
   - 这是 `src/main.py:622` 的纯函数版 `--auto` 流水线，无 IO 副作用，返回 JSON-serializable dict。
   - **不要**走 `uv run python src/main.py --auto` CLI，那会落盘 + 打印表格，纯函数版更快更干净。
   - 调用方式（在 Python REPL 或一次性脚本内）：

   ```python
   from src.main import compute_auto_screening_results
   payload = compute_auto_screening_results(trade_date="YYYYMMDD", top_n=20)
   recommendations = payload["recommendations"]
   market_state = payload["market_state"]
   ```

   - `top_n=20` 而非 `top_n=8`：留出排序空间，BUY 通过的可能 < 8，需要从 HOLD 中补足。
   - 如果 `recommendations` 为空，停止并说明 blocker。

3. 调用 `detect_market_state` 拿 regime。
   - **不要**从 payload 的 `market_state` 字段直接读 regime 字符串，要用 `detect_market_state(trade_date).regime_gate_level`，这是 regime 判定的唯一真源（见 `src/screening/top_picks.py:114` 注释）。

   ```python
   from src.screening.market_state import detect_market_state
   ms = detect_market_state("YYYYMMDD")
   regime = ms.regime_gate_level  # "crisis" / "risk_off" / "normal"
   ```

4. 对每条 recommendation 调用 `build_front_door_verdict` 拿 BUY/HOLD/AVOID + signal_horizon。

   ```python
   from src.screening.investability import build_front_door_verdict
   for rec in recommendations:
       verdict = build_front_door_verdict(rec, market_regime=regime)
       # verdict = {"action": "BUY"/"HOLD"/"AVOID",
       #            "market_regime": regime,
       #            "invalidation_reason": "...",
       #            "signal_horizon": "T+5"/"T+10"/"T+5+T+10"/""}
       rec["_verdict"] = verdict
   ```

   - `build_front_door_verdict` 内部已实现 NS-11（优先读 `composite_score_gated` pre-bonus 分数判 BUY gate，不被 consecutive bonus 放水）、C220（T+5 OR T+10 短期 horizon BUY gate）、C245（crisis/risk_off regime 下只看 T+10，BUY 全部降级 HOLD）、C221（signal_horizon 标注）。**不要**在 skill 里重复实现这些逻辑。

5. 排序与截取 8 只。
   - 排序键（与 `rank_recommendations_by_investability` 一致，C222）：

   ```
   BUY 优先 (action="BUY" 排最前)
   → composite_score_gated 降序
   → max(t5_edge, t10_edge) 降序
   → max(t5_winrate, t10_winrate) 降序
   → bucket_sample_count 降序
   → ticker 升序 (tie-break)
   ```

   - 取前 8 只。如果 BUY + HOLD 不足 8 只，从 AVOID 中按相同键补足，并在报告中明确标注"备选观察"。
   - 如果 8 只中有同行业/同概念重复，可以保留（不像 `select_representative_candidates` 那样去重），因为用户要的是"最佳 8 只"而非"分散 8 只"；但在报告中提示行业集中度。

6. 渲染报告。
   - MANDATORY：起草前加载 `references/final-doc-spec.md`。
   - 输出 1 份 Markdown：`outputs/YYYYMM/YYYYMMDD/stock-top8/stock-top8-YYYYMMDD.md`
   - 输出 1 份 JSON：`outputs/YYYYMM/YYYYMMDD/stock-top8/stock-top8-YYYYMMDD.json`
   - 报告必须包含三硬区块（标题完全一致）：
     - `胜率/赔率诊断卡（Alpha）`
     - `执行触发/取消/升级/降级矩阵（Beta）`
     - `大盘-板块-赚钱效应环境卡（Gamma）`
   - 渲染 regime 历史 winrate 时，必须用 `render_regime_winrate_line(regime, today=signal_date)` 和 `render_regime_multihorizon_line(regime, today=signal_date)`，让 `as_of` 与 staleness 警告自动出现（NS-5 诚实披露）。

   ```python
   from src.screening.regime_winrate import (
       render_regime_winrate_line,
       render_regime_multihorizon_line,
   )
   alpha_block_lines = [
       render_regime_winrate_line(regime, today=signal_date_obj),
       render_regime_multihorizon_line(regime, today=signal_date_obj),
   ]
   ```

7. 交付前验证。
   - 所有 8 只票都有 verdict（action / signal_horizon / invalidation_reason）。
   - 所有票的 `composite_score_gated`、`t5_edge`、`t5_winrate`、`t10_edge`、`t10_winrate`、`t30_edge`、`t30_winrate`、`bucket_sample_count` 都从 recommendation 直接读取，**不要**重新计算或脑补。
   - crisis/risk_off regime 下的 BUY 候选已自动降级为 HOLD（C245），报告里必须明说"本可 BUY 但被市场门控降级"。
   - regime winrate 行带 `as_of` + staleness ⚠（如 stale）。
   - 报告里写真实的 `next trade date`，不能写 `N/A`。
   - 文件名用 `signal date`，不是 `next trade date`。

## 策略硬规则

- 最终文档必须是中文。
- 股票首次出现必须用 `stock_code + stock_name`（如 `300750 宁德时代`）。
- 不能虚构股票名、原因、排序、执行规则、verdict、signal_horizon。
- 不能把 `HOLD` 或 `AVOID` 票擅自标成 `BUY`。
- 不能把 `AVOID` 票排进 Top 8 主表而不标注"备选观察"。
- 不能让 regime stale 数据伪装成实时数据。
- crisis/risk_off regime 下，BUY 候选必须降级为 HOLD，不能维持 BUY 口径。
- 不能把高胜率但低赔率、或低样本下的点估计，包装成稳定 alpha。
- 当样本量 < 20 时，必须在该票行标注"样本不足"。
- 当 `bucket_t30_mature_count` 字段缺失时，回退到 `bucket_sample_count` 但要标注"mature 字段缺失"。
- `signal_horizon` 为空字符串时，报告里不展示该字段，保持简洁（与 `top_picks.py:1369` 一致）。
- 一般字段缺失时直接省略，不猜；但对三硬区块，若当前 artifacts 不支持，必须显式写 `artifacts not available` 或 `context weak`，不能直接消失。
- 上游 `compute_auto_screening_results` 抛错时，停止并报告 blocker，不伪造 deliverables。
- 不重复实现 `build_front_door_verdict` 已有的 BUY gate 逻辑；skill 只负责调用 + 排序 + 渲染。

## regime 与 market gate 口径

- regime 判定真源：`src/screening/market_state.py:75` `detect_market_state(trade_date).regime_gate_level`。
- 三档：`crisis` / `risk_off` / `normal`。
- crisis/risk_off 触发条件见 `src/screening/market_state_helpers.py:72-91`（breadth_ratio / position_scale / regime_flip_risk 阈值）。
- BUY gate 在 crisis/risk_off 下的降级（C245）：
  - crisis/risk_off：BUY gate 只看 T+10（T+5 单独不可靠，实际 winrate=43.59% < 50%）；即使 T+10 通过，所有 BUY 候选自动降级为 HOLD。
  - 非 crisis：BUY gate 用 T+5 OR T+10 OR 逻辑（任一短期 horizon 满足 edge>0 AND winrate>=0.55 即可 BUY）。
- regime 历史 winrate 数据时点：`REGIME_HISTORICAL_DATA_AS_OF = date(2026, 6, 25)`（NS-5/C234）；若距今 > 14 天，自动显示 ⚠ 数据可能过时。
- 如果用户要求重算 regime 历史 winrate，指向 `uv run python src/main.py --refresh-regime-winrates`，但本 skill 默认不跑（耗时长，且需要 mature 数据）。

## Lazy loading

- 在读取 `compute_auto_screening_results` payload 与构造 verdict 前，加载 `references/artifact-reading.md`。
- 在起草最终报告前，加载 `references/final-doc-spec.md`。
- 当用户问如何触发 skill 或触发语义不清时，才加载 `references/trigger-examples.md`。
- 正常执行时不要加载 `使用说明.md`（如果将来新增）。

## P0D / P0B 行为边界

- payload 字段读取优先级、verdict 字段含义、缺失字段降级流程，统一以 `references/artifact-reading.md` 为准。
- 报告结构、Top 8 表格列、三硬区块标题、Beta 矩阵字段，统一以 `references/final-doc-spec.md` 为准。
- `SKILL.md` 只保留总原则，不重复展开这些 reference 已覆盖的细节，避免 prompt 膨胀和双重真源。

## 常见边界情况

- **BUY 通过的票 < 8 只**：按 HOLD 补足，HOLD 也不足时按 AVOID 补足并标注"备选观察"。报告里明说"BUY 通过 N 只，补足 M 只 HOLD，K 只 AVOID 备选"。
- **0 只 BUY**：全部输出 HOLD/AVOID，报告标题改为"Top 8 观察池（无 BUY 信号）"，并在 Alpha 区块明说"当前无 BUY 候选，建议观望"。
- **crisis regime**：所有 BUY 自动降级 HOLD（C245），报告里明说"crisis regime 下 BUY gate 只看 T+10，且所有 BUY 候选降级 HOLD"。
- **regime 数据 stale**：Gamma 区块显示 ⚠ 数据可能过时，但不能拒绝输出报告，仍按现有硬编码 winrate 渲染。
- **`compute_auto_screening_results` 抛 ValueError（候选池为空）**：停止，报告 blocker"信号日 YYYYMMDD 候选池为空，请检查市场数据源"。
- **`compute_auto_screening_results` 抛 RuntimeError（数据获取失败）**：停止，报告 blocker"数据获取失败，请检查 TUSHARE_TOKEN"。
- **`detect_market_state` 失败**：停止，报告 blocker"market state 检测失败"，不伪造 regime。
