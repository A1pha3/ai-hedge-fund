from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

import scripts.run_exit_shadow_research as exit_shadow_cli
from scripts.run_exit_shadow_research import main


@dataclass(frozen=True)
class LegacyFixturePaths:
    journal: Path
    price_cache: Path


@pytest.fixture(autouse=True)
def fixed_policy_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exit_shadow_cli, "_civil_today", lambda: date(2026, 7, 14))


def _business_dates(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


@pytest.fixture
def legacy_fixture_paths(tmp_path: Path) -> LegacyFixturePaths:
    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    dates = _business_dates(date(2025, 12, 1), 55)
    signal_indices = (25, 35)
    journal_rows: list[str] = []

    for ticker, signal_index in zip(("000001", "000002"), signal_indices):
        signal_date = dates[signal_index].strftime("%Y%m%d")
        prices = pd.DataFrame(
            {
                "date": [item.strftime("%Y-%m-%d") for item in dates],
                "open": [10.0] * len(dates),
                "high": [10.4] * len(dates),
                "low": [9.8] * len(dates),
                "close": [10.1] * len(dates),
                "volume": [1_000.0] * len(dates),
            }
        )
        prices.loc[signal_index - 1, ["open", "high", "low", "close"]] = [
            9.0,
            9.2,
            8.8,
            9.0,
        ]
        prices.loc[signal_index, ["open", "high", "low", "close"]] = [
            9.8,
            10.1,
            9.7,
            10.0,
        ]
        prices.to_csv(price_cache / f"{ticker}.csv", index=False)
        journal_rows.extend(
            (
                json.dumps(
                    {
                        "date": signal_date,
                        "ticker": ticker,
                        "setup": "btst_breakout",
                        "action": "BUY",
                        "entry_price": 10.0,
                    }
                ),
                json.dumps(
                    {
                        "date": signal_date,
                        "ticker": ticker,
                        "setup": "btst_breakout",
                        "action": "EXIT",
                        "reasoning": "realized=+1.00%",
                    }
                ),
            )
        )

    journal = tmp_path / "journal.jsonl"
    journal.write_text("\n".join(journal_rows) + "\n", encoding="utf-8")
    return LegacyFixturePaths(journal=journal, price_cache=price_cache)


def test_cli_report_cannot_claim_production_readiness(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    output = tmp_path / "reports"
    rc = main(
        [
            "--journal",
            str(legacy_fixture_paths.journal),
            "--price-cache",
            str(legacy_fixture_paths.price_cache),
            "--output-dir",
            str(output),
            "--as-of",
            "20260714",
            "--bootstrap-draws",
            "100",
            "--bootstrap-seed",
            "7",
        ]
    )

    assert rc == 0
    payload = json.loads(
        (output / "exit_shadow_20260714.json").read_text(encoding="utf-8")
    )
    json_path = output / "exit_shadow_20260714.json"
    markdown_path = output / "exit_shadow_20260714.md"
    marker_path = output / "exit_shadow_20260714.commit.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["schema_version"] == 1
    assert (
        marker["semantic_payload_sha256"]
        == payload["artifact_identity"]["semantic_payload_sha256"]
    )


def test_future_evidence_changes_only_truthful_cutoff_audit_and_bundle_identity(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    before_output = tmp_path / "cutoff-reports-before"
    assert main(_base_args(legacy_fixture_paths, before_output)) == 0
    before = json.loads(
        (before_output / "exit_shadow_20260714.json").read_text(encoding="utf-8")
    )
    with legacy_fixture_paths.journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "date": "20260715", "ticker": "000001", "setup": "btst_breakout", "action": "BUY"
        }) + "\n")
    cache = legacy_fixture_paths.price_cache / "000001.csv"
    with cache.open("a", encoding="utf-8") as stream:
        stream.write("2026-07-15,99,99,99,99,1000\n")
    (legacy_fixture_paths.price_cache / "999999.csv").write_text(
        "date,open,high,low,close,volume\n2026-07-15,9,10,8,9,1000\n",
        encoding="utf-8",
    )
    output = tmp_path / "cutoff-reports-after"
    assert main(_base_args(legacy_fixture_paths, output)) == 0
    json_path = output / "exit_shadow_20260714.json"
    markdown_path = output / "exit_shadow_20260714.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    marker = json.loads((output / "exit_shadow_20260714.commit.json").read_text(encoding="utf-8"))
    assert marker["artifacts"]["json"]["filename"] == json_path.name
    assert (
        marker["artifacts"]["json"]["sha256"]
        == hashlib.sha256(json_path.read_bytes()).hexdigest()
    )
    assert marker["artifacts"]["markdown"]["filename"] == markdown_path.name
    assert (
        marker["artifacts"]["markdown"]["sha256"]
        == hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    )
    assert payload["mode"] == "legacy_sensitivity"
    assert payload["shadow_only"] is True
    assert payload["production_eligible"] is False
    assert payload["parameters"] == {
        "activation_return": 0.10,
        "atr_multiple": 2.5,
    }
    assert payload["policy_identity"]["cost_version"] == "daily-action-v2"
    assert payload["policy_identity"]["plan_exit_session"] == 9
    assert payload["policy_identity"]["planned_execution"] == "next_executable_open"
    assert payload["input_fingerprints"]["journal"]["sha256"]
    assert payload["input_fingerprints"]["price_cache"]["sha256"]
    assert payload["input_fingerprints"] == before["input_fingerprints"]
    assert payload["analysis_snapshot_fingerprint"] == before["analysis_snapshot_fingerprint"]
    assert payload["policy_identity"] == before["policy_identity"]
    assert payload["statistics"] == before["statistics"]
    assert payload["cutoff_audit"]["future_journal_rows"] == 1
    assert payload["cutoff_audit"]["future_price_rows"] == 2
    assert payload["cutoff_audit"]["future_price_affected_files"] == 2
    assert payload["cutoff_audit"]["future_only_price_files"] == 1
    assert payload["cutoff_audit"]["future_price_tickers"] == 2
    assert before["cutoff_audit"]["future_journal_rows"] == 0
    assert payload["cohort"]["counts"]["total_paired_btst"] == 2
    assert payload["cohort"]["exclusions"] == []
    assert payload["common_mask"]["total_paths"] == 2
    assert payload["common_mask"]["eligible"] == 2
    assert payload["statistics"]["coverage"] == 1.0
    assert payload["statistics"]["block_mean_difference"]["draws"] == 100
    assert payload["statistics"]["block_mean_difference"]["seed"] == 0
    assert payload["statistics"]["challenger"]["mfe_is_diagnostic_not_executable"]

    markdown = (output / "exit_shadow_20260714.md").read_text(encoding="utf-8")
    assert markdown.startswith("# Legacy sensitivity / shadow only")
    assert "production_eligible: false" in markdown
    assert "Why this cohort differs from current production" in markdown
    assert "six-month legacy backtest" in markdown
    assert "selected common executable mask" in markdown
    assert "price files containing future rows: 2" in markdown
    assert "future-only price files: 1" in markdown
    assert "tickers with future price rows: 2" in markdown


def test_historical_analysis_rejects_empty_marker_bypass(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "historical"
    output.mkdir()
    (output / "exit_shadow_20260714.commit.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(exit_shadow_cli, "_civil_today", lambda: date(2026, 7, 15))
    monkeypatch.setattr(
        exit_shadow_cli,
        "build_legacy_cohort",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reanalyzed")),
    )

    with pytest.raises(SystemExit):
        main(_base_args(legacy_fixture_paths, output))


def test_historical_rerun_is_forbidden_even_for_self_consistent_bundle(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "committed"
    assert main(_base_args(legacy_fixture_paths, output)) == 0
    monkeypatch.setattr(exit_shadow_cli, "_civil_today", lambda: date(2026, 7, 15))
    monkeypatch.setattr(
        exit_shadow_cli,
        "build_legacy_cohort",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reanalyzed")),
    )

    with pytest.raises(SystemExit):
        main(_base_args(legacy_fixture_paths, output))


def test_real_cli_attempts_no_socket_connection(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    instrumentation = tmp_path / "instrumentation"
    instrumentation.mkdir()
    attempt_log = tmp_path / "socket-attempts.jsonl"
    (instrumentation / "sitecustomize.py").write_text(
        f"""import json
import socket
from pathlib import Path

ATTEMPT_LOG = Path({str(attempt_log)!r})

def deny(name):
    def blocked(*args, **kwargs):
        attempt = {{"primitive": name, "address": repr(args[-1] if args else kwargs)}}
        with ATTEMPT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(attempt) + "\\n")
        raise AssertionError("socket attempt: " + repr(attempt))
    return blocked

socket.socket.connect = deny("socket.connect")
socket.socket.connect_ex = deny("socket.connect_ex")
socket.create_connection = deny("socket.create_connection")
""",
        encoding="utf-8",
    )
    output = tmp_path / "reports"
    project_root = Path(__file__).resolve().parents[2]
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(instrumentation), str(project_root))),
    }
    subprocess_args = _base_args(legacy_fixture_paths, output)
    live_as_of = date.today().strftime("%Y%m%d")
    subprocess_args[subprocess_args.index("--as-of") + 1] = live_as_of
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_exit_shadow_research.py",
            *subprocess_args,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert not attempt_log.exists()
    assert (output / f"exit_shadow_{live_as_of}.commit.json").is_file()


def test_report_semantic_and_artifact_hashes_are_independently_verifiable(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    output = tmp_path / "reports"
    assert main(_base_args(legacy_fixture_paths, output)) == 0
    json_path = output / "exit_shadow_20260714.json"
    markdown_path = output / "exit_shadow_20260714.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    identity = payload["artifact_identity"]
    semantic_payload = dict(payload)
    semantic_payload.pop("artifact_identity")
    canonical = json.dumps(
        semantic_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    assert identity["contract_identity"] == "exit-shadow-legacy-sensitivity-v2"
    assert identity["semantic_payload_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert (
        identity["markdown_sha256"]
        == hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    )
    assert identity["commit_marker_filename"] == "exit_shadow_20260714.commit.json"


def test_fixed_policy_identity_and_markdown_are_complete(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    output = tmp_path / "reports"
    assert main(_base_args(legacy_fixture_paths, output)) == 0
    payload = json.loads(
        (output / "exit_shadow_20260714.json").read_text(encoding="utf-8")
    )
    policy = payload["policy_identity"]

    assert policy["activation_return"] == 0.10
    assert policy["atr_multiple"] == 2.5
    assert policy["atr"] == {"method": "Wilder", "period": 14}
    assert policy["entry"] == {
        "holding_session": 1,
        "price": "open",
        "exit_allowed": False,
    }
    assert policy["baseline"] == {
        "trigger": "session_9_close",
        "planned_execution": "session_10_next_executable_open",
    }
    assert policy["close_trigger_execution"] == "next_executable_open"
    assert policy["queue_suspension_deferral"] == "defer_over_supplied_sessions"
    assert policy["execution_classifier"] == "classify_open_fill"
    assert policy["t_plus_one"] is True
    assert policy["execution_costs"] == {
        "version": "daily-action-v2",
        "commission": 0.0,
        "tax_rate": 0.0,
        "slippage_bps": 0.0,
        "other_fee": 0.0,
    }

    markdown = (output / "exit_shadow_20260714.md").read_text(encoding="utf-8")
    for disclosure in (
        "activation return: 10.00%",
        "ATR: Wilder period 14, multiple 2.5",
        "entry: holding session 1 open; no session-1 exit",
        "baseline: session-9 close trigger; session-10 next executable open",
        "close-trigger execution: next executable open",
        "queue/suspension: defer over supplied sessions",
        "execution classifier: classify_open_fill",
        "T+1: true",
        "commission=0.0, tax_rate=0.0, slippage_bps=0.0, other_fee=0.0",
    ):
        assert disclosure in markdown


def test_markdown_separates_reconstruction_and_common_mask_denominators(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    output = tmp_path / "reports"
    assert main(_base_args(legacy_fixture_paths, output)) == 0
    markdown = (output / "exit_shadow_20260714.md").read_text(encoding="utf-8")

    assert "reconstruction coverage: 2/2 (100.0000%)" in markdown
    assert "reconstruction covered legacy mean:" in markdown
    assert "reconstruction missing legacy mean:" in markdown
    assert "common executable coverage: 2/2 (100.0000%)" in markdown
    assert "common-mask covered legacy mean:" in markdown
    assert "common-mask missing legacy mean:" in markdown
    assert "baseline mean / median / worst decile / downside-decile mean:" in markdown
    assert "challenger mean / median / worst decile / downside-decile mean:" in markdown
    assert "paired downside-decile mean difference:" in markdown
    assert "exit reasons:" in markdown
    assert "candidate / usable / empty blocks:" in markdown
    assert "MFE uses non-executable daily highs" in markdown
    assert "Cohort exclusion reasons" in markdown
    assert "Common-mask exclusion reasons" in markdown


def test_cli_rejects_policy_search_arguments(
    legacy_fixture_paths: LegacyFixturePaths,
) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--journal",
                str(legacy_fixture_paths.journal),
                "--price-cache",
                str(legacy_fixture_paths.price_cache),
                "--as-of",
                "20260714",
                "--activation-return",
                "0.2",
            ]
        )


def test_cli_never_overwrites_mismatched_same_as_of_report(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    output = tmp_path / "reports"
    args = [
        "--journal",
        str(legacy_fixture_paths.journal),
        "--price-cache",
        str(legacy_fixture_paths.price_cache),
        "--output-dir",
        str(output),
        "--as-of",
        "20260714",
        "--bootstrap-draws",
        "100",
    ]
    assert main(args) == 0
    json_path = output / "exit_shadow_20260714.json"
    md_path = output / "exit_shadow_20260714.md"
    original_json = json_path.read_bytes()
    original_md = md_path.read_bytes()

    with pytest.raises(FileExistsError, match="immutable report conflict"):
        main([*args[:-1], "101"])

    assert json_path.read_bytes() == original_json
    assert md_path.read_bytes() == original_md


def test_cli_same_inputs_are_idempotent(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    output = tmp_path / "reports"
    args = [
        "--journal",
        str(legacy_fixture_paths.journal),
        "--price-cache",
        str(legacy_fixture_paths.price_cache),
        "--output-dir",
        str(output),
        "--as-of",
        "20260714",
        "--bootstrap-draws",
        "100",
    ]

    assert main(args) == 0
    assert main(args) == 0


def test_unmatched_exit_is_reported_without_entering_paired_denominator(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    with legacy_fixture_paths.journal.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "date": "20260105",
                    "ticker": "000003",
                    "setup": "btst_breakout",
                    "action": "EXIT",
                    "reasoning": "realized=+2.00%",
                }
            )
            + "\n"
        )

    output = tmp_path / "reports"
    assert (
        main(
            [
                "--journal",
                str(legacy_fixture_paths.journal),
                "--price-cache",
                str(legacy_fixture_paths.price_cache),
                "--output-dir",
                str(output),
                "--as-of",
                "20260714",
                "--bootstrap-draws",
                "100",
            ]
        )
        == 0
    )
    payload = json.loads(
        (output / "exit_shadow_20260714.json").read_text(encoding="utf-8")
    )
    assert payload["cohort"]["denominator"] == 2
    assert payload["statistics"]["coverage"] == 1.0
    assert payload["cohort"]["exclusions"][0]["reason"] == "unmatched_buy"


def test_partial_identical_report_is_recovered_without_rewriting_existing_file(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    output = tmp_path / "reports"
    args = [
        "--journal",
        str(legacy_fixture_paths.journal),
        "--price-cache",
        str(legacy_fixture_paths.price_cache),
        "--output-dir",
        str(output),
        "--as-of",
        "20260714",
        "--bootstrap-draws",
        "100",
    ]
    assert main(args) == 0
    json_path = output / "exit_shadow_20260714.json"
    md_path = output / "exit_shadow_20260714.md"
    original_json = json_path.read_bytes()
    md_path.unlink()
    marker_path = output / "exit_shadow_20260714.commit.json"
    marker_path.unlink(missing_ok=True)

    assert main(args) == 0

    assert json_path.read_bytes() == original_json
    assert md_path.is_file()
    assert marker_path.is_file()


def test_irrelevant_blank_input_change_during_run_does_not_poison_cutoff_report(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = exit_shadow_cli.build_legacy_cohort

    def build_then_mutate(*args: object, **kwargs: object):
        cohort = original_builder(*args, **kwargs)
        with legacy_fixture_paths.journal.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        return cohort

    monkeypatch.setattr(exit_shadow_cli, "build_legacy_cohort", build_then_mutate)
    output = tmp_path / "reports"

    assert (
        main(
            [
                "--journal",
                str(legacy_fixture_paths.journal),
                "--price-cache",
                str(legacy_fixture_paths.price_cache),
                "--output-dir",
                str(output),
                "--as-of",
                "20260714",
                "--bootstrap-draws",
                "100",
            ]
        ) == 0
    )
    assert (output / "exit_shadow_20260714.json").is_file()


def test_consumed_pre_cutoff_mutation_during_run_blocks_publication(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_builder = exit_shadow_cli.build_legacy_cohort

    def build_then_mutate(*args, **kwargs):
        cohort = original_builder(*args, **kwargs)
        content = legacy_fixture_paths.journal.read_text(encoding="utf-8")
        legacy_fixture_paths.journal.write_text(content.replace('"entry_price": 10.0', '"entry_price": 10.5', 1), encoding="utf-8")
        return cohort

    monkeypatch.setattr(exit_shadow_cli, "build_legacy_cohort", build_then_mutate)
    with pytest.raises(RuntimeError, match="inputs changed during report run"):
        main(_base_args(legacy_fixture_paths, tmp_path / "reports"))


def test_single_line_holding_exclusion_retains_missing_group_return(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    rows = [
        json.loads(line)
        for line in legacy_fixture_paths.journal.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    rows[0]["horizon"] = 5
    third_signal_date = _business_dates(date(2025, 12, 1), 55)[43].strftime("%Y%m%d")
    rows.extend(
        (
            {
                "date": third_signal_date,
                "ticker": "000003",
                "setup": "btst_breakout",
                "action": "BUY",
                "entry_price": 10.0,
            },
            {
                "date": third_signal_date,
                "ticker": "000003",
                "setup": "btst_breakout",
                "action": "EXIT",
                "reasoning": "realized=+1.00%",
            },
        )
    )
    (legacy_fixture_paths.price_cache / "000003.csv").write_bytes(
        (legacy_fixture_paths.price_cache / "000002.csv").read_bytes()
    )
    legacy_fixture_paths.journal.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    output = tmp_path / "reports"

    assert (
        main(
            [
                "--journal",
                str(legacy_fixture_paths.journal),
                "--price-cache",
                str(legacy_fixture_paths.price_cache),
                "--output-dir",
                str(output),
                "--as-of",
                "20260714",
                "--bootstrap-draws",
                "100",
            ]
        )
        == 0
    )
    payload = json.loads(
        (output / "exit_shadow_20260714.json").read_text(encoding="utf-8")
    )
    assert payload["cohort"]["denominator"] == 3
    assert payload["statistics"]["coverage"] == pytest.approx(2 / 3)
    assert payload["statistics"]["missing_group_legacy_mean"] == 0.01
    assert payload["cohort"]["exclusions"][0]["line_numbers"] == [1]


def test_concurrent_identical_completion_is_never_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "reports"
    output.mkdir()
    original_link = exit_shadow_cli.os.link
    link_count = 0

    def complete_then_report_collision(
        source: str, target: str, **kwargs: object
    ) -> None:
        nonlocal link_count
        link_count += 1
        if link_count == 2:
            original_link(source, target, **kwargs)
            raise FileExistsError("simulated concurrent identical publisher")
        original_link(source, target, **kwargs)

    monkeypatch.setattr(exit_shadow_cli.os, "link", complete_then_report_collision)

    exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))

    assert (output / "exit_shadow_20260714.json").read_bytes() == b'{"report":"json"}\n'
    assert (output / "exit_shadow_20260714.md").read_bytes() == b"# report\n"
    assert (output / "exit_shadow_20260714.commit.json").is_file()


def _commit_fixture(output: Path) -> tuple[str, bytes, bytes, str]:
    return (
        "exit_shadow_20260714",
        b'{"report":"json"}\n',
        b"# report\n",
        hashlib.sha256(b"semantic payload").hexdigest(),
    )


@pytest.mark.parametrize("fail_after_publish", [1, 2, 3])
def test_commit_protocol_recovers_from_every_publish_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_after_publish: int,
) -> None:
    output = tmp_path / "reports"
    output.mkdir()
    original_publish = exit_shadow_cli._publish_exclusive
    calls = 0

    def publish_then_crash(*args: object, **kwargs: object) -> None:
        nonlocal calls
        original_publish(*args, **kwargs)
        calls += 1
        if calls == fail_after_publish:
            raise RuntimeError("simulated crash boundary")

    monkeypatch.setattr(exit_shadow_cli, "_publish_exclusive", publish_then_crash)
    with pytest.raises(RuntimeError, match="simulated crash boundary"):
        exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))
    marker_exists = (output / "exit_shadow_20260714.commit.json").exists()
    assert marker_exists is (fail_after_publish == 3)

    monkeypatch.setattr(exit_shadow_cli, "_publish_exclusive", original_publish)
    exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))

    assert (output / "exit_shadow_20260714.json").is_file()
    assert (output / "exit_shadow_20260714.md").is_file()
    assert (output / "exit_shadow_20260714.commit.json").is_file()
    assert not list(output.glob(".*.tmp-*"))


def test_commit_protocol_fsyncs_directory_and_uses_normal_file_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "reports"
    output.mkdir()
    original_fsync = exit_shadow_cli.os.fsync
    directory_fsyncs = 0

    def track_fsync(descriptor: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_fsyncs += 1
        original_fsync(descriptor)

    monkeypatch.setattr(exit_shadow_cli.os, "fsync", track_fsync)
    exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))

    assert directory_fsyncs >= 2
    for suffix in ("json", "md", "commit.json"):
        mode = stat.S_IMODE((output / f"exit_shadow_20260714.{suffix}").stat().st_mode)
        assert mode == 0o644


def test_open_output_directory_fsyncs_each_new_parent_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_fsync = exit_shadow_cli.os.fsync
    directory_fsyncs = 0

    def track_fsync(descriptor: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_fsyncs += 1
        original_fsync(descriptor)

    monkeypatch.setattr(exit_shadow_cli.os, "fsync", track_fsync)
    descriptor = exit_shadow_cli._open_output_directory(tmp_path / "new" / "nested")
    os.close(descriptor)
    assert directory_fsyncs == 2


def test_open_output_directory_accepts_concurrent_identical_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "concurrent"
    original_mkdir = exit_shadow_cli.os.mkdir
    raced = False

    def concurrent_mkdir(
        name: str, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        nonlocal raced
        if not raced:
            raced = True
            original_mkdir(name, mode, dir_fd=dir_fd)
            raise FileExistsError("simulated concurrent mkdir")
        original_mkdir(name, mode, dir_fd=dir_fd)

    monkeypatch.setattr(exit_shadow_cli.os, "mkdir", concurrent_mkdir)
    descriptor = exit_shadow_cli._open_output_directory(target)
    try:
        assert stat.S_ISDIR(os.fstat(descriptor).st_mode)
    finally:
        os.close(descriptor)


def test_fallback_atomically_renames_fsynced_stage_without_rewriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    temporary = ".report.json.tmp-owner"
    content = b"complete report"
    (tmp_path / temporary).write_bytes(content)

    def unsupported_link(*args: object, **kwargs: object) -> None:
        raise OSError(errno.EOPNOTSUPP, "unsupported")

    def forbidden_rewrite(descriptor: int, body: bytes) -> None:
        raise AssertionError("fallback must not rewrite the final artifact")

    monkeypatch.setattr(exit_shadow_cli.os, "link", unsupported_link)
    monkeypatch.setattr(exit_shadow_cli, "_write_all", forbidden_rewrite)
    exit_shadow_cli._publish_exclusive(directory_fd, temporary, "report.json", content)
    assert (tmp_path / "report.json").read_bytes() == content
    assert not (tmp_path / temporary).exists()
    os.close(directory_fd)


def test_fallback_never_overwrites_target_created_after_last_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    temporary = ".report.json.tmp-owner"
    content = b"complete report"
    intruder = b"concurrent immutable artifact"
    (tmp_path / temporary).write_bytes(content)
    original_rename = exit_shadow_cli._rename_noreplace_at

    def unsupported_link(*args: object, **kwargs: object) -> None:
        raise OSError(errno.EOPNOTSUPP, "unsupported")

    def concurrent_target(descriptor: int, source_name: str, target_name: str) -> None:
        (tmp_path / target_name).write_bytes(intruder)
        original_rename(descriptor, source_name, target_name)

    monkeypatch.setattr(exit_shadow_cli.os, "link", unsupported_link)
    monkeypatch.setattr(exit_shadow_cli, "_rename_noreplace_at", concurrent_target)
    with pytest.raises(FileExistsError):
        exit_shadow_cli._publish_exclusive(
            directory_fd, temporary, "report.json", content
        )
    assert (tmp_path / "report.json").read_bytes() == intruder
    assert (tmp_path / temporary).read_bytes() == content
    os.close(directory_fd)


def test_commit_does_not_delete_another_publishers_live_stage(tmp_path: Path) -> None:
    live_stage = tmp_path / ".exit_shadow_20260714.json.tmp-other-publisher"
    live_stage.write_bytes(b"still in use")

    exit_shadow_cli._commit_report_bundle(
        tmp_path,
        "exit_shadow_20260714",
        b'{"payload": true}\n',
        b"# report\n",
        "0" * 64,
    )

    assert live_stage.read_bytes() == b"still in use"


def test_commit_protocol_falls_back_when_hardlinks_are_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "reports"
    output.mkdir()

    def unsupported_link(*args: object, **kwargs: object) -> None:
        raise OSError(errno.EOPNOTSUPP, "hardlinks unsupported")

    monkeypatch.setattr(exit_shadow_cli.os, "link", unsupported_link)
    exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))

    assert (output / "exit_shadow_20260714.commit.json").is_file()


@pytest.mark.parametrize("existing_kind", ["symlink", "fifo"])
def test_commit_protocol_rejects_nonregular_existing_artifact(
    tmp_path: Path, existing_kind: str
) -> None:
    output = tmp_path / "reports"
    output.mkdir()
    target = output / "exit_shadow_20260714.json"
    if existing_kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_text("outside", encoding="utf-8")
        target.symlink_to(outside)
    else:
        os.mkfifo(target)

    with pytest.raises(FileExistsError, match="nonregular or symlink"):
        exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))


@pytest.mark.parametrize("fail_after_stage", [1, 2, 3])
def test_commit_protocol_recovers_and_cleans_temps_after_every_stage_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_after_stage: int,
) -> None:
    output = tmp_path / "reports"
    output.mkdir()
    original_stage = exit_shadow_cli._stage_at
    calls = 0

    def stage_then_crash(*args: object, **kwargs: object) -> str:
        nonlocal calls
        temporary = original_stage(*args, **kwargs)
        calls += 1
        if calls == fail_after_stage:
            raise RuntimeError("simulated stage boundary")
        return temporary

    monkeypatch.setattr(exit_shadow_cli, "_stage_at", stage_then_crash)
    with pytest.raises(RuntimeError, match="simulated stage boundary"):
        exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))

    monkeypatch.setattr(exit_shadow_cli, "_stage_at", original_stage)
    exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))
    assert (output / "exit_shadow_20260714.commit.json").is_file()
    assert not list(output.glob(".*.tmp-*"))


@pytest.mark.parametrize("fail_after_directory_fsync", [1, 2])
def test_commit_protocol_recovers_from_each_directory_fsync_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_after_directory_fsync: int,
) -> None:
    output = tmp_path / "reports"
    output.mkdir()
    original_fsync = exit_shadow_cli.os.fsync
    directory_calls = 0

    def fsync_then_crash(descriptor: int) -> None:
        nonlocal directory_calls
        original_fsync(descriptor)
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_calls += 1
            if directory_calls == fail_after_directory_fsync:
                raise RuntimeError("simulated directory fsync boundary")

    monkeypatch.setattr(exit_shadow_cli.os, "fsync", fsync_then_crash)
    with pytest.raises(RuntimeError, match="simulated directory fsync boundary"):
        exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))

    monkeypatch.setattr(exit_shadow_cli.os, "fsync", original_fsync)
    exit_shadow_cli._commit_report_bundle(output, *_commit_fixture(output))
    assert (output / "exit_shadow_20260714.commit.json").is_file()


def test_rerun_rejects_corrupt_marker_or_marker_artifact_mismatch(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    output = tmp_path / "reports"
    args = _base_args(legacy_fixture_paths, output)
    assert main(args) == 0
    marker = output / "exit_shadow_20260714.commit.json"
    json_path = output / "exit_shadow_20260714.json"
    original_marker = marker.read_bytes()
    original_json = json_path.read_bytes()

    marker.write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="mismatched commit marker"):
        main(args)
    assert json_path.read_bytes() == original_json

    marker.write_bytes(original_marker)
    json_path.write_bytes(original_json + b" ")
    with pytest.raises(FileExistsError, match="commit marker artifact mismatch"):
        main(args)


def _base_args(paths: LegacyFixturePaths, output: Path) -> list[str]:
    return [
        "--journal",
        str(paths.journal),
        "--price-cache",
        str(paths.price_cache),
        "--output-dir",
        str(output),
        "--as-of",
        "20260714",
        "--bootstrap-draws",
        "100",
    ]


@pytest.mark.parametrize("overlap", ["cache", "ancestor"])
def test_cli_rejects_output_overlapping_any_input_boundary(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    overlap: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = legacy_fixture_paths.price_cache if overlap == "cache" else tmp_path

    with pytest.raises(SystemExit):
        main(_base_args(legacy_fixture_paths, output))
    assert "output directory must be disjoint" in capsys.readouterr().err


def test_cli_rejects_repository_source_output_when_invoked_elsewhere(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(exit_shadow_cli.__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit):
        main(_base_args(legacy_fixture_paths, repository_root / "src"))
    assert "output directory must be disjoint" in capsys.readouterr().err


def test_live_input_open_does_not_follow_replaced_ancestor(
    tmp_path: Path, legacy_fixture_paths: LegacyFixturePaths
) -> None:
    input_root = legacy_fixture_paths.journal.parent
    trusted_root = tmp_path.parent / f"{tmp_path.name}-trusted"
    attacker_root = tmp_path.parent / f"{tmp_path.name}-attacker"
    input_root.rename(trusted_root)
    attacker_root.mkdir()
    (attacker_root / legacy_fixture_paths.journal.name).write_bytes(b"{}\n")
    (attacker_root / legacy_fixture_paths.price_cache.name).mkdir()
    input_root.symlink_to(attacker_root, target_is_directory=True)

    with pytest.raises(OSError):
        exit_shadow_cli._read_live_inputs(
            legacy_fixture_paths.journal, legacy_fixture_paths.price_cache
        )


@pytest.mark.parametrize("target_kind", ["cache", "runtime"])
def test_cli_rejects_symlinked_output_alias(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    target_kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = legacy_fixture_paths.price_cache
    if target_kind == "runtime":
        target = tmp_path / "paper_trading"
        target.mkdir()
    output = tmp_path / "output_alias"
    output.symlink_to(target, target_is_directory=True)

    with pytest.raises(SystemExit):
        main(_base_args(legacy_fixture_paths, output))
    assert "output path must not contain symlinks" in capsys.readouterr().err


@pytest.mark.parametrize("input_kind", ["journal", "cache"])
def test_cli_rejects_symlinked_inputs(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    input_kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alias = tmp_path / f"{input_kind}_alias"
    target = getattr(
        legacy_fixture_paths, "price_cache" if input_kind == "cache" else "journal"
    )
    alias.symlink_to(target, target_is_directory=input_kind == "cache")
    paths = LegacyFixturePaths(
        journal=alias if input_kind == "journal" else legacy_fixture_paths.journal,
        price_cache=alias
        if input_kind == "cache"
        else legacy_fixture_paths.price_cache,
    )

    with pytest.raises(SystemExit):
        main(_base_args(paths, tmp_path / "reports"))
    assert "input path must not contain symlinks" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [
        ("--bootstrap-seed", "-1", "bootstrap seed must be a nonnegative integer"),
        ("--bootstrap-seed", "1.5", "invalid"),
        ("--bootstrap-draws", "0", "bootstrap draws must be a positive integer"),
        ("--bootstrap-draws", "1.5", "invalid"),
    ],
)
def test_cli_requires_exact_integer_bootstrap_controls(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    flag: str,
    value: str,
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main([*_base_args(legacy_fixture_paths, tmp_path / "reports"), flag, value])
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("entry_kind", ["symlink", "fifo"])
def test_cli_rejects_nonregular_cache_entries(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    entry_kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = legacy_fixture_paths.price_cache / "999999.csv"
    if entry_kind == "symlink":
        entry.symlink_to(legacy_fixture_paths.price_cache / "000001.csv")
    else:
        os.mkfifo(entry)

    with pytest.raises(SystemExit):
        main(_base_args(legacy_fixture_paths, tmp_path / "reports"))
    assert "cache entries must be nofollow regular files" in capsys.readouterr().err


def test_nofollow_journal_type_check_does_not_block_on_fifo(tmp_path: Path) -> None:
    fifo = tmp_path / "journal.jsonl"
    os.mkfifo(fifo)
    errors: list[BaseException] = []

    def validate() -> None:
        try:
            exit_shadow_cli._validate_nofollow_input(fifo, directory=False)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=validate, daemon=True)
    worker.start()
    worker.join(timeout=0.25)

    assert not worker.is_alive(), (
        "nofollow FIFO validation blocked before type rejection"
    )
    assert errors and isinstance(errors[0], ValueError)


def test_analysis_runs_only_from_single_read_snapshot(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = exit_shadow_cli.build_legacy_cohort
    original_journal = legacy_fixture_paths.journal.read_bytes()
    observed: dict[str, Path] = {}

    def inspect_snapshot(journal_path: Path | str, **kwargs: object):
        snapshot_journal = Path(journal_path)
        snapshot_cache = Path(kwargs["price_cache_dir"])
        observed["journal"] = snapshot_journal
        observed["cache"] = snapshot_cache
        assert snapshot_journal != legacy_fixture_paths.journal
        assert snapshot_cache != legacy_fixture_paths.price_cache
        assert snapshot_journal.read_bytes() == original_journal
        return original_builder(journal_path, **kwargs)

    monkeypatch.setattr(exit_shadow_cli, "build_legacy_cohort", inspect_snapshot)
    output = tmp_path / "reports"

    assert main(_base_args(legacy_fixture_paths, output)) == 0
    payload = json.loads(
        (output / "exit_shadow_20260714.json").read_text(encoding="utf-8")
    )
    assert payload["input_fingerprints_before"] == payload["input_fingerprints_after"]
    assert payload["analysis_snapshot_fingerprint"]["journal"]["sha256"]
    assert not observed["journal"].exists()
    assert not observed["cache"].exists()


def test_semantically_empty_aba_does_not_change_consumed_fingerprint(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = exit_shadow_cli.build_legacy_cohort
    original_bytes = legacy_fixture_paths.journal.read_bytes()

    def mutate_restore_then_build(*args: object, **kwargs: object):
        legacy_fixture_paths.journal.write_bytes(original_bytes + b"\n")
        legacy_fixture_paths.journal.write_bytes(original_bytes)
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(
        exit_shadow_cli, "build_legacy_cohort", mutate_restore_then_build
    )
    output = tmp_path / "reports"

    assert main(_base_args(legacy_fixture_paths, output)) == 0


def test_unconsumed_cache_membership_aba_is_ignored(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = exit_shadow_cli.build_legacy_cohort

    def add_remove_then_build(*args: object, **kwargs: object):
        transient = legacy_fixture_paths.price_cache / "999999.csv"
        transient.write_text("transient", encoding="utf-8")
        transient.unlink()
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(exit_shadow_cli, "build_legacy_cohort", add_remove_then_build)

    assert main(_base_args(legacy_fixture_paths, tmp_path / "reports")) == 0


def test_irrelevant_blank_append_after_render_does_not_poison_commit(
    tmp_path: Path,
    legacy_fixture_paths: LegacyFixturePaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_render = exit_shadow_cli._render_markdown

    def render_then_mutate(payload: dict[str, object]) -> str:
        rendered = original_render(payload)
        with legacy_fixture_paths.journal.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        return rendered

    monkeypatch.setattr(exit_shadow_cli, "_render_markdown", render_then_mutate)
    output = tmp_path / "reports"

    assert main(_base_args(legacy_fixture_paths, output)) == 0
