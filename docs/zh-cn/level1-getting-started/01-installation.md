# 第一章：安装与环境配置

## 学习目标

完成本章节学习后，你将能够理解 AI Hedge Fund 系统的基本概念和功能定位，掌握开发环境的配置方法，成功安装项目依赖并配置 API 密钥，验证安装是否成功完成。这些基础技能是后续学习和使用系统的必要前提，预计学习时间为 30 分钟至 1 小时。

## 1.1 系统概述

在开始安装之前，我们首先来了解这个系统是什么、能做什么、不能做什么。AI Hedge Fund 是一个概念验证项目，旨在探索使用人工智能进行投资决策的可能性。这个系统模拟了 18 位著名投资大师的分析风格，包括价值投资的沃伦·巴菲特、成长投资的彼得·林奇、宏观策略的斯坦利·德鲁肯米勒等，通过大型语言模型的推理能力生成投资建议。

理解这个系统的定位非常重要。这个系统目前仅用于教育和研究目的，不进行真实的交易操作。它可以帮助你了解不同投资风格的思考方式，学习量化投资的基本概念，但不能替代专业的投资顾问。做出的任何投资决策都应该基于你自己的判断，并考虑个人的财务状况、投资目标和风险承受能力。

系统的核心架构包含三个主要部分。第一部分是数据层，负责从外部数据源获取金融数据，包括价格数据、财务报表、新闻资讯等。第二部分是智能体层，包含 18 个专业智能体，每个智能体负责特定的分析任务。第三部分是决策层，整合各智能体的输出，进行风险评估和投资组合优化，生成最终的交易建议。

## 1.2 系统要求

### 硬件要求

系统的硬件要求取决于你的使用场景。如果你只是运行基本分析功能，最低配置要求相对较低。最低配置需要双核 2.0GHz 以上 CPU、4GB RAM 和 5GB 可用磁盘空间。推荐配置为四核 3.0GHz 以上 CPU、8GB RAM 和 10GB 可用磁盘空间，这个配置可以保证流畅的使用体验。

如果你需要运行本地的大型语言模型（通过 Ollama），则需要更高的配置。推荐使用支持 CUDA 的 NVIDIA GPU 或 Apple Silicon（M 系列芯片），并配备 16GB 以上 RAM，额外需要 20GB 以上的磁盘空间用于存储模型文件。

### 软件要求

操作系统方面，系统支持 macOS 10.15+（Catalina 及以上版本）、Ubuntu 20.04+ 以及 Windows 10+。Windows 用户建议通过 WSL2（Windows Subsystem for Linux）运行，这可以避免许多兼容性问题。

必需软件包括以下几项。Python 版本要求 3.11 或更高版本，建议使用 3.11.x 系列以获得最佳的包兼容性。Git 用于版本控制，是获取项目源码的必要工具。Poetry 是 Python 的依赖管理工具，用于管理项目的依赖包。curl 用于下载安装脚本，是大多数操作系统的标准配置。

可选软件包括 Docker（容器化部署）和 Ollama（本地 LLM 运行）。这些软件在基础使用场景下不是必需的，但如果需要容器化部署或本地运行 LLM，则需要安装。

### 网络要求

系统运行需要访问互联网，主要用于两个方面。第一是调用 LLM 服务的 API（如 OpenAI、Anthropic 等），这需要稳定的网络连接。第二是获取金融数据，这同样需要访问外部数据服务。请确保你的网络环境可以访问这些服务，某些地区可能需要配置 VPN。

## 1.3 安装步骤

### 步骤一：克隆项目

首先，打开终端（Terminal），执行以下命令将项目克隆到本地：

```bash
git clone https://github.com/virattt/ai-hedge-fund.git
cd ai-hedge-fund
```

克隆完成后，项目文件将保存在当前目录下的 `ai-hedge-fund` 文件夹中。所有后续命令都默认在此目录下执行。如果你的网络环境无法访问 GitHub，可以考虑使用镜像源或手动下载源码包。

克隆完成后，你可以查看项目的目录结构：

```bash
ls -la
```

你应该能看到以下主要目录和文件：`src/` 包含项目的源代码，`app/` 包含 Web 应用代码，`docs/` 包含文档，`pyproject.toml` 是项目配置文件，`README.md` 是项目说明文件。

### 步骤二：安装 Poetry

Poetry 是 Python 的依赖管理工具，它将项目的依赖和版本信息集中管理，简化了环境配置。如果你的系统中已经安装了 Poetry，可以跳过此步骤。

**macOS 和 Linux 系统**的安装命令如下：

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

**Windows 系统**需要在 PowerShell 中以管理员身份执行：

```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python3 -
```

安装完成后，通过以下命令验证安装是否成功：

```bash
poetry --version
```

如果命令返回版本号（例如 `Poetry version 1.7.1`），则表示安装成功。如果提示命令未找到，请检查 Poetry 是否正确添加到 PATH，或尝试重启终端。

Poetry 安装脚本会自动将 Poetry 添加到用户 PATH 中，但可能需要重启终端才能生效。如果遇到问题，可以尝试以下解决方案。第一种方案是使用 pip 安装 Poetry：`pip install poetry`。第二种方案是使用 conda 安装：`conda install -c conda-forge poetry`。第三种方案是手动下载安装脚本并执行。

### 步骤三：安装项目依赖

在项目根目录下执行以下命令，Poetry 会自动创建虚拟环境并安装所有依赖：

```bash
poetry install
```

这个过程可能需要几分钟时间，取决于你的网络速度和系统性能。首次运行时，Poetry 会从 PyPI 下载所有依赖包并安装到独立的虚拟环境中。

如果遇到网络超时或包版本冲突，可以尝试以下解决方案。第一个方案是使用国内镜像源，可以在 `pyproject.toml` 中配置或使用环境变量设置。第二个方案是更新 Poetry 到最新版本：`pip install --upgrade poetry`。第三个方案是删除现有的虚拟环境并重新创建，执行命令 `poetry env remove python && poetry install`。第四个方案是在干净的 Python 虚拟环境中安装，确保使用 Python 3.11 版本。

安装完成后，可以通过以下命令进入 Poetry 创建的虚拟环境：

```bash
poetry shell
```

在这个环境中，所有 Python 相关的命令都会使用项目指定的依赖版本。在虚拟环境外执行命令时，需要使用 `poetry run python` 的形式来调用正确版本的 Python 解释器。

### 步骤四：配置 API 密钥

系统需要配置 LLM 提供商的 API 密钥才能正常运行。首先，复制环境变量模板文件：

```bash
cp .env.example .env
```

然后使用文本编辑器打开 `.env` 文件，根据你的需求配置以下变量。

**必需配置**：你需要至少选择配置一个 LLM 提供商的 API 密钥。可选配置包括 `OPENAI_API_KEY` 用于 OpenAI 的 GPT 系列模型、`ANTHROPIC_API_KEY` 用于 Anthropic 的 Claude 系列模型、`GROQ_API_KEY` 用于 Groq 的高速推理服务，或 `DEEPSEEK_API_KEY` 用于 DeepSeek 的模型。

**可选配置**：`FINANCIAL_DATASETS_API_KEY` 用于获取更多股票的财务数据。需要注意的是，AAPL、GOOGL、MSFT、NVDA、TSLA 这五只股票的数据免费，其他股票需要有效的 API 密钥。`GOOGLE_API_KEY` 用于 Google 的 Gemini 系列模型，`XAI_API_KEY` 用于 xAI 的模型。

配置示例如下：

```bash
# LLM 提供商配置（至少选择一个）
OPENAI_API_KEY=sk-your-openai-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
GROQ_API_KEY=your-groq-api-key

# 金融数据配置（可选）
FINANCIAL_DATASETS_API_KEY=your-financial-datasets-api-key

# 其他配置（可选）
LOG_LEVEL=INFO
```

关于 API 密钥的获取，以下是各主要提供商的相关信息。OpenAI 的 API 密钥可以在 https://platform.openai.com/api-keys 申请。Anthropic 的 API 密钥可以在 https://console.anthropic.com/keys 申请。Groq 的 API 密钥可以在 https://console.groq.com/keys 申请。DeepSeek 的 API 密钥可以在 https://platform.deepseek.com/ 申请。Financial Datasets API 的密钥可以在 https://financialdatasets.ai/ 申请。

## 1.5 验证安装

完成所有配置后，可以通过以下命令验证安装是否成功。

**测试基本功能**：

```bash
poetry run python src/main.py --help
```

如果命令正常显示帮助信息，则表示基础安装成功。帮助信息应该显示可用的命令参数和选项说明。

**运行简单测试**：

```bash
poetry run python src/main.py --ticker AAPL --start-date 2024-01-01 --end-date 2024-01-02
```

这个命令会分析苹果公司（AAPL）在 2024 年 1 月 1 日到 1 月 2 日期间的数据。由于时间范围很短，分析应该很快完成。

如果看到类似以下的输出，则表示系统运行正常：

```
AI Hedge Fund Analysis
======================

Analyzing ticker: AAPL
Using model: gpt-4o

Initializing market data...
 ✓ Data loaded successfully

[各智能体的分析输出]

Analysis complete!
```

## 1.6 Web 应用安装（可选）

如果你更倾向于使用 Web 界面而非命令行，需要额外安装前端依赖。

**步骤一**：进入应用目录：

```bash
cd app
```

**步骤二**：安装 Node.js 依赖：

```bash
npm install
```

**步骤三**：启动后端服务（在一个新的终端窗口中）：

```bash
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**步骤四**：启动前端开发服务器（在另一个终端窗口中）：

```bash
npm run dev
```

完成上述步骤后，打开浏览器访问 `http://localhost:5173`，你应该能看到 Web 应用界面。

## 1.7 常见安装问题

### 问题一：Poetry 安装失败

如果 Poetry 安装后无法正常使用，请尝试以下解决方案。

第一种方法，确认安装脚本已正确执行，可以通过 `curl --version` 确保 curl 命令可用。第二种方法，检查 Poetry 是否正确添加到 PATH，在 macOS/Linux 上通常位于 `~/.local/bin/poetry`，在 Windows 上位于 `%APPDATA%\Python\Scripts\poetry`。如果 PATH 配置正确但仍然无法使用，可以尝试手动添加软链接或重新运行安装脚本。第三种方法，可以考虑使用 pip 安装 Poetry：`pip install poetry`，但这可能需要额外配置环境。

### 问题二：依赖安装版本冲突

依赖版本冲突通常发生在 Poetry 尝试安装的包版本与已安装的其他包不兼容时。解决方案包括：更新 Poetry 到最新版本（`pip install --upgrade poetry`）；删除现有的虚拟环境并重新创建（`poetry env remove python && poetry install`）；显式指定包的版本约束（编辑 `pyproject.toml`）；如果冲突无法解决，可以尝试在干净的 Python 虚拟环境中安装。

### 问题三：Windows 系统兼容性问题

Windows 用户建议使用 WSL2（Windows Subsystem for Linux）来运行项目，这可以避免许多 Windows 特有的兼容性问题。安装 WSL2 后，在 WSL2 终端中按照 Linux 的安装说明操作。如果必须在原生 Windows 上运行，请确保安装 Visual Studio Build Tools 以编译某些 C++ 扩展包，并在 PowerShell 中以管理员身份执行安装命令。

### 问题四：API 密钥配置错误

如果遇到与 API 密钥相关的错误，请检查以下几点。首先，确认 `.env` 文件位于项目根目录，且文件扩展名正确（不是 `.env.txt`）。其次，检查 API 密钥格式是否正确，不要包含多余的空格或换行符。第三，确认 API 密钥有足够的配额和正确的权限。第四，对于某些提供商，需要设置额外的配置（如 OpenAI 的组织 ID）。可以使用 `poetry run python -c "import os; print(os.getenv('OPENAI_API_KEY'))"` 来验证环境变量是否正确加载。

## 1.8 练习题

### 练习 1.1：环境验证

**任务**：验证你的开发环境是否满足所有要求。

**步骤**：首先检查 Python 版本，执行命令 `python --version` 或 `python3 --version`，确认版本号以 3.11 开头。然后检查 Poetry 版本，执行 `poetry --version`，确认版本号显示正常。最后检查 Git 版本，执行 `git --version`，确认版本号显示正常。

**成功标准**：三个命令都能正常返回版本号，没有任何错误信息。

### 练习 1.2：项目克隆与依赖安装

**任务**：完成项目的克隆和依赖安装。

**步骤**：首先克隆项目到本地（如果尚未完成），然后进入项目目录，接着执行 `poetry install` 安装依赖，最后验证安装。

**成功标准**：能够成功执行 `poetry run python src/main.py --help` 并看到帮助信息。

### 练习 1.3：API 密钥配置

**任务**：配置至少一个 LLM 提供商的 API 密钥。

**步骤**：首先复制 `.env.example` 到 `.env`，然后使用文本编辑器打开 `.env` 文件，接着添加你的 API 密钥（以 `#` 开头的是注释，可以删除或保留），最后验证配置是否生效。

**成功标准**：执行 `poetry run python -c "import os; print('OPENAI_API_KEY configured:', bool(os.getenv('OPENAI_API_KEY')))"` 显示配置状态为 True。

## 1.9 知识检测

完成本章节学习后，请自检以下能力：

**概念理解**方面，你能够用自己的话解释 AI Hedge Fund 系统的定位和用途，能够说明系统的主要组成部分及其功能，能够理解为什么需要配置 LLM API 密钥。

**动手能力**方面，你能够独立完成项目的完整安装和配置，能够解决常见的安装问题，能够验证安装是否成功。

**问题解决**方面，你能够根据错误信息定位安装问题，能够查找文档解决安装中的疑问，能够为他人解释安装步骤。

---

## 进阶思考

如果你完成了基础安装，可以思考以下问题。系统支持多种 LLM 提供商，它们之间有什么区别？不同提供商的价格和性能如何选择？本地部署 Ollama 有什么优势和劣势？

下一章节我们将学习如何运行第一个分析示例。
