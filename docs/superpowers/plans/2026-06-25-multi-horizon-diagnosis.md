# 多周期诊断验证 (Multi-Horizon Diagnosis) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 tracking_history 加 T+15/T+25 两个实测周期（Phase 1 持久化），再跑一次性诊断脚本验证 6 周期能否选出赚钱的票（Phase 2，产出 54 格表格回答 Q1-Q4）。

**Architecture:** Phase 1 扩展 `DEFAULT_HORIZONS` 常量（fetch_actual_returns 已拉 45 天价格，只是循环没算 15/25）+ 消费者同步加字段（向后兼容 None 默认值）。Phase 2 写 `scripts/_multi_horizon_diagnosis.py`，按 horizon × score 分桶 × regime 分组算 8 指标，跑完删除。

**Tech Stack:** Python 3.12 / pytest / 现有 `recommendation_tracker` + `verify_recommendations` + `confidence_calibration` 模块。无新依赖。

## Global Constraints

（从 spec `docs/superpowers/specs/2026-06-25-multi-horizon-diagnosis-design.md` 逐字摘录）

- **分桶逻辑**：固定切分 `<0.4` / `0.4 <= score < 0.5` / `score >= 0.5`，跨 horizon 统一，不试其他切分
- **6 horizon**：T+5, T+10, T+15, T+20, T+25, T+30（Phase 2 诊断用 6 个；Phase 1 扩展到 8 个含 T+1/T+3）
- **8 指标**：n / 胜率 / median / mean / 上行赔率 / 下行赔率 / 盈亏比 / 5th pct
- **收益过滤**：`-50% ~ +50%`（百分点，防除权/停牌异常）
- **样本不足**：n>=20 完整 8 指标；10<=n<20 加 ⚠、5th pct 不显示；n<10 加 ❌、5th pct 不显示、不参与结论
- **行长度**：black/flake8 用 420 字符（CLAUDE.md 规约）
- **诚实约束**：不 cherry-pick、不 p-hack、不预设结论、regime 关联失败归 unknown 桶
- **TDD**：Phase 1 所有改动先写 RED 测试再 GREEN
- **commit**：Phase 1 commit 持久化；Phase 2 脚本跑完删除，commit "chore: 移除一次性诊断脚本"
- **Sanity check**：Phase 2 的 T+30 聚合全 score 桶，胜率应约等于 R-5.A `REGIME_HISTORICAL_WINRATES`（normal 43% / crisis 47% / risk_off 30%），偏离 >5pp 需排查

---

## File Structure

### Phase 1 修改文件

| 文件 | 责任 | 改动 |
|---|---|---|
| `src/screening/recommendation_tracker.py` | tracking_history 核心数据结构 + 回填 | 扩 `DEFAULT_HORIZONS` + `TrackingRecord` 加 2 字段 + `from_dict` + fetch 映射 + bucket_fields |
| `src/screening/verify_recommendations.py` | 历史推荐胜率/收益验证 | 扩 `_extract_tracking_returns` + summary 加 t15/t25 |
| `src/screening/confidence_calibration.py` | score 分桶校准 | 扩 `ScoreBucketStats` + bucket 提取加 t15/t25 |
| `src/screening/btst_realized_bridge.py` | BTST 桥接到 tracking_history | seed dict + horizon 映射加 t15/t25 |

### Phase 1 测试文件

| 文件 | 责任 |
|---|---|
| `tests/test_recommendation_tracker_extended_horizons.py` | 已有 P5-1 扩展测试，新增 T+15/T+25 用例 |

### Phase 2 新建文件（跑完删除）

| 文件 | 责任 |
|---|---|
| `scripts/_multi_horizon_diagnosis.py` | 一次性诊断：6 horizon × 3 分桶 × 3 regime = 54 格 × 8 指标 |

---

## Phase 1: 持久化基础设施（TDD，commit）

### Task 1: 扩展 `DEFAULT_HORIZONS` + `TrackingRecord` 字段

**Files:**
- Modify: `src/screening/recommendation_tracker.py:54`（常量）
- Modify: `src/screening/recommendation_tracker.py:75-97`（dataclass docstring + 字段）
- Modify: `src/screening/recommendation_tracker.py:103-119`（`from_dict`）
- Test: `tests/test_recommendation_tracker_extended_horizons.py`

**Interfaces:**
- Produces: `DEFAULT_HORIZONS = (1, 3, 5, 10, 15, 20, 25, 30)`；`TrackingRecord.next_15day_return: float | None`；`TrackingRecord.next_25day_return: float | None`

- [ ] **Step 1: 写 RED 测试 — DEFAULT_HORIZONS 含 15/25**

在 `tests/test_recommendation_tracker_extended_horizons.py` 末尾追加：

```python
def test_default_horizons_includes_t15_t25():
    """DEFAULT_HORIZONS 必须包含 T+15, T+25 (Phase 1 多周期扩展)."""
    from src.screening.recommendation_tracker import DEFAULT_HORIZONS

    assert 15 in DEFAULT_HORIZONS, "T+15 missing from DEFAULT_HORIZONS"
    assert 25 in DEFAULT_HORIZONS, "T+25 missing from DEFAULT_HORIZONS"
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_recommendation_tracker_extended_horizons.py::test_default_horizons_includes_t15_t25 -v`
Expected: FAIL "T+15 missing from DEFAULT_HORIZONS"

- [ ] **Step 3: 改常量（最小改动让它通过）**

`src/screening/recommendation_tracker.py:54`：

```python
DEFAULT_HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 15, 20, 25, 30)
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/test_recommendation_tracker_extended_horizons.py::test_default_horizons_includes_t15_t25 -v`
Expected: PASS

- [ ] **Step 5: 写 RED 测试 — TrackingRecord 含 next_15day_return/next_25day_return 字段**

在 `tests/test_recommendation_tracker_extended_horizons.py` 追加：

```python
def test_tracking_record_has_t15_t25_fields():
    """TrackingRecord 必须含 next_15day_return / next_25day_return 字段."""
    from src.screening.recommendation_tracker import TrackingRecord

    rec = TrackingRecord(
        ticker="000001",
        name="平安",
        recommended_date="20260101",
        recommended_price=10.0,
        recommendation_score=0.4,
        next_15day_return=3.5,
        next_25day_return=-1.2,
    )
    assert rec.next_15day_return == 3.5
    assert rec.next_25day_return == -1.2


def test_tracking_record_from_dict_reads_t15_t25():
    """from_dict 必须读 next_15day_return / next_25day_return."""
    from src.screening.recommendation_tracker import TrackingRecord

    payload = {
        "ticker": "000001",
        "name": "平安",
        "recommended_date": "20260101",
        "recommended_price": 10.0,
        "recommendation_score": 0.4,
        "next_15day_return": 2.1,
        "next_25day_return": None,
    }
    rec = TrackingRecord.from_dict(payload)
    assert rec.next_15day_return == 2.1
    assert rec.next_25day_return is None
```

- [ ] **Step 6: 跑测试验证失败**

Run: `uv run pytest tests/test_recommendation_tracker_extended_horizons.py::test_tracking_record_has_t15_t25_fields tests/test_recommendation_tracker_extended_horizons.py::test_tracking_record_from_dict_reads_t15_t25 -v`
Expected: FAIL "TrackingRecord has no attribute 'next_15day_return'"

- [ ] **Step 7: 改 dataclass（最小改动让它通过）**

`src/screening/recommendation_tracker.py:80-96` 在 `next_10day_return` 之后、`next_20day_return` 之前加 2 字段。docstring 同步加 2 行。

```python
    next_10day_return: float | None = None  # 已有
    next_15day_return: float | None = None  # 新增
    next_20day_return: float | None = None  # 已有
    next_25day_return: float | None = None  # 新增
    next_30day_return: float | None = None  # 已有
```

docstring 在 `next_10day_return` 行后加：

```python
        next_15day_return: T+15 收益率 (%, 可正可负); 缺失时为 ``None``
```

在 `next_20day_return` 行后加：

```python
        next_25day_return: T+25 收益率 (%, 可正可负); 缺失时为 ``None``
```

- [ ] **Step 8: 改 `from_dict`（`recommendation_tracker.py:113-117`）**

在 `next_10day_return=_optional_float(...)` 后、`next_20day_return=...` 前加：

```python
            next_15day_return=_optional_float(payload.get("next_15day_return")),
```

在 `next_20day_return=...` 后、`next_30day_return=...` 前加：

```python
            next_25day_return=_optional_float(payload.get("next_25day_return")),
```

- [ ] **Step 9: 跑测试验证通过**

Run: `uv run pytest tests/test_recommendation_tracker_extended_horizons.py -v`
Expected: 全部 PASS（含新 3 测试 + 旧 7 测试）

- [ ] **Step 10: 不 commit（等 Task 5 一起）**

---

### Task 2: 扩展回填映射 + bucket_fields（`recommendation_tracker.py`）

**Files:**
- Modify: `src/screening/recommendation_tracker.py:466-473`（fetch 回填映射）
- Modify: `src/screening/recommendation_tracker.py:607-614`（bucket_fields 汇总）
- Test: `tests/test_recommendation_tracker_extended_horizons.py`

**Interfaces:**
- Consumes: Task 1 的 `DEFAULT_HORIZONS`
- Produces: `update_tracking_history` 写入 `next_15day_return/next_25day_return`；`_summarize_history` 输出 `win_count_day15/win_rate_day15/avg_return_day15` 等

- [ ] **Step 1: 写 RED 测试 — fetch_actual_returns 算 day_15/day_25**

追加到测试文件：

```python
def test_fetch_actual_returns_computes_day15():
    """fetch_actual_returns 必须计算 T+15 收益."""
    from src.screening.recommendation_tracker import fetch_actual_returns

    # 15 个交易日的价格序列 (基准 100, T+15 涨到 110 → +10%)
    prices = [("20260101", 100.0)] + [("2026010%d" % i, 100.0 + i) for i in range(1, 16)]
    fetcher = _mock_fetcher_map({"000001": prices})
    result = fetch_actual_returns(["000001"], "20260101", "20260116", use_data_fetcher=fetcher)
    assert "000001" in result
    assert abs(result["000001"]["day_15"] - 10.0) < 0.01


def test_fetch_actual_returns_computes_day25():
    """fetch_actual_returns 必须计算 T+25 收益."""
    from src.screening.recommendation_tracker import fetch_actual_returns

    prices = [("20260101", 100.0)] + [("2026010%d" % i, 100.0 + 2 * i) for i in range(1, 26)]
    fetcher = _mock_fetcher_map({"000001": prices})
    result = fetch_actual_returns(["000001"], "20260101", "20260126", use_data_fetcher=fetcher)
    assert "000001" in result
    assert abs(result["000001"]["day_25"] - 50.0) < 0.01
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/test_recommendation_tracker_extended_horizons.py::test_fetch_actual_returns_computes_day15 tests/test_recommendation_tracker_extended_horizons.py::test_fetch_actual_returns_computes_day25 -v`
Expected: FAIL "KeyError: 'day_15'"（fetcher 已拉 45 天价格但只算 DEFAULT_HORIZONS 循环里的，加 15/25 到常量后自动会算——验证 Task 1 的常量改动是否生效；若已 PASS 说明 Task 1 已覆盖，直接进 Step 3）

- [ ] **Step 3: 扩展 fetch 回填映射（`recommendation_tracker.py:466-473`）**

在 `("next_10day_return", "day_10")` 后加：

```python
                        ("next_15day_return", "day_15"),
```

在 `("next_20day_return", "day_20")` 后加：

```python
                        ("next_25day_return", "day_25"),
```

- [ ] **Step 4: 扩展 bucket_fields（`recommendation_tracker.py:607-614`）**

在 `10: "next_10day_return"` 后加：

```python
        15: "next_15day_return",
```

在 `20: "next_20day_return"` 后加：

```python
        25: "next_25day_return",
```

- [ ] **Step 5: 写 RED 测试 — update_tracking_history 写入 next_15day_return**

追加到测试文件：

```python
def test_update_tracking_history_populates_day15_day25(tmp_path):
    """update_tracking_history 必须填充 next_15day_return / next_25day_return."""
    from src.screening.recommendation_tracker import update_tracking_history, _load_history

    _make_report(tmp_path, "20260101", [
        {"ticker": "000001", "name": "平安", "score_b": 0.4},
    ])
    prices = [("20260101", 100.0)] + [("2026010%d" % i, 100.0 + i) for i in range(1, 31)]
    fetcher = _mock_fetcher_map({"000001": prices})

    update_tracking_history(
        history_path=tmp_path / "tracking_history.json",
        reports_dir=tmp_path,
        trade_date="20260201",
        use_data_fetcher=fetcher,
    )
    records = _load_history(tmp_path / "tracking_history.json")
    assert len(records) == 1
    rec = records[0]
    assert rec.get("next_15day_return") is not None
    assert rec.get("next_25day_return") is not None
```

- [ ] **Step 6: 跑测试验证通过**

Run: `uv run pytest tests/test_recommendation_tracker_extended_horizons.py::test_update_tracking_history_populates_day15_day25 -v`
Expected: PASS（Task 1 常量改动 + Task 2 Step 3-4 已让它生效）

- [ ] **Step 7: 跑 tracker 全部测试验证向后兼容**

Run: `uv run pytest tests/test_recommendation_tracker.py tests/test_recommendation_tracker_extended_horizons.py -v`
Expected: 全部 PASS（旧记录缺 next_15day_return → None，不破坏）

- [ ] **Step 8: 不 commit（等 Task 5 一起）**

---

### Task 3: 扩展 `verify_recommendations` 加 t15/t25

**Files:**
- Modify: `src/screening/verify_recommendations.py:216-230`（`_extract_tracking_returns`）
- Modify: `src/screening/verify_recommendations.py:138-147`（dataclass 字段）
- Modify: `src/screening/verify_recommendations.py:300-466`（accumulator + summary）
- Test: `tests/screening/test_verify_recommendations.py`

**Interfaces:**
- Consumes: tracking_history records（含 next_15day_return/next_25day_return）
- Produces: `VerifySummary.overall_t15_win_rate: float | None`、`overall_t25_win_rate`、`avg_t15_return`、`avg_t25_return`

- [ ] **Step 1: 检查现有 verify 测试结构**

Run: `uv run pytest tests/screening/test_verify_recommendations.py -v 2>&1 | head -30`
Expected: 列出现有测试名，找到 horizon 相关测试模式（若无，参考 `test_verify_recommendations.py` 现有 t30 测试模板）

- [ ] **Step 2: 写 RED 测试 — verify 提取 t15/t25**

追加到 `tests/screening/test_verify_recommendations.py`：

```python
def test_verify_summary_includes_t15_t25_winrate():
    """compute_verify_recommendations 必须算 overall_t15_win_rate / overall_t25_win_rate."""
    from src.screening.verify_recommendations import compute_verify_recommendations, VerifySummary

    # 这个测试依赖现有 fixture 模式; 若 fixture 不支持注入 tracking,
    # 用现有 test_verify_recommendations 里的 tmp_path + tracking_history 模式
    # 参考同文件里 test_t30_win_rate 的 fixture 构造
    summary = compute_verify_recommendations(lookback_days=30, reports_dir=tmp_path)
    assert hasattr(summary, "overall_t15_win_rate")
    assert hasattr(summary, "overall_t25_win_rate")
```

注：具体 fixture 构造参考同文件已有 t30 测试。如果 t30 测试用 `_make_tracking_record(...)` 类 helper，复用它。

- [ ] **Step 3: 跑测试验证失败**

Run: `uv run pytest tests/screening/test_verify_recommendations.py::test_verify_summary_includes_t15_t25_winrate -v`
Expected: FAIL "VerifySummary has no attribute 'overall_t15_win_rate'"

- [ ] **Step 4: 扩展 VerifySummary dataclass（`verify_recommendations.py:138-147`）**

在 `overall_t10_win_rate` 后加：

```python
    overall_t15_win_rate: float | None = None
```

在 `overall_t20_win_rate` 后加：

```python
    overall_t25_win_rate: float | None = None
```

在 `avg_t10_return` 后加 `avg_t15_return: float | None = None`（找对应字段位置）；在 `avg_t20_return` 后加 `avg_t25_return: float | None = None`。

- [ ] **Step 5: 扩展 `_extract_tracking_returns`（`verify_recommendations.py:216-230`）**

改函数签名返回 8 元组（加 t15, t25）。在 `t10 = ...` 后加 `t15 = _optional_float(entry.get("next_15day_return"))`，在 `t20 = ...` 后加 `t25 = _optional_float(entry.get("next_25day_return"))`，返回 tuple 加这两个。调用处（`verify_recommendations.py:367`）同步解包 8 个值。

- [ ] **Step 6: 扩展 accumulator + summary（`verify_recommendations.py:300-466`）**

参照 t10/t20 的 accumulator 模式（`all_t10, t10_wins, t10_total` 等），加 `all_t15, t15_wins, t15_total, all_t25, t25_wins, t25_total`。在 `verify_recommendations.py:461-466` 的 summary 赋值段加：

```python
    summary.overall_t15_win_rate = t15_wins / t15_total if t15_total > 0 else None
    summary.overall_t25_win_rate = t25_wins / t25_total if t25_total > 0 else None
    summary.avg_t15_return = _mean_or_none(all_t15)
    summary.avg_t25_return = _mean_or_none(all_t25)
```

- [ ] **Step 7: 跑测试验证通过**

Run: `uv run pytest tests/screening/test_verify_recommendations.py -v`
Expected: 全部 PASS

- [ ] **Step 8: 不 commit（等 Task 5 一起）**

---

### Task 4: 扩展 `confidence_calibration` 加 t15/t25 分桶统计

**Files:**
- Modify: `src/screening/confidence_calibration.py:340-350`（returns 提取）
- Modify: `src/screening/confidence_calibration.py:357-367`（ScoreBucketStats 字段 + 赋值）
- Test: `tests/screening/test_confidence_calibration.py`

**Interfaces:**
- Consumes: tracking_history records
- Produces: `ScoreBucketStats.t15_win_rate / t15_avg_return / t25_win_rate / t25_avg_return`

- [ ] **Step 1: 检查 `ScoreBucketStats` 字段定义位置**

Run: `grep -n "class ScoreBucketStats\|t10_win_rate\|t20_win_rate" src/screening/confidence_calibration.py`
Expected: 定位 dataclass + 字段位置

- [ ] **Step 2: 写 RED 测试 — ScoreBucketStats 含 t15/t25**

追加到 `tests/screening/test_confidence_calibration.py`：

```python
def test_score_bucket_stats_has_t15_t25():
    """ScoreBucketStats 必须含 t15_win_rate / t25_win_rate."""
    from src.screening.confidence_calibration import ScoreBucketStats

    stats = ScoreBucketStats(
        label="low", score_low=0.0, score_high=0.4, sample_count=10,
        t15_win_rate=0.5, t25_win_rate=0.6,
    )
    assert stats.t15_win_rate == 0.5
    assert stats.t25_win_rate == 0.6
```

- [ ] **Step 3: 跑测试验证失败**

Run: `uv run pytest tests/screening/test_confidence_calibration.py::test_score_bucket_stats_has_t15_t25 -v`
Expected: FAIL "unexpected keyword argument 't15_win_rate'"

- [ ] **Step 4: 扩展 ScoreBucketStats dataclass**

在 `t10_win_rate` 后加 `t15_win_rate: float | None = None`；在 `t20_win_rate` 后加 `t25_win_rate: float | None = None`。同样加 `t15_avg_return / t25_avg_return`。

- [ ] **Step 5: 扩展 returns 提取（`confidence_calibration.py:340-350`）**

在 `t10_returns = [...]` 后加 `t15_returns = [_optional_float(r.get("next_15day_return")) for r in recs]`；在 `t20_returns = [...]` 后加 `t25_returns = [_optional_float(r.get("next_25day_return")) for r in recs]`。

加 `t15_valid = [x for x in t15_returns if x is not None]`、`t25_valid = ...`。

- [ ] **Step 6: 扩展 ScoreBucketStats 构造（`confidence_calibration.py:357-367`）**

在 `t10_win_rate=...` 后加 `t15_win_rate=_win_rate_or_none(t15_valid)`；在 `t20_win_rate=...` 后加 `t25_win_rate=_win_rate_or_none(t25_valid)`。同样加 avg_return。

- [ ] **Step 7: 跑测试验证通过**

Run: `uv run pytest tests/screening/test_confidence_calibration.py -v`
Expected: 全部 PASS

- [ ] **Step 8: 扩展 `btst_realized_bridge.py`（seed dict + horizon 映射）**

`src/screening/btst_realized_bridge.py:118-122` seed dict 在 `next_10day_return` 后加 `"next_15day_return": None`，在 `next_20day_return` 后加 `"next_25day_return": None`。

`btst_realized_bridge.py:156-159` horizon 映射在 `("next_10day_return", "day_10")` 后加 `("next_15day_return", "day_15")`，在 `("next_20day_return", "day_20")` 后加 `("next_25day_return", "day_25")`。

- [ ] **Step 9: 不 commit（等 Task 5 一起）**

---

### Task 5: FULL 回归 + 回填 tracking_history + commit

**Files:**
- 无新文件，跑回填命令
- Run: 回填 + 全套测试

- [ ] **Step 1: 跑全套回归验证向后兼容**

Run: `uv run pytest tests/ -q`
Expected: 全部 PASS（9872 baseline + 新增 ~5 测试 = 9877 左右），0 failures

- [ ] **Step 2: 跑 lint**

Run: `uv run flake8 --max-line-length 420 src/screening/recommendation_tracker.py src/screening/verify_recommendations.py src/screening/confidence_calibration.py src/screening/btst_realized_bridge.py`
Expected: 0 errors

- [ ] **Step 3: 备份 tracking_history（回填前）**

Run: `cp data/reports/tracking_history.json data/reports/tracking_history.json.bak-pre-t15-t25`
（备份防止回填出错；回填成功后可删 .bak）

- [ ] **Step 4: 触发回填 — 写一次性回填脚本**

写 `scripts/_backfill_t15_t25.py`（临时脚本，跑完删除）：

```python
"""一次性脚本: 给 tracking_history 现有 293 条记录补 T+15/T+25 实测收益.

R-5.E 已拉过 45 天价格窗口, tushare 价格应大多缓存; 对每条记录
调用 fetch_actual_returns (现已含 day_15/day_25) 并写回.
"""
from pathlib import Path
from src.screening.recommendation_tracker import (
    _load_history, _save_history, update_tracking_history, HISTORY_FILENAME,
)

reports_dir = Path("data/reports")
history_path = reports_dir / HISTORY_FILENAME

# update_tracking_history 会扫描 auto_screening 报告, 用 fetch_actual_returns 拉价
# 格并填充所有 DEFAULT_HORIZONS 字段 (含新的 15/25)。它会增量合并, 不破坏现有数据。
update_tracking_history(
    history_path=history_path,
    reports_dir=reports_dir,
    trade_date=None,  # 锚定到历史最新 recommended_date
)

records = _load_history(history_path)
n_t15 = sum(1 for r in records if r.get("next_15day_return") is not None)
n_t25 = sum(1 for r in records if r.get("next_25day_return") is not None)
print(f"回填完成: {len(records)} 条记录, T+15={n_t15}, T+25={n_t25}")
```

注：`update_tracking_history` 的确切签名以 `recommendation_tracker.py:371` 为准（trade_date 参数名、是否必需）。如果 `trade_date=None` 不被接受，参考 R-5.E 用过的回填调用方式。

- [ ] **Step 5: 跑回填脚本**

Run: `uv run python scripts/_backfill_t15_t25.py`
Expected: 输出 "回填完成: 293 条记录, T+15=<N>, T+25=<N>"，N 应接近记录数（缺数据的归 None）

- [ ] **Step 6: 验证回填完整性**

Run: `uv run python -c "
import json
with open('data/reports/tracking_history.json') as f:
    th = json.load(f)
recs = th['records']
n_t15 = sum(1 for r in recs if r.get('next_15day_return') is not None)
n_t25 = sum(1 for r in recs if r.get('next_25day_return') is not None)
n_t30 = sum(1 for r in recs if r.get('next_30day_return') is not None)
print(f'Total: {len(recs)}, T+15: {n_t15}, T+25: {n_t25}, T+30: {n_t30}')
"`
Expected: T+15/T+25 数量与 T+30 相近（差值 = 那些在第 15/25 天停牌或缺数据的）

- [ ] **Step 7: 删除回填脚本**

Run: `rm scripts/_backfill_t15_t25.py data/reports/tracking_history.json.bak-pre-t15-t25`

- [ ] **Step 8: commit Phase 1**

```bash
git add src/screening/recommendation_tracker.py \
        src/screening/verify_recommendations.py \
        src/screening/confidence_calibration.py \
        src/screening/btst_realized_bridge.py \
        tests/test_recommendation_tracker_extended_horizons.py \
        tests/screening/test_verify_recommendations.py \
        tests/screening/test_confidence_calibration.py \
        data/reports/tracking_history.json
git commit -m "feat(multi-horizon): 扩展 DEFAULT_HORIZONS 到 8 周期 (T+15/T+25)

Phase 1 持久化基础设施 (multi-horizon diagnosis 设计 docs/superpowers/specs/2026-06-25-...):
- recommendation_tracker.DEFAULT_HORIZONS 加 15/25
- TrackingRecord 加 next_15day_return/next_25day_return
- verify_recommendations / confidence_calibration / btst_realized_bridge 同步加字段
- 回填 293 条现有记录 (T+15/T+25 实测收益)

向后兼容: 旧记录缺字段 → None 默认值, 不破坏消费者。
TDD: 5+ 新测试覆盖 horizon 字段 + 回填 + verify。"
```

---

## Phase 2: 一次性诊断脚本（跑完删除）

### Task 6: 写诊断脚本

**Files:**
- Create: `scripts/_multi_horizon_diagnosis.py`

**Interfaces:**
- Consumes: `data/reports/tracking_history.json`（Phase 1 后含 T+15/T+25）+ `data/reports/auto_screening_*.json`（regime 关联）
- Produces: 终端打印 54 格表 + 文字结论

- [ ] **Step 1: 写脚本主体**

`scripts/_multi_horizon_diagnosis.py`：

```python
"""一次性诊断: 多周期 (T+5/10/15/20/25/30) × score 分桶 × regime 胜率/赔率.

目标: 回答 Q1-Q4, 决定后续做 A/B/C/D 中的哪些 (见
docs/superpowers/specs/2026-06-25-multi-horizon-diagnosis-design.md).

诚实约束:
- 固定分桶 <0.4 / 0.4-0.5 / 0.5+ (不试其他切分)
- 54 格全部展示 (不 cherry-pick)
- n<10 不参与结论; n<20 不显示 5th pct
- T+30 baseline 应约等于 R-5.A REGIME_HISTORICAL_WINRATES (sanity check)

跑完删除 (先例: commit 6de3935f).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

# 6 诊断 horizon (Phase 2 不含 T+1/T+3, 噪声大)
DIAG_HORIZONS = [
    ("t5", "T+5", "next_5day_return"),
    ("t10", "T+10", "next_10day_return"),
    ("t15", "T+15", "next_15day_return"),
    ("t20", "T+20", "next_20day_return"),
    ("t25", "T+25", "next_25day_return"),
    ("t30", "T+30", "next_30day_return"),
]

SCORE_BUCKETS = [
    ("<0.4", lambda s: s < 0.4),
    ("0.4-0.5", lambda s: 0.4 <= s < 0.5),
    ("0.5+", lambda s: s >= 0.5),
]

REGIMES = ["normal", "crisis", "risk_off", "unknown"]

# 收益过滤 (百分点; 防 50%+ 异常)
RETURN_MIN = -50.0
RETURN_MAX = 50.0

# R-5.A v2 数据 (sanity check baseline)
R5A_BASELINE = {
    "normal": {"winrate": 0.434, "n": 60},
    "crisis": {"winrate": 0.468, "n": 119},
    "risk_off": {"winrate": 0.30, "n": 10},
}


def load_tracking(path: Path) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return data.get("records", [])


def load_regime_map(reports_dir: Path) -> dict[str, str]:
    """recommended_date (YYYYMMDD) → regime_gate_level."""
    regime_map: dict[str, str] = {}
    for report in reports_dir.glob("auto_screening_*.json"):
        try:
            with open(report) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        date = str(data.get("date", ""))
        if not date:
            continue
        ms = data.get("market_state") or {}
        regime = str(ms.get("regime_gate_level", "") or "").strip().lower()
        regime_map[date] = regime if regime in ("normal", "crisis", "risk_off") else "unknown"
    return regime_map


def resolve_regime(rec_date: str, regime_map: dict[str, str]) -> str:
    return regime_map.get(rec_date, "unknown")


def filter_valid(returns: list[float]) -> list[float]:
    return [r for r in returns if r is not None and RETURN_MIN <= r <= RETURN_MAX]


def compute_metrics(returns: list[float]) -> dict:
    """算 8 指标. returns 已过滤."""
    n = len(returns)
    if n == 0:
        return {"n": 0, "winrate": None, "median": None, "mean": None,
                "upside": None, "downside": None, "rr_ratio": None, "p5": None}
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    winrate = len(wins) / n
    med = median(returns)
    avg = mean(returns)
    upside = mean(wins) if wins else None
    downside = mean(losses) if losses else None
    rr_ratio = (upside / abs(downside)) if (upside is not None and downside is not None and downside != 0) else None
    # 5th pct 仅 n>=20 才稳定
    p5 = None
    if n >= 20:
        sorted_r = sorted(returns)
        idx = max(0, int(0.05 * n) - 1)
        p5 = sorted_r[idx]
    return {"n": n, "winrate": winrate, "median": med, "mean": avg,
            "upside": upside, "downside": downside, "rr_ratio": rr_ratio, "p5": p5}


def fmt_pct(v, warn_n=None):
    if v is None:
        return "—"
    suffix = ""
    if warn_n is not None and 10 <= warn_n < 20:
        suffix = " ⚠"
    elif warn_n is not None and warn_n < 10:
        suffix = " ❌"
    return f"{v:+.1f}%{suffix}" if isinstance(v, (int, float)) and "winrate" not in str(v) else f"{v:.0%}{suffix}"


def fmt_ratio(v, n):
    if v is None:
        return "—"
    suffix = " ⚠" if 10 <= n < 20 else (" ❌" if n < 10 else "")
    return f"{v:.2f}{suffix}"


def main():
    reports_dir = Path("data/reports")
    tracking = load_tracking(reports_dir / "tracking_history.json")
    regime_map = load_regime_map(reports_dir)

    # 分组: (horizon_key, score_bucket_label, regime) → returns
    groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for rec in tracking:
        score = rec.get("recommendation_score")
        if score is None:
            continue
        rec_date = str(rec.get("recommended_date", ""))
        regime = resolve_regime(rec_date, regime_map)
        for h_key, h_label, field in DIAG_HORIZONS:
            ret = rec.get(field)
            if ret is None:
                continue
            if not (RETURN_MIN <= ret <= RETURN_MAX):
                continue
            for bucket_label, bucket_fn in SCORE_BUCKETS:
                if bucket_fn(score):
                    groups[(h_key, bucket_label, regime)].append(ret)
                    break

    # 打印表格 (每个 regime 一张)
    print("\n" + "=" * 100)
    print("多周期诊断: 6 horizon × 3 分桶 × 3 regime = 54 格 (Phase 2)")
    print("=" * 100)
    for regime in REGIMES:
        print(f"\n=== {regime} regime ===")
        print(f"{'周期':<6} | {'Score':<9} | {'n':<4} | {'胜率':<7} | {'median':<9} | {'mean':<9} | {'上行':<8} | {'下行':<8} | {'盈亏比':<7} | {'5th pct':<9}")
        print("-" * 100)
        for h_key, h_label, _ in DIAG_HORIZONS:
            for bucket_label, _ in SCORE_BUCKETS:
                returns = groups.get((h_key, bucket_label, regime), [])
                m = compute_metrics(returns)
                n = m["n"]
                wr = f"{m['winrate']:.0%}" if m["winrate"] is not None else "—"
                if 10 <= n < 20:
                    wr += " ⚠"
                elif 0 < n < 10:
                    wr += " ❌"
                med = fmt_pct(m["median"], n)
                avg = fmt_pct(m["mean"], n)
                up = fmt_pct(m["upside"], n)
                dn = fmt_pct(m["downside"], n)
                rr = fmt_ratio(m["rr_ratio"], n)
                p5 = fmt_pct(m["p5"], n) if n >= 20 else "—"
                print(f"{h_label:<6} | {bucket_label:<9} | {n:<4} | {wr:<7} | {med:<9} | {avg:<9} | {up:<8} | {dn:<8} | {rr:<7} | {p5:<9}")

    # Sanity check: T+30 聚合全分桶 vs R-5.A baseline
    print("\n" + "=" * 100)
    print("Sanity check: T+30 聚合全 score 桶 vs R-5.A REGIME_HISTORICAL_WINRATES")
    print("=" * 100)
    for regime in ["normal", "crisis", "risk_off"]:
        all_t30 = []
        for rec in tracking:
            rec_date = str(rec.get("recommended_date", ""))
            if resolve_regime(rec_date, regime_map) != regime:
                continue
            ret = rec.get("next_30day_return")
            if ret is None or not (RETURN_MIN <= ret <= RETURN_MAX):
                continue
            all_t30.append(ret)
        if not all_t30:
            print(f"  {regime}: 无数据")
            continue
        wr = sum(1 for r in all_t30 if r > 0) / len(all_t30)
        baseline = R5A_BASELINE[regime]
        delta = wr - baseline["winrate"]
        flag = "✓" if abs(delta) <= 0.05 else "⚠ 偏离>5pp"
        print(f"  {regime}: 本次 winrate={wr:.1%} (n={len(all_t30)}) | R-5.A={baseline['winrate']:.1%} (n={baseline['n']}) | Δ={delta:+.1%} {flag}")

    # 文字结论 (基于数据, 不预设)
    print("\n" + "=" * 100)
    print("文字结论 (回答 Q1-Q4)")
    print("=" * 100)
    print("TODO: 基于上面表格人工填入结论。脚本不自动下结论 (避免 p-hack)。")
    print("参考 spec 决策路径:")
    print("  Q1: 某个 horizon+score median > +3% 且 n>=20 → B 有意义")
    print("  Q2: 短周期 vs 长周期胜率差异 < 5pp → D 徒劳")
    print("  Q3: score 高低在任何 horizon 都不能预测胜负 → score 体系需重设")
    print("  Q4: 盈亏比 > 1.5 且 n>=20 → C 仓位建议有意义")
    print("  所有 54 格 median <= 0 → 转 regime-gating (R-5.F) 或定位调整")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑脚本**

Run: `uv run python scripts/_multi_horizon_diagnosis.py`
Expected: 打印 4 张表（normal/crisis/risk_off/unknown）+ sanity check + 结论模板

- [ ] **Step 3: 检查 sanity check 是否通过**

读输出里的 "Sanity check" 段。若 normal/crisis/risk_off 三行都是 ✓（Δ ≤ 5pp），数据一致性验证通过。若任一行 ⚠，排查 regime 关联逻辑或样本集差异。

- [ ] **Step 4: 人工填写文字结论**

基于表格数据，回答 Q1-Q4。把结论写在脚本输出末尾或单独文件，**与用户一起讨论决定 A/B/C/D 哪些值得做**。

- [ ] **Step 5: 删除脚本**

Run: `rm scripts/_multi_horizon_diagnosis.py`

- [ ] **Step 6: commit 删除**

```bash
git rm scripts/_multi_horizon_diagnosis.py 2>/dev/null || true
git commit --allow-empty -m "chore: 移除一次性多周期诊断脚本 (Phase 2 完成)

诊断结论 (基于 293 条记录 × 6 horizon × 3 分桶 × 3 regime):
<在此填入 Q1-Q4 简短结论>

下一步: <在此填入决定 — 做 A/B/C/D 中的哪些, 或转 regime-gating>

先例: commit 6de3935f (R-5.A 一次性脚本同样模式)."
```

---

## Self-Review Checklist

- [x] **Spec 覆盖**: Phase 1（DEFAULT_HORIZONS 扩展、TrackingRecord、verify、calibration、btst bridge、回填）= Task 1-5；Phase 2（54 格诊断 + sanity check + 文字结论）= Task 6；8 指标 = `compute_metrics`；分桶逻辑 = `SCORE_BUCKETS`；诚实约束 = 脚本顶部注释 + `compute_metrics` 的 n<20 5th pct 隐藏；sanity check = Task 6 Step 3
- [x] **占位符扫描**: 无 TBD/TODO（脚本里的 "TODO 人工填入结论" 是有意的——避免 p-hack，不自动下结论）
- [x] **类型一致**: `next_15day_return` / `next_25day_return` / `day_15` / `day_25` / `overall_t15_win_rate` / `t15_win_rate` 跨 Task 1-4 命名一致
- [x] **TDD**: Task 1-4 每个改动都有 RED 测试先行
- [x] **commit**: Task 5 commit Phase 1；Task 6 commit 删除脚本

## 已知实现注意事项（writing-plans 阶段补充，不污染 spec）

- **多周期自相关**: T+5/T+10/T+15 共享数据，跨 horizon 对比不能当独立检验；诊断非假设检验，不阻碍看趋势
- **regime 时滞性**: 用推荐日 regime 当整个持有期 regime 的简化；R-5.D 已用此假设
- **293 条 vs R-5.D 189 只**: tracking_history 含 2024 记录，R-5.D 用子集；sanity check 会暴露差异
- **重复样本**: 连续推荐同一只票会被多次计算，影响 n 真实性；Phase 2 结论需标注
- **小样本 CI 宽**: n=20 胜率 50% 的 95% CI 是 [28%, 72%]；⚠ 标注已足够，不引入 CI 计算
