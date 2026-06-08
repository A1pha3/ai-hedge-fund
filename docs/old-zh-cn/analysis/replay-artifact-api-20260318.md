# 2026-03-18 Replay Artifact 摘要接口

## 1. 目的

P2-2 当前先走后端摘要接口，而不是直接做前端浏览页。目标是让研究侧至少可以不翻原始 JSONL，就能拿到：

1. `session_summary` 级基础绩效
2. 关键 funnel 指标
3. 按 ticker 的执行摘要

这样前端后续如果要补 artifact 浏览页，只需要消费这层接口，而不是直接扫 `data/reports`。

## 2. 当前接口

后端新增了两个受保护接口：

1. `GET /replay-artifacts/`
2. `GET /replay-artifacts/{report_name}`

路由位置：

1. `app/backend/routes/replay_artifacts.py`
2. `app/backend/services/replay_artifact_service.py`

这两个接口都走现有 JWT 保护链，与其他受保护 API 保持一致。

## 3. 列表接口

`GET /replay-artifacts/` 返回当前 `data/reports/*/session_summary.json` 可识别的 replay 列表。

每个 item 当前包含：

1. `report_dir`
2. `window.start_date / end_date`
3. `run_header.mode`
4. `run_header.plan_generation_mode`
5. `run_header.model_provider / model_name`
6. `headline_kpi`
7. `deployment_funnel_runtime`
8. `artifacts`

适用场景：

1. 浏览有哪些 replay 可用
2. 快速比较 run 的收益、交易日、利用率和 blocker 结构

## 4. 详情接口

`GET /replay-artifacts/{report_name}` 在列表字段基础上额外返回：

1. `ticker_execution_digest`
2. `final_portfolio_snapshot`

其中 `ticker_execution_digest` 当前按 ticker 聚合：

1. `buy_count`
2. `sell_count`
3. `final_long`
4. `realized_pnl`
5. `max_unrealized_pnl_pct`
6. `entry_score`

适用场景：

1. 快速确认一个 replay 的主要成交对象是谁
2. 判断 run 更像低利用率、弱 re-entry，还是静态持仓问题

## 5. 字段来源

当前接口沿用 P2-1 模板中的来源边界：

1. `session_summary.json` 负责 run header 与基础 KPI
2. `daily_events.jsonl` 补算平均利用率、漏斗计数、blocker 聚合、ticker 执行摘要
3. `pipeline_timings.jsonl` 补算 runtime

当前没有在接口里自动判断：

1. benchmark guardrail 结论
2. taxonomy 归类
3. 是否应进入专项分析

这三类仍保持在研究层人工判定，避免把解释逻辑提前硬编码进接口。

## 6. 当前范围与限制

这版接口刻意只做最小实现：

1. 只读本地 `data/reports` 目录
2. 不写数据库
3. 不做前端页面
4. 不返回原始 `daily_events` 明细

它的职责只到“把 run 摘要拉平到可消费 JSON”。如果后续要做 UI，优先在这层之上继续扩展，而不是让前端直接解析 artifact 文件。

## 7. 当前收口

截至 `2026-03-18`，P2-2 可以先收口为：

1. 已有最小可用的 backend 摘要接口。
2. 它已经覆盖任务清单要求的三类信息：`session_summary`、关键 funnel 指标、按 ticker 执行摘要。
3. 前端 artifact 浏览页可以留到下一阶段再做，不阻塞研究消费。
