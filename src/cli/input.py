import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime

import questionary
from colorama import Fore, Style
from dateutil.relativedelta import relativedelta

from src.llm.defaults import get_default_model_config
from src.llm.models import (
    find_model_by_name,
    ModelProvider,
    OLLAMA_LLM_ORDER,
)
from src.utils.analysts import ANALYST_ORDER
from src.utils.logging import get_logger
from src.utils.ollama import ensure_ollama_and_model

logger = get_logger(__name__)


def add_common_args(
    parser: argparse.ArgumentParser,
    *,
    require_tickers: bool = False,
    include_analyst_flags: bool = True,
    include_ollama: bool = True,
) -> argparse.ArgumentParser:
    parser.add_argument(
        "--show-default-model",
        action="store_true",
        help="Print the currently resolved default model/provider from .env and exit",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        required=False,
        help="Comma-separated list of stock ticker symbols (e.g., AAPL,MSFT,GOOGL)",
    )
    if include_analyst_flags:
        parser.add_argument(
            "--analysts",
            type=str,
            required=False,
            help="Comma-separated list of analysts to use (e.g., michael_burry,other_analyst)",
        )
        parser.add_argument(
            "--analysts-all",
            action="store_true",
            help="Use all available analysts (overrides --analysts)",
        )
    if include_ollama:
        parser.add_argument("--ollama", action="store_true", help="Use Ollama for local LLM inference")
    parser.add_argument("--model", type=str, required=False, help="Model name to use (e.g., gpt-4o)")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto mode: run full-market screening pipeline (A-share only, no --ticker needed)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Return top N recommendations in --auto mode (default: 10)",
    )
    parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Return exit code 3 when --auto completes with degraded data quality",
    )
    parser.add_argument(
        "--explain",
        type=str,
        default=None,
        metavar="TICKER",
        help="Explain why TICKER was recommended (reads latest auto-screening report)",
    )
    parser.add_argument(
        "--why-not",
        type=str,
        default=None,
        metavar="TICKER",
        help=("反事实解释: 为什么 TICKER 没被推荐, 需要变什么才能进 Top 推荐" " (reads latest auto-screening report, P0-8)"),
    )
    parser.add_argument(
        "--daily-brief",
        action="store_true",
        help="盘前 5 分钟决策卡: Top 3 一句话 + 市场状态 + 行业轮动 (P0-7)",
    )
    return parser


def _resolve_default_end_date() -> str:
    """数据就绪阈值 + 交易日归一化: 返回最新可用开市日。

    A 股资金流 (tushare moneyflow / akshare push2his) 通常在收盘后 ~2 小时
    (约 17:00) 才完成当日数据入库。在 17:00 之前查询当日数据会得到空结果,
    导致 cache_refresh 报 "双源均失败"、筛选缺当日资金流信号。

    当不显式指定 --end-date 时, 17:00 前自动回退一天, 避免查到不存在的当日数据;
    17:00 后 (含) 取当天。随后统一归一化到最近开市日, 这样周日/周一盘前都会
    落到上周五, 不再生成周末 pseudo-date 报告。

    阈值可通过环境变量 DATA_READY_HOUR 覆盖 (默认 17)。

    本函数是 :func:`src.utils.date_utils.resolve_market_ready_date_iso` 的薄包装:
    把"当前墙钟"显式传进去 (而非让 helper 内部读 ``datetime.now()``), 这样
    测试 patch ``src.cli.input.datetime`` 时仍能控制行为 (详见
    ``tests/cli/test_input_dates.py``)。env 解析同样在本地完成以保持契约。

    Returns:
        YYYY-MM-DD 格式的默认结束日期
    """
    from src.utils.date_utils import resolve_market_ready_date_iso

    try:
        ready_hour = int(os.environ.get("DATA_READY_HOUR", "17"))
    except ValueError:
        ready_hour = 17
    return resolve_market_ready_date_iso(now=datetime.now(), ready_hour=ready_hour)


def add_date_args(parser: argparse.ArgumentParser, *, default_months_back: int | None = None) -> argparse.ArgumentParser:
    if default_months_back is None:
        parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
        parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD). Default: previous day if before 17:00, else today")
    else:
        # end-date 无 argparse default → resolve_dates 里动态计算 (17:00 阈值)。
        # 这样用户显式传 --end-date 时完全不受影响, 不传时走 _resolve_default_end_date。
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="End date in YYYY-MM-DD format. Default: previous day if before 17:00, else today",
        )
        default_end_for_start = _resolve_default_end_date()
        parser.add_argument(
            "--start-date",
            type=str,
            default=(datetime.strptime(default_end_for_start, "%Y-%m-%d") - relativedelta(months=default_months_back)).strftime("%Y-%m-%d"),
            help="Start date in YYYY-MM-DD format",
        )
    return parser


def parse_tickers(tickers_arg: str | None) -> list[str]:
    if not tickers_arg:
        return []
    return [ticker.strip() for ticker in tickers_arg.split(",") if ticker.strip()]


def select_analysts(flags: dict | None = None) -> list[str]:
    if flags and flags.get("analysts_all"):
        return [a[1] for a in ANALYST_ORDER]

    if flags and flags.get("analysts"):
        return [a.strip() for a in flags["analysts"].split(",") if a.strip()]

    choices = questionary.checkbox(
        "Select your AI analysts.",
        choices=[questionary.Choice(display, value=value) for display, value in ANALYST_ORDER],
        instruction="\n\nInstructions: \n1. Press Space to select/unselect analysts.\n2. Press 'a' to select/unselect all.\n3. Press Enter when done.",
        validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
        style=questionary.Style(
            [
                ("checkbox-selected", "fg:green"),
                ("selected", "fg:green noinherit"),
                ("highlighted", "noinherit"),
                ("pointer", "noinherit"),
            ]
        ),
    ).ask()

    if not choices:
        logger.info("Interrupt received. Exiting...")
        sys.exit(0)

    logger.info(f"Selected analysts: {', '.join(c.title().replace('_', ' ') for c in choices)}")
    print(f"\nSelected analysts: {', '.join(Fore.GREEN + c.title().replace('_', ' ') + Style.RESET_ALL for c in choices)}\n")
    return choices


def select_model(use_ollama: bool, model_flag: str | None = None) -> tuple[str, str]:
    model_name: str = ""
    model_provider: str | None = None

    if model_flag:
        model = find_model_by_name(model_flag)
        if model:
            logger.info(f"Using specified model: {model.provider.value} - {model.model_name}")
            print(f"\nUsing specified model: {Fore.CYAN}{model.provider.value}{Style.RESET_ALL} - {Fore.GREEN + Style.BRIGHT}{model.model_name}{Style.RESET_ALL}\n")
            return model.model_name, model.provider.value
        logger.warning(f"Model '{model_flag}' not found. Please select a model.")
        print(f"{Fore.RED}Model '{model_flag}' not found. Please select a model.{Style.RESET_ALL}")

    if not use_ollama:
        default_model_name, default_model_provider = get_default_model_config()
        logger.info(f"Using default model from environment: {default_model_provider} - {default_model_name}")
        print(f"\nUsing default model from environment: {Fore.CYAN}{default_model_provider}{Style.RESET_ALL}" f" - {Fore.GREEN + Style.BRIGHT}{default_model_name}{Style.RESET_ALL}\n")
        return default_model_name, default_model_provider

    if use_ollama:
        logger.info("Using Ollama for local LLM inference.")
        print(f"{Fore.CYAN}Using Ollama for local LLM inference.{Style.RESET_ALL}")
        model_name = questionary.select(
            "Select your Ollama model:",
            choices=[questionary.Choice(display, value=value) for display, value, _ in OLLAMA_LLM_ORDER],
            style=questionary.Style(
                [
                    ("selected", "fg:green bold"),
                    ("pointer", "fg:green bold"),
                    ("highlighted", "fg:green"),
                    ("answer", "fg:green bold"),
                ]
            ),
        ).ask()

        if not model_name:
            logger.info("Interrupt received. Exiting...")
            sys.exit(0)

        if model_name == "-":
            model_name = questionary.text("Enter the custom model name:").ask()
            if not model_name:
                logger.info("Interrupt received. Exiting...")
                sys.exit(0)

        if not ensure_ollama_and_model(model_name):
            logger.error("Cannot proceed without Ollama and the selected model.")
            print(f"{Fore.RED}Cannot proceed without Ollama and the selected model.{Style.RESET_ALL}")
            sys.exit(1)

        model_provider = ModelProvider.OLLAMA.value
        logger.info(f"Selected Ollama model: {model_name}")
        print(f"\nSelected {Fore.CYAN}Ollama{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n")
    return model_name, model_provider or ""


def resolve_dates(start_date: str | None, end_date: str | None, *, default_months_back: int | None = None) -> tuple[str, str]:
    if start_date:
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError("Start date must be in YYYY-MM-DD format") from e
    if end_date:
        try:
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError("End date must be in YYYY-MM-DD format") from e

    # 17:00 阈值: 不传 --end-date 时, 未过 17:00 取前一天 (当日资金流数据未就绪)。
    # 显式传 --end-date 时 end_date 非空, 完全尊重用户指定。
    final_end = end_date or _resolve_default_end_date()
    if start_date:
        final_start = start_date
    else:
        months = default_months_back if default_months_back is not None else 3
        end_date_obj = datetime.strptime(final_end, "%Y-%m-%d")
        final_start = (end_date_obj - relativedelta(months=months)).strftime("%Y-%m-%d")
    return final_start, final_end


@dataclass
class CLIInputs:
    tickers: list[str]
    selected_analysts: list[str]
    model_name: str
    model_provider: str
    start_date: str
    end_date: str
    initial_cash: float
    margin_requirement: float
    show_reasoning: bool = False
    show_agent_graph: bool = False
    auto: bool = False
    top_n: int = 10
    strict_quality: bool = False
    explain: str = ""
    why_not: str = ""
    raw_args: argparse.Namespace | None = None


def parse_cli_inputs(
    *,
    description: str,
    require_tickers: bool,
    default_months_back: int | None,
    include_graph_flag: bool = False,
    include_reasoning_flag: bool = False,
) -> CLIInputs:
    parser = argparse.ArgumentParser(description=description)

    # Common/interactive flags
    add_common_args(parser, require_tickers=require_tickers, include_analyst_flags=True, include_ollama=True)
    add_date_args(parser, default_months_back=default_months_back)

    # Funding flags (standardized, with alias)
    parser.add_argument(
        "--initial-cash",
        "--initial-capital",
        dest="initial_cash",
        type=float,
        default=100000.0,
        help="Initial cash position (alias: --initial-capital). Defaults to 100000.0",
    )
    parser.add_argument(
        "--margin-requirement",
        dest="margin_requirement",
        type=float,
        default=0.0,
        help="Initial margin requirement ratio for shorts (e.g., 0.5 for 50%%). Defaults to 0.0",
    )

    if include_reasoning_flag:
        parser.add_argument("--show-reasoning", action="store_true", help="Show reasoning from each agent")
    if include_graph_flag:
        parser.add_argument("--show-agent-graph", action="store_true", help="Show the agent graph")

    args = parser.parse_args()

    is_auto = getattr(args, "auto", False)

    if getattr(args, "show_default_model", False):
        default_model_name, default_model_provider = get_default_model_config()
        print(f"default_model_provider={default_model_provider}")
        print(f"default_model_name={default_model_name}")
        sys.exit(0)

    # Normalize parsed values
    tickers = parse_tickers(getattr(args, "tickers", None))
    if require_tickers and not tickers and not is_auto:
        parser.error("the following arguments are required: --tickers")

    # In --auto mode, skip interactive analyst/model selection
    if is_auto:
        selected_analysts = [a[1] for a in ANALYST_ORDER]
        model_name, model_provider = get_default_model_config()
    else:
        selected_analysts = select_analysts(
            {
                "analysts_all": getattr(args, "analysts_all", False),
                "analysts": getattr(args, "analysts", None),
            }
        )
        model_name, model_provider = select_model(getattr(args, "ollama", False), getattr(args, "model", None))
    start_date, end_date = resolve_dates(getattr(args, "start_date", None), getattr(args, "end_date", None), default_months_back=default_months_back)

    return CLIInputs(
        tickers=tickers,
        selected_analysts=selected_analysts,
        model_name=model_name,
        model_provider=model_provider,
        start_date=start_date,
        end_date=end_date,
        initial_cash=getattr(args, "initial_cash", 100000.0),
        margin_requirement=getattr(args, "margin_requirement", 0.0),
        show_reasoning=getattr(args, "show_reasoning", False),
        show_agent_graph=getattr(args, "show_agent_graph", False),
        auto=is_auto,
        top_n=getattr(args, "top_n", 10),
        strict_quality=getattr(args, "strict_quality", False),
        explain=getattr(args, "explain", None) or "",
        why_not=getattr(args, "why_not", None) or "",
        raw_args=args,
    )
