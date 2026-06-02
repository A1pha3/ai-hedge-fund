from __future__ import annotations

import json
import sys

from scripts.generate_btst_next_day_trade_brief import main


def test_generate_btst_next_day_trade_brief_cli_infers_next_trade_date(tmp_path, monkeypatch):
    report_dir = tmp_path / "paper_trading_2026-03-27_2026-03-27_dummy"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-27"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260327",
                "target_mode": "short_trade_only",
                "selection_targets": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_btst_next_day_trade_brief.py",
            str(report_dir),
            "--output-dir",
            str(output_dir),
        ],
    )

    main()

    output_path = output_dir / "btst_next_day_trade_brief_20260327_for_20260330.json"
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload.get("trade_date") == "2026-03-27"
    assert payload.get("next_trade_date") == "2026-03-30"
