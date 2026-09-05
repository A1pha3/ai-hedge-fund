"""src 触发器账本只读取面测试 (R85 Op1)。

单一实现自 scripts/winrate_payoff_decomposition.py 迁入 (脚本 re-export);
本文件钉死读取面语义与迁移前逐值一致: 排序/损坏行跳过/缺失容忍/连亮计数
保守断链。全部 tmp 账本, 不触真实 data/reports。
"""

from __future__ import annotations

import json

from src.screening.offensive import threshold_trigger as tt


def _rec(day: str, c1_lit=True, c2_lit=False, c1_judged=True, c2_judged=True,
         armed=False, court=None):
    rec = {
        "date": day,
        "anchor": "production_aligned/t10",
        "min_n": 30,
        "condition_1": {"lit": c1_lit, "judged": c1_judged, "n": 315, "stat": 0.0023},
        "condition_2": {"lit": c2_lit, "judged": c2_judged, "n": 303, "stat": 0.0097},
        "conjunction_armed": armed,
    }
    if court is not None:
        rec["court"] = court
    return rec


def _write(tmp_path, records):
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_missing_file_returns_empty(tmp_path):
    assert tt.load_trigger_ledger(tmp_path / "none.jsonl") == []


def test_load_sorts_by_date_and_skips_corrupt(tmp_path):
    path = _write(tmp_path, [_rec("20260831"), _rec("20260829")])
    # 追加一行垃圾与一行空行 — advisory 跳过
    with path.open("a", encoding="utf-8") as fh:
        fh.write("not-json\n\n")
    records = tt.load_trigger_ledger(path)
    assert [r["date"] for r in records] == ["20260829", "20260831"]


def test_load_tolerates_both_record_forms(tmp_path):
    """R81 旧形态 (无 court) 与 R84 新形态 (带 court) 同账本共存。"""
    path = _write(tmp_path, [
        _rec("20260830"),
        _rec("20260831", court={"built_at": "2026-08-30", "window_end": "20260830",
                                "rows": 1866, "formula_fingerprint": "aa" * 32}),
    ])
    records = tt.load_trigger_ledger(path)
    assert "court" not in records[0]
    assert records[1]["court"]["window_end"] == "20260830"


def test_stability_empty_ledger_zeroes():
    st = tt.trigger_stability([])
    assert st["records"] == 0
    assert st["condition_1_streak"] == 0
    assert st["conjunction_streak"] == 0
    assert st["first_date"] is None and st["last_date"] is None


def test_stability_streaks_and_conservative_break():
    records = [
        _rec("20260829", c1_lit=False),
        _rec("20260830"),
        _rec("20260831"),
    ]
    st = tt.trigger_stability(records)
    assert st["records"] == 3
    assert st["condition_1_streak"] == 2  # 0829 未亮断链
    assert st["condition_2_streak"] == 0
    assert st["conjunction_streak"] == 0
    assert st["condition_1_last_lit"] is True
    assert st["max_conjunction_streak"] == 0


def test_stability_unjudged_breaks_streak():
    records = [
        _rec("20260829"),
        _rec("20260830", c1_judged=False, c1_lit=False),
        _rec("20260831"),
    ]
    assert tt.trigger_stability(records)["condition_1_streak"] == 1


def test_stability_armed_run_accumulates():
    """武装连亮计数 — 冻结语义 (R81 逐值迁移): 断链后 run_and 永久关闭,
    max_conjunction_streak 只反映最新锚定段 (恒等于当前连亮, 永不超过)。
    字段名『历史最多』与该语义的偏差登记为 R85 Op2 对抗审查候选。"""
    records = [
        _rec("20260829", c1_lit=True, c2_lit=True, armed=True),
        _rec("20260830", c1_lit=True, c2_lit=True, armed=True),
        _rec("20260831", c1_lit=True, c2_lit=False, armed=False),
    ]
    st = tt.trigger_stability(records)
    assert st["conjunction_streak"] == 0  # 最新未武装 → 断链 (最新锚定语义不变)
    assert st["max_conjunction_streak"] == 2  # 全历史最大武装段如实 (R85 Op2 修复)
    # 正向: 最新连续武装时两字段同步增长
    st2 = tt.trigger_stability(records[:2])
    assert st2["conjunction_streak"] == 2
    assert st2["max_conjunction_streak"] == 2


def test_max_conjunction_true_historical_scan():
    """全历史最大: 多段武装段取最长; 前段断链不吞历史 (R85 Op2 RED 实锚).

    旧实现 max_and 只在 run_and 存活分支内更新 — [A,A,U] 的历史最大 2 被
    吞成 0, MD 披露『历史最多合取连亮』失真。
    """
    records = [
        _rec("20260828", c1_lit=True, c2_lit=True, armed=True),
        _rec("20260829", c1_lit=True, c2_lit=True, armed=True),
        _rec("20260830", c1_lit=True, c2_lit=False, armed=False),
        _rec("20260831", c1_lit=True, c2_lit=True, armed=True),
    ]
    st = tt.trigger_stability(records)
    assert st["conjunction_streak"] == 1  # 最新锚定: 只有 0831 连续武装
    assert st["max_conjunction_streak"] == 2  # 历史最长段 = 0828-0829
    assert tt.trigger_stability([_rec("20260901", armed=False)] * 3)[
        "max_conjunction_streak"
    ] == 0


# --- R100 Op1: 0.60 锚 (条件③/060 合取) 稳定计数 ------------------------------


def _rec060(day, c3_lit=True, armed060=False, with_c3=True, **kw):
    rec = _rec(day, **kw)
    if with_c3:
        rec["condition_3"] = {"lit": c3_lit, "judged": True, "n": 340, "stat": 0.0007}
        rec["conjunction_060_armed"] = armed060
    return rec


def test_stability_060_empty_ledger_zeroes():
    st = tt.trigger_stability([])
    assert st["condition_3_streak"] == 0
    assert st["conjunction_060_streak"] == 0
    assert st["max_conjunction_060_streak"] == 0


def test_stability_060_streak_and_break():
    records = [
        _rec060("20260829", c3_lit=True, armed060=True),
        _rec060("20260830", c3_lit=True, armed060=True),
        _rec060("20260831", c3_lit=False, armed060=False),
    ]
    st = tt.trigger_stability(records)
    assert st["condition_3_streak"] == 0  # 最新未亮 → 断链
    assert st["conjunction_060_streak"] == 0
    assert st["max_conjunction_060_streak"] == 2  # 历史段如实
    st2 = tt.trigger_stability(records[:2])
    assert st2["condition_3_streak"] == 2
    assert st2["conjunction_060_streak"] == 2
    assert st2["condition_3_last_lit"] is True
    assert st2["conjunction_060_last_armed"] is True


def test_stability_060_old_records_break_conservatively():
    """R100 前旧记录无 060 键 → 未点亮断链 (未知不延长连亮)."""
    records = [
        _rec("20260829"),  # 旧形态: 无 condition_3 / conjunction_060_armed
        _rec060("20260830", c3_lit=True, armed060=True),
        _rec060("20260831", c3_lit=True, armed060=True),
    ]
    st = tt.trigger_stability(records)
    assert st["condition_3_streak"] == 2  # 旧记录在最新锚定段之前, 不影响向前计数
    assert st["conjunction_060_streak"] == 2
    # 但旧记录夹在中间会断链:
    records2 = [
        _rec060("20260829", c3_lit=True, armed060=True),
        _rec("20260830"),  # 旧形态夹中间
        _rec060("20260831", c3_lit=True, armed060=True),
    ]
    st2 = tt.trigger_stability(records2)
    assert st2["condition_3_streak"] == 1
    assert st2["conjunction_060_streak"] == 1
    assert st2["max_conjunction_060_streak"] == 1  # 两段各 1, 取最大


def test_stability_060_last_lit_from_old_record_is_none():
    records = [_rec("20260829")]
    st = tt.trigger_stability(records)
    assert st["condition_3_last_lit"] is None
    assert st["conjunction_060_last_armed"] is None


# ---------- R112 Op1: 稳定阈值 K 预注册消费面 (反前瞻资格判定) ----------

_K_OK = {
    "anchor": "production_aligned/t10",
    "k_070": 3,
    "k_060": 3,
    "registered_date": "20260901",
    "owner_ref": "owner:mini 预注册",
}


def _kfile(tmp_path, payload):
    path = tmp_path / "threshold_trigger_k.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _armed_rec(day, armed=True, armed_060=None, anchor="production_aligned/t10"):
    rec = _rec(day, c1_lit=True, c2_lit=True, armed=armed, court={"window_end": day})
    if armed_060 is not None:
        rec["condition_3"] = {"lit": True, "judged": True, "n": 400, "stat": 0.002}
        rec["conjunction_060_armed"] = armed_060
    if anchor is not None:
        rec["anchor"] = anchor
    return rec


def test_load_k_registration_unregistered(tmp_path):
    """K 文件缺失 → unregistered (现默认态, 行为不变)."""
    state, reg = tt.load_k_registration(tmp_path / "none.json")
    assert state == "unregistered" and reg is None


def test_load_k_registration_registered_ok(tmp_path):
    state, reg = tt.load_k_registration(_kfile(tmp_path, _K_OK))
    assert state == "registered"
    assert reg["k_070"] == 3 and reg["k_060"] == 3
    assert reg["registered_date"] == "20260901"
    assert reg["anchor"] == "production_aligned/t10"


def test_load_k_registration_registered_without_k060(tmp_path):
    """k_060 可选 — 只预注册 0.70 锚是合法形态."""
    payload = {k: v for k, v in _K_OK.items() if k != "k_060"}
    state, reg = tt.load_k_registration(_kfile(tmp_path, payload))
    assert state == "registered" and reg["k_060"] is None


def test_load_k_registration_malformed_variants(tmp_path):
    """JSON 损坏/形状不符 → malformed (文件存在却不合法是 owner 可见异常态)."""
    bad_payloads = [
        "\x00 not json",
        [],
        {k: v for k, v in _K_OK.items() if k != "anchor"},      # anchor 缺失
        {k: v for k, v in _K_OK.items() if k != "k_070"},       # k_070 缺失
        {**_K_OK, "k_070": 0},                                   # k 必须 >=1
        {**_K_OK, "k_070": "3"},                                 # 非整数
        {**_K_OK, "k_070": True},                                # bool 不是合法 K
        {**_K_OK, "k_070": 2.5},                                 # 非整数
        {**_K_OK, "registered_date": "2026-9-1"},                # 非 YYYYMMDD
        {**_K_OK, "registered_date": 20260901},                  # 非 str
        {**_K_OK, "k_060": "3"},                                 # 可选键存在则同型
        {**_K_OK, "owner_ref": 7},                               # owner_ref 非 str
    ]
    for payload in bad_payloads:
        state, reg = tt.load_k_registration(_kfile(tmp_path, payload))
        assert state == "malformed" and reg is None, f"payload={payload!r}"


def test_qualification_counts_only_from_registration_date():
    """反前瞻核心: 注册日前的连亮不追溯 — 只数 date >= registered_date."""
    records = [
        _armed_rec("20260830"), _armed_rec("20260831"),
        _armed_rec("20260901"), _armed_rec("20260902"),
    ]
    reg = dict(_K_OK)  # registered_date=20260901, k_070=3
    qual = tt.trigger_qualification(records, reg)
    assert qual["q_070"] == 2              # 0901+0902 两条
    assert qual["qualified_070"] is False  # 2 < 3
    # 同一账本, 若注册更早 (0901 前全在窗内) — 4 连亮达标
    early = {**_K_OK, "registered_date": "20260830"}
    qual_early = tt.trigger_qualification(records, early)
    assert qual_early["q_070"] == 4
    assert qual_early["qualified_070"] is True


def test_qualification_breaks_on_unarmed_within_suffix():
    records = [
        _armed_rec("20260901"), _armed_rec("20260902", armed=False),
        _armed_rec("20260903"), _armed_rec("20260904"),
    ]
    qual = tt.trigger_qualification(records, dict(_K_OK))
    assert qual["q_070"] == 2  # 尾部连亮: 0903+0904
    assert qual["qualified_070"] is False


def test_qualification_060_anchor_independent():
    """0.60 锚独立用 k_060, 互不替代 — 070 未达标不影响 060 判定."""
    records = [
        _armed_rec("20260901", armed=False, armed_060=True),
        _armed_rec("20260902", armed=False, armed_060=True),
        _armed_rec("20260903", armed=False, armed_060=True),
    ]
    qual = tt.trigger_qualification(records, dict(_K_OK))
    assert qual["q_070"] == 0 and qual["qualified_070"] is False
    assert qual["q_060"] == 3 and qual["qualified_060"] is True


def test_qualification_k060_missing_not_judged():
    """k_060 未预注册 → 0.60 锚不判定 (None), 绝不借 0.70 的 K."""
    reg = {k: v for k, v in _K_OK.items() if k != "k_060"}
    records = [_armed_rec("20260901", armed_060=True)]
    qual = tt.trigger_qualification(records, reg)
    assert qual["q_060"] is None and qual["qualified_060"] is None


def test_qualification_anchor_mismatch_excluded():
    """K 绑定 anchor — 异 anchor 记录不参与资格连亮 (数据驱动, 不硬编码)."""
    records = [_armed_rec("20260901", anchor="all_candidates/t10") for _ in range(5)]
    qual = tt.trigger_qualification(records, dict(_K_OK))
    assert qual["q_070"] == 0 and qual["qualified_070"] is False


def test_k_disclosure_unregistered_default_text():
    state = tt.k_qualification_disclosure([], ("unregistered", None))
    assert state["state"] == "unregistered"
    assert "K 未预注册" in state["line_070"]
    assert state["line_060"] is None
    assert state["qualified_070"] is False


def test_k_disclosure_loads_default_path(tmp_path, monkeypatch):
    """registration 省略 → 从 K_REGISTRATION_PATH 读取 (渲染面同一路径)."""
    monkeypatch.setattr(tt, "K_REGISTRATION_PATH", _kfile(tmp_path, _K_OK))
    records = [_armed_rec("20260901"), _armed_rec("20260902"), _armed_rec("20260903")]
    disc = tt.k_qualification_disclosure(records)
    assert disc["state"] == "registered"
    assert disc["qualified_070"] is True
    assert "预注册 K=3" in disc["line_070"]
    assert "正式评估资格达成" in disc["line_070"]


def test_k_disclosure_malformed_disclosed():
    disc = tt.k_qualification_disclosure([], ("malformed", None))
    assert disc["state"] == "malformed"
    assert "损坏" in disc["line_070"]
    assert disc["qualified_070"] is False


def test_k_disclosure_registered_not_yet_qualified_progress_visible():
    reg = dict(_K_OK)  # k_070=3
    records = [_armed_rec("20260901"), _armed_rec("20260902")]
    disc = tt.k_qualification_disclosure(records, ("registered", reg))
    assert disc["qualified_070"] is False
    assert "资格连亮 2/3" in disc["line_070"]
    assert "正式评估资格达成" not in disc["line_070"]
    assert disc["line_060"] is not None and "3" in disc["line_060"]


def test_k_disclosure_json_serializable():
    """payload["threshold_k"] 进 JSON 报告 — 结构必须可序列化."""
    reg = dict(_K_OK)
    records = [_armed_rec("20260901", armed_060=True)]
    disc = tt.k_qualification_disclosure(records, ("registered", reg))
    json.dumps(disc, ensure_ascii=False)


# ---------- R113 Op2: K 预注册对抗加固 (回溯注册防御/形状设防) ----------

def test_observe_k_registration_appends_and_idempotent(tmp_path):
    """观测日志 append-only: 首次写入, 同内容同日重放不重复追加."""
    log = tmp_path / "k_obs.jsonl"
    reg = dict(_K_OK)
    first = tt.observe_k_registration(reg, "20260905", path=log)
    assert first["observed_date"] == "20260905"
    assert first["declared_registered_date"] == "20260901"
    second = tt.observe_k_registration(reg, "20260905", path=log)
    assert second["k_hash"] == first["k_hash"]
    records = tt.load_k_observations(log)
    assert len(records) == 1
    # 同内容次日观测 → 新记录 (连续性), k_hash 相同
    tt.observe_k_registration(reg, "20260908", path=log)
    records = tt.load_k_observations(log)
    assert len(records) == 2
    assert records[0]["k_hash"] == records[1]["k_hash"]


def test_observe_k_registration_different_content_new_hash(tmp_path):
    log = tmp_path / "k_obs.jsonl"
    tt.observe_k_registration(dict(_K_OK), "20260905", path=log)
    changed = {**_K_OK, "k_070": 4}
    tt.observe_k_registration(changed, "20260906", path=log)
    records = tt.load_k_observations(log)
    assert len(records) == 2
    assert records[0]["k_hash"] != records[1]["k_hash"]


def test_load_k_observations_missing_and_corrupt(tmp_path):
    log = tmp_path / "k_obs.jsonl"
    assert tt.load_k_observations(log) == []
    log.write_text('{"observed_date": "20260905", "k_hash": "a"}\nnot-json\n',
                   encoding="utf-8")
    records = tt.load_k_observations(log)
    assert len(records) == 1


def test_effective_registration_no_log_declared_stands():
    reg = dict(_K_OK)
    effective, backdated = tt.effective_k_registration(reg, [])
    assert effective == "20260901" and backdated is False


def test_effective_registration_backdated_corrected():
    """P1 回溯注册 PoC: 声明日期早于首次观测 → 以观测日起算 (旧亮不追溯)."""
    reg = {**_K_OK, "registered_date": "20260825"}  # 事后回溯声明
    log = [
        {"observed_date": "20260905", "k_hash": tt.k_registration_hash(reg),
         "declared_registered_date": "20260825"},
    ]
    effective, backdated = tt.effective_k_registration(reg, log)
    assert effective == "20260905" and backdated is True


def test_effective_registration_other_content_ignored():
    """日志里其他内容哈希的观测不约束本注册 (各自独立)."""
    reg = dict(_K_OK)
    log = [
        {"observed_date": "20260905", "k_hash": "sha256:other-content",
         "declared_registered_date": "20260825"},
    ]
    effective, backdated = tt.effective_k_registration(reg, log)
    assert effective == "20260901" and backdated is False


def test_disclosure_backdated_recomputes_window_and_discloses():
    """回溯形态: 资格连亮按观测日重算 + 披露行明语标注修正."""
    reg = {**_K_OK, "registered_date": "20260825"}  # 回溯声明到亮之前
    records = [
        _armed_rec("20260825"), _armed_rec("20260826"),
        _armed_rec("20260905"), _armed_rec("20260906"),
    ]
    log = [
        {"observed_date": "20260905", "k_hash": tt.k_registration_hash(reg),
         "declared_registered_date": "20260825"},
    ]
    disc = tt.k_qualification_disclosure(
        records, ("registered", reg), observation_log=log
    )
    assert disc["backdated"] is True
    assert disc["effective_registered_date"] == "20260905"
    assert "以观测日起算" in disc["line_070"]
    assert "资格连亮 2/3" in disc["line_070"]  # 只数观测日后的 2 条


def test_disclosure_not_backdated_line_unchanged():
    """诚实注册 (观测日不晚于声明日) → 行文与 Op1 逐字同形."""
    reg = dict(_K_OK)
    records = [_armed_rec("20260901"), _armed_rec("20260902"), _armed_rec("20260903")]
    log = [
        {"observed_date": "20260901", "k_hash": tt.k_registration_hash(reg),
         "declared_registered_date": "20260901"},
    ]
    disc = tt.k_qualification_disclosure(records, ("registered", reg), observation_log=log)
    assert disc["backdated"] is False
    assert "以观测日起算" not in disc["line_070"]
    assert "资格连亮 3/3" in disc["line_070"]


def test_disclosure_loads_observation_log_default_path(tmp_path, monkeypatch):
    monkeypatch.setattr(tt, "K_REGISTRATION_PATH", _kfile(tmp_path, _K_OK))
    log = tmp_path / "k_obs.jsonl"
    log.write_text(json.dumps({
        "observed_date": "20260905",
        "k_hash": tt.k_registration_hash(dict(_K_OK)),
        "declared_registered_date": "20260901",
    }), encoding="utf-8")
    monkeypatch.setattr(tt, "K_OBSERVATION_LOG_PATH", log)
    records = [_armed_rec("20260905")]
    disc = tt.k_qualification_disclosure(records)
    assert disc["backdated"] is True
    assert disc["effective_registered_date"] == "20260905"


def test_qualification_rejects_malformed_registration():
    """P2: 导出纯函数对 registration 形状复验 — 非法一律 ValueError 不静默."""
    bad = [
        None,
        {},
        {**_K_OK, "k_070": 2.5},        # float — int() 截断可使 2/2.5 判达标
        {**_K_OK, "k_070": True},        # bool
        {k: v for k, v in _K_OK.items() if k != "anchor"},
        {**_K_OK, "registered_date": "2026-9-1"},
    ]
    records = [_armed_rec("20260901")]
    for reg in bad:
        try:
            tt.trigger_qualification(records, reg)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {reg!r}")


def test_qualification_excludes_malformed_date_records():
    """P3: 窗口内只认 YYYYMMDD 记录 — 畸形日期不参与资格 (保守断链)."""
    reg = dict(_K_OK)
    records = [
        _armed_rec("2026-9-1"),   # 畸形: 字典序 >= 声明日但形状非法
        _armed_rec("20260901"),
    ]
    qual = tt.trigger_qualification(records, reg)
    assert qual["q_070"] == 1


# ---------- R114 Op3: strength_bucket 单一实现上移 ----------

def test_strength_bucket_edges_left_closed():
    """0.50/0.60/0.70 左闭右开 — 与 court 分组口径逐位一致 (上移钉死)."""
    assert tt.strength_bucket(0.499) == "<0.50"
    assert tt.strength_bucket(0.50) == "0.50-0.60"
    assert tt.strength_bucket(0.599) == "0.50-0.60"
    assert tt.strength_bucket(0.60) == "0.60-0.70"
    assert tt.strength_bucket(0.699) == "0.60-0.70"
    assert tt.strength_bucket(0.70) == "≥0.70"
    assert tt.strength_bucket(0.95) == "≥0.70"
    assert tt.strength_bucket(None) == "unknown"
    assert tt.strength_bucket(float("nan")) == "unknown"


def test_strength_buckets_constant_shape():
    assert tt.ALL_STRENGTH_BUCKETS == ("<0.50", "0.50-0.60", "0.60-0.70", "≥0.70", "unknown")


def test_script_reexports_same_strength_bucket_objects():
    """脚本 re-export 是同一对象 — 上移后无双实现漂移面 (R109 Op2 纪律)."""
    import scripts.winrate_payoff_decomposition as deco

    assert deco.strength_bucket is tt.strength_bucket
    assert deco.ALL_STRENGTH_BUCKETS is tt.ALL_STRENGTH_BUCKETS


# ---------- R115 Op1: 对抗审查加固 (观测形状守卫/顺序无关) ----------

def test_load_k_observations_skips_malformed_observed_date(tmp_path):
    """F3: observed_date 非 8 位数字 (9 位/带横线/非 str/缺失) 的行 advisory 跳过 —
    证据面损坏不得流入资格面 (修复前 9 位行曾使 k_qualification_disclosure
    ValueError 裸逃逸, 炸掉 --daily-action 渲染与夜刷 build 双面)."""
    good = {"observed_date": "20260905", "k_hash": "sha256:" + "a" * 64}
    rows = [
        good,
        {"observed_date": "202609051", "k_hash": "sha256:" + "b" * 64},
        {"observed_date": "2026-9-5", "k_hash": "sha256:" + "c" * 64},
        {"observed_date": 20260905, "k_hash": "sha256:" + "d" * 64},
        {"k_hash": "sha256:" + "e" * 64},
    ]
    log = tmp_path / "obs.jsonl"
    log.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    assert tt.load_k_observations(log) == [good]


def test_effective_registration_ignores_malformed_observed_dates():
    """F3: 直接注入的畸形 observed_date 记录不构成观测证据 — 回落声明日起算."""
    reg = dict(_K_OK)
    polluted = [{"observed_date": "202609011", "k_hash": tt.k_registration_hash(reg)}]
    assert tt.effective_k_registration(reg, polluted) == ("20260901", False)


def test_effective_registration_order_independent():
    """F2: 『首次观测日』= 最早匹配 — 同观测集任意顺序注入逐字等价
    (修复前 next() 取首条, 乱序注入返回不同起算日, PoC 实锤)."""
    reg = {**_K_OK, "registered_date": "20260825"}
    h = tt.k_registration_hash(reg)
    early = {"observed_date": "20260903", "k_hash": h}
    late = {"observed_date": "20260905", "k_hash": h}
    assert tt.effective_k_registration(reg, [late, early]) == ("20260903", True)
    assert tt.effective_k_registration(reg, [early, late]) == ("20260903", True)


def test_k_disclosure_survives_polluted_observation_log(tmp_path, monkeypatch):
    """F3 全链: 污染观测日志 (畸形日期+匹配 k_hash) 下披露不抛异常, 回落声明日."""
    reg_file = _kfile(tmp_path, _K_OK)
    monkeypatch.setattr(tt, "K_REGISTRATION_PATH", reg_file)
    reg = tt.load_k_registration(reg_file)[1]
    log = tmp_path / "obs.jsonl"
    log.write_text(
        json.dumps(
            {"observed_date": "202609011", "k_hash": tt.k_registration_hash(reg)},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tt, "K_OBSERVATION_LOG_PATH", log)
    records = [_armed_rec("20260903", armed=True)]
    disc = tt.k_qualification_disclosure(records)
    assert disc["state"] == "registered"
    assert "自 20260901 起计" in disc["line_070"]


# ---------- R127 Op2: 强度族行内条件值形状毒化守卫 ----------

def test_stability_poisoned_condition_shapes_break_conservatively():
    """R127 Op2 (R126 Op2 强度族镜像, AGENTS.md R126 开放项②): 行内条件值
    truthy 非 dict (非空 str/非空 list/非零 int/True) — 修复前
    `latest.get("condition_1") or {}` 对 truthy 非 dict 不兜底, `.get("lit")`
    裸 AttributeError 炸消费面 (daily_action 触发器状态行 = 日度命令)。
    修复后与缺键同语义: 断链 + last_lit None (advisory 不假装), 不抛异常。"""
    latest = _rec("20260831")
    prev = _rec("20260830")
    for poisoned in ("lit", ["lit"], 7, True):
        latest["condition_1"] = poisoned
        st = tt.trigger_stability([prev, latest])
        assert st["condition_1_streak"] == 0
        assert st["condition_1_last_lit"] is None
        # 非毒化字段判定照常 (latest c2 默认 lit=False)
        assert st["condition_2_last_lit"] is False
        assert st["condition_2_streak"] == 0


def test_stability_poisoned_condition_in_history_breaks_without_crash():
    """毒化行在全历史循环内同样按缺键断链 — 不炸、其余字段连亮不受牵连。"""
    latest = _rec("20260831", c1_lit=True, c2_lit=True, armed=True)
    poisoned_mid = _rec("20260830", c1_lit=True, c2_lit=True, armed=True)
    poisoned_mid["condition_2"] = [{"lit": True}]
    st = tt.trigger_stability([_rec("20260829"), poisoned_mid, latest])
    assert st["condition_2_streak"] == 1  # 0829 未亮 + 0830 毒化断链, 只有 0831 计入
    assert st["condition_1_streak"] == 3  # 未毒化字段三行皆亮, 不受牵连 (_rec 默认 c1 亮)
    assert st["conjunction_streak"] == 2  # armed 与条件毒化独立 (0830+0831 皆武装)
    assert st["max_conjunction_streak"] == 2  # 0830+0831 连续武装如实


# ---------------------------------------------------------------------------
# R130 Op1: 前进门数据状态身份 + 相邻重复观测折叠
# ---------------------------------------------------------------------------

def _dg(tag: str) -> str:
    return "sha256:" + tag * 32


def _court(digest: str | None, win_end: str = "20260904") -> dict | None:
    if digest is None and win_end is None:
        return None
    return {
        "window_start": "20250701", "window_end": win_end,
        "rows": 1950, "formula_fingerprint": "aa" * 32,
        "content_digest": digest, "universe_audit_complete": True,
    }


def test_court_data_state_equal_requires_both_digests():
    """数据状态身份: 双方 content_digest 均为非空 str 且相等才同状态。"""
    assert tt.court_data_state_equal(_court(_dg("a1")), _court(_dg("a1"))) is True
    assert tt.court_data_state_equal(_court(_dg("a1")), _court(_dg("b2"))) is False
    # 任一侧缺失/畸形 → 不等 (保守方向: 宁多记不漏记)
    assert tt.court_data_state_equal(_court(None), _court(_dg("a1"))) is False
    assert tt.court_data_state_equal(_court(_dg("a1")), None) is False
    assert tt.court_data_state_equal(None, None) is False
    assert tt.court_data_state_equal("poison", _court(_dg("a1"))) is False
    assert tt.court_data_state_equal({"content_digest": 7}, _court(_dg("a1"))) is False


def test_stability_folds_adjacent_duplicate_observations():
    """相邻同数据状态重复观测不膨胀连亮 (2026-09-05 重复判定形态)。"""
    records = [
        _rec("20260902", c1_lit=True, court=_court(_dg("c3"))),
        _rec("20260903", c1_lit=True, court=_court(_dg("c4"))),
        _rec("20260904", c1_lit=True, court=_court(_dg("e3"))),
        _rec("20260905", c1_lit=True, court=_court(_dg("e3"), win_end="20260905")),
    ]
    st = tt.trigger_stability(records)
    assert st["condition_1_streak"] == 3  # c3, c4, e3 三个数据状态
    # 原始账本事实保持: 记录数/首末日不折叠
    assert st["records"] == 4
    assert st["first_date"] == "20260902"
    assert st["last_date"] == "20260905"


def test_stability_fold_keeps_first_of_run_for_conjunction():
    """合取连亮同款折叠; 历史最大段不因重复观测虚增。"""
    records = [
        _rec("20260901", c2_lit=True, armed=True, court=_court(_dg("b1"))),
        _rec("20260902", c2_lit=True, armed=True, court=_court(_dg("b1"), win_end="20260902")),
        _rec("20260903", c2_lit=True, armed=True, court=_court(_dg("b2"))),
    ]
    st = tt.trigger_stability(records)
    assert st["condition_2_streak"] == 2
    assert st["conjunction_streak"] == 2
    assert st["max_conjunction_streak"] == 2


def test_stability_fold_regression_relit_not_collapsed():
    """A→B→A 数据回退再亮不折叠 (回归再判定是真判定); 仅相邻同状态折叠。"""
    records = [
        _rec("20260901", c1_lit=True, court=_court(_dg("a1"))),
        _rec("20260902", c1_lit=False, court=_court(_dg("b2"))),
        _rec("20260903", c1_lit=True, court=_court(_dg("a1"))),
    ]
    st = tt.trigger_stability(records)
    assert st["condition_1_streak"] == 1  # 尾部 A 态独立计 1


def test_stability_fold_skipped_without_digest():
    """缺 digest (旧形态/毒化形态) 记录永不折叠 — 未知不合并。"""
    records = [
        _rec("20260901", c1_lit=True, court=_court(None)),
        _rec("20260902", c1_lit=True, court=_court(None, win_end="20260902")),
    ]
    st = tt.trigger_stability(records)
    assert st["condition_1_streak"] == 2


def test_qualification_folds_duplicates_within_window():
    """资格窗口内重复观测不膨胀 q 值 — 保首语义: 注册前首现的状态不因
    周末重复观测变成注册后证据。"""
    reg = {"anchor": "production_aligned/t10", "k_070": 3,
           "registered_date": "20260903"}
    records = [
        _rec("20260902", c2_lit=True, armed=True, court=_court(_dg("e3"))),  # 状态 e3 注册前首现
        _rec("20260904", c2_lit=True, armed=True, court=_court(_dg("e3"), win_end="20260904")),  # 重复观测
        _rec("20260905", c2_lit=True, armed=True, court=_court(_dg("f4"), win_end="20260905")),
    ]
    qual = tt.trigger_qualification(records, reg)
    assert qual["q_070"] == 1  # 仅 f4 一个新状态; e3 首现在注册前不追溯
    assert qual["qualified_070"] is False


def test_qualification_folds_duplicates_all_in_window():
    """窗内相邻重复折叠: 两记录同状态只计 1。"""
    reg = {"anchor": "production_aligned/t10", "k_070": 2,
           "registered_date": "20260901"}
    records = [
        _rec("20260904", c2_lit=True, armed=True, court=_court(_dg("e3"))),
        _rec("20260905", c2_lit=True, armed=True, court=_court(_dg("e3"), win_end="20260905")),
    ]
    qual = tt.trigger_qualification(records, reg)
    assert qual["q_070"] == 1
    assert qual["qualified_070"] is False
