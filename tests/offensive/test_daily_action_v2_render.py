"""--daily-action v2 渲染面测试 (R80 Op2) — 漏斗 per-condition 分桶行.

prefilter→hits 之间此前是黑箱: 0828 零命中日 (85 prefilter→0 命中) 的检测面
取证只能手工复现检测路径 (66 C2 / 16 C3 / 3 C1). 本文件钉死: detect_miss_stages
非空时渲染未命中分桶行 (只列非零桶), None 的旧构造点不出现分桶行 (向后兼容).
"""

from __future__ import annotations

from datetime import date, timedelta

import json

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action import (
    DailyActionV2Run,
    ScanFunnel,
    render_daily_action_v2,
)
from src.screening.offensive.daily_action_service import (
    DailyActionService,
    MarketBar,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository


def _sessions() -> tuple[date, ...]:
    start = date(2026, 8, 17)
    return tuple(start + timedelta(days=offset) for offset in range(30))


def _bar(close: float) -> MarketBar:
    return MarketBar(
        open=close,
        close=close,
        limit_down=close * 0.9,
        limit_up=close * 1.1,
        suspended=False,
        high=close + 0.2,
        low=close - 0.2,
    )


@pytest.fixture
def case(tmp_path):
    sessions = _sessions()
    as_of = sessions[3]
    prices = {
        (symbol, session): _bar(10.0)
        for symbol in ("300009", "600000")
        for session in sessions
    }
    costs = ExecutionCosts(version="test", commission=5.0, other_fee=10.0)
    repository = LedgerRepository(
        tmp_path / "ledger.sqlite3", "v2-render", 1_000_000, execution_costs=costs
    )
    repository.initialize()
    service = DailyActionService(
        repository,
        TradingSessionCalendar(sessions),
        lambda symbol, session: prices.get((symbol, session)),
        costs,
        enforce_manifest_gate=False,
    )
    return service, repository, as_of, sessions


def test_funnel_miss_stage_buckets_render_when_present(case):
    """非零桶按名称排序成行 — 0828 形态 (66 C2 / 16 C3 / 3 C1) 自解释."""
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        funnel=ScanFunnel(
            scannable=85,
            prefilter_passed=85,
            hits=0,
            universe=1840,
            detect_miss_stages={
                "c2_flow_below_mean": 66,
                "c3_industry_weak": 16,
                "c1_limit_up_pct": 3,
            },
        ),
    )
    text = render_daily_action_v2(view)
    assert "未命中分桶：c1_limit_up_pct 3 · c2_flow_below_mean 66 · c3_industry_weak 16" in text


def test_funnel_miss_stage_absent_on_legacy_construction(case):
    """detect_miss_stages=None (旧构造点) 不出现分桶行 — 向后兼容."""
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        funnel=ScanFunnel(scannable=10, prefilter_passed=3, hits=1),
    )
    assert "未命中分桶" not in render_daily_action_v2(view)


# ---------- R85 Op1: 强度阈值触发器状态行 (判定面日度可见性) ----------

def _trigger_ledger(tmp_path, records):
    import json
    path = tmp_path / "trigger_ledger.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def _trigger_rec(day, c1_lit, c2_lit, c1_judged=True, c2_judged=True, armed=False,
                 window_end="20260830"):
    return {
        "date": day, "anchor": "production_aligned/t10", "min_n": 30,
        "condition_1": {"lit": c1_lit, "judged": c1_judged, "n": 315, "stat": 0.0023},
        "condition_2": {"lit": c2_lit, "judged": c2_judged, "n": 303, "stat": 0.0097},
        "conjunction_armed": armed,
        "court": {"built_at": "2026-08-30", "window_end": window_end, "rows": 1866},
    }


def _patch_ledger(monkeypatch, path):
    from src.screening.offensive import threshold_trigger as tt
    monkeypatch.setattr(tt, "LEDGER_PATH", path)


def test_trigger_state_line_renders_conditions_and_streaks(case, tmp_path, monkeypatch):
    """有账本 → 状态行披露条件判定/连亮/合取与 court 覆盖 (hermetic tmp 账本)."""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260829", c1_lit=True, c2_lit=False),
        _trigger_rec("20260830", c1_lit=True, c2_lit=False),
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "强度阈值触发器" in text
    assert "条件① ≥0.70 桶 CI>0 已亮（连亮 2）" in text
    assert "条件② 0.50-0.60 转负 未亮（连亮 0）" in text
    assert "合取未武装" in text
    assert "court 覆盖至 20260830" in text
    assert "账本 2 条" in text


def test_trigger_state_line_omitted_when_ledger_missing(case, tmp_path, monkeypatch):
    """账本缺失 → 整行省略 (fail-open), 无异常 (hermetic: 不受主区真实账本影响)."""
    _patch_ledger(monkeypatch, tmp_path / "nope.jsonl")
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "强度阈值触发器" not in render_daily_action_v2(view)


def test_trigger_state_line_armed_and_unjudged_disclosed(case, tmp_path, monkeypatch):
    """武装态显示 owner 评估就绪提示; 未判定条件显示样本不足 — 不假装知道."""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260831", c1_lit=True, c2_lit=True, c1_judged=False,
                     c2_judged=False, armed=True),
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "条件① ≥0.70 桶 CI>0 样本不足未判定" in text
    assert "条件② 0.50-0.60 转负 样本不足未判定" in text
    assert "合取已武装 → 阈值上调正式评估就绪（owner 预注册动作）" in text


# ---------- R87 Op1: 逐刷新翻转状态行 (admission 噪声的日度可见性) ----------

def _scan_run_file(tmp_path, day, runs):
    """构造当日 scan_runs 工件 (与 log_scan_run 落盘形态同构)。"""
    import json
    out = tmp_path / "sol"
    out.mkdir(exist_ok=True)
    target = out / f"{day}.scan_runs.jsonl"
    payload = []
    for candidates in runs:
        payload.append({
            "record_kind": "scan_run", "schema_version": 1,
            "signal_date": day, "candidates": candidates,
        })
    target.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in payload) + "\n",
        encoding="utf-8",
    )
    return out


def _cand(ticker, setup, eligible, strength):
    return {"ticker": ticker, "setup": setup, "plan_eligible": eligible,
            "trigger_strength": strength, "degraded": False, "block_reason": ""}


def _patch_sol_dir(monkeypatch, path):
    from src.screening.offensive import setup_output_log as sol
    monkeypatch.setattr(sol, "_DEFAULT_DIR", path)


def test_flip_state_line_renders_flips_and_union_gap(case, tmp_path, monkeypatch):
    """有翻转日: 状态行披露刷新数/候选数/翻转数与并集−末次差明细 + 诚实边界注记."""
    out = _scan_run_file(tmp_path, "20260831", [
        [_cand("300009.SZ", "btst_breakout", True, 0.595),
         _cand("600000.SH", "btst_breakout", False, 0.42)],
        [_cand("300009.SZ", "btst_breakout", False, 0.48),
         _cand("600000.SH", "btst_breakout", False, 0.44)],
    ])
    _patch_sol_dir(monkeypatch, out)
    service, _repository, as_of, _sessions = case
    as_of = as_of.replace(year=2026, month=8, day=31)
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "逐刷新翻转" in text
    assert "2 次刷新" in text
    assert "候选 2" in text
    assert "资格翻转 1 只" in text
    assert "并集−末次 1 只" in text
    assert "300009.SZ btst_breakout" in text
    assert "噪声代理量" in text  # 诚实边界: 不判定为全部噪声


def test_flip_state_line_omitted_when_no_flips(case, tmp_path, monkeypatch):
    """单刷新/零翻转: 整行省略 (无噪声不出行, fail-open 语义)."""
    out = _scan_run_file(tmp_path, "20260831", [
        [_cand("600000.SH", "btst_breakout", False, 0.42)],
    ])
    _patch_sol_dir(monkeypatch, out)
    service, _repository, as_of, _sessions = case
    as_of = as_of.replace(year=2026, month=8, day=31)
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "逐刷新翻转" not in render_daily_action_v2(view)


def test_flip_state_line_omitted_when_file_missing(case, tmp_path, monkeypatch):
    """当日无 scan_runs 工件: 整行省略无异常."""
    _patch_sol_dir(monkeypatch, tmp_path / "empty-sol")
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "逐刷新翻转" not in render_daily_action_v2(view)


# ---------- R100 Op1: 0.60 锚触发器子句 (条件③/060 合取日度可见性) ----------

def _trigger_rec060(day, c3_lit=True, c3_judged=True, armed060=False, **kw):
    rec = _trigger_rec(day, **kw)
    rec["condition_3"] = {"lit": c3_lit, "judged": c3_judged, "n": 340, "stat": 0.0007}
    rec["conjunction_060_armed"] = armed060
    return rec


def test_trigger_state_line_renders_060_anchor_clause(case, tmp_path, monkeypatch):
    """新形态记录 → 0.60 锚子句披露条件③与 060 合取 (连亮计数)."""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec060("20260830", c1_lit=True, c2_lit=False, c3_lit=True),
        _trigger_rec060("20260831", c1_lit=True, c2_lit=True, c3_lit=True, armed060=True),
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "0.60 锚条件③ 0.60-0.70 桶 CI>0 已亮（连亮 2）" in text
    assert "0.60 锚合取③∧②已武装 → 0.50→0.60 上调评估就绪" in text


def test_trigger_state_line_060_unarmed_and_old_ledger_forms(case, tmp_path, monkeypatch):
    """060 未武装显示连亮; R100 前旧账本 (无 condition_3) 显示无记录不点亮."""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec060("20260831", c1_lit=True, c2_lit=False, c3_lit=True),
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "0.60 锚合取未武装（连亮 0）" in text

    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260831", c1_lit=False, c2_lit=False),
    ]))
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "0.60 锚条件③ 无记录（R100 前旧账本）" in text
    assert "已武装" not in text.split("强度阈值触发器")[1]


# ---------- R109 Op1: 先验漂移披露行 + 触发器行 max 连亮/K 读数 ----------

def _write_decomposition_report(tmp_path, wr=0.4456, expectancy=-0.0001,
                                ci_low=-0.0163, n=1627, date="20260904"):
    """合成 winrate_payoff_decomposition 报告 (production_aligned/t10/ALL 行)."""
    base = tmp_path / "reports"
    base.mkdir(parents=True, exist_ok=True)
    payload = {
        "universes": {
            "production_aligned": {
                "horizons": {
                    "t10": [
                        {
                            "group": "ALL", "n": n, "wins": int(n * wr),
                            "winrate": wr, "avg_win": 0.1303, "avg_loss": -0.1049,
                            "payoff": 1.243, "expectancy": expectancy,
                            "cluster_ci_low_90": ci_low,
                            "attribution_vs_all": None,
                        },
                    ],
                },
            },
        },
    }
    path = base / f"winrate_payoff_decomposition_{date}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return base


def _patch_drift_reports_dir(monkeypatch, path):
    from src.screening.offensive import daily_action as da
    monkeypatch.setattr(da, "_PRIOR_DRIFT_REPORTS_DIR", path)


def test_prior_drift_line_renders_when_material(case, tmp_path, monkeypatch):
    """材料漂移 (|ΔE|≥0.25pp): 披露行并置先验与最新 court 数字 + owner 决策指引."""
    _patch_drift_reports_dir(
        monkeypatch, _write_decomposition_report(tmp_path, expectancy=-0.0001, wr=0.4456)
    )
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "先验漂移披露" in text
    assert "+0.56%" in text          # 先验 E (BTST_BREAKOUT_T10)
    assert "46.5%" in text           # 先验胜率 (46.45% 经 .1%% 格式化四舍五入)
    assert "-0.01%" in text          # 最新 court 生产对齐 E
    assert "44.6%" in text           # 最新 court 生产对齐 胜率
    assert "20260904" in text        # 报告日期
    assert "owner" in text           # 重校准属 owner 决策
    assert "仅披露" in text          # 不改变决策的诚实边界


def test_prior_drift_line_omitted_when_aligned(case, tmp_path, monkeypatch):
    """未达材料阈值 (|ΔE|<0.25pp 且 |Δ胜率|<1.0pp): 整行省略无噪声."""
    _patch_drift_reports_dir(
        monkeypatch,
        _write_decomposition_report(tmp_path, expectancy=0.0056, wr=0.4650),
    )
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "先验漂移披露" not in render_daily_action_v2(view)


def test_prior_drift_line_omitted_when_report_missing(case, tmp_path, monkeypatch):
    """报告目录缺失/为空: 整行省略无异常 (fail-open 家族纪律)."""
    _patch_drift_reports_dir(monkeypatch, tmp_path / "no-such-reports")
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "先验漂移披露" not in render_daily_action_v2(view)


def test_prior_drift_line_omitted_when_report_corrupt(case, tmp_path, monkeypatch):
    """最新报告损坏 (垃圾字节): 整行省略, 不以陈旧报告冒充当前证据."""
    base = tmp_path / "reports"
    base.mkdir(parents=True, exist_ok=True)
    (base / "winrate_payoff_decomposition_20260903.json").write_text(
        json.dumps({"universes": {"production_aligned": {"horizons": {"t10": [
            {"group": "ALL", "n": 1500, "winrate": 0.46, "expectancy": 0.005,
             "cluster_ci_low_90": 0.001}]}}}}), encoding="utf-8")
    (base / "winrate_payoff_decomposition_20260904.json").write_text(
        "\x00 not json", encoding="utf-8")
    _patch_drift_reports_dir(monkeypatch, base)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "先验漂移披露" not in render_daily_action_v2(view)


def test_trigger_state_line_discloses_max_streaks_and_k_pending(case, tmp_path, monkeypatch):
    """触发器行补「历史最多连亮」两读数 + K 未预注册子句 (R109 Op1)."""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260829", c1_lit=True, c2_lit=True, armed=True),
        _trigger_rec("20260830", c1_lit=True, c2_lit=True, armed=True),
        _trigger_rec("20260831", c1_lit=True, c2_lit=False, armed=False),
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "历史最多连亮 2" in text       # 0.70 锚合取全历史最大武装段
    assert "060 锚 0" in text            # 0.60 锚历史最大武装段 (无 060 键)
    assert "K 未预注册" in text          # 稳定阈值 K 属 owner 预注册动作
