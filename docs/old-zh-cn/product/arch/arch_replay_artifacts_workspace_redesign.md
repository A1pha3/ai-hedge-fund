# Replay Artifacts 一级工作台改造设计与执行计划

> 文档状态：Replay Artifacts 一级工作台改造记录
> 最近补充导航时间：2026-03-28 10:06:25 CST
> 相关专题：如果你当前关注的是双目标系统后续如何消费 artifact 和 workspace 结果，请从 [dual_target_system/README.md](./dual_target_system/README.md) 进入，而不是只停留在本前端工作台文档。

## 专题导航

本文档聚焦的是 Replay Artifacts 从 Settings 子页面升级为一级工作台的前端/交互/工作流设计，不负责定义双目标系统本身的目标模型、ExecutionPlan 扩展或 artifact 字段协议。

如果你现在继续推进的是“双目标系统如何接入 artifact、review、summary 和后续 workspace 消费”，建议同时参考以下文档：

1. [双目标系统专题目录](./dual_target_system/README.md)
2. [双目标系统数据结构与 Artifact Schema 规格](./dual_target_system/dual_target_data_contract_and_artifact_schema.md)
3. [双目标系统实施与代码改造计划](./dual_target_system/dual_target_implementation_plan.md)
4. [选股优先优化方案实施设计文档](./arch_optimize_implementation.md)

## 0. 当前落地状态

截至 2026-03-25，本文档描述的第一阶段主线改造已经完成，文档不再只是“待实施设计”，同时也是本轮前端结构升级的落地记录。

当前已完成事项：

1. 已在 app/frontend/src/services/tab-service.ts 中新增 replay-artifacts tab 类型，并补齐 createReplayArtifactsTab、createTabContent 与 restoreTab 对 replay-artifacts 的支持。
2. 已在 app/frontend/src/contexts/tabs-context.tsx 中扩展 TabType，并为 replay-artifacts 绑定固定 tab id，保证刷新恢复时不会落到 unsupported type。
3. 已新增一级工作台容器 app/frontend/src/components/workspaces/replay-artifacts-workspace.tsx，用于承接独立 workspace 布局。
4. 已在 app/frontend/src/components/Layout.tsx 与 app/frontend/src/components/layout/top-bar.tsx 中增加 Replay Artifacts 顶部一级入口，用户可直接打开独立 tab。
5. 已改造 app/frontend/src/components/settings/settings.tsx，Settings 中不再直接渲染完整 Replay Artifacts 页面，而是改为轻量说明卡和“打开工作台”按钮。
6. 已改造 app/frontend/src/components/settings/replay-artifacts.tsx，使其支持 settings 与 workspace 双模式；其中 workspace 模式已使用左栏 Report Rail、中栏 Main Analysis Canvas、右栏 Inspector 的三段式布局。
7. 现有业务能力已保留且可继续使用，包括 report 列表加载、report detail、selection artifact 按 trade_date 浏览、funnel diagnostics、research feedback 读取与追加，以及 report 级 cache benchmark 展示。
8. 已补充 app/frontend/src/components/replay-artifacts/ 组件目录，并提取 Replay Artifacts Settings 入口卡、Workspace Inspector、Selection Review Markdown 折叠区，避免继续把职责堆在单一页面文件内。
9. 长文本 review markdown 已改为折叠区展示，workspace 模式的右侧 inspector 已抽离为独立组件，满足内容分层与工程职责拆分目标。
10. app/frontend 下 npm run build 已再次通过，说明本轮结构升级与后续组件拆分均未破坏 TypeScript 与 Vite 构建链路。
11. 2026-03-25 已完成一轮本地运行级烟测：后端可正常登录并返回 replay 列表、report detail 与 trade_date detail；样本报告 paper_trading_window_20260316_20260323_live_m2_7_20260323 的 selection artifact 数据可正常读取。
12. app/frontend 已补充 Vitest + Testing Library 最小前端测试基建，并新增 replay-artifacts tab、Settings 入口卡、Workspace Inspector、workspace 默认选中报告逻辑四类自动化回归测试；当前共 4 个测试文件、5 个测试用例通过。

当前仍未完成事项：

1. 还未完成真正的浏览器内交互自动化回归；当前环境已完成“页面可访问 + 接口闭环”层面的运行验证，但未做带点击和截图的端到端 UI 自动化。
2. Report Rail 的多维筛选、跨报告对比和更细粒度的 inspector 导航仍属于后续迭代，不在本轮一级工作台升级的必交范围内。

后续章节中，凡是“建议新增”与“已实现”存在差异时，以本节“已完成事项”为准。

## 1. 文档目的

本文档用于定义 Replay Artifacts 从 Settings 子页面升级为一级工作台的完整改造方案，目标是为后续前端开发提供一份可直接执行的设计基线，而不是停留在抽象产品建议。

本文档覆盖以下内容：

1. 为什么当前 Settings 内嵌方案已经不适合继续承载 Replay Artifacts。
2. 一级工作台的目标信息架构、布局方案与交互模型。
3. 在现有 tab/workbench 前端架构下的最小侵入落地方式。
4. 具体代码改造范围、分阶段执行计划、测试方案与验收标准。

本文档面向的直接读者包括：

1. 前端开发者
2. 产品设计者
3. 后端接口维护者
4. 后续承担实现与联调的人

---

## 2. 背景与问题定义

### 2.1 当前现状

Replay Artifacts 当前被放置在 Settings 容器内部，作为一个二级 section 渲染。现有实现具备以下事实：

1. Tab 系统当前仅区分 flow 与 settings 两类 tab。
2. Settings 页面左侧为配置导航，右侧内容区域受限于较窄的内容宽度。
3. Replay Artifacts 已经不只是配置项，而是一个承担研究复盘、产物浏览、反馈回写、cache benchmark 审视的分析工作区。

当前前端代码中的结构性事实如下：

1. app/frontend/src/services/tab-service.ts 只支持 flow 和 settings 两类 tab。
2. app/frontend/src/components/Layout.tsx 的顶部入口目前只能直接打开 Settings。
3. app/frontend/src/components/settings/settings.tsx 使用 Settings 左侧导航和右侧 max-w-4xl 容器承载 Replay Artifacts。
4. app/frontend/src/components/settings/replay-artifacts.tsx 已经承载大量浏览、筛选、详情和反馈交互。

### 2.2 当前问题

当前方案的主要问题不是局部 CSS，而是信息架构错位。

问题分为四类：

1. 入口层级过深
   Replay Artifacts 需要先进入 Settings，再切换到对应 section，路径过长，不符合高频研究操作的访问预期。

2. 容器宽度不适配
   Settings 右侧内容区存在明显的宽度约束，长 report 名、长路径、模型标识、reason、blocker、prompt 等内容只能被动折行，导致视觉密度过高。

3. 语义定位错误
   Settings 应承载“系统配置”，Replay Artifacts 实际上承载“研究工作台”。两者在任务类型、停留时长、信息密度和交互复杂度上完全不同。

4. 扩展性受限
   当前页面已经开始展示 selection artifact、funnel diagnostics、feedback records、cache benchmark 等内容。后续如果继续增加对比、筛选、批注、侧栏 inspector 等能力，Settings 容器会持续成为上限。

### 2.3 结论

Replay Artifacts 不应继续作为 Settings 的一个 section 存在，而应升级为一级工作台，与 Settings 平级。

这不是单纯的视觉美化，而是职责边界重构。

---

## 3. 设计目标

### 3.1 总体目标

把 Replay Artifacts 改造为一个适合研究、复盘和证据浏览的一级工作台，在不破坏现有 tab/workbench 架构的前提下，显著提升以下能力：

1. 可达性
2. 可读性
3. 可扩展性
4. 任务完成效率

### 3.2 具体目标

本次改造需要实现以下目标：

1. 顶部或主工作台区域可直接打开 Replay Artifacts 一级 tab。
2. Replay Artifacts 脱离 Settings 的 max-width 约束，获得完整工作台宽度。
3. 页面布局从单列详情页升级为适合浏览大量报告的三段式工作台。
4. 报告列表、报告摘要、详情钻取、路径信息、反馈区之间的层次更加清晰。
5. 保持现有后端接口和核心数据契约可复用，优先降低首轮改造风险。

### 3.3 非目标

本次设计不以以下内容为目标：

1. 不重写后端 replay artifact 数据模型。
2. 不在第一阶段引入复杂的多报告对比引擎。
3. 不在第一阶段实现数据库级 research feedback 工作流重构。
4. 不强制引入传统路由体系。

---

## 4. 现有架构约束

### 4.1 前端不是传统路由应用

当前前端是 tab/workbench 结构，而不是标准的页面路由应用。其核心特征是：

1. 顶部存在固定 Top Bar。
2. 主内容由 TabBar 和 TabContent 管理。
3. 左右侧栏和底部面板由 Layout 控制。
4. Settings 本身也是通过 tab 打开的。

因此，Replay Artifacts 最合理的升级路径不是增加一个独立路由页，而是新增一种一级 tab 类型。

### 4.2 现有代码约束

目前已有代码说明以下约束真实存在：

1. tab-service.ts 中 TabData.type 只支持 flow 和 settings。
2. Layout.tsx 中 onSettingsClick 直接调用 createSettingsTab。
3. settings.tsx 中 Replay Artifacts 作为 settings section 之一，由 selectedSection 切换。
4. replay-artifacts.tsx 当前已包含较多业务渲染逻辑，适合作为“业务内容层”复用，不适合作为“页面容器层”继续耦合在 Settings 内。

### 4.3 设计原则

设计必须遵循以下原则：

1. 最小侵入
   第一阶段尽量复用现有 replay-artifacts.tsx 的业务能力，不推倒重写。

2. 容器与内容分离
   将 Settings 容器职责与 Replay Artifacts 内容职责拆开。

3. 先完成一级入口，再迭代高级交互
   先解决入口深、布局窄、层次乱的问题，再追加二期增强。

4. 保持恢复与持久化语义一致
   新 tab 类型应兼容现有 tab 的 restore 逻辑，避免工作台重启后状态异常。

---

## 5. 目标方案总览

### 5.1 目标定位

Replay Artifacts 升级为一级工作台后，建议在产品语义上定位为：

1. 对外展示名：Replay Artifacts
2. 内部定位：研究复盘工作台
3. 主要任务：浏览报告、筛选样本、查看证据、追踪执行阻塞、回写反馈

### 5.2 一级入口方案

建议新增一级入口，而不是继续嵌在 Settings 中。入口优先级如下：

1. 顶部 Top Bar 增加 Replay Artifacts 直接入口。
2. TabService 支持创建 Replay Artifacts tab。
3. Settings 中保留一个轻量跳转卡或说明卡，而不是继续渲染完整页面。

这样可以同时满足两类用户：

1. 高频研究用户可以直接进入一级工作台。
2. 习惯从 Settings 进入的用户仍能看到跳转入口，不会完全迷失。

### 5.3 页面布局总览

一级工作台采用三段式布局：

1. 左栏：Report Rail
   用于浏览报告列表、筛选状态、快速摘要。

2. 中栏：Main Analysis Canvas
   用于展示当前报告或当前交易日的核心分析内容。

3. 右栏：Inspector
   用于展示路径、产物文件、反馈、cache benchmark 细节和附加诊断。

这个布局比 Settings 单列内容区更符合实际使用模式，因为用户浏览 Replay Artifacts 时通常不是线性阅读，而是“列表选择 + 中间主读 + 右侧补充细节”的工作流。

---

## 6. 信息架构设计

### 6.1 一级工作台结构

工作台分为五个区域：

1. Workspace Header
2. Report Rail
3. Summary Strip
4. Main Analysis Canvas
5. Inspector Panel

### 6.2 Workspace Header

Header 承担以下职责：

1. 显示工作台标题与简要说明。
2. 提供刷新按钮。
3. 提供筛选入口，例如按模型、日期范围、状态、是否存在 cache benchmark、是否存在 feedback。
4. 显示当前选中报告的关键元信息。

建议 Header 仅保留高频控制项，不承载大段描述。

### 6.3 Report Rail

左栏 Report Rail 用于承载报告列表，不再只显示一个被动下拉框或简单卡片。

每个报告卡建议展示：

1. 紧凑标题
2. 时间窗口
3. 模型标签
4. 产物数量或关键能力标签
5. cache benchmark 状态摘要
6. feedback 数量或是否已有人工结论

Report Rail 的目标是让用户在不点开详情的情况下，先做一轮粗筛。

### 6.4 Summary Strip

中栏顶部增加 Summary Strip，显示当前报告的关键指标摘要，建议包括：

1. 报告类型
2. 时间窗口
3. 交易日数量
4. selection artifact 覆盖状态
5. cache benchmark 结果
6. feedback 覆盖状态

Summary Strip 用于让用户在切换报告时立即获得上下文，而不是直接掉进长页面正文。

### 6.5 Main Analysis Canvas

中栏主体用于展示主分析内容。建议使用 section stack，而不是超长一页平铺。

建议默认顺序如下：

1. Replay Summary
2. Selection Artifact Overview
3. Funnel Diagnostics
4. Cache Benchmark Overview
5. Day Detail Viewer
6. Research Feedback Timeline

其中 Day Detail Viewer 需要支持按 trade_date 切换，避免所有日期细节全部展开导致页面失控。

### 6.6 Inspector Panel

右栏用于承载补充信息和长文本信息，适合放置以下内容：

1. 报告目录与关键文件路径
2. session_summary.json 对应产物状态
3. window_review、selection_review、daily_events 等入口
4. 当前 trade_date 的原始 artifact 路径
5. cache benchmark 原始指标细节
6. feedback 写入区

右栏的核心目的不是展示最重要的内容，而是接住那些“有价值但不应挤占主阅读区域”的信息。

---

## 7. 交互设计

### 7.1 核心交互流程

目标工作流如下：

1. 用户从 Top Bar 或已有 tab 直接打开 Replay Artifacts。
2. 用户在左栏浏览报告列表，选择一个报告。
3. 中栏显示报告摘要与关键分析模块。
4. 用户切换交易日查看 selection review 和 execution blocker。
5. 用户在右栏查看路径、原始产物和补充指标。
6. 用户提交或回看 feedback。

### 7.2 默认焦点策略

建议默认策略如下：

1. 首次进入时自动选中最近一个报告。
2. 如果存在最近浏览记录，则优先恢复最近一次选中的报告。
3. 切换报告时，默认落在 Overview section，而不是直接跳到某个深层 detail。

### 7.3 长文本策略

长文件名、长路径、长模型名、长 blocker reason、长 prompt 文本统一遵循以下策略：

1. 主阅读区展示压缩后的可读标签。
2. Inspector 中展示完整值。
3. 对路径类字段，优先突出 leaf 名称，其次展示完整路径。
4. 对推理文本类字段，优先展示摘要，可展开查看全文。

### 7.4 空状态与异常状态

需要显式设计以下状态：

1. 无报告
2. 报告加载中
3. 详情加载失败
4. 当前报告无 selection artifacts
5. 当前报告无 cache benchmark
6. 当前报告无 feedback

空状态不应只显示空白容器，而应告诉用户“缺什么”和“下一步能做什么”。

---

## 8. 前端技术设计

### 8.1 核心改造思路

建议将当前 Replay Artifacts 页面拆成两层：

1. Workspace 容器层
   负责一级页面布局、左右栏组织、工作台 header、选中状态与跨区域编排。

2. 业务内容层
   复用现有 replay-artifacts.tsx 中已经成熟的报告加载、摘要展示、细节渲染与 feedback 能力。

这样可以把布局升级与业务渲染解耦，降低一次性重写风险。

### 8.2 新增 tab 类型

需要在 TabService 中新增 replay-artifacts 类型。

目标能力如下：

1. createReplayArtifactsTab()
2. createTabContent() 支持 replay-artifacts
3. restoreTab() 支持 replay-artifacts
4. TabData.type 扩展为 flow、settings、replay-artifacts

这样可以确保新工作台与当前 tab 恢复机制兼容。

### 8.3 新增工作台容器组件

建议新增独立容器组件，命名建议如下二选一：

1. app/frontend/src/components/replay-artifacts/replay-artifacts-workspace.tsx
2. app/frontend/src/components/workspaces/replay-artifacts-workspace.tsx

建议采用第二种命名，以便后续工作台类页面统一收敛在 workspaces 目录。

该组件承担以下职责：

1. 渲染 workspace header
2. 管理当前选中的 report
3. 管理当前选中的 trade_date
4. 组织 left rail、main canvas、inspector 三段布局
5. 调用现有 API 服务获取列表与详情
6. 将数据状态下放给现有内容组件

### 8.4 现有组件的拆分建议

当前 replay-artifacts.tsx 不应继续同时承担“页面容器”和“业务区块”两种职责。

建议拆分为以下层次：

1. replay-artifacts-workspace.tsx
   一级工作台容器

2. replay-artifacts-browser.tsx
   主浏览逻辑容器，负责 report list、selection state、detail fetch

3. replay-artifacts-detail.tsx
   当前报告详情主内容

4. replay-artifacts-inspector.tsx
   路径、原始 artifact、附加元数据、feedback 操作区

5. 保留基础展示单元组件
   例如 PathPreviewCard、KPI 卡、状态徽标、摘要卡等

如果首轮不想拆得太细，最少也要完成以下分离：

1. 从 settings/replay-artifacts.tsx 中抽出独立容器
2. Settings 内只保留一个入口卡组件

### 8.5 Settings 的改造方式

Settings 不应再直接 render 完整 Replay Artifacts 页面，而应改为：

1. 显示简短说明
2. 提供 “Open Replay Artifacts Workspace” 按钮
3. 可附带最近报告数量、最后更新时间等摘要信息

这样 Settings 仍保留可发现性，但不再承担重内容浏览职责。

### 8.6 Top Bar 入口设计

Top Bar 建议新增 Replay Artifacts 一级入口，形式可选：

1. 独立按钮
2. 带图标的工具入口
3. 研究类入口分组中的一项

第一阶段推荐使用最简单的独立按钮，原因如下：

1. 改动面小
2. 发现性高
3. 便于验证用户是否开始高频使用该工作台

### 8.7 状态管理建议

工作台层建议管理以下状态：

1. selectedReportId
2. selectedTradeDate
3. reportFilter
4. inspectorCollapsed
5. activeSection

其中 selectedReportId 和 selectedTradeDate 可以在第一阶段存在组件局部状态中，不必一开始就引入全局 store 扩展。

### 8.8 API 复用策略

第一阶段尽量复用现有 replay artifact API，不建议同步做接口重构。

原因如下：

1. 当前后端已能提供列表和详情。
2. 当前需求核心是入口与布局重构，而不是数据不足。
3. 先把前端信息架构拉直，再决定是否需要二期接口聚合优化。

只有当首轮工作台落地后发现以下问题时，再考虑二期后端调整：

1. 左栏摘要字段仍不足
2. 详情加载过重
3. 需要跨报告对比视图

---

## 9. 目标文件改造范围

### 9.1 必改文件

第一阶段预计至少涉及以下文件：

1. app/frontend/src/services/tab-service.ts
2. app/frontend/src/contexts/tabs-context.tsx
3. app/frontend/src/components/Layout.tsx
4. app/frontend/src/components/layout/top-bar.tsx
5. app/frontend/src/components/settings/settings.tsx
6. app/frontend/src/components/settings/replay-artifacts.tsx

### 9.2 建议新增文件

建议新增以下文件：

1. app/frontend/src/components/workspaces/replay-artifacts-workspace.tsx
2. app/frontend/src/components/replay-artifacts/replay-artifacts-browser.tsx
3. app/frontend/src/components/replay-artifacts/replay-artifacts-inspector.tsx
4. app/frontend/src/components/replay-artifacts/replay-artifacts-entry-card.tsx

是否需要新增 replay-artifacts-detail.tsx 取决于首轮拆分深度。如果当前文件过大或嵌套复杂，建议同步拆出。

### 9.3 可选优化文件

若首轮开发时发现样式逻辑过于分散，可考虑同步整理：

1. app/frontend/src/services/replay-artifact-api.ts
2. app/frontend/src/lib/utils.ts
3. app/frontend/src/components/ui 目录中的通用展示组件

---

## 10. 分阶段执行计划

### 10.1 Phase 0：准备阶段

目标：明确边界，避免直接在现有大文件上粗暴堆逻辑。

执行项：

1. 盘点 replay-artifacts.tsx 中哪些逻辑属于布局层，哪些属于业务层。
2. 确认 top-bar.tsx 当前按钮扩展方式。
3. 确认 tabs-context 与 tab persistence 对新增类型的兼容点。
4. 明确是否已有可复用的 resizable panel 或 workspace shell 组件。

交付物：

1. 改造清单
2. 组件拆分草图

验收标准：

1. 不带代码改动也能输出一份精确的 file-level 改造列表。

### 10.2 Phase 1：一级入口落地

目标：让 Replay Artifacts 能以一级 tab 形式打开。

执行项：

1. 扩展 TabData.type。
2. 新增 createReplayArtifactsTab。
3. 实现 replay-artifacts tab content 渲染。
4. 在 Layout 或 Top Bar 中增加入口按钮。
5. 确保 restoreTab 能恢复 replay-artifacts。

交付物：

1. 新 tab 类型可打开、可关闭、可恢复。

验收标准：

1. 点击入口后可直接打开 Replay Artifacts。
2. 刷新或恢复 tab 状态后不会报 unsupported type。
3. npm run build 成功。

当前状态：已完成。

补充说明：

1. replay-artifacts 现已拥有固定 tab id，可避免重复开出多个同类工作台并确保 restore 语义稳定。
2. 顶部入口已以 Top Bar 独立按钮形式落地。

### 10.3 Phase 2：Settings 解耦

目标：Settings 不再承载完整 Replay Artifacts 页面。

执行项：

1. 把 Settings 中的 Replay Artifacts section 改为入口卡或说明卡。
2. 入口卡点击后打开一级 Replay Artifacts tab。
3. 保留必要摘要信息，避免 Settings 中完全空洞。

交付物：

1. Settings 内的轻量入口卡。

验收标准：

1. Settings 中不再渲染完整 Replay Artifacts 页面。
2. 用户仍可从 Settings 发现并打开该工作台。

当前状态：已完成。

补充说明：

1. 当前 Settings 中保留了说明卡、三段式能力摘要和“打开 Replay Artifacts 工作台”按钮。

### 10.4 Phase 3：一级 Workspace 三段式布局

目标：把 Replay Artifacts 从单列 settings 页面改造成适合持续分析的 workspace。

当前状态：已完成。

补充说明：

1. 当前 workspace 已采用左栏 Report Rail、中栏 Main Analysis Canvas、右栏 Inspector 的三段式布局。
2. selection artifact 浏览、feedback 与 cache benchmark 相关信息已按 workspace 使用场景重新编排。

### 10.5 Phase 4：内容分层优化与工程质量

目标：在完成功能迁移后，继续减少单文件膨胀，提升内容密度控制与可维护性。

当前状态：已完成本轮必交范围。

补充说明：

1. Settings 内的 Replay Artifacts 入口卡已提取为独立组件。
2. Workspace 右侧 Inspector 已提取为独立组件。
3. 长文本 Selection Review Markdown 已改为可折叠区域，避免主画布持续被长文本淹没。
4. 当前仍可继续做更细粒度拆分，但已满足“关键新增组件职责清晰，不继续把所有逻辑堆回单文件”的本轮验收要求。

### 10.6 Phase 5：验证与收口

目标：确保改造后可稳定使用并可继续迭代。

当前状态：已完成本轮必交范围。

补充说明：

1. 2026-03-25 已再次执行 app/frontend 下 npm run build，构建通过。
2. 已在 localhost 启动 backend 与 frontend dev server，并确认前端页面地址可正常打开。
3. 已重新完成一轮接口级烟测：登录、report 列表、report detail、trade_date detail 均可正常访问。
4. 样本报告 paper_trading_window_20260316_20260323_live_m2_7_20260323 已确认可返回 6 个 trade_date，且 2026-03-23 日级详情包含 selection snapshot、review markdown 与 funnel diagnostics。
5. 已补充最小前端自动化回归：TabService 对 replay-artifacts 的 create/restore、Settings 入口卡打开行为、Inspector 关键渲染，以及 workspace 初始默认选中报告逻辑均已有测试覆盖。
6. 当前环境无法直接做浏览器内点击式 DOM 自动化，因此更高层交互验证仍以“页面可访问 + 接口闭环 + 构建通过 + 关键组件级自动化测试通过”为准；tab restore 与 Settings 跳转语义则由现有实现和自动化用例共同保证。

---

## 11. 开发任务拆解建议

建议把实际开发任务拆成以下顺序，避免多人并行时互相冲突：

1. 任务 A：TabService 扩展与 tab 恢复支持
2. 任务 B：Top Bar 新增 Replay Artifacts 一级入口
3. 任务 C：新建 Replay Artifacts Workspace 容器骨架
4. 任务 D：Settings 中的 Replay Artifacts section 改造为入口卡
5. 任务 E：将现有 replay-artifacts 内容迁移进 workspace 主体
6. 任务 F：引入左栏 Report Rail 与右栏 Inspector
7. 任务 G：长文本分层与视觉整理
8. 任务 H：构建、烟测、文档补充

若只允许单人连续开发，建议严格按以上顺序执行。

---

## 12. 验收标准

### 12.1 功能验收

以下条件全部满足才视为功能完成：

1. Replay Artifacts 可从 Top Bar 直接打开。
2. Replay Artifacts 可作为独立 tab 存在。
3. 刷新后 tab 可被正常恢复。
4. Settings 中不再承载完整 Replay Artifacts 页面。
5. 报告列表、报告详情、交易日详情、feedback、cache benchmark 都仍可访问。

### 12.2 体验验收

以下条件全部满足才视为体验改造达标：

1. 宽屏下不再受 max-w-4xl 限制。
2. 长路径和长 report 名不会破坏主结构。
3. 用户无需经过 Settings 即可进入 Replay Artifacts。
4. 左栏可快速切换报告，中栏可持续阅读，右栏可承接补充信息。

### 12.3 工程验收

以下条件全部满足才视为工程质量达标：

1. TypeScript 构建通过。
2. 现有 replay artifact API 类型未被破坏。
3. tab restore 不会抛出 unsupported type。
4. 关键新增组件职责清晰，不继续把所有逻辑堆回单文件。

---

## 13. 测试计划

### 13.1 必做验证

1. npm run build
2. 打开 Replay Artifacts 一级入口
3. 打开多个 tab 后切换与关闭
4. 刷新后恢复 Replay Artifacts tab
5. 从 Settings 打开 Replay Artifacts
6. 选择不同 report 并验证详情刷新
7. 切换 trade_date 查看 day detail
8. 提交或查看 feedback

### 13.2 建议补充的自动化测试

如果当前前端已有适合的测试基础，可补以下测试：

1. TabService 对 replay-artifacts 的 create/restore 单测
2. Settings 入口卡点击行为测试
3. Workspace 初始选中最近报告的逻辑测试
4. Inspector 长路径渲染测试

当前状态：

1. 前 1、2、3、4 项已在 2026-03-25 全部落地为自动化测试。

---

## 14. 风险与回滚策略

### 14.1 主要风险

1. replay-artifacts.tsx 当前职责过重，拆分时容易引入状态回退。
2. tab restore 机制若遗漏 replay-artifacts，会在刷新后报错。
3. Top Bar 入口增加后，若命名或图标处理不当，可能与现有信息架构不协调。
4. 若一次性引入过多组件拆分，短期内会增加调试复杂度。

### 14.2 风险控制策略

1. 先做一级入口和容器迁移，再做深拆分。
2. 第一阶段尽量不改后端接口。
3. 每个 phase 结束后都执行一次构建验证。
4. 若 workspace 拆分风险过高，可先做“独立 tab + 原页面复用”，再逐步三段式化。

### 14.3 回滚策略

若第一阶段出现严重回归，可按以下方式回滚：

1. 保留 replay-artifacts.tsx 旧实现。
2. 暂时只撤销 Top Bar 入口与新 tab 类型。
3. Settings 内旧 section 可临时恢复。

但从工程上看，更建议通过小步提交和阶段性验证降低回滚需求，而不是依赖大回退。

---

## 15. 推荐实施顺序

如果下一次开发要严格按最小风险推进，推荐顺序如下：

1. 先完成 Phase 1：一级 tab 能打开
2. 再完成 Phase 2：Settings 改为跳转卡
3. 再完成 Phase 3：三段式工作台骨架
4. 最后完成 Phase 4：细节内容分层

这个顺序的好处是：

1. 每一步都能形成可运行成果。
2. 任一步停下，系统仍保持可用。
3. 不会把入口、容器、内容、样式同时打散，降低失控风险。

---

## 16. 最终结论

Replay Artifacts 当前最大的问题不是某几个长字符串换行不好看，而是它已经超出了 Settings 子页面的职责边界。

最优解不是继续在 Settings 里修边角，而是把它提升为一级工作台，并在现有 tab/workbench 架构下用最小侵入方式完成重构。

本次推荐方案的核心判断如下：

1. 以新增 replay-artifacts tab 类型为一级入口基础。
2. 以独立 workspace 容器承接工作台布局。
3. 以三段式结构解决浏览、阅读、补充信息三类任务冲突。
4. 以“先入口、后容器、再分层”的顺序降低改造风险。

后续实现时，应优先按照本文档的 Phase 1 到 Phase 5 顺序推进，而不是直接在现有 Settings 页面上继续堆叠复杂布局。
