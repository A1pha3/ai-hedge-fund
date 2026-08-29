"""行业动量因子契约 (R62, 对抗审查 A/B/C 落 C)。

全合成 hermetic。钉死:
- **PIT**: D 当日的指数收盘不得进入 D 的因子值 (巨值对照) — T0 收盘决策
  只可用 T-1 晚间已发布的指数数据。
- 动量正确性: lookback 会话收盘比手算精确相等。
- 行业缺失/映射缺失/序列缺段 → NaN 行如实计数, 不冒充中性值。
- 预注册单一规格: lookback=20 (改动规格=新候选重注册, 不是调参)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_industry_momentum_factor import (  # noqa: E402
    IndustryFactorError,
    build_factor,
)

CAL = [f"2026{m:02d}{d:02d}" for m in range(1, 7) for d in range(1, 29)]
# 去掉周末 (周六=5): 2026-01-03 是周六 → 简化: 直接顺序会话即可, 日历是权威
CAL = CAL[:60]  # 60 个顺序"会话"


def _world(tmp_path: Path, court: pd.DataFrame, indices: dict[str, list[float]]):
    court_path = tmp_path / "court.csv"
    court.to_csv(court_path, index=False)
    ind_dir = tmp_path / "ind"
    ind_dir.mkdir()
    codes = {"钢铁": "801040.SI", "煤炭": "801960.SI"}
    (ind_dir / "_industry_codes.json").write_text(
        json.dumps({v: k for k, v in codes.items()}), encoding="utf-8")
    for code, closes in indices.items():
        pd.DataFrame({
            "trade_date": CAL[: len(closes)],
            "close": closes,
        }).to_csv(ind_dir / f"{code}.csv", index=False)
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps(CAL), encoding="utf-8")
    return court_path, ind_dir, cal


def _court(signal_date: str, industry: str, ticker: str = "000001.SZ") -> pd.DataFrame:
    return pd.DataFrame([{
        "signal_date": signal_date, "ts_code": ticker,
        "industry_name": industry,
    }])


def test_momentum_exact_and_pit_safe(tmp_path: Path) -> None:
    # 30 个会话收盘 1.0..30; 因子(第 25 个会话) 用到第 24 与第 4 个的收盘
    closes = [float(i + 1) for i in range(30)]
    court = _court(CAL[24], "钢铁")
    court_path, ind_dir, cal = _world(tmp_path, court, {"801040.SI": closes})
    factor, summary = build_factor(court_path=court_path, ind_dir=ind_dir,
                                   calendar_path=cal, lookback=20)
    row = factor.iloc[0]
    # prior = CAL[:24], t_last=CAL[23] (close 24), t_start=CAL[3] (close 4)
    assert row["factor"] == pytest.approx(24.0 / 4.0 - 1.0)
    assert summary["factor_rows"] == 1
    assert summary["missing_momentum_rows"] == 0


def test_pit_day_d_close_never_enters(tmp_path: Path) -> None:
    """生死线: D 当日收盘巨值不得影响 D 的因子。"""
    closes = [1.0] * 30
    closes[24] = 9_999_999.0  # D 当日 (CAL[24]) 巨值
    court = _court(CAL[24], "钢铁")
    court_path, ind_dir, cal = _world(tmp_path, court, {"801040.SI": closes})
    factor, _ = build_factor(court_path=court_path, ind_dir=ind_dir,
                             calendar_path=cal, lookback=20)
    assert factor.iloc[0]["factor"] == pytest.approx(0.0)  # 全 1.0 序列 → 动量 0


def test_missing_industry_and_mapping_counted(tmp_path: Path) -> None:
    court = pd.DataFrame([
        {"signal_date": CAL[25], "ts_code": "000001.SZ", "industry_name": ""},
        {"signal_date": CAL[25], "ts_code": "000002.SZ", "industry_name": "房地产"},  # 无映射
        {"signal_date": CAL[25], "ts_code": "000003.SZ", "industry_name": "钢铁"},
    ])
    closes = [1.0 + i * 0.01 for i in range(30)]
    court_path, ind_dir, cal = _world(tmp_path, court, {"801040.SI": closes})
    factor, summary = build_factor(court_path=court_path, ind_dir=ind_dir,
                                   calendar_path=cal, lookback=20)
    # 钢铁行有值; 空行业计 missing_industry; 房地产计 missing_momentum
    assert set(factor["ts_code"]) == {"000003.SZ"}
    assert summary["missing_industry_rows"] == 1
    assert summary["missing_momentum_rows"] == 1


def test_insufficient_history_is_none_not_fake(tmp_path: Path) -> None:
    closes = [1.0] * 10  # 序列只有 10 段 < lookback+1
    court = _court(CAL[25], "钢铁")
    court_path, ind_dir, cal = _world(tmp_path, court, {"801040.SI": closes})
    factor, summary = build_factor(court_path=court_path, ind_dir=ind_dir,
                                   calendar_path=cal, lookback=20)
    assert len(factor) == 0
    assert summary["missing_momentum_rows"] == 1


def test_calendar_stale_and_missing_court(tmp_path: Path) -> None:
    closes = [1.0] * 30
    court = _court(CAL[25], "钢铁")
    court_path, ind_dir, _ = _world(tmp_path, court, {"801040.SI": closes})
    stale_cal = tmp_path / "stale.json"
    stale_cal.write_text(json.dumps(CAL[:10]), encoding="utf-8")
    with pytest.raises(IndustryFactorError) as ei:
        build_factor(court_path=court_path, ind_dir=ind_dir,
                     calendar_path=stale_cal, lookback=20)
    assert ei.value.code == "calendar_stale"
    with pytest.raises(IndustryFactorError) as ei2:
        build_factor(court_path=tmp_path / "absent.csv", ind_dir=ind_dir,
                     calendar_path=tmp_path / "cal.json", lookback=20)
    assert ei2.value.code == "court_table_not_found"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
