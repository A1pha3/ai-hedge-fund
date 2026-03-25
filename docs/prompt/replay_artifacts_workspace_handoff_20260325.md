# 新会话续接提示词：Replay Artifacts 一级工作台改造

你现在接手的是 ai-hedge-fund-fork 仓库中的一个前端结构改造任务，请先完整理解上下文，再直接进入实现，不要重复做高层方案讨论。

## 一、当前任务目标

当前要做的主线任务只有一个：

把 Replay Artifacts 从 Settings 子页面升级为一级工作台，并按已有设计文档完成前端开发改造。

注意，这不是继续做局部 CSS 修补，而是要完成信息架构升级：

1. Replay Artifacts 不再继续嵌在 Settings 中作为一个 section。
2. 它要成为与 Settings 平级的一级 tab/workspace。
3. 页面要从受限的 settings content pane 升级为适合研究复盘的工作台布局。

## 二、必须先读的文档

先读这份设计文档，并严格按它推进实现：

1. docs/zh-cn/product/arch/arch_replay_artifacts_workspace_redesign.md

这份文档已经包含：

1. 问题定义
2. 现有架构约束
3. 目标信息架构
4. 目标布局设计
5. 必改文件与建议新增文件
6. Phase 0 到 Phase 5 的执行计划
7. 验收标准、测试计划、风险与回滚策略

你的工作不是重写这份文档，而是把它落地成代码。

## 三、当前已知代码结构与关键判断

你必须基于以下事实工作，不要误判成传统路由网站：

1. 当前前端不是标准 react-router 页面应用，而是 tab/workbench 结构。
2. Tab 由以下文件驱动：
   app/frontend/src/services/tab-service.ts
3. 顶层布局与 tab 挂载点在：
   app/frontend/src/components/Layout.tsx
4. Settings 页面容器在：
   app/frontend/src/components/settings/settings.tsx
5. 当前 Replay Artifacts 页面内容主要在：
   app/frontend/src/components/settings/replay-artifacts.tsx

当前结构性问题已经明确：

1. TabService 目前只支持 flow 和 settings。
2. Layout 的顶部入口现在只能打开 Settings。
3. Settings 页面右侧内容区受 max-w-4xl 约束，不适合承载高信息密度的 Replay Artifacts。
4. Replay Artifacts 已经承载大量研究复盘内容，语义上应是 workspace，不是 setting item。

## 四、你应该优先完成的实现顺序

严格按以下顺序推进，避免一上来大拆导致回归：

### Phase 1：一级 tab 落地

先完成最小结构改造：

1. 扩展 app/frontend/src/services/tab-service.ts
   - 为 TabData.type 新增 replay-artifacts
   - 新增 createReplayArtifactsTab()
   - createTabContent() 支持 replay-artifacts
   - restoreTab() 支持 replay-artifacts

2. 在合适位置新增 Replay Artifacts workspace 容器组件
   推荐路径：
   - app/frontend/src/components/workspaces/replay-artifacts-workspace.tsx

3. 在 app/frontend/src/components/Layout.tsx 和对应 top bar 入口中增加一级入口
   - 用户应能直接打开 Replay Artifacts tab

完成这一阶段后，先跑构建验证，不要急着继续深拆。

### Phase 2：Settings 解耦

然后改造：

1. app/frontend/src/components/settings/settings.tsx
   - 不再直接渲染完整 Replay Artifacts 页面
   - 改成一个轻量入口卡或说明卡
   - 卡片点击后打开一级 Replay Artifacts tab

2. 旧的 Replay Artifacts 内容逻辑从 Settings 容器中解耦出来，避免继续被 max-w-4xl 卡死。

### Phase 3：工作台布局升级

在一级 tab 已稳定后，再做布局升级：

1. 左栏：Report Rail
2. 中栏：Main Analysis Canvas
3. 右栏：Inspector

优先复用现有 replay-artifacts.tsx 中已经稳定的业务逻辑，不要为了“更漂亮”而全量推翻重写。

## 五、实现约束

你必须遵守这些约束：

1. 优先最小侵入，不要同步改后端接口，除非实现过程中发现前端确实无法落地。
2. 先解决入口和容器问题，再解决视觉分层问题。
3. 保持现有 Replay Artifacts 已有能力不回退，包括：
   - report 列表加载
   - report detail 加载
   - selection artifact 展示
   - funnel diagnostics 展示
   - research feedback 读取与追加
   - cache benchmark overview 展示
4. 不要引入传统 router 体系来做这次改造。
5. 保持 tab restore 语义正确，刷新后不能因为新 tab type 报 unsupported type。

## 六、当前已经完成的相关工作

这些工作已经做完，不要重复投入：

1. Replay Artifacts 页面长 report 名、长路径、长模型字符串的第一轮和第二轮 UI 优化已经做过。
2. replay-artifacts.tsx 的构建错误已经修复，npm run build 之前已经成功通过。
3. 后端 replay artifact service 已经能返回 cache_benchmark_overview。
4. 前端已能展示 report 级别 cache benchmark KPI 和 detail。
5. 相关文档和 cache benchmark 运行验收已经完成。

所以你现在的重点不是继续证明 cache benchmark 是否可见，而是完成前端工作台升级。

## 七、你在新会话中应采取的工作方式

请按下面方式推进：

1. 先快速读取以下文件，确认当前代码状态：
   - docs/zh-cn/product/arch/arch_replay_artifacts_workspace_redesign.md
   - app/frontend/src/services/tab-service.ts
   - app/frontend/src/components/Layout.tsx
   - app/frontend/src/components/layout/top-bar.tsx
   - app/frontend/src/components/settings/settings.tsx
   - app/frontend/src/components/settings/replay-artifacts.tsx

2. 给出一个简短实施计划，但不要只停留在计划，随后直接开始改代码。

3. 优先完成：
   - 新 tab 类型
   - 顶部入口
   - 独立 workspace 容器
   - Settings 入口卡替换

4. 每完成一个阶段就做一次验证，至少包括：
   - npm run build

5. 如有必要，再做浏览器级烟测，但不要在没有完成基本结构改造前浪费时间在细枝末节上。

## 八、完成标准

只有在下面条件满足后，才算这一轮任务完成：

1. Replay Artifacts 可以直接作为一级 tab 打开。
2. Settings 中不再承载完整的 Replay Artifacts 页面。
3. 新工作台不再受原先 Settings 右侧 max width 限制。
4. 现有 report detail、feedback、cache benchmark 等能力没有回退。
5. npm run build 成功。

## 九、建议你在新会话中的第一句话这样理解任务

你可以把任务理解为：

“基于 docs/zh-cn/product/arch/arch_replay_artifacts_workspace_redesign.md，直接把 Replay Artifacts 从 Settings section 升级为一级 tab/workspace，先完成 tab 类型、顶部入口、独立 workspace 容器和 Settings 解耦，再做三段式布局优化，并在每个阶段后验证前端构建。”

## 十、附加说明

如果你在实现中发现 replay-artifacts.tsx 文件职责过重，可以做有限拆分，但原则仍然是：

1. 先完成结构迁移
2. 再做组件分层
3. 不要为了理想结构而延误一级入口落地

请现在按以上上下文继续工作，不要重新发散讨论产品方向，直接进入实现。