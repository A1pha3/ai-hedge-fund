import os
from pathlib import Path

import pytest

from scripts import btst_momentum_rollout_blocker_dossier as dossier_script


SAMPLE_MD = """
# Optimized Profile Report

Summary

Rollout Blockers:

- `missing metrics pipeline`
- Cross-window stability: alignment failure between windows
- `risk/payoff regression` observed in backtest
- Some unclassified issue needing review

Other Section

"""


def test_build_momentum_rollout_blocker_dossier_groups_and_surfaces_unclassified(tmp_path, monkeypatch):
    # write sample markdown to a repo-local path
    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    md_path = fixtures_dir / "sample_optimized_profile.md"
    md_path.write_text(SAMPLE_MD)

    # call builder with the markdown text
    with md_path.open("r", encoding="utf-8") as f:
        md_text = f.read()

    result = dossier_script.build_momentum_rollout_blocker_dossier(md_text)

    # result should have families mapping with exactly the three keys
    assert "families" in result
    families = result["families"]
    expected_keys = {"missing_observability", "cross_window_stability", "risk_payoff_regression"}
    assert set(families.keys()) == expected_keys

    # each family should be a list
    for k in expected_keys:
        assert isinstance(families[k], list)

    # the sample blockers should be classified into the expected families
    # missing metrics -> missing_observability
    assert any("missing metrics" in b.lower() or "missing" in b.lower() and "metric" in b.lower() for b in families["missing_observability"])

    # cross-window -> cross_window_stability
    assert any("cross-window" in b.lower() or "cross window" in b.lower() or "window" in b.lower() for b in families["cross_window_stability"])

    # risk/payoff regression -> risk_payoff_regression
    assert any("risk" in b.lower() and ("regression" in b.lower() or "payoff" in b.lower()) for b in families["risk_payoff_regression"])

    # unclassified blockers must be surfaced and not dropped
    assert "unclassified" in result
    assert isinstance(result["unclassified"], list)
    assert any("unclassified issue" in b.lower() for b in result["unclassified"]) 


def test_main_writes_json_and_md_outputs(tmp_path, monkeypatch):
    # prepare input file
    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    md_path = fixtures_dir / "sample_optimized_profile_for_main.md"
    md_path.write_text(SAMPLE_MD)

    out_dir = Path("outputs/test_blocker_dossier")
    if out_dir.exists():
        # clear
        for p in out_dir.iterdir():
            p.unlink()
    else:
        out_dir.mkdir(parents=True)

    # run main with input and output dir
    dossier_script.main(argv=["--input-md", str(md_path), "--out-dir", str(out_dir)])

    json_out = out_dir / "momentum_rollout_blocker_dossier.json"
    md_out = out_dir / "momentum_rollout_blocker_dossier.md"

    assert json_out.exists(), f"Expected JSON output at {json_out}"
    assert md_out.exists(), f"Expected MD output at {md_out}"

    # basic content checks
    json_text = json_out.read_text(encoding="utf-8")
    assert '"families"' in json_text

    md_text = md_out.read_text(encoding="utf-8")
    assert "Rollout Blocker Dossier" in md_text
