import re
from typing import TextIO

from colorama import Fore, Style


def extract_download_progress(output: str) -> tuple[float | None, str | None]:
    percentage = None
    current_phase = None

    percentage_match = re.search(r"(\d+(\.\d+)?)%", output)
    if percentage_match:
        try:
            percentage = float(percentage_match.group(1))
        except ValueError:
            percentage = None

    phase_match = re.search(r"^([a-zA-Z\s]+):", output)
    if phase_match:
        current_phase = phase_match.group(1).strip()

    return percentage, current_phase


def render_download_progress(output: str, last_percentage: float, last_phase: str, bar_length: int = 40) -> tuple[str | None, float, str]:
    percentage, current_phase = extract_download_progress(output)
    if percentage is not None:
        if abs(percentage - last_percentage) >= 1 or (current_phase and current_phase != last_phase):
            next_phase = current_phase or last_phase
            filled_length = int(bar_length * percentage / 100)
            bar = "█" * filled_length + "░" * (bar_length - filled_length)
            phase_display = f"{Fore.CYAN}{next_phase.capitalize()}{Style.RESET_ALL}: " if next_phase else ""
            status_line = f"\r{phase_display}{Fore.GREEN}{bar}{Style.RESET_ALL} {Fore.YELLOW}{percentage:.1f}%{Style.RESET_ALL}"
            return status_line, percentage, next_phase
        return None, last_percentage, last_phase

    lowered_output = output.lower()
    if "download" in lowered_output or "extract" in lowered_output or "pulling" in lowered_output:
        if "%" in output:
            return f"\r{Fore.GREEN}{output}{Style.RESET_ALL}", last_percentage, last_phase
        return f"{Fore.GREEN}{output}{Style.RESET_ALL}", last_percentage, last_phase
    return None, last_percentage, last_phase


def stream_download_progress(stdout: TextIO) -> None:
    last_percentage = 0.0
    last_phase = ""
    while True:
        output = stdout.readline()
        if output == "":
            break
        rendered_output, last_percentage, last_phase = render_download_progress(output.strip(), last_percentage, last_phase)
        if rendered_output is None:
            continue
        if rendered_output.startswith("\r"):
            print(rendered_output, end="", flush=True)
        else:
            print(rendered_output)
