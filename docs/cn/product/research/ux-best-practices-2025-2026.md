# R20.9 前端 UX 审计 + 行业最佳实践 (2026-06-08)

> GAMMA 产品经理 UX 研究。覆盖前端代码审计、行业 UX 趋势调研、Top 3 改进建议。

---

## 一、前端 UX 问题清单

### 1. 缺失的 Loading 状态

| # | 文件 | 问题 | 严重性 | 建议 |
|---|------|------|--------|------|
| L-1 | `backtest-output.tsx:402-414` | BacktestOutput 组件无 loading 状态 — 回测运行时用户看到空白，不知道是否在加载 | HIGH | 添加 Skeleton 占位 + 进度条指示器 |
| L-2 | `backtest-equity-curve.tsx:234-236` | BacktestEquityCurve 在 `dailyResults.length < 2` 时直接返回 null，无"数据不足"提示 | MEDIUM | 添加空状态提示："数据点不足 (需至少2天)，等待回测数据..." |
| L-3 | `backtest-output.tsx:9-31` | BacktestProgress 仅显示文字状态，无动画/进度条/步骤指示 | MEDIUM | 添加分步进度条 (数据获取 → 策略计算 → 组合优化 → 回测执行) |
| L-4 | `backtest-output.tsx:34-148` | BacktestTradingTable 首次渲染前无 skeleton | LOW | 添加 Table Skeleton (3-5 行占位) |

### 2. 缺失的 Error 状态

| # | 文件 | 问题 | 严重性 | 建议 |
|---|------|------|--------|------|
| E-1 | `backtest-output.tsx:395-415` | BacktestOutput 无 error boundary — 后端数据格式异常时白屏 | HIGH | 添加 ErrorBoundary + fallback UI ("数据加载失败，请重试") |
| E-2 | `backtest-equity-curve.tsx:248-249` | `portfolio_value` 为 NaN/Infinity 时导致 SVG 渲染崩溃 | HIGH | 添加数值校验: `if (!isFinite(day.portfolio_value)) return null` |
| E-3 | `backtest-output.tsx:55-56` | `ticker_details` 字段可能为 undefined/null (后端返回格式变更时) | MEDIUM | 添加防御性检查 `backtestResult.ticker_details?.forEach(...)` |

### 3. 可访问性 (Accessibility) 问题

| # | 文件 | 问题 | 严重性 | 建议 |
|---|------|------|--------|------|
| A-1 | `backtest-equity-curve.tsx:89-123` | SVG 图表无 aria-label，屏幕阅读器无法识别 | HIGH | 添加 `role="img" aria-label="回测净值曲线: 从 ¥X万 到 ¥Y万，总收益 Z%"` |
| A-2 | `backtest-equity-curve.tsx:157-173` | DrawdownChart SVG 无可访问性标注 | HIGH | 添加 `role="img" aria-label="最大回撤图: 最大回撤 X%"` |
| A-3 | `backtest-output.tsx:100-147` | Table 缺少 caption 元素 (WCAG 2.1 要求) | MEDIUM | 添加 `<caption className="sr-only">回测交易活动表</caption>` |
| A-4 | `backtest-output.tsx:119` | 使用 `idx` 作为 key — 当列表更新时 React 无法正确 diff | MEDIUM | 使用组合 key: `key={${row.date}-${row.ticker}-${idx}}` |
| A-5 | `backtest-equity-curve.tsx:214-228` | MonthlyReturnsHeatmap 使用 `title` 属性做 tooltip — 键盘用户无法触发 | LOW | 改用 `aria-label` 或自定义 tooltip 组件 |
| A-6 | 所有 backtest 组件 | 无 focus-visible 样式 — 键盘导航无视觉反馈 | MEDIUM | 为可交互元素添加 `focus-visible:ring-2 focus-visible:ring-ring` |
| A-7 | `backtest-output.tsx:130` | `$` 符号硬编码，不支持中文货币环境 | LOW | 根据 ticker 前缀动态显示 ¥ 或 $ |

### 4. 视觉一致性 (Inconsistency) 问题

| # | 文件 | 问题 | 严重性 | 建议 |
|---|------|------|--------|------|
| V-1 | `AttributionPage.tsx:237` | 使用硬编码 `bg-zinc-950/text-zinc-100` 而非 design token (`bg-background/text-foreground`) — 与暗色主题不兼容，在亮色主题下完全不可读 | HIGH | 替换为 `bg-background text-foreground` |
| V-2 | `AttributionPage.tsx` 全文 | 所有颜色用 `text-zinc-*` 硬编码，不跟随主题变量 | HIGH | 替换为 `text-muted-foreground`, `text-foreground` 等 design token |
| V-3 | `AttributionPage.tsx:244-248` | 按钮使用原生 `<button>` + 内联样式，不用 shadcn Button 组件 | MEDIUM | 替换为 `<Button variant="default">` 保持一致性 |
| V-4 | `backtest-output.tsx:130` | 价格前缀硬编码 `$` (美元)，但 A-share 数据应显示 `¥` | MEDIUM | 根据 `row.ticker` 判断货币符号 |
| V-5 | `backtest-output.tsx` vs `backtest-equity-curve.tsx` | 两处重复计算 KPI (Total Return, Win Rate, Max Drawdown) — 数值可能不一致 | MEDIUM | 提取共享 hook `useBacktestMetrics(agentData)` |
| V-6 | `backtest-equity-curve.tsx:98` | Y轴标签固定中文"万" — 国际化缺失 | LOW | 根据语言环境显示 "万" 或 "10K" |

### 5. 移动端响应式缺陷

| # | 文件 | 问题 | 严重性 | 建议 |
|---|------|------|--------|------|
| R-1 | `Layout.tsx:20-24` | `COMPACT_VIEWPORT_WIDTH = 1200` — 在平板 (768-1024) 上侧栏全部折叠，内容区无导航入口 | HIGH | 添加汉堡菜单/抽屉导航作为折叠时的入口 |
| R-2 | `backtest-output.tsx:100-147` | Trading table 10 列，无横向滚动提示，移动端溢出 | HIGH | 外层添加 `overflow-x-auto` + 滚动指示箭头 |
| R-3 | `backtest-equity-curve.tsx:270` | KPI grid `grid-cols-2` 最小 2 列，在小屏 (320px) 上卡片太窄 | MEDIUM | 改为 `grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-6` |
| R-4 | `backtest-equity-curve.tsx:89` | SVG 固定 viewBox 800x200，超窄屏幕挤压变形 | LOW | 设置 `preserveAspectRatio="xMidYMid meet"` |

### 6. 代码质量问题

| # | 文件 | 问题 | 严重性 | 建议 |
|---|------|------|--------|------|
| C-1 | `backtest-output.tsx:156` | `console.log("outputData", outputData)` — 生产环境遗留调试日志 | MEDIUM | 移除或替换为 `if (import.meta.env.DEV) console.log(...)` |
| C-2 | `backtest-output.tsx:51` | `any[]` 类型 — 失去类型安全 | LOW | 定义 `BacktestRow` interface |
| C-3 | `backtest-output.tsx:275` | `Object.entries` 类型断言为 `[string, any]` | LOW | 定义 Position interface |

---

## 二、行业 UX 最佳实践 (2025-2026)

### 来源
- Smashing Magazine: [UX Strategies for Real-Time Dashboards](https://www.smashingmagazine.com/2025/09/ux-strategies-real-time-dashboards/)
- TradingView Platform Redesign Case Study (RonDesignLab)
- Fintech Design Trends 2026 (Outcrowd)
- Trading App Design Complete Guide (Lollypop Design)
- Dashboard Design UX Patterns (Pencil & Paper)
- Raw.Studio: UX Rules for Real-Time Performance Dashboards
- 同花顺/Choice/聚宽/米筐 2025-2026 产品观察

### 核心模式

#### 1. 交易 Dashboard 布局模式

**Bloomberg/TradingView 模式 (我们已采用)**:
- 左侧面板: 监控/输入 (我们: LeftSidebar — analyst nodes)
- 中央区域: 主图表/可视化 (我们: ReactFlow canvas + TabContent)
- 右侧面板: 详情/属性 (我们: RightSidebar — node properties)
- 底部面板: 日志/输出 (我们: BottomPanel — backtest output)

**行业趋势 (2025-2026)**:
- **可拖拽/可调整大小的面板** — 用户自定义布局 (TradingView, Bloomberg)
- **多标签工作区** — 同时查看多个策略/股票 (TradingView 2026 新增)
- **AI 摘要卡片** — 顶部显示 AI 生成的市场概要 (同花顺问财 2025)
- **上下文感知面板** — 点击股票自动展开相关数据 (Choice 终端)

#### 2. 数据可视化最佳实践

| 图表类型 | 用途 | 行业标准 | 我们现状 |
|----------|------|----------|----------|
| **KPI 卡片** | 顶部关键指标一目了然 | 大字体数值 + 小字体标签 + 颜色编码趋势 | 已有 (backtest-equity-curve.tsx) |
| **净值曲线** | 策略 vs 基准收益对比 | Plotly/D3.js 交互式，hover tooltip + 时间缩放 | 已有 (SVG静态) — 缺交互 |
| **水下图** | Drawdown 持续时间 + 恢复 | 面积图 + 颜色编码严重度 | 已有 (SVG静态) |
| **月度热力图** | 月度收益模式识别 | Year x Month grid, RdYlGn 色阶 | 已有 (CSS flex) |
| **因子瀑布图** | 归因分析 | 交互式 Waterfall chart (Plotly) | AttributionPage 已有基础版 |
| **Agent 推理卡片** | 多 Agent 信号汇总 | 折叠卡片 + 信号灯 + 点击展开 | 缺失 — 仅显示 JSON |

**关键洞察**: 我们的 SVG 自绘图表是正确的轻量级选择 (无需引入 Plotly.js 3MB)，但缺少以下行业标准交互:
1. **Hover tooltip** — 鼠标悬停显示精确数值和日期
2. **时间范围缩放** — 1M/3M/6M/1Y/ALL 快速切换
3. **十字准线** — 对齐所有图表的时间轴

#### 3. 实时数据展示模式 (SSE/WebSocket)

**行业模式 (2025)**:
| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **乐观更新** | 先显示预期结果，后端确认后修正 | Agent 信号推送 |
| **流式渲染** | SSE 逐条追加，不重载整个列表 | 我们已采用 (backtest streaming) |
| **水位线** | 显示"最后更新时间" + 数据新鲜度指示 | 实时行情 |
| **渐进式加载** | Skeleton → 部分数据 → 完整数据 | 回测结果加载 |
| **离线指示** | 断连时显示"数据可能过期"提示 | 长时间运行的回测 |

**我们的现状**: SSE 流式渲染已就绪，但缺少:
- 数据新鲜度指示 (最后更新时间戳)
- 断连/重连状态提示
- 流式进度指示 (X/Y 步骤完成)

#### 4. 量化工具 Onboarding 设计

**行业最佳实践 (2025-2026)**:

1. **渐进式披露 (Progressive Disclosure)**
   - 首次使用: 仅显示 "输入股票代码 → 运行" 的最小界面
   - 高级功能: 折叠在 "高级选项" 下
   - 专家模式: 全部面板展开 (当前默认)

2. **空状态引导 (Empty State Onboarding)**
   - 首次进入: 显示 "欢迎 + 快速开始教程" 而非空白画布
   - 引导步骤: ①选择股票 → ②配置Agent → ③运行分析 → ④查看结果

3. **模板/预设 (Templates/Presets)**
   - 预置策略模板: "价值投资", "技术分析", "多因子融合"
   - 一键复现经典策略
   - 同花顺/聚宽均提供策略模板作为新用户入口

4. **上下文帮助 (Contextual Help)**
   - 每个面板右上角的 `?` 图标
   - 悬停提示解释专业术语 (Sharpe Ratio, Max Drawdown 等)
   - 交互式 tooltip 引导 (类似 TradingView 首次登录引导)

---

## 三、Top 3 UX 改进建议

### 改进 1: 回测加载状态 + 错误边界 (Impact: HIGH, Effort: S)

**问题**: 用户运行回测时，BacktestOutput 在数据到达前完全空白 — 没有任何反馈。

**方案**:
```
BacktestOutput 状态机:
  IDLE (未运行) → "点击运行开始回测" 空状态插图
  LOADING (运行中) → Skeleton + 进度步骤条 + 预估时间
  STREAMING (数据流入) → 渐进渲染已有组件 + 脉冲指示器
  COMPLETE (完成) → 完整结果展示
  ERROR (失败) → ErrorBoundary + 错误信息 + 重试按钮
```

**具体改动**:
- `backtest-output.tsx`: 添加状态判断逻辑，根据 `agentData` 和 `outputData` 的状态切换渲染
- 添加 `BacktestErrorBoundary` React ErrorBoundary 组件
- `backtest-equity-curve.tsx`: 数据不足时显示 "正在等待数据..." 占位

### 改进 2: AttributionPage 主题兼容 + 视觉一致性 (Impact: HIGH, Effort: S)

**问题**: AttributionPage 硬编码 `bg-zinc-950` — 在亮色主题下完全不可用。与其他页面使用 design token 的做法不一致。

**方案**:
- 替换所有 `text-zinc-*` / `bg-zinc-*` 为 `text-muted-foreground` / `bg-card` 等 design token
- 替换原生 `<button>` 为 shadcn `<Button>` 组件
- 替换原生 `<table>` 为 shadcn `<Table>` 组件
- 添加响应式处理 (当前表格在窄屏溢出)

### 改进 3: 首次使用引导 (Impact: MEDIUM, Effort: M)

**问题**: 新用户首次打开看到空白 ReactFlow 画布 + 三个空侧栏 — 不知道从何开始。

**方案**:
1. **空状态设计**: 当无 flow 数据时，中央显示引导卡片:
   ```
   ┌─────────────────────────────┐
   │   🎯 AI Hedge Fund          │
   │                              │
   │   Quick Start:               │
   │   1. 输入股票代码 (左侧面板)  │
   │   2. 点击 "Run Analysis"     │
   │   3. 查看 Agent 分析结果      │
   │                              │
   │   [▶ Run Demo with AAPL]     │
   └─────────────────────────────┘
   ```
2. **预置模板**: 提供 2-3 个预设 flow (价值分析, 技术分析, 综合分析)
3. **键盘快捷键提示**: 底部状态栏显示 `Cmd+B 侧栏 | Cmd+J 面板 | Cmd+O 适配`

---

## 四、行业趋势总结

| 趋势 | 成熟度 | 与我们相关 | 行动 |
|------|--------|-----------|------|
| AI 驱动 Dashboard (自动选择指标/图表) | 早期 | 高 — 我们的 20-agent 架构天然适合 | 中期考虑 |
| 可拖拽面板布局 (TradingView 模式) | 成熟 | 中 — 当前固定布局足够 | 不做 (复杂度高) |
| 暗色主题为默认 | 成熟 | 高 — 量化用户偏好暗色 | 已有，确保一致性 |
| 实时协作 (多人编辑同一策略) | 早期 | 低 — 个人量化工具 | 不做 |
| 语音交互 (Bloomberg Voice) | 探索 | 低 | 不做 |
| 生成式图表 (Plotly Agentic Analytics) | 新兴 | 中 — AI 生成可视化 | 观察 |

---

**相关文档**: [industry-2025-2026.md](./industry-2025-2026.md) | [主文档](../feature-proposals.md)

**最后更新**: 2026-06-08
