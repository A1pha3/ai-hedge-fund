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


def test_attach_freshness_check_adds_data_freshness_field(monkeypatch):
    """_attach_freshness_check should attach data_freshness to report_payload."""
    from src import main as main_mod

    payload: dict = {"date": "20260708", "recommendations": []}

    def fake_check(*, trade_date: str, **kwargs) -> dict:
        assert trade_date == "20260708"
        return {
            "fresh": True,
            "trade_date": "20260708",
            "warnings": [],
            "warning_count": 0,
            "summary": "全部数据源新鲜",
        }

    monkeypatch.setattr("src.screening.data_freshness_guard.check_data_freshness", fake_check)

    main_mod._attach_freshness_check("20260708", payload)
    assert "data_freshness" in payload
    assert payload["data_freshness"]["fresh"] is True


def test_attach_freshness_check_handles_exception_gracefully(monkeypatch):
    """If check_data_freshness raises, _attach_freshness_check should not crash."""
    from src import main as main_mod

    payload: dict = {"date": "20260708", "recommendations": []}

    def fake_check(*, trade_date: str, **kwargs) -> dict:
        raise RuntimeError("cache unreachable")

    monkeypatch.setattr("src.screening.data_freshness_guard.check_data_freshness", fake_check)

    main_mod._attach_freshness_check("20260708", payload)
    assert "data_freshness" not in payload  # no field on failure


def test_attach_freshness_check_stale_data_prints_warning(monkeypatch, capsys):
    """If data is stale, _attach_freshness_check prints a warning line (not fatal)."""
    from src import main as main_mod

    payload: dict = {"date": "20260708", "recommendations": []}

    def fake_check(*, trade_date: str, **kwargs) -> dict:
        return {
            "fresh": False,
            "trade_date": "20260708",
            "warnings": [{"source": "fund_flow", "label": "资金流向", "latest_date": "20260701", "stale_days": 7, "max_stale_days": 3, "severity": "HIGH", "message": "资金流数据 7 天未更新"}],
            "warning_count": 1,
            "summary": "资金流向: 7 天未更新",
        }

    monkeypatch.setattr("src.screening.data_freshness_guard.check_data_freshness", fake_check)

    main_mod._attach_freshness_check("20260708", payload)
    captured = capsys.readouterr()
    assert "资金流向" in captured.out
