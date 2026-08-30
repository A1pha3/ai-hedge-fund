"""研究数据面统一日更契约 (R58 数据新鲜度工作线)。

覆盖三件交付物 (hermetic: 注入 fetch_fn / stub 解释器, 零网络、零生产数据):
- scripts/fetch_lhb_daily.py — 龙虎榜续传: 幂等 (已存在日零 API)、
  空返回日落表头空文件且续传越过、失败类型化绝不 except:pass 静默
  (旧 _ensure_lhb_backfill 静默死亡 53 天的根因收口)。
- scripts/research_freshness.py — 只读新鲜度仪表: 五数据集 latest vs
  权威日历期望会话; session 语义 (bars/lhb 文件名精确) 与 bulk 语义
  (mtime 日期) 分流; 日历缺失/过期类型化拒绝 (R57 同款)。
- scripts/research_data_refresh.sh — 18:30 驱动器: bars→lhb→freshness
  三阶段, 单阶段失败不中止后续, rc=失败阶段数, preflight 失败 97,
  阶段 JSONL 记录。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from fetch_lhb_daily import (  # noqa: E402
    LhbFetchError,
    expected_session,
    load_calendar_sessions,
    run_fetch,
)
from research_freshness import check_freshness  # noqa: E402

REFRESH = SCRIPTS / "research_data_refresh.sh"
TIMEOUT_S = 30
CAL = ["20260101", "20260102", "20260103", "20260105"]


def _write_calendar(repo: Path, sessions: list[str]) -> Path:
    path = repo / "calendar.json"
    path.write_text(json.dumps(sessions), encoding="utf-8")
    return path


def _lhb_frame(session: str) -> pd.DataFrame:
    return pd.DataFrame([
        {"trade_date": session, "ts_code": "000001.SZ", "exalter": "x",
         "buy": 1.0, "buy_rate": 1.0, "sell": 0.0, "sell_rate": 0.0,
         "net_buy": 1.0, "side": 0, "reason": "r"},
    ])


# ---- fetch_lhb_daily: 期望会话 ----


def test_expected_session_picks_last_completed_before_today(tmp_path: Path) -> None:
    cal = _write_calendar(tmp_path, CAL)
    # T-1 语义 (严格 < today): 交易日今日的期望是昨日已完成会话
    assert expected_session(cal, "20260105") == "20260103"
    assert expected_session(cal, "20260104") == "20260103"  # 非交易日同样回退
    assert expected_session(cal, "20260102") == "20260101"


def test_expected_session_rejects_missing_or_stale_calendar(tmp_path: Path) -> None:
    with pytest.raises(LhbFetchError) as ei:
        expected_session(tmp_path / "absent.json", "20260105")
    assert ei.value.code == "calendar_not_found"
    cal = _write_calendar(tmp_path, ["20251231"])
    with pytest.raises(LhbFetchError) as ei2:
        expected_session(cal, "20260105")
    assert ei2.value.code == "calendar_stale"


def test_load_calendar_rejects_malformed(tmp_path: Path) -> None:
    bad = tmp_path / "cal.json"
    bad.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(LhbFetchError) as ei:
        load_calendar_sessions(bad)
    assert ei.value.code == "calendar_malformed"


# ---- fetch_lhb_daily: 续传主循环 ----


def test_run_fetch_catches_up_idempotent_and_empty_days(tmp_path: Path) -> None:
    cal = _write_calendar(tmp_path, CAL)
    cache = tmp_path / "lhb_cache"
    cache.mkdir()
    (cache / "20260101.csv").write_text("existing\n", encoding="utf-8")

    calls: list[str] = []

    def fetch_fn(session: str):
        calls.append(session)
        if session == "20260103":
            return None  # 空榜日 (API 合法空返回)
        return _lhb_frame(session)

    summary = run_fetch(cache_dir=cache, calendar_path=cal, today="20260105",
                        fetch_fn=fetch_fn, rate_sleep=0)
    # 期望会话 = T-1 (20260103); 只补缺口 02/03; 已存在 01 零调用; 05 超出期望不拉
    assert calls == ["20260102", "20260103"]
    assert summary["fetched"] == ["20260102"]
    assert summary["empty_days"] == ["20260103"]
    # 空榜日 = 表头空文件 (已尝试标记), 续传窗口越过了它 (05 已拉)
    assert (cache / "20260103.csv").read_text().startswith("trade_date,ts_code")
    assert len(_lhb_frame("x")) == 1  # sanity: 非空日有数据行

    # 幂等重放: 全部已缓存 → 零新调用
    calls.clear()
    run_fetch(cache_dir=cache, calendar_path=cal, today="20260105",
              fetch_fn=fetch_fn, rate_sleep=0)
    assert calls == []


def test_run_fetch_types_api_failure_never_silent(tmp_path: Path) -> None:
    cal = _write_calendar(tmp_path, CAL)
    cache = tmp_path / "lhb_cache"
    cache.mkdir()

    def fetch_fn(session: str):
        raise RuntimeError("rate limit exhausted")

    with pytest.raises(LhbFetchError) as ei:
        run_fetch(cache_dir=cache, calendar_path=cal, today="20260103",
                  fetch_fn=fetch_fn, rate_sleep=0)
    assert ei.value.code == "lhb_api_failed"
    assert ei.value.details["session"] == "20260101"  # 空缓存 → 首个缺口即日历首日


def test_run_fetch_rejects_bad_today(tmp_path: Path) -> None:
    cal = _write_calendar(tmp_path, CAL)
    with pytest.raises(LhbFetchError) as ei:
        run_fetch(cache_dir=tmp_path, calendar_path=cal, today="2026-01-05",
                  fetch_fn=lambda s: None, rate_sleep=0)
    assert ei.value.code == "invalid_today"


# ---- research_freshness: 仪表 ----


def _build_world(repo: Path, *, with_lhb: bool) -> Path:
    (repo / "data/research/btst_court/raw/daily").mkdir(parents=True)
    (repo / "data/research/btst_court/raw/daily/daily_20260105.csv").write_text("x\n")
    if with_lhb:
        (repo / "data/lhb_cache").mkdir(parents=True)
        (repo / "data/lhb_cache/20260105.csv").write_text("trade_date,ts_code\n")
    court_dir = repo / "data/research/btst_court/event_tables"
    court_dir.mkdir(parents=True)
    pd.DataFrame({"signal_date": ["20260105"]}).to_csv(
        court_dir / "event_table_v1.csv.gz", index=False, compression="gzip")
    for bulk in ("price_cache", "fund_flow_cache", "industry_index_cache"):
        d = repo / "data" / bulk
        d.mkdir(parents=True)
        f = d / "sample.csv"
        f.write_text("x\n")
        # mtime 锚到 20260105 当日 (bulk 语义)
        stamp = time.mktime(time.strptime("20260105 19:00:00", "%Y%m%d %H:%M:%S"))
        os.utime(f, (stamp, stamp))
    court_dir = repo / "data/research/btst_court/event_tables"
    court_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"signal_date": ["20260105"]}).to_csv(
        court_dir / "event_table_v1.csv.gz", index=False, compression="gzip")
    # 日历须覆盖 today 之后 (否则 expected_session 判 calendar_stale — 真实日历
    # 前向覆盖数月, 周末 today > 上一会话是常态而非过期)
    return _write_calendar(repo, CAL + ["20260107"])


def test_freshness_all_fresh_rc_zero(tmp_path: Path) -> None:
    cal = _build_world(tmp_path, with_lhb=True)
    report = check_freshness(repo_root=tmp_path, calendar_path=cal, today="20260106")
    # T-1 语义: 0106 的期望会话 = 20260105 (今日之前的最近已完成)
    assert report["expected_session"] == "20260105"
    assert all(not r["stale"] for r in report["datasets"])
    assert len(report["datasets"]) == 6


def test_freshness_missing_lhb_is_loud(tmp_path: Path) -> None:
    cal = _build_world(tmp_path, with_lhb=False)
    report = check_freshness(repo_root=tmp_path, calendar_path=cal, today="20260106")
    stale = [r for r in report["datasets"] if r["stale"]]
    assert [r["dataset"] for r in stale] == ["lhb"]
    assert report["datasets"][1]["latest"] is None


def test_freshness_rejects_uncovered_calendar(tmp_path: Path) -> None:
    cal = _write_calendar(tmp_path, ["20251231"])  # max < today → 过期响亮
    with pytest.raises(LhbFetchError) as ei:
        check_freshness(repo_root=tmp_path, calendar_path=cal, today="20260105")
    assert ei.value.code == "calendar_stale"


# ---- research_data_refresh.sh: 18:30 驱动器 (stub 解释器, hermetic) ----


def _stage_stub_py(fake_repo: Path, fail_stage: str, fail_rc: int,
                   fail_stdout: str) -> str:
    log = fake_repo / "stub_invocations.jsonl"
    return _write_stub_simple(
        fake_repo / "stub_py",
        f'#!/bin/bash\n'
        f'if [ "${{1:-}}" = "-c" ]; then [ "${{V3R_PREFLIGHT_FAIL:-0}}" = "1" ] '
        f'&& exit 7; exit 0; fi\n'
        f'printf \'%s\\n\' "$*" >> "{log}"\n'
        f'subject=" ${{1##*/}} "\n'
        f'case "$subject" in\n'
        f'  *" ${{V3R_FAIL_STAGE:-__none__}} "*) '
        f'[ -n "${{V3R_FAIL_STDOUT:-}}" ] && printf \'%s\\n\' "$V3R_FAIL_STDOUT"; '
        f'exit ${{V3R_FAIL_RC:-0}} ;;\n'
        f'  *) exit 0 ;;\n'
        f'esac\n'
        f'exit 0\n',
    )


def _write_stub_simple(path: Path, body: str) -> str:
    path.write_text(body)
    path.chmod(0o755)
    return str(path)


def _run_refresh(fake_repo: Path, *extra_env: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("V3R_")]:
        env.pop(key)
    env.update({
        "V3R_REPO": str(fake_repo),
        "V3R_PY": str(fake_repo / "stub_py"),
        "V3R_BARS_FETCH": str(fake_repo / "bars_fetch_dummy"),
        "V3R_LHB_FETCH": str(fake_repo / "lhb_fetch_dummy"),
        "V3R_FRESHNESS": str(fake_repo / "freshness_dummy"),
        "V3R_COURT_BUILD": str(fake_repo / "court_build_dummy"),
        "V3R_HISTORY": str(fake_repo / "logs" / "cron" / "research_refresh_history.jsonl"),
        "V3R_TODAY": "20260105",
    })
    for patch in extra_env:
        env.update(patch)
    return subprocess.run(["bash", str(REFRESH)], cwd=str(fake_repo), env=env,
                          capture_output=True, text=True, timeout=TIMEOUT_S)


def _history(fake_repo: Path) -> list[dict]:
    path = fake_repo / "logs" / "cron" / "research_refresh_history.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


@pytest.fixture()
def refresh_repo(tmp_path: Path) -> Path:
    (tmp_path / "logs" / "cron").mkdir(parents=True)
    _stage_stub_py(tmp_path, fail_stage="__none__", fail_rc=0, fail_stdout="")
    return tmp_path


def test_refresh_all_stages_ok_in_order(refresh_repo: Path) -> None:
    proc = _run_refresh(refresh_repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    records = _history(refresh_repo)
    # R72: court 重建插入为第 3 阶段 (bars→lhb→court_build→freshness)
    assert [r["stage"] for r in records] == ["bars", "lhb", "court_build", "freshness"]
    assert all(r["rc"] == 0 for r in records)
    invocations = (refresh_repo / "stub_invocations.jsonl").read_text().splitlines()
    assert len(invocations) == 4
    assert invocations[1].startswith("lhb_fetch_dummy ") or "/lhb_fetch_dummy " in invocations[1]
    assert invocations[1].endswith("--today 20260105")
    assert "court_build_dummy" in invocations[2]
    assert "freshness_dummy" in invocations[3]


def test_refresh_stage_failure_recorded_without_aborting(refresh_repo: Path) -> None:
    # lhb 失败 (rc=3, typed code 转记): freshness 照常; 整体 rc=1
    proc = _run_refresh(refresh_repo, {
        "V3R_FAIL_STAGE": "lhb_fetch_dummy", "V3R_FAIL_RC": "3",
        "V3R_FAIL_STDOUT": '{"ok": false, "code": "lhb_api_failed"}',
    })
    assert proc.returncode == 1, proc.stdout + proc.stderr
    records = _history(refresh_repo)
    lhb = next(r for r in records if r["stage"] == "lhb")
    assert lhb["rc"] == 3
    assert lhb["detail"] == "lhb_api_failed"
    # R72: court_build 与 freshness 在 lhb 失败后照常执行
    assert [r["stage"] for r in records] == ["bars", "lhb", "court_build", "freshness"]


def test_refresh_preflight_failure_exits_97_zero_stages(refresh_repo: Path) -> None:
    proc = _run_refresh(refresh_repo, {"V3R_PREFLIGHT_FAIL": "1"})
    assert proc.returncode == 97
    records = _history(refresh_repo)
    assert len(records) == 1
    assert records[0]["detail"] == "interpreter_unavailable"
    assert not (refresh_repo / "stub_invocations.jsonl").exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---- R73: freshness court 数据集携带 regime 漂移状态 ----

def test_freshness_court_regime_drift_disclosed(tmp_path: Path) -> None:
    """无 manifest → checked=False 如实未知; 有 manifest+修订 → drift=True 响亮。"""
    cal = _build_world(tmp_path, with_lhb=True)
    report = check_freshness(repo_root=tmp_path, calendar_path=cal, today="20260106")
    court_row = [r for r in report["datasets"] if r["dataset"] == "court"][0]
    assert court_row["regime_drift"] == {"checked": False, "drift": False,
                                         "changed_sessions": []}

    manifest = (tmp_path / "data/research/btst_court/event_tables/manifest_v1.json")
    manifest.write_text(json.dumps({"regime_window": {"20260105": "crisis"}}),
                        encoding="utf-8")
    report = check_freshness(repo_root=tmp_path, calendar_path=cal,
                             today="20260106",
                             regime_history={"20260105": "normal"})
    court_row = [r for r in report["datasets"] if r["dataset"] == "court"][0]
    assert court_row["regime_drift"]["drift"] is True
    assert court_row["regime_drift"]["changed_sessions"] == [
        {"session": "20260105", "manifest": "crisis", "current": "normal"}]


# ---- R73 Op3: freshness 对损坏 manifest 降级不崩 (仪表可用性) ----

def test_freshness_court_corrupt_manifest_degrades_loud(tmp_path: Path, caplog) -> None:
    """manifest 损坏 JSON → 仪表正常输出, court 行 checked=False + WARNING (不裸崩)。"""
    import logging

    cal = _build_world(tmp_path, with_lhb=True)
    manifest = (tmp_path / "data/research/btst_court/event_tables/manifest_v1.json")
    manifest.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        report = check_freshness(repo_root=tmp_path, calendar_path=cal, today="20260106")
    court_row = [r for r in report["datasets"] if r["dataset"] == "court"][0]
    assert court_row["regime_drift"] == {"checked": False, "drift": False,
                                         "changed_sessions": []}
    assert any("manifest" in r.message for r in caplog.records)
