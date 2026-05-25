from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.analyze_btst_upstream_shadow_repeat_saturation import analyze_upstream_shadow_repeat_saturation


def test_analyze_upstream_shadow_repeat_saturation_flags_fn_to_fp_flip(tmp_path: Path) -> None:
    dossier_path = tmp_path / "fnfp.json"
    dossier_path.write_text(
        json.dumps(
            {
                "false_negative_rows": [
                    {"trade_date": "2026-03-27", "ticker": "300683", "score_target": 0.3883, "trend_acceleration": 0.7097, "close_strength": 0.8779},
                    {"trade_date": "2026-03-31", "ticker": "300683", "score_target": 0.3910, "trend_acceleration": 0.7543, "close_strength": 0.8775},
                ],
                "false_positive_rows": [
                    {"trade_date": "2026-04-06", "ticker": "300683", "score_target": 0.4183, "trend_acceleration": 0.7872, "close_strength": 0.8936},
                    {"trade_date": "2026-03-31", "ticker": "003036", "score_target": 0.4561, "trend_acceleration": 0.8578, "close_strength": 0.8802},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    analysis = analyze_upstream_shadow_repeat_saturation(dossier_path)

    assert analysis["focus_blocked_tickers"] == ["300683"]
    assert analysis["blocked_rows"][0]["ticker"] == "300683"
    assert analysis["blocked_rows"][0]["block_reason"] == "fn_to_fp_flip_after_repeat_shadow_hits"


def test_analyze_upstream_shadow_repeat_saturation_blocks_real_flip_tickers(tmp_path: Path) -> None:
    dossier_path = tmp_path / "fnfp.json"
    dossier_path.write_text(
        json.dumps(
            {
                "false_negative_rows": [
                    {"trade_date": "2026-03-27", "ticker": "300683"},
                    {"trade_date": "2026-03-30", "ticker": "300683"},
                    {"trade_date": "2026-03-23", "ticker": "003036"},
                    {"trade_date": "2026-03-27", "ticker": "003036"},
                ],
                "false_positive_rows": [
                    {"trade_date": "2026-04-06", "ticker": "300683"},
                    {"trade_date": "2026-04-07", "ticker": "300683"},
                    {"trade_date": "2026-03-31", "ticker": "003036"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    analysis = analyze_upstream_shadow_repeat_saturation(dossier_path)

    assert set(analysis["focus_blocked_tickers"]) == {"300683", "003036"}
    assert {row["ticker"] for row in analysis["blocked_rows"]} == {"300683", "003036"}
    assert {row["block_reason"] for row in analysis["blocked_rows"]} == {"fn_to_fp_flip_after_repeat_shadow_hits"}


def test_analyze_upstream_shadow_repeat_saturation_requires_repeated_false_negatives_before_flip(tmp_path: Path) -> None:
    dossier_path = tmp_path / "fnfp.json"
    dossier_path.write_text(
        json.dumps(
            {
                "false_negative_rows": [
                    {"trade_date": "2026-03-27", "ticker": "300683"},
                ],
                "false_positive_rows": [
                    {"trade_date": "2026-04-06", "ticker": "300683"},
                    {"trade_date": "2026-04-07", "ticker": "300683"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    analysis = analyze_upstream_shadow_repeat_saturation(dossier_path)

    assert analysis["focus_blocked_tickers"] == []
    assert analysis["blocked_rows"] == []


def test_analyze_upstream_shadow_repeat_saturation_cli_writes_output_json(tmp_path: Path) -> None:
    dossier_path = tmp_path / "fnfp.json"
    output_path = tmp_path / "artifacts" / "saturation.json"
    dossier_path.write_text(
        json.dumps(
            {
                "false_negative_rows": [
                    {"trade_date": "2026-03-27", "ticker": "300683"},
                    {"trade_date": "2026-03-30", "ticker": "300683"},
                ],
                "false_positive_rows": [
                    {"trade_date": "2026-04-06", "ticker": "300683"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_btst_upstream_shadow_repeat_saturation.py",
            "--dossier-json",
            str(dossier_path),
            "--output-json",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    stdout_payload = json.loads(completed.stdout)
    written_payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert stdout_payload == written_payload
    assert written_payload["dossier_path"] == str(dossier_path.resolve())
    assert written_payload["blocked_rows"][0]["block_reason"] == "fn_to_fp_flip_after_repeat_shadow_hits"
    assert written_payload["focus_blocked_tickers"] == ["300683"]
