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
    assert "060 锚合取 0" in text        # 0.60 锚历史最大武装段 (无 060 键)
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
    assert "court 覆盖至 20260827" in line
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
    assert "fetch_failed" in line


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
