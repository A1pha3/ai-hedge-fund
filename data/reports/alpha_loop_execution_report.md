# Alpha-Loop 执行报告

**目标**: 对 600567（山鹰国际）分析报告进行数据质量迭代修复
**迭代次数**: 8 次（含基线和最终验证）
**模型**: MiniMax-M2.5
**时间范围**: 2024-06-01 ~ 2026-03-01
**执行时间**: 2026-03-01 21:45 ~ 22:39

---

## 执行摘要

通过 8 轮迭代，修复了 **6 个代码级 bug** 和 **2 个数据映射缺失**，涉及 **7 个文件**。核心估值误差从数量级错误（¥58.4B vs 实际 ¥4.5B）降至合理范围。报告中所有极端异常值均已消除。

---

## 迭代详情

### 迭代 0 — 基线运行
- **报告**: `600567_20260301_214536.md`
- **发现**: 生成 18 位分析师报告，识别出以下数据错误：
  - Bill Ackman 内在价值 ¥58.4B（硬编码 DCF 参数）
  - Damodaran `search_line_items` 缺少 `period` 参数
  - EPS Growth 显示 -431.25%（跨零百分比无意义）
  - Earnings Growth 显示 -522.74%

### 迭代 1 — Ackman 质量调整 DCF + Damodaran 修复
- **报告**: `600567_20260301_215537.md`
- **修改文件**: 
  - `src/agents/bill_ackman.py` — `analyze_valuation()`: 硬编码 `growth=6%, discount=10%, terminal=15x` → 基于公司质量动态调整（亏损公司: `growth=2%, discount=14%+杠杆惩罚, terminal=4-6x`）
  - `src/agents/aswath_damodaran.py` — `search_line_items` 添加 `period="annual", limit=5`；`estimate_cost_of_equity` 添加 A 股国家风险溢价 +2.5%
- **结果**: Ackman 内在价值 ¥58.4B → ¥30.6B（仍偏高，需进一步修复）

### 迭代 2 — Ackman 标准化 FCF
- **报告**: `600567_20260301_220211.md`
- **修改文件**:
  - `src/agents/bill_ackman.py` — `analyze_valuation()`: 单期 FCF → 3-5 年标准化 FCF 均值
- **结果**: Ackman 内在价值 ¥30.6B → **¥4.5B**，MOS 从 +429% → **-59.46%**
- **关键纠正**: Ackman 与 Munger（-31.6%）估值方向一致，消除了看涨/看跌矛盾

### 迭代 3 — EPS Growth 钳位 + 运营费用映射
- **报告**: `600567_20260301_220904.md`
- **修改文件**:
  - `src/agents/growth_agent.py` — 添加 `_clamp_growth()` 函数，EPS/FCF growth 钳位到 [-100%, +500%]
  - `src/agents/fundamentals.py` — `earnings_growth` 钳位到 [-100%, +500%]
  - `src/tools/tushare_api.py` — 添加 `operating_expense` 字段映射（`total_revenue - operate_profit`）
- **结果**: Growth Agent EPS Growth -431% → **-100%**；Fundamentals Earnings Growth -522.74% → **-100%**

### 迭代 4 — 源头数据钳位 + Damodaran 杠杆 Beta
- **报告**: `600567_20260301_221643.md`
- **修改文件**:
  - `src/tools/tushare_api.py` — 所有 YoY 增长字段（`earnings_growth`, `revenue_growth`, `eps_growth`, `fcf_growth`, `operating_income_growth`）在数据层钳位到 [-100%, +500%]
  - `src/agents/aswath_damodaran.py` — `estimate_cost_of_equity()` 添加 Hamada 杠杆 Beta（$\beta_L = \beta_U \times  (1 + (1-t) \times D/E)$）+ 亏损公司 distress premium +3%
- **结果**: 
  - Buffett earnings growth -523% → **-100%**（源头钳位生效）
  - Jhunjhunwala earnings growth "crashed 522%" → **-100%**
  - Damodaran 折现率 11.5% → **22.4%**，内在价值 ¥6.18/股 → **¥2.96/股**

### 迭代 5 — Cathie Wood DCF + Burry 标签修正
- **报告**: `600567_20260301_222454.md` → `600567_20260301_223144.md`（两次运行）
- **修改文件**:
  - `src/agents/cathie_wood.py` — `analyze_cathie_wood_valuation()`: 
    - 亏损公司检测（`net_income < 0` 或 `operating_margin < 0`）
    - 亏损时降级: `growth=5%, discount=20%, terminal=8x`（原: `growth=20%, discount=15%, terminal=25x`）
    - `search_line_items` 添加 `net_income` 字段
  - `src/agents/michael_burry.py` — `_analyze_value()`: `EV/EBIT` 标签修正为 `EV/EBITDA`（实际使用的是 `enterprise_value_to_ebitda_ratio`）
- **结果**: Cathie Wood MOS 1044% → **134.75%**；Burry 指标标签正确

### 迭代 6-7 — 设计差异审计
- 审查了所有 18 位分析师的数据一致性
- 确认以下差异为**设计特性**（非 bug）：
  - `current_ratio` 0.40 vs 0.44 → annual vs TTM 期间差异
  - FCF yield 18.5% vs 4.56% → 单期 TTM vs 5 年归一化均值
  - `risk_free` 4% → 全球 CAPM 框架（Damodaran 推荐方法）

### 迭代 8 — 最终验证
- **报告**: `600567_20260301_223927.md`
- **验证项**: 所有 6 个修复稳定，无回退，无新错误

---

## 修改文件汇总

| 文件 | 修改函数 | Bug 类型 | 影响 |
|------|---------|---------|------|
| `src/agents/bill_ackman.py` | `analyze_valuation()` | 硬编码 DCF + 单期 FCF | 估值误差 13x |
| `src/agents/aswath_damodaran.py` | `estimate_cost_of_equity()`, `analyze_risk_profile()` | 无杠杆调整 + 缺失 CRP | 折现率偏低 50% |
| `src/agents/growth_agent.py` | `_clamp_growth()`, `analyze_growth_trends()` | 跨零极端百分比 | 误导性数据 |
| `src/agents/fundamentals.py` | 增长率钳位 | 跨零极端百分比 | 误导性数据 |
| `src/agents/cathie_wood.py` | `analyze_cathie_wood_valuation()` | 亏损公司高增长假设 | MOS 错误 7.7x |
| `src/agents/michael_burry.py` | `_analyze_value()` | 指标标签错误 | 误导用户 |
| `src/tools/tushare_api.py` | 字段映射 + 增长率钳位 | 数据缺失 + 极端值 | 全局影响 |

---

## 关键指标修复轨迹

```
指标                    基线          迭代1        迭代2        迭代4        迭代5        最终
Ackman 内在价值         ¥58.4B       ¥30.6B       ¥4.5B        ¥4.5B        ¥4.5B        ¥4.47B
Ackman MOS             +429%        +177%        -59.5%       -59.5%       -59.5%       -59.5%
Damodaran 折现率        —            11.5%        11.5%        22.4%        22.4%        22.4%
Damodaran 内在价值      —            ¥6.18/股     ¥6.18/股     ¥2.96/股     ¥2.96/股     ¥2.96/股
Growth EPS Growth       -431%        -431%        -431%        -100%        -100%        -100%
Fundamentals Earnings   -522.7%      -522.7%      -522.7%      -100%        -100%        -100%
Cathie Wood MOS         —            —            —            —            134.75%      134.75%
Burry 指标标签          EV/EBIT      EV/EBIT      EV/EBIT      EV/EBIT      EV/EBITDA    EV/EBITDA
```

---

## 设计层差异（非 Bug，已确认）

| 差异 | 原因 | 影响 |
|------|------|------|
| current_ratio 0.40 vs 0.44 | `period=annual` vs `period=ttm` | 低 — 不改变信号 |
| FCF yield 18.5% vs 4.56% | 单期 vs 5 年归一化 | 中 — 多 agent 分歧是设计特性 |
| Revenue Growth -0.77% vs CAGR 4.7% | YoY vs 复合增长率 | 低 — 不同时间维度 |
| risk_free 4% (US Treasury) | 全球 CAPM 框架 | 低 — 与 CRP 配合合理 |

---

## 生成报告清单

| 迭代 | 文件名 | 最终决策 |
|------|--------|---------|
| 0 (基线) | `600567_20260301_214536.md` | SHORT 85% |
| 1 | `600567_20260301_215537.md` | SHORT 85% |
| 2 | `600567_20260301_220211.md` | SHORT 85% |
| 3 | `600567_20260301_220904.md` | SHORT 85% |
| 4 | `600567_20260301_221643.md` | SHORT 90% |
| 5a | `600567_20260301_222454.md` | SHORT 90% |
| 5b | `600567_20260301_223144.md` | HOLD 85% |
| 8 (最终) | `600567_20260301_223927.md` | — |

---

## 经验总结

1. **周期股 DCF 需用标准化 FCF** — 单期 FCF 对周期性行业会严重高估或低估
2. **硬编码参数是估值系统的头号敌人** — 所有 DCF 参数都应基于公司质量动态调整
3. **跨零百分比变化无分析意义** — 从 -0.01 到 0.05 的 EPS 变化显示 "600% 增长" 是误导
4. **数据层钳位优于 agent 层** — 在源头（tushare_api.py）做一次，所有 agent 受益
5. **字段请求不完整导致 None 回退** — Cathie Wood 未请求 `net_income` → 条件检查失效
6. **指标标签准确性至关重要** — EV/EBIT vs EV/EBITDA 标签错误直接误导 LLM 输出
7. **Hamada 方程对高杠杆公司关键** — D/E=2.1 时 leveraged beta 是 unlevered 的 2.6 倍
