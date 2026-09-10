"""regime_excess_return_decomposition — 净收益的 beta/selection 恒等分解 (R172 Op1).

工作线证据至今全部在净收益空间, 从未与市场基准对照; crisis 会话本质是市场
回撤期, 高动量候选天然高 beta。本工具把净收益恒等分解 net = bench + excess
(等权全市场 open→open 基准, 与 court 执行口径同窗), 回答: 优势多少是市场
beta, 多少是 selection (纯诊断, 宪法 #2 只披露不判定)。

钉死的正确性面:
- 基准算术: 已知合成世界逐值精确 (外部 oracle 独立复算, 不调用工具自身);
- 恒等分解: E_net = E_bench + E_excess 逐组 1e-12 精确 (无残差);
- 语义: 纯 beta 世界净对比非零而超额对比恰零 (gate 证据的机制归属判据);
- 窗口: T+1 精确对齐 + 顺延偏移 (exit_off>10) 走偏移会话 (构建器同款语义);
- 自检: 篡改 open / 删候选开盘 → typed fail-closed (窗口约定漂移防线);
- 守卫: MIN_PAIR_NAMES / 源会话缺失 / 信号日不在日历 / 偏移越界 / 空宇宙
  全 typed 拒绝;
- 渲染存活: 缺键 '—' 不崩 / falsy-zero 显示 (R158 家族);
- 确定性: 同输入两次 analyze 逐字节一致 (R13 家族)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.regime_excess_return_decomposition import (
    GROUP_ORDER,
    MIN_PAIR_NAMES,
    REPORT_STEM,
    analyze,
    horizon_rows_with_benchmark,
    main,
    render_md,
)
from scripts.regime_blocked_run_conditioning import run_groups
from scripts.regime_proximity_conditioning import load_regime_history
from scripts.winrate_payoff_decomposition import (
    ROUNDTRIP_COST,
    production_aligned,
)

SESSIONS = [f"202601{d:02d}" for d in range(1, 31)]  # 30 会话 = CLI 日历下界
SESSIONS += [f"202602{d:02d}" for d in range(1, 7)]
BLIP_DAY, RUN_DAY = "20260106", "20260103"
MARKET = [f"M{i:03d}" for i in range(MIN_PAIR_NAMES + 20)]  # ≥ MIN_PAIR_NAMES
N_CAND = 40
BLIP = [f"B{i:03d}" for i in range(N_CAND)]
RUN = [f"R{i:03d}" for i in range(N_CAND)]
REGIMES = {
    "20260101": "crisis",
    "20260102": "crisis",   # run=2 → 0103 是 d1_run
    "20260103": "normal",
    "20260104": "normal",
    "20260105": "risk_off",  # 单日闪断 → 0106 是 d1_blip
    **{f"202601{d:02d}": "normal" for d in range(6, 31)},
    **{f"202602{d:02d}": "normal" for d in range(1, 7)},
}


def _idx(day: str) -> int:
    return SESSIONS.index(day)


def _entry(day: str) -> str:
    return SESSIONS[_idx(day) + 1]


def _exit(day: str, offset: int) -> str:
    return SESSIONS[_idx(day) + offset]


def _world(
    *,
    blip_exit10: float = 110.0,
    run_exit10: float = 90.0,
    blip_cand_exit10: float | None = None,
    run_cand_exit10: float | None = None,
) -> dict[str, "pd.Series"]:
    """合成市场: 窗口外会话 open=100; blip 窗口市场涨 (exit10=110), run 窗口
    市场跌 (exit10=90); 候选退出价默认与市场同 (纯 beta), 可给 selection
    偏移。t8 窗口独立取值 (108/95)。世界内候选名用裸 symbol, opens 键面
    (带 .SZ) 由 _opens_with_ts 统一转换。"""
    data: dict[str, dict[str, float]] = {
        s: {ts: 100.0 for ts in MARKET} for s in SESSIONS
    }
    for ts in MARKET:
        data[_exit(BLIP_DAY, 10)][ts] = blip_exit10
        data[_exit(BLIP_DAY, 8)][ts] = 108.0
        data[_exit(RUN_DAY, 10)][ts] = run_exit10
        data[_exit(RUN_DAY, 8)][ts] = 95.0
    b_ex = blip_cand_exit10 if blip_cand_exit10 is not None else blip_exit10
    r_ex = run_cand_exit10 if run_cand_exit10 is not None else run_exit10
    for ts in BLIP:
        data[_entry(BLIP_DAY)][ts] = 100.0
        data[_exit(BLIP_DAY, 10)][ts] = b_ex
        data[_exit(BLIP_DAY, 8)][ts] = b_ex - 2.0
    for ts in RUN:
        data[_entry(RUN_DAY)][ts] = 100.0
        data[_exit(RUN_DAY, 10)][ts] = r_ex
        data[_exit(RUN_DAY, 8)][ts] = r_ex + 5.0
    return {s: pd.Series(v) for s, v in data.items()}


def _opens(world: dict[str, "pd.Series"]) -> dict[str, "pd.Series"]:
    """世界 → opens 键面: 候选名加 .SZ 后缀 (与事件表 ts_code 形态一致)."""
    out = {}
    for s, series in world.items():
        renamed = series.copy()
        renamed.index = [
            f"{i}.SZ" if i in (*BLIP, *RUN) else i for i in renamed.index
        ]
        out[s] = renamed
    return out


def _gross(world: dict[str, "pd.Series"], day: str, offset: int, ts: str) -> float:
    out_s = _exit(day, offset)
    return float(world[out_s][ts]) / float(world[_entry(day)][ts]) - 1


def _event_row(ts: str, day: str, gross10: float, gross8: float,
               *, off10: float = 10.0, off8: float = 8.0) -> dict:
    return {
        "symbol": ts, "ts_code": f"{ts}.SZ", "signal_date": day,
        "regime": "normal", "trigger_strength": 0.75, "signal_close": 10.0,
        "gap_t1_open": 0.0, "fillable": True, "t1_unbuyable": False,
        "t1_missing_bar": False, "degraded": False, "industry_missing": False,
        "industry_name": "测试", "st_name": False, "excluded_ticker": False,
        "price_ge_3": True, "gate_blocked": False,
        "exit_session_t10": off10, "gross_ret_t10": gross10,
        "exit_session_t8": off8, "gross_ret_t8": gross8,
    }


def _event_table(world: dict[str, "pd.Series"], *, off10: float = 10.0,
                 off8: float = 8.0) -> pd.DataFrame:
    rows = [
        _event_row(ts, BLIP_DAY, _gross(world, BLIP_DAY, int(off10), ts),
                   _gross(world, BLIP_DAY, int(off8), ts),
                   off10=off10, off8=off8)
        for ts in BLIP
    ] + [
        _event_row(ts, RUN_DAY, _gross(world, RUN_DAY, int(off10), ts),
                   _gross(world, RUN_DAY, int(off8), ts),
                   off10=off10, off8=off8)
        for ts in RUN
    ]
    return pd.DataFrame(rows)


def _external_bench(world: dict[str, "pd.Series"], day: str,
                    offset: int) -> float:
    """外部 oracle: 独立复算等权基准 (与工具零共享代码, R171 M-d 教训)."""
    entry_s, exit_s = _entry(day), _exit(day, offset)
    ins, outs = world[entry_s], world[exit_s]
    rets = []
    for ts in ins.index:
        if ts in outs.index and ins[ts] > 0 and outs[ts] > 0:
            rets.append(float(outs[ts]) / float(ins[ts]) - 1)
    assert len(rets) >= MIN_PAIR_NAMES
    return sum(rets) / len(rets)


def _history(tmp_path: Path) -> Path:
    p = tmp_path / "regime_history.json"
    p.write_text(json.dumps(REGIMES), encoding="utf-8")
    return p


def _rows(world, ev, tmp_path):
    sessions, labels = load_regime_history(_history(tmp_path))
    u = production_aligned(ev)
    prox = run_groups(pd.unique(u["signal_date"].astype(str)), sessions, labels)
    return u, prox


class TestBenchmarkArithmetic:
    def test_pair_benchmark_matches_external_oracle(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        u, prox = _rows(world, ev, tmp_path)
        rows, integrity = horizon_rows_with_benchmark(
            u, 10, prox, _opens(world), SESSIONS
        )
        expected_blip = _external_bench(world, BLIP_DAY, 10)
        expected_run = _external_bench(world, RUN_DAY, 10)
        blip = rows[rows["group"] == "d1_blip"]
        run = rows[rows["group"] == "d1_run"]
        assert len(blip) == N_CAND and len(run) == N_CAND
        assert abs(float(blip["bench"].mean()) - expected_blip) < 1e-12
        assert abs(float(run["bench"].mean()) - expected_run) < 1e-12
        assert integrity["selfcheck_checked"] == 2 * N_CAND
        assert integrity["selfcheck_mismatch"] == 0
        assert integrity["n_pairs"] == 2

    def test_window_alignment_t1_and_deferral_offset(self, tmp_path):
        """exit_off>10 顺延走偏移会话; T+1 精确对齐 (构建器同款语义)."""
        world = _world()
        # 扩展世界: 顺延窗口 (offset=12) 的市场与候选开盘 (裸名, rename 面统一处理)
        for ts in MARKET:
            world[_exit(BLIP_DAY, 12)][ts] = 112.0
            world[_exit(RUN_DAY, 12)][ts] = 92.0
        for ts in BLIP:
            world[_exit(BLIP_DAY, 12)][ts] = 112.0
        for ts in RUN:
            world[_exit(RUN_DAY, 12)][ts] = 92.0
        ev = _event_table(world, off10=12.0)
        u, prox = _rows(world, ev, tmp_path)
        rows, _ = horizon_rows_with_benchmark(u, 10, prox, _opens(world), SESSIONS)
        expected_blip = _external_bench(world, BLIP_DAY, 12)
        expected_run = _external_bench(world, RUN_DAY, 12)
        blip = rows[rows["group"] == "d1_blip"]
        run = rows[rows["group"] == "d1_run"]
        assert abs(float(blip["bench"].mean()) - expected_blip) < 1e-12
        assert abs(float(run["bench"].mean()) - expected_run) < 1e-12
        # T+1 与顺延退出会话的精确日历算术
        assert _exit(BLIP_DAY, 1) == "20260107"
        assert _exit(BLIP_DAY, 12) == "20260118"

    def test_gross_values_reproduced_from_world(self, tmp_path):
        """事件表 gross 由世界开盘价独立构造 — 工具自检必须 0 mismatch."""
        world = _world(blip_cand_exit10=113.0, run_cand_exit10=80.0)
        ev = _event_table(world)
        u, prox = _rows(world, ev, tmp_path)
        rows, integrity = horizon_rows_with_benchmark(
            u, 10, prox, _opens(world), SESSIONS
        )
        assert integrity["selfcheck_mismatch"] == 0
        assert len(rows) == 2 * N_CAND


class TestIdentityDecomposition:
    def test_identity_exact_per_group_per_horizon(self, tmp_path):
        world = _world(blip_cand_exit10=113.0, run_cand_exit10=80.0)
        ev = _event_table(world)
        payload = analyze(ev, _history(tmp_path), _opens(world), SESSIONS)
        for h in ("t10", "t8"):
            groups = payload["decomposition"][h]["groups"]
            for g in GROUP_ORDER:
                cell = groups[g]
                assert cell["n"] > 0
                assert cell["identity_residual"] <= 1e-12

    def test_group_values_exact(self, tmp_path):
        """已知世界的 E_net/E_bench/E_excess 逐值精确 (外部 oracle)."""
        world = _world(blip_cand_exit10=113.0, run_cand_exit10=80.0)
        ev = _event_table(world)
        payload = analyze(ev, _history(tmp_path), _opens(world), SESSIONS)
        groups = payload["decomposition"]["t10"]["groups"]
        bench_b = _external_bench(world, BLIP_DAY, 10)
        gross_b = float(world[_exit(BLIP_DAY, 10)]["B000"]) / 100.0 - 1
        assert abs(groups["d1_blip"]["e_net"] - (gross_b - ROUNDTRIP_COST)) < 1e-12
        assert abs(groups["d1_blip"]["e_bench"] - bench_b) < 1e-12
        assert abs(
            groups["d1_blip"]["e_excess"] - (gross_b - ROUNDTRIP_COST - bench_b)
        ) < 1e-12
        assert groups["d1_blip"]["n_days"] == 1
        assert groups["all"]["n"] == 2 * N_CAND


class TestBetaSelectionSemantics:
    def test_pure_beta_world_net_contrast_nonzero_excess_contrast_zero(self, tmp_path):
        """语义核心: 纯 beta 世界 (候选 gross == 市场基准) — 净对比非零
        (表面优势), 超额对比恰零 (优势全部是市场 beta)。"""
        world = _world()  # 候选与市场同路径 = 零 selection
        ev = _event_table(world)
        payload = analyze(ev, _history(tmp_path), _opens(world), SESSIONS)
        contrast = payload["decomposition"]["t10"]["contrast"]
        groups = payload["decomposition"]["t10"]["groups"]
        raw_delta = groups["d1_blip"]["e_net"] - groups["d1_run"]["e_net"]
        excess_delta = groups["d1_blip"]["e_excess"] - groups["d1_run"]["e_excess"]
        assert raw_delta > 0.15  # 净空间"决定性"形态
        assert abs(excess_delta) < 1e-12  # 超额空间优势消失
        assert contrast["raw"]["ci_low"] > 0
        assert contrast["excess"]["ci_low"] <= 0 <= contrast["excess"]["ci_high"]

    def test_selection_world_excess_contrast_survives(self, tmp_path):
        """selection 世界 (blip 候选跑赢、run 候选跑输市场) — 超额对比保持正."""
        world = _world(blip_cand_exit10=113.0, run_cand_exit10=80.0)
        ev = _event_table(world)
        payload = analyze(ev, _history(tmp_path), _opens(world), SESSIONS)
        groups = payload["decomposition"]["t10"]["groups"]
        excess_delta = groups["d1_blip"]["e_excess"] - groups["d1_run"]["e_excess"]
        assert excess_delta > 0.05
        assert payload["decomposition"]["t10"]["contrast"]["excess"]["ci_low"] > 0


class TestSelfcheckAndGuards:
    def test_tampered_open_fails_closed(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        opens = _opens(world)
        exit_s = _exit(BLIP_DAY, 10)
        opens[exit_s]["B000.SZ"] = 150.0  # 篡改候选退出开盘 → 重算 gross 不匹配
        u, prox = _rows(world, ev, tmp_path)
        with pytest.raises(SystemExit, match="benchmark_selfcheck_mismatch"):
            horizon_rows_with_benchmark(u, 10, prox, opens, SESSIONS)

    def test_missing_candidate_open_fails_closed(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        opens = _opens(world)
        opens[_exit(BLIP_DAY, 10)] = opens[_exit(BLIP_DAY, 10)].drop(index="B000.SZ")
        u, prox = _rows(world, ev, tmp_path)
        with pytest.raises(SystemExit, match="benchmark_selfcheck_open_missing"):
            horizon_rows_with_benchmark(u, 10, prox, opens, SESSIONS)

    def test_pair_min_names_guard(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        opens = _opens(world)
        small = {s: v.head(MIN_PAIR_NAMES - 1) for s, v in opens.items()}
        u, prox = _rows(world, ev, tmp_path)
        with pytest.raises(SystemExit, match="benchmark_pair_degenerate"):
            horizon_rows_with_benchmark(u, 10, prox, small, SESSIONS)

    def test_missing_source_session_fails_closed(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        opens = _opens(world)
        del opens[_exit(BLIP_DAY, 10)]
        u, prox = _rows(world, ev, tmp_path)
        with pytest.raises(SystemExit, match="benchmark_source_session_missing"):
            horizon_rows_with_benchmark(u, 10, prox, opens, SESSIONS)

    def test_signal_not_in_calendar_fails_closed(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        u, prox = _rows(world, ev, tmp_path)
        with pytest.raises(SystemExit, match="signal_session_not_in_calendar"):
            horizon_rows_with_benchmark(u, 10, prox, _opens(world), SESSIONS[6:])

    def test_window_beyond_calendar_fails_closed(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        u, prox = _rows(world, ev, tmp_path)
        with pytest.raises(SystemExit, match="benchmark_window_beyond_calendar"):
            horizon_rows_with_benchmark(u, 10, prox, _opens(world), SESSIONS[:10])

    def test_gross_present_offset_missing_fails_closed(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        ev.loc[0, "exit_session_t10"] = float("nan")
        u, prox = _rows(world, ev, tmp_path)
        with pytest.raises(SystemExit, match="exit_offset_missing_with_gross_present"):
            horizon_rows_with_benchmark(u, 10, prox, _opens(world), SESSIONS)

    def test_empty_universe_fails_closed(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        ev["gate_blocked"] = True  # 全体被生产 gate 排除 → 空宇宙
        with pytest.raises(SystemExit, match="empty_production_aligned_universe"):
            analyze(ev, _history(tmp_path), _opens(world), SESSIONS)


class TestDeterminismAndRender:
    def test_analyze_deterministic_bytes(self, tmp_path):
        world = _world(blip_cand_exit10=113.0, run_cand_exit10=80.0)
        ev = _event_table(world)
        opens = _opens(world)
        hist = _history(tmp_path)
        a = json.dumps(analyze(ev, hist, opens, SESSIONS), sort_keys=True)
        b = json.dumps(analyze(ev, hist, opens, SESSIONS), sort_keys=True)
        assert a == b

    def test_render_md_survives_missing_keys(self):
        payload = {"schema_version": 1, "decomposition": {}, "benchmark_integrity": {}}
        md = render_md(payload, "20260910")
        assert "—" in md

    def test_render_md_shows_falsy_zero(self):
        payload = {
            "schema_version": 1,
            "court_window": {"start": "20250702", "end": "20260909"},
            "aligned_n": 10,
            "rows_with_benchmark": 10,
            "benchmark_integrity": {
                "selfcheck_checked": 10, "selfcheck_mismatch": 0,
                "n_pairs": 2, "pair_names_min": 140, "pair_names_median": 150.0,
            },
            "decomposition": {
                "t10": {
                    "groups": {
                        g: {
                            "n": 40, "n_days": 1, "e_net": 0.0, "e_bench": 0.0,
                            "e_excess": 0.0, "winrate_net": 0.5,
                            "winrate_excess": 0.0, "identity_residual": 0.0,
                        }
                        for g in GROUP_ORDER
                    },
                    "contrast": {
                        "raw": {"ci_low": 0.02, "ci_high": 0.1,
                                "n_blip": 40, "n_run": 40},
                        "excess": {"ci_low": 0.0, "ci_high": 0.0,
                                   "n_blip": 40, "n_run": 40},
                    },
                },
            },
            "label_consistency": {"checked": 2, "mismatch_count": 0},
        }
        md = render_md(payload, "20260910")
        assert "+0.00%" in md  # falsy-zero 显示, 不是 '—'
        assert "OK" in md  # 恒等残差 0 → OK
        # 名单数是计数不是百分比 (R171 F-a 同款形态纪律) — 精确形态 + 百分比
        # 伪影缺席双面钉住 (子串断言 "140" 会被 "+14000.00%" 撞形, R173 M-f)
        assert "min 140 / median 150.0" in md
        assert "14000" not in md
        assert "15000" not in md

    def test_label_consistency_passes(self, tmp_path):
        world = _world()
        ev = _event_table(world)
        payload = analyze(ev, _history(tmp_path), _opens(world), SESSIONS)
        assert payload["label_consistency"]["mismatch_count"] == 0


class TestMainEndToEnd:
    def test_main_writes_reports_and_binding(self, tmp_path, capsys):
        world = _world()
        ev = _event_table(world)
        court_csv = tmp_path / "court.csv"
        ev.to_csv(court_csv, index=False)
        hist = _history(tmp_path)
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        for s, series in _opens(world).items():
            df = series.rename("open").reset_index().rename(
                columns={"index": "ts_code"}
            )
            df.to_csv(raw_dir / f"daily_{s}.csv", index=False)
        cal = tmp_path / "cal.json"
        cal.write_text(json.dumps(SESSIONS), encoding="utf-8")
        report_dir = tmp_path / "reports"
        rc = main([
            "--court-table", str(court_csv),
            "--regime-history", str(hist),
            "--raw-dir", str(raw_dir),
            "--trade-calendar", str(cal),
            "--report-dir", str(report_dir),
        ])
        assert rc == 0
        assert (report_dir / f"{REPORT_STEM}_20260910.md").exists()
        assert (report_dir / f"{REPORT_STEM}_20260910.json").exists()
        payload = json.loads(
            (report_dir / f"{REPORT_STEM}_20260910.json").read_text()
        )
        assert payload["benchmark_integrity"]["selfcheck_mismatch"] == 0
        # stdout 契约面钉住 (R173 M-h: 键路径断裂曾静默 [None,None] 全绿放行) —
        # 纯 beta 世界两组 excess 恒 −cost → 对比差 CI 两端 ≈ 0 (超额优势消失)
        stdout = json.loads(capsys.readouterr().out)
        assert stdout["aligned_n"] == 2 * N_CAND
        assert stdout["rows_with_benchmark"] == 2 * N_CAND
        ci = stdout["excess_delta_ci_t10"]
        assert len(ci) == 2
        for v in ci:
            assert v is not None
            assert abs(v) < 1e-9
