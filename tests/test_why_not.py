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


def test_score_b_null_does_not_crash_confidence_block(tmp_path: Path, capsys) -> None:
    """R76 (R73 同族): recommendation 中 score_b 为 JSON null 不得让 --why-not 崩溃。

    ``score_b`` 在生产里通常是 float, 但部分推荐 (例如只进了 candidate_pool 但未完成
    composite scoring 的标的) 在 JSON 里可能是 ``null``。 ``.get("score_b", 0.0)`` 默认值
    只在 key 缺失时生效, key 存在且为 null 时返回 None, 裸 ``float(None)`` 抛 TypeError,
    一条 malformed rec 让整个 ``--why-not`` 4-区块解释器崩溃。
    """
    reports_dir = tmp_path / "data" / "reports"
    recs = [
        _make_rec("300724", 0.80),
        # 模拟一条 score_b=null 的残缺推荐 (例如 scoring 中途失败)
        {"ticker": "600519", "name": "贵州茅台", "score_b": None, "decision": "neutral",
         "strategy_signals": {}},
    ]
    _write_report(reports_dir, recommendations=recs)

    rc = run_why_not("999999", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # null score_b 必须被当作 0.0 处理, 区块 2 仍正常渲染
    assert "区块 2: confidence 不足" in captured.out
    assert "末位:" in captured.out


def test_score_b_null_in_already_recommended_does_not_crash(tmp_path: Path, capsys) -> None:
    """R76 (R73 同族): State 1 命中 score_b=null 的 rec 不得在格式化 ``{score_b:+.4f}`` 时崩溃。

    与 ``test_score_b_null_does_not_crash_confidence_block`` 同根因, 但触发点是
    ``_print_already_recommended`` 的 f-string format — ``None:+.4f`` 抛 TypeError。
    """
    reports_dir = tmp_path / "data" / "reports"
    recs = [
        {"ticker": "000001", "name": "平安银行", "score_b": None, "decision": "neutral",
         "strategy_signals": {}},
    ]
    _write_report(reports_dir, recommendations=recs)

    rc = run_why_not("000001", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    assert "已被推荐" in captured.out
    # null 必须降级为 0.0, 不得崩 format string
    assert "Score B:" in captured.out


def test_confidence_block_last_pick_matches_min_score(tmp_path: Path, capsys) -> None:
    """R76: 区块 2 「末位票」标签必须指向 score_b 真正最低的那条 rec, 而非 recs[-1]。

    recs 在 auto_screening_*.json 里的顺序由 ranking 逻辑决定, 不保证按 score_b 升序,
    所以 ``recs[-1]`` 不一定是末位。原代码 ``末位票: recs[-1]`` 在 recs 未排序时会标
    错标的, 与上面「末位: <min>  ← 门槛」自相矛盾, 误导 power-user 反事实判断。
    """
    reports_dir = tmp_path / "data" / "reports"
    # 故意把最低分 000002 放在 recs 中间, 最高分 300724 放在末尾
    recs = [
        _make_rec("600519", 0.60, name="贵州茅台"),
        _make_rec("000002", 0.10, name="万科A"),
        _make_rec("300724", 0.80, name="捷佳伟创"),
    ]
    _write_report(reports_dir, recommendations=recs)

    rc = run_why_not("999999", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 末位票必须指向真正最低分的 000002 (万科A), 而非 recs[-1] 的 300724
    assert "末位票: 000002" in captured.out
    assert "万科A" in captured.out
    # 不得把 recs[-1] (300724, 最高分) 标成末位票
    assert "末位票: 300724" not in captured.out


def test_main_path_has_disclaimer(tmp_path: Path, capsys) -> None:
    """R76 (R71/R72/R73/R75 同族 trust calibration): --why-not 主路径 (State 2, 4 区块)
    必须在 footer 追加「不构成投资建议」disclaimer, 与 --top-picks / --daily-brief /
    --position-check / --explain / PDF / backtest 六个用户决策面语义一致。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("600777", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 必须出现 disclaimer 关键词 (与 R71-R75 一致的措辞)
    assert "不构成任何投资建议" in captured.out
    assert "研究" in captured.out


def test_already_recommended_state_has_disclaimer(tmp_path: Path, capsys) -> None:
    """R76 同族: State 1 (已在推荐中) 也输出 decision label, 必须同样补 disclaimer。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("000001", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    assert "已被推荐" in captured.out
    assert "不构成任何投资建议" in captured.out
