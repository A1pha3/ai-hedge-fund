# BTST System Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the BTST reporting system so the generated documents have real Gamma market-context artifacts, compact Alpha statistical scorecards, and a less repetitive Beta execution layer.

**Architecture:** Treat this as three coordinated workstreams that meet in `scripts/generate_btst_doc_bundle.py`. First, strengthen the upstream market-context artifacts so Gamma has structured inputs instead of repeated `artifacts not available`; second, render Alpha statistics into compact per-ticket scorecards; third, simplify Beta checklist rendering so execution guidance is dense, non-repetitive, and action-first.

**Tech Stack:** Python 3.12, existing BTST scripts under `scripts/`, BTST reporting helpers under `src/paper_trading/_btst_reporting/`, pytest-based script tests under `tests/scripts/` and focused reporting tests under `tests/`.

---

### Task 1: Add a Gamma-ready market / sector / 赚钱效应 artifact

**Files:**
- Modify: `scripts/run_btst_nightly_control_tower.py`
- Modify: `scripts/btst_nightly_payload_helpers.py`
- Modify: `scripts/btst_nightly_render_helpers.py`
- Modify: `scripts/analyze_catalyst_theme_frontier.py`
- Test: `tests/test_btst_control_tower_scripts.py`
- Test: `tests/scripts/test_analyze_catalyst_theme_frontier_script.py`

- [ ] **Step 1: Write the failing Gamma artifact test**

Add a test that proves the current control-tower output does not expose enough structured market-context fields for the new report layer:

```python
def test_control_tower_emits_gamma_market_context_fields(tmp_path):
    summary = {
        "market_gate": "halt",
        "regime_gate_level": "risk_off",
        "breadth_ratio": 0.37,
        "limit_up_count": 91,
        "limit_down_count": 12,
        "position_scale": 0.75,
    }

    payload = build_btst_nightly_payload(
        trade_date="20260618",
        summary=summary,
        catalyst_theme_frontier_summary={
            "primary_theme": "AI 算力",
            "theme_state": "有线索但未扩散",
            "promoted_shadow_count": 0,
        },
    )

    gamma = payload["gamma_market_context"]
    assert gamma["market_gate"] == "halt"
    assert gamma["primary_theme"] == "AI 算力"
    assert gamma["theme_state"] == "有线索但未扩散"
    assert gamma["money_effect_state"] == "artifacts_not_available"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_control_tower_scripts.py -k gamma_market_context_fields -q
```

Expected: FAIL because `gamma_market_context` or one of its required keys is missing.

- [ ] **Step 3: Implement the minimal payload extension**

Add a dedicated Gamma payload in `scripts/btst_nightly_payload_helpers.py`:

```python
gamma_market_context = {
    "market_gate": summary.get("market_gate"),
    "regime_gate_level": summary.get("regime_gate_level"),
    "breadth_ratio": summary.get("breadth_ratio"),
    "limit_up_count": summary.get("limit_up_count"),
    "limit_down_count": summary.get("limit_down_count"),
    "position_scale": summary.get("position_scale"),
    "primary_theme": frontier_summary.get("primary_theme"),
    "theme_state": frontier_summary.get("theme_state"),
    "promoted_shadow_count": frontier_summary.get("promoted_shadow_count", 0),
    "money_effect_state": frontier_summary.get("money_effect_state", "artifacts_not_available"),
}
```

Render the same fields in `scripts/btst_nightly_render_helpers.py` and ensure `analyze_catalyst_theme_frontier.py` surfaces `primary_theme`, `theme_state`, and `money_effect_state` without inventing unsupported commentary.

- [ ] **Step 4: Run the Gamma artifact tests**

Run:

```bash
uv run pytest tests/test_btst_control_tower_scripts.py -k gamma_market_context_fields -q
uv run pytest tests/scripts/test_analyze_catalyst_theme_frontier_script.py -q
```

Expected: PASS.


### Task 2: Render Alpha scorecards as compact tables instead of scattered prose

**Files:**
- Modify: `scripts/generate_btst_doc_bundle.py`
- Modify: `src/paper_trading/_btst_reporting/brief_rendering.py`
- Modify: `src/paper_trading/_btst_reporting/premarket_rendering.py`
- Test: `tests/scripts/test_generate_btst_doc_bundle_script.py`

- [ ] **Step 1: Write the failing Alpha scorecard rendering test**

Add a test that expects a compact table-oriented Alpha block:

```python
def test_doc_bundle_renders_alpha_scorecard_table(tmp_path):
    result = generate_btst_doc_bundle(
        "20260618",
        output_dir=tmp_path,
        refresh_early_runner=False,
    )
    text = (tmp_path / "BTST-LLM-20260618.md").read_text(encoding="utf-8")
    assert "## 胜率/赔率诊断卡（Alpha）" in text
    assert "| 股票 | 样本量 | 收缩后胜率 | 盈亏比 | 分化标签 |" in text
    assert "688008 澜起科技" in text
```

- [ ] **Step 2: Run the Alpha rendering test to verify it fails**

Run:

```bash
uv run pytest tests/scripts/test_generate_btst_doc_bundle_script.py -k alpha_scorecard_table -q
```

Expected: FAIL because the current doc bundle emits paragraphs, not the required table.

- [ ] **Step 3: Add a reusable Alpha scorecard renderer**

In `src/paper_trading/_btst_reporting/brief_rendering.py`, add a helper shaped like:

```python
def render_alpha_scorecard_rows(entries: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 股票 | 样本量 | 收缩后胜率 | 盈亏比 | 分化标签 | 当前层级 |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for entry in entries:
        lines.append(
            f"| {entry['ticker']} {entry['name']} | {entry['sample_size']} | "
            f"{entry['shrunk_win_rate']:.2%} | {entry['payoff_ratio']:.2f} | "
            f"{entry['divergence_label']} | {entry['lane_label']} |"
        )
    return lines
```

Wire that into `scripts/generate_btst_doc_bundle.py` so `BTST-LLM-YYYYMMDD.md` and `BTST-YYYYMMDD-EXEC-CHECKLIST.md` use the same compact Alpha table instead of re-spreading the same stats across multiple bullet lists.

- [ ] **Step 4: Run the Alpha doc-bundle tests**

Run:

```bash
uv run pytest tests/scripts/test_generate_btst_doc_bundle_script.py -k "alpha_scorecard_table or generate_btst_doc_bundle" -q
```

Expected: PASS, and the Alpha section is table-based.


### Task 3: Slim the Beta execution layer and enforce single-responsibility docs

**Files:**
- Modify: `scripts/generate_btst_doc_bundle.py`
- Modify: `src/paper_trading/_btst_reporting/premarket_rendering.py`
- Modify: `src/paper_trading/_btst_reporting/brief_rendering.py`
- Test: `tests/scripts/test_generate_btst_doc_bundle_script.py`

- [ ] **Step 1: Write the failing Beta deduplication test**

Add a test that proves the checklist duplicates too much prose from the LLM document:

```python
def test_exec_checklist_uses_compact_beta_matrix_without_redundant_prose(tmp_path):
    generate_btst_doc_bundle("20260618", output_dir=tmp_path, refresh_early_runner=False)
    checklist = (tmp_path / "BTST-20260618-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    assert "## 执行触发/取消/升级/降级矩阵（Beta）" in checklist
    assert "| 股票 | 触发条件 | 取消条件 | 观察升级条件 | 降级条件 |" in checklist
    assert checklist.count("等待盘中延续确认后再执行") <= 2
```

- [ ] **Step 2: Run the Beta dedupe test to verify it fails**

Run:

```bash
uv run pytest tests/scripts/test_generate_btst_doc_bundle_script.py -k beta_matrix_without_redundant_prose -q
```

Expected: FAIL because the current checklist repeats too much explanatory prose.

- [ ] **Step 3: Replace repeated prose with a single action matrix**

Implement a compact matrix in `src/paper_trading/_btst_reporting/premarket_rendering.py`:

```python
columns = [
    "股票",
    "触发条件",
    "取消条件",
    "观察升级条件",
    "降级条件",
    "最大滑点",
    "最大参与率",
    "时间窗",
]
```

Render one row per formal candidate, and keep long narrative explanations only in `BTST-LLM-YYYYMMDD.md`. The checklist should become a morning action card, not a second copy of the same explanation.

- [ ] **Step 4: Run the Beta checklist tests**

Run:

```bash
uv run pytest tests/scripts/test_generate_btst_doc_bundle_script.py -k "beta_matrix_without_redundant_prose or generate_btst_doc_bundle" -q
```

Expected: PASS, with a denser checklist and less repeated prose.


### Task 4: End-to-end smoke verification on the proven 20260618 artifact set

**Files:**
- Verify output: `outputs/202606/20260618_scheme_a/`
- Verify output: `outputs/202606/20260618_profile_compare/`
- Test: `tests/scripts/test_generate_btst_doc_bundle_script.py`

- [ ] **Step 1: Rebuild the document bundle from existing artifacts**

Run:

```bash
uv run python scripts/run_btst_next_day_package.py \
  --signal-date 20260618 \
  --output-dir outputs/202606/20260618_scheme_a \
  --reuse-existing
```

Expected: success, no new upstream blocker, files refreshed in place.

- [ ] **Step 2: Rebuild the profile compare bundle**

Run:

```bash
uv run python scripts/generate_btst_doc_bundle.py \
  --signal-date 20260618 \
  --compare-profiles conservative aggressive \
  --output-dir outputs/202606/20260618_profile_compare
```

Expected: success, compare bundle regenerated.

- [ ] **Step 3: Verify the final outputs contain the new structure**

Run:

```bash
rg -n "胜率/赔率诊断卡（Alpha）|执行触发/取消/升级/降级矩阵（Beta）|大盘-板块-赚钱效应环境卡（Gamma）|money_effect_state|frontier promoted|artifacts not available" \
  outputs/202606/20260618_scheme_a \
  outputs/202606/20260618_profile_compare
```

Expected: matches in the core documents, the compare bundle, and the regenerated Gamma narrative.
