"""封板反转稳健性三连契约 (R66)。非对称合成四态: 全过 / 时段翻转 / 离群驱动 /
与主因子共线 — 每一态只让一项检查变 false (归因精确)。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from seal_inversion_robustness import RobustnessError, run_triage  # noqa: E402

DAYS = 40
PER_DAY = 12


def _synthetic_world(tmp_path: Path, *, mode: str):
    """合成 court 表 + seal 因子 csv。

    基础构造: seal_inverted (即 −seal) 与 net_t10 正相关 (每票的收益由
    「弱封板程度」线性驱动 + 噪声), strength 独立随机 — 三项应全过。
    mode 变换:
      flip   — 后半段相关性翻转 (收益改由 −弱封板驱动) → split-half false
      outlier— 相关性只由每天 1 个巨大离群收益撑起 → winsorize 后 false
      colin  — 收益改由 strength 驱动, seal 与 strength 完全共线 → 正交后 false
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
    weak = rng.index.to_series().mod(PER_DAY) / (PER_DAY - 1)   # 0..1 弱封板度
    # 种子化均匀噪声 (R13 纪律: 确定性; 且日内非单调 — 旧 (i*7919%1000)
    # 锯齿在 12 行的日内窗口里近似单调, 与弱封板度同源污染噪声日 IC)
    import numpy as np
    noise = pd.Series(np.random.default_rng(20260829).uniform(-0.5, 0.5, n))
    strength = pd.Series([((i * 104729) % 1000) / 1000 for i in range(n)])
    first_half = (rng.index < n / 2)
    if mode == "flip":
        direction = pd.Series([1.0 if fh else -1.0 for fh in first_half])
        gross = 0.02 + 0.10 * weak * direction + 0.01 * noise
    elif mode == "outlier":
        # 极端日依赖 (确定性, 无 RNG): 仅前 3 个信号日对齐 (IC=+1), 其余 37 日
        # 收益秩按置换 π 排布——Σ(i−5.5)(π(i)−5.5) = Σi·π(i)−363 = 506−143−363 = 0,
        # 日度 Spearman 恰为 0 → 均值 3/40 被极端日撑起为正, 中位数 = 0
        # (集中依赖判死), 后半段均值 = 0 (split-half 同死)
        zero_perm = [10, 6, 5, 3, 7, 2, 1, 4, 8, 9, 0, 11]
        day_idx = rng.index.to_series() // PER_DAY
        within = rng.index.to_series().mod(PER_DAY)
        gross = pd.Series([
            0.01 + 0.10 * weak.iloc[i] if day_idx.iloc[i] < 3
            else 0.01 + 0.001 * zero_perm[within.iloc[i]]
            for i in range(n)
        ])
    elif mode == "colin":
        strength = 1 - weak                               # 完全共线
        gross = 0.02 + 0.10 * strength + 0.01 * noise     # 收益由 strength 驱动
    else:
        gross = 0.02 + 0.10 * weak + 0.01 * noise
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
    seal = rng[["signal_date", "ts_code"]].copy()
    seal["factor"] = 1 - weak                            # 封板质量 = 1−弱封板度
    seal_path = tmp_path / "seal.csv"
    seal.to_csv(seal_path, index=False)
    return court_path, seal_path


def _verdict(tmp_path: Path, mode: str) -> dict:
    court, seal = _synthetic_world(tmp_path, mode=mode)
    return run_triage(court_path=court, seal_csv=seal)


def test_stable_inversion_qualifies(tmp_path: Path) -> None:
    payload = _verdict(tmp_path, "stable")
    assert payload["verdict"] == "qualifies"
    assert all(payload["checks"][k].get("same_sign", False) or
               payload["checks"][k].get("still_positive", False)
               for k in ("split_half", "winsorized", "orthogonal_vs_main"))
    # winsorize IC 是「因子 vs 截尾收益」的相关; 传错列名 "net_t10" 时该值
    # 恒为恰 1.0 (自相关, 离群检查永不判死)——真相关因截尾微扰严格小于 1
    assert payload["checks"]["winsorized"]["ic_winsorized"] < 1.0


def test_sign_flip_second_half_fails_split_half(tmp_path: Path) -> None:
    payload = _verdict(tmp_path, "flip")
    assert payload["checks"]["split_half"]["same_sign"] is False
    assert payload["verdict"] == "rejected"


def test_extreme_day_dependence_fails_ic_median(tmp_path: Path) -> None:
    # 仅前 3 日携带对齐信息: 日度 IC 均值为正但中位数 ≈ 噪声水平 → 判死
    payload = _verdict(tmp_path, "outlier")
    assert payload["verdict"] == "rejected"
    assert payload["checks"]["winsorized"]["same_sign"] is False
    assert payload["checks"]["split_half"]["same_sign"] is False


def test_collinear_with_main_fails_orthogonal(tmp_path: Path) -> None:
    payload = _verdict(tmp_path, "colin")
    assert abs(payload["checks"]["orthogonal_vs_main"]["mean_rank_corr_with_main"]) > 0.99
    assert payload["checks"]["orthogonal_vs_main"]["still_positive"] is False
    assert payload["verdict"] == "rejected"


def test_missing_inputs_typed(tmp_path: Path) -> None:
    with pytest.raises(RobustnessError) as ei:
        run_triage(court_path=tmp_path / "no.csv", seal_csv=tmp_path / "no2.csv")
    assert ei.value.code == "court_table_not_found"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
