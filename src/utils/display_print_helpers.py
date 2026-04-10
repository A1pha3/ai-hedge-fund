import json

from colorama import Fore, Style


def stringify_reasoning(reasoning: object) -> str:
    if isinstance(reasoning, str):
        return reasoning
    if isinstance(reasoning, dict):
        return json.dumps(reasoning, indent=2)
    return str(reasoning)


def wrap_output_text(text: object, max_line_length: int = 60) -> str:
    if not text:
        return ""

    words = stringify_reasoning(text).split()
    wrapped_lines: list[str] = []
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 > max_line_length:
            wrapped_lines.append(current_line)
            current_line = word
        else:
            current_line = f"{current_line} {word}".strip()
    if current_line:
        wrapped_lines.append(current_line)
    return "\n".join(wrapped_lines)


def build_agent_signal_table_rows(ticker: str, analyst_signals: dict) -> list[list[str]]:
    table_data: list[list[str]] = []
    for agent, signals in analyst_signals.items():
        if ticker not in signals or agent == "risk_management_agent":
            continue

        signal = signals[ticker]
        agent_name = agent.replace("_agent", "").replace("_", " ").title()
        signal_type = signal.get("signal", "").upper()
        confidence = signal.get("confidence", 0)
        signal_color = {"BULLISH": Fore.GREEN, "BEARISH": Fore.RED, "NEUTRAL": Fore.YELLOW}.get(signal_type, Fore.WHITE)

        table_data.append(
            [
                f"{Fore.CYAN}{agent_name}{Style.RESET_ALL}",
                f"{signal_color}{signal_type}{Style.RESET_ALL}",
                f"{Fore.WHITE}{confidence}%{Style.RESET_ALL}",
                f"{Fore.WHITE}{wrap_output_text(signal.get('reasoning', ''))}{Style.RESET_ALL}",
            ]
        )
    return table_data


def build_decision_table_rows(decision: dict) -> list[list[str]]:
    action = decision.get("action", "").upper()
    action_color = {"BUY": Fore.GREEN, "SELL": Fore.RED, "HOLD": Fore.YELLOW, "COVER": Fore.GREEN, "SHORT": Fore.RED}.get(action, Fore.WHITE)
    return [
        ["Action", f"{action_color}{action}{Style.RESET_ALL}"],
        ["Quantity", f"{action_color}{decision.get('quantity')}{Style.RESET_ALL}"],
        ["Confidence", f"{Fore.WHITE}{decision.get('confidence'):.1f}%{Style.RESET_ALL}"],
        ["Reasoning", f"{Fore.WHITE}{wrap_output_text(decision.get('reasoning', ''))}{Style.RESET_ALL}"],
    ]


def find_portfolio_manager_reasoning(decisions: dict) -> object | None:
    for decision in decisions.values():
        if decision.get("reasoning"):
            return decision.get("reasoning")
    return None


def build_portfolio_summary_rows(decisions: dict, analyst_signals: dict) -> list[list[str]]:
    portfolio_data: list[list[str]] = []
    for ticker, decision in decisions.items():
        action = decision.get("action", "").upper()
        action_color = {"BUY": Fore.GREEN, "SELL": Fore.RED, "HOLD": Fore.YELLOW, "COVER": Fore.GREEN, "SHORT": Fore.RED}.get(action, Fore.WHITE)
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        for signals in analyst_signals.values():
            if ticker not in signals:
                continue
            signal = signals[ticker].get("signal", "").upper()
            if signal == "BULLISH":
                bullish_count += 1
            elif signal == "BEARISH":
                bearish_count += 1
            elif signal == "NEUTRAL":
                neutral_count += 1

        portfolio_data.append(
            [
                f"{Fore.CYAN}{ticker}{Style.RESET_ALL}",
                f"{action_color}{action}{Style.RESET_ALL}",
                f"{action_color}{decision.get('quantity')}{Style.RESET_ALL}",
                f"{Fore.WHITE}{decision.get('confidence'):.1f}%{Style.RESET_ALL}",
                f"{Fore.GREEN}{bullish_count}{Style.RESET_ALL}",
                f"{Fore.RED}{bearish_count}{Style.RESET_ALL}",
                f"{Fore.YELLOW}{neutral_count}{Style.RESET_ALL}",
            ]
        )
    return portfolio_data
