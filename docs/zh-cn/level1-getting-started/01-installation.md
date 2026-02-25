# 第一章：安装与环境配置 ⭐

> **📘 Level 1 入门教程**

本文档将引导你完成 AI Hedge Fund 系统的安装和环境配置。完成本章后，你将拥有一个完全可用的开发环境，为后续的学习和使用打下坚实的基础。

---

## 学习目标

完成本章节学习后，你将能够：

### 基础目标（必掌握）
- [ ] 理解 AI Hedge Fund 系统的定位和用途
- [ ] 独立完成系统环境的完整配置
- [ ] 成功安装所有必需的依赖包
- [ ] 配置至少一个 LLM 提供商的 API 密钥
- [ ] 验证安装是否成功

### 进阶目标（建议掌握）
- [ ] 理解为什么使用 Poetry 而不是 pip
- [ ] 能够诊断和解决常见的安装问题
- [ ] 根据需求选择合适的 LLM 提供商
- [ ] 配置 Web 应用环境

### 专家目标（挑战）
- [ ] 评估不同安装方式的优劣
- [ ] 优化开发环境配置

**预计学习时间**：30 分钟至 1 小时

---

## 1.1 系统概述

### 系统是什么？

在开始安装之前，我们首先来了解这个系统是什么、能做什么、不能做什么。

AI Hedge Fund 是一个概念验证（Proof of Concept，POC）系统，旨在探索使用人工智能进行投资决策的可能性。这个系统模拟了 18 位著名投资大师的分析风格，包括价值投资的沃伦·巴菲特、成长投资的彼得·林奇、宏观策略的斯坦利·德鲁肯米勒等，通过大型语言模型（Large Language Model，LLM）的推理能力生成投资建议。

> **💡 关键概念**
>
> - **概念验证（POC）**：用于验证想法可行性的早期原型系统
> - **大型语言模型（LLM）**：如 GPT-4、Claude 等具有强大推理能力的 AI 模型

### 系统能做什么？

✅ **可以做到**：
- 模拟不同投资大师的分析风格
- 从多个角度分析股票和投资机会
- 生成投资建议和决策理由
- 进行历史数据回测

### 系统不能做什么？

❌ **不能做到**：
- 进行真实的交易操作
- 保证投资收益
- 替代专业的投资顾问
- 提供精准的市场预测

### 系统定位

> **⚠️ 重要提醒**

理解这个系统的定位非常重要。这个系统目前**仅用于教育和研究目的**，不进行真实的交易操作。它可以帮助你：

- 了解不同投资风格的思考方式
- 学习量化投资的基本概念
- 理解 AI 如何应用于金融领域

但它**不能**：
- 替代专业的投资顾问
- 做出的任何投资决策都应该基于你自己的判断
- 考虑个人的财务状况、投资目标和风险承受能力

### 系统架构概览

系统的核心架构包含三个主要部分：

```
AI Hedge Fund 系统架构
│
├── 数据层
│   ├── 金融数据获取（价格、财务报表、新闻）
│   └── 数据预处理与缓存
│
├── 智能体层（18 个专业智能体）
│   ├── 价值投资类
│   ├── 成长投资类
│   ├── 专业分析类
│   └── 宏观策略类
│
└── 决策层
    ├── 风险评估
    ├── 投资组合优化
    └── 交易建议生成
```

---

## 1.2 系统要求

### 硬件要求

系统的硬件要求取决于你的使用场景。

#### 基础使用（云端 LLM）

如果你只是运行基本分析功能（使用 OpenAI、Anthropic 等云端 LLM），最低配置要求相对较低：

| 配置项 | 最低要求 | 推荐配置 |
|--------|---------|----------|
| CPU | 双核 2.0GHz+ | 四核 3.0GHz+ |
| RAM | 4GB | 8GB |
| 磁盘空间 | 5GB 可用 | 10GB 可用 |
| GPU | 不需要 | 不需要 |

#### 高级使用（本地 LLM）

如果你需要运行本地的大型语言模型（通过 Ollama），则需要更高的配置：

| 配置项 | 推荐配置 |
|--------|----------|
| CPU | 支持硬件加速的处理器 |
| RAM | 16GB+ |
| 磁盘空间 | 20GB+（用于存储模型文件） |
| GPU | 支持 CUDA 的 NVIDIA GPU 或 Apple Silicon（M 系列芯片） |

> **💡 建议**
>
> 对于初学者，建议先使用云端 LLM（如 OpenAI GPT-4o-mini），这样可以降低硬件要求和学习成本。熟悉系统后，再考虑本地部署。

### 软件要求

#### 操作系统

| 操作系统 | 支持版本 | 备注 |
|---------|---------|------|
| macOS | 10.15+（Catalina 及以上） | 支持 Intel 和 Apple Silicon |
| Linux | Ubuntu 20.04+ | 其他主流发行版通常也支持 |
| Windows | 10+ | 建议使用 WSL2（Windows Subsystem for Linux） |

**Windows 用户特别说明**：

Windows 用户建议通过 WSL2（Windows Subsystem for Linux，适用于 Linux 的 Windows 子系统）运行，这可以避免许多兼容性问题。如果必须在原生 Windows 上运行，请确保安装 Visual Studio Build Tools 以编译某些 C++ 扩展包。

#### 必需软件

| 软件 | 版本要求 | 用途 |
|------|---------|------|
| Python | 3.11+ | 编程语言环境 |
| Git | 任意版本 | 版本控制，获取项目源码 |
| Poetry | 任意版本 | Python 依赖管理工具 |
| curl | 任意版本 | 下载安装脚本 |

> **🔧 关于 Python 版本**
>
> 建议使用 Python 3.11.x 系列以获得最佳的包兼容性。避免使用 Python 3.12+，因为某些依赖包可能还未完全支持。

#### 可选软件

| 软件 | 用途 | 是否必需 |
|------|------|----------|
| Docker | 容器化部署 | 否（用于生产环境） |
| Ollama | 本地运行 LLM | 否（如需本地模型则需要） |
| Node.js | Web 应用前端 | 否（如需使用 Web 界面则需要） |

### 网络要求

系统运行需要访问互联网，主要用于：

1. **调用 LLM 服务的 API**（如 OpenAI、Anthropic 等）
   - 需要稳定的网络连接
   - 某些地区可能需要配置 VPN

2. **获取金融数据**
   - 访问外部数据服务
   - 免费股票数据（AAPL、GOOGL、MSFT、NVDA、TSLA）

> **⚠️ 网络限制**
>
> 如果你的网络环境无法直接访问 GitHub 或某些 API 服务，请考虑：
> - 使用 GitHub 镜像源（如 gitee.com）
> - 配置代理或 VPN
> - 使用国内的数据源镜像

---

## 1.3 安装步骤

> **🎯 安装概览**
>
> 完整的安装流程包括以下 5 个主要步骤：
> 1. 克隆项目代码
> 2. 安装 Poetry（依赖管理工具）
> 3. 安装项目依赖
> 4. 配置 API 密钥
> 5. 验证安装

---

### 步骤一：克隆项目

首先，打开终端（Terminal），执行以下命令将项目克隆到本地：

```bash
# 克隆项目到本地
git clone https://github.com/virattt/ai-hedge-fund.git

# 进入项目目录
cd ai-hedge-fund
```

> **📝 说明**
>
> - `git clone`：从 GitHub 下载项目代码
> - `cd ai-hedge-fund`：切换到项目目录
> - 后续命令都默认在此目录下执行

克隆完成后，项目文件将保存在当前目录下的 `ai-hedge-fund` 文件夹中。

#### 验证克隆成功

```bash
# 查看项目目录结构
ls -la
```

你应该能看到以下主要目录和文件：

```
drwxr-xr-x  10 user  staff   320 Feb 13 10:00 .
drwxr-xr-x   5 user  staff   160 Feb 13 10:00 ..
drwxr-xr-x   8 user  staff   256 Feb 13 10:00 .git/
-rw-r--r--   1 user  staff  1234 Feb 13 10:00 .env.example
-rw-r--r--   1 user  staff  5678 Feb 13 10:00 pyproject.toml
drwxr-xr-x   5 user  staff   160 Feb 13 10:00 src/
drwxr-xr-x   5 user  staff   160 Feb 13 10:00 app/
drwxr-xr-x   5 user  staff   160 Feb 13 10:00 docs/
-rw-r--r--   1 user  staff  2345 Feb 13 10:00 README.md
```

**关键文件说明**：
- `src/`：项目的源代码目录
- `app/`：Web 应用代码目录
- `docs/`：文档目录
- `pyproject.toml`：项目配置文件（Poetry 使用）
- `.env.example`：环境变量配置模板
- `README.md`：项目说明文件

> **❓ 常见问题：网络无法访问 GitHub**
>
> 如果你的网络环境无法访问 GitHub，可以考虑：
>
> 1. **使用 GitHub 镜像源**：
> ```bash
> git clone https://gitee.com/mirrors/ai-hedge-fund.git
> ```
>
> 2. **手动下载源码包**：
> - 访问 https://github.com/virattt/ai-hedge-fund/releases
> - 下载最新的源码压缩包
> - 解压后进入目录

---

### 步骤二：安装 Poetry

> **💡 为什么使用 Poetry？**
>
> Poetry 是 Python 的依赖管理工具，它将项目的依赖和版本信息集中管理，简化了环境配置。相比传统的 pip + requirements.txt，Poetry 有以下优势：
>
> - **自动创建虚拟环境**：不需要手动创建和管理虚拟环境
> - **依赖解析**：自动解决依赖冲突
> - **版本锁定**：确保不同环境下的依赖版本一致
> - **构建和发布**：集成了包构建和发布功能

如果你的系统中已经安装了 Poetry，可以跳过此步骤。

#### 验证是否已安装

```bash
poetry --version
```

如果命令返回版本号（例如 `Poetry version 1.7.1`），则表示已安装，可以跳过此步骤。

#### macOS 和 Linux 系统

执行以下命令安装 Poetry：

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

> **📝 命令说明**
>
> - `curl`：下载安装脚本
> - `-sSL`：静默模式，跟随重定向
> - `python3 -`：使用 Python 3 执行下载的脚本

#### Windows 系统

需要在 PowerShell 中以管理员身份执行：

```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python3 -
```

> **⚠️ Windows 提示**
>
> - 需要以管理员身份运行 PowerShell
> - 按 `Win + X`，选择 "Windows PowerShell (管理员)"
> - 如果提示无法执行脚本，先执行：`Set-ExecutionPolicy RemoteSigned`

#### 验证安装

安装完成后，通过以下命令验证安装是否成功：

```bash
poetry --version
```

如果命令返回版本号，则表示安装成功。

#### 可能遇到的问题

**问题 1：命令未找到**

如果提示 `poetry: command not found` 或类似错误：

**解决方案 1**：重启终端，让 PATH 生效

Poetry 安装脚本会自动将 Poetry 添加到用户 PATH 中，但可能需要重启终端才能生效。

**解决方案 2**：手动添加到 PATH

- **macOS/Linux**：通常位于 `~/.local/bin/poetry`
  ```bash
  export PATH="$HOME/.local/bin:$PATH"
  ```
  将此命令添加到 `~/.bashrc` 或 `~/.zshrc`

- **Windows**：通常位于 `%APPDATA%\Python\Scripts\poetry`
  - 手动添加到系统 PATH

**解决方案 3**：使用 pip 安装

```bash
pip install poetry
```

**解决方案 4**：使用 conda 安装（如果你使用 Anaconda）

```bash
conda install -c conda-forge poetry
```

**问题 2：权限错误（Linux/macOS）**

如果遇到权限错误：

```bash
# 使用 sudo 安装（不推荐，但可以解决问题）
curl -sSL https://install.python-poetry.org | sudo python3 -
```

或者：

```bash
# 下载到临时目录，然后手动安装
curl -sSL https://install.python-poetry.org -o install-poetry.py
python3 install-poetry.py
```

---

### 步骤三：安装项目依赖

> **🔧 关于虚拟环境**
>
> Poetry 会自动创建一个独立的虚拟环境，确保项目依赖不会影响系统环境或其他项目。这意味着：
>
> - 每个项目都有自己的依赖环境
> - 不同项目可以使用不同版本的依赖包
> - 避免了"依赖地狱"问题

在项目根目录下执行以下命令：

```bash
poetry install
```

#### 安装过程

这个过程可能需要几分钟时间，取决于你的网络速度和系统性能。

```bash
$ poetry install
Updating dependencies
Resolving dependencies... (4.2s)

Writing lock file
Installing dependencies...

Package operations: 45 installs, 0 updates, 0 removals
  - Installing certifi (2023.11.17)
  - Installing charset-normalizer (3.3.2)
  - Installing idna (3.6)
  ...
  - Installing openai (1.6.1)
  - Installing langgraph (0.0.20)
  - Installing ...

Installing the current project: ai-hedge-fund (1.0.0)
```

> **⏱️ 预计时间**
>
> - 快速网络：1-2 分钟
> - 普通网络：3-5 分钟
> - 慢速网络：10+ 分钟

#### 可能遇到的问题

**问题 1：网络超时或下载失败**

**解决方案 1**：使用国内镜像源

创建或编辑 `~/.pip/pip.conf`（Linux/macOS）或 `%APPDATA%\pip\pip.ini`（Windows）：

```ini
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
```

**解决方案 2**：更新 Poetry 到最新版本

```bash
pip install --upgrade poetry
```

**解决方案 3**：删除现有的虚拟环境并重新创建

```bash
poetry env remove python
poetry install
```

**解决方案 4**：手动指定 Python 版本

```bash
poetry env use python3.11
poetry install
```

**问题 2：依赖版本冲突**

**解决方案 1**：检查 Python 版本

```bash
poetry env info
```

确保使用的是 Python 3.11.x 版本。

**解决方案 2**：更新 Poetry

```bash
pip install --upgrade poetry
poetry update
```

**解决方案 3**：清理缓存

```bash
poetry cache clear pypi --all
poetry install
```

#### 进入虚拟环境

安装完成后，可以通过以下命令进入 Poetry 创建的虚拟环境：

```bash
poetry shell
```

进入后，你的命令行提示符通常会发生变化（例如增加 `(ai-hedge-fund-py3.11)` 前缀）。

```bash
(ai-hedge-fund-py3.11) user@machine:~/ai-hedge-fund$
```

在虚拟环境中，所有 Python 相关的命令都会使用项目指定的依赖版本。

> **💡 使用技巧**
>
> **方式一**：使用 `poetry shell` 进入虚拟环境（推荐用于交互式开发）
>
> **方式二**：使用 `poetry run` 执行单个命令（推荐用于脚本执行）
> ```bash
> poetry run python src/main.py --help
> ```
>
> **方式三**：不进入虚拟环境，直接使用 Poetry 前缀
> ```bash
> poetry run pip list
> ```

---

### 步骤四：配置 API 密钥

> **⚠️ 重要提示**
>
> 系统需要配置至少一个 LLM 提供商的 API 密钥才能正常运行。**没有 API 密钥，系统无法生成分析结果。**

#### 创建配置文件

首先，复制环境变量模板文件：

```bash
cp .env.example .env
```

> **📝 文件说明**
>
> - `.env.example`：配置文件模板，包含所有可配置项的示例
> - `.env`：实际的配置文件（不提交到 Git，用于存储敏感信息）

#### 编辑配置文件

使用你喜欢的文本编辑器打开 `.env` 文件：

```bash
# macOS/Linux
nano .env
# 或
vim .env

# Windows
notepad .env
```

#### 必需配置

你需要至少选择配置一个 LLM 提供商的 API 密钥。

**选项 1：OpenAI**

```bash
# OpenAI 配置
OPENAI_API_KEY=sk-your-openai-api-key-here
```

**选项 2：Anthropic**

```bash
# Anthropic 配置
ANTHROPIC_API_KEY=your-anthropic-api-key-here
```

**选项 3：Groq**

```bash
# Groq 配置（高速推理）
GROQ_API_KEY=your-groq-api-key-here
```

**选项 4：DeepSeek**

```bash
# DeepSeek 配置（低成本）
DEEPSEEK_API_KEY=your-deepseek-api-key-here
```

> **💡 如何选择 LLM 提供商？**
>
> | 提供商 | 价格 | 速度 | 质量 | 适用场景 |
> |--------|------|------|------|----------|
> | OpenAI | 中等 | 快 | 优秀 | 日常使用，综合需求 |
> | Anthropic | 中等 | 中等 | 优秀 | 长文本分析，复杂推理 |
> | Groq | 低 | 极快 | 良好 | 实时交互，批量测试 |
> | DeepSeek | 最低 | 快 | 良好 | 大规模测试，成本敏感 |
>
> **推荐**：
> - 初学者：使用 OpenAI GPT-4o-mini（平衡性能和成本）
> - 成本敏感：使用 Groq 或 DeepSeek
> - 需要长上下文：使用 Anthropic Claude 3.5 Sonnet

#### 可选配置

**金融数据 API**

```bash
# 金融数据配置（可选）
# 注意：AAPL、GOOGL、MSFT、NVDA、TSLA 这五只股票的数据免费
# 其他股票需要有效的 API 密钥
FINANCIAL_DATASETS_API_KEY=your-financial-datasets-api-key-here
```

**其他提供商**

```bash
# Google Gemini（可选）
GOOGLE_API_KEY=your-google-api-key-here

# xAI（可选）
XAI_API_KEY=your-xai-api-key-here
```

**日志配置**

```bash
# 日志级别（可选）
LOG_LEVEL=INFO  # 可选值：DEBUG, INFO, WARNING, ERROR
```

#### 完整配置示例

```bash
# =====================================================
# LLM 提供商配置（至少选择一个）
# =====================================================

# OpenAI - 推荐
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Anthropic
# ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx

# Groq - 高速推理
# GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx

# DeepSeek - 低成本
# DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# =====================================================
# 金融数据配置（可选）
# =====================================================

# Financial Datasets API
# 免费股票：AAPL, GOOGL, MSFT, NVDA, TSLA
FINANCIAL_DATASETS_API_KEY=your-key-here

# =====================================================
# 其他配置（可选）
# =====================================================

# Google Gemini
# GOOGLE_API_KEY=your-key-here

# xAI
# XAI_API_KEY=your-key-here

# 日志级别
LOG_LEVEL=INFO
```

#### 获取 API 密钥

以下是各主要提供商的 API 密钥申请链接：

| 提供商 | 申请链接 | 免费额度 |
|--------|---------|---------|
| OpenAI | https://platform.openai.com/api-keys | 通常有免费额度 |
| Anthropic | https://console.anthropic.com/keys | 有免费额度 |
| Groq | https://console.groq.com/keys | 免费高速推理 |
| DeepSeek | https://platform.deepseek.com/ | 价格极低 |
| Financial Datasets | https://financialdatasets.ai/ | 5 只股票免费 |

**OpenAI 获取步骤**：

1. 访问 https://platform.openai.com/
2. 注册/登录账号
3. 进入 API Keys 页面
4. 点击 "Create new secret key"
5. 复制生成的密钥（只显示一次，请妥善保存）

> **⚠️ 安全提示**
>
> - API 密钥是敏感信息，不要分享给他人
> - 不要将 `.env` 文件提交到 Git 仓库
> - 如果密钥泄露，立即在提供商平台撤销并重新生成

#### 验证配置

配置完成后，可以通过以下命令验证配置是否正确：

```bash
# 检查 OpenAI API 密钥
poetry run python -c "import os; print('OPENAI_API_KEY configured:', bool(os.getenv('OPENAI_API_KEY')))"

# 检查 Anthropic API 密钥
poetry run python -c "import os; print('ANTHROPIC_API_KEY configured:', bool(os.getenv('ANTHROPIC_API_KEY')))"
```

如果显示 `True`，则表示配置正确。

---

## 1.5 验证安装

完成所有配置后，让我们验证安装是否成功。

### 测试 1：检查帮助信息

```bash
poetry run python src/main.py --help
```

**预期输出**：

```
usage: main.py [-h] [--ticker TICKER] [--model MODEL] [--start-date START_DATE]
                [--end-date END_DATE] [--ollama]

AI Hedge Fund - AI-Powered Investment Analysis

options:
  -h, --help            show this help message and exit
  --ticker TICKER       Stock ticker symbol (e.g., AAPL, MSFT, NVDA)
  --model MODEL         LLM model to use (default: gpt-4o-mini)
  --start-date START_DATE
                        Start date for analysis (YYYY-MM-DD)
  --end-date END_DATE   End date for analysis (YYYY-MM-DD)
  --ollama              Use Ollama for local LLM inference
```

如果命令正常显示帮助信息，则表示基础安装成功。

### 测试 2：运行简单分析

运行一个简短的测试分析，验证完整功能：

```bash
poetry run python src/main.py --ticker AAPL --start-date 2024-01-01 --end-date 2024-01-02
```

这个命令会分析苹果公司（AAPL）在 2024 年 1 月 1 日到 1 月 2 日期间的数据。由于时间范围很短，分析应该很快完成。

**预期输出**：

```
AI Hedge Fund Analysis
=====================

Analyzing ticker: AAPL
Using model: gpt-4o-mini
Date range: 2024-01-01 to 2024-01-02

Initializing market data...
 ✓ Data loaded successfully

Initializing agents...
 ✓ 18 agents initialized

Running analysis...

[Warren Buffett Agent]:
Analysis: Apple maintains strong brand value and competitive moat...
Recommendation: HOLD
Confidence: 0.75

[Peter Lynch Agent]:
Analysis: Strong product lineup with innovation potential...
Recommendation: BUY
Confidence: 0.80

[... 其他智能体的分析输出 ...]

Final Portfolio Decision:
Action: HOLD
Position Size: 5%
Risk Level: MEDIUM

Analysis complete!
Time elapsed: 45.2 seconds
```

> **✅ 成功标志**
>
> 如果你看到类似的输出（包含各智能体的分析结果和最终决策），则表示系统运行正常！
>
> **❌ 失败处理**
>
> 如果遇到错误：
> - 检查 API 密钥是否正确配置
> - 检查网络连接是否正常
> - 查看"常见安装问题"章节

### 测试 3：检查环境信息

```bash
poetry env info
```

**预期输出**：

```
Virtualenv
Python:         3.11.7
Implementation: CPython
Path:           /Users/user/Library/Caches/pypoetry/virtualenvs/ai-hedge-fund-abc123
Executable:     /Users/user/Library/Caches/pypoetry/virtualenvs/ai-hedge-fund-abc123/bin/python
Valid:          True

System
Platform:   darwin
OS:         posix
Python:     3.11.7
Path:       /usr/local/opt/python@3.11/bin/python3.11
```

---

## 1.6 Web 应用安装（可选）

如果你更倾向于使用 Web 界面而非命令行，需要额外安装前端依赖。

> **⚠️ 前置要求**
>
> Web 应用需要 Node.js 环境。如果你还没有安装 Node.js，请先访问 https://nodejs.org/ 下载并安装 LTS 版本。

### 步骤一：安装前端依赖

```bash
# 确保在项目根目录
cd ai-hedge-fund

# 进入前端目录
cd app/frontend

# 安装前端依赖（可能需要几分钟）
npm install
```

> **💡 关于 npm**
>
> npm（Node Package Manager）是 Node.js 的包管理器，用于管理前端依赖。

### 步骤二：启动后端服务

在一个新的终端窗口中，执行以下命令：

```bash
# 确保在项目根目录
cd ai-hedge-fund

# 启动 FastAPI 后端服务
poetry run uvicorn app.backend.main:app --reload --host 0.0.0.0 --port 8000
```

**预期输出**：

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using StatReload
INFO:     Started server process [12346]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### 步骤三：启动前端开发服务器

在另一个终端窗口中，执行以下命令：

```bash
# 确保在 app 目录
cd ai-hedge-fund/app

# 启动前端开发服务器
npm run dev
```

**预期输出**：

```
VITE v5.0.0  ready in 234 ms

➜  Local:   http://localhost:5173/
➜  Network: use --host to expose
```

### 步骤四：访问 Web 应用

打开浏览器，访问 http://localhost:5173，你应该能看到 Web 应用界面。

> **✅ 成功标志**
>
> 浏览器显示完整的 Web 应用界面，可以输入股票代码进行分析。

---

## 1.7 常见安装问题

### 问题一：Poetry 安装失败

#### 症状

- 执行 `poetry --version` 时提示命令未找到
- 安装脚本执行失败

#### 原因分析

1. PATH 环境变量未正确配置
2. 安装脚本执行失败
3. 权限问题

#### 解决方案

**方案 1**：确认 curl 可用

```bash
curl --version
```

如果提示命令未找到，请先安装 curl。

**方案 2**：检查 Poetry 安装位置

- **macOS/Linux**：通常位于 `~/.local/bin/poetry`
  ```bash
  ls -la ~/.local/bin/poetry
  ```

- **Windows**：通常位于 `%APPDATA%\Python\Scripts\poetry`
  ```powershell
  ls $env:APPDATA\Python\Scripts\poetry
  ```

**方案 3**：手动添加到 PATH

- **macOS/Linux**（使用 zsh）：
  ```bash
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
  source ~/.zshrc
  ```

- **macOS/Linux**（使用 bash）：
  ```bash
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  source ~/.bashrc
  ```

- **Windows**：
  - 搜索 "环境变量"
  - 编辑系统或用户 PATH
  - 添加 `%APPDATA%\Python\Scripts`

**方案 4**：使用 pip 安装

```bash
pip install poetry
```

**方案 5**：使用 conda 安装

```bash
conda install -c conda-forge poetry
```

---

### 问题二：依赖安装版本冲突

#### 症状

- 执行 `poetry install` 时出现版本冲突错误
- 错误信息包含 "dependency conflict" 或 "incompatible"

#### 原因分析

1. Python 版本不符合要求
2. Poetry 版本过旧
3. 依赖包之间存在版本冲突

#### 解决方案

**方案 1**：检查 Python 版本

```bash
python --version
# 或
python3 --version
```

确保版本是 3.11.x。

如果版本不正确，可以：

```bash
# macOS（使用 Homebrew）
brew install python@3.11

# Ubuntu
sudo apt update
sudo apt install python3.11

# 使用 pyenv 安装多版本 Python
pyenv install 3.11.7
pyenv local 3.11.7
```

**方案 2**：更新 Poetry

```bash
pip install --upgrade poetry
poetry --version
```

**方案 3**：删除虚拟环境并重新创建

```bash
# 删除现有虚拟环境
poetry env remove python

# 重新安装
poetry install
```

**方案 4**：清理 Poetry 缓存

```bash
poetry cache clear pypi --all
poetry install
```

**方案 5**：指定 Python 版本

```bash
# 使用 Python 3.11
poetry env use python3.11
poetry install
```

**方案 6**：使用国内镜像源

创建或编辑 `~/.pip/pip.conf`：

```ini
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
```

---

### 问题三：Windows 系统兼容性问题

#### 症状

- 执行命令时出现 "command not found"
- 编译错误
- 路径问题

#### 原因分析

1. Windows 和 Linux 的路径和命令差异
2. 某些 C++ 扩展需要编译

#### 解决方案

**方案 1**：使用 WSL2（推荐）

WSL2（Windows Subsystem for Linux，适用于 Linux 的 Windows 子系统）可以让你在 Windows 上运行 Linux 环境。

**安装 WSL2**：

1. 以管理员身份打开 PowerShell
2. 执行：
   ```powershell
   wsl --install
   ```
3. 重启计算机
4. 安装 Ubuntu（或其他 Linux 发行版）
5. 在 WSL2 终端中按照 Linux 的安装说明操作

**方案 2**：安装 Visual Studio Build Tools

如果必须在原生 Windows 上运行，请安装 Visual Studio Build Tools 以编译某些 C++ 扩展包。

1. 下载 Visual Studio Build Tools
2. 在安装时选择 "Desktop development with C++"
3. 重启计算机

**方案 3**：使用预编译的 wheel 包

有些包提供预编译的 wheel，避免编译：

```bash
pip install package-name --prefer-binary
```

---

### 问题四：API 密钥配置错误

#### 症状

- 执行分析时出现 "API key not found" 或类似错误
- API 调用失败

#### 原因分析

1. `.env` 文件配置错误
2. API 密钥格式不正确
3. API 密钥无效或过期

#### 解决方案

**方案 1**：检查 `.env` 文件位置

确认 `.env` 文件位于项目根目录：

```bash
# macOS/Linux
ls -la .env

# Windows PowerShell
ls .env
```

如果文件不存在，重新创建：

```bash
cp .env.example .env
```

> **⚠️ 注意**
>
> - 确保文件名是 `.env`（不是 `.env.txt`）
> - 文件不应该有扩展名

**方案 2**：检查 API 密钥格式

打开 `.env` 文件，检查：

```bash
# ✅ 正确格式（没有空格或引号）
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ❌ 错误格式
OPENAI_API_KEY="sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # 不需要引号
OPENAI_API_KEY = sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # 不应该有空格
OPENAI_API_KEY= sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # 不应该有空格
```

**方案 3**：验证环境变量加载

```bash
# macOS/Linux
poetry run python -c "import os; print('OPENAI_API_KEY:', os.getenv('OPENAI_API_KEY'))"

# Windows PowerShell
poetry run python -c "import os; print('OPENAI_API_KEY:', os.getenv('OPENAI_API_KEY'))"
```

如果输出 `None`，说明环境变量未正确加载。

**方案 4**：检查 API 密钥有效性

1. 登录对应的 LLM 提供商平台
2. 检查 API 密钥是否有效
3. 检查密钥是否有足够的配额
4. 如果密钥失效，重新生成

**方案 5**：检查网络连接

```bash
# 测试 OpenAI API 连接
curl -I https://api.openai.com

# 测试 Anthropic API 连接
curl -I https://api.anthropic.com
```

如果连接失败，检查：
- 网络连接是否正常
- 是否需要配置代理或 VPN
- 防火墙是否阻止了连接

---

## 1.8 练习题

### 练习 1.1：环境验证 ⭐

**任务**：验证你的开发环境是否满足所有要求。

**步骤**：

1. 检查 Python 版本
   ```bash
   python --version
   # 或
   python3 --version
   ```
   确认版本号以 3.11 开头

2. 检查 Poetry 版本
   ```bash
   poetry --version
   ```
   确认版本号显示正常

3. 检查 Git 版本
   ```bash
   git --version
   ```
   确认版本号显示正常

**成功标准**：
- [ ] 三个命令都能正常返回版本号
- [ ] 没有任何错误信息

**扩展挑战**：
- 检查你是否在正确的操作系统版本上
- 检查磁盘空间是否足够

---

### 练习 1.2：项目克隆与依赖安装 ⭐⭐

**任务**：完成项目的克隆和依赖安装。

**步骤**：

1. 克隆项目到本地（如果尚未完成）
   ```bash
   git clone https://github.com/virattt/ai-hedge-fund.git
   cd ai-hedge-fund
   ```

2. 查看项目目录结构
   ```bash
   ls -la
   ```

3. 安装依赖
   ```bash
   poetry install
   ```

4. 验证安装
   ```bash
   poetry run python src/main.py --help
   ```

**成功标准**：
- [ ] 项目目录包含 `src/`、`app/`、`docs/` 等目录
- [ ] 依赖安装成功，没有错误
- [ ] 能够看到帮助信息

**扩展挑战**：
- 查看 `pyproject.toml` 文件，了解项目依赖了哪些包
- 使用 `poetry show` 查看已安装的包列表

---

### 练习 1.3：API 密钥配置 ⭐⭐

**任务**：配置至少一个 LLM 提供商的 API 密钥。

**步骤**：

1. 复制环境变量模板
   ```bash
   cp .env.example .env
   ```

2. 使用文本编辑器打开 `.env` 文件
   ```bash
   nano .env  # 或使用你喜欢的编辑器
   ```

3. 添加你的 API 密钥
   ```bash
   # 以 # 开头的是注释，可以删除或保留
   OPENAI_API_KEY=your-api-key-here
   ```

4. 保存并退出编辑器

5. 验证配置
   ```bash
   poetry run python -c "import os; print('OPENAI_API_KEY configured:', bool(os.getenv('OPENAI_API_KEY')))"
   ```

**成功标准**：
- [ ] 输出显示 `True`
- [ ] API 密钥格式正确（没有多余的空格或引号）

**扩展挑战**：
- 配置多个 LLM 提供商的 API 密钥
- 配置 `FINANCIAL_DATASETS_API_KEY`
- 修改 `LOG_LEVEL` 为 `DEBUG`，查看详细日志

---

### 练习 1.4：运行完整分析 ⭐⭐⭐

**任务**：运行一次完整的股票分析，验证系统功能。

**步骤**：

1. 运行简短分析
   ```bash
   poetry run python src/main.py --ticker AAPL --start-date 2024-01-01 --end-date 2024-01-02
   ```

2. 观察输出，确认：
   - 数据加载成功
   - 智能体初始化成功
   - 分析完成，有最终决策

3. 记录分析结果（决策建议、置信度等）

**成功标准**：
- [ ] 分析成功完成
- [ ] 输出包含所有 18 个智能体的分析
- [ ] 有最终的投资组合决策

**扩展挑战**：
- 分析多只股票（AAPL, MSFT, NVDA）
- 尝试不同的时间范围
- 比较不同模型的结果（`--model` 参数）

---

## 1.9 知识检测

完成本章节学习后，请自检以下能力：

### 概念理解

- [ ] **系统定位**：能够用自己的话解释 AI Hedge Fund 系统的定位和用途
- [ ] **架构组成**：能够说明系统的主要组成部分及其功能
- [ ] **Poetry 优势**：能够解释为什么使用 Poetry 而不是 pip
- [ ] **API 密钥作用**：能够理解为什么需要配置 LLM API 密钥

### 动手能力

- [ ] **环境配置**：能够独立完成项目的完整安装和配置
- [ ] **依赖管理**：能够使用 Poetry 安装和管理依赖
- [ ] **问题解决**：能够解决常见的安装问题
- [ ] **验证安装**：能够验证安装是否成功

### 问题解决

- [ ] **错误定位**：能够根据错误信息定位安装问题
- [ ] **文档查阅**：能够查找文档解决安装中的疑问
- [ ] **资源利用**：能够利用在线资源解决问题
- [ ] **知识分享**：能够为他人解释安装步骤

---

## 1.10 进阶思考

如果你完成了基础安装，可以思考以下问题：

### 思考题 1

系统支持多种 LLM 提供商，它们之间有什么区别？不同提供商的价格和性能如何选择？

**提示**：
- 考虑响应速度
- 考虑分析质量
- 考虑成本
- 考虑使用场景

### 思考题 2

本地部署 Ollama 有什么优势和劣势？在什么情况下适合使用本地模型？

**提示**：
- 优势：数据隐私、无 API 费用、可离线运行
- 劣势：硬件要求高、模型更新慢、推理速度较慢

### 思考题 3

为什么系统使用 Poetry 而不是传统的 pip + requirements.txt？

**提示**：
- 依赖解析
- 虚拟环境管理
- 版本锁定
- 构建和发布

---

## 1.11 下一步

恭喜你完成了安装和环境配置！下一步，我们将学习如何运行第一个分析示例。

**下一章节**：[02-第一次运行](./02-first-run.md)

**学习目标**：
- 运行你的第一个股票分析
- 理解分析输出的含义
- 掌握基本的命令行操作

---

## 版本信息

| 项目 | 信息 |
|------|------|
| 文档版本 | 1.3.0 |
| 最后更新 | 2026 年 2 月 13 日 |
| 适用版本 | 1.0.0+ |

### 更新日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.3.0 | 2026.02.13 | 按照 chinese-doc-writer 规范全面改进：增加分层学习目标、更详细的步骤说明、更多视觉提示、完整的练习题和自检清单 |
| v1.0.2 | 2026.02.05 | 修正 API 密钥获取链接，完善故障排除章节 |
| v1.0.1 | 2025.12 | 增加 Ollama 本地部署说明 |
| v1.0.0 | 2025.10 | 初始版本 |

---

## 反馈与贡献

如果您在安装过程中遇到问题或有改进建议，欢迎通过以下方式提交反馈：

- 📝 **GitHub Issues**：提交 Bug 报告或功能建议
- 💬 **Discussion**：参与文档讨论

感谢您的反馈，这将帮助我们改进文档质量！

---

**📘 返回文档体系总览**：[SUMMARY.md](../SUMMARY.md)
