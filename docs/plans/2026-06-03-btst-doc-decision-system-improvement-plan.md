# BTST 文档、决策卡、系统与 Skill 优化计划（v2.1，对齐 2026-06-03 代码状态，补齐落地契约）

> 这份文档最初写于 2026-06-02，回放当天产物；v2 在 6-3 重新核对了 `scripts/generate_btst_doc_bundle.py` 的实际实现，把"系统永久缺陷"和"已经被修但还没并文档"分开。  
> 6-3 重新核对后，结论从"补齐最后一层裁决压缩与自动桥接"收窄为 4 件事：统一摘要 `operator_summary.json`、`freshness` 与 `actionability` 在顶层 JSON 里显式拆开、`BTST-*-ONE-PAGER.md` 一页盘前卡、统一入口脚本。  
> 文档其余方向（决策卡升级、profile compare 升级、反馈闭环）方向仍对，但落地清单要按 6-3 现状重排。
> 2026-06-04 再修订：保留 v2 的 P0 收窄判断，但补上字段契约、产物归属、桥接失败态和测试验收，避免把"方向正确"误读成"可以直接开工"。

## 学习目标

读完这份文档，团队应该能回答 4 个问题：

1. 相对于 2026-06-03 的代码现实，BTST 文档包和决策卡真正还差什么。
2. 哪些"P0 系统缺口"在文档写作当天是事实、但代码已经修上、不应该再排工。
3. 真正未实现的 4 件事各自的 owner、字段契约、风险、依赖和优先级。
4. 接下来 1 周、2 周、1 个月应该推进什么。

## 先给判断

BTST 体系已经不缺"能不能生成文档"，也不缺"决策卡能不能区分 profile 差异"。旧版文档里列成 P0 的几项，6-3 代码已经补上了基础能力：

- `_build_profile_doc_bundle_decision_card` 已经会按五种 `dominant_reason_type`（`market_gate_override / no_effective_profile_diff / intersection_advantage / only_early_runner_pressure / second_entry_interference`）输出结论。
- `_build_profile_doc_bundle_comparison` 在 markdown 表格里同时给 `early_runner_status / report_mode / market_gate / buy_orders_cleared / intersection_count / only_early_runner_count / second_entry_count / written_file_count / output_dir` 九列，并且按"正式执行层 / 观察层 / 交集优先复审层 / 补充复审层 / 回补机会层"五层做票级 diff。
- `_append_profile_decision_bridge` 已经具备按 `YYYYMMDD_profile_compare` 命名约定回写主目录 `BTST-{date}.md` 和 `BTST-LLM-{date}.md` 的能力。

所以现在不该继续排"从零补决策卡 / 从零补 compare / 从零补桥接"。真正还差的是把这些能力收成稳定接口，具体是下面 4 件事：

1. 缺一个由统一入口最终汇总的 `operator_summary.json`；`compare_btst_doc_bundle_profiles` 可以提供局部摘要，但不应该单独承担完整运行摘要的 owner。
2. `early_runner_freshness_status` 和 `early_runner_actionability_status` 在顶层 JSON 里没显式拆开，导致盘前常被 `exact` 字面意思误导。
3. 没有一页盘前卡 `BTST-YYYYMMDD-ONE-PAGER.md`，盘前 30 秒答不完"今天能不能做"。
4. 缺统一入口 `run_btst_next_day_package.py`，现在要手串规则版、多智能体、early-runner 分析、early-runner 日表、文档包、profile compare 六步。

剩下 P1/P2 部分（profile 历史校准、only early-runner 噪音率、second-entry 独立策略）方向对，但都依赖上面 4 件事的产物形态先稳定下来。

## 当前系统地图（2026-06-03 状态）

| 层 | 当前入口 | 当前作用 | 6-3 状态 |
| --- | --- | --- | --- |
| 规则版主线 | `scripts/btst_full_report.py` | 规则筛选、市场状态、高确信候选 | 基础能力可用，统一入口要先做数据可用性检查 |
| 多智能体主线 | `scripts/run_paper_trading.py` | `short_trade_only` 候选、门控、执行约束 | 基础能力可用，统一入口要捕获 fallback / optimized run 状态 |
| 文档包生成 | `scripts/generate_btst_doc_bundle.py` | 生成 5+2 份文档 + profile compare + 决策卡 | 基础产物稳定，缺 ONE-PAGER 与最终摘要契约 |
| 决策压缩 | profile compare + pretrade decision card | 比较 conservative / aggressive，输出 `dominant_reason_type` | 基础能力已实现，缺 `freshness` / `actionability` 顶层字段和 schema 测试 |
| early-runner 叠加 | `btst_early_runner_v1_latest.*` + 日表 | 提供交集票、补充票、second-entry | 基础能力可用，但 freshness、deployment、gate action、entry status 还没压成统一可行动状态 |
| Skill 编排 | `ai-hedge-fund-btst` | 组织运行顺序、目录、回复口径 | 回复口径已有，下一步应默认消费 `operator_summary.json` |
| 统一摘要（缺） | `operator_summary.json` | 下游消费的单一入口 | 未实现；最终 owner 应是统一入口脚本 |
| 一页盘前卡（缺） | `BTST-YYYYMMDD-ONE-PAGER.md` | 30 秒读完 | 未实现 |
| 统一入口（缺） | `run_btst_next_day_package.py` | 一次跑完 6 步并产出统一摘要 | 未实现 |

## 2026-06-02 产物回放：哪些问题在 6-3 已经被修

### 1. 决策卡过于"轻"——6-3 基础能力已修

6-2 那张卡只有 5 行有效信息：

- 推荐 profile：`conservative`
- 执行倾向：`偏保守执行`
- early-runner 状态：`exact`
- 交集票 / only early-runner / second-entry 全部为 `0`
- 推荐理由：两套 profile 没有有效差异，默认保守

6-3 现状：决策卡扩到 13 行有效信息，参见 `scripts/generate_btst_doc_bundle.py` 里的 `_render_profile_doc_bundle_decision_card_markdown`，多出来的关键字段是 `dominant_reason_type / action_mode / market_gate / buy_orders_cleared` 和三个 `delta vs runner-up` 计数。也就是说，门控压制已经能写到第一层，不会再被 profile 选择抢标题。

但这还不是完整闭环。决策卡现在能表达"为什么偏这套 profile 或为什么被 gate 压住"，还不能单独回答"early-runner 板子是否新"和"这块信息今天能不能转成动作"。这也是 P0 要补 `early_runner_freshness_status` / `early_runner_actionability_status` 的原因。

### 2. profile compare 太浅——6-3 主体已修

6-2 现状只展示 5 个字段（`intersection_count / only_early_runner_count / second_entry_count / written_file_count / output_dir`）。

6-3 现状：markdown 表格 9 列（多出 `early_runner_status / report_mode / market_gate / buy_orders_cleared`），并且在主表之后多了一张"层级差异"票级表，按 5 层（正式执行层 / 观察层 / 交集优先复审层 / 补充复审层 / 回补机会层）做 `top_only` / `runner_up_only` diff，由 `scripts/generate_btst_doc_bundle.py` 里的 `_build_profile_doc_bundle_comparison` 生成。

还没做的是历史校准：现在 compare 能解释当日结构差异，但不能回答"近 20 日哪套 profile 的 realized edge 更好"。这部分放 P1，等 `operator_summary.json` 跑出稳定 outcome 后再接。

### 3. `exact` 只表示时间对齐，不等于增量价值——6-3 部分修

6-2 现象：板子是 `exact`，但当日没有交集票、没有 only early-runner、没有 second-entry，主票 `002463 沪电股份` 来自正式 BTST，不来自 early-runner 增量。文档正文虽然写到了 `deployment_mode=research_only` / `gate_action=research_only`，但没在决策卡顶层把 freshness 与 actionability 拆开。

6-3 现状：上面那些字段在文档正文里继续保留，但还没有作为 decision card JSON 顶层独立字段 `early_runner_freshness_status` / `early_runner_actionability_status` 出来。这一条是 v2 的 P0 之一，仍然没修。

### 4. 顶层主文档没自动桥接——6-3 基础桥接已修（仍缺失败显式化）

6-2 现象：profile compare 脚本只把"今日执行倾向"写进了子目录 `outputs/202606/20260602_profile_compare/{conservative,aggressive}/BTST-20260602.md`，没有自动写到主目录。

6-3 现状：`_append_profile_decision_bridge` 已经会写主目录，前提是 `output_dir` 遵守 `YYYYMMDD_profile_compare` 命名约定；`_resolve_primary_btst_doc_output_dir` 会按这个规则反推主目录路径。如果 6-2 那天桥接失败，多半是目录命名不规范导致主目录解析为空，回退到了子目录。

这里不能再作为"完全未实现"排 P0，但也不能写成"已经稳定闭环"。后续要让 `operator_summary.json` 明确写出 `bridge_updated_files`、`bridge_skipped_files`、`missing_bridge_targets` 和 `manual_patch_required`，否则失败时下游 skill 仍然只能猜。

### 5. 文档完整但盘前决策成本高——6-3 仍然成立

7 份文档的内容足够（BTST / BTST-LLM / EXEC-CHECKLIST / 通俗说明 / 论坛短版 / EARLY-WARNING / EARLY-WARNING-CARD），但盘前 30 秒要答完"今天能不能做、主票是谁、第一取消条件"还是太重。补 ONE-PAGER 是 6-3 之后最直接的优化。

## 一个真实任务流案例：2026-06-02 → 2026-06-03

这次运行的真实链路大致是这样：

1. `btst_full_report.py` 先产出规则版报告，给出 228 只高确信标的和市场中性偏弱判断。
2. `run_paper_trading.py` 跑出 `short_trade_only + momentum_optimized` 的多智能体结果，主票是 `002463 沪电股份`。
3. `session_summary.json` 证明这次是 `optimized run`，不是 fallback。
4. early-runner 日表刷新成功，状态 `exact`，但当日没有交集票、没有 only early-runner、没有 second-entry。
5. `generate_btst_doc_bundle.py` 生成顶层 7 份文档，多智能体结论压成 `confirmation_review_only`。
6. `--compare-profiles conservative aggressive` 额外生成两套 profile 子目录、对照文档和决策卡。
7. 在 6-3 之后，每一步的产物变化：

| 步骤 | 6-2 产物 | 6-3 产物 |
| --- | --- | --- |
| 决策卡 | 5 行有效信息 | 13 行 + `dominant_reason_type` + 3 个 delta |
| profile compare 表格 | 5 列 | 9 列 + 5 层票级 diff 表 |
| 主目录桥接 | 需人工补桥 | 命名规范时自动写回，但失败态还不显式 |
| 下游消费 | 每次手拼多个 JSON | 仍然手拼（`operator_summary.json` 缺） |
| 盘前 30 秒读完 | 不能 | 不能（`ONE-PAGER` 缺） |

## 优化方向一：把 4 件未实现补上

P0 的核心不是继续增加文档数量，而是把"谁负责最终口径"定下来。建议把产物分成两层：

- `compare_btst_doc_bundle_profiles` 负责 profile compare 局部事实：推荐 profile、当日差异、决策卡、桥接尝试结果。
- `run_btst_next_day_package.py` 负责完整运行事实：前置数据检查、六步脚本状态、缺失文件、最终 `operator_summary.json`、ONE-PAGER。

这样下游只需要读 `operator_summary.json`；但代码实现上不会把"完整流程控制"塞进 profile compare 函数里。

### 1. `operator_summary.json`

每次完整运行结束后产出一份统一摘要，放在主目录下。最终 owner 是 `scripts/run_btst_next_day_package.py`；`compare_btst_doc_bundle_profiles` 只需要返回可被汇总的局部 payload。建议字段：

```json
{
  "signal_date": "20260602",
  "next_trade_date": "2026-06-03",
  "market_gate": "halt",
  "action_mode": "confirmation_review_only",
  "recommended_profile": "conservative",
  "dominant_reason_type": "market_gate_override",
  "top_formal_tickers": ["002463"],
  "early_runner_freshness_status": "exact",
  "early_runner_actionability_status": "research_only",
  "early_runner_source_gate_action": "research_only",
  "early_runner_source_deployment_mode": "research_only",
  "intersection_count": 0,
  "only_early_runner_count": 0,
  "second_entry_count": 0,
  "expected_files": [
    "outputs/202606/20260602/BTST-20260602.md",
    "outputs/202606/20260602/BTST-LLM-20260602.md",
    "outputs/202606/20260602/BTST-20260602-ONE-PAGER.md"
  ],
  "missing_files": [],
  "bridge_updated_files": [
    "outputs/202606/20260602/BTST-20260602.md",
    "outputs/202606/20260602/BTST-LLM-20260602.md"
  ],
  "bridge_skipped_files": [],
  "missing_bridge_targets": [],
  "manual_patch_required": false
}
```

这份 JSON 不应该只表示"比较成功"，还要表示"完整流程是否可靠"。字段建议先少后多，但上面这些字段最好 P0 一次补齐，因为它们决定下游是否还要手拼多个 artifact。

### 2. `freshness` 与 `actionability` 在决策卡 JSON 顶层拆开

`freshness` 可以直接从 `early_runner.status` 取，值保持 `exact / stale_fallback / unavailable`。`actionability` 不建议凭空引入一套和代码不一致的原始枚举；对外只暴露 4 个压缩值：

- `executable`
- `confirmation_only`
- `research_only`
- `unavailable`

派生顺序建议写死，避免不同调用方各猜一套：

1. 没有当日或回退板子 → `unavailable`。
2. `gate_action != tradeable` 或 `deployment_mode=research_only` → `research_only`。
3. `gate_action=tradeable`，且存在 `filled` / 可确认 entry，且市场门控允许正式执行 → `executable`。
4. `gate_action=tradeable`，但仍需要开盘承接、VWAP 或宽度确认 → `confirmation_only`。

其中 `confirmation_only` 是给最终读者看的压缩语义，不一定是原始 `gate_action` 的值；原始字段仍然要保留到 `early_runner_source_gate_action` / `early_runner_source_deployment_mode`。改完以后，决策卡和 `operator_summary.json` 都能一眼区分"板子新"和"板子能不能用"，盘前再也不会被 `exact` 字面意思误导。

### 3. 一页盘前卡 `BTST-YYYYMMDD-ONE-PAGER.md`

只回答 8 行：

1. 今天是否允许交易。
2. 当天执行模式：`正常 / 确认复核 / 观望 / no-trade`。
3. 推荐 profile。
4. 主票 1-2 只。
5. 第一取消条件。
6. early-runner 是否有增量价值。
7. 交集票是否存在。
8. only early-runner / second-entry 是否值得花时间看。

这份文档不替代现有 7 份文档，只替代"盘前先扫一眼哪个文件"的判断成本。生成位置放在主目录，命名固定 `BTST-YYYYMMDD-ONE-PAGER.md`，便于 skill 在回复时直接附路径。

ONE-PAGER 补上之后，现有 7 份文档也要保留清楚边界，避免后续又把所有信息塞回同一份长文档：

| 文件 | 保留定位 | 不应该承担的职责 |
| --- | --- | --- |
| `BTST-LLM` | 完整执行主线，解释正式执行层、观察层、门控和 guardrail | 不承担 30 秒入口 |
| `EXEC-CHECKLIST` | 次日盘前动作单，写触发条件、取消条件和时间轴 | 不展开长篇背景 |
| `BTST` | 规则版底稿，保留规则侧市场状态和候选依据 | 不承担 profile 裁决 |
| 通俗说明 | 给非开发读者解释当天分层和边界 | 不重复所有指标 |
| 论坛短版 | 对外短摘要 | 不承载内部细节 |
| `EARLY-WARNING` | early-runner 补充观察池、研究确认池和 second-entry | 不和正式主票混写 |
| `EARLY-WARNING-CARD` | early-runner 超短摘要 | 不替代 ONE-PAGER |

### 4. 统一入口 `scripts/run_btst_next_day_package.py`

至少做 6 件事：

1. 自动检查收盘数据可用性（找不到就早退出，不让后续脚本各报一次错）。
2. 串起规则版 `btst_full_report.py` 和多智能体 `run_paper_trading.py`。
3. 串起 early-runner 分析 `analyze_btst_early_runner_v1.py` 和日表 `generate_btst_early_runner_daily_tables.py`。
4. 串起文档包生成和 profile compare。
5. 校验所有文件存在，并把缺的文件路径写进 `operator_summary.json`。
6. 尝试桥接"今日执行倾向"到顶层主文档，并把 `bridge_updated_files / bridge_skipped_files / missing_bridge_targets` 写进 `operator_summary.json`。

`operator_summary.json` 必须在成功和失败路径都写出来。完整成功时 `manual_patch_required=false`；桥接目标缺失、命名不规范、关键文件缺失或 compare 失败时，统一写 `manual_patch_required=true` 和具体原因。

调用形式建议：

```bash
uv run python scripts/run_btst_next_day_package.py \
  --signal-date YYYYMMDD \
  --with-profile-compare \
  --default-output
```

## 优化方向二：profile 历史校准面板

这一条放在 P1，不是 P0。

前置条件是 `operator_summary.json` 至少跑满 20 个交易日，outcome 字段（建议加 `formal_selected_outcome / no_trade_outcome`）有真实数据之后才校准。校准面板至少要回答：

- 近 20 日 conservative 的 formal selected 胜率
- 近 20 日 aggressive 的 formal selected 胜率
- 近 20 日 conservative 的平均盈亏比
- 近 20 日 aggressive 的平均盈亏比
- 近 20 日 conservative 的 no-trade precision
- 近 20 日 aggressive 的 no-trade precision

实现位置可以挂在 `scripts/btst_*_backtest.py` 系列之后，输出 `outputs/calibration/{YYYYMM}-profile-calibration.md`，并在 P0 跑完后接入 `operator_summary.json` 的 `calibration_ref` 字段。

## 优化方向三：only early-runner 噪音率监控

每月固定统计 3 个指标：

- only early-runner 次日正收益率
- only early-runner 3 日、5 日延续率
- only early-runner 被后来正式 BTST 捕捉到的比例

如果长期主要是噪音，就该把这一层的展示面积收回去；如果稳定高于正式层，就要考虑把它从"补充名单"升级成"独立策略层"。和 P1 一样，依赖 `operator_summary.json` 的 outcome 字段。

## 优化方向四：second-entry 独立策略层

`second_entry_reentry` 的逻辑和首发主票不同，应该单独跟踪：

- T+1 / T+2 优势
- 对应日型（gate / breadth / volatility bucket）
- 需要的盘口确认强度
- 单独仓位建议

实现位置建议在文档包生成之后多跑一个 `scripts/btst_second_entry_eval.py`，把结果写进 `outputs/calibration/second-entry-{YYYYMM}.md`。

## 优化方向五：拉高收益的 5 个杠杆

真正会拉高收益质量的不是文档写得更漂亮，而是下面 5 个杠杆。但前 4 件事没做之前，这 5 个杠杆都接不上 outcome 数据。

1. **提高 no-trade / confirmation-only 的正确率。** 很多日子最大的 alpha 不是"买哪只"，而是"今天别乱买"。6-2 这种 `crisis + halt` 日就是典型。
2. **让 profile 选择基于历史 realized edge，而不是只基于计数。** 见优化方向二。
3. **给正式执行层增加"样本稳健性折扣"。** 像 6-2 那天主票 `002463 沪电股份` 样本只有 `9`，胜率 `66.67%`、盈亏比 `1.93`，但 Wilson 区间仍然较宽。少样本的票应该统一折扣。
4. **把 only early-runner 从"补充名单"升级成"噪音受控研究池"。** 见优化方向三。
5. **把 second-entry 从"展示层"升级成"独立策略层"。** 见优化方向四。

## 对 skill 的具体改进建议

### 1. skill 应在最终回复里默认读 `operator_summary.json`

v1 文档里"skill 应该在最终回复里固定输出"这类建议要重新对齐：v1 提出的几条（区分有效执行分歧、把 market gate 结论顶到第一句、压缩手工干预、固定输出"有没有增量 alpha"）在 6-3 之后都可以从 `operator_summary.json` 直接读出来，不再需要 skill 临时拼装。

### 2. skill 应在 `gate=halt` 时把市场门控结论顶到第一句

`operator_summary.json` 跑通后，skill 只判断 `market_gate` 和 `action_mode` 两个字段：

- `market_gate ∈ {halt, risk_off}` → 第一句先讲"今天不交易 / 只做确认复核"
- `market_gate=normal` 且 `action_mode=formal_execution` → 第一句讲"今天可做"

### 3. skill 应在最终回复里固定输出"early-runner 增量价值"

`operator_summary.json` 提供 `early_runner_freshness_status` 和 `early_runner_actionability_status` 两个字段后，skill 的固定行可以收敛为：

- `early-runner 增量价值：有 / 无 / 仅研究价值`

### 4. skill 不应再依赖手工补桥

`operator_summary.json` 提供 `manual_patch_required` 字段。如果它是 `true`，skill 应直接告诉用户"今天某条桥接失败，需要人工处理"，而不是默默继续。

## 建议的实施顺序（v2.1）

### P0：1 到 3 天内完成

目标：把 4 件未实现一次性补完，闭环当前所有"系统缺口"。

1. 新增 `early_runner_freshness_status` / `early_runner_actionability_status` 派生 helper，并让决策卡 JSON 顶层使用它。
2. 让 `compare_btst_doc_bundle_profiles` 返回 profile compare 局部摘要，包括桥接尝试结果和失败原因。
3. 新增 `scripts/run_btst_next_day_package.py`，串联 6 步并负责最终 `operator_summary.json`。
4. 新增 `BTST-YYYYMMDD-ONE-PAGER.md`，固定放在主目录，只从 `operator_summary.json` 渲染。
5. 补 P0 测试，先锁 schema、失败态和 ONE-PAGER 内容，再接 skill 消费。

### P1：1 到 2 周

目标：让 P0 产物接上 outcome 数据，准备给决策提供历史校准。

1. `operator_summary.json` 加 `formal_selected_outcome` / `no_trade_outcome` 字段。
2. 接入近 20 日 realized outcome 校准摘要，输出 `outputs/calibration/{YYYYMM}-profile-calibration.md`。
3. 决策卡补 `top candidate expected edge` / `risk budget`。
4. profile compare 补"历史胜率/赔率差异摘要"。

### P2：2 到 4 周

目标：把系统从"日报生成器"升级成"可闭环优化的盘前决策系统"。

1. 建立 decision card 推荐结果的月度胜率/盈亏比归因面板。
2. 建立 conservative / aggressive 在不同 gate 日型下的 outcome 校准。
3. 建立 only early-runner 噪音率监控。
4. 建立 second-entry 独立回补策略评估。
5. 把"是否不交易"纳入正式策略优化目标，而不只是把"选出哪只票"当目标。

## P0 测试与验收样例

P0 不应该只用"文件生成了"验收，至少补下面这些测试：

| 测试点 | 建议覆盖 |
| --- | --- |
| `actionability` 派生 | `tradeable + filled`、`tradeable + confirmation required`、`research_only`、无板子四种路径 |
| 决策卡 JSON schema | 顶层必须有 `early_runner_freshness_status` / `early_runner_actionability_status`，且保留 source 字段 |
| `operator_summary.json` schema | 成功路径、缺文件路径、桥接失败路径都能产出 JSON |
| 桥接失败显式化 | 命名不符合 `YYYYMMDD_profile_compare`、主目录缺失、目标文件已存在桥接段三种情况 |
| ONE-PAGER 渲染 | 8 行主问题都能从 `operator_summary.json` 回答，不回读多个 JSON |
| wrapper 早退出 | 收盘数据缺失时不继续跑后续脚本，并写清 `missing_files` / `manual_patch_required` |

## 验收指标

P0 完成后，至少看下面这些指标是否改善：

| 指标 | 目标 |
| --- | --- |
| `operator_summary.json` 自动消费率 | 接近 100%（下游 skill / 日报 / 回测脚本不再手拼 JSON） |
| `ONE-PAGER` 阅读替代率 | 盘前主问 5 题 90% 在 ONE-PAGER 里能答完 |
| 决策卡与 `operator_summary.json` 口径冲突次数 | 降到 0 |
| `manual_patch_required=true` 出现次数 | 降到接近 0 |

P1 完成后：

| 指标 | 目标 |
| --- | --- |
| profile compare 出现"历史差异摘要" | 100% |
| decision card 出现 `top candidate expected edge` | 100% |
| no-trade / confirmation-only 日错误出手率 | 明显下降 |

P2 完成后：

| 指标 | 目标 |
| --- | --- |
| decision card 推荐与历史更优 outcome 的一致率 | 持续提升 |
| only early-runner 噪音率 | 可被量化并持续受控 |
| second-entry 独立策略的回测 | 跑满至少 60 个交易日 |

## 最后一句判断

6-3 之后，BTST 系统真正没做完的事被收窄到 4 件，全部在 P0 一层。补完之后，技能边界会重新划清——`operator_summary.json` 决定了下游怎么消费，ONE-PAGER 决定了盘前怎么读，统一入口决定了脚本怎么串。P1 和 P2 都要等这 4 件事的产物形态稳定下来再去接 outcome 校准，否则校准目标会跟着产物一起漂。
