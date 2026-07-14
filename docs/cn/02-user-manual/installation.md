---
难度: ⭐
类型: 入门教程
预计时间: 20 分钟
前置知识:
  - [项目总览](../01-introduction/overview.md) ⭐
---

# 安装与配置

完成 AI Hedge Fund(A 股研究分叉)的本地安装、依赖配置与 API key 设置。安装完成后即可运行 `--auto` 全市场筛选。

## 学习目标

- [ ] 确认本机满足环境要求
- [ ] 用 `uv sync` 安装全部依赖
- [ ] 配置 `TUSHARE_TOKEN` 与至少一个 LLM API key
- [ ] 显式设置默认模型路由
- [ ] 通过 `scripts/list-models.py` 验证安装

## 环境要求

| 项目 | 要求 | 说明 |
|---|---|---|
| 操作系统 | macOS / Linux | Windows 建议用 WSL2 |
| Python | 3.11 - 3.12 | 3.13+ 未充分验证 |
| 包管理 | uv(推荐) | 也支持 poetry,但入口命令用 `uv run` |
| 内存 | 8 GB+ | 批量并发场景建议 16 GB |
| 磁盘 | 10 GB | 缓存 + 历史报告 |
| 网络 | 可访问 Tushare / AKShare | LLM API 各 provider 独立访问 |

## 安装步骤

### Step 1:克隆仓库

```bash
git clone <repo-url> ai-hedge-fund-fork
cd ai-hedge-fund-fork
```

### Step 2:安装 uv(如果尚未安装)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装后重新加载 shell,确认 `uv --version` 可执行。

### Step 3:安装 Python 依赖

```bash
uv sync
```

`uv sync` 读取 `pyproject.toml` 与 `uv.lock`,在 `.venv/` 下创建隔离环境并安装全部依赖。首次安装耗时 2-5 分钟。

**验证点**:

```bash
.venv/bin/python --version
```

应输出 Python 3.11.x 或 3.12.x。

### Step 4:复制环境变量模板

```bash
cp .env.example .env
```

### Step 5:配置 API key

编辑 `.env`,填入以下必填项:

```bash
# Tushare 数据源(必填)
# 从 https://tushare.pro/register 注册后获取
TUSHARE_TOKEN=your-tushare-token

# 至少一个 LLM API key(必填)
OPENAI_API_KEY=sk-...
# 或 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / GROQ_API_KEY / GOOGLE_API_KEY

# 默认模型路由(必填,系统不再回退到 provider-specific 变量)
LLM_DEFAULT_MODEL_PROVIDER=MiniMax
LLM_DEFAULT_MODEL_NAME=MiniMax-M2.7
```

`LLM_DEFAULT_MODEL_PROVIDER` 与 `LLM_DEFAULT_MODEL_NAME` 必须成对设置。常见组合:

| Provider | 模型名示例 | 适用场景 |
|---|---|---|
| `MiniMax` | `MiniMax-M2.7` | 默认推荐,国内访问稳定 |
| `openai` | `gpt-4o-mini` | OpenAI key 已有 |
| `deepseek` | `deepseek-chat` | 性价比高 |
| `Zhipu` | `glm-4.7` | 国内备选 |

### Step 6:验证安装

```bash
.venv/bin/python scripts/list-models.py
```

**验证点**:输出列出当前解析到的默认 provider、model,且不出现 `fallback` 或 `unset` 警告。

接着运行:

```bash
uv run python src/main.py --show-default-model
```

应输出与 `.env` 一致的 provider/model 路由。

## 可选配置

### 并发控制

```bash
# 分析师并发数(默认 2,可调 1-3)
ANALYST_CONCURRENCY_LIMIT=2

# 分 provider 限流(双 provider 模式)
MINIMAX_PROVIDER_CONCURRENCY_LIMIT=2
ZHIPU_PROVIDER_CONCURRENCY_LIMIT=1

# 主 provider 偏向
LLM_PRIMARY_PROVIDER=MiniMax
```

并发调高会提升吞吐,但也会增加 provider 侧 429 或配额耗尽的风险。从 2 调到 3 比直接跳到 4 更安全。

### 缓存路径

```bash
# 默认 ~/.cache/ai-hedge-fund/cache.sqlite
DISK_CACHE_PATH=/custom/path/cache.sqlite
```

查看缓存统计:

```bash
.venv/bin/python scripts/manage_data_cache.py stats
```

清空缓存:

```bash
.venv/bin/python scripts/manage_data_cache.py clear --yes
```

### daily-action 开关

```bash
# 默认暂停 OversoldBounce(统计不显著)
# 设为 none 恢复全部 setup
DAILY_ACTION_DISABLED_SETUPS=oversold_bounce

# 真实止损执行模式(默认不执行,仅披露)
DAILY_ACTION_EXECUTION_STOP=atr_k2
```

## 常见安装错误

### 错误 1:`uv sync` 报 Python 版本不匹配

`pyproject.toml` 指定了 `requires-python` 范围。用 `uv python install 3.12` 安装合适版本,或确认本机 Python 在 3.11 - 3.12 范围内。

### 错误 2:`TUSHARE_TOKEN` 报 401

token 无效或过期。登录 https://tushare.pro/user/token 确认 token 是否正确,以及账户积分是否满足接口要求(daily_basic 需要 2000 分以上)。

### 错误 3:`list-models.py` 输出 "default model not resolved"

`.env` 中 `LLM_DEFAULT_MODEL_PROVIDER` 或 `LLM_DEFAULT_MODEL_NAME` 缺失。系统不再回退到 `MINIMAX_MODEL` 等 provider-specific 变量,必须显式设置这两个变量。

### 错误 4:`--auto` 报 LLM quota exhausted

并发过高导致 provider 侧 429。把 `ANALYST_CONCURRENCY_LIMIT` 调到 1,或减少 `MINIMAX_PROVIDER_CONCURRENCY_LIMIT`。配额紧张时优先降低并发,而不是重试。

## 下一步

- [快速开始](getting-started.md) — 跑通第一次筛选
- [每日工作流](daily-workflow.md) — 建立交易日例行流程
