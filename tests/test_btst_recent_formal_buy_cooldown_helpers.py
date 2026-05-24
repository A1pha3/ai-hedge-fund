from __future__ import annotations

import json

from scripts.btst_latest_followup_utils import load_recent_btst_buy_order_cooldowns


def _write_selection_snapshot(root, report_name: str, trade_date: str, tickers: list[str]) -> None:
    selection_dir = root / report_name / "selection_artifacts" / trade_date
    selection_dir.mkdir(parents=True, exist_ok=True)
    (selection_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": trade_date,
                "buy_orders": [{"ticker": ticker} for ticker in tickers],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_load_recent_btst_buy_order_cooldowns_blocks_recent_formal_buy(tmp_path) -> None:
    _write_selection_snapshot(tmp_path, "paper_trading_2026-03-08_2026-03-08_live_m2_7_short_trade_only_plan", "2026-03-08", ["300724"])

    blocked = load_recent_btst_buy_order_cooldowns(tmp_path, trade_date="2026-03-10")

    assert blocked == {
        "300724": {
            "trigger_reason": "recent_formal_buy_cooldown",
            "exit_trade_date": "20260308",
            "blocked_until": "20260311",
        }
    }


def test_load_recent_btst_buy_order_cooldowns_ignores_old_snapshot(tmp_path) -> None:
    _write_selection_snapshot(tmp_path, "paper_trading_2026-03-05_2026-03-05_live_m2_7_short_trade_only_plan", "2026-03-05", ["300724"])

    blocked = load_recent_btst_buy_order_cooldowns(tmp_path, trade_date="2026-03-10")

    assert blocked == {}
