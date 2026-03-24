# AI Hedge Fund

This is a proof of concept for an AI-powered hedge fund.  The goal of this project is to explore the use of AI to make trading decisions.  This project is for **educational** purposes only and is not intended for real trading or investment.

This system employs several agents working together:

1. Aswath Damodaran Agent - The Dean of Valuation, focuses on story, numbers, and disciplined valuation
2. Ben Graham Agent - The godfather of value investing, only buys hidden gems with a margin of safety
3. Bill Ackman Agent - An activist investor, takes bold positions and pushes for change
4. Cathie Wood Agent - The queen of growth investing, believes in the power of innovation and disruption
5. Charlie Munger Agent - Warren Buffett's partner, only buys wonderful businesses at fair prices
6. Michael Burry Agent - The Big Short contrarian who hunts for deep value
7. Mohnish Pabrai Agent - The Dhandho investor, who looks for doubles at low risk
8. Peter Lynch Agent - Practical investor who seeks "ten-baggers" in everyday businesses
9. Phil Fisher Agent - Meticulous growth investor who uses deep "scuttlebutt" research 
10. Rakesh Jhunjhunwala Agent - The Big Bull of India
11. Stanley Druckenmiller Agent - Macro legend who hunts for asymmetric opportunities with growth potential
12. Warren Buffett Agent - The oracle of Omaha, seeks wonderful companies at a fair price
13. Valuation Agent - Calculates the intrinsic value of a stock and generates trading signals
14. Sentiment Agent - Analyzes market sentiment and generates trading signals
15. Fundamentals Agent - Analyzes fundamental data and generates trading signals
16. Technicals Agent - Analyzes technical indicators and generates trading signals
17. Risk Manager - Calculates risk metrics and sets position limits
18. Portfolio Manager - Makes final trading decisions and generates orders

<img width="1042" alt="Screenshot 2025-03-22 at 6 19 07 PM" src="https://github.com/user-attachments/assets/cbae3dcf-b571-490d-b0ad-3f0f035ac0d4" />

Note: the system does not actually make any trades.

[![Twitter Follow](https://img.shields.io/twitter/follow/virattt?style=social)](https://twitter.com/virattt)

## Disclaimer

This project is for **educational and research purposes only**.

- Not intended for real trading or investment
- No investment advice or guarantees provided
- Creator assumes no liability for financial losses
- Consult a financial advisor for investment decisions
- Past performance does not indicate future results

By using this software, you agree to use it solely for learning purposes.

## Table of Contents
- [AI Hedge Fund](#ai-hedge-fund)
  - [Disclaimer](#disclaimer)
  - [Table of Contents](#table-of-contents)
  - [How to Install](#how-to-install)
    - [1. Clone the Repository](#1-clone-the-repository)
    - [2. Set up API keys](#2-set-up-api-keys)
  - [How to Run](#how-to-run)
    - [⌨️ Command Line Interface](#️-command-line-interface)
      - [Quick Start](#quick-start)
      - [Run the AI Hedge Fund](#run-the-ai-hedge-fund)
      - [Run the Backtester](#run-the-backtester)
      - [Control Analyst Concurrency](#control-analyst-concurrency)
        - [Track Data Cache](#track-data-cache)
    - [🖥️ Web Application](#️-web-application)
  - [How to Contribute](#how-to-contribute)
  - [Feature Requests](#feature-requests)
  - [License](#license)

## How to Install

Before you can run the AI Hedge Fund, you'll need to install it and set up your API keys. These steps are common to both the full-stack web application and command line interface.

### 1. Clone the Repository

```bash
git clone https://github.com/virattt/ai-hedge-fund.git
cd ai-hedge-fund
```

### 2. Set up API keys

Create a `.env` file for your API keys:
```bash
# Create .env file for your API keys (in the root directory)
cp .env.example .env
```

Open and edit the `.env` file to add your API keys:
```bash
# For running LLMs hosted by openai (gpt-4o, gpt-4o-mini, etc.)
OPENAI_API_KEY=your-openai-api-key

# Optional: set a unified default model route for every CLI/script/web entry
LLM_DEFAULT_MODEL_PROVIDER=MiniMax
LLM_DEFAULT_MODEL_NAME=MiniMax-M2.7

# For getting financial data to power the hedge fund
FINANCIAL_DATASETS_API_KEY=your-financial-datasets-api-key
```

**Important**: You must set at least one LLM API key (e.g. `OPENAI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, or `DEEPSEEK_API_KEY`) for the hedge fund to work. 

**Default Model Routing**: You must explicitly set both `LLM_DEFAULT_MODEL_PROVIDER` and `LLM_DEFAULT_MODEL_NAME` for default routing. To avoid silent model downgrades, the system no longer falls back to provider-specific model variables such as `MINIMAX_MODEL` or `MINIMAX_FALLBACK_MODEL` when resolving the default model.

You can inspect the currently resolved default model with:

```bash
.venv/bin/python scripts/list-models.py
```

**Financial Data**: Data for AAPL, GOOGL, MSFT, NVDA, and TSLA is free and does not require an API key. For any other ticker, you will need to set the `FINANCIAL_DATASETS_API_KEY` in the .env file.

## How to Run

### ⌨️ Command Line Interface

You can run the AI Hedge Fund directly via terminal. This approach offers more granular control and is useful for automation, scripting, and integration purposes.

<img width="992" alt="Screenshot 2025-01-06 at 5 50 17 PM" src="https://github.com/user-attachments/assets/e8ca04bf-9989-4a7d-a8b4-34e04666663b" />

#### Quick Start

1. Install Poetry (if not already installed):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Install dependencies:
```bash
poetry install
```

#### Run the AI Hedge Fund
```bash
poetry run python src/main.py --ticker AAPL,MSFT,NVDA
```

You can also specify a `--ollama` flag to run the AI hedge fund using local LLMs.

```bash
poetry run python src/main.py --ticker AAPL,MSFT,NVDA --ollama
```

You can optionally specify the start and end dates to make decisions over a specific time period.

```bash
poetry run python src/main.py --ticker AAPL,MSFT,NVDA --start-date 2024-01-01 --end-date 2024-03-01
```

You can inspect the currently resolved default model directly from the main CLI.

```bash
poetry run python src/main.py --show-default-model
```

#### Run the Backtester
```bash
poetry run python src/backtester.py --ticker AAPL,MSFT,NVDA
```

#### Control Analyst Concurrency

For pipeline-style hedge fund runs and A/B backtests, the environment variable `ANALYST_CONCURRENCY_LIMIT` controls the default size of each provider lane.

- `1` means fully serialized analysis. This is the safest option when your LLM quota is tight, but also the slowest.
- `2` means two analysts run in parallel per wave. This was the original conservative default used to stabilize long A-share runs.
- `3` means three analysts run in parallel per provider lane. When both Zhipu and MiniMax are available, the system can schedule them together for up to `6` analyst calls in the same wave.
- `MINIMAX_PROVIDER_CONCURRENCY_LIMIT` and `ZHIPU_PROVIDER_CONCURRENCY_LIMIT` let you bias the split instead of keeping the two providers at `1:1`.
- `LLM_PRIMARY_PROVIDER=MiniMax` makes the weighted wave start from MiniMax first, which is useful when MiniMax is your main workhorse and Zhipu is the overflow lane.
- Larger values increase throughput, but they also increase the chance of provider-side `429`, quota exhaustion, or unstable long-running jobs.

This setting does **not** change the number of stocks being processed. It only changes how many analyst personas are evaluated concurrently before the workflow moves on to the next batch. In dual-provider mode, total concurrency is approximately `MINIMAX_PROVIDER_CONCURRENCY_LIMIT + ZHIPU_PROVIDER_CONCURRENCY_LIMIT` when those two variables are set, otherwise it remains approximately `ANALYST_CONCURRENCY_LIMIT * 2`.

**Examples**

Run the main program with conservative concurrency:

```bash
ANALYST_CONCURRENCY_LIMIT=2 poetry run python src/main.py --ticker AAPL,MSFT,NVDA
```

Run a real A/B backtest with moderate concurrency:

```bash
ANALYST_CONCURRENCY_LIMIT=3 .venv/bin/backtester --ab-compare --mode pipeline \
  --start-date 2025-12-01 --end-date 2026-03-04 \
  --train-months 2 --test-months 1 --step-months 1 \
  --model-provider Zhipu --model-name glm-4.7 \
  --analysts-all \
  --report-file data/reports/ab_walk_forward_first_pilot.md \
  --report-json data/reports/ab_walk_forward_first_pilot.json
```

Run a weighted dual-provider backtest where MiniMax carries more traffic and Zhipu stays as a spillover lane:

```bash
ANALYST_CONCURRENCY_LIMIT=3 \
MINIMAX_PROVIDER_CONCURRENCY_LIMIT=4 \
ZHIPU_PROVIDER_CONCURRENCY_LIMIT=2 \
LLM_PRIMARY_PROVIDER=MiniMax \
.venv/bin/backtester --ab-compare --mode pipeline \
  --start-date 2025-12-01 --end-date 2026-03-04 \
  --train-months 2 --test-months 1 --step-months 1 \
  --model-provider Zhipu --model-name glm-4.7 \
  --analysts-all \
  --report-file data/reports/ab_weighted_dual_provider.md \
  --report-json data/reports/ab_weighted_dual_provider.json
```

Run the supervisor so that all future restart attempts also keep the same concurrency:

```bash
.venv/bin/python scripts/supervise_ab_compare.py \
  --start-date 2025-12-01 --end-date 2026-03-04 \
  --train-months 2 --test-months 1 --step-months 1 \
  --analyst-concurrency-limit 3 \
  --report-file data/reports/ab_walk_forward_first_pilot.md \
  --report-json data/reports/ab_walk_forward_first_pilot.json \
  --first-reset '2026-03-08 05:00:00'
```

#### Track LLM Metrics

Every shared LLM call now writes structured metrics into the `logs/` directory.

- One JSONL file records every logical LLM attempt, including provider, model, agent, duration, success/failure, and whether the error was a rate-limit.
- One summary JSON file keeps an aggregated view by provider, model, and agent so you can quickly judge where the bottleneck is.

Example output files:

- `logs/llm_metrics_20260310_183246.jsonl`
- `logs/llm_metrics_20260310_183246.summary.json`

Summarize a metrics file after a run:

```bash
.venv/bin/python scripts/summarize_llm_metrics.py logs/llm_metrics_20260310_183246.jsonl
```

You can also save the aggregated result:

```bash
.venv/bin/python scripts/summarize_llm_metrics.py \
  logs/llm_metrics_20260310_183246.jsonl \
  --output data/reports/llm_metrics_summary.json
```

#### Track Data Cache

Repeated stock-selection, replay, and backtesting windows often reuse the same Tushare and AKShare payloads. The project now persists hot market-data responses through the multi-layer cache in `src/data/enhanced_cache.py`, so overlapping reruns can hit the local SQLite cache instead of refetching from upstream providers.

Default cache location:

- `~/.cache/ai-hedge-fund/cache.sqlite`
- Override with `DISK_CACHE_PATH=/custom/path/cache.sqlite`

Inspect cache runtime info and counters:

```bash
.venv/bin/python scripts/manage_data_cache.py stats
```

Write the same runtime payload to a file:

```bash
.venv/bin/python scripts/manage_data_cache.py stats \
  --output data/reports/data_cache_stats.json
```

Clear the local cache explicitly:

```bash
.venv/bin/python scripts/manage_data_cache.py clear --yes
```

Validate cross-process reuse on a representative trade date:

```bash
source .env && \
.venv/bin/python scripts/validate_data_cache_reuse.py \
  --trade-date 20260305 \
  --ticker 300724 \
  --output data/reports/data_cache_reuse_20260305.json
```

Run a cold-vs-warm benchmark summary in one command:

```bash
source .env && \
.venv/bin/python scripts/benchmark_data_cache_reuse.py \
  --trade-date 20260305 \
  --ticker 300724 \
  --clear-first \
  --output data/reports/data_cache_benchmark_20260305.json
```

Interpretation guidelines:

- The first run should usually show `misses` and `sets` increasing.
- Re-running the exact same command should shift the session toward `disk_hits` with few or no new `misses`.
- `manage_data_cache.py stats` now also reports `disk_entry_count` and `disk_file_size_bytes`, which is useful when you want to confirm the local cache is actually growing across experiments.
- `session_summary.json` for paper-trading runs now also records `data_cache`, `data_cache.session_stats`, and `artifacts.data_cache_path` for later inspection.
- `benchmark_data_cache_reuse.py` wraps the first and second runs into one JSON summary so you can compare cold-start vs warm-cache behavior without manual diffing.
- For a Chinese quickstart focused on cache inspection and reuse validation, see `docs/zh-cn/manual/data-cache-reuse-manual.md`.

If you are running under unstable quota conditions, increase concurrency gradually. In practice, moving from `2` to `3` is usually a safer step than jumping directly to `4` or higher.

**Example Output:**
<img width="941" alt="Screenshot 2025-01-06 at 5 47 52 PM" src="https://github.com/user-attachments/assets/00e794ea-8628-44e6-9a84-8f8a31ad3b47" />


Note: The `--ollama`, `--start-date`, and `--end-date` flags work for the backtester, as well!

### 🖥️ Web Application

The new way to run the AI Hedge Fund is through our web application that provides a user-friendly interface. This is recommended for users who prefer visual interfaces over command line tools.

Please see detailed instructions on how to install and run the web application [here](https://github.com/virattt/ai-hedge-fund/tree/main/app).

<img width="1721" alt="Screenshot 2025-06-28 at 6 41 03 PM" src="https://github.com/user-attachments/assets/b95ab696-c9f4-416c-9ad1-51feb1f5374b" />


## How to Contribute

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

**Important**: Please keep your pull requests small and focused.  This will make it easier to review and merge.

## Feature Requests

If you have a feature request, please open an [issue](https://github.com/virattt/ai-hedge-fund/issues) and make sure it is tagged with `enhancement`.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
