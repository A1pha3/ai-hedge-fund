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
    # hermeticity (R112): K 预注册文件同样钉到 tmp — owner 未来落真实 K 文件
    # 时, 既有「未注册」pin 断言不受宿主工作目录真实文件影响。
    monkeypatch.setattr(tt, "K_REGISTRATION_PATH", path.parent / "k_registration_absent.json")


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
    # R120 措辞收口: 加合取限定, 与条件①连亮量纲区分 (防『连亮 3 vs 最多 0』误读)
    assert "历史最多合取连亮 2" in text   # 0.70 锚合取全历史最大武装段
    assert "历史最多 060 锚合取连亮 0" in text  # 0.60 锚历史最大武装段 (R129 Op3 斜杠歧义已除, 合取限定保留)
    assert "历史最多连亮 " not in text    # 旧的无限定措辞不得回归
    assert "K 未预注册" in text          # 稳定阈值 K 属 owner 预注册动作


def test_prior_drift_line_ignores_non_dated_lookalike_files(case, tmp_path, monkeypatch):
    """R109 Op2 PoC: 同前缀非日期文件 (合法 payload) 不得劫持披露行 — 形状守卫."""
    base = _write_decomposition_report(tmp_path, expectancy=-0.0001, wr=0.4456)
    junk = {
        "universes": {"production_aligned": {"horizons": {"t10": [
            {"group": "ALL", "n": 99, "winrate": 0.99, "expectancy": 0.99,
             "cluster_ci_low_90": 0.9}]}}},
    }
    (base / "winrate_payoff_decomposition_backup.json").write_text(
        json.dumps(junk), encoding="utf-8")
    _patch_drift_reports_dir(monkeypatch, base)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "先验漂移披露" in text
    assert "20260904" in text      # 仍取真实日期报告
    assert "99.0%" not in text     # 垃圾文件 payload 未渗入
    assert "backup" not in text


def test_prior_drift_line_omitted_when_all_row_missing_keys(case, tmp_path, monkeypatch):
    """ALL 行缺 expectancy/winrate 键: 整行省略零崩溃 (畸形报告家族)."""
    base = tmp_path / "reports"
    base.mkdir(parents=True, exist_ok=True)
    (base / "winrate_payoff_decomposition_20260904.json").write_text(
        json.dumps({"universes": {"production_aligned": {"horizons": {"t10": [
            {"group": "ALL", "n": 100}]}}}}), encoding="utf-8")
    _patch_drift_reports_dir(monkeypatch, base)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "先验漂移披露" not in render_daily_action_v2(view)


# ---------- R112 Op1: 触发器行 K 预注册消费面 ----------

def _kfile(tmp_path, payload, name="threshold_trigger_k.json"):
    path = tmp_path / name
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


_K_OK = {
    "anchor": "production_aligned/t10",
    "k_070": 2,
    "k_060": 2,
    "registered_date": "20260829",
    "owner_ref": "owner:mini 预注册",
}


def _patch_k(monkeypatch, path):
    from src.screening.offensive import threshold_trigger as tt
    monkeypatch.setattr(tt, "K_REGISTRATION_PATH", path)


def test_trigger_state_line_k_registered_discloses_qualification(case, tmp_path, monkeypatch):
    """owner 预注册 K → 行内披露 K/起算日/资格连亮; 达标 → 资格达成明语."""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260829", c1_lit=True, c2_lit=True, armed=True),
        _trigger_rec("20260830", c1_lit=True, c2_lit=True, armed=True),
    ]))
    _patch_k(monkeypatch, _kfile(tmp_path, _K_OK))  # 注册日起两条全武装 → 2/2 达标
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "预注册 K=2（自 20260829 起计资格连亮 2/2）" in text
    assert "正式评估资格达成" in text


def test_trigger_state_line_k_registered_not_yet_qualified(case, tmp_path, monkeypatch):
    """注册日晚于连亮起点 → 不追溯计旧亮, 进度如实可见."""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260829", c1_lit=True, c2_lit=True, armed=True),
        _trigger_rec("20260830", c1_lit=True, c2_lit=True, armed=True),
    ]))
    late = {**_K_OK, "registered_date": "20260830", "k_070": 3}
    _patch_k(monkeypatch, _kfile(tmp_path, late))  # 窗内只有 0830 一条 → 1/3
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "资格连亮 1/3" in text
    assert "正式评估资格达成" not in text


def test_trigger_state_line_k_malformed_disclosed(case, tmp_path, monkeypatch):
    """K 文件存在但损坏 → 明语披露, 不假装未注册也不猜字段."""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260830", c1_lit=True, c2_lit=True, armed=True),
    ]))
    _patch_k(monkeypatch, _kfile(tmp_path, "{not json"))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "预注册文件损坏" in text
    assert "正式评估资格达成" not in text


# ---------- R114 Op3: 入选质量构成披露行 ----------

def _write_decomp_report_with_buckets(tmp_path, day="20260904"):
    base = tmp_path / "reports"
    base.mkdir(parents=True, exist_ok=True)
    rows = [
        {"group": "ALL", "n": 1627, "winrate": 0.4456, "expectancy": -0.0001,
         "cluster_ci_low_90": -0.0163},
        {"group": "strength=≥0.70", "n": 340, "winrate": 0.4853,
         "expectancy": 0.0169, "cluster_ci_low_90": 0.0007},
        {"group": "strength=0.60-0.70", "n": 431, "winrate": 0.4501,
         "expectancy": 0.0103, "cluster_ci_low_90": -0.0035},
        {"group": "strength=0.50-0.60", "n": 341, "winrate": 0.4575,
         "expectancy": 0.0014, "cluster_ci_low_90": -0.023},
    ]
    (base / f"winrate_payoff_decomposition_{day}.json").write_text(
        json.dumps({"universes": {"production_aligned": {"horizons": {"t10": rows}}}}),
        encoding="utf-8",
    )
    return base


def _patch_quality_reports_dir(monkeypatch, base):
    from src.screening.offensive import daily_action as da
    monkeypatch.setattr(da, "_PRIOR_DRIFT_REPORTS_DIR", base)


def _detail(ticker, strength):
    from src.screening.offensive.daily_action import PlanDetail
    from datetime import date as _d
    return PlanDetail(
        ticker=ticker, setup="btst_breakout", horizon=10,
        trigger_strength=strength, expected_exit_date=_d(2026, 8, 31),
        distribution=None, metadata={},
    )


def test_picks_quality_line_buckets_and_expectancies(case, tmp_path, monkeypatch):
    """有 picks + 有报告 → 分桶计数与 court 实测净期望同屏."""
    _patch_quality_reports_dir(monkeypatch, _write_decomp_report_with_buckets(tmp_path))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        plan_details=(
            _detail("111.SZ", 0.72),
            _detail("222.SZ", 0.72),
            _detail("333.SZ", 0.55),
        ),
    )
    text = render_daily_action_v2(view)
    assert "入选质量构成" in text
    assert "≥0.70 × 2（历史期望 +1.69%）" in text
    assert "0.50-0.60 × 1（历史期望 +0.14%）" in text
    assert "0.60-0.70 × 0" in text
    assert "<0.50 × 0" in text
    assert "20260904" in text and "n=1627" in text
    assert "不改变计划与执行" in text


def test_picks_quality_line_absent_without_picks(case, tmp_path, monkeypatch):
    _patch_quality_reports_dir(monkeypatch, _write_decomp_report_with_buckets(tmp_path))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "入选质量构成" not in render_daily_action_v2(view)


def test_picks_quality_line_absent_when_report_corrupt(case, tmp_path, monkeypatch):
    """最新报告损坏 → 整行省略, 不回退旧报告 (镜像漂移行纪律)."""
    base = _write_decomp_report_with_buckets(tmp_path, day="20260903")
    (base / "winrate_payoff_decomposition_20260904.json").write_text(
        "\x00 not json", encoding="utf-8")
    _patch_quality_reports_dir(monkeypatch, base)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        plan_details=(_detail("111.SZ", 0.72),),
    )
    assert "入选质量构成" not in render_daily_action_v2(view)


def test_picks_quality_line_count_only_when_bucket_row_missing(case, tmp_path, monkeypatch):
    """报告缺个别桶行 (如 <0.50) → 该桶只计数不出 E, 其余桶正常."""
    base = tmp_path / "reports"
    base.mkdir(parents=True, exist_ok=True)
    rows = [
        {"group": "ALL", "n": 1627, "winrate": 0.4456, "expectancy": -0.0001,
         "cluster_ci_low_90": -0.0163},
        {"group": "strength=≥0.70", "n": 340, "winrate": 0.4853,
         "expectancy": 0.0169, "cluster_ci_low_90": 0.0007},
    ]
    (base / "winrate_payoff_decomposition_20260904.json").write_text(
        json.dumps({"universes": {"production_aligned": {"horizons": {"t10": rows}}}}),
        encoding="utf-8",
    )
    _patch_quality_reports_dir(monkeypatch, base)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        plan_details=(
            _detail("111.SZ", 0.72),
            _detail("222.SZ", 0.48),
        ),
    )
    text = render_daily_action_v2(view)
    assert "≥0.70 × 1（历史期望 +1.69%）" in text
    assert "<0.50 × 1" in text
    assert "<0.50 × 1（历史期望" not in text


def test_trigger_state_line_survives_polluted_observation_log(case, tmp_path, monkeypatch):
    """F3 全链 (修复前 RED = ValueError 裸逃逸炸掉整个 --daily-action 渲染):
    污染 K 观测日志行 → 触发器行照常渲染, K 披露回落声明日起算."""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260830", c1_lit=True, c2_lit=True, armed=True),
    ]))
    kfile = _kfile(tmp_path, _K_OK)
    _patch_k(monkeypatch, kfile)
    from src.screening.offensive import threshold_trigger as tt
    reg = tt.load_k_registration(kfile)[1]
    log = tmp_path / "k_obs.jsonl"
    log.write_text(
        json.dumps(
            {"observed_date": "202609011", "k_hash": tt.k_registration_hash(reg)},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tt, "K_OBSERVATION_LOG_PATH", log)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "强度阈值触发器" in text
    assert "自 20260829 起计资格连亮 1/2" in text


# ---------- R115 Op2: 证据新鲜度告警行 ----------

def _freshness_sessions():
    from datetime import date as _date

    return tuple(_date(2026, 8, d) for d in (24, 25, 26, 27, 28, 31))


def _write_refresh_status(base, ok=True, day="20260830"):
    payload = {
        "date": day, "ok": ok,
        "fetch": ({"rc": 0, "error": None} if ok
                  else {"rc": 1, "error": "exit rc=1: fetch boom"}),
        "build": ({"rc": 0, "window_start": "20250701", "error": None} if ok
                  else {"skipped": "fetch_failed"}),
    }
    base.mkdir(parents=True, exist_ok=True)
    p = base / "court_refresh_status.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_freshness_line_omitted_when_fresh_and_ok(tmp_path, monkeypatch):
    """报告距今日 1 个交易日 (正常节律: 每晚刷新覆盖前一交易日) + 昨夜 ok →
    整行省略零噪声 (R109 漂移行先例: 未达材料阈值不出行)."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260828")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260828", c1_lit=True, c2_lit=False, window_end="20260828"),
    ]))
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", tmp_path / "no-status.json")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is None


def test_freshness_line_renders_when_stale_two_sessions(tmp_path, monkeypatch):
    """报告距今日 ≥2 个交易日 → 出行: 陈旧 N 个交易日 + 账本最后判定 +
    court 覆盖至 + 诚实边界 (≥2 = 至少一夜未刷新)."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260827")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260827", c1_lit=True, c2_lit=False, window_end="20260827"),
    ]))
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", tmp_path / "no-status.json")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "证据新鲜度告警" in line
    assert "20260827" in line
    assert "陈旧 2 个交易日" in line
    assert "触发器账本最后判定 20260827" in line
    # R139 Op3: window_end 同样落后 ≥2 交易日 → 覆盖部分从被动『覆盖至』
    # 升级为『覆盖停滞』(停滞距离与最后覆盖日期仍可见)
    assert "court 覆盖停滞 2 个交易日（最后覆盖 20260827）" in line
    assert "仅披露" in line


def test_freshness_line_natural_day_fallback_without_calendar(tmp_path, monkeypatch):
    """交易日历缺失/报告日不在日历 → 自然日兜底文案, 阈值 4 天保守降级."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260820")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, tmp_path / "no-ledger.jsonl")
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", tmp_path / "no-status.json")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=()
    )
    assert line is not None
    assert "陈旧 11 个自然日（交易日折算不可用）" in line


def test_freshness_line_renders_when_refresh_failed_even_if_fresh(tmp_path, monkeypatch):
    """昨夜刷新 status ok=False → 即使报告新鲜也出行, 含归因尾 (操作员当晚
    即知夜刷链中断, 不必等陈旧显形)."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260828")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260828", c1_lit=True, c2_lit=False, window_end="20260828"),
    ]))
    status_dir = tmp_path / "st"
    _write_refresh_status(status_dir, ok=False)
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", status_dir / "court_refresh_status.json")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    # G2: 不推断『昨夜』— 措辞携带 status 真实日期
    assert "court 夜刷状态 失败" in line
    assert "status 20260830" in line
    # R139 Op2 F: 归因因果序改为 fetch.error 优先 — 该断言旧锁 'fetch_failed'
    # 正是被修复的降级标签, 契约更新为可操作的 error 尾
    assert "exit rc=1: fetch boom" in line


def test_freshness_line_omitted_when_report_missing(tmp_path, monkeypatch):
    """报告缺失 → 整行省略 (判定面未建立是稳态, fail-open 家族纪律)."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    _patch_drift_reports_dir(monkeypatch, tmp_path / "no-such-reports")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is None


def test_freshness_line_tolerates_corrupt_status(tmp_path, monkeypatch):
    """status 损坏 → 刷新子句省略不假装, 陈旧判定照常 (fail-open)."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260820")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, tmp_path / "no-ledger.jsonl")
    status_dir = tmp_path / "st"
    status_dir.mkdir(parents=True, exist_ok=True)
    (status_dir / "court_refresh_status.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", status_dir / "court_refresh_status.json")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "陈旧" in line
    assert "昨夜 court 刷新失败" not in line


# ---------- R139 Op1: 夜刷判定链诊断失败子句 ----------

def _write_refresh_status_full(
    base, *, ok=True, day="20260830", diagnostics=None, reconcile=None
):
    payload = {
        "date": day,
        "ok": ok,
        "fetch": {"rc": 0, "error": None},
        "build": {"rc": 0, "window_start": "20250701", "error": None},
    }
    if reconcile is not None:
        payload["reconcile"] = reconcile
    if diagnostics is not None:
        payload["diagnostics"] = diagnostics
    base.mkdir(parents=True, exist_ok=True)
    p = base / "court_refresh_status.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def _freshness_env(tmp_path, monkeypatch, status_dir, report_day="20260828"):
    from datetime import date as _date

    base = _write_decomposition_report(tmp_path, date=report_day)
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec(report_day, c1_lit=True, c2_lit=False, window_end=report_day),
    ]))
    from src.screening.offensive import daily_action as _da

    monkeypatch.setattr(
        _da, "_COURT_REFRESH_STATUS_PATH", status_dir / "court_refresh_status.json"
    )


def test_freshness_line_renders_when_diagnostic_failed_even_if_fresh(tmp_path, monkeypatch):
    """诊断一步 rc=2 而 ok=True、报告新鲜 → 出行: 脚本名 + error 尾 + status
    日期 (G2); 尾句『其余判定面照常刷新』而非整体『证据冻结』."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    status_dir = tmp_path / "st"
    _write_refresh_status_full(
        status_dir,
        diagnostics={
            "scripts/winrate_payoff_decomposition.py": {
                "rc": 0, "error": None,
            },
            "scripts/btst_signal_day_cohort.py": {
                "rc": 2, "error": "exit rc=2: cohort boom",
            },
        },
        reconcile={"rc": 0, "error": None},
    )
    _freshness_env(tmp_path, monkeypatch, status_dir)
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "夜刷判定链 1 步失败" in line
    assert "scripts/btst_signal_day_cohort.py" in line
    assert "exit rc=2: cohort boom" in line
    assert "status 20260830" in line
    assert "其余判定面照常刷新" in line
    assert "证据冻结" not in line


def test_freshness_line_omitted_when_diagnostics_all_ok(tmp_path, monkeypatch):
    """诊断/对账全 rc=0 → 整行省略 (零噪声纪律, R109 先例)."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    status_dir = tmp_path / "st"
    _write_refresh_status_full(
        status_dir,
        diagnostics={
            f"scripts/script_{i}.py": {"rc": 0, "error": None} for i in range(5)
        },
        reconcile={"rc": 0, "error": None},
    )
    _freshness_env(tmp_path, monkeypatch, status_dir)
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is None


def test_freshness_line_omitted_when_status_lacks_diagnostic_keys(tmp_path, monkeypatch):
    """pre-R118 旧 status (无 reconcile/diagnostics 键) → 子句安静不虚构."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    status_dir = tmp_path / "st"
    _write_refresh_status_full(status_dir)
    _freshness_env(tmp_path, monkeypatch, status_dir)
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is None


def test_freshness_line_tolerates_malformed_diagnostics_shape(tmp_path, monkeypatch):
    """diagnostics 键非 dict (未知写入方/损坏落盘) → 子句空串不虚构清单."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    status_dir = tmp_path / "st"
    _write_refresh_status_full(status_dir, diagnostics="poison")
    _freshness_env(tmp_path, monkeypatch, status_dir)
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is None


def test_freshness_line_counts_malformed_diagnostic_entry(tmp_path, monkeypatch):
    """条目非 dict (记账损坏 = 步骤结果未知) → 按失败显形 malformed_entry."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    status_dir = tmp_path / "st"
    _write_refresh_status_full(
        status_dir,
        diagnostics={"scripts/day_feature_attribution.py": "poison"},
    )
    _freshness_env(tmp_path, monkeypatch, status_dir)
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "scripts/day_feature_attribution.py: malformed_entry" in line


def test_freshness_line_reconcile_failure_surfaces(tmp_path, monkeypatch):
    """reconcile 步失败 (诊断全绿) → 单独显形 reconcile: error."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    status_dir = tmp_path / "st"
    _write_refresh_status_full(
        status_dir,
        diagnostics={
            f"scripts/script_{i}.py": {"rc": 0, "error": None} for i in range(5)
        },
        reconcile={"rc": 1, "error": "exit rc=1: reconcile boom"},
    )
    _freshness_env(tmp_path, monkeypatch, status_dir)
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "reconcile: exit rc=1: reconcile boom" in line
    assert "夜刷判定链 1 步失败" in line


# ---------- R139 Op3: court 窗口停滞子句 ----------

def _freshness_env_window(tmp_path, monkeypatch, window_end, report_day="20260828"):
    from src.screening.offensive import daily_action as _da

    base = _write_decomposition_report(tmp_path, date=report_day)
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec(report_day, c1_lit=True, c2_lit=False, window_end=window_end),
    ]))
    monkeypatch.setattr(
        _da,
        "_COURT_REFRESH_STATUS_PATH",
        tmp_path / "no-status.json",
    )


def test_freshness_line_fires_when_court_window_stalls(tmp_path, monkeypatch):
    """R139 Op3 A1 (RED→GREEN): window_end 落后 as_of 2 个交易日且其余全绿
    (报告新鲜/ok=True/诊断无键) → 出行『覆盖停滞』+ 冻结尾句 — 闭合
    『一切正常但证据宇宙冻结』组合 (连续空涨停日/原料边界事故)."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    _freshness_env_window(tmp_path, monkeypatch, "20260827")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "court 覆盖停滞 2 个交易日（最后覆盖 20260827）" in line
    assert "证据冻结" in line


def test_freshness_line_quiet_when_window_lags_one_session(tmp_path, monkeypatch):
    """R139 Op3 A2: 落后 1 个交易日属合法空涨停日节律 → 整行省略零噪声."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    _freshness_env_window(tmp_path, monkeypatch, "20260828")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is None


def test_freshness_line_stall_and_report_stale_coexist(tmp_path, monkeypatch):
    """R139 Op3 A3: 报告陈旧与窗口停滞同时成立 → 单行双事实, 陈旧文案不变."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    _freshness_env_window(tmp_path, monkeypatch, "20260827", report_day="20260827")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "陈旧 2 个交易日" in line
    assert "court 覆盖停滞 2 个交易日（最后覆盖 20260827）" in line


def test_freshness_line_quiet_when_window_precedes_all_sessions(tmp_path, monkeypatch):
    """R139 Op3 A4 (fail-open): 窗口早于全部会话 (无折算会话) → 子句安静,
    不虚构停滞距离 (报告陈旧判定照常兜底)."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    _freshness_env_window(tmp_path, monkeypatch, "20200101")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is None


def test_freshness_line_window_snap_to_last_session_before_nontrading_day(tmp_path, monkeypatch):
    """R139 Op3 (真实形态折算): 真实账本 window_end 常为非交易日 (如周六,
    宿主实测 20260905 ∉ 日历) — 非交易日覆盖 ≡ 前一收盘覆盖: 周六窗口折算
    到周五, 距离 1 → 安静; 若按原样丢给 session_distance 会 ValueError
    永久安静, 子句在真实数据上死代码."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    _freshness_env_window(tmp_path, monkeypatch, "20260829")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is None


def test_freshness_line_stall_with_diagnostic_failure_keeps_frozen_tail(tmp_path, monkeypatch):
    """R139 Op3: 窗口停滞与诊断失败并存 → 冻结尾句优先 (数据真冻结),
    两事实同屏."""
    from datetime import date as _date

    from src.screening.offensive import daily_action as da

    _freshness_env_window(tmp_path, monkeypatch, "20260827")
    status_dir = tmp_path / "st"
    _write_refresh_status_full(
        status_dir,
        diagnostics={"scripts/btst_signal_day_cohort.py": {
            "rc": 2, "error": "exit rc=2: cohort boom",
        }},
    )
    status_path = status_dir / "court_refresh_status.json"
    import json as _json
    payload = _json.loads(status_path.read_text(encoding="utf-8"))
    payload["reconcile"] = {"rc": 0, "error": None}
    status_path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        da, "_COURT_REFRESH_STATUS_PATH", status_path
    )
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "court 覆盖停滞 2 个交易日" in line
    assert "夜刷判定链 1 步失败" in line
    assert "证据冻结" in line
    assert "其余判定面照常刷新" not in line


def test_freshness_line_stale_and_diagnostic_failure_coexist(tmp_path, monkeypatch):
    """报告陈旧与诊断失败同时成立 → 单行双事实, 既有陈旧文案不变."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    status_dir = tmp_path / "st"
    _write_refresh_status_full(
        status_dir,
        diagnostics={"scripts/realized_selection_wedge.py": {
            "rc": 1, "error": "exit rc=1: wedge boom",
        }},
    )
    _freshness_env(tmp_path, monkeypatch, status_dir, report_day="20260827")
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "陈旧 2 个交易日" in line
    assert "夜刷判定链 1 步失败" in line
    assert "证据冻结" in line


def test_freshness_line_fetch_failure_shows_actionable_error(tmp_path, monkeypatch):
    """R139 Op2 F (PoC RED→GREEN): fetch 失败时归因因果序 fetch.error 优先 —
    旧序 build.skipped='fetch_failed' 泛化标签截胡, status 文件里已有的可操作
    原因 (如 'daily 缺 1 天') 被降级, 操作员当晚无法归因."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260828")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260828", c1_lit=True, c2_lit=False, window_end="20260828"),
    ]))
    status_dir = tmp_path / "st"
    status_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": "20260907",
        "ok": False,
        "fetch": {"rc": 1, "error": "exit rc=1: daily 缺 1 天 ['20260907']"},
        "build": {"skipped": "fetch_failed"},
    }
    (status_dir / "court_refresh_status.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        da, "_COURT_REFRESH_STATUS_PATH", status_dir / "court_refresh_status.json"
    )
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is not None
    assert "daily 缺 1 天 ['20260907']" in line
    assert "fetch_failed" not in line


def test_freshness_line_manifest_missing_falls_back_to_skip_tag(tmp_path, monkeypatch):
    """R139 Op2 A2: fetch 成功而 manifest 缺失 (build skip, fetch.error=None)
    → 自然落回 build.skipped, 既有语义不变路径."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260828")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260828", c1_lit=True, c2_lit=False, window_end="20260828"),
    ]))
    status_dir = tmp_path / "st"
    status_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": "20260907",
        "ok": True,
        "fetch": {"rc": 0, "error": None},
        "build": {"skipped": "court_manifest_missing_or_window_missing"},
    }
    (status_dir / "court_refresh_status.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        da, "_COURT_REFRESH_STATUS_PATH", status_dir / "court_refresh_status.json"
    )
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    # ok=True → 既有 refresh 子句不触发 (skip 非 failure), 行仍省略
    assert line is None


def test_freshness_line_report_missing_beats_diagnostic_failure(tmp_path, monkeypatch):
    """R139 Op2 A3 (边界钉死): 报告目录缺失 (判定面未建立稳态) + status 含诊断
    失败 → 整行省略。R115 fail-open 家族纪律: 报告缺失时行让位, 诊断子句不单独
    撑起一行 — 钉死为显式选择, 防未来『顺手修复』悄然改变稳态语义."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    _patch_drift_reports_dir(monkeypatch, tmp_path / "no-such-reports")
    status_dir = tmp_path / "st"
    _write_refresh_status_full(
        status_dir,
        diagnostics={"scripts/btst_signal_day_cohort.py": {
            "rc": 2, "error": "exit rc=2: cohort boom",
        }},
    )
    monkeypatch.setattr(
        da, "_COURT_REFRESH_STATUS_PATH", status_dir / "court_refresh_status.json"
    )
    line = da._render_evidence_freshness_line(
        _date(2026, 8, 31), calendar_sessions=_freshness_sessions()
    )
    assert line is None


def test_freshness_line_renders_in_daily_action_when_stale(case, tmp_path, monkeypatch):
    """渲染面集成: 陈旧时 --daily-action 输出含告警行 (触发器行之后)."""
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260827")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260827", c1_lit=True, c2_lit=False, window_end="20260827"),
    ]))
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", tmp_path / "no-status.json")
    monkeypatch.setattr(da, "_load_authoritative_session_dates", _freshness_sessions)
    service, _repository, as_of, _sessions = case
    as_of = as_of.replace(year=2026, month=8, day=31)
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "证据新鲜度告警" in text


def test_freshness_line_flags_future_dated_report(tmp_path, monkeypatch):
    """G1 (修复前 RED = line None 伪最新不可见): 合法 8 位未来日文件名过形状
    守卫成为『最新』— 报告日期在今日之后比陈旧更值得显形 (R109 Op2 反劫持残端).
    R127 Op1: 真未来判定锚定注入墙钟 (报告日 > today), 测试永久确定."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260910")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, tmp_path / "no-ledger.jsonl")
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", tmp_path / "no-status.json")
    sessions = tuple(_date(2026, 9, d) for d in (1, 2, 3, 4, 5, 8, 9, 10, 11))
    line = da._render_evidence_freshness_line(
        _date(2026, 9, 5), calendar_sessions=sessions, today=_date(2026, 9, 5)
    )
    assert line is not None
    assert "报告日期在今日之后（文件名或时钟异常）" in line
    assert "20260910" in line


def test_freshness_line_legit_evening_report_not_flagged(tmp_path, monkeypatch):
    """R127 Op1 (G1 假阳性修复, R126 冒烟实录形态): 补班日 20260905 晚刷落
    报告 20260905, 而 as_of 取 readiness 快照日 2026-09-04 → dist=-1。
    报告日 ≤ 今日墙钟 → 合法当晚刷新, 按最新鲜渲染 (整行省略零噪声),
    不再误报『报告日期在今日之后』。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260905")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, tmp_path / "no-ledger.jsonl")
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", tmp_path / "no-status.json")
    sessions = tuple(_date(2026, 9, d) for d in (1, 2, 3, 4, 5))
    line = da._render_evidence_freshness_line(
        _date(2026, 9, 4), calendar_sessions=sessions, today=_date(2026, 9, 5)
    )
    assert line is None


def test_freshness_line_legit_evening_report_natural_day_fallback(tmp_path, monkeypatch):
    """R127 Op1 同语义自然日兜底分支: days<0 但报告日 ≤ 今日墙钟 → 按 0
    自然日渲染 (新鲜省略), 不报『报告日期在今日之后』也不渲染『陈旧 -N』."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260905")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, tmp_path / "no-ledger.jsonl")
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", tmp_path / "no-status.json")
    line = da._render_evidence_freshness_line(
        _date(2026, 9, 4), calendar_sessions=(), today=_date(2026, 9, 5)
    )
    assert line is None


def test_freshness_line_future_dated_report_natural_day_fallback(tmp_path, monkeypatch):
    """G1 自然日兜底分支同语义: days<0 且报告日 > 今日墙钟 → 异常文案而非
    『陈旧 -N 个自然日』(R127 Op1: 真未来判定锚定注入墙钟)."""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260910")
    _patch_drift_reports_dir(monkeypatch, base)
    _patch_ledger(monkeypatch, tmp_path / "no-ledger.jsonl")
    monkeypatch.setattr(da, "_COURT_REFRESH_STATUS_PATH", tmp_path / "no-status.json")
    line = da._render_evidence_freshness_line(
        _date(2026, 9, 5), calendar_sessions=(), today=_date(2026, 9, 5)
    )
    assert line is not None
    assert "报告日期在今日之后（文件名或时钟异常）" in line


# ---------- R118 Op1: 宇宙对齐行 ----------

def _alignment_summary(**overrides):
    payload = {
        "date": "20260905",
        "total_buys": 18,
        "class_counts": {
            "outside_window": 0,
            "day_excluded_regime_gap": 0,
            "day_missing_panel_data": 0,
            "day_missing_from_court": 6,
            "ticker_not_in_court_day": 3,
            "matched": 9,
        },
        "realized_only": {
            "n": 15, "win_rate_pct": 20.0, "avg_win_pct": 8.52,
            "avg_loss_pct": -9.68, "payoff": 0.88, "expectancy_pct": -6.04,
        },
        "latest_split_signal_date": "20260813",
        "latest_matched_signal_date": "20260821",
        "court_window": {"start": "20250701", "end": "20260901"},
    }
    payload.update(overrides)
    return payload


def _write_alignment(base, payload):
    base.mkdir(parents=True, exist_ok=True)
    p = base / "realized_vs_court_alignment.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_alignment_line_renders_counts_split_and_realized(tmp_path):
    from src.screening.offensive import daily_action as da

    path = _write_alignment(tmp_path, _alignment_summary())
    line = da._render_universe_alignment_line(path)
    assert line is not None
    assert "宇宙对齐（对账 20260905 · court 窗口 20250701..20260901）" in line
    assert "生产 BUY 18 · matched 9 · 分裂 9（最晚分裂 20260813）" in line
    assert "已平仓 15 胜率 20.0% 期望 -6.04%" in line
    assert "仅披露参考，不改变计划与执行决策" in line


def test_alignment_line_all_matched_reports_zero_split(tmp_path):
    from src.screening.offensive import daily_action as da

    # R119 P3 一致性守卫: 夹具必须是自洽世界 (total = matched + split);
    # 旧夹具清零分裂类但 total 仍 18, 守卫正确拒绝 → 夹具修正为 total=9。
    counts = {**_alignment_summary()["class_counts"],
              "day_missing_from_court": 0, "ticker_not_in_court_day": 0}
    payload = _alignment_summary(
        total_buys=9, class_counts=counts, latest_split_signal_date=None,
    )
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert "分裂 0 — 全部生产信号在 court 宇宙内" in line
    assert "最晚分裂" not in line


def test_alignment_line_omits_realized_clause_when_none_closed(tmp_path):
    from src.screening.offensive import daily_action as da

    line = da._render_universe_alignment_line(
        _write_alignment(tmp_path, _alignment_summary(realized_only=None))
    )
    assert line is not None
    assert "· 已平仓" not in line
    assert "生产 BUY 18" in line


def test_alignment_line_omitted_when_summary_missing_or_corrupt(tmp_path):
    from src.screening.offensive import daily_action as da

    assert da._render_universe_alignment_line(tmp_path / "nope.json") is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert da._render_universe_alignment_line(corrupt) is None
    garbage = tmp_path / "garbage.bin"
    garbage.write_bytes(b"\xff\xfe\x00garbage")
    assert da._render_universe_alignment_line(garbage) is None


@pytest.mark.parametrize("mutate", [
    lambda p: p.pop("total_buys"),
    lambda p: p["class_counts"].pop("matched"),
    lambda p: p.pop("date"),
    lambda p: p.update(date=""),
    lambda p: p.update(total_buys="18"),
    lambda p: p.update(class_counts=[1, 2]),
])
def test_alignment_line_omitted_on_shape_violation(tmp_path, mutate):
    from src.screening.offensive import daily_action as da

    payload = _alignment_summary()
    mutate(payload)
    assert da._render_universe_alignment_line(_write_alignment(tmp_path, payload)) is None


def test_alignment_line_wired_after_drift_line(case, tmp_path, monkeypatch):
    """渲染面集成: summary 工件在场时, 完整 --daily-action 输出含宇宙对齐行;
    缺失时整行省略 (fail-open 家族), 两次渲染 rc 均不受影响."""
    from src.screening.offensive import daily_action as da

    _write_alignment(tmp_path, _alignment_summary())
    monkeypatch.setattr(da, "_ALIGNMENT_SUMMARY_PATH", tmp_path / "realized_vs_court_alignment.json")
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "宇宙对齐（对账 20260905" in text
    assert "生产 BUY 18" in text

    monkeypatch.setattr(da, "_ALIGNMENT_SUMMARY_PATH", tmp_path / "nope.json")
    text_without = render_daily_action_v2(view)
    assert "宇宙对齐" not in text_without


# ---------- R119 Op2: 对齐行对抗审查收口 (R118 交付面 PoC 六连) ----------

def test_alignment_line_realized_clause_crash_on_string_expectancy(tmp_path):
    """G1 (修复前 RED = ValueError 裸逃逸炸掉整个渲染): expectancy_pct 字符串 →
    数值子句整体省略, 行照常渲染 (R115 Op1 P1 fail-open 家族纪律同族)."""
    from src.screening.offensive import daily_action as da

    payload = _alignment_summary(
        realized_only={**_alignment_summary()["realized_only"],
                       "expectancy_pct": "-6.04"}
    )
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert line is not None
    assert "· 已平仓" not in line
    assert "生产 BUY 18" in line


@pytest.mark.parametrize("bad", [{}, "20%", float("nan"), float("inf"), True])
def test_alignment_line_realized_clause_omitted_on_non_finite(tmp_path, bad):
    """G1 族: wr 非有限数值 (dict/str/NaN/inf/bool) → realized 子句省略, 不渲染垃圾."""
    from src.screening.offensive import daily_action as da

    payload = _alignment_summary(
        realized_only={**_alignment_summary()["realized_only"], "win_rate_pct": bad}
    )
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert line is not None
    assert "· 已平仓" not in line


def test_alignment_line_date_shape_guard(tmp_path):
    """G2a (修复前 RED = 『对账 banana』照常渲染): date 非八位 → 整行 None."""
    from src.screening.offensive import daily_action as da

    line = da._render_universe_alignment_line(
        _write_alignment(tmp_path, _alignment_summary(date="banana"))
    )
    assert line is None
    assert da._render_universe_alignment_line(
        _write_alignment(tmp_path / "b", _alignment_summary(date="202609051"))
    ) is None


def test_alignment_line_future_date_renders_anomaly_explicitly(tmp_path):
    """G2b (修复前 RED = 未来日期静默照常渲染): 合法 8 位未来日 → 异常显形出行
    (R115b G1 文案先例), 其余统计照常."""
    from datetime import date as _date

    from src.screening.offensive import daily_action as da

    payload = _alignment_summary(date="20260910")
    line = da._render_universe_alignment_line(
        _write_alignment(tmp_path, payload), as_of=_date(2026, 9, 5)
    )
    assert line is not None
    assert "⚠ 对账日期 20260910 在今日之后（工件异常）" in line
    assert "生产 BUY 18 · matched 9 · 分裂 9" in line


@pytest.mark.parametrize("mutate", [
    lambda p: p["class_counts"].update(matched=27),
    lambda p: p["class_counts"].update(matched=5),
    lambda p: p.update(total_buys=36),
])
def test_alignment_line_count_inconsistency_omits_line(tmp_path, mutate):
    """G3 (修复前 RED = matched 27 > total 18 照常渲染): 计数内部矛盾 → 整行 None."""
    from src.screening.offensive import daily_action as da

    payload = _alignment_summary()
    mutate(payload)
    assert da._render_universe_alignment_line(_write_alignment(tmp_path, payload)) is None


# ---------- R121b Op2: 宇宙对齐行分 store 时代归属披露 ----------

def _stores_block(journal_buys=18, ledger_buys=15, ledger_realized=None):
    """R121b stores 块 — journal 18 + ledger 15 = union 33 的取证镜像."""
    stores = {}
    if journal_buys:
        stores["legacy_journal"] = {
            "buys": journal_buys, "open_buys": 3,
            "realized_only": {
                "n": 12, "win_rate_pct": 16.67, "avg_win_pct": 8.52,
                "avg_loss_pct": -10.9, "payoff": 0.78, "expectancy_pct": -7.5,
            },
        }
    if ledger_buys:
        stores["ledger_v2"] = {
            "buys": ledger_buys, "open_buys": 6,
            "realized_only": ledger_realized if ledger_realized is not None else {
                "n": 9, "win_rate_pct": 22.22, "avg_win_pct": 10.49,
                "avg_loss_pct": -13.0, "payoff": 0.81, "expectancy_pct": -8.93,
            },
        }
    return stores


def test_alignment_line_store_split_clause_and_ledger_realized(tmp_path):
    """stores 块在场: 分 store 计数子句 + 台账已平仓子句 + 合并口径尾注."""
    from src.screening.offensive import daily_action as da

    counts = {**_alignment_summary()["class_counts"],
              "matched": 27, "day_missing_from_court": 3, "ticker_not_in_court_day": 3}
    payload = _alignment_summary(
        total_buys=33,
        class_counts=counts,
        latest_split_signal_date="20260813",
        realized_only={**_alignment_summary()["realized_only"],
                       "n": 21, "expectancy_pct": -8.3},
        stores=_stores_block(),
    )
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert line is not None
    assert "生产 BUY 33 · matched 27 · 分裂 6（最晚分裂 20260813）" in line
    assert "（legacy journal 18 · v2 台账 15）" in line
    assert "· 台账已平仓 9 胜率 22.22% 期望 -8.93%" in line
    assert "legacy journal+v2 台账合并已平仓口径" in line
    # 旧 journal-only 尾注不再出现 (口径更新防同屏矛盾)
    assert "realized 为 paper journal 已平仓口径" not in line


def test_alignment_line_legacy_summary_renders_unchanged(tmp_path):
    """无 stores 键的旧 summary → 渲染逐字节回退旧行 (向后兼容契约)."""
    from src.screening.offensive import daily_action as da

    payload = _alignment_summary()
    assert "stores" not in payload
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert line is not None
    assert "（legacy journal" not in line and "v2 台账" not in line
    assert "· 台账已平仓" not in line
    assert "realized 为 paper journal 已平仓口径" in line


def test_alignment_line_empty_stores_renders_old_tail(tmp_path):
    """stores 显式空块 (ledger 缺席的 legacy-only 世界) → 同旧行, 无分裂子句."""
    from src.screening.offensive import daily_action as da

    payload = _alignment_summary(stores={
        "legacy_journal": {"buys": 18, "open_buys": 3, "realized_only": None},
    })
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert line is not None
    assert "（legacy journal 18）" in line
    assert "v2 台账" not in line
    assert "· 台账已平仓" not in line
    assert "legacy journal+v2 台账合并已平仓口径" not in line


@pytest.mark.parametrize("mutate, ledger_gone", [
    (lambda s: s.update(ledger_v2={"buys": "15", "open_buys": 0}), True),
    (lambda s: s.update(ledger_v2={"buys": True, "open_buys": 0}), True),
    (lambda s: s.update(ledger_v2="garbage"), True),
    # legacy buys=0 → legacy 项省略, ledger 项照常 (不是整块拒绝)
    (lambda s: s.update(legacy_journal={"buys": 0}), False),
])
def test_alignment_line_malformed_store_block_omits_clause(tmp_path, mutate, ledger_gone):
    """stores 畸形 (buys 非正整数/块非 dict) → 该项省略, 行不炸不渲染垃圾."""
    from src.screening.offensive import daily_action as da

    stores = _stores_block()
    mutate(stores)
    counts = {**_alignment_summary()["class_counts"],
              "matched": 27, "day_missing_from_court": 3, "ticker_not_in_court_day": 3}
    payload = _alignment_summary(total_buys=33, class_counts=counts, stores=stores)
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert line is not None
    assert ("· 台账已平仓" in line) is (not ledger_gone)


def test_alignment_line_ledger_realized_non_finite_omits_subclause(tmp_path):
    """台账 realized 数值垃圾 → 台账子句省略, 分 store 计数子句照常 (R119 P1 镜像)."""
    from src.screening.offensive import daily_action as da

    bad = {"n": 9, "win_rate_pct": "22.22", "expectancy_pct": float("nan"),
           "avg_win_pct": None, "avg_loss_pct": None, "payoff": None}
    counts = {**_alignment_summary()["class_counts"],
              "matched": 27, "day_missing_from_court": 3, "ticker_not_in_court_day": 3}
    payload = _alignment_summary(total_buys=33, class_counts=counts,
                                 stores=_stores_block(ledger_realized=bad))
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert line is not None
    assert "（legacy journal 18 · v2 台账 15）" in line
    assert "· 台账已平仓" not in line


def test_alignment_line_post_ledger_anomaly_annotation(tmp_path):
    """R121c F2: post_ledger_start_buys>0 → 结构异常子句显形 (测试污染笔不冒充历史生产)."""
    from src.screening.offensive import daily_action as da

    stores = _stores_block()
    stores["legacy_journal"]["post_ledger_start_buys"] = 3
    counts = {**_alignment_summary()["class_counts"],
              "matched": 27, "day_missing_from_court": 3, "ticker_not_in_court_day": 3}
    payload = _alignment_summary(total_buys=33, class_counts=counts, stores=stores)
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert line is not None
    assert "（legacy journal 18 · v2 台账 15），其中台账启用后 journal 尾部 3 笔（结构异常）" in line


def test_alignment_line_no_anomaly_clause_when_clean_or_absent(tmp_path):
    """post 计数缺失或为 0 → 异常子句省略 (legacy-only 旧世界零噪声)."""
    from src.screening.offensive import daily_action as da

    stores = _stores_block()
    stores["legacy_journal"]["post_ledger_start_buys"] = 0
    counts = {**_alignment_summary()["class_counts"],
              "matched": 27, "day_missing_from_court": 3, "ticker_not_in_court_day": 3}
    payload = _alignment_summary(total_buys=33, class_counts=counts, stores=stores)
    line = da._render_universe_alignment_line(_write_alignment(tmp_path, payload))
    assert line is not None
    assert "结构异常" not in line

    legacy_only = _alignment_summary(stores={
        "legacy_journal": {"buys": 18, "open_buys": 3, "realized_only": None},
    })
    line2 = da._render_universe_alignment_line(_write_alignment(tmp_path, legacy_only))
    assert line2 is not None
    assert "结构异常" not in line2


# ---------------------------------------------------------------------------
# R125 Op3: 今日信号日 cohort 语境行 (fail-open 家族, 镜像入选质量行四面)
# ---------------------------------------------------------------------------

def _write_cohort_report(base, day="20260905"):
    import json as _json
    base.mkdir(parents=True, exist_ok=True)
    payload = {
        "cohort_buckets": [
            {"bucket": "1", "days": 9, "n": 9, "day_e_median": 0.0184,
             "event_stats": {"n": 9, "winrate": 0.556, "expectancy": 0.1125,
                             "cluster_ci_low_90": None}},
            {"bucket": "4-9", "days": 45, "n": 293, "day_e_median": -0.0233,
             "event_stats": {"n": 293, "winrate": 0.348, "expectancy": -0.0249,
                             "cluster_ci_low_90": -0.0386}},
            {"bucket": "20+", "days": 26, "n": 864, "day_e_median": 0.0064,
             "event_stats": {"n": 864, "winrate": 0.503, "expectancy": 0.0126,
                             "cluster_ci_low_90": -0.017}},
        ],
    }
    (base / f"signal_day_cohort_{day}.json").write_text(
        _json.dumps(payload), encoding="utf-8")
    return base


def test_day_cohort_line_bucket_stats_and_small_sample_note(case, tmp_path, monkeypatch):
    """正常形态: 规模→桶映射 + 历史战绩并置; 小样本桶 CI 缺失显式尾注."""
    _patch_quality_reports_dir(monkeypatch, _write_cohort_report(tmp_path))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    # 3 只 picks → cohort 规模 3 → 「2-3」桶无样本 → 只报只数形态
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        plan_details=(
            _detail("111.SZ", 0.72),
            _detail("222.SZ", 0.72),
            _detail("333.SZ", 0.55),
        ),
    )
    text = render_daily_action_v2(view)
    assert "今日同振语境" in text
    assert "「2-3」桶无样本" in text
    assert "不改变计划与执行" in text


def test_day_cohort_line_hits_bucket_with_stats(case, tmp_path, monkeypatch):
    """6 只 picks → 4-9 桶 (45 日 · 事件 E -2.49% · 胜率 34.8% · CI -3.86%)."""
    _patch_quality_reports_dir(monkeypatch, _write_cohort_report(tmp_path))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        plan_details=tuple(_detail(f"{i}.SZ", 0.72) for i in range(111, 117)),
    )
    text = render_daily_action_v2(view)
    assert "今日计划 6 只 → 历史同规模「4-9」桶" in text
    assert "45 日 · 事件 E -2.49% · 胜率 34.8% · CI90 下界 -3.86%" in text


def test_day_cohort_line_small_sample_bucket_ci_note(case, tmp_path, monkeypatch):
    """单票 cohort → 「1」桶 (n=9<30) → CI 不产出尾注."""
    _patch_quality_reports_dir(monkeypatch, _write_cohort_report(tmp_path))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        plan_details=(_detail("111.SZ", 0.72),),
    )
    text = render_daily_action_v2(view)
    assert "今日计划 1 只 → 历史同规模「1」桶" in text
    assert "CI 不产出（小样本只披露）" in text


def test_day_cohort_line_absent_without_picks(case, tmp_path, monkeypatch):
    _patch_quality_reports_dir(monkeypatch, _write_cohort_report(tmp_path))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "今日同振语境" not in render_daily_action_v2(view)


def test_day_cohort_line_absent_when_report_corrupt(case, tmp_path, monkeypatch):
    """最新报告损坏 → 整行省略, 不回退旧报告 (镜像质量行纪律)."""
    base = _write_cohort_report(tmp_path, day="20260903")
    (base / "signal_day_cohort_20260905.json").write_text("\x00 not json", encoding="utf-8")
    _patch_quality_reports_dir(monkeypatch, base)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        plan_details=(_detail("111.SZ", 0.72),),
    )
    assert "今日同振语境" not in render_daily_action_v2(view)


# ---------- R126 Op3: 日层 cohort 触发器状态行 (第二判定面日度可见性) ----------

def _day_cohort_ledger(tmp_path, records):
    import json
    path = tmp_path / "day_cohort_trigger_ledger.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def _day_cohort_rec(day, c1_lit, c2_lit, c1_judged=True, c2_judged=True,
                    armed=False, window_end="20260905"):
    rec = {
        "date": day,
        "anchor": "production_aligned/t10/cohort_size",
        "min_n": 30,
        "conjunction_armed": armed,
        "court": {"window_end": window_end, "rows": 1627},
    }
    if c1_judged:
        rec["strong_bucket"] = {"lit": c1_lit, "judged": True, "n": 864, "stat": -0.017}
    if c2_judged:
        rec["mid_buckets"] = {"lit": c2_lit, "judged": True, "n": 293, "stat": -0.011}
    return rec


def _patch_day_cohort_ledger(monkeypatch, path):
    from src.screening.offensive import cohort_trigger as ct

    monkeypatch.setattr(ct, "COHORT_TRIGGER_LEDGER_PATH", path)


def test_day_cohort_trigger_line_renders_conditions(case, tmp_path, monkeypatch):
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, [
        _day_cohort_rec("20260904", c1_lit=False, c2_lit=True),
        _day_cohort_rec("20260905", c1_lit=False, c2_lit=True),
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "日层 cohort 触发器" in text
    assert "条件C1 20+ 桶 CI>0 未亮（连亮 0）" in text
    assert "条件C2 中间桶(4-9/10-19)转负 已亮（连亮 2）" in text
    assert "日层合取未武装（连亮 0）" in text
    assert "历史最多日层合取连亮 0" in text
    assert "court 覆盖至 20260905" in text
    assert "账本 2 条" in text
    assert "披露不是行为改变" in text


def test_day_cohort_trigger_line_omitted_when_ledger_missing(case, tmp_path, monkeypatch):
    _patch_day_cohort_ledger(monkeypatch, tmp_path / "nope.jsonl")
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "日层 cohort 触发器" not in render_daily_action_v2(view)


def test_day_cohort_trigger_line_armed_and_unjudged(case, tmp_path, monkeypatch):
    """武装态显示 owner 评估就绪; 未判定条件按格披露样本不足 — 不假装知道."""
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, [
        _day_cohort_rec("20260905", c1_lit=True, c2_lit=True,
                        c1_judged=False, c2_judged=False, armed=True),
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "条件C1 20+ 桶 CI>0 样本不足未判定" in text
    assert "条件C2 中间桶(4-9/10-19)转负 样本不足未判定" in text
    assert "日层合取已武装 → cohort 规模条件化正式评估就绪" in text


def test_day_cohort_trigger_line_survives_poisoned_condition_values(case, tmp_path, monkeypatch):
    """行内条件值非 dict (手编账本/损坏写入) → 该格未判定, 渲染不炸 (R119 双层)."""
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, [
        {"date": "20260905", "anchor": "production_aligned/t10/cohort_size",
         "strong_bucket": "corrupted", "mid_buckets": 42,
         "conjunction_armed": False, "court": {"window_end": "20260905"}},
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "日层 cohort 触发器" in text
    assert "样本不足未判定" in text
    assert "日层合取未武装" in text


# ---------- R129 Op1: 日层族 K 预注册子句 (单一事实源接入渲染行) ----------

def _patch_cohort_k_files(monkeypatch, reg_payload, tmp_path):
    import json as _json

    from src.screening.offensive import cohort_trigger as ct

    reg_path = tmp_path / "cohort_trigger_k.json"
    if reg_payload is None:
        reg_path.write_text("{corrupted", encoding="utf-8")
    elif reg_payload is not False:
        reg_path.write_text(
            _json.dumps(reg_payload, ensure_ascii=False), encoding="utf-8"
        )
    obs_path = tmp_path / "cohort_trigger_k_observations.jsonl"
    monkeypatch.setattr(ct, "COHORT_K_REGISTRATION_PATH", reg_path)
    monkeypatch.setattr(ct, "COHORT_K_OBSERVATION_LOG_PATH", obs_path)


def test_day_cohort_trigger_line_unregistered_k_byte_identical(case, tmp_path, monkeypatch):
    """未注册态 (现默认) 渲染行与修复前逐字节一致 — K 子句单一事实源的
    缺席句就是本行旧硬编码尾句 (A2 钉死, 零现行为变化)。"""
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, [
        _day_cohort_rec("20260905", c1_lit=False, c2_lit=True),
    ]))
    _patch_cohort_k_files(monkeypatch, False, tmp_path)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    line = next(
        ln for ln in text.splitlines() if ln.startswith("日层 cohort 触发器")
    )
    assert line.endswith(" · 稳定阈值 K 属 owner 预注册；披露不是行为改变")


def test_day_cohort_trigger_line_registered_k_reports_window(case, tmp_path, monkeypatch):
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, [
        _day_cohort_rec("20260903", c1_lit=True, c2_lit=True, armed=True),
        _day_cohort_rec("20260904", c1_lit=True, c2_lit=True, armed=True),
    ]))
    _patch_cohort_k_files(monkeypatch, {
        "anchor": "production_aligned/t10/cohort_size",
        "registered_date": "20260901",
        "k": 2,
    }, tmp_path)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "预注册 K=2（自 20260901 起计资格连亮 2/2）" in text
    assert "资格达成" in text
    assert "稳定阈值 K 属 owner 预注册；披露不是行为改变" not in text


def test_day_cohort_trigger_line_registered_k_below_threshold(case, tmp_path, monkeypatch):
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, [
        _day_cohort_rec("20260904", c1_lit=False, c2_lit=True, armed=False),
    ]))
    _patch_cohort_k_files(monkeypatch, {
        "anchor": "production_aligned/t10/cohort_size",
        "registered_date": "20260901",
        "k": 3,
    }, tmp_path)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "预注册 K=3（自 20260901 起计资格连亮 0/3）" in text
    assert "资格达成" not in text


def test_day_cohort_trigger_line_malformed_k_discloses_fix_path(case, tmp_path, monkeypatch):
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, [
        _day_cohort_rec("20260904", c1_lit=False, c2_lit=True),
    ]))
    _patch_cohort_k_files(monkeypatch, None, tmp_path)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "稳定阈值 K 预注册文件损坏" in text
    assert "cohort_trigger_k.json" in text


def test_day_cohort_trigger_line_k_survives_disclosure_failure(case, tmp_path, monkeypatch):
    """K 注册面损坏为不可恢复形态 (非 OSError 家族) 也不炸渲染 — 行内
    fail-open 只覆盖文件读取, disclosure 自身异常由本行 try 家族兜底省略
    全行是既有语义; 本测试钉毒化注册文件 (list 形态) 走 malformed 句。"""
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, [
        _day_cohort_rec("20260904", c1_lit=False, c2_lit=True),
    ]))
    _patch_cohort_k_files(monkeypatch, ["not", "a", "dict"], tmp_path)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "日层 cohort 触发器" in text
    assert "预注册文件损坏" in text


# ---------- R128 Op1: 强度触发器状态行渲染毒化守卫 ----------

def test_trigger_state_line_poisoned_condition_renders_unjudged(case, tmp_path, monkeypatch):
    """R128 Op1 (R127 Op2 渲染消费面同族收尾): 行内条件值 truthy 非 dict
    (手编账本/损坏写入/形态演化) — 修复前 `_render_trigger_state_line` 的
    `latest.get("condition_1") or {}` 对 truthy 非 dict 不兜底, `.get` 裸
    AttributeError 炸 --daily-action 日度命令 (R115 Op1 fail-open 家族违例)。
    修复后毒化格按未判定披露 (缺键同语义, advisory 不假装), 非毒化子句照常。"""
    for poisoned in ("lit", ["lit"], 7, True):
        rec = _trigger_rec("20260830", c1_lit=True, c2_lit=False)
        rec["condition_1"] = poisoned
        _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
            _trigger_rec("20260829", c1_lit=True, c2_lit=False),
            rec,
        ]))
        service, _repository, as_of, _sessions = case
        context = service.advance_lifecycle(as_of)
        run = service.complete_run(context, candidates=())
        view = DailyActionV2Run(run, (), run.open_positions, (), ())
        text = render_daily_action_v2(view)
        assert "强度阈值触发器" in text  # 整行不炸 (fail-open 家族)
        assert "条件① ≥0.70 桶 CI>0 样本不足未判定" in text  # 毒化格降级未判定
        assert "条件② 0.50-0.60 转负 未亮（连亮 0）" in text  # 非毒化格照常
        assert "court 覆盖至 20260830" in text  # 覆盖子句不受牵连


# ---------- R129 Op3: 二进制损坏文件 PoC (UnicodeDecodeError 家族收口) ----------

def _patch_strength_k_files(monkeypatch, tmp_path, k_bytes: bytes):
    from src.screening.offensive import threshold_trigger as _tt

    k_path = tmp_path / "threshold_trigger_k.json"
    k_path.write_bytes(k_bytes)
    obs_path = tmp_path / "threshold_trigger_k_obs.jsonl"
    obs_path.write_bytes(b"")
    monkeypatch.setattr(_tt, "K_REGISTRATION_PATH", k_path)
    monkeypatch.setattr(_tt, "K_OBSERVATION_LOG_PATH", obs_path)


def test_binary_k_registration_file_malformed_not_crash(case, tmp_path, monkeypatch):
    """非 UTF-8 损坏 K 注册文件: 修复前 UnicodeDecodeError (ValueError 子类)
    从 load_k_registration 裸逃逸, 强度行无 try 守卫 → 炸穿 --daily-action
    (R115 家族违例); 修复后按 loader malformed 契约披露明语句。"""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260904", c1_lit=True, c2_lit=False),
    ]))
    _patch_strength_k_files(monkeypatch, tmp_path, b"\xff\xfe\x00binary")
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "强度阈值触发器" in text
    assert "稳定阈值 K 预注册文件损坏" in text


def test_binary_ledger_file_strength_line_omitted_not_crash(case, tmp_path, monkeypatch):
    """非 UTF-8 损坏账本: 修复前 load_trigger_ledger 裸逃逸 → 炸; 修复后
    advisory 空态 → 整行省略 (fail-open 家族既有语义)。"""
    from src.screening.offensive import threshold_trigger as _tt

    binary_ledger = tmp_path / "binary_ledger.jsonl"
    binary_ledger.write_bytes(b"\xff\xfe\x00binary")
    monkeypatch.setattr(_tt, "LEDGER_PATH", binary_ledger)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "强度阈值触发器" not in text


def test_binary_cohort_k_file_shows_malformed_sentence(case, tmp_path, monkeypatch):
    """日层行二进制 K 文件: 修复前 UnicodeDecodeError 穿过 loader 被整行
    try 吞成整行省略 (与 loader malformed 明语句语义不一致); 修复后按
    malformed 契约披露损坏句, 行内其它子句照常。"""
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, [
        _day_cohort_rec("20260904", c1_lit=False, c2_lit=True),
    ]))
    from src.screening.offensive import cohort_trigger as ct

    k_path = tmp_path / "cohort_trigger_k.json"
    k_path.write_bytes(b"\xff\xfe\x00binary")
    obs_path = tmp_path / "cohort_k_obs.jsonl"
    obs_path.write_bytes(b"")
    monkeypatch.setattr(ct, "COHORT_K_REGISTRATION_PATH", k_path)
    monkeypatch.setattr(ct, "COHORT_K_OBSERVATION_LOG_PATH", obs_path)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "日层 cohort 触发器" in text
    assert "稳定阈值 K 预注册文件损坏" in text


def test_strength_line_max_streak_wording_disambiguated(case, tmp_path, monkeypatch):
    """F2: 『历史最多合取连亮 0/060 锚合取 0』斜杠连读被操作员判读为
    分数 (R129 冒烟实录) — 改为分隔符『·』措辞, 语义零变化。"""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260904", c1_lit=True, c2_lit=False),
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "历史最多合取连亮 0 · 历史最多 060 锚合取连亮 0" in text
    assert "/060 锚合取" not in text


def test_trigger_state_line_discloses_folded_duplicates(case, tmp_path, monkeypatch):
    """R130 Op2: 账本含同数据重复观测时, 状态行显式披露折叠 (真相消失必有名)。"""
    recs = []
    for day, we in (("20260904", "20260904"), ("20260905", "20260905")):
        r = _trigger_rec(day, c1_lit=True, c2_lit=False, window_end=we)
        r["court"]["content_digest"] = "sha256:" + "e3" * 32
        recs.append(r)
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, recs))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    text = render_daily_action_v2(DailyActionV2Run(run, (), run.open_positions, (), ()))
    assert "账本 2 条 · 折叠同数据重复观测 1 条" in text
    assert "条件① ≥0.70 桶 CI>0 已亮（连亮 1）" in text  # 重复观测不膨胀连亮


def test_trigger_state_line_clean_ledger_has_no_fold_clause(case, tmp_path, monkeypatch):
    """R130 Op2: 干净账本零新增文案 (零噪声纪律)。"""
    _patch_ledger(monkeypatch, _trigger_ledger(tmp_path, [
        _trigger_rec("20260829", c1_lit=True, c2_lit=False),
        _trigger_rec("20260830", c1_lit=True, c2_lit=False),
    ]))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    text = render_daily_action_v2(DailyActionV2Run(run, (), run.open_positions, (), ()))
    assert "折叠" not in text


def test_day_cohort_trigger_line_discloses_folded_duplicates(case, tmp_path, monkeypatch):
    """R130 Op2: 日层行同款折叠披露。"""
    recs = []
    for day, we in (("20260904", "20260904"), ("20260905", "20260905")):
        r = _day_cohort_rec(day, c1_lit=False, c2_lit=True, window_end=we)
        r["court"]["content_digest"] = "sha256:" + "e3" * 32
        recs.append(r)
    _patch_day_cohort_ledger(monkeypatch, _day_cohort_ledger(tmp_path, recs))
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    text = render_daily_action_v2(DailyActionV2Run(run, (), run.open_positions, (), ()))
    assert "账本 2 条 · 折叠同数据重复观测 1 条" in text
    assert "条件C2 中间桶(4-9/10-19)转负 已亮（连亮 1）" in text


def test_future_dated_poison_guarded_evidence_but_flagged_freshness(
    case, tmp_path, monkeypatch
):
    """未来日期毒报告在场时的双面行为 (R137 Op1 立面, R140 Op3 契约升级) —
    (a) 证据消费面 (先验漂移行) fail-closed: 毒报告不被当作证据也不回退次新
        合法报告 (守卫下沉共享读取体), 且以 typed 告警显形『不可用 — 毒化
        原因』而非旧契约的静默整行省略 (R140 Op3: 操作员必须看得见哪一行
        证据被谁挡住);
    (b) 异常显形面 (freshness 行) 照常出行: 报告日期在今日之后文案保留
        (R115b G1 告警不因守卫失效)。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, expectancy=-0.0001, wr=0.4456)
    poison = json.loads(
        (base / "winrate_payoff_decomposition_20260904.json").read_text(
            encoding="utf-8"
        )
    )
    poison["universes"]["production_aligned"]["horizons"]["t10"][0]["expectancy"] = 0.99
    (base / "winrate_payoff_decomposition_20990101.json").write_text(
        json.dumps(poison, ensure_ascii=False), encoding="utf-8"
    )
    _patch_drift_reports_dir(monkeypatch, base)

    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    # (a) 毒报告不被当作证据也不回退次新 — 且 R140 Op3 起 typed 告警显形
    assert "先验漂移披露：不可用" in text
    assert "20990101" in text
    assert "守卫拒绝读取" in text
    # 毒值 0.99 不得以任何形式进入先验漂移行渲染 (证据面仍 fail-closed)
    assert "先验漂移披露：BTST" not in text

    line = da._render_evidence_freshness_line(
        _date(2026, 9, 4), today=_date(2026, 9, 5)
    )
    assert line is not None  # (b) 异常显形保留
    assert "报告日期在今日之后（文件名或时钟异常）" in line
    assert "20990101" in line


def test_future_probe_uses_injected_today_one_clock(case, tmp_path, monkeypatch):
    """R137 Op2 (F2): freshness 探测与渲染必须同一时钟 — 探测经 today 注入
    锚定注入世界 (R127 测试确定性纪律的补全)。注入 today 晚于报告 (注入
    世界=合法昨日) → 探测 None + 整行省略, 即使真实钟仍判未来; 注入 today
    早于报告 → 异常照常 (单钟两方向钉死)。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20990101")
    _patch_drift_reports_dir(monkeypatch, base)

    # 方向一: 注入 today (2099-12-31) 晚于报告 → 非未来, 探测 None, 行省略
    assert da._future_dated_report_day(base, today=_date(2099, 12, 31)) is None
    line = da._render_evidence_freshness_line(
        _date(2099, 12, 30), reports_dir=base, today=_date(2099, 12, 31)
    )
    assert line is None

    # 方向二: 注入 today (2026-09-01) 早于报告 → 异常探测与文案照常
    assert da._future_dated_report_day(base, today=_date(2026, 9, 1)) == "20990101"
    line = da._render_evidence_freshness_line(
        _date(2026, 9, 1), reports_dir=base, today=_date(2026, 9, 1)
    )
    assert line is not None
    assert "报告日期在今日之后（文件名或时钟异常）" in line
    assert "20990101" in line


# ━━━ R140 Op3: 未来日期毒文件 typed 告警族 (R137 开放项②收口) ━━━


def test_future_dated_probe_single_source_delegation(tmp_path):
    """daily_action._future_dated_report_day 委托 gap_disclosure 单一实现 —
    两处行为分叉 (一侧拒一侧看不见) 在源头钉死。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.gap_disclosure import future_dated_report_day

    base = _write_decomposition_report(tmp_path, date="20990101")
    assert da._future_dated_report_day(
        base, today=_date(2026, 9, 1)
    ) == future_dated_report_day(base, today=_date(2026, 9, 1)) == "20990101"


def test_future_dated_probe_injected_clock_two_directions(tmp_path):
    """today 注入锚双向: 注入晚于毒日期 → 无毒化; 注入早于 → 探测命中。"""
    from datetime import date as _date
    from src.screening.offensive.gap_disclosure import future_dated_report_day

    base = _write_decomposition_report(tmp_path, date="20990101")
    assert future_dated_report_day(base, today=_date(2099, 12, 31)) is None
    assert future_dated_report_day(base, today=_date(2026, 9, 1)) == "20990101"


def test_prior_drift_line_poison_typed_warning(tmp_path, monkeypatch):
    """先验漂移行: 毒文件在场 → typed 告警携带毒日期; 毒值不进渲染。"""
    import json as _json
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, expectancy=-0.0001, wr=0.4456)
    poison = _json.loads(
        (base / "winrate_payoff_decomposition_20260904.json").read_text(
            encoding="utf-8"
        )
    )
    poison["universes"]["production_aligned"]["horizons"]["t10"][0][
        "expectancy"
    ] = 0.99
    (base / "winrate_payoff_decomposition_20990101.json").write_text(
        _json.dumps(poison, ensure_ascii=False), encoding="utf-8"
    )
    line = da._render_prior_drift_line(base, today=_date(2026, 9, 5))
    assert line is not None
    assert line.startswith("先验漂移披露：不可用 — ")
    assert "20990101" in line and "守卫拒绝读取" in line
    assert "0.99" not in line and "+99.00%" not in line


def test_prior_drift_line_clean_missing_dir_byte_identical_absence(
    tmp_path, monkeypatch
):
    """非毒化 None 形态 (目录缺失/纯损坏) 维持整行省略 (fail-open 不回归)。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    empty = tmp_path / "empty"
    empty.mkdir()
    assert da._render_prior_drift_line(empty, today=_date(2026, 9, 5)) is None
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "winrate_payoff_decomposition_20260904.json").write_text(
        "{broken", encoding="utf-8"
    )
    assert (
        da._render_prior_drift_line(corrupt, today=_date(2026, 9, 5)) is None
    )


def test_picks_quality_line_poison_typed_warning(case, tmp_path):
    """入选质量构成行: 毒文件在场 → typed 告警 (非毒化省略形态不变)。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = tmp_path / "reports"
    base.mkdir()
    (base / "winrate_payoff_decomposition_20990101.json").write_text("{}",)
    line = da._render_picks_quality_line(
        [_detail("111.SZ", 0.72)], base, today=_date(2026, 9, 5)
    )
    assert line is not None
    assert line.startswith("入选质量构成：不可用 — ")
    assert "20990101" in line


def test_gap_reference_line_poison_typed_warning(tmp_path):
    """执行面缺口参考行: 毒文件在场 → typed 告警。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = tmp_path / "reports"
    base.mkdir()
    (base / "winrate_payoff_decomposition_20990101.json").write_text("{}")
    line = da._render_gap_reference_line(base, today=_date(2026, 9, 5))
    assert line is not None
    assert line.startswith("执行面缺口参考：不可用 — ")
    assert "20990101" in line


def test_day_cohort_line_poison_typed_warning_cohort_glob(case, tmp_path):
    """cohort 语境行: cohort 报告族毒文件同等显形 (glob 参数族覆盖)。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = tmp_path / "reports"
    base.mkdir()
    (base / "signal_day_cohort_20990101.json").write_text("{}")
    line = da._render_day_cohort_line(
        [_detail("111.SZ", 0.72)], base, today=_date(2026, 9, 5)
    )
    assert line is not None
    assert line.startswith("信号日 cohort 语境：不可用 — ")
    assert "cohort 报告目录被未来日期文件占据" in line
    assert "20990101" in line


def test_day_cohort_line_clean_missing_dir_absent(case, tmp_path):
    """cohort 语境行非毒化形态: 目录缺失维持整行省略。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    empty = tmp_path / "empty"
    empty.mkdir()
    assert (
        da._render_day_cohort_line(
            [_detail("111.SZ", 0.72)], empty, today=_date(2026, 9, 5)
        )
        is None
    )


def test_poison_dir_all_evidence_rows_light_together(tmp_path):
    """R141 Op2 跨行一致性 smoke: 同毒化目录下四证据行 + freshness 行
    同屏全部携带毒文件日期。零 today 注入 — 管线统一真实钟, 跨行单钟
    是显形面不漏行的前提; freshness 行注入 calendar_sessions 是输入缝
    (该行在日历缺失时对全部形态 fail-open, 家族纪律, 非钟注入)。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = tmp_path / "reports"
    base.mkdir()
    (base / "winrate_payoff_decomposition_20990101.json").write_text("{}")
    (base / "signal_day_cohort_20990101.json").write_text("{}")
    sessions = (_date(2026, 9, 4), _date(2026, 9, 5))
    lines = {
        "prior_drift": da._render_prior_drift_line(base),
        "picks_quality": da._render_picks_quality_line(
            [_detail("111.SZ", 0.72)], base
        ),
        "gap_reference": da._render_gap_reference_line(base),
        "day_cohort": da._render_day_cohort_line(
            [_detail("111.SZ", 0.72)], base
        ),
        "freshness": da._render_evidence_freshness_line(
            _date(2026, 9, 5), reports_dir=base, calendar_sessions=sessions
        ),
    }
    for name, line in lines.items():
        assert line is not None, f"{name} 行毒化形态静默缺席"
        assert "20990101" in line, f"{name} 行未携带毒文件日期"


def _write_windowed_decomposition_report(tmp_path, with_window=True, date="20260904"):
    """R141 Op3: 带/不带 court_window 的分解报告 (gap anatomy 可读)。"""
    import json as _json
    base = tmp_path / "reports"
    base.mkdir(parents=True, exist_ok=True)
    payload = {
        "universes": {
            "production_aligned": {
                "horizons": {"t10": [{"group": "ALL", "n": 1627}]},
                "gap_anatomy": {
                    "available": True,
                    "buckets": [
                        {"bucket": "5~10%", "n": 157, "expectancy": -0.0401},
                        {"bucket": "0~2%", "n": 900, "expectancy": 0.0042},
                    ],
                },
            },
        },
    }
    if with_window:
        payload["court_window"] = {"start": "20250701", "end": "20260904"}
    (base / f"winrate_payoff_decomposition_{date}.json").write_text(
        _json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return base


def test_gap_reference_line_renders_build_and_window(tmp_path):
    """R141 Op3: gap 行区分『构建』与『覆盖至』两个事实。"""
    from src.screening.offensive import daily_action as da

    base = _write_windowed_decomposition_report(tmp_path, with_window=True)
    line = da._render_gap_reference_line(base)
    assert line is not None
    assert "court 证据构建 20260904 · 覆盖至 20260904" in line
    assert "court 证据截至" not in line


def test_gap_reference_line_old_report_falls_back_to_build_date(tmp_path):
    """旧报告缺 court_window → 回退构建日语义, 不虚构『覆盖至』。"""
    from src.screening.offensive import daily_action as da

    base = _write_windowed_decomposition_report(tmp_path, with_window=False)
    line = da._render_gap_reference_line(base)
    assert line is not None
    assert "court 证据构建 20260904" in line
    assert "覆盖至" not in line


def test_prior_drift_line_renders_window_when_present(tmp_path, monkeypatch):
    """R141 Op3: 漂移行『(X 构建 · 覆盖至 Y, n=…)』标注。"""
    import json as _json
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = tmp_path / "reports"
    base.mkdir()
    payload = _json.loads(
        (  # 复用共享 fixture 形态
            _write_decomposition_report(tmp_path, date="20260904")
            / "winrate_payoff_decomposition_20260904.json"
        ).read_text(encoding="utf-8")
    )
    payload["court_window"] = {"start": "20250701", "end": "20260905"}
    (base / "winrate_payoff_decomposition_20260904.json").write_text(
        _json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    line = da._render_prior_drift_line(base, today=_date(2026, 9, 5))
    assert line is not None
    assert "（20260904 构建 · 覆盖至 20260905，n=" in line


def test_prior_drift_line_old_report_keeps_legacy_format(tmp_path, monkeypatch):
    """旧报告缺 court_window → 现行『(X，n=…)』格式逐字节不变。"""
    from datetime import date as _date
    from src.screening.offensive import daily_action as da

    base = _write_decomposition_report(tmp_path, date="20260904")
    line = da._render_prior_drift_line(base, today=_date(2026, 9, 5))
    assert line is not None
    assert "（20260904，n=" in line
    assert "覆盖至" not in line
