# Feature Flags — Operator-Facing Env Vars

> 本文档列出影响**输出展示 / 过滤行为**的环境变量 (operator 可切换的 feature flags).
> 内部调优参数 (阈值、并发数等) 不在此列 — 见各自模块 docstring.

所有 flag 默认 OFF (status quo 保持). 通过 `FLAG=1 uv run python ...` 启用.

## 条件单 / 前门门控

| Flag | 默认 | 效果 | 引入 |
|------|------|------|------|
| `CONDITIONAL_ORDER_FILTER_VERDICT` | off | 条件单 (CLI + 券商导出) 只输出 BUY-verdict 标的. AVOID/HOLD-rated 标的不生成条件单, 防止真实券商 CSV 导入非 BUY 标的. 三入口点全部过滤 (attach + CLI + export 安全网). | autodev-32 session 4 |

## 评分展示

| Flag | 默认 | 效果 | 引入 |
|------|------|------|------|
| `GRADE_RECOLOR_BY_VERDICT` | off | `--top-picks` 的 grade 按前门判决重新着色 (BUY=原色, AVOID=红, HOLD=黄). 替代默认的 ⚠ 追加模式 (Option B). 剥除原 ANSI 色码避免双色歧义. | autodev-32 session 5 |

## Daily Action

| Flag | 默认 | 效果 |
|------|------|------|
| `DAILY_ACTION_CACHE_REFRESH` | on (设 `false` 关闭) | `--auto` 结束后刷新 daily-action 缓存 (price/fund_flow/industry). 设 `false` 跳过. |
| `DAILY_ACTION_REGIME_SIZING` | 安全降级 | 扫描器仍计算 crisis/risk_off 的 1.2×/1.1× 请求，但当前 canonical auto manifest 尚未携带可重算的 regime 授权证据，v2 ledger 会 fail-closed 到单票 10%，并输出 `regime_authorization_evidence_unavailable`。在 manifest 完成 regime evidence 绑定前，本 flag **不会产生实际加仓**；设 `false` 可关闭请求侧 regime sizing。 |
| `DAILY_ACTION_DISABLED_SETUPS` | `oversold_bounce` | 暂停的 setup 名 (逗号分隔). 特殊值 `none` 清空默认, 恢复全部 setup. |

## 使用示例

```bash
# 条件单只导出 BUY (real-money 安全)
CONDITIONAL_ORDER_FILTER_VERDICT=1 uv run python src/main.py --export-conditional-orders

# grade 按 verdict 着色 (替代 ⚠ 追加)
GRADE_RECOLOR_BY_VERDICT=1 uv run python src/main.py --top-picks

# 组合使用
CONDITIONAL_ORDER_FILTER_VERDICT=1 GRADE_RECOLOR_BY_VERDICT=1 uv run python src/main.py --auto
```

## 设计原则 (autodev-32)

这些 flag 遵循 contract §feature-flag: **默认 OFF 保持 status quo**, owner 可随时 opt-in 测试.
owner 如需将某 flag 切为默认 ON, 需明确批准 (属 owner-only 行为变更).
