# Trigger Examples

Load this file only when the user asks how to trigger the skill, or when the trigger semantics are unclear.

## 强触发（明确应触发 stock-top8）

这些请求应直接触发本 skill，无需额外确认：

- 给我未来 5-10 天胜率最高的 8 只股票
- 推荐下周胜率和盈亏比最佳的 8 只
- top 8 短期反弹票
- 用系统数据挑 8 只 T+5/T+10 horizon 的票
- 5-10 个交易日 horizon 选股 8 只
- 帮我出一份 top8 短期选股报告
- 一周左右胜率赔率最佳 8 只
- 短周期选股 8 只，要有 BUY gate 判定和 signal_horizon
- 基于 composite_score_gated 给我 8 只最佳短期反弹票
- 短期盈亏比 top 8
- T+5 horizon 8 只最佳股票
- T+10 horizon 8 只最佳股票
- 5 日 horizon 选 8 只
- 10 日 horizon 选 8 只
- 来 8 只短期 horizon 的，要带 regime 标注
- 给 8 只 BUY 信号最强的票（短期 horizon）

## 弱触发（应触发但需简短确认）

这些请求语义接近但略有歧义，触发后简短确认 horizon 与数量：

- 推荐 8 只股票（用户没说 horizon，但"8 只"是本 skill 标志性数量）
  - 确认：`默认按 T+5/T+10 horizon（5-10 个交易日）选 8 只，可以吗？`
- 给我 8 只最佳股票（同上）
- top 8 选股（同上）
- 短期选股 8 只（"短期"=5-10 天？确认）
- 胜率最高的 8 只（"胜率"是 T+5/T+10 还是 T+30？默认 T+5/T+10，确认）

## 非触发（不应触发 stock-top8）

这些请求应触发其他 skill 或直接走系统已有功能，**不要**触发本 skill：

- 给我明天的 BTST 计划 → 触发 `ai-hedge-fund-btst`（次日 T+1 计划）
- 生成 BTST 全套文档 → 触发 `ai-hedge-fund-btst`
- 给我 10 只股票（数量不是 8） → 直接走 `uv run python src/main.py --top 10`，不触发本 skill
- 给我 top 5 选股 → 同上，走 `--top 5`
- 给我长期持有 8 只 → 长期持有 ≠ T+5/T+10 短期反弹，不触发本 skill；建议走 `--top-picks` + T+30 horizon 诊断
- 给我 8 只价值投资 → 价值投资 ≠ 短期反弹，不触发本 skill
- 因子诊断 → 走 `scripts/_diag_*.py` 系列，不触发本 skill
- 回测历史数据 → 走 `scripts/_backfill_historical_recs.py`，不触发本 skill
- regime winrate 重算 → 走 `uv run python src/main.py --refresh-regime-winrates`，不触发本 skill
- 给我 8 只基金 / 8 只 ETF → 本 skill 只覆盖 A 股个股，不触发
- 解释某只票为什么推荐 → 走 `uv run python src/main.py --explain 300750`，不触发本 skill
- 为什么某只票没推荐 → 走 `uv run python src/main.py --why-not 000001`，不触发本 skill

## 边界判断

- 用户说"给我 8 只下周怎么打"：下周 = 5 个交易日 ≈ T+5 horizon → 触发本 skill（不是 btst，btst 是次日 T+1）。
- 用户说"给我 8 只明天怎么打"：明天 = T+1 → 触发 `ai-hedge-fund-btst`，**不**触发本 skill。
- 用户说"8 只短期"：短期默认 T+5/T+10 → 触发本 skill；如用户纠正"短期=明天"则切到 btst。
- 用户说"8 只中期"：中期 ≠ T+5/T+10 → 不触发本 skill，建议走 `--top-picks` + T+30 诊断。
- 用户说"8 只长期"：长期 ≠ T+5/T+10 → 不触发本 skill。
- 用户说"top 8"但没说 horizon：默认 T+5/T+10 → 触发本 skill，但简短确认 horizon。
- 用户说"给我 8 只 BUY 信号最强的"：BUY 信号 = 短期 horizon → 触发本 skill。

## 与 ai-hedge-fund-btst 的触发对比

| 用户请求 | 触发 skill | 原因 |
|---|---|---|
| 明天 BTST 计划 | ai-hedge-fund-btst | T+1 horizon |
| 8 只未来 5-10 天最佳 | stock-top8（本 skill） | T+5/T+10 horizon |
| BTST 全套文档 | ai-hedge-fund-btst | BTST 文档流 |
| 8 只短期反弹票 | stock-top8（本 skill） | 短期反弹 = T+5/T+10 |
| 次日交易计划 | ai-hedge-fund-btst | T+1 |
| 一周左右 8 只 | stock-top8（本 skill） | 一周 ≈ T+5 |
| 8 只持仓 1 个月 | 都不触发 | 1 个月 = T+30 ≠ T+5/T+10，走 `--top-picks` |

## 触发时的默认确认问题

触发本 skill 后，如果用户没有明确给出：

1. **signal date**：自动解析"已拿到收盘数据的最新交易日"，不问。
2. **保存路径**：问一句 `是否保存到默认目录 outputs/YYYYMM/YYYYMMDD/stock-top8/？`
3. **horizon**：默认 T+5/T+10（5-10 天），不问；如用户说"短期=明天"则切到 btst。
4. **数量**：默认 8 只，不问；如用户明确要其他数量（如 10 只），不触发本 skill，走 `--top 10`。

如果用户同时给了自定义路径和默认路径，以自定义路径为准。
