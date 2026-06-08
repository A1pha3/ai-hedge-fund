# 5. Web 应用 (前端 + 后端)

> 本节对应主文档 §5,包含后端 API 端点、前端界面组件。

## 5.1 后端 API

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 对冲基金运行 (SSE 流式) | ✅ | `POST /api/hedge-fund/run` — 实时 SSE 推送 |
| 2 | 回测运行 (SSE 流式) | ✅ | `POST /api/hedge-fund/backtest` |
| 3 | 健康检查 | ✅ | `GET /api/health` |
| 4 | 缓存管理 | ✅ | `app/backend/routes/cache.py` |
| 5 | 数据源管理 | ✅ | `app/backend/routes/data_sources.py` |
| 6 | Flow 工作流管理 | ✅ | `app/backend/routes/flows.py` — 工作流 CRUD |
| 7 | Flow 运行管理 | ✅ | `app/backend/routes/flow_runs.py` |
| 8 | Ollama 本地模型管理 | ✅ | `app/backend/routes/ollama.py` |
| 9 | LLM 模型列表 | ✅ | `app/backend/routes/language_models.py` |
| 10 | API Key 管理 | ✅ | `app/backend/routes/api_keys.py` |
| 11 | LLM 调用指标 | ✅ | `app/backend/routes/llm_metrics.py` — 调用统计和性能分析 |
| 12 | 回放制品管理 | ✅ | `app/backend/routes/replay_artifacts.py` |
| 13 | 研究回溯审计 | ✅ | `GET /api/research/lookback-audit` |
| 14 | 组合归因分析 | ✅ | `GET /api/portfolio/attribution` — Brinson 归因 |
| 15 | 组合调整模拟器 | ✅ | `POST /api/portfolio/simulate-adjustment` |
| 16 | 管理员审计 | ✅ | `app/backend/routes/admin_audit.py` |
| 17 | 用户认证 (JWT) | ✅ | `app/backend/routes/auth.py` + invite 系统 |

## 5.2 前端界面

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | ReactFlow 工作流编辑器 | ✅ | 可视化编排 Agent 节点 |
| 2 | 登录/注册/密码重置 | ✅ | 完整的用户认证流程 |
| 3 | 管理员面板 | ✅ | `AdminPage.tsx` — 用户/invite 管理 |
| 4 | 归因分析面板 | ✅ | `AttributionPage.tsx` — Brinson 归因可视化 |
| 5 | 风险监控面板 | ✅ | `risk-monitor-panel.tsx` |
| 6 | Lookback 审计面板 | ✅ | `lookback-audit-panel.tsx` — 历史选股效果回溯 |
| 7 | 期望值卡片 | ✅ | `expectation-card.tsx` |
| 8 | Edge Card 边缘卡片 | ✅ | `edge-card.tsx` |
| 9 | 缓存状态指示器 | ✅ | `cache-status-indicator.tsx` |
| 10 | 组合调整模拟器 | ✅ | `adjustment-simulator.tsx` |
| 11 | 设置面板 | ✅ | `settings/` 目录 |
| 12 | **回测净值曲线 (P0-4)** | ✅ | `backtest-equity-curve.tsx` — KPI 卡片 + 净值曲线 + 水下图 + 月度热力图 (R20.7 完成) |

---

**相关章节**: [3. 回测与验证](./backtesting.md) | [9. CLI 工具](./cli-tools.md)
