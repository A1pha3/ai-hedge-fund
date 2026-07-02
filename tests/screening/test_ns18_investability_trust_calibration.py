"""NS-18 trust calibration pass — investability.py build_front_door_verdict 3 gaps.

AutoDev C12/Loop 13 (c282): closes 3 trust calibration gaps in
build_front_door_verdict that let gate behavior be correct but presentation
layer dishonest — user cannot self-audit decision reasons.

Gaps closed:
1. market_regime unknown 误导 (L295-298) — 原二分支把 unknown / 空 / 拼写错误
   全部标 "市场门控转弱". 改为白名单三档: crisis/risk_off → "risk-off";
   已知非 risk-off (cautious/range/normal) → "转弱"; 其他 → "regime 未识别".
2. horizon 数据缺失 (L207-208 / L329-330) — `or {}` 保护把 expected_returns/
   win_rates 缺失静默兜底为空 dict, `_safe_metric(..., 0.0)` 把缺失变 0.0 触发
   AVOID (gate 正确) 但 invalidation_reason 不标 "horizon 数据缺失". 与 R68/R96
   falsy-zero 同源未闭环. 新增显式检查: sample_count > 0 且 horizon dict 为空
   → 标 "horizon 数据缺失".
3. missing-composite 无 0.9 discount (L203-206) — ranker L408 对 missing-composite
   应用 0.9 折扣 (R39 defensive), 但 verdict 直接读 score_b 无折扣. 把 0.9 折扣
   下沉到 verdict, 让 direct call 路径 (测试/skill/ad-hoc) 也有一致行为. 同时
   invalidation_reasons 标 "composite 缺失(已折扣)".

Tests verify:
- Gap 1: regime="unknown" → "regime 未识别" (NOT "市场门控转弱")
- Gap 1: regime="" → "regime 未识别"
- Gap 1: regime="cautious" → "市场门控转弱" (向后兼容)
- Gap 1: regime="crisis" → "市场门控维持 risk-off" (向后兼容)
- Gap 2: sample_count>0 + empty expected_returns → "horizon 数据缺失"
- Gap 2: sample_count>0 + empty win_rates → "horizon 数据缺失"
- Gap 2: sample_count>0 + full horizon dicts → no "horizon 数据缺失"
- Gap 3: missing composite_score_gated + composite_score → use composite_score (no discount)
- Gap 3: missing both → use score_b * 0.9 + "composite 缺失(已折扣)"
- Gap 3: score_b=0.55 missing-composite → 0.495 < 0.5 → not BUY (R39 intent)
"""

from __future__ import annotations

from typing import Any

from src.screening.investability import build_front_door_verdict


def _make_rec(
    *,
    ticker: str = "TEST001",
    composite_score_gated: float | None = 0.6,
    composite_score: float | None = 0.6,
    score_b: float = 0.5,
    expected_returns: dict[str, float] | None = None,
    win_rates: dict[str, float] | None = None,
    bucket_sample_count: int = 100,
    decision: str = "bullish",
) -> dict[str, Any]:
    """构造 build_front_door_verdict 输入 rec (默认通过 BUY gate)."""
    rec: dict[str, Any] = {
        "ticker": ticker,
        "decision": decision,
        "score_b": score_b,
        "bucket_sample_count": bucket_sample_count,
    }
    if composite_score_gated is not None:
        rec["composite_score_gated"] = composite_score_gated
    if composite_score is not None:
        rec["composite_score"] = composite_score
    # 默认填充让 BUY gate 通过的 horizon 数据
    rec["expected_returns"] = expected_returns if expected_returns is not None else {
        "t5": 0.02, "t10": 0.025, "t30": 0.03,
    }
    rec["win_rates"] = win_rates if win_rates is not None else {
        "t5": 0.60, "t10": 0.62, "t30": 0.55,
    }
    return rec


# ---------------------------------------------------------------------------
# Gap 1: market_regime unknown 三档判定
# ---------------------------------------------------------------------------


class TestMarketRegimeUnknownHonestLabel:
    """NS-18 trust calibration (c282): regime 未识别时诚实标注, 不假装"转弱"."""

    def test_regime_unknown_labels_as_unrecognized(self) -> None:
        """regime='unknown' → 'regime 未识别' (NOT '市场门控转弱')."""
        rec = _make_rec()
        verdict = build_front_door_verdict(rec, market_regime="unknown")
        reasons = verdict["invalidation_reason"]
        assert "regime 未识别" in reasons, (
            f"regime='unknown' should label 'regime 未识别'; got reasons={reasons}"
        )
        assert "市场门控转弱" not in reasons, (
            f"regime='unknown' should NOT label '市场门控转弱' (misleading); got reasons={reasons}"
        )

    def test_regime_empty_labels_as_unrecognized(self) -> None:
        """regime='' → 'regime 未识别' (空字符串 = 未识别)."""
        rec = _make_rec()
        verdict = build_front_door_verdict(rec, market_regime="")
        reasons = verdict["invalidation_reason"]
        assert "regime 未识别" in reasons, (
            f"regime='' should label 'regime 未识别'; got reasons={reasons}"
        )

    def test_regime_typo_labels_as_unrecognized(self) -> None:
        """regime='risky' (拼写错误) → 'regime 未识别'."""
        rec = _make_rec()
        verdict = build_front_door_verdict(rec, market_regime="risky")
        reasons = verdict["invalidation_reason"]
        assert "regime 未识别" in reasons, (
            f"regime='risky' (typo) should label 'regime 未识别'; got reasons={reasons}"
        )

    def test_regime_cautious_labels_as_weakening(self) -> None:
        """regime='cautious' → '市场门控转弱' (向后兼容, 已知非 risk-off)."""
        rec = _make_rec()
        verdict = build_front_door_verdict(rec, market_regime="cautious")
        reasons = verdict["invalidation_reason"]
        assert "市场门控转弱" in reasons, (
            f"regime='cautious' should label '市场门控转弱' (backward compat); got reasons={reasons}"
        )
        assert "regime 未识别" not in reasons

    def test_regime_normal_labels_as_weakening(self) -> None:
        """regime='normal' → '市场门控转弱' (向后兼容)."""
        rec = _make_rec()
        verdict = build_front_door_verdict(rec, market_regime="normal")
        reasons = verdict["invalidation_reason"]
        assert "市场门控转弱" in reasons

    def test_regime_range_labels_as_weakening(self) -> None:
        """regime='range' → '市场门控转弱' (向后兼容)."""
        rec = _make_rec()
        verdict = build_front_door_verdict(rec, market_regime="range")
        reasons = verdict["invalidation_reason"]
        assert "市场门控转弱" in reasons

    def test_regime_crisis_labels_as_risk_off(self) -> None:
        """regime='crisis' → '市场门控维持 risk-off' (向后兼容)."""
        rec = _make_rec()
        verdict = build_front_door_verdict(rec, market_regime="crisis")
        reasons = verdict["invalidation_reason"]
        assert "市场门控维持 risk-off" in reasons
        assert "市场门控转弱" not in reasons
        assert "regime 未识别" not in reasons

    def test_regime_risk_off_labels_as_risk_off(self) -> None:
        """regime='risk_off' → '市场门控维持 risk-off' (向后兼容)."""
        rec = _make_rec()
        verdict = build_front_door_verdict(rec, market_regime="risk_off")
        reasons = verdict["invalidation_reason"]
        assert "市场门控维持 risk-off" in reasons


# ---------------------------------------------------------------------------
# Gap 2: horizon 数据缺失显式标注
# ---------------------------------------------------------------------------


class TestHorizonDataMissingHonestLabel:
    """NS-18 trust calibration (c282): horizon dict 缺失时显式标注."""

    def test_empty_expected_returns_labels_horizon_missing(self) -> None:
        """sample_count>0 + empty expected_returns → 'horizon 数据缺失'."""
        rec = _make_rec(expected_returns={})
        verdict = build_front_door_verdict(rec, market_regime="normal")
        reasons = verdict["invalidation_reason"]
        assert "horizon 数据缺失" in reasons, (
            f"empty expected_returns should label 'horizon 数据缺失'; got reasons={reasons}"
        )

    def test_empty_win_rates_labels_horizon_missing(self) -> None:
        """sample_count>0 + empty win_rates → 'horizon 数据缺失'."""
        rec = _make_rec(win_rates={})
        verdict = build_front_door_verdict(rec, market_regime="normal")
        reasons = verdict["invalidation_reason"]
        assert "horizon 数据缺失" in reasons, (
            f"empty win_rates should label 'horizon 数据缺失'; got reasons={reasons}"
        )

    def test_missing_expected_returns_key_labels_horizon_missing(self) -> None:
        """sample_count>0 + expected_returns key absent → 'horizon 数据缺失'.

        L207 `or {}` 把 None/missing 静默兜底为空 dict, 但 sample_count>0 说明
        bucket 有样本, horizon 计算缺失是数据完整性问题, 应诚实标注.
        """
        rec = _make_rec()
        del rec["expected_returns"]  # 完全删除 key
        verdict = build_front_door_verdict(rec, market_regime="normal")
        reasons = verdict["invalidation_reason"]
        assert "horizon 数据缺失" in reasons

    def test_full_horizon_dicts_no_horizon_missing_label(self) -> None:
        """sample_count>0 + 完整 horizon dicts → 不标 'horizon 数据缺失'."""
        rec = _make_rec()  # 默认填充完整 horizon
        verdict = build_front_door_verdict(rec, market_regime="normal")
        reasons = verdict["invalidation_reason"]
        assert "horizon 数据缺失" not in reasons, (
            f"full horizon dicts should NOT label 'horizon 数据缺失'; got reasons={reasons}"
        )

    def test_sample_count_zero_with_empty_horizon_no_horizon_missing_label(self) -> None:
        """sample_count=0 + empty horizon → 只标 '数据缺失', 不标 'horizon 数据缺失'.

        sample_count=0 是更严重的 "完全无数据", 已由 L339 的 '数据缺失' 标注覆盖.
        'horizon 数据缺失' 是针对 "bucket 有样本但 horizon 计算缺失" 的更细致标注,
        不应在 sample_count=0 时重复触发.
        """
        rec = _make_rec(expected_returns={}, win_rates={}, bucket_sample_count=0)
        verdict = build_front_door_verdict(rec, market_regime="normal")
        reasons = verdict["invalidation_reason"]
        assert "数据缺失" in reasons  # 完全无数据
        assert "horizon 数据缺失" not in reasons, (
            f"sample_count=0 should NOT also label 'horizon 数据缺失' (redundant); "
            f"got reasons={reasons}"
        )


# ---------------------------------------------------------------------------
# Gap 3: missing-composite 0.9 discount 下沉到 verdict
# ---------------------------------------------------------------------------


class TestMissingCompositeDiscount:
    """NS-18 trust calibration (c282): missing-composite 0.9 折扣下沉到 verdict.

    与 ranker L408 的 R39 defensive 逻辑一致, 让 direct call 路径也有一致行为.
    """

    def test_missing_composite_uses_score_b_with_discount(self) -> None:
        """composite_score_gated + composite_score 都缺失 → score_b * 0.9."""
        # score_b=0.60, missing-composite → 0.60 * 0.9 = 0.54 (仍 >= 0.5 BUY gate)
        rec = _make_rec(
            composite_score_gated=None,
            composite_score=None,
            score_b=0.60,
        )
        verdict = build_front_door_verdict(rec, market_regime="normal")
        # action 应该是 BUY (0.54 >= 0.5 + horizon passes)
        assert verdict["action"] == "BUY", (
            f"score_b=0.60 missing-composite → 0.54 >= 0.5 → BUY; "
            f"got action={verdict['action']}"
        )
        # invalidation_reason 应标 "composite 缺失(已折扣)"
        reasons = verdict["invalidation_reason"]
        assert "composite 缺失(已折扣)" in reasons, (
            f"missing-composite should label 'composite 缺失(已折扣)'; got reasons={reasons}"
        )

    def test_missing_composite_score_b_055_not_buy(self) -> None:
        """score_b=0.55 missing-composite → 0.495 < 0.5 → NOT BUY (R39 intent).

        R39 注释: "应降级为 HOLD 的标的(composite≈0.4)以 score_b=0.55 跨越 BUY 0.5
        门控". 0.9 折扣后 0.495 < 0.5, 正确阻止跨越.
        """
        rec = _make_rec(
            composite_score_gated=None,
            composite_score=None,
            score_b=0.55,
        )
        verdict = build_front_door_verdict(rec, market_regime="normal")
        assert verdict["action"] != "BUY", (
            f"score_b=0.55 missing-composite → 0.495 < 0.5 → NOT BUY (R39 intent); "
            f"got action={verdict['action']}"
        )

    def test_present_composite_no_discount_no_label(self) -> None:
        """composite_score_gated 存在 → 直接用, 无折扣, 无 'composite 缺失' 标注."""
        rec = _make_rec(composite_score_gated=0.65, composite_score=0.60, score_b=0.50)
        verdict = build_front_door_verdict(rec, market_regime="normal")
        # 应该用 composite_score_gated=0.65 (无折扣)
        assert verdict["action"] == "BUY"  # 0.65 >= 0.5
        reasons = verdict["invalidation_reason"]
        assert "composite 缺失(已折扣)" not in reasons, (
            f"present composite should NOT label 'composite 缺失(已折扣)'; got reasons={reasons}"
        )

    def test_composite_score_gated_missing_falls_back_to_composite_score(self) -> None:
        """composite_score_gated 缺失但 composite_score 存在 → 用 composite_score, 无折扣.

        这是 normal path (旧报告/无 bonus 路径), 不触发 missing-composite 折扣.
        只有两者都缺失才触发折扣.
        """
        rec = _make_rec(
            composite_score_gated=None,
            composite_score=0.58,
            score_b=0.50,
        )
        verdict = build_front_door_verdict(rec, market_regime="normal")
        # 应该用 composite_score=0.58 (无折扣)
        assert verdict["action"] == "BUY"  # 0.58 >= 0.5
        reasons = verdict["invalidation_reason"]
        assert "composite 缺失(已折扣)" not in reasons, (
            f"composite_score present should NOT label 'composite 缺失(已折扣)'; got reasons={reasons}"
        )


# ---------------------------------------------------------------------------
# Gap 3 continuation: ranker-path missing-composite disclosure consistency
# ---------------------------------------------------------------------------
# c282 把 0.9 折扣从 ranker 下沉到 verdict 让两条路径的 DISCOUNT 一致, 但
# DISCLOSURE ("composite 缺失(已折扣)" invalidation_reason) 仍只在 direct call
# 路径 (_composite_score_raw is None) 触发. ranker 处理过的 missing-composite
# 标的到达 verdict 时 composite_score 已是 0.9*score_b (float 非 None), verdict
# 读不出"这是 missing-composite"→ 默认前门 (ranker→verdict) 路径的 invalidation_reason
# 漏标. 渲染层 (top_picks "估" marker / decision_flow "估" marker) 读 composite_verified
# 兜底了显示层, 但 verdict 的结构化 invalidation_reason 字段 (API/logs/替代渲染器
# 消费的 canonical disclosure) 不一致. 修复: 把 disclosure 条件从"_score_raw is None"
# 扩展为"_score_raw is None OR composite_verified is False" (与 top_picks.py:1506
# 和 decision_flow.py:274 的 strict False 检查对齐), discount 保持 direct-path-only
# (ranker 已折扣, 不重复).


class TestMissingCompositeDisclosureRankerPath:
    """NS-18 trust calibration (c283): ranker-path missing-composite disclosure.

    ranker 对 missing-composite 标的设置 ``composite_verified=False`` 并把
    ``composite_score=round(score_b*0.9, 4)`` 写入 rec. 默认前门路径 (ranker →
    verdict) 上, verdict 读到的 composite_score 是 float (非 None), 原
    ``_is_missing_composite = _composite_score_raw is None`` 检测为 False →
    "composite 缺失(已折扣)" invalidation_reason 不触发. 与 direct call 路径
    披露不一致 (c282 消除的"必须先经 ranker"隐式依赖在 DISCLOSURE 侧复发).
    """

    @staticmethod
    def _ranker_missing_composite_rec(*, score_b: float = 0.55) -> dict[str, Any]:
        """构造 rank_recommendations_by_investability 对 missing-composite 标的的输出.

        模拟 investability.py L433-450 的 else 分支:
        - composite_score_gated: 不设置 (ranker 从不设置此字段)
        - composite_score: round(score_b * 0.9, 4) (R39 0.9 折扣, float 非 None)
        - composite_verified: False (ranker 显式标记)
        - base_score = score_b; momentum/sector/consistency/volume/trend bonus = 0
        """
        return {
            "ticker": "RANKER001",
            "decision": "bullish",
            "score_b": score_b,
            "base_score": score_b,
            "momentum_bonus": 0.0,
            "sector_bonus": 0.0,
            "consistency_adj": 0.0,
            "volume_factor": 0.0,
            "trend_resonance_factor": 0.0,
            "composite_score": round(score_b * 0.9, 4),
            "composite_grade": "C",
            "composite_verified": False,
            "bucket_sample_count": 100,
            "bucket_label": "mid",
            "bucket_t30_mature_count": 80,
            "expected_returns": {"t5": 0.02, "t10": 0.025, "t30": 0.03},
            "win_rates": {"t5": 0.60, "t10": 0.62, "t30": 0.55},
        }

    def test_ranker_path_missing_composite_labels_discounted(self) -> None:
        """ranker 处理过的 missing-composite 标的 → verdict 必须标 'composite 缺失(已折扣)'.

        这是默认前门路径 (ranker → verdict). composite_score=0.495 (0.55*0.9) 非 None,
        但 composite_verified=False 是 ranker 留下的 missing-composite 信号. verdict 的
        结构化 invalidation_reason 必须披露, 与 direct call 路径一致.
        """
        rec = self._ranker_missing_composite_rec(score_b=0.55)
        verdict = build_front_door_verdict(rec, market_regime="normal")
        reasons = verdict["invalidation_reason"]
        assert "composite 缺失(已折扣)" in reasons, (
            f"ranker-path missing-composite (composite_verified=False) must label "
            f"'composite 缺失(已折扣)' in verdict invalidation_reason; got reasons={reasons}"
        )

    def test_ranker_path_missing_composite_no_double_discount(self) -> None:
        """ranker-path discount 不重复: composite_score 已是 0.9*score_b, verdict 不再打 0.9.

        score_b=0.60 → ranker 写 composite_score=0.54 (0.60*0.9). verdict 读 0.54,
        若误对 ranker 路径再打 0.9 折扣 → 0.486 < 0.5 → action 从 BUY 翻成 HOLD/AVOID.
        本测试守住"discount direct-path-only"边界: ranker-path 用 ranker 已折扣的值原样.
        """
        rec = self._ranker_missing_composite_rec(score_b=0.60)
        # composite_score = round(0.60 * 0.9, 4) = 0.54 >= 0.5 → 应 BUY
        verdict = build_front_door_verdict(rec, market_regime="normal")
        assert verdict["action"] == "BUY", (
            f"ranker-path: score_b=0.60 → composite_score=0.54 (ranker 已折扣) >= 0.5 → BUY; "
            f"double-discount would push to <0.5 → non-BUY. got action={verdict['action']}"
        )

    def test_ranker_path_verified_composite_no_missing_label(self) -> None:
        """composite_verified=True (真实 composite) → 不标 'composite 缺失(已折扣)'."""
        rec = self._ranker_missing_composite_rec(score_b=0.60)
        rec["composite_verified"] = True  # 真实 composite
        rec["composite_score"] = 0.60  # 真实分, 非 0.9 折扣值
        verdict = build_front_door_verdict(rec, market_regime="normal")
        reasons = verdict["invalidation_reason"]
        assert "composite 缺失(已折扣)" not in reasons, (
            f"composite_verified=True must NOT label 'composite 缺失(已折扣)'; got reasons={reasons}"
        )

    def test_composite_verified_none_legacy_no_missing_label(self) -> None:
        """composite_verified 缺失 (None, 旧报告/未走 ranker) → 不标, 向后兼容.

        与 top_picks.py:1506 和 decision_flow.py:274 一致: strict ``is False`` 检查,
        None / 缺省按 verified 处理, 避免误报.
        """
        rec = self._ranker_missing_composite_rec(score_b=0.60)
        rec.pop("composite_verified")  # 模拟旧报告无此字段
        rec["composite_score"] = 0.60  # 真实分
        verdict = build_front_door_verdict(rec, market_regime="normal")
        reasons = verdict["invalidation_reason"]
        assert "composite 缺失(已折扣)" not in reasons, (
            f"composite_verified missing (None/legacy) must NOT label; got reasons={reasons}"
        )


# ---------------------------------------------------------------------------
# Regression: existing behavior preserved
# ---------------------------------------------------------------------------


class TestExistingBehaviorPreserved:
    """回归: 现有行为 (BUY/HOLD/AVOID gate 逻辑) 不受 trust calibration 影响."""

    def test_buy_gate_still_passes_with_full_data(self) -> None:
        """完整数据的 bullish 标的仍应 BUY."""
        rec = _make_rec()  # 默认通过 BUY gate
        verdict = build_front_door_verdict(rec, market_regime="normal")
        assert verdict["action"] == "BUY"

    def test_avoid_gate_still_blocks_low_quality(self) -> None:
        """低质量标的 (无 horizon 数据 + sample_count=0) 仍应 AVOID."""
        rec = _make_rec(
            expected_returns={},
            win_rates={},
            bucket_sample_count=0,
            composite_score_gated=0.3,
        )
        verdict = build_front_door_verdict(rec, market_regime="normal")
        assert verdict["action"] == "AVOID"

    def test_crisis_regime_still_downgrades_to_hold_or_avoid(self) -> None:
        """crisis regime 下 BUY gate 降级为 HOLD/AVOID (NS-23 C245 行为不变)."""
        rec = _make_rec()  # 默认通过 BUY gate
        verdict = build_front_door_verdict(rec, market_regime="crisis")
        assert verdict["action"] in ("HOLD", "AVOID"), (
            f"crisis regime should downgrade to HOLD/AVOID; got action={verdict['action']}"
        )
