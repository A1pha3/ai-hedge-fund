from __future__ import annotations

import json
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
            "20260713",
            "--bootstrap-draws",
            "100",
            "--bootstrap-seed",
            "7",
        ]
    )

    assert rc == 0
    payload = json.loads(
        (output / "exit_shadow_20260713.json").read_text(encoding="utf-8")
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
    assert payload["cohort"]["counts"]["total_paired_btst"] == 2
    assert payload["cohort"]["exclusions"] == []
    assert payload["common_mask"]["total_paths"] == 2
    assert payload["common_mask"]["eligible"] == 2
    assert payload["statistics"]["coverage"] == 1.0
    assert payload["statistics"]["block_mean_difference"]["draws"] == 100
    assert payload["statistics"]["block_mean_difference"]["seed"] == 7
    assert payload["statistics"]["challenger"]["mfe_is_diagnostic_not_executable"]

    markdown = (output / "exit_shadow_20260713.md").read_text(encoding="utf-8")
    assert markdown.startswith("# Legacy sensitivity / shadow only")
    assert "production_eligible: false" in markdown
    assert "Why this cohort differs from current production" in markdown
    assert "six-month legacy backtest" in markdown
    assert "selected common executable mask" in markdown


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
                "20260713",
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
        "20260713",
        "--bootstrap-draws",
        "100",
    ]
    assert main(args) == 0
    json_path = output / "exit_shadow_20260713.json"
    md_path = output / "exit_shadow_20260713.md"
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
        "20260713",
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
                "20260713",
                "--bootstrap-draws",
                "100",
            ]
        )
        == 0
    )
    payload = json.loads(
        (output / "exit_shadow_20260713.json").read_text(encoding="utf-8")
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
        "20260713",
        "--bootstrap-draws",
        "100",
    ]
    assert main(args) == 0
    json_path = output / "exit_shadow_20260713.json"
    md_path = output / "exit_shadow_20260713.md"
    original_json = json_path.read_bytes()
    md_path.unlink()

    assert main(args) == 0

    assert json_path.read_bytes() == original_json
    assert md_path.is_file()


def test_input_change_during_run_prevents_report_publication(
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

    with pytest.raises(RuntimeError, match="inputs changed during report run"):
        main(
            [
                "--journal",
                str(legacy_fixture_paths.journal),
                "--price-cache",
                str(legacy_fixture_paths.price_cache),
                "--output-dir",
                str(output),
                "--as-of",
                "20260713",
                "--bootstrap-draws",
                "100",
            ]
        )

    assert not output.exists()


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
                "20260713",
                "--bootstrap-draws",
                "100",
            ]
        )
        == 0
    )
    payload = json.loads(
        (output / "exit_shadow_20260713.json").read_text(encoding="utf-8")
    )
    assert payload["cohort"]["denominator"] == 3
    assert payload["statistics"]["coverage"] == pytest.approx(2 / 3)
    assert payload["statistics"]["missing_group_legacy_mean"] == 0.01
    assert payload["cohort"]["exclusions"][0]["line_numbers"] == [1]


def test_concurrent_identical_completion_is_never_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"
    files = ((json_path, b"{}\n"), (md_path, b"# report\n"))
    original_link = exit_shadow_cli.os.link
    link_count = 0

    def complete_then_report_collision(source: Path, target: Path) -> None:
        nonlocal link_count
        link_count += 1
        if link_count == 2:
            original_link(source, target)
            raise FileExistsError("simulated concurrent identical publisher")
        original_link(source, target)

    monkeypatch.setattr(exit_shadow_cli.os, "link", complete_then_report_collision)

    exit_shadow_cli._publish_immutable_pair(files)

    assert json_path.read_bytes() == b"{}\n"
    assert md_path.read_bytes() == b"# report\n"
