---
难度: ⭐
类型: 入门教程
预计时间: 15 分钟
前置知识:
  - [安装与配置](installation.md) ⭐
---

# 快速开始

用 15 分钟完成首次 A 股全市场筛选,拿到当日的 Top 10 推荐列表。

## 学习目标

完成本教程后,你能够:

- [ ] 确认环境变量与默认模型路由已就绪
- [ ] 运行 `--auto` 完成一次全市场筛选
- [ ] 用 `--top` 秒级查看最近一次推荐
- [ ] 用 `--explain` 查看单只票的推荐原因
- [ ] 用 `--check-freshness` 验证数据新鲜度

## 环境检查清单

开始前确认以下条件已满足:

- [ ] 已完成 [安装与配置](installation.md),`uv sync` 无报错
- [ ] `.env` 中 `TUSHARE_TOKEN` 已填入有效 token
- [ ] `.env` 中至少一个 LLM API key(如 `OPENAI_API_KEY`)
- [ ] `.env` 中 `LLM_DEFAULT_MODEL_PROVIDER` 与 `LLM_DEFAULT_MODEL_NAME` 已显式设置
- [ ] 当前时间在 A 股收盘后(约 15:30 之后),或使用 `--end-date` 指定历史日期

## 步骤指南

### Step 1:确认默认模型路由

```bash
.venv/bin/python scripts/list-models.py
```

**验证点**:输出应包含 `LLM_DEFAULT_MODEL_PROVIDER` 和 `LLM_DEFAULT_MODEL_NAME` 的解析值,且不出现 `fallback` 或 `unset` 警告。

如果看到 "default model not resolved",回到 `.env` 检查两个变量是否都已设置。系统不再回退到 `MINIMAX_MODEL` 等 provider-specific 变量,必须显式配置这两个变量。

### Step 2:预热缓存(可选,首次运行推荐)

```bash
uv run python src/main.py --preheat
```

**验证点**:命令退出码为 0,日志显示预热任务完成。预热会把 Tushare 的 daily_basic、daily_prices 等热数据写入本地 SQLite 缓存,减少 `--auto` 时的实时 API 请求。

如果 Tushare token 无效,这里会报 401 或空数据错误。先修 token 再继续。

### Step 3:运行全市场筛选

```bash
uv run python src/main.py --auto
```

**验证点**:

- 命令退出码为 0
- `data/reports/` 目录下出现 `auto_screening_YYYYMMDD.json` 文件
- 终端输出包含 Top 10 推荐,每条含 ticker、名称、score_b、决策(buy/hold/skip)

首次运行耗时数分钟(取决于网络与 LLM 速度),后续有缓存时会更快。

### Step 4:秒级查看推荐

```bash
uv run python src/main.py --top 10
```

**验证点**:终端在 1 秒内输出最近一次 `--auto` 的 Top 10 推荐,无需重跑。支持过滤参数,例如只看电子行业且 score_b ≥ 0.5 的票:

```bash
uv run python src/main.py --top 20 --industry=电子 --min-score=0.5 --exclude-st
```

### Step 5:解释单只票的推荐原因

```bash
uv run python src/main.py --explain 000001
```

**验证点**:输出包含该票的四策略因子明细、事件线、行业排名与最终决策。如果该票不在最近一次推荐中,系统会说明原因(分数不足、被过滤等)。

## 完成验证

运行以下命令确认全部就绪:

```bash
uv run python src/main.py --check-freshness
```

输出应显示当日数据新鲜度检查通过。如果出现 `stale` 警告,说明 price_cache 或 regime_history 未更新到当日,需要先跑 `--auto` 刷新。

## 常见问题 Top 3

### Q1:`--auto` 报 "TUSHARE_TOKEN not set"

`.env` 文件未加载或 token 为空。确认 `.env` 在项目根目录,且 `TUSHARE_TOKEN=` 后面紧跟 token 值,无引号。

### Q2:`--auto` 跑完后 `--top` 显示空列表

检查 `data/reports/` 下最新的 `auto_screening_*.json` 文件,看 `recommendations` 字段是否为空。可能是当日候选池过滤过严或 LLM 调用全部失败。查看 `logs/llm_metrics_*.jsonl` 确认 LLM 调用成功率。

### Q3:`--explain 000001` 提示 "ticker not in latest report"

`--explain` 只解释最近一次 `--auto` 报告中的票。如果 000001 不在 Top 10,用 `--top 50` 查看更大范围,或用 `--why-not 000001` 查看它为何被排除。

## 下一步

- [每日工作流](daily-workflow.md) — 学习两条管线的协作时序,建立交易日例行流程
- [CLI 参考](cli-reference.md) — 浏览全部命令与参数
- [报告解读](interpreting-reports.md) — 读懂 JSON 报告的每个字段

跑完 `--auto` 后,还需要跑 `--daily-action` 获取次日 BUY 信号:

```bash
uv run python src/main.py --daily-action
```

该命令读缓存扫描凸性 setup(涨停突破),输出次日 BUY 信号 + Kelly 仓位 + 止损计划,耗时约 3 秒。两条管线的协作时序详见 [每日工作流](daily-workflow.md)。
