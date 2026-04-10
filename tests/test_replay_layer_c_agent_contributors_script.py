from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.replay_layer_c_agent_contributors as replay_layer_c_agent_contributors


def test_main_requires_at_least_one_variant(monkeypatch) -> None:
    monkeypatch.setattr(
        replay_layer_c_agent_contributors.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            baseline="baseline.jsonl",
            variants=[],
            dates="20260202",
            model_name=None,
            model_provider=None,
            output=None,
            resume=False,
            ticker_batch_size=0,
            tickers=[],
        ),
    )

    with pytest.raises(ValueError, match="至少需要提供一个 --variant"):
        replay_layer_c_agent_contributors.main()


def test_main_replays_targets_and_persists_progress(monkeypatch, tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "replay.json"
    writes: list[dict] = []
    runner_calls: list[tuple[list[str], str, str]] = []

    monkeypatch.setattr(
        replay_layer_c_agent_contributors.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            baseline=str(tmp_path / "baseline.jsonl"),
            variants=[str(tmp_path / "variant_a.jsonl")],
            dates="20260202",
            model_name="demo-model",
            model_provider="demo-provider",
            output=str(output_path),
            resume=True,
            ticker_batch_size=1,
            tickers=["300001"],
        ),
    )

    monkeypatch.setattr(
        replay_layer_c_agent_contributors,
        "_load_pipeline_rows",
        lambda path: {"20260202": {"trade_date": "20260202", "path": str(path)}},
    )
    monkeypatch.setattr(
        replay_layer_c_agent_contributors,
        "resolve_model_selection",
        lambda model_name, model_provider: ("resolved-model", "resolved-provider"),
    )
    monkeypatch.setattr(replay_layer_c_agent_contributors, "ANALYST_ORDER", [("a", "alpha"), ("b", "beta")])

    def _fake_runner(tickers: list[str], trade_date: str, mode: str):
        runner_calls.append((tickers, trade_date, mode))
        return {"signals": tickers}

    monkeypatch.setattr(replay_layer_c_agent_contributors, "make_pipeline_agent_runner", lambda **kwargs: _fake_runner)
    monkeypatch.setattr(
        replay_layer_c_agent_contributors,
        "_build_focus_targets",
        lambda baseline_rows, variant_rows, selected_dates, variant_name: [
            {
                "variant": variant_name,
                "trade_date": "20260202",
                "ticker": "300001",
                "logged": {"score_b": 0.4, "score_c": 0.1, "score_final": 0.2, "decision": "watch", "bc_conflict": None, "reasons": []},
            }
        ],
    )
    monkeypatch.setattr(replay_layer_c_agent_contributors, "_filter_targets_by_tickers", lambda targets, selected_tickers: targets)
    monkeypatch.setattr(replay_layer_c_agent_contributors, "_load_existing_output", lambda path: ([], []))
    monkeypatch.setattr(
        replay_layer_c_agent_contributors,
        "aggregate_layer_c_results",
        lambda fused_scores, analyst_signals: [
            SimpleNamespace(
                ticker="300001",
                score_b=0.4,
                score_c=0.3,
                score_final=0.5,
                decision="watch",
                bc_conflict=None,
                agent_contribution_summary={"top_negative_agents": ["alpha"]},
            )
        ],
    )
    monkeypatch.setattr(
        replay_layer_c_agent_contributors,
        "_write_payload",
        lambda path, payload: writes.append({"path": path, "payload": payload}),
    )

    exit_code = replay_layer_c_agent_contributors.main()

    assert exit_code == 0
    assert runner_calls == [(["300001"], "20260202", "fast")]
    assert len(writes) == 3
    assert writes[0]["path"] == output_path
    assert writes[0]["payload"]["partial"] is True
    assert writes[1]["payload"]["partial"] is True
    assert writes[2]["payload"]["partial"] is False
    assert writes[2]["payload"]["model"] == {"model_name": "resolved-model", "model_provider": "resolved-provider"}
    assert writes[2]["payload"]["dates"] == ["20260202"]
    assert writes[2]["payload"]["comparisons"][0]["ticker"] == "300001"

    stdout = capsys.readouterr().out
    assert f"saved_partial_json: {output_path} completed_keys=1" in stdout
    assert f"saved_partial_json: {output_path} completed_dates=['20260202']" in stdout
    assert f"saved_json: {output_path}" in stdout
    assert "20260202 variant_a 300001 logged_score_c=0.1000 replay_score_c=0.3000" in stdout
    assert "top_negative_agents=['alpha']" in stdout
