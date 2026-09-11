"""--daily-action v2 渲染面测试 (R80 Op2) — 漏斗 per-condition 分桶行.

prefilter→hits 之间此前是黑箱: 0828 零命中日 (85 prefilter→0 命中) 的检测面
取证只能手工复现检测路径 (66 C2 / 16 C3 / 3 C1). 本文件钉死: detect_miss_stages
非空时渲染未命中分桶行 (只列非零桶), None 的旧构造点不出现分桶行 (向后兼容).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from pathlib import Path

import json

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action import (
    DailyActionV2Run,
    ScanFunnel,
    _render_reentry_proximity_line,
    _render_stop_loss_readiness_line,
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


# ---------- R149 Op3: 近期窗条件化披露行 (日报消费面收口) ----------

def _real_shape_trailing_window():
    """真实形态 (20260908 报告) 的 trailing_window 载荷 — 非对称 fixture (R13 教训).

    池化 E>0 / 半窗早负晚正 / delta>0 — 与全窗漂移行 (E<0 vs 先验) 方向相反,
    恰是本行要显形的分歧形态。
    """
    return {
        "available": True,
        "window_days_n": 20,
        "observed_days": 20,
        "first_day": "20260709",
        "last_day": "20260821",
        "pooled": {
            "n": 341, "wins": 178, "winrate": 0.5219941348973607,
            "avg_win": 0.1417149355706783, "avg_loss": -0.1463000636349404,
            "payoff": 0.9686594253594907, "expectancy": 0.004042076712860554,
            "cluster_ci_low_90": -0.05731911387539803,
        },
        "full_window_expectancy": -5.338592315450724e-05,
        "delta_vs_full": 0.004095462636015061,
        "strength_buckets": [
            {"bucket": "<0.50", "n": 144, "wins": 60, "winrate": 0.4166666666666667,
             "expectancy": -0.0454},
            {"bucket": "0.50-0.60", "n": 76, "wins": 42, "winrate": 0.5526315789473685,
             "expectancy": 0.0146},
        ],
        "gradient_monotone_up": True,
        "split_half": {
            "early": {"days": 10, "n": 228, "expectancy": -0.036577613496487256,
                      "winrate": 0.49122807017543857},
            "late": {"days": 10, "n": 113, "expectancy": 0.0860003897016331,
                     "winrate": 0.584070796460177},
            "sign_consistent": False,
        },
    }


def _write_decomposition_report_with_trailing(tmp_path, trailing, date="20260908"):
    """合成含 (或不含) trailing_window 的最新分解报告 — R149 Op1 additive 键形态."""
    base = _write_decomposition_report(tmp_path, date=date)
    payload_path = base / f"winrate_payoff_decomposition_{date}.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if trailing is not None:
        payload["universes"]["production_aligned"]["trailing_window"] = trailing
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return base


def test_trailing_window_line_renders_multi_view(case, tmp_path, monkeypatch):
    """A1: available=True → 池化/CI/梯度/半窗/delta 方向中性词 + owner 边界齐."""
    _patch_drift_reports_dir(
        monkeypatch,
        _write_decomposition_report_with_trailing(tmp_path, _real_shape_trailing_window()),
    )
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "近期窗判读" in text
    assert "尾 20 信号日" in text and "20260709..20260821" in text and "n=341" in text
    assert "+0.40%" in text and "52.2%" in text       # 池化 E / 胜率
    assert "CI90 下界 -5.73%" in text                  # 聚类 bootstrap CI
    assert "强度梯度单调非降: 是" in text
    assert "早 -3.66%/晚 +8.60% 符号翻转" in text       # 半窗 (真实形态: 符号翻转)
    assert "近期更强" in text                          # delta>0 方向中性词
    assert "owner" in text and "宪法 #2" in text        # 判读边界


def test_trailing_window_line_omitted_when_unavailable(case, tmp_path, monkeypatch):
    """A2: available 非 True (no_mature_rows/invalid_days_n 形态) → 整行省略."""
    tw = _real_shape_trailing_window()
    tw["available"] = False
    tw["reason"] = "no_mature_rows"
    _patch_drift_reports_dir(
        monkeypatch, _write_decomposition_report_with_trailing(tmp_path, tw)
    )
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "近期窗判读" not in render_daily_action_v2(view)


def test_trailing_window_line_omitted_when_key_missing_or_malformed(
    case, tmp_path, monkeypatch
):
    """A2: trailing_window 键缺失 / 非 dict → 整行省略 (fail-open 家族)."""
    service, _repository, as_of, _sessions = case

    # 键缺失
    _patch_drift_reports_dir(
        monkeypatch, _write_decomposition_report_with_trailing(tmp_path, None)
    )
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "近期窗判读" not in render_daily_action_v2(view)

    # 非 dict
    _patch_drift_reports_dir(
        monkeypatch,
        _write_decomposition_report_with_trailing(tmp_path, "garbage"),
    )
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "近期窗判读" not in render_daily_action_v2(view)


def test_trailing_window_line_omitted_when_report_missing(case, tmp_path, monkeypatch):
    """A2: 报告目录缺失 → 整行省略无异常 (fail-open 家族纪律)."""
    _patch_drift_reports_dir(monkeypatch, tmp_path / "no-such-reports")
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "近期窗判读" not in render_daily_action_v2(view)


def test_trailing_window_line_negative_delta_direction_symmetric(
    case, tmp_path, monkeypatch
):
    """A3: delta<0 → 「近期更弱」与正 delta「近期更强」方向词对称, 无归因叙事."""
    tw = _real_shape_trailing_window()
    tw["delta_vs_full"] = -0.0041
    tw["full_window_expectancy"] = 0.05
    _patch_drift_reports_dir(
        monkeypatch, _write_decomposition_report_with_trailing(tmp_path, tw)
    )
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "近期更弱" in text
    assert "近期更强" not in text
    assert "由旧窗主导" not in text   # Op2 A1 同款纪律: 方向词不携带归因叙事


def test_trailing_window_line_nonfinite_cells_omitted(case, tmp_path, monkeypatch):
    """A2/R119 家族: 池化 E 非有限 → 整行省略; CI 非有限 → 子句省略不虚构."""
    service, _repository, as_of, _sessions = case

    # 池化 E 非有限 (str 冒充数值) → 行主体缺失, 整行省略不以残行冒充
    tw = _real_shape_trailing_window()
    tw["pooled"]["expectancy"] = "oops"
    _patch_drift_reports_dir(
        monkeypatch, _write_decomposition_report_with_trailing(tmp_path, tw)
    )
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    assert "近期窗判读" not in render_daily_action_v2(view)

    # CI 非有限 (NaN) → CI 子句省略, 行其余照常 (不虚构 CI)
    tw = _real_shape_trailing_window()
    tw["pooled"]["cluster_ci_low_90"] = float("nan")
    _patch_drift_reports_dir(
        monkeypatch, _write_decomposition_report_with_trailing(tmp_path, tw)
    )
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    trailing = next(line for line in text.splitlines() if "近期窗判读" in line)
    assert "CI90" not in trailing   # CI 子句省略 (先验漂移行的 CI90 子句不相干)


def test_trailing_window_full_window_contrast_renders_both_numbers(
    case, tmp_path, monkeypatch
):
    """A1 (R151 Op1): 全窗对照双数形态 — 全窗 E 与近期差分列渲染.

    修复前 RED: 「全窗对照 +0.41%(近期更强)」把 delta_vs_full (近期−全窗差值)
    放在全窗标签下 — 读者把差值误读为全窗期望 (真实全窗 E=-0.00%), 与紧邻
    先验漂移行 (全窗 E -0.00%) 同报自相矛盾; 报告面同节是正确双数格式
    「全期 E=-0.00% → 近期差 +0.41%」。本测钉死值形态 (fixture 非对称:
    full_e≠delta, R13 教训), 防方向词断言再放过数字误导。
    """
    tw = _real_shape_trailing_window()
    assert tw["full_window_expectancy"] != tw["delta_vs_full"]  # 非对称前提
    _patch_drift_reports_dir(
        monkeypatch, _write_decomposition_report_with_trailing(tmp_path, tw)
    )
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    trailing = next(line for line in text.splitlines() if "近期窗判读" in line)
    assert "全窗 E -0.01%" in trailing       # 全窗数值 = payload full_window_expectancy (-5.34e-05 → -0.01%)
    assert "近期差 +0.41%" in trailing       # 差值独立标签 (零重算, 直取 payload)
    assert "全窗对照 +0.41%" not in trailing  # 修复前形态: delta 值在全窗标签下


def test_trailing_window_full_window_missing_or_nonfinite_degrades(
    case, tmp_path, monkeypatch
):
    """A3 (R151 Op1): full_window_expectancy 缺失/非有限 → 「较全窗差」降级形态
    (无全窗数值, 不虚构); delta 也非有限 → 整个子句省略 (fail-open 家族纪律)."""
    service, _repository, as_of, _sessions = case

    def _render_with(tw):
        _patch_drift_reports_dir(
            monkeypatch, _write_decomposition_report_with_trailing(tmp_path, tw)
        )
        context = service.advance_lifecycle(as_of)
        run = service.complete_run(context, candidates=())
        view = DailyActionV2Run(run, (), run.open_positions, (), ())
        text = render_daily_action_v2(view)
        return next(line for line in text.splitlines() if "近期窗判读" in line)

    # 键缺失 → 仅差值降级, 无全窗数值
    tw = _real_shape_trailing_window()
    del tw["full_window_expectancy"]
    trailing = _render_with(tw)
    assert "较全窗差 +0.41%" in trailing
    assert "全窗 E" not in trailing

    # 非有限 (NaN) → 同降级
    tw = _real_shape_trailing_window()
    tw["full_window_expectancy"] = float("nan")
    trailing = _render_with(tw)
    assert "较全窗差 +0.41%" in trailing
    assert "全窗 E" not in trailing

    # delta 非有限 → 整个子句省略 (方向词一并省略, 不以残子句冒充)
    tw = _real_shape_trailing_window()
    tw["delta_vs_full"] = float("nan")
    trailing = _render_with(tw)
    assert "全窗 E" not in trailing
    assert "较全窗差" not in trailing
    assert "近期更强" not in trailing and "近期更弱" not in trailing


def test_trailing_window_span_shape_guard_omits_garbage(
    case, tmp_path, monkeypatch
):
    """A1/A2 (R151 Op2): first_day/last_day 形状守卫 — 畸形 span 省略不虚构.

    修复前 RED (Observe 期 PoC): span 是行内唯一无形状守卫的单元格 (n/days/
    CI/E/半窗全有守卫), int 123/dict 裸 f-string 垃圾渲染直达操作员日报
    (「(123..None，n=10)」「({'a': 1}..[1, 2]，n=10)」), R119 P1 『垃圾渲染』
    家族违例; 修复后 8 位数字串 (同模块 _DATE_8_RE 单一实现) 才渲染。
    """
    service, _repository, as_of, _sessions = case

    def _render_with(tw):
        _patch_drift_reports_dir(
            monkeypatch, _write_decomposition_report_with_trailing(tmp_path, tw)
        )
        context = service.advance_lifecycle(as_of)
        run = service.complete_run(context, candidates=())
        view = DailyActionV2Run(run, (), run.open_positions, (), ())
        text = render_daily_action_v2(view)
        return next(line for line in text.splitlines() if "近期窗判读" in line)

    # int / None 混合畸形 → span 省略, 行主体与数值子句保留
    tw = _real_shape_trailing_window()
    tw["first_day"] = 123
    tw["last_day"] = None
    trailing = _render_with(tw)
    assert "123..None" not in trailing
    assert "近期窗判读：尾 20 信号日（n=341）期望" in trailing
    assert "全窗 E -0.01%" in trailing          # 其余子句不受影响 (Op1 双数形态)

    # dict/list repr 畸形 → 同守卫
    tw = _real_shape_trailing_window()
    tw["first_day"] = {"a": 1}
    tw["last_day"] = [1, 2]
    trailing = _render_with(tw)
    assert "{'a': 1}" not in trailing and "[1, 2]" not in trailing

    # banana / 7 位 / 9 位数字串 → 同守卫 (8 位 fullmatch 家族语义)
    for bad in ("banana", "2026070", "202607099"):
        tw = _real_shape_trailing_window()
        tw["first_day"] = bad
        trailing = _render_with(tw)
        assert bad not in trailing

    # 合法 8 位 span 照旧渲染 (修复后正常形态逐字节不变)
    trailing = _render_with(_real_shape_trailing_window())
    assert "（20260709..20260821，n=341）" in trailing


def test_trailing_window_zero_delta_flat_form(case, tmp_path, monkeypatch):
    """A4 (R151 Op2): delta=0 → 「近期差 +0.00%(持平)」三分支全覆盖 pin."""
    tw = _real_shape_trailing_window()
    tw["delta_vs_full"] = 0.0
    _patch_drift_reports_dir(
        monkeypatch, _write_decomposition_report_with_trailing(tmp_path, tw)
    )
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    trailing = next(line for line in text.splitlines() if "近期窗判读" in line)
    assert "近期差 +0.00%（持平）" in trailing
    assert "近期更强" not in trailing and "近期更弱" not in trailing


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


# ---------- R157 Op1: 止损启用条件读数行 (项 5 判定输入日度合取显形) ----------

def _stop_view(case, regime=None):
    """构造带 fresh 台账估值的 v2 run (回撤 0.0) 与其 as_of。

    regime 默认 None (行省略形态); 位置断言测试传 "crisis" 显形 Regime 行。
    """
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    return DailyActionV2Run(run, (), run.open_positions, (), (), regime=regime), as_of


class _StubValuation:
    def __init__(self, drawdown):
        self.drawdown = drawdown


class _StubServiceRun:
    def __init__(self, trade_date, valuation):
        self.trade_date = trade_date
        self.valuation = valuation


class _StubRun:
    def __init__(self, trade_date, valuation):
        self.service_run = _StubServiceRun(trade_date, valuation)


def test_stop_readiness_crisis_streak_counts_consecutive_days(case):
    """锚日在内的连续 crisis 天数逐日累计 (3 日 crisis → 3)。"""
    view, as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={
            "20260818": "crisis", "20260819": "crisis", "20260820": "crisis",
        },
    )
    assert "连续 crisis 3 日" in line


def test_stop_readiness_crisis_streak_resets_on_interruption(case):
    """回溯遇首个非 crisis 即停 — 连亮语义与触发器账本一致。"""
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={
            "20260818": "crisis", "20260819": "normal", "20260820": "crisis",
        },
    )
    assert "连续 crisis 1 日" in line


def test_stop_readiness_stale_anchor_discloses_cutoff_date(case):
    """regime 史滞后于今日 (最新标签 0819) → 截至日响亮披露, 不冒充今日读数。"""
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260818": "crisis", "20260819": "crisis"},
    )
    assert "连续 crisis 2 日（截至 0819）" in line


def test_stop_readiness_zero_streak_disclosed_when_no_crisis(case):
    """全 normal 史 → 连续 crisis 0 日照实显示 (触发行不静默省略)。"""
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260819": "normal", "20260820": "normal"},
    )
    assert "连续 crisis 0 日" in line


def test_stop_readiness_drawdown_margin_signed_against_reference():
    """余量 = drawdown − (−15%): 0% 回撤 → +15.0pp; 越线 → 已触及措辞。"""
    as_of = date(2026, 8, 20)
    fresh = _StubRun(as_of, _StubValuation(0.0))
    line = _render_stop_loss_readiness_line(fresh, regimes_by_date={})
    assert "回撤 0.0%（距 -15% 降仓参考线余量 +15.0pp）" in line

    breached = _StubRun(as_of, _StubValuation(-0.16))
    line = _render_stop_loss_readiness_line(breached, regimes_by_date={})
    assert "已触及 -15% 降仓参考线，余量 -1.0pp" in line


def test_stop_readiness_nonfinite_drawdown_clause_omitted():
    """NaN 回撤子句省略 (R119 数值守卫家族), streak 子句不受牵连。"""
    as_of = date(2026, 8, 20)
    run = _StubRun(as_of, _StubValuation(float("nan")))
    line = _render_stop_loss_readiness_line(
        run, regimes_by_date={"20260820": "crisis"},
    )
    assert line is not None
    assert "连续 crisis 1 日" in line
    assert "回撤" not in line


def test_stop_readiness_both_inputs_missing_line_omitted():
    """regime 史空 + 估值缺 → 整行省略 (fail-open, 不出残行)。"""
    run = _StubRun(date(2026, 8, 20), None)
    assert _render_stop_loss_readiness_line(run, regimes_by_date={}) is None


def test_stop_readiness_stop_mode_disclosed(case, monkeypatch):
    """登记状态如实双面: 默认 none (不启用) / 显式启用时反照 env。"""
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260820": "crisis"},
    )
    assert "止损执行模式 none（登记: 不启用）" in line

    monkeypatch.setenv("DAILY_ACTION_EXECUTION_STOP", "atr_k2")
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260820": "crisis"},
    )
    assert "止损执行模式 atr_k2（已启用）" in line


def test_stop_readiness_line_renders_after_regime_line(case, monkeypatch):
    """整链接线: render_daily_action_v2 中行位于 Regime 行之后, 协议指针在行内。"""
    view, _as_of = _stop_view(case, regime="crisis")
    import src.screening.offensive.daily_action as da

    monkeypatch.setattr(
        da, "_load_regime_history",
        lambda: {"20260819": "crisis", "20260820": "crisis"},
    )
    text = render_daily_action_v2(view)
    lines = text.splitlines()
    regime_idx = next(
        i for i, l in enumerate(lines) if l.startswith("Regime：")
    )
    stop_idx = next(
        i for i, l in enumerate(lines) if l.startswith("止损启用条件（清单项 5）")
    )
    assert stop_idx > regime_idx
    assert "连续 crisis 2 日" in lines[stop_idx]
    assert "backtest_exit_strategies.py" in lines[stop_idx]
    assert "DAILY_ACTION_EXECUTION_STOP" in lines[stop_idx]


def test_stop_readiness_datetime_trade_date_omitted_not_crash(monkeypatch):
    """F-a (R157 Op2): trade_date=datetime + 非空 regime 史 → 行省略不裸逃逸。

    service 路径 _plain_date 恒产 date (现行不可达); 本测试钉住防御线:
    渲染器接受任意 run 对象 (display/legacy 面), date<=datetime 的 TypeError
    必须被家族同款兜底吞为整行省略 (镜像 trailing/universe_alignment 先例),
    绝不炸掉整个 --daily-action 渲染。
    """
    import src.screening.offensive.daily_action as da

    run = _StubRun(datetime(2026, 8, 20, 18, 0), _StubValuation(-0.05))
    monkeypatch.setattr(
        da, "_load_regime_history",
        lambda: {"20260819": "crisis", "20260820": "crisis"},
    )
    assert _render_stop_loss_readiness_line(run) is None


def test_stop_readiness_future_only_keys_and_poison_keys_skip_gracefully():
    """F-j (R157 Op2): history 仅含 > as_of 键 → streak 子句省略, 行由回撤
    子句托住; 毒化键 (非 YYYYMMDD) 跳过不崩 (R150 教训同族)。
    """
    run = _StubRun(date(2026, 8, 20), _StubValuation(-0.05))
    line = _render_stop_loss_readiness_line(
        run, regimes_by_date={"20260821": "crisis", "not-a-date": "crisis"},
    )
    assert line is not None
    assert "连续 crisis" not in line
    assert "回撤" in line


# ---------- R158 Op1: 持仓退出建议行未实现盈亏披露 (纯披露, fail-open) ----------

def _run_with_open_position(tmp_path, *, as_of_index=20, close=8.0):
    """建仓 (entry sessions[15], 前置 ≥14 会话) → complete_run 带持仓视图.

    自足世界: 独立 ledger/prices (000909 恒价 close), 不依赖 case fixture.
    """
    from dataclasses import replace as dc_replace

    sessions = _sessions()
    prices = {("000909", session): _bar(close) for session in sessions}
    costs = ExecutionCosts(version="test", commission=5.0, other_fee=10.0)
    repository = LedgerRepository(
        tmp_path / "unrealized_pnl.sqlite3",
        "unrealized-pnl",
        1_000_000,
        execution_costs=costs,
    )
    repository.initialize()
    service = DailyActionService(
        repository,
        TradingSessionCalendar(sessions),
        lambda symbol, session: prices.get((symbol, session)),
        costs,
        enforce_manifest_gate=False,
    )
    entry_date = sessions[15]
    plan = repository.create_plan(
        "000909", "btst_breakout", "v2", sessions[14], entry_date, 0.10, 1
    )
    repository.settle_plan_at_open(
        plan.trade_id, entry_date, 10.0, 9.0, 11.0, False, 10.2, 9.8
    )
    target = sessions[as_of_index]
    context = service.advance_lifecycle(target)
    run = service.complete_run(context, candidates=())
    return run, sessions, target, dc_replace


def test_exit_advice_row_shows_unrealized_pct(tmp_path):
    """有浮盈亏 → 行内披露「浮 -20.0%」(与 v1 渲染器『浮』标记口径一致)."""
    run, _sessions, _target, _replace = _run_with_open_position(tmp_path)
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "浮 -20.0%" in text


def test_exit_advice_row_omits_clause_when_pct_none(tmp_path):
    """shadow_unrealized_pct=None (旧构造/数据不足) → 行与修复前逐字节一致."""
    run, _sessions, _target, dc_replace = _run_with_open_position(tmp_path)
    stripped = dc_replace(run.open_positions[0], shadow_unrealized_pct=None)
    view_with = DailyActionV2Run(run, (), run.open_positions, (), ())
    view_without = DailyActionV2Run(run, (), (stripped,), (), ())
    text_with = render_daily_action_v2(view_with)
    text_without = render_daily_action_v2(view_without)
    row_with = next(line for line in text_with.splitlines() if "000909" in line)
    row_without = next(line for line in text_without.splitlines() if "000909" in line)
    assert "浮" not in row_without
    assert row_without == row_with.replace(" 浮 -20.0%", "")


def test_exit_advice_row_omits_clause_when_pct_nonfinite(tmp_path):
    """毒化 (inf/nan) 浮盈亏 → 子句省略, 行不阻断 (typed-exception 家族纪律)."""
    import math

    run, _sessions, _target, dc_replace = _run_with_open_position(tmp_path)
    poisoned = dc_replace(run.open_positions[0], shadow_unrealized_pct=math.inf)
    view = DailyActionV2Run(run, (), (poisoned,), (), ())
    text = render_daily_action_v2(view)
    row = next(line for line in text.splitlines() if "000909" in line)
    assert "浮" not in row
    assert "影子建议" in row


# ---------- R158 Op2: 浮盈亏子句守卫对抗性钉住 (探针实证面) ----------

def test_exit_advice_row_bool_pct_is_omitted(tmp_path):
    """bool 旁路钉住: isinstance(True, Real)=True, 守卫的 not-bool 排除必须生效
    (否则未来重构把守卫简化成 isinstance 单判时会静默渲染 浮 +100%)."""
    import math
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    truthy = dc_replace(run.open_positions[0], shadow_unrealized_pct=True)
    view = DailyActionV2Run(run, (), (truthy,), (), ())
    text = render_daily_action_v2(view)
    row = next(line for line in text.splitlines() if "000909" in line)
    assert "浮" not in row
    assert "影子建议" in row
    assert not math.isnan(0.0)  # 占位避免 lint 空断言语义漂移


def test_exit_advice_row_zero_pct_is_shown_not_omitted(tmp_path):
    """falsy-zero 钉住: close==entry → 浮 +0.0% 必须显示 (守卫按 None/类型判定,
    不按真值 — 防未来改成 truthiness 判定时保本持仓静默漏显)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    zero = dc_replace(run.open_positions[0], shadow_unrealized_pct=0.0)
    view = DailyActionV2Run(run, (), (zero,), (), ())
    text = render_daily_action_v2(view)
    row = next(line for line in text.splitlines() if "000909" in line)
    assert "浮 +0.0%" in row


def test_exit_advice_row_non_real_poison_is_omitted(tmp_path):
    """非 Real 毒化 (字符串/对象) → 子句省略行不阻断 (isinstance Real 门)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    for poison in ("5%", object()):
        poisoned = dc_replace(run.open_positions[0], shadow_unrealized_pct=poison)
        view = DailyActionV2Run(run, (), (poisoned,), (), ())
        text = render_daily_action_v2(view)
        row = next(line for line in text.splitlines() if "000909" in line)
        assert "浮" not in row
        assert "影子建议" in row


def test_exit_advice_row_shows_pct_alongside_exit_advice(tmp_path):
    """并存形态钉住: should_exit=True 行同时披露 浮 与 建议次日退出 (决策两输入)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    exiting = dc_replace(run.open_positions[0], shadow_would_exit_next_open=True)
    view = DailyActionV2Run(run, (), (exiting,), (), ())
    text = render_daily_action_v2(view)
    row = next(line for line in text.splitlines() if "000909" in line)
    assert "浮 -20.0%" in row
    assert "建议次日退出" in row


# ---------- R159 Op1: 持仓行 T+10 到期日披露 (v1 C-DAILY-ACTION-POSITION-VISIBILITY 迁移恢复) ----------

def test_exit_advice_row_shows_maturity_date(tmp_path):
    """持仓行披露「到期 M/D（剩N天）」— 到期日与剩余日历日 (v1 同款口径),
    同日到期 cohort (0831 五笔集中释放) 由此日度可见."""
    run, _sessions, _target, _r = _run_with_open_position(tmp_path)
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    row = next(line for line in text.splitlines() if "000909" in line)
    # entry = sessions[15], T+10 = sessions[24], as_of = sessions[20] → 剩 4 天
    assert "到期 9/10（剩4天）" in row
    assert "影子建议" in row


def test_exit_advice_row_omits_maturity_when_none(tmp_path):
    """projected_exit_date=None (旧构造/日历不足) → 到期子句省略, 行其余部分
    与修复前逐字节一致 (R158 fail-open 同款钉住)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    stripped = dc_replace(run.open_positions[0], projected_exit_date=None)
    view_with = DailyActionV2Run(run, (), run.open_positions, (), ())
    view_without = DailyActionV2Run(run, (), (stripped,), (), ())
    text_with = render_daily_action_v2(view_with)
    text_without = render_daily_action_v2(view_without)
    row_with = next(line for line in text_with.splitlines() if "000909" in line)
    row_without = next(line for line in text_without.splitlines() if "000909" in line)
    assert "到期" in row_with
    assert "到期" not in row_without
    assert row_without == row_with.replace(" 到期 9/10（剩4天）", "")


def test_exit_advice_row_maturity_today(tmp_path):
    """到期日 == as_of → 「今日到期」形态 (v1 同款)."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    as_of = run.trade_date
    matured = dc_replace(run.open_positions[0], projected_exit_date=as_of)
    view = DailyActionV2Run(run, (), (matured,), (), ())
    text = render_daily_action_v2(view)
    row = next(line for line in text.splitlines() if "000909" in line)
    assert "今日到期" in row
    assert "剩" not in row


def test_exit_advice_row_maturity_survives_datetime_trade_date(tmp_path):
    """service_run.trade_date=datetime (R157 F-a 同款形态) → 到期子句整体省略,
    行不阻断 (datetime - date TypeError 被家族同款防御吞掉)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    stale_service_run = dc_replace(run, trade_date=datetime(2026, 9, 6, 18, 0))
    view = DailyActionV2Run(stale_service_run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    row = next(line for line in text.splitlines() if "000909" in line)
    assert "到期" not in row
    assert "影子建议" in row


# ---------- R159 Op2: 退出计划区到期子句 (F-a) + 过期日形态钉住 (F-c) ----------

def _run_with_exit_plan(tmp_path, *, with_date=True):
    """在 Op1 自足世界上叠加一条退出计划 item (day-9 视图)."""
    from dataclasses import replace as dc_replace

    from src.screening.offensive.daily_action_service import ActionItem

    run, sessions, _target, _r = _run_with_open_position(tmp_path)
    item = ActionItem(
        "t-fa", "000909", "maximum_holding_session", "pending", "pending",
        target_exit_date=sessions[24] if with_date else None,
    )
    service_run = dc_replace(run, exit_plans=(item,))
    return run, service_run, sessions


def test_exit_plan_row_shows_maturity_date(tmp_path):
    """F-a: 退出计划行披露「到期 M/D（剩N天）」— day-9/10 退出窗口的日期可见性."""
    run, service_run, _sessions = _run_with_exit_plan(tmp_path)
    view = DailyActionV2Run(service_run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    section = text.split("退出计划（")[1]
    row = next(line for line in section.splitlines() if "000909" in line)
    assert "到期 9/10（剩4天）" in row


def test_exit_plan_row_omits_maturity_when_none(tmp_path):
    """target_exit_date=None (旧构造点) → 退出计划行与修复前逐字节一致."""
    run, service_run, _sessions = _run_with_exit_plan(tmp_path, with_date=False)
    view = DailyActionV2Run(service_run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    section = text.split("退出计划（")[1]
    row = next(line for line in section.splitlines() if "000909" in line)
    assert "到期" not in row
    assert "000909" in row


def test_deferred_exit_row_never_shows_maturity_clause(tmp_path):
    """语义区隔钉住: 延迟退出行不加日期子句 — 延期后 target 日期不可靠,
    即使 item 意外携带 target_exit_date 也不渲染 (防未来管道误扩散)."""
    from dataclasses import replace as dc_replace

    from src.screening.offensive.daily_action_service import ActionItem

    run, _sessions, target, _r = _run_with_open_position(tmp_path)
    item = ActionItem(
        "t-def", "000909", "unknown_queue", "pending", "pending",
        target_exit_date=target,
    )
    service_run = dc_replace(run, deferred_exits=(item,))
    view = DailyActionV2Run(service_run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    section = text.split("延迟退出")[1]
    row = next(line for line in section.splitlines() if "000909" in line)
    assert "到期" not in row


def test_maturity_clause_past_date_shows_date_only():
    """F-c 钉住: 过期日 (days<0, 陈旧渲染面) 只披露日期不显负数天数."""
    from src.screening.offensive.daily_action import _maturity_clause

    assert _maturity_clause(date(2026, 9, 1), date(2026, 9, 10)) == " 到期 9/1"
    assert _maturity_clause(date(2026, 9, 14), date(2026, 9, 10)) == " 到期 9/14（剩4天）"


# ---------- R162 Op1: 到期释放日程聚合行 (v1 C-DAILY-ACTION-POSITION-VISIBILITY 第三项迁移恢复) ----------

def test_release_schedule_line_shows_soonest_cohort(tmp_path):
    """单仓未来到期 → 聚合行披露日期/只数/释放敞口/剩余敞口 + cap 恢复提示;
    释放敞口与 open_exposure 同基准 (单持仓时相等), after = 持仓+待成交 − 释放."""
    run, _sessions, _t, _r = _run_with_open_position(tmp_path)
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    assert "最近到期 9/10（剩4天）" in line
    assert "释放 1 只 / " in line
    weight = run.open_positions[0].mark_weight
    assert f"{weight:.0%} 敞口" in line
    total = run.open_exposure + run.reserved_exposure
    assert f"约 {max(0.0, total - weight):.0%}" in line
    assert "（降回上限内，可恢复出新仓）" in line


def test_release_schedule_line_aggregates_same_date_cohort(tmp_path):
    """同日多仓 cohort → 只数与释放敞口按 cohort 合计 (0831 五仓 9/14 形态)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    first = run.open_positions[0]
    second = dc_replace(first, trade_id="t-second")
    view = DailyActionV2Run(run, (), (first, second), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    assert "释放 2 只 / " in line
    assert f"{2 * first.mark_weight:.0%} 敞口" in line


def test_release_schedule_line_prefers_earliest_of_two_dates(tmp_path):
    """双未来日期 → 只聚合最近到期日 cohort, 晚到期仓不入本次释放."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    first = run.open_positions[0]
    later = dc_replace(
        first, trade_id="t-later", projected_exit_date=sessions[25], mark_weight=0.2
    )
    view = DailyActionV2Run(run, (), (first, later), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    assert "最近到期 9/10" in line
    assert "释放 1 只 / " in line


def test_release_schedule_line_omitted_when_no_future_maturity(tmp_path):
    """全部持仓 projected_exit_date=None (旧构造/日历不足) → 聚合行整体省略,
    敞口行与主视图不受影响 (fail-open 家族钉住)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    stripped = dc_replace(run.open_positions[0], projected_exit_date=None)
    view = DailyActionV2Run(run, (), (stripped,), (), ())
    text = render_daily_action_v2(view)
    assert "释放日程" not in text
    assert "敞口：" in text


def test_release_schedule_line_over_cap_clause_includes_reserved_base(tmp_path):
    """after = 持仓 + 待成交 − 释放 (待成交不因释放消失) → 仍超上限子句;
    reserved 计入基数的钉住 (0.5+0.25−0.10=0.65 > 60%)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    service_run = dc_replace(
        run, open_exposure=0.5, reserved_exposure=0.25
    )
    position = dc_replace(run.open_positions[0], mark_weight=0.10)
    view = DailyActionV2Run(service_run, (), (position,), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    assert "约 65%" in line
    assert "（仍超 60% 上限，需继续等待）" in line


def test_release_schedule_line_omitted_for_datetime_trade_date(tmp_path):
    """service_run.trade_date=datetime (R157 F-a 同款形态) → 聚合行省略,
    主视图不阻断 (家族纪律: 披露面永不炸主视图)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    stale_service_run = dc_replace(run, trade_date=datetime(2026, 9, 6, 18, 0))
    view = DailyActionV2Run(stale_service_run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "释放日程" not in text
    assert "000909" in text


def test_release_schedule_line_omitted_when_weight_poisoned(tmp_path):
    """cohort 任一 mark_weight 非有限实数 (nan/bool/字符串) → 聚合行整体省略
    (诚实缺位优于错误聚合, R158 毒化守卫同族)."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    for poison in (float("nan"), True, "5%", None):
        poisoned = dc_replace(run.open_positions[0], mark_weight=poison)
        view = DailyActionV2Run(run, (), (poisoned,), (), ())
        text = render_daily_action_v2(view)
        assert "释放日程" not in text, f"poison={poison!r} 未被守卫"


# ---------- R163 Op2: 释放日程聚合行对抗审查钉住 (F-b 两项) ----------

def test_release_schedule_line_zero_weight_is_shown_not_omitted(tmp_path):
    """F-b falsy-zero 钉住 (R158 同族): mark_weight=0.0 → 「0% 敞口」必须显示,
    守卫按 None/类型判定不按真值 — 防 truthiness 重构静默漏显零权重 cohort."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    zero = dc_replace(run.open_positions[0], mark_weight=0.0)
    view = DailyActionV2Run(run, (), (zero,), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    assert "释放 1 只 / 0% 敞口" in line
    total = run.open_exposure + run.reserved_exposure
    assert f"约 {total:.0%}" in line


def test_release_schedule_line_excludes_maturity_equal_to_as_of(tmp_path):
    """F-b 边界日钉住: projected_exit_date == as_of (今日到期) 不入未来释放聚合
    — 今日退出属「完成退出/今日平仓」区, >= 重构会双重计数."""
    from dataclasses import replace as dc_replace

    run, _s, _t, _r = _run_with_open_position(tmp_path)
    today = dc_replace(
        run.open_positions[0], projected_exit_date=run.trade_date
    )
    view = DailyActionV2Run(run, (), (today,), (), ())
    text = render_daily_action_v2(view)
    assert "释放日程" not in text
    assert "敞口：" in text


def test_release_schedule_line_excludes_past_maturity(tmp_path):
    """F-b 过期日钉住: projected_exit_date < as_of (陈旧渲染面) 不入未来释放
    聚合, 与 R159 过期日只显日期的行级子句互不串扰."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    past = dc_replace(
        run.open_positions[0], projected_exit_date=sessions[18]
    )
    view = DailyActionV2Run(run, (), (past,), (), ())
    text = render_daily_action_v2(view)
    assert "释放日程" not in text


# ---------- R164 Op1: 释放日程多期扩展 (R163 登记不修①: 全日程表) ----------

def test_release_schedule_line_shows_all_future_cohorts(tmp_path):
    """双未来日期 → 首段保持『最近到期』逐字节同款语义, 第二段按升序追加
    后续 cohort 复合扣减 (after = 总敞口 − 累计释放), 不再只显最近一期."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    first = run.open_positions[0]
    later = dc_replace(
        first, trade_id="t-later", projected_exit_date=sessions[25], mark_weight=0.2
    )
    view = DailyActionV2Run(run, (), (first, later), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    total = run.open_exposure + run.reserved_exposure
    first_weight = first.mark_weight
    after1 = max(0.0, total - first_weight)
    after2 = max(0.0, total - first_weight - 0.2)
    assert (
        f"释放日程：最近到期 9/10（剩4天）释放 1 只 / {first_weight:.0%} 敞口"
        f" → 约 {after1:.0%}（降回上限内，可恢复出新仓）"
    ) in line
    later_day = f"{sessions[25].month}/{sessions[25].day}"
    assert f"；{later_day} 释放 1 只 / 20% 敞口 → 约 {after2:.0%}" in line
    assert line.count("降回上限内") == 1


def test_release_schedule_line_orders_descending_input_positions(tmp_path):
    """F-a 排序钉住: 乱序 (降序) 持仓输入 → 升序日程渲染, 首段保持『最近到期』
    语义 (剩N天口径/字样/注记落点三重绑定 index==0=最早到期日), 三段复合算术
    逐段钉住 — 摘掉 sorted() 或错置 index==0 的重构在此 RED."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    service_run = dc_replace(run, open_exposure=0.5, reserved_exposure=0.25)
    base = run.open_positions[0]
    early = dc_replace(
        base, trade_id="t-early", projected_exit_date=sessions[24], mark_weight=0.10
    )
    mid = dc_replace(
        base, trade_id="t-mid", projected_exit_date=sessions[25], mark_weight=0.30
    )
    late = dc_replace(
        base, trade_id="t-late", projected_exit_date=sessions[26], mark_weight=0.05
    )
    view = DailyActionV2Run(service_run, (), (late, mid, early), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    assert line == (
        "释放日程：最近到期 9/10（剩4天）释放 1 只 / 10% 敞口 → 约 65%；"
        "9/11 释放 1 只 / 30% 敞口 → 约 35%（降回上限内，可恢复出新仓）；"
        "9/12 释放 1 只 / 5% 敞口 → 约 30%"
    )
    assert line.count("最近到期") == 1
    assert line.count("降回上限内") == 1


def test_release_schedule_line_cap_note_follows_recovery_segment(tmp_path):
    """首段释放后仍超上限 → 注记不落首段, 落在首个降回上限的段 (恢复时点
    在多期日程上显形 — 操作员看到的是哪一期恢复出新仓)."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    service_run = dc_replace(run, open_exposure=0.5, reserved_exposure=0.25)
    first = dc_replace(run.open_positions[0], mark_weight=0.10)
    later = dc_replace(
        first, trade_id="t-later", projected_exit_date=sessions[25], mark_weight=0.30
    )
    view = DailyActionV2Run(service_run, (), (first, later), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    assert "→ 约 65%；" in line
    later_day = f"{sessions[25].month}/{sessions[25].day}"
    assert f"；{later_day} 释放 1 只 / 30% 敞口 → 约 35%（降回上限内，可恢复出新仓）" in line


def test_release_schedule_line_never_recovers_note_on_last_segment(tmp_path):
    """全程不恢复 → 『仍超上限，需继续等待』注记只落末段, 首段无注记
    (数字继续可见, 注记恰出现一次)."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    service_run = dc_replace(run, open_exposure=0.5, reserved_exposure=0.25)
    first = dc_replace(run.open_positions[0], mark_weight=0.05)
    later = dc_replace(
        first, trade_id="t-later", projected_exit_date=sessions[25], mark_weight=0.05
    )
    view = DailyActionV2Run(service_run, (), (first, later), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    later_day = f"{sessions[25].month}/{sessions[25].day}"
    assert f"释放 1 只 / 5% 敞口 → 约 70%；{later_day} 释放 1 只 / 5% 敞口 → 约 65%（仍超 60% 上限，需继续等待）" in line
    assert line.count("仍超 60% 上限") == 1


def test_release_schedule_line_poisoned_later_cohort_omits_line(tmp_path):
    """后续 cohort 任一 mark_weight 毒化 → 整行省略 (R162 最近 cohort 守卫
    纪律的自然扩员: 诚实缺位优于『干净 cohort 局部聚合』的残缺数字)."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    for poison in (float("nan"), True, "5%", None):
        first = run.open_positions[0]
        later = dc_replace(
            first,
            trade_id="t-later",
            projected_exit_date=sessions[25],
            mark_weight=poison,
        )
        view = DailyActionV2Run(run, (), (first, later), (), ())
        text = render_daily_action_v2(view)
        assert "释放日程" not in text, f"poison={poison!r} 未被守卫"


def test_release_schedule_line_later_cohort_aggregates_same_date(tmp_path):
    """后续到期日同日多仓 → 该段按 cohort 合计只数与释放敞口 (0831 形态
    在后续期位的同款语义)."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    first = run.open_positions[0]
    later_a = dc_replace(
        first, trade_id="t-later-a", projected_exit_date=sessions[25], mark_weight=0.2
    )
    later_b = dc_replace(
        first, trade_id="t-later-b", projected_exit_date=sessions[25], mark_weight=0.2
    )
    view = DailyActionV2Run(run, (), (first, later_a, later_b), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    later_day = f"{sessions[25].month}/{sessions[25].day}"
    assert f"；{later_day} 释放 2 只 / 40% 敞口" in line


def test_release_schedule_line_later_cohort_zero_weight_shown(tmp_path):
    """后续 cohort falsy-zero 钉住 (R163 同族): 0.0 → 『0% 敞口』必须显示,
    after 不受零释放影响."""
    from dataclasses import replace as dc_replace

    run, sessions, _t, _r = _run_with_open_position(tmp_path)
    first = run.open_positions[0]
    later = dc_replace(
        first, trade_id="t-later", projected_exit_date=sessions[25], mark_weight=0.0
    )
    view = DailyActionV2Run(run, (), (first, later), (), ())
    text = render_daily_action_v2(view)
    line = next(line for line in text.splitlines() if "释放日程" in line)
    total = run.open_exposure + run.reserved_exposure
    later_day = f"{sessions[25].month}/{sessions[25].day}"
    assert f"；{later_day} 释放 1 只 / 0% 敞口" in line
    assert f"→ 约 {total - first.mark_weight:.0%}" in line


# ---------- R176 Op1: d1 重入邻近度披露行 ----------

def _reentry_history():
    """3 日 crisis 连跑后首个 normal 信号日 (d1_run) 的注入史."""
    return {
        "20260817": "normal",
        "20260818": "crisis",
        "20260819": "crisis",
        "20260820": "crisis",
        "20260821": "normal",
    }


def test_reentry_line_d1_run_renders_registered_evidence():
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert "d1_run 形态" in line
    assert "前导连跑 3 日：crisis×3" in line
    assert "E=-5.74%" in line
    assert "E=+1.77%" in line
    assert "CI90 [+2.49%,+11.94%]" in line
    assert "截至 2026-09-10" in line
    assert "纯披露不判定" in line


def test_reentry_line_d1_blip_variant():
    history = dict(_reentry_history(), **{"20260819": "normal"})
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=history)
    assert line is not None
    assert "d1_blip 形态" in line
    assert "前导阻断 1 日" in line
    assert "E=+1.77%" in line
    assert "纯披露不判定" in line


def test_reentry_line_mixed_stretch_labels():
    history = {
        "20260818": "risk_off",
        "20260819": "crisis",
        "20260820": "crisis",
        "20260821": "normal",
    }
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=history)
    assert line is not None
    assert "crisis×2/risk_off" in line


def test_reentry_line_omitted_on_non_d1_forms():
    # d2 日
    history = dict(_reentry_history(), **{"20260821": "normal", "20260824": "normal"})
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 24)))
    assert _render_reentry_proximity_line(run, regimes_by_date=history) is None
    # 阻断日自身 (gate 行已覆盖)
    blocked_run = SimpleNamespace(
        service_run=SimpleNamespace(trade_date=date(2026, 8, 20))
    )
    assert (
        _render_reentry_proximity_line(blocked_run, regimes_by_date=_reentry_history())
        is None
    )
    # 窗口内无阻断日
    calm = {d: "normal" for d in _reentry_history()}
    calm_run = SimpleNamespace(
        service_run=SimpleNamespace(trade_date=date(2026, 8, 21))
    )
    assert _render_reentry_proximity_line(calm_run, regimes_by_date=calm) is None
    # 信号日不在会话序
    ghost_run = SimpleNamespace(
        service_run=SimpleNamespace(trade_date=date(2026, 9, 30))
    )
    assert (
        _render_reentry_proximity_line(ghost_run, regimes_by_date=_reentry_history())
        is None
    )


def test_reentry_line_fail_open_family():
    # 缺史
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    assert _render_reentry_proximity_line(run, regimes_by_date=None) is None
    assert _render_reentry_proximity_line(run, regimes_by_date={}) is None
    # trade_date 非 date 形态 (R157 Op2 同族输入契约)
    str_run = SimpleNamespace(service_run=SimpleNamespace(trade_date="20260821"))
    assert (
        _render_reentry_proximity_line(str_run, regimes_by_date=_reentry_history())
        is None
    )
    none_run = SimpleNamespace(service_run=SimpleNamespace(trade_date=None))
    assert (
        _render_reentry_proximity_line(none_run, regimes_by_date=_reentry_history())
        is None
    )
    # service_run 缺失
    assert _render_reentry_proximity_line(SimpleNamespace(), regimes_by_date=_reentry_history()) is None


def test_reentry_line_end_to_end_in_report(case, monkeypatch):
    """报告级集成: d1_run 日 render_daily_action_v2 输出含披露行."""
    from src.screening.offensive import daily_action as da

    # case fixture as_of = 2026-08-20: 3 日危机连跑后的首个 normal 信号日 (d1_run)
    history = {
        "20260817": "crisis",
        "20260818": "crisis",
        "20260819": "crisis",
        "20260820": "normal",
    }
    monkeypatch.setattr(da, "_load_regime_history", lambda: history)
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "重入邻近度：d1_run 形态" in text
    assert "纯披露不判定" in text


def test_reentry_line_run_two_boundary_is_d1_run():
    """P-d 钉住 (R177 Op2): run_len==2 是 d1_run (R168 定义 run≥2) — 恰是
    2026-09-09+09-10 连续 crisis 的真实形态; `>=2 → >=3` 变异曾无牙放行,
    会把该形态误判 d1_blip 渲染『为正』证据."""
    history = {
        "20260819": "crisis",
        "20260820": "crisis",
        "20260821": "normal",
    }
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=history)
    assert line is not None
    assert "d1_run 形态" in line
    assert "前导连跑 2 日：crisis×2" in line


def test_reentry_line_coerces_non_string_history_keys():
    """P-h 钉住 (R177 Op2): 非字符串键 (如 int YYYYMMDD) 经 str 强制照常渲染 —
    丢强制的变异曾无牙放行 (整行静默省略)."""
    history = {
        20260819: "crisis",
        20260820: "crisis",
        20260821: "normal",
    }
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=history)
    assert line is not None
    assert "d1_run 形态" in line


def test_reentry_line_suppressed_when_gate_regime_blocks():
    """P-j 钉住 (R177 Op2): gate 视角今日阻断 (crisis/risk_off) → 整行省略 —
    历史≠快照分歧下『⚠阻断新仓』+『重入邻近度』矛盾双行不可达 (门权威语义)."""
    history = {
        "20260817": "crisis",
        "20260818": "crisis",
        "20260819": "crisis",
        "20260820": "normal",
    }
    for blocked in ("crisis", "risk_off"):
        run = SimpleNamespace(
            regime=blocked, service_run=SimpleNamespace(trade_date=date(2026, 8, 20))
        )
        assert _render_reentry_proximity_line(run, regimes_by_date=history) is None
    # normal / None (legacy 构造) 不抑制 — 历史分类照常决定
    for regime in ("normal", None):
        run = SimpleNamespace(
            regime=regime, service_run=SimpleNamespace(trade_date=date(2026, 8, 20))
        )
        assert _render_reentry_proximity_line(run, regimes_by_date=history) is not None


# ---------- R181 Op1: 止损当期方向子句 (项 5 判定输入当期化, 纯披露) ----------

def _write_exit_anatomy_fixture(reports_dir, date_str="20260910"):
    """非对称 fixture: crisis 最佳档 -5%/Δ+0.90pp, normal 最佳档 -8%/Δ+0.27pp
    (R180 P-l/P-p 教训: 对称值掩盖桶互换与目标源互换)。"""
    payload = {
        "production": {
            "by_regime": {
                "crisis": {
                    "n_included": 132,
                    "base": {"mean_net": -0.05506869208225434, "n": 132},
                    "stop_grid": {
                        "-5%": {
                            "delta_vs_base": 0.009027072247123666,
                            "mean_net": -0.04604161983513067,
                            "n": 132,
                            "n_stopped": 114,
                            "n_gap_through": 49,
                        },
                        "-8%": {
                            "delta_vs_base": -0.004216352983654442,
                            "mean_net": -0.05928504506590878,
                            "n": 132,
                            "n_stopped": 96,
                            "n_gap_through": 24,
                        },
                    },
                },
                "normal": {
                    "n_included": 217,
                    "base": {"mean_net": 0.0005123, "n": 217},
                    "stop_grid": {
                        "-8%": {
                            "delta_vs_base": 0.0027,
                            "mean_net": 0.0031,
                            "n": 217,
                            "n_stopped": 12,
                            "n_gap_through": 3,
                        },
                    },
                },
            }
        }
    }
    path = Path(reports_dir) / f"exit_anatomy_{date_str}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _isolated_exit_anatomy_dir(tmp_path, monkeypatch):
    """止损当期方向读取面默认隔离 (R120b 家族): 渲染测试绝不读宿主真实报告,
    保证 slot (无 data/) 与宿主 (报告在场) 断言路径逐字节一致。"""
    import src.screening.offensive.daily_action as da

    target = tmp_path / "exit_anatomy_reports"
    target.mkdir()
    monkeypatch.setattr(da, "_EXIT_ANATOMY_REPORTS_DIR", target)
    return target


def test_stop_readiness_direction_clause_renders_nightly_reading(
    case, _isolated_exit_anatomy_dir
):
    """as_of 当日 regime 标签匹配夜刷报告 → 当期方向子句逐字节渲染。"""
    _write_exit_anatomy_fixture(_isolated_exit_anatomy_dir)
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view,
        regimes_by_date={"20260819": "crisis", "20260820": "crisis"},
    )
    assert line is not None
    assert (
        "当期方向（exit_anatomy 20260910 · 生产表/crisis/全候选，n=132）："
        "基准 -5.51% · 最佳止损档 -5%（Δ+0.90pp，档内 -4.60%，触发 114/132，"
        "跳空穿越 49）"
    ) in line
    assert "连续 crisis 2 日 · " in line


def test_stop_readiness_direction_clause_matches_as_of_label(
    case, _isolated_exit_anatomy_dir
):
    """as_of 标签为 normal → 读 normal 桶 (标签匹配, 非 crisis 桶硬编码)。"""
    _write_exit_anatomy_fixture(_isolated_exit_anatomy_dir)
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260820": "normal"}
    )
    assert line is not None
    assert "生产表/normal/全候选，n=217" in line
    assert "最佳止损档 -8%（Δ+0.27pp，档内 +0.31%，触发 12/217，跳空穿越 3）" in line
    assert "crisis/全候选" not in line


def test_stop_readiness_direction_clause_omitted_without_report(case):
    """夜刷报告缺席 (slot 形态) → 方向子句省略, 行由 streak 托住不消失。"""
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260820": "crisis"}
    )
    assert line is not None
    assert "当期方向（exit_anatomy" not in line
    assert "连续 crisis 1 日" in line
    assert "证据未就绪" in line


def test_stop_readiness_direction_clause_omitted_when_label_unknown(case):
    """as_of 标签 unknown (数据缺口) → 不冒充证据, 子句省略。"""
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260820": "unknown"}
    )
    assert line is not None
    assert "当期方向（exit_anatomy" not in line


def test_stop_readiness_direction_clause_requires_as_of_label(
    case, _isolated_exit_anatomy_dir
):
    """as_of 当日标签缺失 (regime 史滞后) → 方向子句省略 — 按构造不可达形态
    (标签存在 ⇒ streak 锚存在) 的反向面: 不用昨日的 regime 匹配今日读数。"""
    _write_exit_anatomy_fixture(_isolated_exit_anatomy_dir)
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260821": "crisis"}
    )
    assert line is not None
    assert "连续 crisis" not in line
    assert "当期方向（exit_anatomy" not in line
    assert "回撤" in line


def test_stop_readiness_direction_clause_corrupt_report_omitted(case):
    """最新报告损坏 → None 不回退旧报告 (读取家契约), 子句省略不炸。"""
    import src.screening.offensive.daily_action as da

    view, _as_of = _stop_view(case)
    (da._EXIT_ANATOMY_REPORTS_DIR / "exit_anatomy_20260910.json").write_text(
        "{broken", encoding="utf-8"
    )
    (da._EXIT_ANATOMY_REPORTS_DIR / "exit_anatomy_20260909.json").write_text(
        json.dumps({"production": {"by_regime": {"crisis": {}}}}), encoding="utf-8"
    )
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260820": "crisis"}
    )
    assert line is not None
    assert "当期方向（exit_anatomy" not in line


def test_stop_readiness_pointer_names_both_evidence_faces(case):
    """指针措辞双面化: backtest 工具=样本期方向, 夜刷读数=当期方向 (R181 失实修正)。"""
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view, regimes_by_date={"20260820": "crisis"}
    )
    assert line is not None
    assert "backtest_exit_strategies.py 回答样本期方向（journal 恢复样本，非当期）" in line
    assert "当期方向见夜刷 exit_anatomy 止损反事实" in line
    assert "DAILY_ACTION_EXECUTION_STOP" in line
    # 旧措辞 (把样本期工具当「确认当期方向」的入口) 防回归
    assert "先跑 backtest_exit_strategies.py 确认当期方向" not in line


def test_stop_readiness_direction_clause_in_full_render_after_regime_line(
    case, monkeypatch
):
    """整链接线: 方向子句在完整 --daily-action 渲染中随止损行出现, 行位于
    Regime 行之后。"""
    import src.screening.offensive.daily_action as da

    view, _as_of = _stop_view(case, regime="crisis")
    monkeypatch.setattr(
        da, "_load_regime_history",
        lambda: {"20260819": "crisis", "20260820": "crisis"},
    )
    _write_exit_anatomy_fixture(da._EXIT_ANATOMY_REPORTS_DIR)
    text = render_daily_action_v2(view)
    lines = text.splitlines()
    regime_idx = next(i for i, l in enumerate(lines) if l.startswith("Regime："))
    stop_idx = next(
        i for i, l in enumerate(lines) if l.startswith("止损启用条件（清单项 5）")
    )
    assert stop_idx > regime_idx
    assert "当期方向（exit_anatomy 20260910" in lines[stop_idx]


def test_stop_readiness_direction_clause_explicit_dir_param(case, tmp_path):
    """显式 exit_anatomy_reports_dir 注入缝活着 (R181 Op2 P-m 钉住):
    参数路径独立于模块常量隔离, 参数目录的报告照常消费。"""
    other = tmp_path / "other_reports"
    other.mkdir()
    _write_exit_anatomy_fixture(other)
    view, _as_of = _stop_view(case)
    line = _render_stop_loss_readiness_line(
        view,
        regimes_by_date={"20260820": "crisis"},
        exit_anatomy_reports_dir=other,
    )
    assert line is not None
    assert "当期方向（exit_anatomy 20260910" in line


# ---------- R182 Op1: 重入行当期读数子句 ----------


@pytest.fixture(autouse=True)
def _isolated_run_conditioning_dir(tmp_path, monkeypatch):
    """重入当期读数读取面默认隔离 (R120b 家族, R181 同款): 渲染测试绝不读
    宿主真实夜刷报告, 保证 slot (无 data/) 与宿主 (报告在场) 断言路径一致;
    既有 R176 静态行测试因此恒走回退路径。"""
    import src.screening.offensive.daily_action as da

    target = tmp_path / "run_conditioning_reports"
    target.mkdir()
    monkeypatch.setattr(da, "_RUN_CONDITIONING_REPORTS_DIR", target)
    return target


def _write_run_conditioning_fixture(reports_dir, date_str="20260910"):
    """非对称夜刷报告 fixture (数字取自真实 20260910 读数形态)。"""
    payload = {
        "tables": {
            "t10": {
                "d1_run": {
                    "n": 341,
                    "expectancy": -0.057425,
                    "winrate": 0.30792,
                    "cluster_ci_low_90": -0.084515,
                },
                "d1_blip": {
                    "n": 460,
                    "expectancy": 0.017710,
                    "winrate": 0.536957,
                    "cluster_ci_low_90": -0.007072,
                },
            }
        },
        "run_deltas_t10": {
            "d1_run_vs_blip": {
                "ci_low": 0.024943,
                "ci_high": 0.119363,
                "n_blip": 460,
                "n_run": 341,
            }
        },
        "split_half_d1": {"consistent": True},
    }
    path = Path(reports_dir) / f"regime_blocked_run_conditioning_{date_str}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_reentry_line_live_readings_render_d1_run(_isolated_run_conditioning_dir):
    """夜刷报告在场 → 行内当期读数 (报告日期自暴露) + 注册证据压缩为锚。"""
    _write_run_conditioning_fixture(_isolated_run_conditioning_dir)
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert "d1_run 形态（距上一阻断日 1 个会话；前导连跑 3 日：crisis×3）" in line
    assert (
        "当期读数（夜刷 regime_blocked_run_conditioning 20260910 · t10 净口径）："
        "d1_run E=-5.74%/胜率 30.8%（n=341）· d1_blip E=+1.77%/53.7%（n=460）· "
        "配对差 CI90 [+2.49%,+11.94%]（正值=run 罚分） · split-half 跨半一致"
    ) in line
    assert "注册证据 R168（轴边界预注册 2026-09-10）：同对比当时已决定性" in line
    assert "纯披露不判定（宪法 #2）" in line
    # 静态数字与旧指针不再出现 (当期读数取代其职责)
    assert "截至 2026-09-10" not in line
    assert "当期数字见夜刷" not in line


def test_reentry_line_live_readings_render_d1_blip(_isolated_run_conditioning_dir):
    history = dict(_reentry_history(), **{"20260819": "normal"})
    _write_run_conditioning_fixture(_isolated_run_conditioning_dir)
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=history)
    assert line is not None
    assert "d1_blip 形态（距上一阻断日 1 个会话；前导阻断 1 日）" in line
    assert "d1_run E=-5.74%" in line
    assert "注册证据 R168（轴边界预注册 2026-09-10）：d1_run 同对比中反为深负" in line


def test_reentry_line_static_fallback_when_no_report(_isolated_run_conditioning_dir):
    """报告缺席 → 注册证据静态行逐字节回退 (R176 原行为, 不以读数缺席抹掉
    已注册发现)。"""
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert "注册证据（R168，截至 2026-09-10）；当期数字见夜刷" in line
    assert "E=-5.74%，胜率 30.8%" in line
    assert "当期读数" not in line


def test_reentry_line_corrupt_report_falls_back_to_static(
    _isolated_run_conditioning_dir,
):
    (Path(_isolated_run_conditioning_dir) / "regime_blocked_run_conditioning_20260910.json").write_text(
        "{broken", encoding="utf-8"
    )
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert "注册证据（R168，截至 2026-09-10）" in line
    assert "当期读数" not in line


def test_reentry_line_malformed_payload_falls_back_to_static(
    _isolated_run_conditioning_dir,
):
    """报告在场但形状不符 (n=0) → 子句拒绝 → 静态回退 (不渲染部分垃圾)。"""
    import json as _json

    path = (
        Path(_isolated_run_conditioning_dir)
        / "regime_blocked_run_conditioning_20260910.json"
    )
    payload = {
        "tables": {"t10": {"d1_run": {"n": 0, "expectancy": 0.0, "winrate": 0.5},
                           "d1_blip": {"n": 10, "expectancy": 0.0, "winrate": 0.5}}},
        "run_deltas_t10": {"d1_run_vs_blip": {"ci_low": 0.0, "ci_high": 0.1,
                                              "n_blip": 10, "n_run": 0}},
    }
    path.write_text(_json.dumps(payload), encoding="utf-8")
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert "当期读数" not in line


def test_reentry_line_explicit_dir_param_seam_pinned(
    _isolated_run_conditioning_dir, tmp_path
):
    """显式 run_conditioning_reports_dir 注入缝活着 (R181 Op2 P-m 同族钉住):
    参数路径独立于模块常量隔离, 参数目录的报告照常消费。"""
    other = tmp_path / "other_reports"
    other.mkdir()
    _write_run_conditioning_fixture(other)
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(
        run, regimes_by_date=_reentry_history(), run_conditioning_reports_dir=other
    )
    assert line is not None
    assert "当期读数（夜刷 regime_blocked_run_conditioning 20260910" in line
    # 模块常量隔离目录仍空 → 默认路径仍回退
    default_line = _render_reentry_proximity_line(
        run, regimes_by_date=_reentry_history()
    )
    assert default_line is not None
    assert "当期读数" not in default_line


def test_reentry_line_live_readings_render_run_len_2(_isolated_run_conditioning_dir):
    """live 分支 run_len==2 形态钉住 (R182 Op2 P-x: R177 P-d 同族在 live 分支
    复活 — 2 日 crisis 连跑后首个 normal 信号日恰是 2026-09-09/10 真实形态,
    门变 >=3 会把它误渲染成 d1_blip 形态)。"""
    history = {
        "20260817": "normal",
        "20260819": "crisis",
        "20260820": "crisis",
        "20260821": "normal",
    }
    _write_run_conditioning_fixture(_isolated_run_conditioning_dir)
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=history)
    assert line is not None
    assert "d1_run 形态（距上一阻断日 1 个会话；前导连跑 2 日：crisis×2）" in line
    assert "当期读数（夜刷 regime_blocked_run_conditioning 20260910" in line
    assert "前导阻断 1 日" not in line


# ---------- R184 Op1: 重入决策锚时代外验当期读数子句 ----------


@pytest.fixture(autouse=True)
def _isolated_cross_era_dir(tmp_path, monkeypatch):
    """时代外验读取面默认隔离 (R120b 家族, R181/R182 同款): 渲染测试绝不读
    宿主真实夜刷报告; 既有测试因此恒走无子句路径 (行逐字节不变)。"""
    import src.screening.offensive.daily_action as da

    target = tmp_path / "cross_era_reports"
    target.mkdir()
    monkeypatch.setattr(da, "_CROSS_ERA_REPORTS_DIR", target)
    return target


def _write_cross_era_fixture(reports_dir, date_str="20260911"):
    """非对称 cross-era 报告 fixture (数字取自 R178 时代外验真实读数形态)。"""
    payload = {
        "schema_version": 1,
        "verdict": {
            "d1_penalty_sign_consistent": False,
            "early_ci_excludes_current_point": None,
            "statement": (
                "d1 罚分仅当前时代可检 (早期 CI 跨零) — R168 d1 边界为时代条件"
                "证据, 不可单独据以外推"
            ),
        },
        "d1_point_penalty": {"current": -0.0751, "early": 0.0072},
    }
    path = (
        Path(reports_dir) / f"regime_run_cross_era_validation_{date_str}.json"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_reentry_line_cross_era_clause_on_static_run_line(
    _isolated_cross_era_dir,
):
    """报告在场 (静态回退路径) → 行尾时代外验子句 (判定输入当期化第三腿)。"""
    _write_cross_era_fixture(_isolated_cross_era_dir)
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert (
        "时代外验（夜刷 regime_run_cross_era_validation 20260911 · "
        "当前点罚分 -7.51% · 早期点罚分 +0.72% · 两时代 方向不一致）" in line
    )
    assert "R168 d1 边界为时代条件" in line
    # 子句在句末纯披露限定语之前
    assert line.index("时代外验") < line.index("纯披露不判定")


def test_reentry_line_cross_era_clause_on_blip_line(_isolated_cross_era_dir):
    history = dict(_reentry_history(), **{"20260819": "normal"})
    _write_cross_era_fixture(_isolated_cross_era_dir)
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=history)
    assert line is not None
    assert "d1_blip 形态" in line
    assert "时代外验（夜刷 regime_run_cross_era_validation 20260911" in line


def test_reentry_line_cross_era_clause_with_live_readings(
    _isolated_run_conditioning_dir, _isolated_cross_era_dir
):
    """当期读数与时代外验双证据面并存 (同一决策点的两条独立腿)。"""
    _write_run_conditioning_fixture(_isolated_run_conditioning_dir)
    _write_cross_era_fixture(_isolated_cross_era_dir)
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert "当期读数（夜刷 regime_blocked_run_conditioning 20260910" in line
    assert "时代外验（夜刷 regime_run_cross_era_validation 20260911" in line


def test_reentry_line_cross_era_absent_line_unchanged(_isolated_cross_era_dir):
    """报告缺席 → 行逐字节不变 (fail-open 接线家族纪律; R183 Op2 交付面)。"""
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert "时代外验" not in line
    assert line.endswith("纯披露不判定（宪法 #2）")


def test_reentry_line_cross_era_corrupt_and_malformed_omitted(
    _isolated_cross_era_dir,
):
    """损坏 json / 形状不符 (sign_consistent 缺席) → 子句省略, 行其余不变。"""
    (Path(_isolated_cross_era_dir) / "regime_run_cross_era_validation_20260911.json").write_text(
        "{broken", encoding="utf-8"
    )
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert "时代外验" not in line

    import json as _json

    payload = {
        "schema_version": 1,
        "verdict": {
            "early_ci_excludes_current_point": None,
            "statement": "x",
        },
        "d1_point_penalty": {"current": -0.07, "early": 0.01},
    }
    (
        Path(_isolated_cross_era_dir)
        / "regime_run_cross_era_validation_20260911.json"
    ).write_text(_json.dumps(payload), encoding="utf-8")
    line = _render_reentry_proximity_line(run, regimes_by_date=_reentry_history())
    assert line is not None
    assert "时代外验" not in line


def test_reentry_line_cross_era_explicit_dir_param_seam_pinned(
    _isolated_cross_era_dir, tmp_path
):
    """显式 cross_era_reports_dir 注入缝活着 (R181 Op2 P-m 同族钉住)。"""
    other = tmp_path / "other_cross_era"
    other.mkdir()
    _write_cross_era_fixture(other)
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(
        run, regimes_by_date=_reentry_history(), cross_era_reports_dir=other
    )
    assert line is not None
    assert "时代外验（夜刷 regime_run_cross_era_validation 20260911" in line
    default_line = _render_reentry_proximity_line(
        run, regimes_by_date=_reentry_history()
    )
    assert default_line is not None
    assert "时代外验" not in default_line


def test_reentry_line_cross_era_clause_on_live_blip_line(
    _isolated_run_conditioning_dir, _isolated_cross_era_dir
):
    """live blip 分支双证据面 (四分支穷尽: live×2 由本测+with_live_readings
    覆盖, 静态×2 由 static_run/blip 两测覆盖 — 漏一分支的变异无牙放行)。"""
    history = dict(_reentry_history(), **{"20260819": "normal"})
    _write_run_conditioning_fixture(_isolated_run_conditioning_dir)
    _write_cross_era_fixture(_isolated_cross_era_dir)
    run = SimpleNamespace(service_run=SimpleNamespace(trade_date=date(2026, 8, 21)))
    line = _render_reentry_proximity_line(run, regimes_by_date=history)
    assert line is not None
    assert "d1_blip 形态" in line
    assert "当期读数（夜刷 regime_blocked_run_conditioning 20260910" in line
    assert "时代外验（夜刷 regime_run_cross_era_validation 20260911" in line
    assert line.index("当期读数") < line.index("时代外验") < line.index("纯披露不判定")
