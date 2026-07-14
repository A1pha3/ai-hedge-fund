---
难度: ⭐⭐
类型: 核心概念
预计时间: 8 分钟
前置知识:
  - [项目总览](overview.md) ⭐⭐
---

# 项目定位与边界

本仓库是 [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) 的 A 股研究分叉，不是上游英文项目本身。上游 README 保留在仓库根目录用于 credit，但本分叉的实际工作流、CLI、数据源与上游完全不同。新用户应直接读本目录的中文文档，不要照上游英文说明操作。

## 与上游的核心差异

| 维度 | 上游 virattt/ai-hedge-fund | 本分叉（A 股研究） |
|---|---|---|
| 市场 | 美股（AAPL/MSFT/NVDA 等） | A 股沪深（6 位代码，000001/300750/600519） |
| 主入口 | `poetry run python src/main.py --ticker AAPL,MSFT` | `uv run python src/main.py --auto` |
| 包管理 | poetry（含 `poetry.lock`） | uv（含 `uv.lock`，仓库同时保留 `poetry.lock` 仅作历史） |
| 数据源 | `FINANCIAL_DATASETS_API_KEY` | Tushare / AkShare / Baostock，需 `TUSHARE_TOKEN` |
| 决策面 | 14 个名人人格 agent + portfolio manager | 四策略因子评分 + 凸性 setup + Kelly 仓位 |
| 典型用法 | 单票/多票 LLM 决策 | 全市场筛选 → paper trading 回测验证 |
| Web 端 | 上游 app/ 目录的 React 全栈 | 本分叉不维护 Web 端，主入口是 CLI |

上游的核心是「让 14 个名人人格 agent（巴菲特、芒格、Cathie Wood 等）对一只美股给出买卖判断」。本分叉的核心是「在 A 股全市场上跑因子评分 + 凸性 setup，用回测验证 setup 是否真的有 alpha」。两条路线的工程问题、数据治理、风险约束都不一样，本分叉把上游的 LLM agent 部分保留为 `--pipeline` 模式的可选能力，不作为默认工作流。

## A 股 vs 美股的具体差异

A 股市场有 T+1 交易、涨跌停板、ST/*ST 标记、行业分类（申万一级/二级）、北交所/科创板/创业板板块差异等结构性约束。本分叉针对这些做了若干上游没有的适配：

- **涨停判定按板块自适应**：`src/tools/ashare_board_utils.py` 的 `limit_up_pct_for_ticker` 按代码前缀取阈值——主板 9.5%、科创/创业 19.5%、北交所 29.0%。固定 9.5% 会把 20% 板的非涨停大涨日误判为涨停。
- **T+N 持有周期**：BTST setup 持有 T+10、OversoldBounce 持有 T+5，与美股 T+0/T+1 的执行节奏不同。
- **regime 分层**：系统按 crisis / risk_off / normal 三档分层评分，2020-2026 共 1588 天的 regime 历史在 `data/reports/regime_history.json`。
- **资金流条件**：BTST 的「资金流 >20d 均值」条件依赖 `data/fund_flow_cache/*.csv`，但该缓存深度普遍浅（部分仅 1 行），浅数据下条件降级为 `degraded=True`，渲染时标 `⚠残缺`。

## 研究性质声明

本仓库的 README 和 AGENTS.md 都明确声明：

> This project is for **educational and research purposes only**.
> - Not intended for real trading or investment
> - No investment advice or guarantees provided
> - Creator assumes no liability for financial losses
> - Past performance does not indicate future results

这套声明不是法律模板。本分叉的几个核心机制都按研究语义实现，**与实盘交易系统有结构性差异**：

1. **止损是披露字段，不进 P&L**：`stop_would_have_triggered` 只进 reasoning 字符串，不影响 realized P&L 账面。2026 H1 的 192 笔回测里 0 笔触发，因为行情好；这不能说明止损策略无效，只能说当前样本不支持验证。
2. **仓位上限受证据约束**：当前 v2 ledger 单票硬上限 10%，组合上限 60%。12% regime 例外暂停——canonical manifest 缺少可重算的 regime 授权证据时，系统降级到 10% 并披露 `regime_authorization_evidence_unavailable`，不实际加仓。
3. **paper_trading 与 paper_trading_backtest 是两套**：`data/paper_trading/` 是运行时实例（0 笔 EXIT），`data/paper_trading_backtest/` 是回测（192 EXIT）。查成交数据用后者。
4. **样本期仅 6 个月**：`price_cache` 只有 2026-01-12 → 2026-07-08 的数据。回测结论可能存在样本期偏差，补全历史数据重跑前，所有结论都是「当前最佳依据」而非定论。

## 边界之外做什么

如果要把本仓库的产出用于实盘，必须自行完成以下工作（本仓库不提供）：

- 接入券商交易 API（本仓库只生成条件单格式，不下单）
- 自行验证止损策略在目标样本的稳定性（可跑 `scripts/backtest_exit_strategies.py`）
- 自行补全 `price_cache` 的历史深度（至少 3-5 年）以重跑 Phase 0
- 自行承担监管、税务、风控合规责任

## 下一步阅读

- 想理解为什么 OversoldBounce 暂停、为什么凸性优先：[设计哲学与原则](design-philosophy.md)
- 想看完整工作流：[项目总览](overview.md)
