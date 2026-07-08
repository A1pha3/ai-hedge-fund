from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _FakeRefreshStats:
    price_total: int = 3
    price_updated: int = 2
    fund_flow_total: int = 3
    fund_flow_saved: int = 1

    def to_dict(self) -> dict:
        return {
            "price_total": self.price_total,
            "price_updated": self.price_updated,
            "fund_flow_total": self.fund_flow_total,
            "fund_flow_saved": self.fund_flow_saved,
        }


def test_refresh_daily_action_caches_for_auto_attaches_summary_and_persists(monkeypatch):
    from src import main as main_mod

    saved: list[tuple[str, dict]] = []
    payload = {"date": "20260708", "recommendations": []}

    monkeypatch.delenv("DAILY_ACTION_CACHE_REFRESH", raising=False)
    monkeypatch.setattr(main_mod, "_save_json_report", lambda filename, body: saved.append((filename, dict(body))))

    main_mod._refresh_daily_action_caches_for_auto(
        "20260708",
        payload,
        refresh_fn=lambda trade_date: _FakeRefreshStats(),
    )

    assert payload["daily_action_cache_refresh"] == {
        "price_total": 3,
        "price_updated": 2,
        "fund_flow_total": 3,
        "fund_flow_saved": 1,
    }
    assert saved == [("auto_screening_20260708.json", payload)]


def test_refresh_daily_action_caches_for_auto_respects_env_kill_switch(monkeypatch):
    from src import main as main_mod

    called = False
    payload = {"date": "20260708", "recommendations": []}

    def refresh_fn(_trade_date: str):
        nonlocal called
        called = True
        return _FakeRefreshStats()

    monkeypatch.setenv("DAILY_ACTION_CACHE_REFRESH", "false")
    monkeypatch.setattr(main_mod, "_save_json_report", lambda *_args, **_kwargs: None)

    main_mod._refresh_daily_action_caches_for_auto("20260708", payload, refresh_fn=refresh_fn)

    assert called is False
    assert "daily_action_cache_refresh" not in payload
