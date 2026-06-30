# Artifact Reading Guide

Load this file before constructing verdicts and rendering the Top 8 report.

## Source priority

0. **`compute_auto_screening_results` payload**（主真源，纯函数返回，无 IO 副作用）:
   - 调用：`from src.main import compute_auto_screening_results; payload = compute_auto_screening_results(trade_date="YYYYMMDD", top_n=20)`
   - 字段读取顺序：`recommendations` → `market_state` → `industry_rotation` → `signal_decay_summary` → `consecutive_recommendation`。
1. **`detect_market_state` 返回的 `MarketState`**（regime 真源）:
   - 调用：`from src.screening.market_state import detect_market_state; ms = detect_market_state("YYYYMMDD")`
   - **必须**用 `ms.regime_gate_level` 取 regime 字符串，**不要**从 `payload["market_state"]` 直接读 regime（后者是派生视图，可能与 `regime_gate_level` 不一致，见 `src/screening/top_picks.py:114` 注释）。
2. **`build_front_door_verdict` 返回的 dict**（BUY/HOLD/AVOID 真源）:
   - 调用：`from src.screening.investability import build_front_door_verdict; verdict = build_front_door_verdict(rec, market_regime=regime)`
   - 返回：`{"action", "market_regime", "invalidation_reason", "signal_horizon"}`
3. **`render_regime_winrate_line` / `render_regime_multihorizon_line`**（regime 历史 winrate 渲染真源）:
   - 调用：`from src.screening.regime_winrate import render_regime_winrate_line, render_regime_multihorizon_line`
   - 必须传 `today=signal_date_obj` 让 `as_of` + staleness ⚠ 自动出现（NS-5）。

## Recommendation 字段读取规则

每条 `rec` (来自 `payload["recommendations"]`) 的关键字段：

| 字段 | 类型 | 含义 | 缺失处理 |
|---|---|---|---|
| `ticker` | str | 股票代码（如 `300750`） | 必填，缺失则跳过该 rec |
| `name` | str | 股票名称（如 `宁德时代`） | 缺失时用 ticker 代替 |
| `composite_score_gated` | float | pre-bonus 分数（NS-11，BUY gate 依据） | 缺失回退 `composite_score` |
| `composite_score` | float | post-bonus 分数（排序用，含 consecutive bonus） | 缺失回退 `score_b` |
| `score_b` | float | 基础分（fallback） | 缺失视为 0.0 |
| `composite_verified` | bool | 是否完整维度调整（False=R39 fallback 0.9 折扣） | 缺失视为 True |
| `decision` | str | 系统决策（`bullish` / `bearish` / `neutral`） | bearish 时 `supports_long=False` |
| `expected_returns` | dict | `{"t1":..., "t5":..., "t10":..., "t20":..., "t30":...}`（百分比） | 缺失视为 0.0 |
| `win_rates` | dict | `{"t1":..., "t5":..., "t10":..., "t20":..., "t30":...}`（0-1） | 缺失视为 0.0 |
| `bucket_sample_count` | dict | bucket 全样本量（含未 mature） | 缺失视为 0 |
| `bucket_t30_mature_count` | int | bucket T+30 mature 样本量（R35，BUY gate 依据） | 缺失回退 `bucket_sample_count` 并标注"mature 字段缺失" |
| `bucket_t30_avg_negative_return` | float | per-bucket T+30 典型下行（赔率） | 缺失显示 `—` |
| `momentum_bonus` / `sector_bonus` / `consistency_adj` / `volume_factor` / `trend_resonance_factor` | float | 失效信号分量（< 0 时进入 invalidation_reasons） | 缺失视为 0.0 |
| `consecutive_days` | int | 连续推荐天数 | 缺失视为 0 |
| `consecutive_status` | str | 连续推荐状态 | 缺失视为空 |

## Verdict 字段读取规则

`build_front_door_verdict` 返回的 dict：

| 字段 | 取值 | 含义 |
|---|---|---|
| `action` | `"BUY"` / `"HOLD"` / `"AVOID"` | BUY gate 判定结果 |
| `market_regime` | 输入的 regime 字符串 | 回显 regime |
| `invalidation_reason` | str | 失效条件（多个用 `, ` 分隔） |
| `signal_horizon` | `"T+5"` / `"T+10"` / `"T+5+T+10"` / `""` | BUY 信号来源 horizon（C221） |

### signal_horizon 含义

- `"T+5+T+10"`：T+5 和 T+10 都通过 BUY gate（edge>0 AND winrate>=0.55），最强信号。
- `"T+5"`：仅 T+5 通过（短期反弹）。
- `"T+10"`：仅 T+10 通过（crisis regime 下唯一可放行的 horizon，C245）。
- `""`：无短期信号（HOLD/AVOID 的常见情况），报告里**不展示**该字段（与 `top_picks.py:1369` 一致）。

### action 判定逻辑（已封装在 `build_front_door_verdict` 内，skill 不重复实现）

- crisis/risk_off regime（`_is_market_gate_active=True`）：
  - `_short_term_passes = _t10_passes`（C245，只看 T+10）
  - 即使 `_short_term_passes=True`，action 也降级为 `HOLD`（不 BUY）
- 非 crisis regime：
  - `_short_term_passes = _t5_passes or _t10_passes`（C220 OR 逻辑）
  - `_meets_quality_bar=True` 且 `backing_sample>=20` → `BUY`
  - `is_watchable=True`（composite_score>=0.25 且 T+5/T+10 winrate>=0.5 edge>=0）→ `HOLD`
  - 否则 → `AVOID`

## 排序键（与 `rank_recommendations_by_investability` 一致，C222）

```
1. action 优先级: BUY > HOLD > AVOID
2. composite_score_gated 降序 (pre-bonus, NS-11)
3. max(t5_edge, t10_edge) 降序 (决策 horizon edge)
4. max(t5_winrate, t10_winrate) 降序 (决策 horizon winrate)
5. bucket_sample_count 降序 (样本量)
6. ticker 升序 (tie-break)
```

## 缺失字段降级流程

1. `composite_score_gated` 缺失 → 回退 `composite_score` → 再缺失回退 `score_b` → 再缺失视为 0.0。
2. `expected_returns.t5` / `win_rates.t5` 缺失 → 视为 0.0（不阻止 BUY 判定，但 edge=0 不满足 `>0` 条件，自然 fail）。
3. `bucket_t30_mature_count` 缺失 → 回退 `bucket_sample_count`，并在报告标注"mature 字段缺失（用全样本量）"。
4. `composite_verified=False` → 在 `composite_score` 后追加 `(估)` 标记（R111 trust-calibration）。
5. `name` 缺失 → 用 `ticker` 代替，不再编造名称。
6. 整条 rec 缺失 `ticker` → 跳过该 rec，不计入 8 只。

## 失败处理

- `compute_auto_screening_results` 抛 `ValueError`（候选池为空）→ 停止，报告 blocker"信号日 YYYYMMDD 候选池为空，请检查市场数据源"。
- `compute_auto_screening_results` 抛 `RuntimeError`（数据获取失败）→ 停止，报告 blocker"数据获取失败，请检查 TUSHARE_TOKEN"。
- `detect_market_state` 抛错 → 停止，报告 blocker"market state 检测失败"，不伪造 regime。
- `build_front_door_verdict` 抛错 → 跳过该 rec，不计入 8 只，但在报告末尾标注"N 只 rec verdict 失败"。
- `payload["recommendations"]` 为空 → 停止，报告 blocker"recommendations 为空"。
