# Decision Pack: 条件单前门门控 (C-CONDITIONAL-ORDER-VERDICT-GATE)

> **生成**: autodev-32 /loop session 3, 2026-07-09
> **状态**: 等待 owner 决策
> **北极星**: T+5/T+10 赚钱工具 — 条件单是买入建议的下游, 不应在隐含建议买入的列表中包含前门判决为 AVOID/HOLD 的标的

## 问题

`--conditional-orders` 和 `--export-conditional-orders` 对 **所有** Top-N 推荐生成条件单建议(买入区间/止损/止盈/券商CSV), 
不经过 `build_front_door_verdict` 过滤。因此:

- AVOID-rated 的标的 (如 20260703 报告中的 688019/688766) 仍有条件单输出
- 输出券商CSV可导入真实券商 → **真实资金可能在条件触发时买入一个前门否决的标的**

条件单本质是风险约束(仅当价格触及买入区间才触发), 不是买入指令, 
但出现在同一个 CLI 表中且没有明显警示, 容易让 operator 误以为是含蓄的买入建议。

## 当前状态

**已完成的防御 (autodev-13, loop 104)**:
- `_format_front_door_verdict_disclosure` 在 CLI 输出尾部显示前门判决摘要
- `⚠ 前门判决: M/N 为 BUY; K 个非 BUY (AVOID×A, HOLD×H): xxx` 已在条件单 CLI 和 export CLI 中渲染
- **券商 CSV/JSON 文件中不包含判决信息** (格式限制)

## 候选方案

| 方案 | 描述 | 影响 | 自主性 |
|------|------|------|--------|
| **A (Filter)** | 条件单生成/导出时过滤掉非 BUY 标的 | 改变默认行为 → 用户看不到条件单 | ❌ owner |
| **B (Additive)** | CLI 添加判决列 + ，export 添加警示行 | 已完成 | ✅ 已完成 |
| **C (Disclaimer)** | 只在 CLI 输出尾部加一行文本 | 已被 B 覆盖 | ✅ 已完成 |
| **D (Keep)** | 保持现状, 承认条件单是独立工具 | 最小风险（条件单不是买入指令） | ✅ |

## 推荐方案

**Option A behind env var**: 实现 filter 但不改默认行为:

```
CONDITIONAL_ORDER_FILTER_VERDICT=1  # 开启过滤
CONDITIONAL_ORDER_FILTER_VERDICT=0  # 关闭 (默认)
```

理由:
1. 默认行为不变, 不违反合同 §「不改变生产默认行为」
2. operator 可随时开启: `CONDITIONAL_ORDER_FILTER_VERDICT=1 uv run python src/....`
3. 工程成本低: 在 `attach_conditional_orders_to_payload` 中加 ~20 行
4. 过滤后输出的 CSV 只包含 BUY 标的, 减少真实券商的误买入风险

## 明确问题

**Owner: 你希望实现按前门判决过滤条件单的 env var 吗?**
- 如果「是」: 默认关闭, operator 通过 `CONDITIONAL_ORDER_FILTER_VERDICT=1` 启用
- 如果「保持现状」: 当前 additive disclosure (Option B) 已到位, 工程上可关闭此候选
