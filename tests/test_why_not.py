"""P0-8 --why-not 反事实解释测试。"""

from __future__ import annotations

import json
from pathlib import Path

from src.cli.why_not import run_why_not


def _make_rec(
    ticker: str,
    score_b: float,
    direction_trend: int = 1,
    name: str = "示例股",
) -> dict:
    """构造一条推荐记录 (含 strategy_signals)。"""
    return {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "decision": "bullish" if score_b > 0 else "bearish" if score_b < 0 else "neutral",
        "industry_sw": "示例行业",
        "strategy_signals": {
            "trend": {"direction": direction_trend, "confidence": 60.0},
            "mean_reversion": {"direction": -direction_trend, "confidence": 30.0},
            "fundamental": {"direction": 0, "confidence": 50.0},
            "event_sentiment": {"direction": 1, "confidence": 40.0},
        },
    }


def _write_report(
    reports_dir: Path,
    *,
    trade_date: str = "20260609",
    top_n: int = 5,
    recommendations: list[dict] | None = None,
) -> Path:
    """写一份 minimal auto_screening_*.json 报告。"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "auto_screening",
        "date": trade_date,
        "market_state": {
            "state_type": "trend_up",
            "position_scale": 0.85,
            "regime_gate_level": "normal",
        },
        "top_n": top_n,
        "recommendations": recommendations
        or [_make_rec("300724", 0.78), _make_rec("600519", 0.65), _make_rec("000001", 0.55)],
    }
    path = reports_dir / f"auto_screening_{trade_date}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ── 测试 ──────────────────────────────────────────────────────────────────


def test_ticker_already_recommended(tmp_path: Path, capsys) -> None:
    """State 1: ticker 在 recommendations 中 → 提示用 --explain 而非 --why-not。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("000001", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    assert "已被推荐" in captured.out
    assert "--explain" in captured.out


def test_ticker_not_in_recommendations_outputs_4_blocks(tmp_path: Path, capsys) -> None:
    """State 2: ticker 不在 recommendations → 主战场, 4 个区块全部输出。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    # 600777 是个不存在于 recommendations 的 ticker
    rc = run_why_not("600777", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 4 个区块标题必须全部出现
    assert "区块 1: 策略方向冲突" in captured.out
    assert "区块 2: confidence 不足" in captured.out
    assert "区块 3: 排除规则" in captured.out
    assert "区块 4: 反事实模拟" in captured.out


def test_counterfactual_covers_3_plus_strategies(tmp_path: Path, capsys) -> None:
    """验收标准: 反事实模拟至少覆盖 3 个策略。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("600777", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 反事实区块必须出现以下策略中的至少 3 个
    expected_strategies = ["trend", "mean_reversion", "fundamental", "event_sentiment"]
    found = [s for s in expected_strategies if s in captured.out]
    assert len(found) >= 3, f"反事实模拟只覆盖 {len(found)} 个策略, 期望 ≥ 3: {found}"


def test_no_auto_screening_returns_1(tmp_path: Path, capsys) -> None:
    """无报告目录时返回 1。"""
    rc = run_why_not("000001", reports_dir=tmp_path / "empty")
    captured = capsys.readouterr()

    assert rc == 1
    assert "请先运行 --auto" in captured.out


def test_north_exchange_ticker_excluded(tmp_path: Path, capsys) -> None:
    """北交所 ticker (8xxxxx) → 区块 3 必须明确指出「北交所」排除。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("830001", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 区块 3 标题
    assert "区块 3: 排除规则" in captured.out
    # 北交所必须被显式提及
    assert "北交所" in captured.out
    # 830001 应被识别为北交所
    assert "命中" in captured.out  # 命中北交所


def test_top_n_cutoff_in_confidence_block(tmp_path: Path, capsys) -> None:
    """区块 2 应输出 Top 1 / 中位数 / 末位的 score_b。"""
    reports_dir = tmp_path / "data" / "reports"
    recs = [
        _make_rec("300724", 0.80),
        _make_rec("600519", 0.60),
        _make_rec("000001", 0.40),
    ]
    _write_report(reports_dir, recommendations=recs)

    rc = run_why_not("999999", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    assert "Top 1:" in captured.out
    assert "中位数:" in captured.out
    assert "末位:" in captured.out
    # 末位票 000001 应被列出
    assert "000001" in captured.out
