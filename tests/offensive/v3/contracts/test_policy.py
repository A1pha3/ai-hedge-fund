"""Contract and adversarial loader tests for frozen v3 policy snapshots."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
INITIAL_POLICY_PATH = REPOSITORY_ROOT / "config/policies/v3/policy-v1.json"


def _policy_api() -> Any:
    try:
        from src.screening.offensive.v3 import policy
    except ImportError as exc:
        pytest.fail(f"v3 policy contract is not implemented: {exc}")
    return policy


def _initial_policy() -> Any:
    return _policy_api().load_policy_snapshot(INITIAL_POLICY_PATH)


def _raw_initial_policy() -> dict[str, Any]:
    return json.loads(INITIAL_POLICY_PATH.read_text(encoding="utf-8"))


def _write_policy(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("drawdown", "expected"),
    [
        (Decimal("0"), Decimal("1")),
        (Decimal("0.0999"), Decimal("1")),
        (Decimal("0.10"), Decimal("1")),
        (Decimal("0.125"), Decimal("0.5")),
        (Decimal("0.1499"), Decimal("0.002")),
        (Decimal("0.15"), Decimal("0")),
        (Decimal("0.25"), Decimal("0")),
    ],
)
def test_drawdown_multiplier_boundaries(drawdown: Decimal, expected: Decimal) -> None:
    policy = _policy_api()

    assert policy.PolicySnapshot.drawdown_multiplier(drawdown) == expected


def test_drawdown_multiplier_rejects_invalid_truth() -> None:
    policy = _policy_api()

    for value in (Decimal("-0.0001"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValueError, match="drawdown"):
            policy.PolicySnapshot.drawdown_multiplier(value)
    with pytest.raises(TypeError, match="Decimal"):
        policy.PolicySnapshot.drawdown_multiplier(0.10)


def test_initial_policy_is_off_and_contains_governed_risk_contract() -> None:
    policy = _initial_policy()

    assert policy.runtime_mode.value == "off"
    assert tuple(tier.value for tier in policy.capital.governed_tiers) == (2, 5, 10)
    assert policy.capital.exploration_aggregate_gross_cap == Decimal("0")
    assert policy.capital.portfolio_gross_cap == Decimal("0")
    assert policy.capital.single_name_gross_cap == Decimal("0")
    assert policy.capital.industry_gross_cap == Decimal("0")
    assert policy.capital.daily_entry_gross_cap == Decimal("0")
    assert policy.capital.stage_loss_budget_cap == Decimal("0")
    assert policy.risk.drawdown_scale_start == Decimal("0.10")
    assert policy.risk.drawdown_halt == Decimal("0.15")


def test_initial_policy_disables_all_producer_and_sizing_switches() -> None:
    policy = _initial_policy()

    assert policy.producers.btst_enabled is False
    assert policy.producers.oversold_bounce_enabled is False
    assert policy.producers.regime_sizing_enabled is False
    assert policy.producers.streak_sizing_enabled is False
    assert policy.producers.trigger_strength_sizing_enabled is False
    assert policy.producers.composite_sizing_enabled is False


def test_runtime_modes_are_typed_but_initial_policy_enables_none() -> None:
    policy_api = _policy_api()

    assert [mode.value for mode in policy_api.RuntimeMode] == [
        "off",
        "shadow",
        "btst_canary",
        "authoritative",
    ]
    assert _initial_policy().runtime_mode is policy_api.RuntimeMode.OFF


def test_initial_policy_binds_adv_execution_and_governance_versions() -> None:
    policy = _initial_policy()

    assert policy.adv.lookback_sessions == 20
    assert policy.adv.max_participation_rate == Decimal("0.05")
    assert policy.adv.missing_data_behavior.value == "fail_closed"
    assert policy.execution.entry_session_ordinal == 1
    assert policy.execution.exit_session_ordinal == 10
    assert policy.execution.order_type == "opening_auction_limit"
    assert policy.execution.seal_deadline_after_t0_close_minutes == 240
    assert policy.execution.permit_deadline_before_auction_minutes == 20
    assert policy.execution.gateway_send_deadline_before_auction_minutes == 10
    assert policy.execution.broker_auction_submission_cutoff_cn == "09:20:00"
    assert policy.versions.cost_version == "cn-a-share-costs.v1"
    assert policy.versions.board_rule_version == "ashare-board-prefix-v1"
    assert policy.versions.calendar_version == "sse-szse-official-sessions.v1"
    assert policy.versions.lot_rule_version == "cn-board-lot.v1"
    assert policy.versions.setup_version == "daily-action-setups-v1"
    assert policy.versions.execution_contract_version == "t0-close-t1-open-t10-open.v1"
    assert policy.versions.governance_version == "growth-kernel-governance.v1"


def test_initial_policy_payload_has_no_self_referential_fingerprint() -> None:
    raw = _raw_initial_policy()

    assert "policy_fingerprint" not in raw
    assert "behavior_fingerprint" not in raw
    assert _initial_policy().policy_fingerprint == hashlib.sha256(_initial_policy().canonical_bytes()).hexdigest()


def test_policy_fingerprint_covers_the_complete_payload() -> None:
    original = _initial_policy()
    changed = original.model_copy(update={"versions": original.versions.model_copy(update={"governance_version": "growth-kernel-governance.v2"})})

    assert original.policy_fingerprint != changed.policy_fingerprint


def test_behavior_fingerprint_is_typed_deterministic_and_policy_bound() -> None:
    policy_api = _policy_api()
    policy = _initial_policy()
    producer = policy_api.ProducerIdentity(
        producer_namespace="daily_action.btst",
        strategy_semver="3.0.0",
    )

    first = policy_api.behavior_fingerprint(producer, policy)
    second = policy_api.behavior_fingerprint(producer, policy)
    changed_producer = producer.model_copy(update={"strategy_semver": "3.0.1"})
    changed_policy = policy.model_copy(update={"versions": policy.versions.model_copy(update={"setup_version": "daily-action-setups-v2"})})

    assert first == second
    assert len(first) == 64
    assert first != policy_api.behavior_fingerprint(changed_producer, policy)
    assert first != policy_api.behavior_fingerprint(producer, changed_policy)
    with pytest.raises(TypeError, match="ProducerIdentity"):
        policy_api.behavior_fingerprint(  # type: ignore[arg-type]
            {"producer_namespace": "daily_action.btst", "strategy_semver": "3.0.0"},
            policy,
        )


def test_behavior_fingerprint_excludes_provenance_only_policy_labels() -> None:
    policy_api = _policy_api()
    policy = _initial_policy()
    producer = policy_api.ProducerIdentity(
        producer_namespace="daily_action.btst",
        strategy_semver="3.0.0",
    )
    provenance_revision = policy.model_copy(
        update={
            "policy_id": "growth-kernel-v3-republished",
            "policy_version": "policy-v2",
        }
    )

    assert policy.policy_fingerprint != provenance_revision.policy_fingerprint
    assert policy_api.behavior_fingerprint(producer, policy) == policy_api.behavior_fingerprint(producer, provenance_revision)


@pytest.mark.parametrize("epoch_field", ["policy_epoch", "authority_epoch", "risk_epoch"])
def test_behavior_fingerprint_includes_governed_epochs(epoch_field: str) -> None:
    policy_api = _policy_api()
    policy = _initial_policy()
    producer = policy_api.ProducerIdentity(
        producer_namespace="daily_action.btst",
        strategy_semver="3.0.0",
    )
    next_epoch = policy.model_copy(update={epoch_field: 2})

    assert policy_api.behavior_fingerprint(producer, policy) != policy_api.behavior_fingerprint(producer, next_epoch)


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("schema_major",), 2),
        (("policy_version",), ""),
        (("versions", "cost_version"), "  "),
        (("versions", "calendar_version"), "not a version"),
    ],
)
def test_loader_rejects_unknown_major_and_invalid_versions(tmp_path: Path, field_path: tuple[str, ...], value: Any) -> None:
    policy_api = _policy_api()
    raw = _raw_initial_policy()
    target: dict[str, Any] = raw
    for part in field_path[:-1]:
        target = target[part]
    target[field_path[-1]] = value
    path = tmp_path / "policy.json"
    _write_policy(path, raw)

    with pytest.raises(policy_api.PolicyLoadError):
        policy_api.load_policy_snapshot(path)


def test_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    policy_api = _policy_api()
    raw = INITIAL_POLICY_PATH.read_text(encoding="utf-8")
    duplicate = raw.replace('"schema_major":1', '"schema_major":1,"schema_major":1', 1)
    path = tmp_path / "policy.json"
    path.write_text(duplicate, encoding="utf-8")

    with pytest.raises(policy_api.PolicyLoadError, match="duplicate"):
        policy_api.load_policy_snapshot(path)


def test_loader_rejects_unknown_and_missing_governance_fields(tmp_path: Path) -> None:
    policy_api = _policy_api()
    extra = _raw_initial_policy()
    extra["environment_override"] = True
    extra_path = tmp_path / "extra.json"
    _write_policy(extra_path, extra)

    missing = _raw_initial_policy()
    del missing["versions"]["governance_version"]
    missing_path = tmp_path / "missing.json"
    _write_policy(missing_path, missing)

    with pytest.raises(policy_api.PolicyLoadError, match="extra_forbidden"):
        policy_api.load_policy_snapshot(extra_path)
    with pytest.raises(policy_api.PolicyLoadError, match="governance_version"):
        policy_api.load_policy_snapshot(missing_path)


def test_loader_rejects_symlink_and_non_regular_file(tmp_path: Path) -> None:
    policy_api = _policy_api()
    real = tmp_path / "real.json"
    _write_policy(real, _raw_initial_policy())
    link = tmp_path / "policy-link.json"
    link.symlink_to(real)

    with pytest.raises(policy_api.PolicyLoadError, match="regular|symlink"):
        policy_api.load_policy_snapshot(link)
    with pytest.raises(policy_api.PolicyLoadError, match="regular"):
        policy_api.load_policy_snapshot(tmp_path)

    real_directory = tmp_path / "real-directory"
    real_directory.mkdir()
    nested_policy = real_directory / "policy.json"
    _write_policy(nested_policy, _raw_initial_policy())
    linked_directory = tmp_path / "linked-directory"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    with pytest.raises(policy_api.PolicyLoadError, match="regular|symlink"):
        policy_api.load_policy_snapshot(linked_directory / "policy.json")


def test_loader_rejects_file_mutation_during_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.screening.offensive.v3.policy import loader

    policy_path = tmp_path / "policy.json"
    original = INITIAL_POLICY_PATH.read_bytes()
    policy_path.write_bytes(original)
    real_read = loader.os.read
    mutated = False

    def mutate_after_first_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = real_read(descriptor, size)
        if chunk and not mutated:
            mutated = True
            policy_path.write_bytes(original)
        return chunk

    monkeypatch.setattr(loader.os, "read", mutate_after_first_read)

    with pytest.raises(loader.PolicyLoadError, match="changed"):
        loader.load_policy_snapshot(policy_path)


def test_loader_rejects_oversized_policy_before_parsing(tmp_path: Path) -> None:
    policy_api = _policy_api()
    policy_path = tmp_path / "oversized-policy.json"
    policy_path.write_bytes((b" " * (1024 * 1024 + 1)) + INITIAL_POLICY_PATH.read_bytes())

    with pytest.raises(policy_api.PolicyLoadError, match="too large"):
        policy_api.load_policy_snapshot(policy_path)


@pytest.mark.parametrize(
    "missing_flag",
    ["O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK"],
)
def test_loader_fails_closed_when_required_descriptor_flag_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_flag: str,
) -> None:
    from src.screening.offensive.v3.policy import loader

    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(INITIAL_POLICY_PATH.read_bytes())
    monkeypatch.delattr(loader.os, missing_flag)

    with pytest.raises(loader.PolicyLoadError, match=missing_flag):
        loader.load_policy_snapshot(policy_path)


def test_loader_does_not_consult_permissive_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_api = _policy_api()
    path = tmp_path / "policy.json"
    _write_policy(path, _raw_initial_policy())
    expected = policy_api.load_policy_snapshot(path)
    permissive = {
        "V3_RUNTIME_MODE": "authoritative",
        "V3_PORTFOLIO_GROSS_CAP": "1",
        "V3_ADV_MISSING_FAIL_OPEN": "true",
        "DAILY_ACTION_DISABLED_SETUPS": "none",
        "DAILY_ACTION_REGIME_SIZING": "true",
        "DAILY_ACTION_STREAK_SIZING": "true",
    }
    for name, value in permissive.items():
        monkeypatch.setenv(name, value)

    loaded = policy_api.load_policy_snapshot(path)

    assert loaded == expected
    assert loaded.policy_fingerprint == expected.policy_fingerprint
    assert loaded.runtime_mode.value == "off"
    assert loaded.capital.portfolio_gross_cap == Decimal("0")
    assert loaded.producers.oversold_bounce_enabled is False


def test_off_policy_cannot_hide_nonzero_executable_risk(tmp_path: Path) -> None:
    policy_api = _policy_api()
    raw = _raw_initial_policy()
    raw["capital"]["portfolio_gross_cap"] = 0.02
    path = tmp_path / "policy.json"
    _write_policy(path, raw)

    with pytest.raises(policy_api.PolicyLoadError, match="off.*zero|zero.*off"):
        policy_api.load_policy_snapshot(path)


def test_policy_model_forbids_mutation_and_extra_fields() -> None:
    policy_api = _policy_api()
    policy = _initial_policy()

    with pytest.raises(ValidationError, match="frozen_instance"):
        policy.runtime_mode = policy_api.RuntimeMode.AUTHORITATIVE
    with pytest.raises(ValidationError, match="extra_forbidden"):
        policy_api.ProducerIdentity.model_validate(
            {
                "producer_namespace": "daily_action.btst",
                "strategy_semver": "3.0.0",
                "environment": dict(os.environ),
            }
        )


def test_fingerprints_revalidate_copied_policy_models() -> None:
    policy_api = _policy_api()
    policy = _initial_policy()
    producer = policy_api.ProducerIdentity(
        producer_namespace="daily_action.btst",
        strategy_semver="3.0.0",
    )
    invalid_capital = policy.capital.model_copy(update={"portfolio_gross_cap": Decimal("1")})
    invalid_policy = policy.model_copy(update={"capital": invalid_capital})

    with pytest.raises(ValidationError, match="gross cap"):
        _ = invalid_policy.policy_fingerprint
    with pytest.raises(ValidationError, match="gross cap"):
        policy_api.behavior_fingerprint(producer, invalid_policy)
