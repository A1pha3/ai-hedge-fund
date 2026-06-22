# BTST Skill Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `ai-hedge-fund-btst` so it behaves like an institutional `alpha / beta / gamma` research team, with stronger hit-rate / payoff gating, more specific execution guidance, and explicit market / sector /赚钱效应 context.

**Architecture:** Keep the existing output contract (`5+2` BTST documents, scheme A layering, profile-compare support), but rewrite the skill instructions and reference templates so every run must produce Alpha statistical diagnostics, Beta execution matrices, and Gamma market-environment / rollout conclusions. The redesign is prompt-and-template heavy: the main work is in `SKILL.md` plus the three reference files that control artifact reading, document structure, and final response wording.

**Tech Stack:** Copilot skill markdown (`SKILL.md`), reference markdown templates under `~/.copilot/skills/ai-hedge-fund-btst/references/`, repository-side plan doc in `docs/superpowers/plans/`, manual smoke validation via the BTST skill against the existing 20260618 artifact set.

---

### Task 1: Rebuild the skill’s top-level contract around Alpha / Beta / Gamma

**Files:**
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/SKILL.md`
- Test: manual grep against `SKILL.md`

- [ ] **Step 1: Prove the current skill file is missing the new institutional contract**

Run:

```bash
rg -n "Alpha 胜率/赔率诊断卡|Beta 执行触发/取消/降级矩阵|Gamma 大盘-板块-赚钱效应环境卡|alpha 负责|beta 负责|gamma 负责" \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/SKILL.md
```

Expected: no matches or obviously incomplete matches, proving the current skill does not yet encode the new team structure.

- [ ] **Step 2: Rewrite the skill header, default goals, and workflow to encode the new team responsibilities**

Insert / replace the top-level responsibility block in `SKILL.md` with content equivalent to:

```md
## 团队分工（硬约束）

- `alpha` 负责因子设计、标签定义、统计稳健性、过拟合防控、胜率/赔率解释、文档编写。
- `beta` 负责交易执行、微观结构、盘口确认、成交约束、滑点与成本、执行模板优化。
- `gamma` 负责风险预算、组合构建、市场门控、大盘/板块/赚钱效应环境、样本外验证与 rollout 结论。

## 新的默认优化优先级

1. 先提高正式执行层的命中质量和盈亏比质量，而不是先扩大出票数量。
2. 再把执行策略写到“可直接照着做”的粒度，避免泛化建议。
3. 同时补齐市场、板块、赚钱效应与交易者心态环境卡，让交易建议有上下文。
```

Then replace the current linear workflow wording with a three-line workflow:

```md
6A. Alpha 线：统计稳健性、标签拆解、主票降级规则、胜率/赔率诊断卡。
6B. Beta 线：开盘触发、取消条件、观察升级条件、滑点/参与率/成本约束、动作矩阵。
6C. Gamma 线：大盘/板块/赚钱效应环境卡、市场门控、风险预算、rollout / 样本外结论。
```

- [ ] **Step 3: Add hard gates so weak candidates cannot be promoted to formal execution**

Add explicit non-negotiable rules to `SKILL.md`:

```md
- 若正式候选存在“样本太薄 / Wilson 区间过宽 / 盈亏比低于 1 / 市场门控压制 / 板块赚钱效应背离”，必须降级到确认复核层或观察层。
- 正式执行层不能只报 raw 胜率，必须同时给出样本量、区间、收缩后胜率与盈亏比。
- 没有市场/板块/赚钱效应环境卡时，不得直接输出“今天可做/不可做”的强结论。
```

- [ ] **Step 4: Verify the rewritten contract is present**

Run:

```bash
rg -n "alpha 负责|beta 负责|gamma 负责|Alpha 胜率/赔率诊断卡|Gamma 大盘-板块-赚钱效应环境卡|样本太薄|Wilson" \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/SKILL.md
```

Expected: matches for all new sections and hard gates.


### Task 2: Strengthen artifact-reading so the skill pulls the right evidence for hit-rate, execution, and market context

**Files:**
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/artifact-reading.md`
- Test: manual grep against `artifact-reading.md`

- [ ] **Step 1: Prove the current artifact guide under-specifies market and evidence extraction**

Run:

```bash
rg -n "赚钱效应|板块|情绪|Wilson|盈亏比|降级|动作矩阵" \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/artifact-reading.md
```

Expected: few or no matches, showing the guide is still too thin for the new design.

- [ ] **Step 2: Expand the source-priority and read-rules sections**

Add concrete requirements such as:

```md
## Alpha extraction additions

- 优先抽取每只 formal selected / confirmation candidate 的样本量、胜率、Wilson 区间、收缩后胜率、盈亏比、标签拆解。
- 若某票胜率与盈亏比背离，必须显式标记为“质量背离”，不得只报更好看的单一指标。

## Beta extraction additions

- 必须从 execution card / opening watch card 提取每只票的触发条件、取消条件、确认方式、成本闸门、参与率限制。
- 若 execution semantics 只有 `confirmation_only`，必须把“等确认”写成执行主语，不能再写成可直接开盘执行。

## Gamma extraction additions

- 必须抽取 market gate、breadth、position scale、涨跌停、主导主题、板块扩散/收缩、赚钱效应、风险姿态。
- 若 artifacts 缺少板块/赚钱效应字段，必须显式写“当前 artifacts 未提供”，不能脑补泛化股评。
```

- [ ] **Step 3: Add downgrade and blocker rules**

Append rules like:

```md
- 若 market gate 为 `halt` / `risk_off` / `crisis`，先输出“执行姿态”，再输出个股顺序。
- 若样本证据不足，只能写“证据不足”，不得把票包装成高把握主票。
- 若只有规则排序、没有足够执行或环境证据，必须降级为观察性建议。
```

- [ ] **Step 4: Verify the new extraction requirements exist**

Run:

```bash
rg -n "赚钱效应|Wilson|收缩后胜率|质量背离|触发条件|取消条件|market gate|证据不足" \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/artifact-reading.md
```

Expected: all new evidence requirements are visible.


### Task 3: Rewrite the final document and final response templates around the new Alpha / Beta / Gamma sections

**Files:**
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-doc-spec.md`
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-response-template.md`
- Test: manual grep against both reference files

- [ ] **Step 1: Prove the current templates do not force the new sections**

Run:

```bash
rg -n "Alpha 胜率/赔率诊断卡|Beta 执行触发/取消/降级矩阵|Gamma 大盘-板块-赚钱效应环境卡|赚钱效应|交易者心态" \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-doc-spec.md \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-response-template.md
```

Expected: no matches, confirming the current templates do not enforce the richer structure.

- [ ] **Step 2: Add required document sections to `final-doc-spec.md`**

Extend the per-file requirements so the implementation must produce:

```md
- `BTST-LLM-YYYYMMDD.md` 必须包含：
  - `Alpha 胜率/赔率诊断卡`
  - `Beta 执行触发/取消/降级矩阵`
  - `Gamma 大盘-板块-赚钱效应环境卡`
  - `Gamma rollout / 样本外 / 是否允许升级`

- `BTST-YYYYMMDD-EXEC-CHECKLIST.md` 必须把每只正式票写成：
  - 触发条件
  - 取消条件
  - 不做条件
  - 观察升级条件
  - 成本/参与率约束

- `YYYYMMDD-两套交易计划通俗说明.md` 必须解释：
  - 大盘环境
  - 板块热点与赚钱效应
  - 这些环境为什么会影响次日交易者心态与执行方式
```

- [ ] **Step 3: Add final-response wording requirements to `final-response-template.md`**

Add or replace with content equivalent to:

```md
**今日执行倾向**
- 先回答今天偏保守还是偏激进，并写明这不是拍脑袋结论，而是由 Alpha/Beta/Gamma 三线共同约束得出。

**核心理由**
- 至少一句来自 Alpha（样本/胜率/赔率质量）
- 至少一句来自 Gamma（市场/板块/赚钱效应/门控）

**主线摘要**
- 规则版一句话
- 多智能体一句话
- 市场/板块/赚钱效应一句话
- 是否存在“高分但不该做”的正式降级原因一句话
```

Also keep the existing P0B rule:

```md
- 当 `effective_decision_diff=False` 时，只能写“默认采用 conservative 做风控基线”，不能暗示已经验证 conservative 更优。
```

- [ ] **Step 4: Verify the templates now force the richer response**

Run:

```bash
rg -n "Alpha 胜率/赔率诊断卡|Beta 执行触发/取消/降级矩阵|Gamma 大盘-板块-赚钱效应环境卡|交易者心态|默认采用 conservative 做风控基线" \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-doc-spec.md \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-response-template.md
```

Expected: all phrases present.


### Task 4: Smoke-validate the redesigned skill against the existing 20260618 artifact set

**Files:**
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/SKILL.md`
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/artifact-reading.md`
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-doc-spec.md`
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-response-template.md`
- Verify output: `outputs/202606/20260618_scheme_a/`
- Verify compare output: `outputs/202606/20260618_profile_compare/`

- [ ] **Step 1: Run a manual RED check against the already-generated 20260618 docs**

Run:

```bash
rg -n "Alpha 胜率/赔率诊断卡|Beta 执行触发/取消/降级矩阵|Gamma 大盘-板块-赚钱效应环境卡" \
  /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202606/20260618_scheme_a/BTST-20260618.md \
  /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202606/20260618_scheme_a/BTST-LLM-20260618.md \
  /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202606/20260618_scheme_a/BTST-20260618-EXEC-CHECKLIST.md
```

Expected: missing matches, proving the current generated docs do not yet satisfy the redesigned skill.

- [ ] **Step 2: Re-run the skill manually on the proven 20260618 artifact set**

Use the same user prompt in a fresh Copilot session after editing the skill:

```text
使用 ai-hedge-fund-btst skill，基于 2026-06-18 收盘数据，为交易日2026-06-22 生成 BTST 全套中文文档，并补生成 conservative/aggressive profile 对照与交易前决策卡
```

Expected: the skill reuses the 20260618 artifacts and regenerates the doc bundle plus compare bundle under the existing `outputs/202606/` paths.

- [ ] **Step 3: Verify the regenerated docs contain the new sections**

Run:

```bash
rg -n "Alpha 胜率/赔率诊断卡|Beta 执行触发/取消/降级矩阵|Gamma 大盘-板块-赚钱效应环境卡|交易者心态|高分但不该做" \
  /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202606/20260618_scheme_a/BTST-20260618.md \
  /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202606/20260618_scheme_a/BTST-LLM-20260618.md \
  /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202606/20260618_scheme_a/BTST-20260618-EXEC-CHECKLIST.md \
  /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202606/20260618_profile_compare/20260618-btst-pretrade-decision-card.md
```

Expected: all new sections present; the decision card still says `effective_decision_diff=False` and uses conservative only as the risk baseline.

- [ ] **Step 4: Final review for consistency**

Run:

```bash
rg -n "effective_decision_diff|默认采用 conservative 做风控基线|risk_off|赚钱效应|confirmation_review_only" \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/SKILL.md \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-response-template.md \
  /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202606/20260618_profile_compare/20260618-btst-pretrade-decision-card.md
```

Expected: the skill, template, and decision-card wording all align on the same conservative-baseline conclusion.
