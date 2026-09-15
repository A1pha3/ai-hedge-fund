"""flow_backfill 自愈阶段回归 — R232 Op1: 哨兵 detection-only 结构病的闭环面.

背景 (R232 Observe 实录): 停牌票掉出 auto_screening 候选集后复牌日资金流行
无人补 (逐票刷新只覆盖最新候选 ~30 只), 哨兵每夜轮换报警而修复命令无人执行 —
缺口期 BTST 条件 2 用退化均值判定 (哨兵 docstring 实例: 300684 被失真均值判
BLOCK)。本回归网锁定:

1. derive_backfill_plan 纯函数: 单票窗 / 多票并集 / 空集 no-op / 窗口超上限
   类型化拒绝 / 畸形记录拒绝 (结构性缺口属人工决策, 编排器绝不擅自大窗自愈);
2. CLI 契约: 默认 dry-run 零写入 / --execute 才调回填 / typed JSON 输出
   (typed_code 的 ``"code": "..."`` grep 契约) / refusal rc=2 / backfill
   失败 rc=1 / 复扫披露;
3. 夜链接线: research_data_refresh.sh 的 flow_backfill 阶段位于 bars 之后
   court 之前 (bars 供给最新价格缓存算 lag, court 消费修复后的资金流)。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "flow_backfill_remediate.py"
REFRESH_SH = REPO / "scripts" / "research_data_refresh.sh"

TDAYS = [f"202609{d:02d}" for d in range(1, 31)]  # 20260901..20260930 全交易月


def _load_module():
    spec = importlib.util.spec_from_file_location("flow_backfill_remediate_for_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _gap(ticker: str, flow_latest: str, price_latest: str):
    mod = _load_module()
    return mod.FlowGap(ticker=ticker, flow_latest=flow_latest, price_latest=price_latest)


def _write_flow_csv(directory: Path, ticker: str, last_date: str) -> None:
    (directory / f"{ticker}.csv").write_text(
        f"date,close\n{last_date[:4]}-{last_date[4:6]}-{last_date[6:]},10.0\n",
        encoding="utf-8",
    )


def _write_price_csv(directory: Path, ticker: str, last_date: str) -> None:
    (directory / f"{ticker}.csv").write_text(
        f"date,close\n{last_date[:4]}-{last_date[4:6]}-{last_date[6:]},10.0\n",
        encoding="utf-8",
    )


def _run_cli(args, monkeypatch, backfill_recorder=None):
    """跑 CLI 主函数, 返回 (rc, envelope)。backfill_recorder 非 None 时替换子进程。"""
    mod = _load_module()
    recorded = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        recorded["cmd"] = cmd
        if backfill_recorder is not None:
            backfill_recorder(cmd)

        class _P:  # noqa: N801
            returncode = 0
            stdout = ""
            stderr = ""

        return _P()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    import contextlib
    import io

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = mod.main(args)
    envelope = json.loads(stdout.getvalue())
    return rc, envelope, recorded, mod


# ---------- derive_backfill_plan 纯函数 ----------


def test_plan_single_gap_window_bounds():
    mod = _load_module()
    gaps = [_gap("002870", "20260831", "20260915")]
    plan = mod.derive_backfill_plan(gaps, TDAYS, max_window_trading_days=30)
    assert plan.window_start == "20260901"
    assert plan.window_end == "20260915"
    assert plan.trading_days == tuple(TDAYS[0:15])
    assert plan.tickers == ("002870",)


def test_plan_multi_gap_union_min_max():
    mod = _load_module()
    gaps = [
        _gap("002870", "20260831", "20260915"),
        _gap("600929", "20260826", "20260920"),
    ]
    plan = mod.derive_backfill_plan(gaps, TDAYS, max_window_trading_days=30)
    assert plan.window_start == "20260901"
    assert plan.window_end == "20260920"
    assert plan.tickers == ("002870", "600929")


def test_plan_empty_gaps_returns_none():
    mod = _load_module()
    assert mod.derive_backfill_plan([], TDAYS, max_window_trading_days=30) is None


def test_plan_window_over_cap_typed_refusal():
    mod = _load_module()
    gaps = [_gap("002870", "20260901", "20260930")]  # 29 交易日 > 上限 5
    with pytest.raises(mod.BackfillPlanRefused) as excinfo:
        mod.derive_backfill_plan(gaps, TDAYS, max_window_trading_days=5)
    assert excinfo.value.code == "plan_window_exceeds_cap"


def test_plan_malformed_record_refused():
    mod = _load_module()
    for bad in (
        _gap("002870", "20260831-1", "20260915"),  # 非 8 位数字
        _gap("002870", "20260915", "20260915"),    # price <= flow (非落后)
        _gap("", "20260831", "20260915"),          # 空 ticker
    ):
        with pytest.raises(mod.BackfillPlanRefused) as excinfo:
            mod.derive_backfill_plan([bad], TDAYS, max_window_trading_days=30)
        assert excinfo.value.code == "gap_record_invalid"


# ---------- CLI 契约 ----------


def _fixture_world(tmp_path):
    price = tmp_path / "price_cache"
    flow = tmp_path / "fund_flow_cache"
    price.mkdir()
    flow.mkdir()
    cal = tmp_path / "trade_calendar.json"
    cal.write_text(json.dumps(TDAYS), encoding="utf-8")
    return price, flow, cal


def test_cli_dry_run_zero_write_and_plan(tmp_path, monkeypatch):
    price, flow, cal = _fixture_world(tmp_path)
    _write_price_csv(price, "002870", "20260915")
    _write_flow_csv(flow, "002870", "20260831")
    before = sorted(p.read_bytes() for p in flow.iterdir())
    rc, env, recorded, _mod = _run_cli(
        [
            "--price-dir", str(price), "--flow-dir", str(flow),
            "--calendar", str(cal), "--backfill-script", "NOPE.py",
        ],
        monkeypatch,
    )
    assert rc == 0
    assert env["ok"] is True
    assert env["mode"] == "dry_run"
    assert env["plan"]["window_start"] == "20260901"
    assert env["plan"]["window_end"] == "20260915"
    assert "cmd" not in recorded  # dry-run 绝不调回填
    after = sorted(p.read_bytes() for p in flow.iterdir())
    assert after == before  # 零写入


def test_cli_execute_invokes_backfill_and_rescans(tmp_path, monkeypatch):
    price, flow, cal = _fixture_world(tmp_path)
    _write_price_csv(price, "002870", "20260915")
    _write_flow_csv(flow, "002870", "20260831")
    calls = []

    def recorder(cmd):
        calls.append(cmd)
        # 模拟回填生效: 补上 flow 缺口日
        _write_flow_csv(flow, "002870", "20260915")

    rc, env, recorded, _mod = _run_cli(
        [
            "--execute",
            "--price-dir", str(price), "--flow-dir", str(flow),
            "--calendar", str(cal), "--backfill-script", "fake_backfill.py",
        ],
        monkeypatch,
        backfill_recorder=recorder,
    )
    assert rc == 0
    assert env["ok"] is True
    assert env["mode"] == "executed"
    assert calls and calls[0][-4:] == ["--start", "20260901", "--end", "20260915"]
    assert env["after"]["stale"] == []


def test_cli_noop_when_fresh(tmp_path, monkeypatch):
    price, flow, cal = _fixture_world(tmp_path)
    _write_price_csv(price, "002870", "20260915")
    _write_flow_csv(flow, "002870", "20260915")
    rc, env, recorded, _mod = _run_cli(
        [
            "--execute",
            "--price-dir", str(price), "--flow-dir", str(flow),
            "--calendar", str(cal),
        ],
        monkeypatch,
    )
    assert rc == 0
    assert env["mode"] == "noop"
    assert "cmd" not in recorded


def test_cli_refusal_exit_2_and_typed_code(tmp_path, monkeypatch):
    price, flow, cal = _fixture_world(tmp_path)
    _write_price_csv(price, "002870", "20260930")
    _write_flow_csv(flow, "002870", "20260901")  # 29 交易日, 上限 5
    rc, env, recorded, _mod = _run_cli(
        [
            "--execute", "--max-window-days", "5",
            "--price-dir", str(price), "--flow-dir", str(flow),
            "--calendar", str(cal),
        ],
        monkeypatch,
    )
    assert rc == 2
    assert env["ok"] is False
    assert env["code"] == "plan_window_exceeds_cap"
    assert "cmd" not in recorded


def test_cli_backfill_failure_exit_1(tmp_path, monkeypatch):
    price, flow, cal = _fixture_world(tmp_path)
    _write_price_csv(price, "002870", "20260915")
    _write_flow_csv(flow, "002870", "20260831")
    mod = _load_module()

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        class _P:  # noqa: N801
            returncode = 1
            stdout = ""
            stderr = "simulated backfill failure"

        return _P()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    import contextlib
    import io

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = mod.main([
            "--execute",
            "--price-dir", str(price), "--flow-dir", str(flow),
            "--calendar", str(cal),
        ])
    env = json.loads(stdout.getvalue())
    assert rc == 1
    assert env["ok"] is False
    assert env["code"] == "backfill_failed"


def test_cli_calendar_missing_typed(tmp_path, monkeypatch):
    price, flow, cal = _fixture_world(tmp_path)
    cal.unlink()
    rc, env, _recorded, _mod = _run_cli(
        [
            "--price-dir", str(price), "--flow-dir", str(flow),
            "--calendar", str(cal),
        ],
        monkeypatch,
    )
    assert rc == 2
    assert env["ok"] is False
    assert env["code"] == "calendar_unavailable"


# ---------- 夜链接线 ----------


def test_refresh_stage_order_and_wiring():
    text = REFRESH_SH.read_text(encoding="utf-8")
    bars_pos = text.index('record "bars"')
    flow_pos = text.index('record "flow_backfill"')
    court_pos = text.index('record "court_build"')
    assert bars_pos < flow_pos < court_pos, "flow_backfill 必须在 bars 之后 court 之前"
    assert "--execute" in text, "夜链阶段必须显式 --execute (默认 dry-run 是人工面契约)"
    assert 'record "flow_backfill" "$rc"' in text, "失败必须记 typed code 进 history"
