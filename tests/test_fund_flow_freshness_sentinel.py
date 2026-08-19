"""fund_flow 缓存新鲜度哨点回归 — trap 20 运营覆盖层自身的检测网.

背景 (2026-08-19): fund_flow_freshness_sentinel (6a37f3db) 上线时零测试覆盖,
而同族哨点 (court_asset_sentinel / prior_check 接线) 均有回归网 — 运营覆盖
层的静默回归只能靠生产日志事后发现, 与『缺口当天可见』的设计目标矛盾。

本回归网锁定:
1. _latest_date 纯函数边界: 正常/缺文件/空文件/仅头行, 两种日期格式;
2. scan_stale 日历口径: lag=1 不告警 (非交易日/未开市正常态), lag=2 告警,
   flow 领先不告警, 完全缺失单列;
3. CLI advisory 语义: 告警不改 rc (恒 0), 目录缺失 rc=1;
4. daemon 接线: _run_advisory_sentinels 调用序列含本哨点。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "fund_flow_freshness_sentinel.py"
PIPELINE = REPO / "scripts" / "run_daily_pipeline.py"


def _load_sentinel():
    spec = importlib.util.spec_from_file_location("fund_flow_sentinel_for_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------- _latest_date 纯函数边界 ----------


def test_latest_date_normal_iso_format(tmp_path):
    sentinel = _load_sentinel()
    fp = tmp_path / "600000.csv"
    fp.write_text("date,close\n2026-08-15,10.0\n2026-08-18,10.5\n", encoding="utf-8")
    assert sentinel._latest_date(fp) == "20260818"


def test_latest_date_compact_format(tmp_path):
    sentinel = _load_sentinel()
    fp = tmp_path / "600000.csv"
    fp.write_text("trade_date,close\n20260815,10.0\n20260818,10.5\n", encoding="utf-8")
    assert sentinel._latest_date(fp) == "20260818"


def test_latest_date_missing_file(tmp_path):
    sentinel = _load_sentinel()
    assert sentinel._latest_date(tmp_path / "nope.csv") is None


def test_latest_date_empty_or_header_only(tmp_path):
    sentinel = _load_sentinel()
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    header_only = tmp_path / "header.csv"
    header_only.write_text("date,close\n", encoding="utf-8")
    blank_tail = tmp_path / "blank_tail.csv"
    blank_tail.write_text("date,close\n2026-08-18,10.5\n\n", encoding="utf-8")
    assert sentinel._latest_date(empty) is None
    assert sentinel._latest_date(header_only) is None
    # 尾部空行不算数据行, 仍取最后一个非空行
    assert sentinel._latest_date(blank_tail) == "20260818"


# ---------- scan_stale 日历口径 ----------


def _make_cache(tmp_path: Path, price_rows: dict[str, str], flow_rows: dict[str, str]):
    price_dir = tmp_path / "price_cache"
    flow_dir = tmp_path / "fund_flow_cache"
    price_dir.mkdir()
    flow_dir.mkdir()
    for ticker, last in price_rows.items():
        (price_dir / f"{ticker}.csv").write_text(
            f"date,close\n2026-08-11,1.0\n{last},2.0\n", encoding="utf-8")
    for ticker, last in flow_rows.items():
        (flow_dir / f"{ticker}.csv").write_text(
            f"date,main\n2026-08-11,1.0\n{last},2.0\n", encoding="utf-8")
    return price_dir, flow_dir


_TDAYS = {"20260811", "20260812", "20260813", "20260814", "20260817", "20260818"}


def test_scan_stale_lag1_is_fresh(tmp_path):
    """落后 1 个交易日 = 正常态 (当日未开市/非交易日), 不告警."""
    sentinel = _load_sentinel()
    price_dir, flow_dir = _make_cache(
        tmp_path, {"600000": "2026-08-14"}, {"600000": "2026-08-13"})
    checked, stale, missing = sentinel.scan_stale(price_dir, flow_dir, _TDAYS,
                                                  sentinel._STALE_THRESHOLD_DAYS)
    assert checked == 1 and stale == [] and missing == []


def test_scan_stale_lag2_warns(tmp_path):
    """落后 ≥2 个交易日 = 告警, lag 按 (flow_latest, price_latest] 内交易日计."""
    sentinel = _load_sentinel()
    price_dir, flow_dir = _make_cache(
        tmp_path, {"600000": "2026-08-18"}, {"600000": "2026-08-14"})
    checked, stale, missing = sentinel.scan_stale(price_dir, flow_dir, _TDAYS,
                                                  sentinel._STALE_THRESHOLD_DAYS)
    assert checked == 1
    # (20260814, 20260818] 内交易日 = {20260817, 20260818} → lag=2
    assert stale == [("600000", 2)]
    assert missing == []


def test_scan_stale_flow_ahead_is_fresh(tmp_path):
    """flow 领先 price (价格刷新失败日) 不告警 — 哨点只管 flow 落后."""
    sentinel = _load_sentinel()
    price_dir, flow_dir = _make_cache(
        tmp_path, {"600000": "2026-08-13"}, {"600000": "2026-08-18"})
    checked, stale, missing = sentinel.scan_stale(price_dir, flow_dir, _TDAYS,
                                                  sentinel._STALE_THRESHOLD_DAYS)
    assert checked == 1 and stale == [] and missing == []


def test_scan_stale_missing_flow_file_listed(tmp_path):
    """价格缓存存在但资金流文件完全缺失 → 单列 missing."""
    sentinel = _load_sentinel()
    price_dir, flow_dir = _make_cache(tmp_path, {"600000": "2026-08-18"}, {})
    checked, stale, missing = sentinel.scan_stale(price_dir, flow_dir, _TDAYS,
                                                  sentinel._STALE_THRESHOLD_DAYS)
    assert checked == 1 and stale == [] and missing == ["600000"]


def test_scan_stale_price_only_empty_skipped(tmp_path):
    """价格缓存仅头行 (无最新日期) 的票不计入 checked — 无从判定落后."""
    sentinel = _load_sentinel()
    price_dir, flow_dir = _make_cache(tmp_path, {}, {})
    (price_dir / "688888.csv").write_text("date,close\n", encoding="utf-8")
    checked, stale, missing = sentinel.scan_stale(price_dir, flow_dir, _TDAYS,
                                                  sentinel._STALE_THRESHOLD_DAYS)
    assert checked == 0 and stale == [] and missing == []


# ---------- CLI advisory 语义 ----------


def test_main_healthy_rc0(capsys, monkeypatch, tmp_path):
    sentinel = _load_sentinel()
    price_dir, flow_dir = _make_cache(
        tmp_path, {"600000": "2026-08-18"}, {"600000": "2026-08-18"})
    monkeypatch.setattr(sentinel, "PRICE_DIR", price_dir)
    monkeypatch.setattr(sentinel, "FLOW_DIR", flow_dir)
    monkeypatch.setattr(
        sentinel, "CAL_PATH", tmp_path / "cal.json")
    (tmp_path / "cal.json").write_text(
        "[\"20260811\",\"20260818\"]", encoding="utf-8")
    assert sentinel.main() == 0
    out = capsys.readouterr().out
    assert "[fund_flow_sentinel]" in out and "OK" in out


def test_main_stale_warning_still_rc0(capsys, monkeypatch, tmp_path):
    """advisory 语义: 有 stale/missing 告警时 exit 仍为 0, 绝不阻塞管道."""
    sentinel = _load_sentinel()
    price_dir, flow_dir = _make_cache(
        tmp_path, {"600000": "2026-08-18", "000001": "2026-08-18"},
        {"600000": "2026-08-14"})  # 000001 完全缺失
    monkeypatch.setattr(sentinel, "PRICE_DIR", price_dir)
    monkeypatch.setattr(sentinel, "FLOW_DIR", flow_dir)
    monkeypatch.setattr(
        sentinel, "CAL_PATH", tmp_path / "cal.json")
    (tmp_path / "cal.json").write_text(
        "[\"20260811\",\"20260814\",\"20260817\",\"20260818\"]",
        encoding="utf-8")
    assert sentinel.main() == 0
    out = capsys.readouterr().out
    assert "1 只票完全无资金流缓存" in out
    assert "落后" in out
    assert "backfill_fund_flow_cache" in out  # 修复指引必须可见


def test_main_missing_dirs_rc1(capsys, monkeypatch, tmp_path):
    sentinel = _load_sentinel()
    monkeypatch.setattr(sentinel, "PRICE_DIR", tmp_path / "nope")
    monkeypatch.setattr(
        sentinel, "CAL_PATH", tmp_path / "cal.json")
    assert sentinel.main() == 1


# ---------- daemon 接线 ----------


def test_advisory_sentinels_include_fund_flow_freshness(monkeypatch):
    """_run_advisory_sentinels 调用序列必须含 fund_flow_freshness_sentinel.py."""
    spec = importlib.util.spec_from_file_location(
        "run_daily_pipeline_for_ff_test", PIPELINE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    calls: list[list[str]] = []

    def fake_call(argv, **_kw):
        calls.append([str(a) for a in argv])
        return 0

    monkeypatch.setattr(module.subprocess, "call", fake_call)

    class _NullLog:
        def write(self, *_a, **_k):
            pass

        def flush(self):
            pass

    module._run_advisory_sentinels(_NullLog())
    joined = [" ".join(c) for c in calls]
    assert any("fund_flow_freshness_sentinel.py" in c for c in joined), joined
