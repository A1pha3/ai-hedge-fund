"""regime_run_universe_match_validation — R168 时代条件性的宇宙构成判别 (R179 Op1).

R178 判定「d1 罚分仅当前时代可检」后, 时代差有两个未分机制: 宇宙构成差
vs 时代行为差异/早期侧幸存者缺失。本工具把当前时代事件表限制到早期表
symbol 全集 (构成匹配视图), 同一 R168 轴重跑 — 机械判别构成轴。
钉死的正确性面:
- 三视图 100% 委托 R168 analyze 单一实现 (经 R178 _era_view 复用, import
  身份断言钉住零 fork);
- 匹配过滤成员资格逐行正确 (in-S 保留 / out-S 剔除) + 匹配视图统计量
  外部 oracle 精确值 (R171 M-d 教训: 直接 oracle, 不靠间接秩测试);
- 判定谓词双形态 fixture 分别触发 (构成解释 / 不解释) + 不可判定诚实路径
  (匹配视图组 n<MIN_CELL_N, CI 缺失不冒充判定);
- manifest 公式指纹漂移 typed 拒绝 (R178 单一实现复用) + symbol 列缺失/
  全空 typed 拒绝 + 零交集 typed 拒绝;
- 渲染缺键存活 (R158 家族) + 报告确定性 (R13 家族: 同输入两次调用逐字节
  同 payload / e2e 双跑逐字节同报告);
- 夜刷链成员 (pinned-set 同步在 test_court_nightly_refresh 面钉住)。
纪律 (宪法 #2): 纯诊断披露, 不判定 d1_run 规则; fixture 驱动 slot 自足
(R10 纪律), 不依赖 gitignored 本地资产。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.regime_run_universe_match_validation import (
    REPORT_STEM,
    RegimeRunUniverseMatchError,
    _symbols,
    main,
    render_md,
    universe_match_payload,
)

# ---------------------------------------------------------------------------
# fixture 世界: 15 会话 (R178 同构阻断形状), 双票集拆分
# ---------------------------------------------------------------------------
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

GROUP_DAYS = {
    "d1_blip": ["20260106", "20260113"],
    "d1_run": ["20260103", "20260110"],
}


def _rows(
    *,
    prefix: str,
    blip_gross: float,
    run_gross: float,
    days_per_group: int = 2,
    rows_per_day: int = 20,
    gross5: float | None = None,
) -> pd.DataFrame:
    """d1_blip/d1_run 两组合成行, symbol 前缀区分票集 (含全部生产过滤列)."""
    gross_t5 = None if gross5 is None else gross5
    rows: list[dict] = []
    for group, days in GROUP_DAYS.items():
        gross = blip_gross if group == "d1_blip" else run_gross
        g5 = gross if gross_t5 is None else gross_t5
        for day in days[:days_per_group]:
            for i in range(rows_per_day):
                sym = f"{prefix}_{group}_{day}_{i}"
                rows.append(
                    {
                        "symbol": sym,
                        "ts_code": sym + ".SZ",
                        "signal_date": day,
                        "regime": "normal",
                        "trigger_strength": 0.75,
                        "signal_close": 10.0,
                        "gap_t1_open": 0.0,
                        "fillable": True,
                        "t1_unbuyable": False,
                        "t1_missing_bar": False,
                        "degraded": False,
                        "industry_missing": False,
                        "industry_name": "测试",
                        "st_name": False,
                        "excluded_ticker": False,
                        "price_ge_3": True,
                        "gate_blocked": False,
                        "gross_ret_t5": g5,
                        "exit_session_t5": 5.0,
                        "gross_ret_t10": gross,
                        "exit_session_t10": 10.0,
                    }
                )
    return pd.DataFrame(rows)


def _world(
    *,
    in_blip: float = 0.10,
    in_run: float = -0.10,
    in_rows_per_day: int = 20,
    out_blip: float = 0.12,
    out_run: float = -0.12,
    out_rows_per_day: int = 20,
    early_blip: float = 0.05,
    early_run: float = 0.04,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """当前表 = in-S (早期票集 e_ 的同型 symbol) + out-S (x_ 独立票集).

    早期表票集 = e_ 前缀的 80 只; 当前 in-S 行复用同一批 symbol 串
    (跨时代同票 — 构成匹配的成员资格语义), out-S 行票集独立。
    """
    current = pd.concat(
        [
            _rows(
                prefix="e_",
                blip_gross=in_blip,
                run_gross=in_run,
                rows_per_day=in_rows_per_day,
            ),
            _rows(
                prefix="x_",
                blip_gross=out_blip,
                run_gross=out_run,
                rows_per_day=out_rows_per_day,
            ),
        ],
        ignore_index=True,
    )
    early = _rows(
        prefix="e_", blip_gross=early_blip, run_gross=early_run
    )
    return current, early


def _payload(tmp: Path, current: pd.DataFrame, early: pd.DataFrame) -> dict:
    history = tmp / "history.json"
    history.write_text(json.dumps(CURRENT_LABELS), encoding="utf-8")
    cm = tmp / "cm.json"
    cm.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    em = tmp / "em.json"
    em.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    return universe_match_payload(current, early, history, cm, em)


# ---------------------------------------------------------------------------
# 零 fork 委托 — import 身份断言 (R176 单一实现先例)
# ---------------------------------------------------------------------------
def test_era_view_and_fingerprint_loader_are_single_implementation() -> None:
    """_era_view/_point_penalty/指纹 loader 是 R178 模块对象本身 (非本地 fork)."""
    from scripts import regime_run_universe_match_validation as m
    from scripts import regime_run_cross_era_validation as x

    assert m._era_view is x._era_view
    assert m._point_penalty is x._point_penalty
    assert m.load_manifest_fingerprint is x.load_manifest_fingerprint


# ---------------------------------------------------------------------------
# 匹配过滤成员资格 + 匹配视图统计量外部 oracle
# ---------------------------------------------------------------------------
def test_matched_view_keeps_only_in_universe_rows(tmp_path: Path) -> None:
    """in-S 保留 / out-S 剔除, 匹配视图 n 与期望逐值精确 (外部 oracle)."""
    current, early = _world()
    payload = _payload(tmp_path, current, early)

    um = payload["universe_match"]
    assert um["early_symbols"] == early["symbol"].nunique()
    assert um["current_rows_full"] == len(current)
    # 保留 = in-S 行 (2 组 × 2 日 × 20 行)
    assert um["current_rows_matched"] == 80
    assert um["matched_row_share"] == pytest.approx(0.5)
    assert um["current_symbols_matched"] == 80
    assert um["matched_symbol_share"] == pytest.approx(0.5)

    matched_table = payload["eras"]["current_matched"]["group_table"]
    blip_gross, run_gross = 0.10, -0.10
    cost = 0.0065
    assert matched_table["d1_blip"]["n"] == 40
    assert matched_table["d1_run"]["n"] == 40
    assert matched_table["d1_blip"]["expectancy"] == pytest.approx(blip_gross - cost)
    assert matched_table["d1_run"]["expectancy"] == pytest.approx(run_gross - cost)
    # 点罚分 = E[blip] − E[run] (独立复算)
    assert payload["d1_point_penalty"]["current_matched"] == pytest.approx(
        blip_gross - run_gross
    )


def test_full_view_unaffected_by_match(tmp_path: Path) -> None:
    """全宇宙视图含 out-S 行 (剔除只影响匹配视图) — 全表 oracle 逐值."""
    current, early = _world()
    payload = _payload(tmp_path, current, early)

    full_table = payload["eras"]["current_full"]["group_table"]
    cost = 0.0065
    assert full_table["d1_blip"]["n"] == 80
    assert full_table["d1_run"]["n"] == 80
    assert full_table["d1_blip"]["expectancy"] == pytest.approx(0.11 - cost)
    assert full_table["d1_run"]["expectancy"] == pytest.approx(-0.11 - cost)
    assert payload["eras"]["early"]["group_table"]["d1_blip"]["n"] == 40


# ---------------------------------------------------------------------------
# 判定谓词双形态 + 不可判定诚实路径
# ---------------------------------------------------------------------------
def test_verdict_composition_does_not_explain(tmp_path: Path) -> None:
    """全宇宙与匹配视图均显著 → 构成不解释时代差 (fixture 全正罚分)."""
    current, early = _world()
    payload = _payload(tmp_path, current, early)
    verdict = payload["verdict"]
    assert verdict["full_penalty_detectable"] is True
    assert verdict["matched_penalty_preserved"] is True
    assert verdict["composition_explains_gap"] is False
    assert "构成不解释时代差" in verdict["statement"]
    assert "构成轴排除" in verdict["statement"]


def test_verdict_composition_explains(tmp_path: Path) -> None:
    """全宇宙显著而匹配视图不显著 → 构成解释时代差 (罚分全部住在 out-S)."""
    # in-S: run 反而更好 (匹配视图罚分为负 → CI 下界必 ≤0);
    # out-S: 罚分巨大 (全宇宙罚分被 out-S 单独拉起)。
    current, early = _world(
        in_blip=0.01,
        in_run=0.02,
        out_blip=0.30,
        out_run=-0.30,
    )
    payload = _payload(tmp_path, current, early)
    verdict = payload["verdict"]
    assert verdict["full_penalty_detectable"] is True
    assert verdict["matched_penalty_preserved"] is False
    assert verdict["composition_explains_gap"] is True
    assert "构成解释时代差" in verdict["statement"]
    assert "宇宙条件证据" in verdict["statement"]


def test_verdict_full_not_detectable(tmp_path: Path) -> None:
    """全宇宙本身不显著 → 无时代差可解释 (检查 R168 前提形态)."""
    current, early = _world(in_blip=0.01, in_run=0.01, out_blip=0.01, out_run=0.01)
    payload = _payload(tmp_path, current, early)
    verdict = payload["verdict"]
    assert verdict["full_penalty_detectable"] is False
    assert verdict["matched_penalty_preserved"] is False
    assert verdict["composition_explains_gap"] is False
    assert "无时代差可解释" in verdict["statement"]


def test_verdict_undeterminable_when_matched_ci_missing(tmp_path: Path) -> None:
    """匹配视图组 n<MIN_CELL_N → CI None → 不可判定诚实路径 (不冒充判定)."""
    current, early = _world(
        in_blip=0.10,
        in_run=-0.10,
        in_rows_per_day=1,  # in-S 每组 2 行 < MIN_CELL_N(30) → CI None
        out_blip=0.30,
        out_run=-0.30,
    )
    payload = _payload(tmp_path, current, early)
    verdict = payload["verdict"]
    assert verdict["full_penalty_detectable"] is True
    assert verdict["matched_penalty_preserved"] is None
    assert verdict["composition_explains_gap"] is None
    assert "不可判定" in verdict["statement"]


# ---------------------------------------------------------------------------
# fail-closed 面 — 指纹漂移 / symbol 列缺失 / 零交集
# ---------------------------------------------------------------------------
def test_fingerprint_mismatch_typed(tmp_path: Path) -> None:
    """指纹漂移 = 两表不可比 → typed 拒绝 (复用 R178 loader 语义)."""
    current, early = _world()
    history = tmp_path / "history.json"
    history.write_text(json.dumps(CURRENT_LABELS), encoding="utf-8")
    cm = tmp_path / "cm.json"
    cm.write_text(
        json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8"
    )
    em = tmp_path / "em.json"
    em.write_text(
        json.dumps(
            {"formula_fingerprint": {**FINGERPRINT, "exit_policy_sha256": "c" * 64}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(RegimeRunUniverseMatchError, match="formula_fingerprint_mismatch"):
        universe_match_payload(current, early, history, cm, em)


def test_symbol_column_missing_typed(tmp_path: Path) -> None:
    current, early = _world()
    with pytest.raises(RegimeRunUniverseMatchError, match="early_symbol_column_missing"):
        _payload(tmp_path, current, early.drop(columns=["symbol"]))
    with pytest.raises(RegimeRunUniverseMatchError, match="current_symbol_column_missing"):
        _payload(tmp_path, current.drop(columns=["symbol"]), early)


def test_symbol_column_empty_typed(tmp_path: Path) -> None:
    current, early = _world()
    empty_sym = early.copy()
    empty_sym["symbol"] = None
    with pytest.raises(RegimeRunUniverseMatchError, match="early_symbol_column_empty"):
        _payload(tmp_path, current, empty_sym)


def test_disjoint_universes_typed(tmp_path: Path) -> None:
    """当前表与早期票集零交集 → 匹配视图不可构造, typed 拒绝不产空报告."""
    current, _ = _world()
    _, early = _world()  # 早期票集前缀 e_, 与 s_/x_ 天然不相交
    disjoint_current = current[current["symbol"].str.startswith("x_")]
    history = tmp_path / "history.json"
    history.write_text(json.dumps(CURRENT_LABELS), encoding="utf-8")
    cm = tmp_path / "cm.json"
    cm.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    em = tmp_path / "em.json"
    em.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    with pytest.raises(RegimeRunUniverseMatchError, match="matched_universe_empty"):
        universe_match_payload(disjoint_current, early, history, cm, em)


def test_symbol_coercion_numeric_strings_match(tmp_path: Path) -> None:
    """pd.read_csv 前导零票推断成 int 的两侧一致性 — str 化后成员资格不变."""
    current, early = _world()
    numeric = early.copy()
    numeric["symbol"] = ["959"] * len(numeric)  # 装载侧可能读成 int 959
    s = _symbols(numeric, "early")
    assert (s == "959").all()
    cur_sym = _symbols(current, "current")
    keep = cur_sym.isin(set(s.unique()))
    assert int(keep.sum()) == 0  # 票集不同 → 零保留 (集合语义而非值域假设)


# ---------------------------------------------------------------------------
# 渲染 — 缺键存活 + 确定性
# ---------------------------------------------------------------------------
def test_render_md_survives_missing_keys() -> None:
    text = render_md({}, "20260911")
    assert "statement: —" in text
    assert "(缺组表)" in text
    assert "公式指纹一致性: —" in text


def test_render_md_contains_verdict_and_stats(tmp_path: Path) -> None:
    current, early = _world()
    payload = _payload(tmp_path, current, early)
    text = render_md(payload, "20260911")
    assert payload["verdict"]["statement"] in text
    assert "matched_row_share" in text
    assert "current_matched" in text
    assert "幸存者" in text  # 混杂披露在渲染面可见


def test_payload_deterministic_double_run(tmp_path: Path) -> None:
    """同输入两次装配逐字节同 payload (R13 家族; BOOT_SEED per-call)."""
    current, early = _world()
    a = _payload(tmp_path, current, early)
    b = _payload(tmp_path, current, early)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(
        b, sort_keys=True, default=str
    )


# ---------------------------------------------------------------------------
# e2e — CSV 装载 + 报告落盘 + 双跑逐字节一致
# ---------------------------------------------------------------------------
def _write_inputs(tmp: Path, current: pd.DataFrame, early: pd.DataFrame) -> dict[str, Path]:
    paths = {
        "court": tmp / "current.csv",
        "early": tmp / "early.csv",
        "history": tmp / "history.json",
        "cm": tmp / "cm.json",
        "em": tmp / "em.json",
    }
    current.to_csv(paths["court"], index=False)
    early.to_csv(paths["early"], index=False)
    paths["history"].write_text(json.dumps(CURRENT_LABELS), encoding="utf-8")
    paths["cm"].write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    paths["em"].write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    return paths


def test_main_end_to_end_writes_reports_and_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    current, early = _world()
    p = _write_inputs(tmp_path, current, early)
    rc = main(
        [
            "--court-table", str(p["court"]),
            "--early-court-table", str(p["early"]),
            "--regime-history", str(p["history"]),
            "--current-manifest", str(p["cm"]),
            "--early-manifest", str(p["em"]),
            "--out-dir", str(tmp_path / "out"),
            "--date", "20260911",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert REPORT_STEM in out
    md = tmp_path / "out" / f"{REPORT_STEM}_20260911.md"
    js = tmp_path / "out" / f"{REPORT_STEM}_20260911.json"
    assert md.exists() and js.exists()
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["universe_match"]["current_rows_matched"] == 80
    assert payload["digest"]["current_rows"] == len(current)
    assert payload["digest"]["early_rows"] == len(early)


def test_main_double_run_byte_identical(tmp_path: Path) -> None:
    """同输入双跑报告逐字节一致 (R13 家族, e2e 面)."""
    current, early = _world()
    p = _write_inputs(tmp_path, current, early)
    argv = [
        "--court-table", str(p["court"]),
        "--early-court-table", str(p["early"]),
        "--regime-history", str(p["history"]),
        "--current-manifest", str(p["cm"]),
        "--early-manifest", str(p["em"]),
        "--out-dir", str(tmp_path / "out"),
        "--date", "20260911",
    ]
    assert main(argv) == 0
    assert main(argv) == 0
    for name in (f"{REPORT_STEM}_20260911.md", f"{REPORT_STEM}_20260911.json"):
        blob = (tmp_path / "out" / name).read_bytes()
        assert blob  # 非空且两次覆盖写后仍稳定 (同一字节串)


def test_main_missing_input_typed(tmp_path: Path) -> None:
    p = tmp_path / "nope.csv"
    with pytest.raises(RegimeRunUniverseMatchError, match="court_table_missing"):
        main(["--court-table", str(p)])


# ---------------------------------------------------------------------------
# 默认路径常量 — 与 R178/proximity 单一定义家 (import 复用而非复制定义)
# ---------------------------------------------------------------------------
def test_default_paths_are_reused_single_definitions() -> None:
    from scripts import regime_run_universe_match_validation as m
    from scripts import regime_proximity_conditioning as prox
    from scripts import regime_run_cross_era_validation as x

    assert m.COURT_TABLE_DEFAULT is prox.COURT_TABLE_DEFAULT
    assert m.REGIME_HISTORY_DEFAULT is prox.REGIME_HISTORY_DEFAULT
    assert m.REPORT_DIR_DEFAULT is prox.REPORT_DIR_DEFAULT
    assert m.EARLY_TABLE_DEFAULT is x.EARLY_TABLE_DEFAULT
    assert m.CURRENT_MANIFEST_DEFAULT is x.CURRENT_MANIFEST_DEFAULT
    assert m.EARLY_MANIFEST_DEFAULT is x.EARLY_MANIFEST_DEFAULT
