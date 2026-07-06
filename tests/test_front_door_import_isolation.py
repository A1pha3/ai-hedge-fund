"""Front-door import-isolation regression guard (autodev-23 loop 128).

Locks in the autodev-22 import-isolation sweep (loops 119-124): front-door
screening modules must NOT trigger ``src.utils.display`` at module-import time.
``src.utils.display`` transitively loads ``akshare_api`` / ``tushare_api`` /
``pandas`` / ``pydantic``, so any module that imports it pays the full chain
cost on every CLI invocation. Front-door modules that only need ``Fore`` /
``Style`` must import from ``colorama`` directly.

The loop-127 regression (``_find_latest_report`` mock target broke because a
screening helper was moved to a function-local import) showed that the
import-isolation property is fragile under refactor — a future change could
silently re-introduce ``from src.utils.display import Fore, Style`` and the
green test suite would not catch it (colorama Fore/Style are functionally
identical whether imported via display.py or directly).

This guard runs each front-door module in a FRESH subprocess (so sys.modules
is clean) and asserts ``src.utils.display`` is NOT loaded as a side effect.
A failure here means an import-isolation regression was introduced.

Background:
- loop 118 (autodev-21): pdf_exporter ``find_latest_report`` / ``load_report``
  kidnapped by top-level ``from fpdf import FPDF``.
- loops 119-124 (autodev-22): systematic sweep — 26 screening modules switched
  to direct colorama import; data_quality_audit._find_latest_report
  function-local; main.py display imports deferred.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Front-door screening modules that MUST stay display.py-free at import time.
#: Adding a module here asserts its import does not transitively load
#: ``src.utils.display``. If a module genuinely needs a display.py function
#: (not just Fore/Style), it does not belong on this list — but then it also
#: should not be on the hot path for ``--top-picks`` / ``--top`` /
#: ``--custom-weights`` / ``--decision-flow``.
_FRONT_DOOR_MODULES: tuple[str, ...] = (
    "src.screening.top_picks",
    "src.screening.composite_score",
    "src.screening.investability",
    "src.screening.expected_return",
    "src.screening.confidence_calibration",
    "src.screening.decision_flow",
    "src.screening.data_quality_audit",
    "src.screening.grade_verdict_parity",
    "src.screening.drawdown_estimate",
    "src.screening.sector_strength",
    "src.screening.signal_momentum",
    "src.screening.signal_consistency",
    "src.screening.trend_resonance",
    "src.screening.volume_confirmation",
)


def _check_module_imports_clean(module: str) -> tuple[bool, str]:
    """Import ``module`` in a fresh subprocess; return (is_clean, detail).

    is_clean=True means ``src.utils.display`` was NOT loaded as a side effect.
    """
    snippet = "import sys; " f"import {module}; " "import json; " "print(json.dumps({" "'display_loaded': 'src.utils.display' in sys.modules, " "'display_helpers_loaded': any('utils.display' in m for m in sys.modules)," "}))"
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
        timeout=60,
    )
    if result.returncode != 0:
        return False, f"import failed (rc={result.returncode}):\nstderr: {result.stderr}"
    import json

    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return False, f"could not parse subprocess output: {result.stdout!r}"
    is_clean = not payload.get("display_loaded", False) and not payload.get("display_helpers_loaded", False)
    detail = f"display_loaded={payload.get('display_loaded')}, " f"display_helpers_loaded={payload.get('display_helpers_loaded')}"
    return is_clean, detail


@pytest.mark.parametrize("module", _FRONT_DOOR_MODULES)
def test_front_door_module_does_not_trigger_display_chain(module: str) -> None:
    """Each front-door screening module must import without loading display.py.

    A failure means a ``from src.utils.display import Fore, Style`` (or a
    transitive equivalent) was re-introduced into this module or one of its
    import dependencies. Fix by switching to ``from colorama import Fore, Style``
    or deferring the import into the function that actually needs a display.py
    function.
    """
    is_clean, detail = _check_module_imports_clean(module)
    assert is_clean, f"{module} triggered src.utils.display at import time ({detail}). " f"This re-introduces the transitive akshare_api/tushare_api/pandas chain " f"on every front-door CLI invocation. See autodev-22 loops 119-124 for " f"the canonical fix (direct colorama import or function-local lazy import)."
