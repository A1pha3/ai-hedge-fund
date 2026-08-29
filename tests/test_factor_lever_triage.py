"""候选因子杠杆级 triage 契约 (R68)。非对称合成世界: 稳定杠杆全过 /
时段翻号 split-half 拒 / 确定性 pin / 缺文件 typed——每一态归因精确。
(镜像 R66 稳健性测试的纪律; 合取判定 = uplift>0 ∧ 双半同正 ∧ CI90 下界>0)"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from factor_lever_triage import LeverTriageError, run_triage  # noqa: E402

DAYS = 60
PER_DAY = 12


def _synthetic_world(tmp_path: Path, *, mode: str):
    """合成 court 表 + 因子 csv (方向=invert: cand = −factor = 因子低值偏好)。

    基础: strength 每日恰 6 行 ≥0.5 (保证门内日 ≥MIN_DAY_ROWS, 不靠运气);
    cand iid uniform, 独立于 strength; 收益由 cand 线性驱动 + 种子化微噪声。
      stable   — 全窗同向 (+0.12/cand) → 各杠杆 uplift 双半同正, CI 下界>0
      signflip — 后半效应翻转 (−0.12) → split_half 拒
    """
    import datetime as dt
    d0 = dt.date(2026, 1, 5)
    sessions = []
    d = d0
    while len(sessions) < DAYS:
        if d.weekday() < 5:
            sessions.append(d.strftime("%Y%m%d"))
        d += dt.timedelta(days=1)
    rng = pd.DataFrame([{"signal_date": s, "ts_code": f"{i:06d}.SZ"}
                        for s in sessions for i in range(PER_DAY)])
    n = len(rng)
    rs = np.random.default_rng(20260830)
    noise = rs.uniform(-0.002, 0.002, n)          # iid 微噪声 (R13: 非单调)
    inv = pd.Series(rs.uniform(0.0, 1.0, n))       # cand (invert 后)
    # 每日恰 6 行 strength ≥ 0.5, 行内随机重排 (门内行数确定性 ≥5)
    lo = rs.uniform(0.05, 0.45, PER_DAY // 2)
    hi = rs.uniform(0.55, 0.99, PER_DAY // 2)
    strength = pd.Series(np.concatenate([rs.permutation(np.concatenate([lo, hi]))
                                         for _ in range(DAYS)]))
    first_half = (rng.index < n / 2)
    if mode == "signflip":
        direction = pd.Series([1.0 if fh else -1.0 for fh in first_half])
        gross = 0.03 + 0.12 * inv * direction + noise
    else:
        gross = 0.03 + 0.12 * inv + noise
    court = pd.DataFrame({
        "signal_date": rng["signal_date"],
        "ts_code": rng["ts_code"],
        "regime": "normal",
        "fillable": True,
        "gate_blocked": False,
        "degraded": False,
        "st_name": False,
        "industry_missing": False,
        "excluded_ticker": False,
        "price_ge_3": True,
        "trigger_strength": strength,
        "gross_ret_t10": gross,
    })
    court_path = tmp_path / "court.csv"
    court.to_csv(court_path, index=False)
    factor = rng[["signal_date", "ts_code"]].copy()
    factor["factor"] = 1 - inv                     # invert 后 = inv
    factor_path = tmp_path / "factor.csv"
    factor.to_csv(factor_path, index=False)
    return court_path, factor_path


def _verdict(tmp_path: Path, mode: str) -> dict:
    court, factor = _synthetic_world(tmp_path, mode=mode)
    return run_triage(court_path=court, factor_csv=factor, factor_direction="invert")


def test_stable_lever_qualifies(tmp_path: Path) -> None:
    payload = _verdict(tmp_path, "stable")
    assert payload["verdict"] == "challenger_ready"
    gate_tilt = payload["levers"]["gate_tilt"]
    assert gate_tilt["qualifies"] is True
    assert gate_tilt["split_half"]["h1"] > 0 and gate_tilt["split_half"]["h2"] > 0
    assert gate_tilt["bootstrap"]["ci90_low"] > 0


def test_sign_flip_fails_split_half(tmp_path: Path) -> None:
    payload = _verdict(tmp_path, "signflip")
    assert payload["verdict"] == "deferred"
    gate_tilt = payload["levers"]["gate_tilt"]
    assert gate_tilt["split_half"]["same_sign"] is False
    assert gate_tilt["qualifies"] is False


def test_deterministic_per_call(tmp_path: Path) -> None:
    a = _verdict(tmp_path, "stable")
    b = _verdict(tmp_path, "stable")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_missing_inputs_typed(tmp_path: Path) -> None:
    with pytest.raises(LeverTriageError) as ei:
        run_triage(court_path=tmp_path / "no.csv",
                   factor_csv=tmp_path / "no2.csv")
    assert ei.value.code == "court_table_not_found"


def test_duplicate_factor_keys_typed(tmp_path: Path) -> None:
    court, factor = _synthetic_world(tmp_path, mode="stable")
    dup = pd.read_csv(factor, dtype={"signal_date": str, "ts_code": str})
    dup = pd.concat([dup, dup.head(1)], ignore_index=True)   # 塞一行重复键
    bad = tmp_path / "dup.csv"
    dup.to_csv(bad, index=False)
    with pytest.raises(LeverTriageError) as ei:
        run_triage(court_path=court, factor_csv=bad, factor_direction="invert")
    assert ei.value.code == "factor_csv_duplicate_keys"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
