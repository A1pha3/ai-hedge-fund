"""Utilities for working with Ollama models"""

import os
import platform
import subprocess
import time

import questionary
import requests
from colorama import Fore, Style

from . import docker
from .ollama_download_helpers import stream_download_progress
from .logging import get_logger

logger = get_logger(__name__)

# Constants
DEFAULT_OLLAMA_SERVER_URL = "http://localhost:11434"


def _get_ollama_base_url() -> str:
    """Return the configured Ollama base URL, trimming any trailing slash."""
    url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_SERVER_URL)
    if not url:
        url = DEFAULT_OLLAMA_SERVER_URL
    return url.rstrip("/")


def _get_ollama_endpoint(path: str) -> str:
    """Build a full Ollama API endpoint from the configured base URL."""
    base = _get_ollama_base_url()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


OLLAMA_DOWNLOAD_URL = {"darwin": "https://ollama.com/download/darwin", "windows": "https://ollama.com/download/windows", "linux": "https://ollama.com/download/linux"}  # macOS  # Windows  # Linux
INSTALLATION_INSTRUCTIONS = {"darwin": "curl -fsSL https://ollama.com/install.sh | sh", "windows": "# Download from https://ollama.com/download/windows and run the installer", "linux": "curl -fsSL https://ollama.com/install.sh | sh"}


def is_ollama_installed() -> bool:
    """Check if Ollama is installed on the system."""
    system = platform.system().lower()

    if system == "darwin" or system == "linux":  # macOS or Linux
        try:
            result = subprocess.run(["which", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return result.returncode == 0
        except Exception:
            return False
    elif system == "windows":  # Windows
        try:
            result = subprocess.run(["where", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
            return result.returncode == 0
        except Exception:
            return False
    else:
        return False  # Unsupported OS


def is_ollama_server_running() -> bool:
    """Check if the Ollama server is running."""
    endpoint = _get_ollama_endpoint("/api/tags")
    try:
        response = requests.get(endpoint, timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False


def get_locally_available_models() -> list[str]:
    """Get a list of models that are already downloaded locally."""
    if not is_ollama_server_running():
        return []

    try:
        endpoint = _get_ollama_endpoint("/api/tags")
        response = requests.get(endpoint, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [model["name"] for model in data["models"]] if "models" in data else []
        return []
    except requests.RequestException:
        return []


def start_ollama_server() -> bool:
    """Start the Ollama server if it's not already running."""
    if is_ollama_server_running():
        logger.info("Ollama server is already running.")
        print(f"{Fore.GREEN}Ollama server is already running.{Style.RESET_ALL}")
        return True

    system = platform.system().lower()

    try:
        if system == "darwin" or system == "linux":  # macOS or Linux
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        elif system == "windows":  # Windows
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        else:
            logger.error(f"Unsupported operating system: {system}")
            print(f"{Fore.RED}Unsupported operating system: {system}{Style.RESET_ALL}")
            return False

        # Wait for server to start
        for _ in range(10):  # Try for 10 seconds
            if is_ollama_server_running():
                logger.info("Ollama server started successfully.")
                print(f"{Fore.GREEN}Ollama server started successfully.{Style.RESET_ALL}")
                return True
            time.sleep(1)

        logger.error("Failed to start Ollama server. Timed out waiting for server to become available.")
        print(f"{Fore.RED}Failed to start Ollama server. Timed out waiting for server to become available.{Style.RESET_ALL}")
        return False
    except Exception as e:
        logger.error(f"Error starting Ollama server: {e}")
        print(f"{Fore.RED}Error starting Ollama server: {e}{Style.RESET_ALL}")
        return False


def _open_download_page(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def _confirm_installation_ready(prompt: str) -> bool:
    return questionary.confirm(prompt, default=False).ask()


def _verify_installed_and_running(restart_message: str) -> bool:
    if is_ollama_installed() and start_ollama_server():
        print(f"{Fore.GREEN}Ollama is now properly installed and running!{Style.RESET_ALL}")
        return True
    print(f"{Fore.RED}{restart_message}{Style.RESET_ALL}")
    return False


def _run_install_script(success_message: str, failure_message: str) -> bool:
    try:
        install_process = subprocess.run(["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if install_process.returncode == 0:
            print(f"{Fore.GREEN}{success_message}{Style.RESET_ALL}")
            return True
        print(f"{Fore.RED}{failure_message.format(stderr=install_process.stderr)}{Style.RESET_ALL}")
        return False
    except Exception as e:
        print(f"{Fore.RED}Error during Ollama installation: {e}{Style.RESET_ALL}")
        return False


def _install_ollama_darwin() -> bool:
    print(f"{Fore.YELLOW}Ollama for Mac is available as an application download.{Style.RESET_ALL}")

    if questionary.confirm("Would you like to download the Ollama application?", default=True).ask():
        try:
            _open_download_page(OLLAMA_DOWNLOAD_URL["darwin"])
            print(f"{Fore.YELLOW}Please download and install the application, then restart this program.{Style.RESET_ALL}")
            print(f"{Fore.CYAN}After installation, you may need to open the Ollama app once before continuing.{Style.RESET_ALL}")
            if _confirm_installation_ready("Have you installed the Ollama app and opened it at least once?"):
                return _verify_installed_and_running("Ollama installation not detected. Please restart this application after installing Ollama.")
            return False
        except Exception as e:
            print(f"{Fore.RED}Failed to open browser: {e}{Style.RESET_ALL}")
            return False

    if questionary.confirm("Would you like to try the command-line installation instead? (For advanced users)", default=False).ask():
        print(f"{Fore.YELLOW}Attempting command-line installation...{Style.RESET_ALL}")
        return _run_install_script("Ollama installed successfully via command line.", "Command-line installation failed. Please use the app download method instead.")
    return False


def _install_ollama_linux() -> bool:
    print(f"{Fore.YELLOW}Installing Ollama...{Style.RESET_ALL}")
    return _run_install_script("Ollama installed successfully.", "Failed to install Ollama. Error: {stderr}")


def _install_ollama_windows() -> bool:
    print(f"{Fore.YELLOW}Automatic installation on Windows is not supported.{Style.RESET_ALL}")
    print(f"Please download and install Ollama from: {OLLAMA_DOWNLOAD_URL['windows']}")

    if questionary.confirm("Do you want to open the Ollama download page in your browser?").ask():
        try:
            _open_download_page(OLLAMA_DOWNLOAD_URL["windows"])
            print(f"{Fore.YELLOW}After installation, please restart this application.{Style.RESET_ALL}")
            if _confirm_installation_ready("Have you installed Ollama?"):
                return _verify_installed_and_running("Ollama installation not detected. Please restart this application after installing Ollama.")
        except Exception as e:
            print(f"{Fore.RED}Failed to open browser: {e}{Style.RESET_ALL}")
    return False


def install_ollama() -> bool:
    """Install Ollama on the system."""
    system = platform.system().lower()
    if system not in OLLAMA_DOWNLOAD_URL:
        print(f"{Fore.RED}Unsupported operating system for automatic installation: {system}{Style.RESET_ALL}")
        print(f"Please visit https://ollama.com/download to install Ollama manually.")
        return False

    if system == "darwin":
        return _install_ollama_darwin()
    if system == "linux":
        return _install_ollama_linux()
    if system == "windows":
        return _install_ollama_windows()
    return False


def download_model(model_name: str) -> bool:
    """Download an Ollama model."""
    if not is_ollama_server_running() and not start_ollama_server():
        return False

    print(f"{Fore.YELLOW}Downloading model {model_name}...{Style.RESET_ALL}")
    print(f"{Fore.CYAN}This may take a while depending on your internet speed and the model size.{Style.RESET_ALL}")
    print(f"{Fore.CYAN}The download is happening in the background. Please be patient...{Style.RESET_ALL}")

    try:
        process = subprocess.Popen(["ollama", "pull", model_name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding="utf-8", errors="replace")  # Redirect stderr to stdout to capture all output  # Line buffered  # Explicitly use UTF-8 encoding  # Replace any characters that cannot be decoded

        print(f"{Fore.CYAN}Download progress:{Style.RESET_ALL}")
        if process.stdout is not None:
            stream_download_progress(process.stdout)

        return_code = process.wait()
        print()

        if return_code == 0:
            print(f"{Fore.GREEN}Model {model_name} downloaded successfully!{Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.RED}Failed to download model {model_name}. Check your internet connection and try again.{Style.RESET_ALL}")
            return False
    except Exception as e:
        print(f"\n{Fore.RED}Error downloading model {model_name}: {e}{Style.RESET_ALL}")
        return False


def _should_use_remote_ollama_workflow(ollama_url: str) -> bool:
    env_override = os.environ.get("OLLAMA_BASE_URL")
    return bool(env_override or ollama_url.startswith("http://ollama:") or ollama_url.startswith("http://host.docker.internal:"))


def _ensure_local_ollama_installed() -> bool:
    if is_ollama_installed():
        return True

    print(f"{Fore.YELLOW}Ollama is not installed on your system.{Style.RESET_ALL}")
    if questionary.confirm("Do you want to install Ollama?").ask():
        return install_ollama()

    print(f"{Fore.RED}Ollama is required to use local models.{Style.RESET_ALL}")
    return False


def _ensure_local_ollama_server() -> bool:
    if is_ollama_server_running():
        return True
    print(f"{Fore.YELLOW}Starting Ollama server...{Style.RESET_ALL}")
    return start_ollama_server()


def _build_model_download_prompt(model_name: str) -> str:
    model_size_info = ""
    if "70b" in model_name:
        model_size_info = " This is a large model (up to several GB) and may take a while to download."
    elif "34b" in model_name or "8x7b" in model_name:
        model_size_info = " This is a medium-sized model (1-2 GB) and may take a few minutes to download."
    return f"Do you want to download the {model_name} model?{model_size_info} The download will happen in the background."


def _ensure_local_model_available(model_name: str) -> bool:
    available_models = get_locally_available_models()
    if model_name in available_models:
        return True

    print(f"{Fore.YELLOW}Model {model_name} is not available locally.{Style.RESET_ALL}")
    if questionary.confirm(_build_model_download_prompt(model_name)).ask():
        return download_model(model_name)

    print(f"{Fore.RED}The model is required to proceed.{Style.RESET_ALL}")
    return False


def ensure_ollama_and_model(model_name: str) -> bool:
    """Ensure Ollama is installed, running, and the requested model is available."""
    ollama_url = _get_ollama_base_url()

    if _should_use_remote_ollama_workflow(ollama_url):
        return docker.ensure_ollama_and_model(model_name, ollama_url)

    if not _ensure_local_ollama_installed():
        return False
    if not _ensure_local_ollama_server():
        return False
    return _ensure_local_model_available(model_name)


def delete_model(model_name: str) -> bool:
    """Delete a locally downloaded Ollama model."""
    # Check if we're running in Docker
    in_docker = os.environ.get("OLLAMA_BASE_URL", "").startswith("http://ollama:") or os.environ.get("OLLAMA_BASE_URL", "").startswith("http://host.docker.internal:")

    # In Docker environment, delegate to docker module
    if in_docker:
        ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
        return docker.delete_model(model_name, ollama_url)

    # Non-Docker environment
    if not is_ollama_server_running() and not start_ollama_server():
        return False

    print(f"{Fore.YELLOW}Deleting model {model_name}...{Style.RESET_ALL}")

    try:
        # Use the Ollama CLI to delete the model
        process = subprocess.run(["ollama", "rm", model_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if process.returncode == 0:
            print(f"{Fore.GREEN}Model {model_name} deleted successfully.{Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.RED}Failed to delete model {model_name}. Error: {process.stderr}{Style.RESET_ALL}")
            return False
    except Exception as e:
        print(f"{Fore.RED}Error deleting model {model_name}: {e}{Style.RESET_ALL}")
        return False


# Add this at the end of the file for command-line usage
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Ollama model manager")
    parser.add_argument("--check-model", help="Check if model exists and download if needed")
    args = parser.parse_args()

    if args.check_model:
        print(f"Ensuring Ollama is installed and model {args.check_model} is available...")
        result = ensure_ollama_and_model(args.check_model)
        sys.exit(0 if result else 1)
    else:
        print("No action specified. Use --check-model to check if a model exists.")
        sys.exit(1)
