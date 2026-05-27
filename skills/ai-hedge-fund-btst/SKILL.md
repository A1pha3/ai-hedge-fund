---
name: ai-hedge-fund-btst
description: 在本仓库中处理中文 BTST 次日计划、全套文档、执行清单、预警池、交集票高亮、方案 A 观察期目录、BTST 选股策略优化等请求时触发。典型触发语义：BTST + 明天/次日/某日收盘数据 + 交易计划|全套文档|执行清单|通俗说明|预警文档|交集票|early-runner|scheme_a。核心职责：运行规则版与 short_trade_only 多智能体链路，优先通过 generate_btst_doc_bundle.py 生成主文档，并按正式执行层、交集优先复审层、补充复审层、回补机会层四层输出，提升使用效率并压制噪音票误升级。
---

# ai-hedge-fund-btst

本 skill 负责本仓库的 BTST 次日文档流与方案 A 观察期选股流。

## 默认目标

- 默认生成 `5` 份核心 BTST 文档；如果方案 A 已激活或用户明确要求 early-runner 预警，再额外生成 `2` 份补充预警文档。
- 默认目标不是“多给几只票”，而是通过更好的分层和排序，提高筛选精度、胜率稳定性和盈亏比质量。
- 所有输出必须把候选明确拆成 `4` 层：
  - 正式执行层
  - 交集优先复审层
  - 补充复审层
  - 回补机会层
- 只有当用户没有给出保存路径时，才问一句简短问题：
  - `是否保存到默认目录 outputs/YYYYMM/？`
- 如果用户已经给出自定义目录，不再重复追问。
- 默认目录中的 `YYYYMM` 来自 `signal date`，不是 `next trade date`。
- 方案 A 观察期内，优先使用 `outputs/YYYYMM/YYYYMMDD_scheme_a/`，只有观察期通过后才切回 `outputs/YYYYMM/YYYYMMDD/`。

## Workflow

1. 解析范围、日期和目录。
   - 如果用户指定了 `signal date`，直接使用。
   - 如果没有指定，自动解析“已拿到收盘数据的最新交易日”。
   - 永远计算真实的 `next trade date`。
   - 如果收盘数据不可用，停止并说明 blocker。
   - 如果用户没有缩小范围，默认走全套文档。
   - 规则版首选入口：

   ```bash
   uv run python scripts/btst_full_report.py [--trade-date YYYYMMDD]
   ```

2. 运行规则版 BTST 报告。
   - 预期产物：
     - `data/reports/btst_full_report_YYYYMMDD.md`
     - `data/reports/btst_full_report_YYYYMMDD.json`

3. 运行多智能体 BTST 链路。
   - 本 skill 固定使用 `short_trade_only`。
   - 默认保持 `MiniMax / MiniMax-M2.7`，除非用户明确覆盖模型路由。
   - 如果最新优化 profile manifest 已就绪，默认优先使用；但只有产物明确支持时，才能称为 optimized run。
   - 如果用户显式给了 short-trade profile 输入，把它视为主动绕过 manifest 自动选择，不能擅自标记为 optimized。
   - 默认命令：

   ```bash
   uv run python scripts/run_paper_trading.py \
     --start-date YYYY-MM-DD \
     --end-date YYYY-MM-DD \
     --selection-target short_trade_only \
     --optimized-profile-manifest data/reports/btst_latest_optimized_profile.json \
     --model-provider MiniMax \
     --model-name MiniMax-M2.7 \
     --output-dir data/reports/paper_trading_YYYYMMDD_YYYYMMDD_live_m2_7_short_trade_only_YYYYMMDD_plan
   ```

4. 刷新或读取 early-runner 产物。
   - 方案 A 下，环境允许时先刷新：

   ```bash
   uv run python scripts/analyze_btst_early_runner_v1.py
   uv run python scripts/generate_btst_early_runner_daily_tables.py
   ```

   - 如果环境嘈杂、离线或刷新不稳定，可以跳过刷新，让文档包直接读取当前 latest artifact。
   - 如果产物只支持 `stale_fallback` 或 `unavailable`，绝不能伪造 `exact-date` 板。

5. 读取当前 artifacts。
   - MANDATORY：起草前加载 `references/artifact-reading.md`。
   - 把 `session_summary.json` 视为 artifact 路径和 optimization provenance 的唯一真源。
   - 先读 `optimization_profile_resolution`，再判断本次运行是否真的用了最新 optimized manifest。
   - 如果 `session_summary.json` 显示 `default_fallback`，最终文档必须明说，不能默默写成 optimized。
   - 如果存在 rollout / governance / payoff validation 相关 JSON，起草前读最新文件；尤其要区分 shadow-ready 和 default-upgrade。
   - 如果 `docs/prompt/generate_file/*.md` 里有 BTST 验证文档，只能拿来解释已验证行为，不能覆盖当前 artifacts，也不能把 blocked profile 写成 active。
   - 结构优先读 JSON， prose fallback 才读 Markdown。

6. 先做选股分层，再写最终文档。
   - MANDATORY：起草前加载 `references/final-doc-spec.md`。
   - 优先使用统一入口：

   ```bash
   uv run python scripts/generate_btst_doc_bundle.py \
     --signal-date YYYYMMDD \
     --output-dir outputs/YYYYMM/YYYYMMDD_scheme_a \
     --no-refresh-early-runner
   ```

   - 必须在文档里执行下面的分层策略：
     - 正式执行层：只使用正式 BTST 已经提升到 `selected_actions` / `primary_entry` 的票。
     - 交集优先复审层：只有 `exact-date overlap` 才能进入；它是优先复审，不是无条件下单。
     - 补充复审层：`only early-runner priority / watchlist` 只做补充观察，不得升级成正式执行层。
     - 回补机会层：`second_entry_reentry` 单独呈现，不和普通 watchlist 混用。
   - 状态解释必须固定：
     - `exact`：允许交集票进入优先复审层。
     - `stale_fallback`：交集只能标成历史参考。
     - `unavailable`：完全按正式 BTST 走，不补 early-runner 票。
   - 产物必须来自当前 artifacts，不能靠固定模板脑补。
   - 忙碌日或用户明确要求精简时，可以只生成 `5` 份核心文档并使用 `--core-only`。

7. 交付前验证。
   - 所有请求文件都存在。
   - 文件名使用 `signal date`，不是 `next trade date`。
   - 所有文档都写真实的 `next trade date`，不能写 `N/A`。
   - 方案 A 激活时，确认文档里能看到 early-runner status、交集票高亮、only early-runner 补充池。
   - 如果用户请求“优化 BTST 策略”或“看是否值得升级”，优先回答：
     - 交集票是否开始比普通观察票更有价值。
     - only early-runner 票是否大多仍是噪音。
     - 当前是否还处于 `scheme_a` 观察期。
     - 是否满足切回正式目录或进入中期强化阶段的条件。

## 策略硬规则

- 最终文档必须是中文。
- 股票首次出现必须用 `stock_code + stock_name`。
- 不能虚构股票名、原因、排序、执行规则、交集关系或 early-runner 状态。
- 不能把 `opportunity / research / shadow / near_miss / only early-runner` 票擅自升成正式交易票。
- 不能让 early-runner 抢正式主票决策权；它当前只能做观察增强和优先级增强。
- 交集票的正确处理是“优先看、优先复审、优先等确认”，不是“优先盲打”。
- `stale_fallback` 交集只能作为参考高亮，不能当成当日优先级提升。
- `second_entry_reentry` 必须单独呈现，不能并入普通 watchlist。
- `BTST-YYYYMMDD.md` 以规则报告为准。
- `BTST-LLM-YYYYMMDD.md` 与 `BTST-YYYYMMDD-EXEC-CHECKLIST.md` 以多智能体计划为执行真源。
- 市场背景只能来自当前 artifacts 和可观察上下文，不能写通用股评。
- 字段缺失时直接省略，不猜。
- 需要交互输入时，向用户要答案后继续。
- 上游 artifacts 产不出来时，停止并报告 blocker，不伪造 deliverables。
- 当 `session_summary.json` 存在时，不能把 report directory 名字当真源。
- 只有 `session_summary.json` 或 downstream artifacts 明确支持时，才能声称本次运行是 optimized-profile run。
- 如果 `optimization_profile_resolution.mode=default_fallback`，要在最终文档里明确写出 fallback 状态和原因。
- 如果 rollout / strict-objective / replay validation 相关 artifacts 给出 `hold`、`runtime_replay_required_before_conclusion` 或其它 blocked 结论，必须照实写，不能包装成 active upgrade。
- 对 candidate-entry / weak-structure 清洗规则，`shadow_rollout_review_ready` 仅代表 governed shadow evidence，不代表默认升级许可。
- 只有当当前 artifacts 明确支持时，最终中文文档才可以提到 auto-applied `P5 precision gate`。

## 观察期与评估口径

- 方案 A 观察期重点看 6 项：
  - `early_runner_status`
  - `early_runner_latest_trade_date`
  - 是否出现交集票高亮
  - 是否出现 only early-runner 补充票
  - 核心文档是否都生成
  - 是否需要手工修补
- 周度和阶段评审时，优先判断：
  - `exact` 占比是否提升
  - 交集票是否比普通观察票更有价值
  - only early-runner 票是否仍以噪音为主
  - 是否满足切回正式目录的条件
- `docs/plans/2026-05-27-early-runner-adoption-plan.md` 定义了 BTST 四层选股结构。
- `docs/plans/2026-05-27-early-runner-scheme-a-operations.md` 定义了 `scheme_a` 目录、每日运行链路和切换 gate。

## Lazy loading

- 在读取 run outputs 前，加载 `references/artifact-reading.md`。
- 在起草最终文档前，加载 `references/final-doc-spec.md`。
- 当用户问如何触发 skill 或触发语义不清时，才加载 `references/trigger-examples.md`。
- 当请求涉及方案 A、early-runner 分层、观察期目录或策略优化判断时，优先对照：
  - `docs/plans/2026-05-27-early-runner-adoption-plan.md`
  - `docs/plans/2026-05-27-early-runner-scheme-a-operations.md`
- 正常执行时不要加载 `使用说明.md` 或 `scripts/install_symlink.sh`。

## 完成时回复

- 说明文件保存到了哪里。
- 用一小段话总结规则版主线和多智能体主线。
- 明确说明本次是否有手工干预。
- 如果方案 A 激活，补一句：
  - 当前是 `exact`、`stale_fallback` 还是 `unavailable`
  - 交集票是可行动的优先复审，还是仅供参考的历史高亮
