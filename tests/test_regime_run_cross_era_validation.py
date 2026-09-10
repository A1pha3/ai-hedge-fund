"""regime_run_cross_era_validation — R168 d1_run 对比的跨时代外部验证 (R178 Op1).

R168 决定性对比 (d1_blip +1.77% vs d1_run −5.74%, 配对差 CI90 越零) 建在
单一时代 (2025-07 起) 的 court 样本上; R170 已诚实降格其时序识别力
(placebo 循环移位 p=0.148 未越 p95)。本工具把同一条轴放到独立时代
(2022-24 早期窗口事件表, 同公式指纹 + 同 regime 轴) 上外部验证。
钉死的正确性面:
- 时代分析 100% 委托 R168 analyze 单一实现 (本模块零统计 fork);
- 判定谓词机械: d1_penalty_sign_consistent (两时代 CI 下界同越零) /
  early_ci_excludes_current_point (早期区间是否排除当前量级) / verdict
  装配 (不可判定形态 None-CI 走诚实路径);
- 阻断段结构直方图 (描述性语境: 两时代阻断频率/连跑长度) 手工可算
  fixture 逐值钉住 + 窗口起点截断右删失形态;
- manifest 公式指纹一致性 fail-closed (指纹漂移 = 两表不可比, typed 拒绝);
- 幸存者偏差方向混杂披露成文 (早期宇宙缺退市票 → 偏差不成比例落在
  危机后组, 早期 d1_run 读数乐观, 不复制≠决定性反证);
- 渲染缺键存活 (R158 家族) + 报告确定性 (R13 家族: 同输入两次调用
  逐字节同 payload)。
纪律 (宪法 #2): 纯诊断披露 — 本工具不判定 d1_run 规则, 只回答『R168
d1 边界是否可外推到独立时代』; 任何据此的策略变化 = 新证据世代 owner
决策。fixture 驱动 slot 自足 (R10 纪律), 不依赖 gitignored 本地资产。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from scripts.regime_run_cross_era_validation import (
    EARLY_TABLE_DEFAULT,
    RegimeRunCrossEraValidationError,
    REPORT_STEM,
    blocked_run_length_histogram,
    cross_era_payload,
    load_manifest_fingerprint,
    main,
    render_md,
)

# ---------------------------------------------------------------------------
# fixture 世界: 15 会话, 两个时代同构阻断形状、不同收益形态
# ---------------------------------------------------------------------------
SESSIONS = [f"202601{d:02d}" for d in range(1, 16)]
# 两段 ≥2 连跑 (0101-0102, 0108-0109) 各跟一个 d1_run 日 (0103, 0110);
# 两个单日闪断 (0105, 0112) 各跟一个 d1_blip 日 (0106, 0113)。
# 注意 0104/0111 是 d2_run、0107/0114 是 d2_blip — fixture 不在其上放行。
CURRENT_LABELS = {
    "20260101": "crisis",
    "20260102": "crisis",
    "20260103": "normal",
    "20260104": "normal",
    "20260105": "risk_off",
    "20260106": "normal",
    "20260107": "normal",
    "20260108": "crisis",
    "20260109": "crisis",
    "20260110": "normal",
    "20260111": "normal",
    "20260112": "risk_off",
    "20260113": "normal",
    "20260114": "normal",
    "20260115": "normal",
}

FINGERPRINT = {
    "btst_breakout_sha256": "a" * 64,
    "exit_policy_sha256": "b" * 64,
}

NET_BIAS = 0.0065  # ROUNDTRIP_COST, 测试内独立常量 (镜像, 不 import)


def _event_rows(
    *,
    blip_gross: float,
    run_gross: float,
    days_per_group: int = 2,
    rows_per_day: int = 20,
) -> pd.DataFrame:
    """d1_blip/d1_run 两组合成行 (含全部生产过滤列, 与 R168 测试同构)."""
    group_days = {
        "d1_blip": ["20260106", "20260113"],
        "d1_run": ["20260103", "20260110"],
    }
    rows: list[dict] = []
    for group, days in group_days.items():
        gross = blip_gross if group == "d1_blip" else run_gross
        for day in days[:days_per_group]:
            for i in range(rows_per_day):
                blocked = False
                sym = f"{group}_{day}_{i}"
                rows.append(
                    {
                        "symbol": sym,
                        "ts_code": sym + ".SZ",
                        "signal_date": day,
                        "regime": "normal",
                        "trigger_strength": 0.75,
                        "signal_close": 10.0,
                        "gap_t1_open": 0.0,
                        "fillable": not blocked,
                        "t1_unbuyable": False,
                        "t1_missing_bar": False,
                        "degraded": False,
                        "industry_missing": False,
                        "industry_name": "测试",
                        "st_name": False,
                        "excluded_ticker": False,
                        "price_ge_3": True,
                        "gate_blocked": blocked,
                        "gross_ret_t5": gross,
                        "exit_session_t5": 5.0,
                        "gross_ret_t10": gross,
                        "exit_session_t10": 10.0,
                    }
                )
    return pd.DataFrame(rows)


def _write_history(tmp: Path, labels: dict[str, str]) -> Path:
    p = tmp / "regime_history.json"
    p.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    return p


def _write_manifest(tmp: Path, name: str, fingerprint: dict) -> Path:
    p = tmp / name
    p.write_text(
        json.dumps({"formula_fingerprint": fingerprint}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# blocked_run_length_histogram — 描述性语境轴 (手工可算)
# ---------------------------------------------------------------------------
def test_blocked_run_length_histogram_exact_values(tmp_path: Path) -> None:
    history = _write_history(
        tmp_path,
        {
            "20260101": "crisis",
            "20260102": "crisis",
            "20260103": "normal",
            "20260104": "risk_off",
            "20260105": "normal",
            "20260106": "crisis",
            "20260107": "normal",
            "20260108": "normal",
            "20260109": "crisis",
            "20260110": "crisis",
        },
    )
    st = blocked_run_length_histogram(history, "20260101", "20260110")
    assert st["sessions"] == 10
    assert st["blocked_days"] == 6
    assert st["blocked_freq"] == pytest.approx(0.6)
    # 连跑段: [2, 1, 1, 2]
    assert st["run_length_hist"] == {"1": 2, "2": 2}
    assert st["runs_total"] == 4
    assert st["runs_ge2"] == 2


def test_blocked_run_length_histogram_window_start_truncation(
    tmp_path: Path,
) -> None:
    """窗口起点落在段中间 → 段按窗内长度计入 (右删失下界, 披露形态)."""
    history = _write_history(
        tmp_path,
        {
            "20260101": "normal",
            "20260102": "crisis",
            "20260103": "crisis",
            "20260104": "crisis",
            "20260105": "normal",
        },
    )
    st = blocked_run_length_histogram(history, "20260103", "20260105")
    # 3 日段被窗口截断为窗内 2 日
    assert st["run_length_hist"] == {"2": 1}
    assert st["runs_total"] == 1


# ---------------------------------------------------------------------------
# load_manifest_fingerprint / 指纹一致性 — fail-closed 面
# ---------------------------------------------------------------------------
def test_load_manifest_fingerprint_extracts_fingerprint(tmp_path: Path) -> None:
    p = _write_manifest(tmp_path, "m.json", FINGERPRINT)
    assert load_manifest_fingerprint(p) == FINGERPRINT


def test_load_manifest_fingerprint_missing_key_typed(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"window": {}}), encoding="utf-8")
    with pytest.raises(RegimeRunCrossEraValidationError, match="manifest_fingerprint_missing"):
        load_manifest_fingerprint(p)


def test_load_manifest_fingerprint_unreadable_typed(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json {", encoding="utf-8")
    with pytest.raises(RegimeRunCrossEraValidationError, match="manifest_unreadable"):
        load_manifest_fingerprint(p)


def test_cross_era_payload_fingerprint_mismatch_typed(tmp_path: Path) -> None:
    """指纹漂移 = 两表不可比 → typed 拒绝, 绝不产报告冒充可比."""
    history = _write_history(tmp_path, CURRENT_LABELS)
    other_fp = {**FINGERPRINT, "exit_policy_sha256": "c" * 64}
    cur_m = _write_manifest(tmp_path, "cur.json", FINGERPRINT)
    early_m = _write_manifest(tmp_path, "early.json", other_fp)
    with pytest.raises(RegimeRunCrossEraValidationError, match="formula_fingerprint_mismatch"):
        cross_era_payload(
            _event_rows(blip_gross=0.02, run_gross=-0.05),
            _event_rows(blip_gross=0.02, run_gross=-0.05),
            history,
            cur_m,
            early_m,
        )


# ---------------------------------------------------------------------------
# cross_era_payload — 判定谓词 + 点罚分精确值 (外部手工 oracle)
# ---------------------------------------------------------------------------
def _era_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    history = _write_history(tmp_path, CURRENT_LABELS)
    cur_m = _write_manifest(tmp_path, "cur.json", FINGERPRINT)
    early_m = _write_manifest(tmp_path, "early.json", FINGERPRINT)
    return history, cur_m, early_m


def test_cross_era_payload_early_null_flips_predicates(tmp_path: Path) -> None:
    """当前时代罚分明显 / 早期时代无罚分 → sign_consistent=False.

    手工 oracle: ROUNDTRIP_COST = 0.65% (0.0065) — blip gross +2% → net
    0.01350; run gross −5% → net −0.05650; 当前点罚分 = 0.01350 −
    (−0.05650) = 0.07。早期两组合成同一 gross +2% → 点罚分 0 (窄区间
    围绕 0, 排除 0.07)。
    """
    history, cur_m, early_m = _era_inputs(tmp_path)
    payload = cross_era_payload(
        _event_rows(blip_gross=0.02, run_gross=-0.05),
        _event_rows(blip_gross=0.02, run_gross=0.02),
        history,
        cur_m,
        early_m,
    )
    cur_point = payload["d1_point_penalty"]["current"]
    early_point = payload["d1_point_penalty"]["early"]
    assert cur_point == pytest.approx(0.01350 - (-0.05650))
    assert early_point == pytest.approx(0.0)
    v = payload["verdict"]
    assert v["d1_penalty_sign_consistent"] is False
    assert v["early_ci_excludes_current_point"] is True
    assert "仅当前时代" in v["statement"]
    # 排除量级的机械读数必须带方向性保留 (幸存者偏差下不构成反证 — R178
    # 交付前自我修正: 反证措辞过强会误导 owner 判读)
    assert "不构成反证" in v["statement"]
    # 时代表数值面: 两时代组 n 一致 (同构形状), E 与 oracle 同
    eras = payload["eras"]
    assert eras["current"]["group_table"]["d1_blip"]["n"] == 40
    assert eras["current"]["group_table"]["d1_run"]["n"] == 40
    assert eras["current"]["group_table"]["d1_blip"]["expectancy"] == pytest.approx(0.01350)
    assert eras["current"]["group_table"]["d1_run"]["expectancy"] == pytest.approx(-0.05650)
    assert eras["early"]["group_table"]["d1_run"]["expectancy"] == pytest.approx(0.01350)
    # 指纹一致性披露
    assert payload["formula_fingerprints"]["identical"] is True


def test_cross_era_payload_early_penalty_replicates(tmp_path: Path) -> None:
    """早期时代同样罚分形态 → sign_consistent=True (独立时代支持形态)."""
    history, cur_m, early_m = _era_inputs(tmp_path)
    payload = cross_era_payload(
        _event_rows(blip_gross=0.02, run_gross=-0.05),
        _event_rows(blip_gross=0.02, run_gross=-0.05),
        history,
        cur_m,
        early_m,
    )
    v = payload["verdict"]
    assert v["d1_penalty_sign_consistent"] is True
    assert "独立时代" in v["statement"]


def test_cross_era_payload_none_ci_undecidable_path(tmp_path: Path) -> None:
    """任一侧 n<MIN_CELL_N → CI None → 不可判定诚实路径 (不冒充判定)."""
    history, cur_m, early_m = _era_inputs(tmp_path)
    # 每组每天 1 行 × 2 天 = 2 行/组 < MIN_CELL_N
    payload = cross_era_payload(
        _event_rows(blip_gross=0.02, run_gross=-0.05, rows_per_day=1),
        _event_rows(blip_gross=0.02, run_gross=0.02, rows_per_day=1),
        history,
        cur_m,
        early_m,
    )
    v = payload["verdict"]
    assert v["d1_penalty_sign_consistent"] is False
    assert v["early_ci_excludes_current_point"] is None
    assert "不可判定" in v["statement"]


def test_cross_era_payload_era_structure_attached(tmp_path: Path) -> None:
    """两时代阻断结构直方图逐值入 payload (描述性语境轴)."""
    history, cur_m, early_m = _era_inputs(tmp_path)
    payload = cross_era_payload(
        _event_rows(blip_gross=0.02, run_gross=-0.05),
        _event_rows(blip_gross=0.02, run_gross=0.02),
        history,
        cur_m,
        early_m,
    )
    st = payload["era_structure"]["current"]
    # 结构按数据内容窗口计 (court_window = 信号日 min/max = 0103..0113, 11 会话):
    # 窗内段 [0105]=1, [0108-0109]=2, [0112]=1 → hist {"1": 2, "2": 1};
    # 0101-0102 段在窗外不计 (窗口截断语义, 与 court_window 披露一致)
    assert st["run_length_hist"] == {"1": 2, "2": 1}
    assert st["blocked_days"] == 4
    assert st["sessions"] == 11
    assert st["runs_total"] == 3
    assert st["runs_ge2"] == 1
    assert payload["era_structure"]["early"]["run_length_hist"] == {"1": 2, "2": 1}


def test_cross_era_payload_confounds_disclosed(tmp_path: Path) -> None:
    """幸存者偏差方向混杂必须成文入 payload (不复制≠反证的方向论证)."""
    history, cur_m, early_m = _era_inputs(tmp_path)
    payload = cross_era_payload(
        _event_rows(blip_gross=0.02, run_gross=-0.05),
        _event_rows(blip_gross=0.02, run_gross=0.02),
        history,
        cur_m,
        early_m,
    )
    conf = payload["confounds"]
    assert "survivorship_direction" in conf
    assert "退市" in conf["survivorship_direction"]["finding"]
    assert "乐观" in conf["survivorship_direction"]["implication"]
    assert "partial_universe" in conf
    # label 一致性逐时代附入 (轴同源证据)
    assert payload["eras"]["early"]["label_consistency"]["mismatch_count"] == 0


def test_cross_era_payload_report_deterministic(tmp_path: Path) -> None:
    """R13 家族: 同输入两次调用 payload 逐字节一致 (per-call seeded)."""
    history, cur_m, early_m = _era_inputs(tmp_path)
    rows_a = _event_rows(blip_gross=0.02, run_gross=-0.05)
    rows_b = _event_rows(blip_gross=0.02, run_gross=0.02)
    p1 = cross_era_payload(rows_a, rows_b, history, cur_m, early_m)
    p2 = cross_era_payload(rows_a.copy(), rows_b.copy(), history, cur_m, early_m)
    assert json.dumps(p1, sort_keys=True, default=str) == json.dumps(
        p2, sort_keys=True, default=str
    )


# ---------------------------------------------------------------------------
# 渲染与 CLI — 缺键存活 / e2e 文件产出
# ---------------------------------------------------------------------------
def test_render_md_survives_missing_keys(tmp_path: Path) -> None:
    history, cur_m, early_m = _era_inputs(tmp_path)
    payload = cross_era_payload(
        _event_rows(blip_gross=0.02, run_gross=-0.05),
        _event_rows(blip_gross=0.02, run_gross=0.02),
        history,
        cur_m,
        early_m,
    )
    battered = dict(payload)
    battered.pop("era_structure")
    battered.pop("confounds")
    battered["verdict"] = {}
    md = render_md(battered, "20260911")
    assert "(缺 era_structure)" in md
    assert "(缺 confounds)" in md
    assert "—" in md  # 缺键行走占位符不崩溃


def test_render_md_group_rows_rendered_exactly_once(tmp_path: Path) -> None:
    """组表每行恰渲染一次 (集合运算优先级曾致行翻倍 — 交付前自查实锤)."""
    history, cur_m, early_m = _era_inputs(tmp_path)
    payload = cross_era_payload(
        _event_rows(blip_gross=0.02, run_gross=-0.05),
        _event_rows(blip_gross=0.02, run_gross=0.02),
        history,
        cur_m,
        early_m,
    )
    md = render_md(payload, "20260911")
    assert md.count("| d1_blip |") == 1
    assert md.count("| d1_run |") == 1
    assert md.count("| d2_run |") == 1
    assert md.count("| d3p_run |") == 1


def test_main_e2e_writes_reports_and_headline(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    history, cur_m, early_m = _era_inputs(tmp_path)
    cur_table = tmp_path / "current.csv"
    early_table = tmp_path / "early.csv"
    _event_rows(blip_gross=0.02, run_gross=-0.05).to_csv(cur_table, index=False)
    _event_rows(blip_gross=0.02, run_gross=0.02).to_csv(early_table, index=False)
    out_dir = tmp_path / "reports"
    rc = main(
        [
            "--court-table", str(cur_table),
            "--early-court-table", str(early_table),
            "--regime-history", str(history),
            "--current-manifest", str(cur_m),
            "--early-manifest", str(early_m),
            "--out-dir", str(out_dir),
            "--date", "20260911",
        ]
    )
    assert rc == 0
    md_path = out_dir / f"{REPORT_STEM}_20260911.md"
    json_path = out_dir / f"{REPORT_STEM}_20260911.json"
    assert md_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["report_date"] == "20260911"
    assert payload["digest"]["early_rows"] == 80
    out = capsys.readouterr().out
    assert REPORT_STEM in out
    assert "sign_consistent=False" in out


def test_main_e2e_missing_early_table_typed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    history, cur_m, early_m = _era_inputs(tmp_path)
    cur_table = tmp_path / "current.csv"
    _event_rows(blip_gross=0.02, run_gross=-0.05).to_csv(cur_table, index=False)
    with pytest.raises(SystemExit):
        main(
            [
                "--court-table", str(cur_table),
                "--early-court-table", str(tmp_path / "nope.csv"),
                "--regime-history", str(history),
                "--current-manifest", str(cur_m),
                "--early-manifest", str(early_m),
                "--out-dir", str(tmp_path / "reports"),
                "--date", "20260911",
            ]
        )


def test_early_table_default_points_at_early_window() -> None:
    """默认早期表路径钉死在 2022-24 事件表 (防未来重构静默漂移)."""
    assert "event_tables_early" in str(EARLY_TABLE_DEFAULT)
    assert str(EARLY_TABLE_DEFAULT).endswith("event_table_v1.csv.gz")
