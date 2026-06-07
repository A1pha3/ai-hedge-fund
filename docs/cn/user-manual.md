# AI 选股系统使用手册 (v2.0)

> 本手册面向首次接触 **AI 选股系统** v2.0 的用户,帮助你在 10 分钟内完成安装、第一次全市场筛选、解读推荐结果,并掌握核心 CLI/Web 用法。

---

## 1. 系统概述

AI 选股系统是一个面向 **A 股市场** 的量化研究工具,核心目标:**帮助用户在 30 天投资周期内找到高胜率标的**。

v2.0 在 v1.x 基础上完成 24 项新功能,核心架构分三层:

| 层 | 名称 | 职责 | 典型输出 |
|---|---|---|---|
| **Layer A** | 候选池快筛 | 全市场 ~5000 只 → 候选池 | 1500-2500 只可投标的 |
| **Layer B** | 四策略评分 | 趋势 / 均值回归 / 基本面 / 事件情绪 | 4 个独立评分 + 子因子 |
| **Layer C** | 信号融合 + 仲裁 | 加权融合 score_b + Hurst 仲裁 + 质量守卫 | Top N 推荐 + 决策 (buy/hold/skip) |

附加模块:行业轮动、自选池、条件单、推送、归因、再平衡、市场温度计等。

**核心 CLI 入口**: `uv run python src/main.py`  
**核心 Web 入口**: `./app/run.sh` → `http://localhost:5173`

**仅支持 A 股**(6 位 ticker: 000001、300750、600519 等)。美股请用上游 v1.x 版本。

---

## 2. 安装与配置

### 2.1 环境要求

| 项目 | 要求 |
|---|---|
| Python | **3.11 - 3.12**(3.13+ 兼容性未充分验证) |
| 包管理 | **uv**(推荐) 或 poetry |
| 内存 | 8 GB+(批量并发场景建议 16 GB) |
| 磁盘 | 10 GB(缓存 + 历史报告) |
| 网络 | 可访问 Tushare / AKShare API |

### 2.2 安装步骤

```bash
# 1. 克隆仓库
git clone <repo-url> ai-hedge-fund-fork
cd ai-hedge-fund-fork

# 2. 安装依赖(uv 优先)
uv sync                       # 安装全部依赖到 .venv/

# 3. 复制环境变量模板
cp .env.example .env

# 4. 编辑 .env,填入 TUSHARE_TOKEN
#    TUSHARE_TOKEN 在 https://tushare.pro 注册获取
#    同时填入至少一个 LLM provider key(OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY 等)
```

### 2.3 关键环境变量

**必填**

| 变量 | 说明 | 示例 |
|---|---|---|
| `TUSHARE_TOKEN` | Tushare Pro API token | `xxxxxxxxxxxxxxxxxxxxxxxx` |
| `OPENAI_API_KEY` | 至少一个 LLM provider key | `sk-...`(或 DEEPSEEK/GROQ/GOOGLE 等) |
| `LLM_DEFAULT_MODEL_PROVIDER` | 默认 LLM 路由 provider | `openai` / `deepseek` / `MiniMax` |
| `LLM_DEFAULT_MODEL_NAME` | 默认 LLM 模型名 | `gpt-4o-mini` / `deepseek-chat` |

**v2.0 核心开关**

| 变量 | 默认 | 说明 |
|---|---|---|
| `USE_BATCH_FETCHER` | `true` | 是否启用批量数据获取层(P0-1) |
| `AUTO_EXPORT_PDF` | `false` | `--auto` 后自动导出 PDF(P1-7) |
| `PREHEAT_BEFORE_AUTO` | `false` | `--auto` 开始前先预热缓存(P1-1) |
| `ANALYST_CONCURRENCY_LIMIT` | `2` | LLM 并发(1=串行,2-3 推荐) |
| `LLM_PRIMARY_PROVIDER` | - | dual-provider 模式下偏向某 provider |
| `DISK_CACHE_PATH` | `~/.cache/ai-hedge-fund/cache.sqlite` | 缓存路径覆盖 |

**v2.0 推送配置**(可选,`--auto` 完成后自动触发)

`data/push_config.json` 由 `--push-test --init` 生成模板,支持企业微信 / 钉钉 / 邮件 / Webhook 4 通道。

---

## 3. 快速开始

### 3.1 第一次运行(完整流程)

```bash
# Step 1: 预热缓存(减少 --auto 时的实时 API 请求)
uv run python src/main.py --preheat

# Step 2: 全市场自动筛选(默认 top_n=10)
uv run python src/main.py --auto

# Step 3: 查看报告
cat data/reports/auto_screening_20260607.json | head -100
```

输出示例(节选):

```json
{
  "date": "20260607",
  "market_state": {
    "state_type": "trend",
    "position_scale": 0.85,
    "regime_gate_level": "normal"
  },
  "layer_a_count": 1842,
  "high_pool_count": 47,
  "top_n": 10,
  "recommendations": [
    {
      "ticker": "300750",
      "name": "宁德时代",
      "industry_sw": "电力设备",
      "score_b": 0.6214,
      "decision": "buy",
      "consecutive_days": 4,
      "decay": {"level": "none"}
    }
  ]
}
```

### 3.2 解释一只推荐票

```bash
uv run python src/main.py --explain 300750
```

输出包含 **4 块信息**:
- **市场状态**:评分当天的 state_type / 仓位系数
- **策略贡献**:四策略的 direction(↑/↓/—)与 confidence(0-100)
- **因子明细**:每个策略的 Top-3 子因子 + 10 格 ASCII 进度条
- **同行业排名**:该票在同行业候选中的分位

### 3.3 标的基本面详情

```bash
uv run python src/main.py --stock-detail 300750
```

输出:估值 / 财务质量 / 技术面 / 资金流 / 近期事件 五板块综合卡片。

---

## 4. 核心功能

### 4.1 全市场自动筛选 `--auto`

```bash
uv run python src/main.py --auto --top-n 20 --end-date 2026-06-07
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--top-n` | `10` | 返回 Top N(范围 1-100) |
| `--end-date` | 今天 | 交易日期 `YYYY-MM-DD` 或 `YYYYMMDD` |

**输出 JSON 字段**:`recommendations[].score_b`(融合评分,-1~+1,>0.35 高信心)/ `decision`(`buy`/`hold`/`skip`)/ `consecutive_days`(P0-6)/ `decay.level`(`none`/`mild`/`moderate`/`severe`,P0-3)/ `industry_rotation`(P1-2)/ `conditional_orders`(P1-10)/ `batch_data_fetcher`(P0-1)/ `sector_concentration_warnings`(>40% 触发)。

### 4.2 市场温度计 `--market-status`

```bash
uv run python src/main.py --market-status --market-date 20260607
```

**6 大指标 + 综合状态**:

| 指标 | 等级阈值 |
|---|---|
| 趋势强度 (ADX) | 偏强 ≥25 / 正常 ≥20 / 偏弱 ≥15 / 弱势 <15 |
| 波动率 (ATR) | 高波 ≥3.0% / 偏大 ≥1.8% / 正常 ≥1.0% / 低波 <1.0% |
| 市场宽度 (涨跌比) | 强势 ≥0.60 / 均衡 ≥0.50 / 偏弱 ≥0.40 / 弱势 <0.40 |
| 北向资金 | 正数=连续净流入天数 / 负数=连续净流出天数 |
| 涨跌停 | 涨停 / 跌停家数 |
| 综合状态 | `trend` / `range` / `mixed` / `crisis` + 仓位系数 0-1 |

### 4.3 标的对比 `--compare`

```bash
uv run python src/main.py --compare 300750,600519,000001 --metrics score_b,trend_score,pe_ttm
```

支持 2-5 只 ticker、`--metrics` 自定义指标、`--no-radar` 关闭雷达图。输出归一化分位表 + 终端 ASCII 雷达图,自动选出 metric 综合 winner。

### 4.4 智能自选池 `--watchlist-*`

```bash
uv run python src/main.py --watchlist-add 300750 --name "宁德时代" --tags 锂电 --note "持仓中"
uv run python src/main.py --watchlist-list
uv run python src/main.py --watchlist-status
uv run python src/main.py --watchlist-remove 300750
```

数据持久化在 `data/watchlist.json`。`--auto` 完成后自动:更新每只自选票的 `score_history`、标记 `consecutive_days`、输出 `watchlist_update.scored_count`。

### 4.5 条件单 / 推送 / 行业轮动 / 缓存预热

```bash
# 条件单:基于 ATR 波动率,生成买入区间 / 止损 / 止盈
uv run python src/main.py --conditional-orders --top-n 20 --atr-period 14

# 推送:4 通道 (wecom/dingtalk/email/webhook),先 init 生成模板,再编辑 + 测试
uv run python src/main.py --push-test --init
uv run python src/main.py --push-test

# 行业轮动:申万一级行业动量 + 强度排名 (Top 5 强势 / Bottom 3 弱势)
uv run python src/main.py --industry-rotation --ir-top 5 --ir-bottom 3

# 缓存预热:列任务 / 全量 / 强制 / 指定任务
uv run python src/main.py --preheat --list-tasks
uv run python src/main.py --preheat
uv run python src/main.py --preheat --preheat-tasks stock_basic,daily_quote --force
```

条件单输出:买入区间(± 0.5 × ATR)/ 止损(− 2 × ATR)/ 止盈(+ 3 × ATR)/ 建议仓位。`--auto` 完成后会自动按 enabled 通道推送。

### 4.6 自定义策略权重 `--custom-weights`

```bash
uv run python src/main.py --custom-weights \
  --trend 0.40 --mean-reversion 0.20 --fundamental 0.30 --event-sentiment 0.10
```

不重新跑 `--auto`,基于最近一次报告,按新权重重算 score_b 并重新排序。四个权重自动归一化(校验求和 > 0)。

### 4.7 标的详情 / 推荐追踪 / 胜率 / 绩效

```bash
uv run python src/main.py --stock-detail 300750 --sd-date 20260607
uv run python src/main.py --tracking-summary --tracking-lookback 30
uv run python src/main.py --winrate-dashboard --winrate-lookback 60
uv run python src/main.py --performance-report --period weekly --pr-end-date 20260607
```

- **stock-detail**:5 板块详情(估值 / 财务质量 / 技术面 / 资金流 / 近期事件)
- **tracking-summary**:近 N 天历史推荐胜率 + T+1/T+3/T+5 收益分布(需先 `--auto`)
- **winrate-dashboard**:按推荐日 / 持有期 / 行业三维胜率统计
- **performance-report**:组合周报/月报,需先准备 `data/positions.json`

### 4.8 PDF 导出 `--export-pdf`

```bash
uv run python src/main.py --export-pdf --pdf-date 20260607 --pdf-output ./report.pdf
```

把最近一次 `--auto` JSON 报告转 PDF(中文需 CJK 字体,见 §7)。也可在 `.env` 设 `AUTO_EXPORT_PDF=true`,让 `--auto` 完成后自动导出。

---

## 5. Web 应用

### 5.1 启动

```bash
./app/run.sh
# 默认:前端 http://localhost:5173  +  后端 http://localhost:8000
```

`run.sh` 自动:
- 启动 FastAPI 后端(端口 8000)
- 启动 Vite 开发服务器(端口 5173)
- macOS 自动打开浏览器
- 关闭时清理子进程

### 5.2 主要页面

| 路径 | 功能 | 关键模块 |
|---|---|---|
| `/` | 自动选股(全市场一键) | `src/screening/candidate_pool.py` + `signal_fusion.py` |
| `/risk` | 风险监控(VaR / CVaR / 回撤) | `src/portfolio/risk_metrics.py` |
| `/attribution` | 归因分析(策略贡献度) | `src/portfolio/strategy_attribution_daily.py` |
| `/lookback` | Lookback 审计(回放) | `src/research/factor_ic_analysis.py` |
| `/admin` | 后台管理(API keys / 邀请) | `app/backend/routes/admin_audit.py` |

### 5.3 主要 API 端点

所有端点前缀 `/api`,无需鉴权(详见项目 `CLAUDE.md`)。

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/screening/auto` | POST | 一键全市场筛选(等价 `--auto`,默认超时 60s) |
| `/api/screening/compare` | GET | 标的对比(2-5 只 ticker) |
| `/api/screening/conditional-orders` | GET | 条件单建议 |
| `/api/screening/custom-weights` | POST | 自定义权重重排 |
| `/api/screening/winrate-dashboard` | GET | 历史胜率看板 |
| `/api/screening/stock-detail/{ticker}` | GET | 标的基本面详情 |
| `/api/portfolio/risk-snapshot` | GET/POST | 组合风险快照(VaR/CVaR/回撤) |
| `/api/portfolio/risk-snapshot/thresholds` | GET | 当前风险阈值 |
| `/api/portfolio/attribution` | GET | 策略归因日报 |
| `/api/research/lookback-audit` | GET | 因子 IC 回测审计 |
| `/api/health` | GET | 健康检查 |
| `/api/auth/login` | POST | 登录(返回 JWT) |

详细请求/响应 schema 见 `app/backend/routes/*.py`(Pydantic BaseModel 定义)。

---

## 6. 高级用法

### 6.1 自定义策略权重

通过 `--custom-weights` 在不重新跑 `--auto` 的情况下,改变四策略权重并立即看到新的 Top N:

```bash
# 偏趋势行情:加大 trend 权重
uv run python src/main.py --custom-weights --trend 0.50 --mean-reversion 0.10 --fundamental 0.20 --event-sentiment 0.20

# 偏震荡行情:加大 mean_reversion
uv run python src/main.py --custom-weights --trend 0.10 --mean-reversion 0.50 --fundamental 0.30 --event-sentiment 0.10
```

输出 `data/reports/custom_weights_<date>.json`。

### 6.2 缓存预热流水线

`--preheat` 任务并行(默认 4 并发),执行前可用 `--list-tasks` 查看每个任务的预计耗时。建议每天开盘前(8:30-9:00)跑一次:

```bash
# 增量预热(只跑当日缺失的)
uv run python src/main.py --preheat

# 强制全量刷新(周末维护用)
uv run python src/main.py --preheat --force
```

或加 `PREHEAT_BEFORE_AUTO=true` 到 `.env`,每次 `--auto` 前自动预热。

### 6.3 回测

```bash
# 单标的回测
uv run backtester --ticker 000001

# 自定义时间窗口
uv run backtester --ticker 000001 --start 2025-01-01 --end 2025-12-31
```

回测引擎源码: `src/backtester.py`(事件驱动 + 滑点模拟)。

### 6.4 模拟交易 (Paper Trading)

```bash
source .env
.venv/bin/python scripts/run_paper_trading.py \
  --start-date 2026-02-02 --end-date 2026-03-13 --tickers 300724
```

模拟交易报告: `data/paper_trading_reports/`。

### 6.5 因子 IC 分析

```bash
uv run python src/main.py --factor-ic --ic-lookback 60 --ic-method spearman
```

输出各因子在近 60 天的 IC (Information Coefficient) 与 IC IR,辅助评估因子有效性。方法可选:`spearman`(默认) / `pearson` / `kendall`。

### 6.6 再平衡建议

准备 `data/positions.json`:

```json
{
  "portfolio_value": 1000000.0,
  "positions": [
    {"ticker": "300750", "current_value": 200000.0, "industry_sw": "电力设备"},
    {"ticker": "600519", "current_value": 150000.0, "industry_sw": "食品饮料"}
  ]
}
```

执行:

```bash
uv run python src/main.py --rebalance --drift-threshold 0.05
```

输出每只票的"减仓/加仓/持有"建议,按 5% 漂移阈值触发。

---

## 7. 故障排除

| 症状 | 原因 | 解决方案 |
|---|---|---|
| `Tushare token 无效` | `.env` 中 `TUSHARE_TOKEN` 缺失/错 | 检查 `.env`,确认 token 在 https://tushare.pro 可登录 |
| `--auto` 超时 / 504 | 首次跑无缓存,实时 API 慢 | 先跑 `--preheat`,或开 `PREHEAT_BEFORE_AUTO=true` |
| 推荐过少(0-3 只) | `score_b` 阈值过高 / 市场冷淡 | 用 `--auto --top-n 50` 拉更多;或调低 Web 端 `score_threshold`(默认 0.0) |
| `--explain` 提示"未找到 300750" | 该票不在最新 Top N 内 | 先跑 `--auto`,再 `--explain` |
| PDF 中文乱码 | 系统缺 CJK 字体 | macOS: `brew install --cask font-noto-sans-cjk`;Linux: `apt install fonts-noto-cjk` |
| 推送失败 | 通道未启用 / target 错误 | `--push-test` 调试;确认 `data/push_config.json` 中 `enabled: true` |
| LLM 调用超时 | 模型 provider 限流 / 余额不足 | 切换 `LLM_DEFAULT_MODEL_PROVIDER`;或调低 `ANALYST_CONCURRENCY_LIMIT=1` |
| 候选池为空 | 当日非交易日 / 数据源异常 | 确认 `TUSHARE_TOKEN` 有效;换 `--end-date` 为前一日重试 |
| 缓存占用过大 | `~/.cache/ai-hedge-fund/` 累积 | 跑 `python scripts/manage_data_cache.py stats`;`clear` 子命令清理 |

---

## 8. 路线图与版本

### 当前版本 v2.0 (2026-06-07)

**新增功能(24 个)**:P0-1 批量获取 / P0-2 可解释性 / P0-3 信号衰减 / P0-5 自选池 / P0-6 连续推荐 / P1-1~P1-12(行业轮动、追踪、IC、Web选股、风险预警、PDF、对比、温度计、条件单、归因、再平衡)/ P2-3 推送 / P2-4 胜率看板 / P2-5 自定义权重 / P2-6 标的详情 / P2-8 绩效周报 / P2-9 宏观数据。

**修复 bug**:48 个(R3-R18 累计,含 GAMMA 系列、ALPHA 系列、缓存 key 错位等)。

**测试覆盖**:1100+ 测试,0 失败。

### 完成度

| 阶段 | 计划 | 已完成 | 状态 |
|---|---|---|---|
| Phase 1 (P0) | 6 | 5 | 83%(剩 P0-4 回测可视化) |
| Phase 2 (P1) | 10 | 10 | 100% |
| Phase 3 | 6 | 6 | 100% |
| P2 系列 | 8 | 7 | 88%(剩 Web 前端任务) |
| **总完成度** | **30** | **28** | **88%** |

完整功能清单见 `docs/cn/product/feature-proposals.md` 第十五章。

---

## 9. 贡献指南

欢迎贡献代码、文档、bug 报告。在提交前请确认:

### 9.1 代码风格

- **行长度 420 字符**(`.flake8` 与 `black` 均已配置,这是项目约定)
- **PEP 484 类型标注** 全量覆盖
- **格式**: `uv run black src/ && uv run isort src/ && uv run flake8 src/`
- **Pydantic** 用于所有外部数据校验

### 9.2 LLM 调用

**所有 LLM 调用必须**通过 `src/utils/llm.call_llm()`,**禁止**直接 import `openai` / `anthropic` 等 provider SDK。这样保证:
- 多 provider 路由统一
- 调用埋点 / 缓存 / 限流透明
- 测试 mock 简单

### 9.3 测试

- 新功能需带测试,目标覆盖率 **> 80%**
- 测试放 `tests/` 对应子目录
- 集成测试放 `tests/integration/`
- 跑: `uv run pytest tests/<path> -v`

### 9.4 提交流程

1. Fork 仓库
2. 创建 feature 分支: `git checkout -b feat/my-feature`
3. 跑全套测试: `uv run pytest tests/ -v`
4. 跑格式检查: `uv run black --check src/ && uv run flake8 src/`
5. 提交 PR,标题 `<type>(scope): description`(如 `feat(screening): add custom weights rebalance`)

### 9.5 目录速查

| 想做什么 | 改哪里 |
|---|---|
| 加新 agent | `src/agents/` + 注册到 `src/utils/analysts.py` |
| 加新数据源 | `src/tools/` 或 `src/data/providers/` |
| 加新 API 端点 | `app/backend/routes/`(放对应模块) |
| 加新 UI 节点 | `app/frontend/src/nodes/`(注册到 `nodes/index.ts`) |
| 加新 CLI 子命令 | `src/cli/dispatcher.py` 的 `COMMAND_REGISTRY` |
| 加新选股策略 | `src/screening/strategy_scorer_*.py` |

---

## 附录: 速查

**完整 CLI 速查**(按功能分组)

| 组 | 命令 |
|---|---|
| 核心 | `--ticker 000001,300750` / `--auto --top-n 20` / `--explain 300750` / `--preheat --list-tasks` |
| 分析 | `--market-status` / `--industry-rotation` / `--compare 300750,600519` / `--stock-detail 300750` / `--custom-weights --trend 0.4` / `--conditional-orders` |
| 组合 | `--tracking-summary` / `--winrate-dashboard` / `--attribution-daily` / `--rebalance` / `--performance-report --period weekly` |
| 自选池 | `--watchlist-add/remove/list/status <TICKER>` |
| 输出/推送 | `--export-pdf` / `--push-test --init` / `--push-test` |
| 流水线 | `--pipeline --trade-date 20260607` / `--screen-only --trade-date 20260607` |
| 宏观 | `--macro` / `--factor-ic --ic-lookback 60` |

**关键报告路径**:`data/reports/auto_screening_<YYYYMMDD>.json` / `tracking_history.json` / `attribution_daily_*.json` / `rebalance_*.json` / `performance_*.json` / `custom_weights_*.json` / `daily_gainers_*.md`。配置:`data/watchlist.json` / `data/push_config.json` / `data/positions.json`。日志 `logs/`,缓存 `~/.cache/ai-hedge-fund/cache.sqlite`。

---

> **反馈**: 问题与建议请提交 GitHub Issue,或在 Web `/admin` 后台留言。  
> **文档版本**: v2.0 / 2026-06-07 / 维护者: gamma
