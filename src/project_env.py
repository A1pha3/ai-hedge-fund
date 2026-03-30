from __future__ import annotations

from pathlib import Path

try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:
    _load_dotenv = None


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_DOTENV_PATH = _PROJECT_ROOT / ".env"


def load_project_dotenv(*, override: bool = True) -> bool:
    if _load_dotenv is None:
        return False
    return bool(_load_dotenv(_PROJECT_DOTENV_PATH, override=override))