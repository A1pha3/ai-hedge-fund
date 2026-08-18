# 题材动量（Theme Momentum）研究计划 Implementation Plan (v3.3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `docs/superpowers/specs/2026-08-17-theme-momentum-setup-design.md` 定义的题材动量 setup 回答核心问题——**"题材确认后的延续段中，BTST 明确不覆盖的部分（增量），全候选执行口径下 E[r] 是否为正且凸性 ≥1.5？"**——产出可复核的做/不做决策包。不写任何生产策略代码。

**先验披露（v3.1，诚实叙事）**：BTST 自身的两条证据（streak 证伪——2 连板胜率比首板低 4pp；中继板更差——pre_runup>8% 组显著弱于池均值）都指向延续段偏负，本方向先验约 20-35% 为真。Tier A 阳性后验也仅 ~50-60%——**Phase 2 前向 shadow 是 Tier A/B 阳性后的强制下一步，不是可选加速通道**；任何"回测显著就直接接入"的路径都违反本约束。

**Architecture:** **两级火箭**（v2 重构）+ **增量对照与聚类推断**（v3 审查）：Tier A 用既有 court raw 快照（涨停列表+SW 成员，零新增数据源）先出行业口径的方向性决策包，判断点在计划 1/3 处；Tier B（概念口径）仅在 Tier A 为正或接近零时启动，且新增数据源只有**月度 as-of 成分**一个（概念内涨停家数由 lu 涨停快照 ∩ 成分**自算**，不依赖任何第三方聚合字段）。研究管道镜像 btst_court 模式：raw → `scripts/theme_momentum_*.py` → 事件表+manifest → 决策包。

**Tech Stack:** pandas、`scripts/_btst_court_common.py`（sessions/regime/前向收益公共函数）、court raw 快照（lu 涨停列表含 first_time/open_times/up_stat + panel 全市场价格）、sw_members.csv、tushare API（仅 Tier B 的 dc_member 月度拉取）。

## Global Constraints（违反任何一条 = 任务不可合并）

1. **不修改 `src/` 下任何生产代码**；研究脚本与数据只在 `scripts/` + `data/research/theme_momentum/` + `data/reports/`。
2. **PIT 纪律**：板块成分用"不晚于信号日的最近**月度** as-of 快照"；绝不用最新快照回填历史。概念内涨停家数一律**自算**（lu 涨停快照 ∩ as-of 成分），禁止依赖第三方聚合字段（z_t_num 的 null 语义不可证明——v3 审查发现 4）。
3. **执行口径与 court 同源**：T+1 开盘买（一字锁死=不可成交，`limit_up_cap_pct_for_ticker`）、T+k 开盘卖（缺 bar 顺延至 T+15）、卫生过滤 = fillable ∧ ¬ST ∧ close≥3 ∧ ¬北交所。前向收益只准用公共函数 `forward_open_returns`（Task 1 提升），禁止复制粘贴。
4. **不预置资金流条件、不预置连板加成**（spec §5）。
5. **主假设预注册唯一（增量口径 + 聚类推断，v3 审查发现 1/2）**：主假设 = `theme ∧ ¬BTST-eligible` **增量子集**、K₁=3、距确认日 1-2 天、T+8、normal regime、卫生过滤后，**按确认日聚类**（每轮题材先聚合为其事件的均值，再对周期样本算 t/wilson）的 95% CI 下界 > 0 且点估计 > 0.65pp。其余一切分组为探索性分析，不得单独作为"做"的依据；禁止在网格里挑最好的格子当结论。
6. **对照基线强制**：决策包必须报告与 BTST 候选（court event_table_v1 同窗口）的**重叠率**与增量子集独立统计——绝对收益无意义，新 setup 的价值只存在于 BTST 覆盖不了的部分。
7. **市场普涨归一化（v3 审查发现 3）**：确认条件一律用"板块涨停家数 / 全市场涨停家数"的**占比跳变**（当日占比 ≥ 2× 该板块占比的 20 日中位），不得用裸家数——裸家数在普涨日测的是次日动量不是题材。
8. **fail-closed 分类**：题材判定以行为签名（占比跳变）为主、名称规则为辅；规则判不出的板块一律按"非叙事"排除。
9. **每个 Phase 允许"结论是不做"**；Tier A 为负且远离零 → 直接关闭方向。
10. **研究保底价值**：确认事件表与决策包无论结论如何**永久保留**于 `data/research/theme_momentum/`——它是 regime 判断、event_sentiment、BTST strength 背景变量的可复用资产（v3 审查发现 5）。
11. 侦察已验证事实（2026-08-17，勿重复侦察）：`kpl_concept` 有 z_t_num 但 **null 值大量存在且语义不可区分**（无涨停 vs 缺失）——这正是自算的原因；court raw `lu_*.csv` 已含 first_time/open_times/up_stat + 东财三级行业字段；概念池混有风格/财报/机械类板块。

---

## Tier A：行业口径方向性验证（零新数据源）

### Task 1: 公共前向收益函数提升（DRY，v2 审查发现 6）

**Files:**
- Modify: `scripts/_btst_court_common.py`（新增函数，不改动现有函数）
- Modify: `scripts/review_cond2_fund_flow_gate.py`（改 import，删本地副本）
- Test: `tests/offensive/test_theme_momentum_common.py`

**Interfaces:**
- Produces: `scripts/_btst_court_common.py::forward_open_returns(by_day, sessions_cal, ts_code, s, signal_close, symbol, horizons=(5,8,10)) -> dict`（T+1 open / 一字剔除 / 缺 bar 顺延——语义逐字来自 `review_cond2_fund_flow_gate._forward_returns`，含 `fillable/t1_unbuyable/gap_t1_open/gross_ret_t{h}` 键）

- [ ] **Step 1: 写失败测试**（构造 3 日合成 panel：正常、一字、缺 bar 三种路径，断言键与语义）

```python
"""公共前向收益函数测试 (Tier A Task 1)."""
import pandas as pd

from scripts._btst_court_common import forward_open_returns


def _by_day(rows):
    df = pd.DataFrame(rows, columns=["trade_date", "ts_code", "open", "close", "pre_close"])
    return {d: g for d, g in df.groupby("trade_date")}


def test_normal_path_t8():
    by_day = _by_day([
        ("20260106", "600000.SH", 11.0, 11.0, 10.0),   # T+1 正常开盘买入
        ("20260113", "600000.SH", 12.0, 12.5, 11.8),   # T+8 卖出
    ])
    out = forward_open_returns(by_day, ["20260105", "20260106", "20260113"],
                               "600000.SH", "20260105", 10.0, "600000")
    assert out["fillable"] is True
    assert abs(out["gross_ret_t8"] - 12.0 / 11.0) < 1e-9


def test_yizi_unbuyable():
    by_day = _by_day([("20260106", "600000.SH", 11.0, 11.0, 10.0)])  # open=11.0=涨停价
    out = forward_open_returns(by_day, ["20260105", "20260106"],
                               "600000.SH", "20260105", 10.0, "600000")
    assert out["fillable"] is False and out["t1_unbuyable"] is True


def test_missing_bar_skips_forward():
    by_day = _by_day([("20260106", "600000.SH", 11.0, 11.0, 10.0),
                      ("20260109", "600000.SH", 11.5, 11.6, 11.4)])  # T+8 缺, 顺延
    out = forward_open_returns(by_day, ["20260105", "20260106", "20260109"],
                               "600000.SH", "20260105", 10.0, "600000")
    assert abs(out["gross_ret_t8"] - 11.5 / 11.0) < 1e-9
```

- [ ] **Step 2: 跑测试确认失败** → Run: `uv run pytest tests/offensive/test_theme_momentum_common.py -v`，Expected: FAIL（ImportError）
- [ ] **Step 3: 把 `review_cond2_fund_flow_gate._forward_returns` 移入 `_btst_court_common.py` 改名 `forward_open_returns`（加 `horizons` 参数），review 脚本改 import 并删除本地副本；重跑 `uv run python scripts/review_cond2_fund_flow_gate.py` 确认复核产物逐字节可再生成**
- [ ] **Step 4: 跑测试通过** → `uv run pytest tests/offensive/test_theme_momentum_common.py -v` PASS
- [ ] **Step 5: Commit** `git commit -m "refactor(research): 前向收益函数提升为 court common 公共函数"`

---

### Task 2: Tier A 决策包——行业涨停家数确认的方向性验证（核心任务）

**Files:**
- Create: `scripts/theme_momentum_tier_a.py`
- Produces: `data/research/theme_momentum/tier_a_events.csv.gz` + `data/reports/theme_momentum_tier_a_decision_pack_YYYYMMDD.{md,json}`

**Interfaces:**
- Consumes: `scripts/_btst_court_common.py`（`load_sessions`/`load_regime_history`/`forward_open_returns`）、`scripts/btst_court_build.py`（`load_panel`/`ticker_frame` 只读复用）、court raw `limit_up/lu_*.csv`、`sw_members.csv`
- **前置依赖（v3.2）**：court raw 是静态构建产物（2026-08-15 构建，不自动更新）——Tier A 窗口显式截至构建日；构建日之后的事件（如华正新材 8-17）不进入统计，作为成熟度不足的尾部观察披露。若未来重建 court 快照，本研究的 manifest 记录所用快照指纹，禁止混用两次构建的数据。
- Produces: 事件表每行 = (symbol, signal_date, industry, days_after_confirm, in_industry_limit_up, prev_day_alive, first_time, open_times, up_stat, fillable, gross_ret_t5/t8/t10, regime)

**确认日与候选定义（Tier A 口径，全部预注册不得事中调整）：**

```
确认日 D* (行业 I) — 双条件分离 (v3.3: v3 的 max(2×baseline_P, 下限占比) 在基线为零时
                                  恒真退化 — 冷行业基线占比普遍为 0, 跳变语义不存在,
                                  且"下限占比"从未定义数值。分离后各条件用不退化的度量):
  (i) 家数跳变 (行为签名): 家数(I, D*) ≥ 3 且 median(家数(I), D* 前 20 个交易日) ≤ 1
      (家数基线为 0/1 语义清晰, 无退化; 锚定确认日, 存活期内冻结 — v3.1 锚点规则不变)
  (ii) 占比防普涨 (Constraint 7): P(d) = 家数(I,D*)/家数(全市场,D*) ≥ 5%
      (预注册固定值, 不做敏感性以免自由度; 31 个申万一级均匀占比 3.2%, 5% ≈ 1.5× 均值
       = 该行业吸金显著超均值; 普涨日行业家数多但占比不突出 → 被 (ii) 排除)
候选 (D > D*, I 存活期内 = 行业涨停家数未连续 2 个交易日回落至 ≤ 1):
  (a) I 内当日涨停票     (b) I 内前一日涨停、今日未跌停的存活票
排除: ST/一字/价格<3/北交所 走卫生过滤
粒度 (v3.1 预注册双粒度, 防阴性后换粒度复跑的时间维多重比较):
  主假设 = 申万一级行业 (sw_members PIT 映射); 稳健性检查 = lu 快照自带东财行业粒度
  (实际级别执行时确认并记入 manifest, 一次额外 groupby)
  两粒度同时落表; 只有主粒度参与主假设判定, 稳健性粒度只作披露
分组: 距确认日 {1-2, 3-5, 6+} × regime {normal, crisis+risk_off} × {全体, ¬BTST-eligible 增量}
成熟度 (v3.1): 每事件带 matured 布尔 (horizon 前向 bar 是否齐); 未成熟保留表内、排除统计
主假设 (Constraint 5): 增量子集 × 距确认日 1-2 × normal × T+8 × matured,
                       按确认日聚类聚合后 95% CI 下界 > 0 且点估计 > 0.65pp
```

- [ ] **Step 1: 实现脚本**（镜像 `review_cond2_fund_flow_gate.py` 的结构：load → 逐日扫描 → 事件 → 统计 → 决策包。**启动前防御检查（v3.2）**：lu 快照月度覆盖完整性——缺口月直接中止并披露，禁止静默断基线窗口。事件表每行额外落 `signal_pct_change`（v3.2：存活腿 (b) 入场日未涨停，当日 -1% 与 -8% 期望显然不同，预注册定义不改但异质性必须在表内可观测）。决策包必须含：主假设判定（增量口径+聚类 CI）、**与 BTST court 候选的重叠率表**（Constraint 6）、探索性分组表（含 signal_pct_change 分桶）、**T+1 一字率对比**（题材延续段 vs court 全体——可成交性是题材 setup 的真实成本）、独立题材周期数与每轮事件数分布、板块幸存者偏差披露、尾部未成熟事件清单）
- [ ] **Step 2: 运行** → Run: `uv run python scripts/theme_momentum_tier_a.py`；Expected: 事件表非空、华正新材 (603186, 20260805/07) 出现在电子行业确认后的候选中（案例观察，非验收门）；**全局 sanity 锚（v1 有、v3 重写时丢失，v3.3 补回）：确认日数量分布 每月 2-15 个，超出范围即中止排查——Tier A 是无生产实现可对拍的新代码，这是唯一的全局正确性锚**
- [ ] **Step 3: 决策分支（写进决策包结论，不得跳过；v3.1 补第四态）**：
  - 主假设成立（增量子集聚类 CI 下界 > 0 且点估计 > 0.65pp）→ 启动 Tier B（概念口径精修）
  - 主假设不成立但增量子集 T+8 点估计 ∈ (−0.5pp, +0.65pp)（接近零）且 CI 含 0 → 启动 Tier B 一次（概念聚焦可能救回）
  - 增量子集 T+8 ≤ −0.5pp → **关闭方向**，Tier B 不启动，产出关闭报告
  - **统计不可判定**（聚类后周期样本 <15, 或 CI 过宽无法区分上两支）→ 默认不推进,
    决策包记录 "证据不足" (区别于 "方向为负": 前者是数据量问题, 后者是效应量问题)
- [ ] **Step 4: Commit** `git commit -m "feat(research): 题材动量 Tier A — 行业口径方向性决策包 (增量+聚类)"`

---

## Tier B：概念板块口径（仅当 Task 2 判定"启动"，否则跳过）

### Task 3: 概念数据管道（行为分类 + 月度成分）

**Files:**
- Create: `scripts/theme_momentum_fetch.py`、`scripts/theme_momentum_common.py`（`classify_concept`：名称辅助规则，**unknown → 排除**）
- Test: `tests/offensive/test_theme_momentum_common.py`（追加分类测试：机械/财报/风格类断言 + **未知名称返回非叙事**）

**数据契约（v3 单源化：唯一新增数据 = 月度 as-of 成分）：**

```
raw/dc_member_{ym01}.csv   — as-of 概念成分 (每月首个交易日采样): ts_code,con_code,con_name  # ~14 次拉取
# 概念内涨停家数 = court raw lu_*.csv (全市场涨停票, 已有) ∩ 当月 as-of 成分 —— 自算, 不依赖 z_t_num
#   (kpl_concept 的 z_t_num null 语义不可证明 → 弃用为聚合字段; 仅可选做交叉验证列)
# 封板质量/连板: court raw lu_*.csv 的 first_time/open_times/up_stat (已有)
# 龙头识别: up_stat 连板数 + first_time 封板时间 (已有) — 不需要 dc_index 的 leading
# dc_index 日行情: 降为可选 (仅当需要板块指数涨幅做探索性分组时再拉, 默认不拉)
manifest.json — per_day_rows / gaps / 板块幸存者偏差披露 (逐日快照含当日板块全集, 但概念下架历史不可见)
题材判定 = 自算涨停占比跳变 (Constraint 7) + classify_concept 名称辅助 (unknown 排除)
```

- [ ] **Step 1: 写分类测试（含 unknown fail-closed 断言）** → FAIL
- [ ] **Step 2: 实现 `classify_concept`（黑名单仅辅助；`is_narrative = 占比跳变 ∧ classify != mechanical/style/report`）** → PASS
- [ ] **Step 3: 实现月度成分 fetcher**（镜像 `btst_court_fetch.py` 的断点续拉/幂等/gaps；仅 dc_member 月度）
- [ ] **Step 4: 拉取 2025-07 → 今天 的月度成分**；Expected: ≈14 文件、gaps=0；抽样验证：2026-08 快照中"对日反制/IC载板"类概念包含 603186
- [ ] **Step 5: 自算交叉验证**：随机抽 5 个 (概念, 日)，自算涨停家数 vs kpl_concept z_t_num 对比，差异行写进 manifest（自算是权威口径，差异用于记录第三方字段质量问题）
- [ ] **Step 6: Commit** `git commit -m "feat(research): 题材动量 Tier B — 月度成分单源管道 (涨停家数自算)"`

### Task 4: 概念口径事件表 + 最终决策包

**Files:**
- Create: `scripts/theme_momentum_build.py`、`scripts/theme_momentum_views.py`
- Produces: `event_tables/theme_confirm_v1.csv.gz` + `manifest_v1.json` + `data/reports/theme_momentum_phase1_decision_pack_*.md`

- [ ] **Step 1: 构建事件表**（K₁∈{2,3,5} 网格全落表——K₁ 作用于**自算占比跳变的绝对家数下限**；候选两腿同 Tier A；rank_in_theme 用 up_stat/first_time 定义；前向收益用 `forward_open_returns`；事件表同时落 `btst_eligible` 布尔列供增量切分）；Expected: 华正新材 8-04/05/07 在"对日反制/IC载板"确认后的候选中（案例观察；失败记录不阻断）
- [ ] **Step 2: 决策包**（结构同 Tier A：主假设 = 增量子集 × K₁=3 × 距确认 1-2 × T+8 × normal × **按确认日聚类 CI**；+ 概念 vs 行业口径对比 + 与 BTST 重叠率；**禁止在网格里挑最好的格子当结论**）
- [ ] **Step 3: Commit**

---

## Phase 2+（条件性，另写计划）

Phase 1（Tier B 或 Tier A 若 Tier B 被跳过且 Tier A 为强正）决策包结论为"做"才启动：前向 shadow → 宪章 14 证据门槛 → 接入评估。

## 退出条件

- Task 2 增量子集 T+8 ≤ −0.5pp → 关闭方向（Tier B 不启动）
- Task 3 月度成分拉取失败 → 记录降级（Tier A 行业口径已是完整可回答的口径）
- Task 4 主假设不成立（增量口径 + 聚类 CI）→ 关闭报告，**禁止调参重扫网格**
- 任何时点：Tier A 结论若为负且未达"接近零"阈值，不允许以"概念口径可能更好"为由重启（那是对 5% 假阳性的追逐）
- 统计不可判定（周期样本 <15 或 CI 过宽）→ 不推进但**不关闭**——记录数据不足, 留待窗口自然延长后复跑主假设（预注册口径不变, 不许换参数）
- 无论结论：确认事件表与决策包永久保留（Constraint 10）
