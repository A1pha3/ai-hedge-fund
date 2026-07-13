from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_socket_denied(
    code: str, tmp_path: Path
) -> tuple[subprocess.CompletedProcess[str], Path]:
    attempt_log = tmp_path / "socket-attempts.jsonl"
    instrumented = f"""
import json
import socket
from pathlib import Path

attempts = []

def deny(name):
    def blocked(*args, **kwargs):
        attempt = {{"primitive": name, "address": repr(args[-1] if args else kwargs)}}
        attempts.append(attempt)
        Path({str(attempt_log)!r}).open("a", encoding="utf-8").write(json.dumps(attempt) + "\\n")
        raise AssertionError("socket attempt: " + repr(attempt))
    return blocked

socket.socket.connect = deny("socket.connect")
socket.socket.connect_ex = deny("socket.connect_ex")
socket.create_connection = deny("socket.create_connection")

{code}
print(json.dumps({{"attempts": attempts, "candidate_pool_loaded": "src.screening.candidate_pool" in sys.modules, "enhanced_cache_loaded": "src.data.enhanced_cache" in sys.modules}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", instrumented],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )
    return completed, attempt_log


def test_exit_shadow_submodule_import_attempts_no_socket_connection(
    tmp_path: Path,
) -> None:
    completed, attempt_log = _run_socket_denied(
        "import sys\nimport src.research.exit_shadow_research", tmp_path
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {
        "attempts": [],
        "candidate_pool_loaded": False,
        "enhanced_cache_loaded": False,
    }
    assert not attempt_log.exists()


def test_package_lazy_public_exports_and_submodule_imports_remain_compatible() -> None:
    code = """
import socket

def block_real_network(*args, **kwargs):
    raise OSError("network disabled for compatibility-only import test")

socket.socket.connect = block_real_network
socket.socket.connect_ex = block_real_network
socket.create_connection = block_real_network

from src.research import DigestResult, build_selection_snapshot, exit_shadow_research
from src.research.artifacts import build_selection_snapshot as direct_snapshot
from src.research.digest import DigestResult as direct_digest
from src.screening import build_candidate_pool, detect_market_state, market_state
from src.screening.candidate_pool import build_candidate_pool as direct_pool
from src.screening.market_state import detect_market_state as direct_market_state

assert DigestResult is direct_digest
assert build_selection_snapshot is direct_snapshot
assert build_candidate_pool is direct_pool
assert detect_market_state is direct_market_state
assert exit_shadow_research.__name__ == "src.research.exit_shadow_research"
assert market_state.__name__ == "src.screening.market_state"
print("compatible")
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "compatible"
