"""decide/advance/finalize CLI 对 store 级类型化异常的透传契约 (R108b Op2).

R108 Op1 宿主真实首演取证 (生产 root 三次实演): ``EvidenceStoreError``
(trusted_clock_rollback) 与 ``TrialStoreError`` (arm_decision_conflict)
自三入口裸逃逸 —— rc=1 traceback、stdout 无 JSON, 夜间链 record 只能记
无类型 ``decide_failed``, 操作员无法机读分诊 (R103 形态的运维盲区)。

本契约: 两族 store 异常与 ``TrialSessionDriverError`` 同面 —— 权威
``code`` + ``details`` verbatim 透传 (不吞不重推导), rc=2。测试经
monkeypatch 在 CLI 接缝处注入真实异常类 (store 本体语义由 store 级测试
钉死, 此处只钉 CLI 边界), 全程零磁盘世界依赖。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts.v3_trial_session import main
from src.screening.offensive.v3.evidence.repository import EvidenceStoreError
from src.screening.offensive.v3.orchestration.trial_store import TrialStoreError


def _base_argv(tmp_path: Path, command: str) -> list[str]:
    argv = [
        command,
        "--identity-dir", str(tmp_path / "id"),
        "--trial-root", str(tmp_path / "root"),
        "--trial-id", "trial-x",
        "--calendar", str(tmp_path / "cal.json"),
        "--now", "2026-09-05T15:05:07+00:00",
        "--execute",
    ]
    if command == "decide":
        argv += [
            "--readiness-manifest", str(tmp_path / "m.json"),
            "--signal-session", "2026-09-05",
            "--data-dir", str(tmp_path / "data"),
        ]
    elif command == "advance":
        argv += [
            "--signal-session", "2026-09-05",
            "--through-session", "2026-09-05",
            "--bar-source", str(tmp_path / "bars"),
        ]
    return argv


def _run(argv: list[str], capsys, monkeypatch) -> tuple[int, dict]:
    if argv[0] == "finalize":
        argv[0] = "finalize-missed"
    rc = main(argv)
    payload = json.loads(capsys.readouterr().out)
    return rc, payload


@pytest.fixture()
def _seamless(monkeypatch):
    """把三入口的文件系统前置全部 stub 掉, 直达 driver/runner 调用点."""
    import scripts.v3_trial_session as cli

    monkeypatch.setattr(cli, "_dry_run_checks", lambda **kwargs: None)
    monkeypatch.setattr(
        cli, "_decide_preflight", lambda **kwargs: None
    )
    snapshot = type("S", (), {"signal_date": date(2026, 9, 5)})()
    monkeypatch.setattr(cli, "_load_snapshot", lambda *a, **k: snapshot)
    monkeypatch.setattr(cli, "_build_stack", lambda **kwargs: object())
    monkeypatch.setattr(
        cli, "_advance_window_sessions", lambda **kwargs: []
    )


class TestDecideStoreErrorPassthrough:
    def test_evidence_store_error_typed_rc2(
        self, tmp_path, capsys, monkeypatch, _seamless
    ) -> None:
        """R108 实演 #1 的真实形态: regime 发布撞 trusted_clock_rollback."""
        from src.screening.offensive.v3.evidence import governance_identity
        from src.screening.offensive.v3.orchestration import (
            trial_session_driver,
        )

        class _Driver:
            def __init__(self, **kwargs) -> None:
                pass

            def ensure_trial_registration(self) -> None:
                return None

            def decide_session(self, **kwargs):
                raise EvidenceStoreError(
                    "trusted_clock_rollback",
                    "store timestamp precedes an already observed trusted time",
                    high_water="2026-09-04T15:05:06+00:00",
                    requested="2026-09-04T15:05:00+00:00",
                )

        monkeypatch.setattr(
            governance_identity, "load_governance_identity", lambda *a, **k: object()
        )
        monkeypatch.setattr(
            trial_session_driver, "OfficialTrialSessionDriver", _Driver
        )

        rc, payload = _run(_base_argv(tmp_path, "decide"), capsys, monkeypatch)

        assert rc == 2
        assert payload["ok"] is False
        assert payload["code"] == "trusted_clock_rollback"
        assert payload["details"]["high_water"] == "2026-09-04T15:05:06+00:00"

    def test_trial_store_error_typed_rc2(
        self, tmp_path, capsys, monkeypatch, _seamless
    ) -> None:
        """R108 实演 #2/#3 的真实形态: 重放撞 arm_decision_conflict."""
        from src.screening.offensive.v3.evidence import governance_identity
        from src.screening.offensive.v3.orchestration import (
            trial_session_driver,
        )

        class _Driver:
            def __init__(self, **kwargs) -> None:
                pass

            def ensure_trial_registration(self) -> None:
                return None

            def decide_session(self, **kwargs):
                raise TrialStoreError(
                    "arm_decision_conflict",
                    "same decision key already committed with different content",
                    key=("trial-x", "2026-09-05", "daily-action-20260905"),
                )

        monkeypatch.setattr(
            governance_identity, "load_governance_identity", lambda *a, **k: object()
        )
        monkeypatch.setattr(
            trial_session_driver, "OfficialTrialSessionDriver", _Driver
        )

        rc, payload = _run(_base_argv(tmp_path, "decide"), capsys, monkeypatch)

        assert rc == 2
        assert payload["code"] == "arm_decision_conflict"
        assert payload["details"]["key"][0] == "trial-x"


class TestAdvanceStoreErrorPassthrough:
    def test_trial_store_error_typed_rc2(
        self, tmp_path, capsys, monkeypatch, _seamless
    ) -> None:
        (tmp_path / "bars").mkdir()
        from src.screening.offensive.v3.evidence import governance_identity
        from src.screening.offensive.v3.orchestration import (
            trial_session_driver,
        )

        class _Driver:
            def __init__(self, **kwargs) -> None:
                pass

            def advance_sessions(self, **kwargs):
                raise TrialStoreError(
                    "pair_key_state_conflict",
                    "advance found a divergent pair state",
                    signal_session="2026-09-05",
                )

        monkeypatch.setattr(
            governance_identity, "load_governance_identity", lambda *a, **k: object()
        )
        monkeypatch.setattr(
            trial_session_driver, "OfficialTrialSessionDriver", _Driver
        )

        rc, payload = _run(_base_argv(tmp_path, "advance"), capsys, monkeypatch)

        assert rc == 2
        assert payload["code"] == "pair_key_state_conflict"
        assert payload["details"]["signal_session"] == "2026-09-05"


class TestFinalizeStoreErrorPassthrough:
    def test_evidence_store_error_typed_rc2(
        self, tmp_path, capsys, monkeypatch, _seamless
    ) -> None:
        class _Runner:
            def finalize_missed_sessions(self, now):
                raise EvidenceStoreError(
                    "spine_registration_missing",
                    "no expected-session spine for program",
                    research_program="research.btst.regime",
                )

        monkeypatch.setattr(
            "scripts.v3_trial_session._build_stack",
            lambda **kwargs: type("Stack", (), {"runner": _Runner()})(),
        )

        rc, payload = _run(_base_argv(tmp_path, "finalize"), capsys, monkeypatch)

        assert rc == 2
        assert payload["code"] == "spine_registration_missing"
        assert payload["details"]["research_program"] == "research.btst.regime"
