"""ob_court_build / ob_court_report 口径核心纯函数测试 — OB 暂停复核 court 管道首张回归网.

锁定 (预注册契约):
- drop30_index 与生产 chained_return_pct 同数学 (prod(1+pct/100)-1, 30 行窗),
  窗口不足/任一 pct 缺失 → 不产出键 (与 detect 保守 miss 一致); 北交所排除;
- ticker_frame PIT 截断与列契约 (detect 语义输入);
- 生产 detect 忠实重放: 预筛放行的构造 fixture 也过 detect 条件 1 (同面板同数学);
- pause_verdict: 样本不足 → None (fail-closed 不判); 深负样本 → pause_holds True;
  强正样本 (CI 下界 > 0) → pause_holds False (如实上报, 不因结论方向改判定);
- 防覆盖护栏: 同指纹允许, 异指纹拒绝, force 例外 (btst_court 同族);
- net 口径 = gross - 65bps (与 btst_court_views.net_ret 同源)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ob_court_build import (  # noqa: E402
    _DROP_THRESHOLD,
    _LOOKBACK_DROP_ROWS,
    drop30_index,
    overwrite_allowed,
    ticker_frame,
)
from ob_court_report import JOURNAL_ANCHOR, pause_verdict  # noqa: E402


def _panel_group(pcts: list[float], dates: list[str] | None = None, ts: str = "600000.SH") -> pd.DataFrame:
    n = len(pcts)
    dates = dates or [f"2026{i:04d}" for i in range(1, n + 1)]  # 占位, 测试里都显式传
    close = np.cumprod(1 + np.array(pcts) / 100.0) * 10.0
    return pd.DataFrame({
        "ts_code": [ts] * n,
        "trade_date": dates,
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "pct_chg": pcts,
        "vol": [1000.0] * n,
    })


def _dates(n: int, start="20260101") -> list[str]:
    return pd.bdate_range(start, periods=n).strftime("%Y%m%d").tolist()


# ---------- drop30_index: 与生产 chained_return_pct 同数学 ----------


def test_drop30_matches_chained_return_pct():
    from src.screening.offensive.price_returns import chained_return_pct

    rng = np.random.default_rng(7)
    pcts = rng.normal(-0.5, 4, 60).round(4).tolist()  # 偏负漂移 → 若干窗口达 -20%
    panel = _panel_group(pcts, _dates(60))
    idx = drop30_index(panel)
    frame = ticker_frame(panel, "20991231")
    checked = 0
    for i in range(_LOOKBACK_DROP_ROWS, 60):
        d = panel["trade_date"].iloc[i]
        expect = chained_return_pct(frame, i - _LOOKBACK_DROP_ROWS, i)
        if expect is not None and expect <= _DROP_THRESHOLD:
            assert abs(idx[("600000.SH", d)] - expect) < 1e-9  # 达标键值一致
            checked += 1
        else:
            assert ("600000.SH", d) not in idx  # 未达标键不产出
    assert checked > 0  # 本种子确有达标窗口 (随机回归钉死种子)


def test_drop30_short_window_and_nan_excluded():
    # 30 行整 (i=29 是第一个可判行, 30×-1%=-26% 达标) — 29 行不可判
    panel = _panel_group([-1.0] * 31, _dates(31))
    idx = drop30_index(panel)
    assert ("600000.SH", panel["trade_date"].iloc[28]) not in idx
    assert ("600000.SH", panel["trade_date"].iloc[29]) in idx
    pcts = [-1.0] * 35
    pcts[33] = float("nan")
    panel2 = _panel_group(pcts, _dates(35))
    idx2 = drop30_index(panel2)
    assert ("600000.SH", panel2["trade_date"].iloc[34]) not in idx2  # NaN 在窗内 → 排除
    assert ("600000.SH", panel2["trade_date"].iloc[32]) in idx2  # 窗内无 NaN (0..32 恒 -1%) → 达标


def test_drop30_threshold_boundary_and_bj_excluded():
    # 达标 (-21%) 放行 / 未达标 (-19%) 不产出 — 与 detect 条件 1 阈值互补
    for daily, expect_in in ((-0.78, True), (-0.70, False)):  # 30 日复合 ≈ -21% / -19%
        panel = _panel_group([0.0] + [daily] * 30, _dates(31))
        idx = drop30_index(panel)
        key = ("600000.SH", panel["trade_date"].iloc[30])
        assert (key in idx) is expect_in
    bj = _panel_group([-1.0] * 31, _dates(31), ts="832000.BJ")
    assert drop30_index(bj) == {}  # 北交所排除 (即使达标)


# ---------- 生产 detect 忠实重放: 预筛放行 ⇒ detect 条件 1 也过 ----------


def test_prefilter_passes_detect_condition1():
    from src.screening.offensive.price_returns import chained_return_pct

    pcts = [0.2] * 29 + [-2.0] * 15  # 深跌尾段 → 末日 30d 链 ≈ -23.7% ≤ -20%
    panel = _panel_group(pcts, _dates(44))
    frame = ticker_frame(panel, panel["trade_date"].iloc[-1])
    # 预筛放行的 (drop ≤ -20), 生产 detect 同款链式跌幅也放行 — 同面板同数学
    drop = chained_return_pct(frame, len(frame) - 31, len(frame) - 1)
    assert drop <= _DROP_THRESHOLD
    # 反向: 温和窗口 (链 ≈ -9.5%) 预筛不放行, detect 条件 1 同样 miss
    mild = [0.2] * 29 + [-0.7] * 15
    panel2 = _panel_group(mild, _dates(44))
    frame2 = ticker_frame(panel2, panel2["trade_date"].iloc[-1])
    drop2 = chained_return_pct(frame2, len(frame2) - 31, len(frame2) - 1)
    assert drop2 > _DROP_THRESHOLD


# ---------- ticker_frame: PIT 截断 + 列契约 ----------


def test_ticker_frame_pit_truncation_and_columns():
    panel = _panel_group([1.0, -1.0, 0.5], _dates(3))
    upto = panel["trade_date"].iloc[1]
    frame = ticker_frame(panel, upto)
    assert list(frame.columns) == ["date", "open", "high", "low", "close", "volume", "pct_change"]
    assert len(frame) == 2
    assert frame.iloc[-1]["date"].replace("-", "") == upto
    assert str(frame["pct_change"].iloc[-1]) == str(-1.0)


# ---------- pause_verdict: 预注册谓词 ----------


def _events(rets: list[float], dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "fillable": [True] * len(rets),
        "gross_ret_t5": rets,
        "signal_date": dates,
    })


def test_pause_verdict_insufficient_sample_fail_closed():
    v = pause_verdict(_events([0.01] * 10, _dates(10)))
    assert v["pause_holds"] is None and v["n"] == 10


def test_pause_verdict_deeply_negative_holds_pause():
    rng = np.random.default_rng(3)
    rets = (rng.normal(-0.03, 0.05, 400)).tolist()
    v = pause_verdict(_events(rets, _dates(400)))
    assert v["mean_net"] < 0
    assert v["pause_holds"] is True


def test_pause_verdict_strong_positive_flags_owner_review():
    rng = np.random.default_rng(4)
    rets = (rng.normal(+0.05, 0.02, 400)).tolist()
    v = pause_verdict(_events(rets, _dates(400)))
    assert v["mean_net"] > 0
    assert v["ci_low_90"] > 0
    assert v["pause_holds"] is False  # 如实: 上报复议, 不因方向改判定


def test_pause_verdict_excludes_unfillable_and_missing():
    df = _events([0.01] * 50, _dates(50))
    df.loc[0, "fillable"] = False
    df.loc[1, "gross_ret_t5"] = None
    v = pause_verdict(df)
    assert v["n"] == 48


# ---------- 防覆盖护栏 (btst_court 同族) ----------


def test_overwrite_guard_same_fp_allowed_diff_refused_force_exception():
    assert overwrite_allowed(None, "aa", force=False) is True
    assert overwrite_allowed("aa", "aa", force=False) is True
    assert overwrite_allowed("aa", "bb", force=False) is False
    assert overwrite_allowed("aa", "bb", force=True) is True


# ---------- net 口径 & 对照锚 ----------


def test_net_ret_65bps_and_journal_anchor_disclosed():
    from btst_court_views import net_ret

    gross = pd.Series([0.0, 0.1])
    net = net_ret(gross, 30.0)
    assert abs((net - gross).iloc[0] + 0.0065) < 1e-12  # 2×30bps + 5bps
    assert JOURNAL_ANCHOR["n"] == 56 and JOURNAL_ANCHOR["mean"] == -0.0215


# ---------- R230 Op1: 双指纹行为等价实证门 ----------
# 旧护栏只比对 oversold_bounce_sha256 (price_returns_sha256 漂移被静默放行,
# 而它是 gross_ret_t3/t5/t10 全部收益列的计算源) — 本节钉死三态门双指纹面:
# 同指纹放行零披露 / 任一组件漂移即触发等价实证 / 等价失败类型化拒绝 /
# force 披露含先验 dict 与漂移组件 / main() 接线 AST 结构钉 (R229 P15-P17 家族)。

import ast  # noqa: E402

from btst_court_build import (  # noqa: E402
    _formula_change_rejection_message,
    evaluate_formula_change_gate,
)

OB_FP_KEYS = ("oversold_bounce_sha256", "price_returns_sha256")
OB_WINDOW = {"start": 20250701, "end": 20250703}


def _ob_row(ts, date, *, strength=0.6, ret5=0.02, ret10=0.03):
    return {
        "ts_code": ts,
        "signal_date": date,
        "regime": "normal",
        "trigger_strength": strength,
        "gross_ret_t5": ret5,
        "gross_ret_t3": 0.01,
        "gross_ret_t10": ret10,
    }


_OB_ROWS = [
    _ob_row("000001.SZ", 20250701),
    _ob_row("000002.SZ", 20250702, strength=0.55, ret5=-0.01, ret10=-0.02),
    _ob_row("300003.SZ", 20250703, ret10=None),
]

_OB_COLS = list(_OB_ROWS[0].keys())


def _ob_manifest(fps, window=None):
    return {"formula_fingerprint": dict(fps), "window": window or OB_WINDOW}


def _write_ob_prior(tmp_path, rows, fps):
    frame = pd.DataFrame(rows)[_OB_COLS]
    path = tmp_path / "ob_event_table_v1.csv.gz"
    frame.to_csv(path, index=False, compression="gzip")
    return path


def _ob_candidate(rows):
    return pd.DataFrame(rows)[_OB_COLS]


def test_gate_dual_same_fingerprints_allow_zero_disclosure(tmp_path):
    prior_path = _write_ob_prior(tmp_path, _OB_ROWS, "aa")
    fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    gate = evaluate_formula_change_gate(
        _ob_manifest(fps),
        prior_path,
        dict(fps),
        _ob_candidate(_OB_ROWS),
        force=False,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    assert gate.manifest_fields == {}
    assert gate.rejection_reason is None


def test_gate_price_returns_only_drift_equal_rows_allows_with_disclosure(tmp_path):
    # 新牙: price_returns_sha256 单独漂移 (收益列计算源变化) 必须进等价实证,
    # 重叠窗口逐值相等才放行并诚实披露 — 旧 main() 对该漂移零防御。
    prior_path = _write_ob_prior(tmp_path, _OB_ROWS, "aa")
    prior_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    new_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "dd"}
    gate = evaluate_formula_change_gate(
        _ob_manifest(prior_fps),
        prior_path,
        new_fps,
        _ob_candidate(_OB_ROWS),
        force=False,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    fields = gate.manifest_fields
    assert fields["formula_change_equivalence_verified"] is True
    assert fields["prior_formula_fingerprint"] == prior_fps
    assert fields["equivalence_proof"]["key_columns"] == ["ts_code", "signal_date"]
    assert fields["equivalence_proof"]["overlap_events"] == 3


def test_gate_price_returns_drift_value_mutation_rejects_ob_named(tmp_path):
    prior_path = _write_ob_prior(tmp_path, _OB_ROWS, "aa")
    prior_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    new_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "dd"}
    mutated = [dict(_OB_ROWS[0], gross_ret_t5=0.05)] + _OB_ROWS[1:]
    gate = evaluate_formula_change_gate(
        _ob_manifest(prior_fps),
        prior_path,
        new_fps,
        _ob_candidate(mutated),
        force=False,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is False
    assert gate.rejection_reason == "overlap_mismatch"
    message = _formula_change_rejection_message(
        gate.rejection_reason, table_label="ob_event_table_v1"
    )
    assert message.startswith("ob_event_table_v1 ")
    assert "--rebuild-force" in message


def test_gate_force_discloses_prior_dict_and_drift_keys(tmp_path):
    prior_fps = {"oversold_bounce_sha256": "aa", "price_returns_sha256": "cc"}
    new_fps = {"oversold_bounce_sha256": "bb", "price_returns_sha256": "cc"}
    gate = evaluate_formula_change_gate(
        _ob_manifest(prior_fps),
        None,
        new_fps,
        _ob_candidate(_OB_ROWS),
        force=True,
        fingerprint_keys=OB_FP_KEYS,
    )
    assert gate.allowed is True
    assert gate.manifest_fields == {
        "formula_change_forced": True,
        "prior_formula_fingerprint": prior_fps,
        "formula_drift_keys": ["oversold_bounce_sha256"],
    }


def test_main_wires_dual_fingerprint_gate_ast_pin():
    # R229 P15-P17 家族: 纯函数钉全绿而 main() 接线可整体退回旧单态语义 —
    # AST 结构钉锁死 main() 必经三态门且拒绝路径走 ob 表名消息。
    source = (Path(__file__).resolve().parents[1] / "scripts" / "ob_court_build.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    mains = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert len(mains) == 1
    fn = mains[0]
    gate_calls = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "evaluate_formula_change_gate"
    ]
    assert len(gate_calls) == 1, "main() 必须恰一次调用 evaluate_formula_change_gate"
    keywords = {kw.arg for kw in gate_calls[0].keywords}
    assert "force" in keywords and "fingerprint_keys" in keywords
    # 双指纹键必须在场 (词法钉): 只比对 oversold 单键的旧形态不可回归
    assert "price_returns_sha256" in source and "OB_FINGERPRINT_KEYS" in source
    # 拒绝路径: 门拒绝必须经 SystemExit + _formula_change_rejection_message
    # (table_label 标 ob 表名); main() 其余既有 fail-closed SystemExit 不约束。
    gate_rejections = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and getattr(node.exc.func, "id", "") == "SystemExit"
        and any(
            isinstance(arg, ast.Call)
            and getattr(arg.func, "id", "") == "_formula_change_rejection_message"
            for arg in node.exc.args
        )
    ]
    assert len(gate_rejections) == 1, "门拒绝路径必须恰一处 SystemExit 经 _formula_change_rejection_message"
    assert "table_label" in source, "拒绝消息必须显式标注 ob 表名"
    # 旧单态接线不可回归: main() 不得再直呼 overwrite_allowed (决策面唯一经门)
    assert not any(
        isinstance(node, ast.Call) and getattr(node.func, "id", "") == "overwrite_allowed"
        for node in ast.walk(fn)
    ), "main() 不得绕过三态门直呼 overwrite_allowed"


def test_main_wiring_surface_ast_pin():
    # R230 Op2 探针运动补钉 (P10-P14 真盲区家族, 全部 RED-on-mutant 先证):
    # AST 结构钉的已知致盲形态 — 恒假死分支 / 披露字段不并入 / 单键内联 /
    # manifest 单指纹 — 逐项钉死 (R229 P15-P17 家族续)。
    source = (Path(__file__).resolve().parents[1] / "scripts" / "ob_court_build.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"][0]
    gate_call = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "evaluate_formula_change_gate"
    ][0]
    # P13: fingerprint_keys 必须引用 OB_FINGERPRINT_KEYS 单一来源 (内联元组
    # 漂移成单键后 price_returns 漂移静默放行的旧缺口不可回归)
    fk = [kw for kw in gate_call.keywords if kw.arg == "fingerprint_keys"][0]
    assert isinstance(fk.value, ast.Name) and fk.value.id == "OB_FINGERPRINT_KEYS"
    # P11: manifest 必须并入 **gate.manifest_fields (R229 P16 家族 — 门放行
    # 的等价/force 披露不得在落盘 manifest 时被静默丢弃)
    assert any(
        isinstance(d, ast.Dict)
        and any(
            k is None and isinstance(v, ast.Attribute) and v.attr == "manifest_fields"
            for k, v in zip(d.keys, d.values)
        )
        for d in ast.walk(fn)
    ), "manifest 必须并入 **gate.manifest_fields"
    # P14: manifest formula_fingerprint 必须写 new_fps 双指纹单一来源
    # (只记 oversold 单键 = price_returns 组件失去下一轮门判定资格)
    assert any(
        isinstance(d, ast.Dict)
        and any(
            isinstance(k, ast.Constant)
            and k.value == "formula_fingerprint"
            and isinstance(v, ast.Name)
            and v.id == "new_fps"
            for k, v in zip(d.keys, d.values)
        )
        for d in ast.walk(fn)
    ), "manifest formula_fingerprint 必须携带 new_fps 双指纹"
    # P10: 恒假 If 是 AST 结构钉的致盲形态 (死分支保语法失语义) — main()
    # 禁止任何可静态判定恒假的测试 (裸 False 与 False and X 两形态均被
    # P10 探针实证致盲, 本钉判别力经两形态突变当场红证明)

    def _is_dead_test(t):
        if isinstance(t, ast.Constant) and t.value is False:
            return True
        return isinstance(t, ast.BoolOp) and isinstance(t.op, ast.And) and any(
            isinstance(v, ast.Constant) and v.value is False for v in t.values
        )

    dead = [n for n in ast.walk(fn) if isinstance(n, ast.If) and _is_dead_test(n.test)]
    assert not dead, "main() 不得含恒假死分支 (门拒绝路径必须活的)"
    # P12: rebuild_count 递增锚 (R229 P17 词法钉先例) — 沿袭计数语义不可丢
    assert 'rebuild_count = int(prior_manifest.get("rebuild_count", 0)) + 1' in source
