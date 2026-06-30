# Final Document Spec

Load this file before drafting the Top 8 Markdown report and JSON payload.

## Output set

用 signal date YYYYMMDD 命名所有文件：

1. `stock-top8-YYYYMMDD.md` — 人类可读 Markdown 报告（中文）
2. `stock-top8-YYYYMMDD.json` — 结构化 JSON payload（程序可读）

落盘目录：`outputs/YYYYMM/YYYYMMDD/stock-top8/`（`YYYYMM` 来自 signal date）。

## Markdown 报告结构

报告必须按以下顺序包含这些区块，标题完全一致：

```
# stock-top8 报告 YYYYMMDD（信号日）→ YYYY-MM-DD（下一交易日）

## 0. 报告摘要
- 信号日 / 下一交易日 / regime / BUY 通过数 / HOLD 补足数 / AVOID 备选数
- 一句话执行倾向（保守 / 中性 / 激进）

## 1. Top 8 主表
[表格，见下方"Top 8 表格列"]

## 2. 胜率/赔率诊断卡（Alpha）
[硬区块，见下方"Alpha 区块"]

## 3. 执行触发/取消/升级/降级矩阵（Beta）
[硬区块，见下方"Beta 矩阵"]

## 4. 大盘-板块-赚钱效应环境卡（Gamma）
[硬区块，见下方"Gamma 区块"]

## 5. 备选观察池（如有 AVOID 补足）
[仅当 AVOID 补足时展示，否则省略]

## 6. 失效条件与风险提示
[逐票 invalidation_reason 汇总 + 数据时点 + 样本警告]
```

## Top 8 表格列

主表必须包含以下列（顺序固定）：

| 列 | 字段来源 | 格式 | 缺失处理 |
|---|---|---|---|
| 排名 | 排序后 1-8 | `1.` / `2.` / ... | 必填 |
| 代码 | `rec["ticker"]` | `300750` | 必填 |
| 名称 | `rec["name"]` | `宁德时代` | 缺失用 ticker |
| 动作 | `verdict["action"]` | `BUY` / `HOLD` / `AVOID` | 必填 |
| 信号 | `verdict["signal_horizon"]` | `T+5` / `T+10` / `T+5+T+10` / （空） | 空时显示 `—` |
| 综合分 | `rec["composite_score_gated"]` 或回退 `composite_score` | `+0.523` | 缺失显示 `—` |
| T+5 edge | `rec["expected_returns"]["t5"]` | `+1.23%` | 缺失显示 `—` |
| T+5 胜率 | `rec["win_rates"]["t5"]` | `62%` | 缺失显示 `—` |
| T+10 edge | `rec["expected_returns"]["t10"]` | `+1.45%` | 缺失显示 `—` |
| T+10 胜率 | `rec["win_rates"]["t10"]` | `60%` | 缺失显示 `—` |
| T+30 edge | `rec["expected_returns"]["t30"]` | `+0.30%` | 缺失显示 `—`（仅作长期衰退参考） |
| T+30 胜率 | `rec["win_rates"]["t30"]` | `45%` | 缺失显示 `—` |
| 样本 | `rec["bucket_t30_mature_count"]` 或回退 `bucket_sample_count` | `n=7203` | 缺失显示 `n=0`，标注"样本不足" |
| 节奏 | `_classify_return_rhythm(rec["expected_returns"])` | `早` / `匀` / `晚` / `—` | 缺失或 T+30 edge<=0 显示 `—` |
| 赔率(下行) | `rec["bucket_t30_avg_negative_return"]` | `-4.5%` | 缺失显示 `—` |
| 市场门控 | `verdict["market_regime"]` | `crisis` / `risk_off` / `normal` | 必填 |

### 表格示例

```markdown
| 排名 | 代码 | 名称 | 动作 | 信号 | 综合分 | T+5 edge | T+5 胜率 | T+10 edge | T+10 胜率 | T+30 edge | T+30 胜率 | 样本 | 节奏 | 赔率(下行) | 市场门控 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1. | 300750 | 宁德时代 | BUY | T+5+T+10 | +0.612 | +1.23% | 62% | +1.45% | 60% | +0.30% | 45% | n=7203 | 倒 U | -4.5% | normal |
| 2. | 000001 | 平安银行 | BUY | T+5 | +0.548 | +0.95% | 58% | +0.42% | 52% | -0.10% | 44% | n=5102 | 倒 U | -5.2% | normal |
| 3. | 600519 | 贵州茅台 | HOLD | — | +0.421 | +0.30% | 53% | +0.20% | 51% | +0.50% | 48% | n=3201 | 单调 | -3.8% | normal |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |
```

## Alpha 区块（胜率/赔率诊断卡）

标题：`## 2. 胜率/赔率诊断卡（Alpha）`

必须包含：

1. **regime 历史 winrate**（用 `render_regime_winrate_line(regime, today=signal_date_obj)` 渲染）：
   - 单行格式：`regime=normal T+30 历史 winrate=43.4% (n=...) | 数据时点 2026-06-25` + 如 stale 追加 `⚠ 数据可能过时 (距今 N 天, 阈值 14 天)`
2. **regime 多 horizon median**（用 `render_regime_multihorizon_line(regime, today=signal_date_obj)` 渲染）：
   - 单行格式：`regime=normal T+15/T+20/T+25/T+30 median=...`
3. **per-bucket 全期 winrate**（来自 C219 n=7203 bootstrap CI）：
   - 表格：`| Horizon | Winrate | 95% CI | >50%? |`
   - T+1: 50.3% [49.2%, 51.4%] ? MARGINAL
   - T+5: 60.2% [59.0%, 61.3%] ✓ YES
   - T+10: 60.5% [59.4%, 61.6%] ✓ YES
   - T+30: 45.4% [44.2%, 46.5%] ✗ NO
   - 说明：T+5/T+10 是短期反弹 horizon（winrate 峰值），T+30 是长期衰退信号（不作 BUY 依据）。
4. **Top 8 整体统计**：
   - BUY 通过数 / HOLD 补足数 / AVOID 备选数
   - 平均 T+5 edge / 平均 T+10 edge / 平均 T+5 winrate / 平均 T+10 winrate
   - 胜率与赔率是否分化（高胜率但赔率弱 / 胜率一般但赔率厚 / 两者一致 / 无法判断）
5. **样本质量警告**：
   - 列出样本量 < 20 的票（如有）
   - 列出 `bucket_t30_mature_count` 字段缺失的票（如有）

如果当前 artifacts 不支持某项，写 `artifacts not available` 或 `context weak`，**不要**省略整个 Alpha 区块。

## Beta 矩阵（执行触发/取消/升级/降级矩阵）

标题：`## 3. 执行触发/取消/升级/降级矩阵（Beta）`

必须包含逐票行（Top 8 每只一行），列固定：

| 列 | 含义 | 来源 |
|---|---|---|
| 代码 | 股票代码 | `rec["ticker"]` |
| 名称 | 股票名称 | `rec["name"]` |
| 所属层 | `正式执行` / `观察补足` / `备选观察` | action + 排序位置 |
| 计划动作 | `BUY` / `HOLD` / `AVOID` | `verdict["action"]` |
| 触发条件 | 何时能做 | BUY: composite>=0.5 AND T+5/T+10 通过 AND regime 非 crisis; HOLD: composite>=0.25 AND T+5/T+10 watchable; AVOID: 其余 |
| 取消条件 | 何时不做 | crisis regime 触发 / 开盘 gap 缺口 > 3% / 量能萎缩 |
| 观察升级条件 | 何时从 HOLD 升 BUY | T+5/T+10 edge 转正且 winrate>=0.55 |
| 降级条件 | 何时从 BUY 降 HOLD | crisis/risk_off regime 触发（C245） |
| 回补条件 | 何时从 AVOID 升观察 | T+5/T+10 edge 转正 |
| 时段 | 建议执行时段 | T+5 票: 09:25-09:35; T+10 票: 09:25-10:00; HOLD: 09:35 后观察 |
| 成本/仓位约束 | 建议仓位（参考） | BUY: `_suggest_position_pct` 输出; HOLD/AVOID: 不建议建仓 |

### 矩阵示例

```markdown
| 代码 | 名称 | 所属层 | 计划动作 | 触发条件 | 取消条件 | 观察升级条件 | 降级条件 | 回补条件 | 时段 | 成本/仓位约束 |
|---|---|---|---|---|---|---|---|---|---|---|
| 300750 | 宁德时代 | 正式执行 | BUY | composite=0.61>=0.5, T+5+T+10 通过, regime=normal | crisis regime 触发 / 开盘 gap>3% | —（已 BUY） | crisis/risk_off regime 触发 | —（已 BUY） | 09:25-09:35 | 建议仓位 8.0% |
| 600519 | 贵州茅台 | 观察补足 | HOLD | —（HOLD 不执行） | — | T+5/T+10 edge 转正且 winrate>=0.55 | — | T+5/T+10 edge 转正 | 09:35 后观察 | 不建议建仓 |
```

如果 `verdict["invalidation_reason"]` 含具体失效信号（如 `T+30 edge 转负` / `市场门控维持 risk-off` / `动量转负`），必须在矩阵行的"取消条件"或"降级条件"列回显。

## Gamma 区块（大盘-板块-赚钱效应环境卡）

标题：`## 4. 大盘-板块-赚钱效应环境卡（Gamma）`

必须包含：

1. **market gate / regime**：
   - `regime = crisis / risk_off / normal`
   - `market gate = 放行 / 维持 risk-off / 危机`
   - 触发原因（breadth_ratio / position_scale / regime_flip_risk 中哪一项触发）
2. **大盘风险框架**：
   - 从 `payload["market_state"]` 读取（如有）
   - 缺失则写 `大盘风险框架 artifacts not available`
3. **板块 / 题材 / 情绪 / 赚钱效应支撑**：
   - 从 `payload["industry_rotation"]` 读取（如有）
   - 缺失则写 `板块 / 题材 context weak`
4. **regime 历史 winrate（含 as_of + staleness）**：
   - 用 `render_regime_winrate_line(regime, today=signal_date_obj)` 渲染
   - 用 `render_regime_multihorizon_line(regime, today=signal_date_obj)` 渲染
5. **对保守 / 激进执行倾向的实际含义**：
   - crisis: 全部降级 HOLD，建议观望
   - risk_off: 谨慎，仅 T+10 信号可考虑
   - normal: BUY 信号可执行，T+5/T+10 OR 逻辑

如果当前 artifacts 不支持某项，写 `artifacts not available` 或 `context weak`，**不要**省略整个 Gamma 区块。

## 备选观察池（可选区块）

标题：`## 5. 备选观察池（如有 AVOID 补足）`

仅当 Top 8 中有 AVOID 补足时展示，否则整个区块省略。

格式同 Top 8 主表，但加一列"备选原因"说明为何该票是 AVOID（composite<0.25 / winrate<0.5 / edge<0 等）。

## 失效条件与风险提示

标题：`## 6. 失效条件与风险提示`

必须包含：

1. **逐票 invalidation_reason 汇总**（Top 8 每只一行）：
   - `300750 宁德时代: T+30 edge 转负, 市场门控转弱`
   - 失效条件来自 `verdict["invalidation_reason"]`，多个用 `, ` 分隔
2. **数据时点**：
   - regime 历史 winrate `as_of` 日期
   - 是否 stale（距今 > 14 天）
3. **样本警告**：
   - 列出样本量 < 20 的票（如有）
   - 列出 `bucket_t30_mature_count` 缺失的票（如有）
4. **horizon 警告**：
   - T+5/T+10 是短期反弹 horizon，T+30 winrate=45% << 50%，不应长期持有（C219 n=7203 验证）
   - crisis regime 下 T+5 winrate=43.59% < 50%，T+5 单独不可靠（C245）

## JSON payload 结构

`stock-top8-YYYYMMDD.json` 必须包含：

```json
{
  "signal_date": "YYYYMMDD",
  "next_trade_date": "YYYY-MM-DD",
  "market_regime": "crisis / risk_off / normal",
  "regime_as_of": "2026-06-25",
  "regime_is_stale": true/false,
  "buy_count": 2,
  "hold_count": 5,
  "avoid_count": 1,
  "top8": [
    {
      "rank": 1,
      "ticker": "300750",
      "name": "宁德时代",
      "action": "BUY",
      "signal_horizon": "T+5+T+10",
      "composite_score_gated": 0.612,
      "composite_score": 0.612,
      "expected_returns": {"t5": 1.23, "t10": 1.45, "t30": 0.30},
      "win_rates": {"t5": 0.62, "t10": 0.60, "t30": 0.45},
      "bucket_t30_mature_count": 7203,
      "bucket_sample_count": 7500,
      "bucket_t30_avg_negative_return": -4.5,
      "rhythm": "早",
      "market_regime": "normal",
      "invalidation_reason": "T+30 edge 转负, 市场门控转弱",
      "layer": "正式执行",
      "suggested_position_pct": 8.0
    }
  ],
  "alpha_summary": {
    "regime_historical_winrate": "regime=normal T+30 历史 winrate=43.4% (n=...) | 数据时点 2026-06-25",
    "regime_multihorizon_median": "regime=normal T+15/T+20/T+25/T+30 median=...",
    "per_bucket_winrate": {
      "t1": {"winrate": 0.503, "ci_lower": 0.492, "ci_upper": 0.514, "verdict": "MARGINAL"},
      "t5": {"winrate": 0.602, "ci_lower": 0.590, "ci_upper": 0.613, "verdict": "YES"},
      "t10": {"winrate": 0.605, "ci_lower": 0.594, "ci_upper": 0.616, "verdict": "YES"},
      "t30": {"winrate": 0.454, "ci_lower": 0.442, "ci_upper": 0.465, "verdict": "NO"}
    },
    "winrate_payoff_divergence": "高胜率但 T+30 赔率弱（短期反弹 vs 长期衰退分化）"
  },
  "gamma_summary": {
    "market_gate": "放行 / 维持 risk-off / 危机",
    "regime_reasons": ["breadth_ratio=0.42 < 0.45 floor", ...],
    "sector_rotation": "...",
    "execution_lean": "保守 / 中性 / 激进"
  }
}
```

## Global writing rules

- 用中文写 Markdown 报告。
- 股票首次出现必须用 `stock_code + stock_name`（如 `300750 宁德时代`）。
- 数字格式：
  - 综合分: `+0.523` / `-0.123`（保留 3 位小数，带正负号）
  - edge: `+1.23%` / `-0.45%`（保留 2 位小数，带正负号）
  - winrate: `62%`（百分比，整数）
  - 样本: `n=7203`（整数）
- 不能虚构股票名、edge、winrate、verdict、signal_horizon。
- 不能把 `HOLD` 或 `AVOID` 票擅自标成 `BUY`。
- `signal_horizon` 为空字符串时，表格"信号"列显示 `—`，不写空字符串。
- crisis/risk_off regime 下的 BUY 候选已自动降级为 HOLD（C245），报告里必须明说"本可 BUY 但被市场门控降级"。
- 字段缺失时显示 `—`，**不要**写 `N/A` 或 `null`；但对三硬区块，若当前 artifacts 不支持，必须显式写 `artifacts not available` 或 `context weak`，不能直接消失。
- 不能写通用股评，所有市场语境必须来自当前 `payload["market_state"]` / `payload["industry_rotation"]` / `detect_market_state`。
- 报告标题里写真实的 `next trade date`，不能写 `N/A`。
- 文件名用 `signal date`，不是 `next trade date`。
