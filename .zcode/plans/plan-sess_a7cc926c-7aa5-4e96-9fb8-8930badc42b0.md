# 选股系统 Bug 修复 + 第一性原理优化方案

## 调查发现总结

我完整审查了 `--auto`（四策略因子评分）和 `--daily-action`（凸性 setup）两条流水线的代码逻辑，并用 `data/paper_trading_backtest/journal.jsonl`（192 笔真实 EXIT）+ `data/price_cache`（493 票 × 6 个月 OHLCV）做了回测验证。

现有测试 223 个全部通过。发现以下问题（按优先级排序）：

---

## 第一部分：Bug 修复（任务 1）

### Bug A【高优先级】BTST 涨停阈值在 20% 板（科创/创业）语义错误
**位置**：`src/screening/offensive/setups/btst_breakout.py:35` `_LIMIT_UP_PCT = 9.5`
**问题**：setup 名为「涨停突破」，但 9.5% 阈值在科创板/创业板（688/300/301 前缀，涨跌停 ±20%）会把**非涨停的大涨日**（如 +13.9%）也判定为涨停。回测验证：20% 板样本中 93%（41/44）是这类「假涨停」。
**影响**：setup 语义被污染——它实际检测的是「大涨日」而非「涨停日」。同样 bug 也存在于 `execution_adjuster.py:24` 的 `_LIMIT_UP_PCT_THRESHOLD = 9.5`（`is_limit_up_unbuyable_next_day` 错误剔除 20% 板的次日开盘涨 9.5-19.5% 的可买样本）。
**修复**（用户已确认方向：板块自适应涨停阈值）：
- 新增 `src/tools/ashare_board_utils.py` 的 `limit_up_pct_for_ticker(ticker) -> float`（主板 9.5%，科创/创业 19.5%，北交所留 9.5% 保守/或 29.5%）
- `btst_breakout.py` 的 detect 用 `limit_up_pct_for_ticker(ticker)` 替代常量 9.5
- `execution_adjuster.py` 同步修复（涨停不可买判定也要按板块）
- 同步修 `cache_refresh.py:33` `_DEFAULT_LIMIT_UP_PCT`（涨停注入扫描的口径）

### Bug B【高优先级】BTST 主力资金「>20日均值」过滤条件在当前数据下是死代码
**位置**：`src/screening/offensive/setups/btst_breakout.py:74-79`
**问题**：条件 2 要求 `today_flow > 20日均值`，但只在 `len(historical) >= 5` 时才执行均值检查。当前 `fund_flow_cache` 全部 495 个文件深度都 < 5 天（平均 1.7 天）→ 这个条件**永远不执行**，BTST 实际只剩「today_flow > 0」（涨停日几乎必为正）这一个无效过滤。
**影响**：BTST 本应有 4 个条件（涨停+放量+板块+不追高），实际只跑 3 个（放量条件失效）。`known_distributions.py` 声称的分布（n=1762）来自深历史数据，与当前运行时（浅数据）的检测口径不一致——运行时检测比回测更宽松（少了资金放量过滤），会产出回测分布未覆盖的「假命中」。
**修复**：当历史数据不足（< 5 日）无法判均值时，标记 `degraded=True`（复用 OversoldBounce 的诚实降级机制，`base.py:27`），让下游知道这个命中基于残缺条件。**不**强行用 today_flow > 0 充数。这是诚实披露，不阻塞运行。

### Bug C【中优先级】`_check_stop_hit` 的 dtype 比较死代码
**位置**：`src/screening/offensive/paper_tracker.py:558`
```python
if not isinstance(df["date"].dtype, type(prices_df["date"].dtype)):
    pass  # pandas dtype 比较不可靠, 直接尝试
```
**问题**：`isinstance(dtype, type(dtype))` 永远为 True（dtype 对象的 type 与自身 type 相同），这个 `if not ... pass` 是无意义的死代码——它既不报错也不做任何事，纯粹是噪声。
**修复**：删除这段无意义的 dtype 检查（直接 try `.dt.date`，失败走 except 兜底）。

### Bug D【低优先级】profit_aware 排序对 winrate=0.0 与无数据不做区分（falsy-zero bug）
**位置**：`src/screening/investability.py:529-538`
**问题**：`profit_aware` 模式排序键 `-_safe_metric(_max_short_horizon_metric(...), float("-inf"))` 把真实 winrate=0.0（确实 0% 胜率）和缺数据都映射到底部。同文件 `:357-359` 对 `t30_win_rate` 已用 `is_finite_number` 修过这类 bug，但排序键没修。
**修复**：用 `is_finite_number` 守卫排序键，让真实 0.0 排在缺数据之上。

---

## 第二部分：第一性原理优化（任务 2，需历史数据验证）

### 优化 1：动态 ATR 止损替代固定 -8%（用户已确认方向）
**现状**：`paper_tracker.py:308` 的 `stop_would_have_triggered` 只进 reasoning 字符串，**不影响 realized P&L**（账面按 T+N close）。AGENTS.md 明确标注「止损是摆设」。
**回测发现**（133 笔 BTST，81 笔有完整 OHLC）：
- 固定 -8% 止损：E[r] +4.19%（vs no_stop +5.54%），把 -25% 大亏封到 -8%，消除 >10% 大亏，但砍掉 19 个最终盈利的票
- 数据明确显示：固定止损在均值回归型 setup 上会误杀——很多票先跌后涨
**优化方案**：引入 ATR（平均真实波幅）动态止损
- 计算各票 20 日 ATR，止损位 = entry - k×ATR（k≈2.0，即约 2 倍波动率）
- 大波动股给更宽止损（少误杀），小波动股给更紧止损（控风险）
- 在 `paper_tracker.py` 的 `_check_stop_hit` 和 `close_matured` 里实现：ATR 止损触发时按止损价平仓，影响 realized P&L
- Kelly 仓位和 `risk_framework.build_risk_plan` 也改用 ATR（软止损 = entry - 3×ATR，硬止损 = entry - 2×ATR）
**验证**：写回测脚本，对 81 笔样本跑「固定 -8% vs 2×ATR vs 3×ATR」对比 E[r]/胜率/最大亏损/Sharpe，确认 ATR 止损是否在牛市和熊市都更优。若 ATR 止损回测不优于 no_stop，保留为披露用（尊重数据）。

### 优化 2：BTST 板块自适应涨停阈值（用户已确认方向）
作为 Bug A 的修复延伸。重跑回测验证：仅真涨停（20% 板要求 ≥19.5%）的子集是否仍统计显著（n 会从 44 降到 3，太小则需补数据或回退）。

### 优化 3：fund_flow 浅数据诚实降级
作为 Bug B 的修复延伸。在 `render_daily_action` 披露哪些 BTST 命中是基于残缺条件（资金流历史 < 5 日），让 operator 知道这些命中未经完整 setup 验证。

---

## 实施步骤（每步含测试 + 回测验证）

1. **板块自适应涨停工具**：在 `ashare_board_utils.py` 加 `limit_up_pct_for_ticker`，单测覆盖各前缀
2. **BTST setup 板块修复**：`btst_breakout.py` + `execution_adjuster.py` + `cache_refresh.py` 改用新函数；更新现有 BTST 测试
3. **fund_flow 降级披露**：`btst_breakout.py` 加 degraded 标记，`daily_action.py` 渲染披露
4. **死代码清理**：删 `_check_stop_hit` 的 dtype 比较；修 investability falsy-zero
5. **ATR 止损实现**：新增 ATR 计算工具 + 回测验证脚本，对比固定止损
6. **集成 ATR 止损到 paper_tracker + risk_framework**：让止损真正影响 P&L（经回测验证后才改执行逻辑）
7. **回测验证**：写 `scripts/backtest_exit_strategies.py`，对 192 笔历史成交跑「现状 vs ATR 止损」对比，输出 E[r]/winrate/max_drawdown/Sharpe
8. **全套测试**：`uv run pytest tests/offensive/ -v` 全绿 + 新增的 ATR/板块测试通过

## 不会做的事（明确边界）
- 不改 `known_distributions.py` 的硬编码分布（需深历史数据重跑，AGENTS.md 明确标注本地数据无法复现 n=1762）
- 不动 OversoldBounce 暂停策略（已默认暂停，统计不显著）
- 不改 `--auto` 的四策略评分权重（独立系统，超出本次范围）
- ATR 止损若回测显示不优于 no_stop，则保留为披露用不强行改执行（尊重数据，不为了改而改）

## 验证标准
- 所有现有 223 个测试 + 新增测试通过
- 回测脚本输出 ATR 止损 vs 固定止损 vs no_stop 的对比表
- `--daily-action` 在 20260708 dry-run 能正常渲染（板块修复后命中数可能变化）