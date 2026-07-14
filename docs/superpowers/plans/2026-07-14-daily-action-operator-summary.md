# Daily Action Operator Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw, empty daily-action output with a Chinese operator summary that distinguishes a healthy no-signal day, a safety block, and an actionable plan while preserving verbose audit codes.

**Architecture:** Keep all selection, manifest, ledger, and execution behavior unchanged. Add pure rendering helpers and static reason metadata beside `render_daily_action_v2`, then pass the CLI's existing `--verbose` flag into the renderer so raw diagnostic details are presentation-only.

**Tech Stack:** Python 3.13, dataclasses, pytest, unittest.mock, existing CLI dispatcher and offensive daily-action modules.

## Global Constraints

- Do not change selection, ledger, fill, exit, manifest-gate, JSON, or SQLite behavior.
- All empty operator sections render `无`.
- A healthy no-signal result must never look like a safety block.
- `regime_authorization_evidence_unavailable` is a non-blocking warning; it must not hide a valid 10% plan.
- Unknown reason codes are treated as blocking and retain their raw value in verbose diagnostics.
- `SHADOW ONLY` remains explicit and never looks like a real exit instruction.
- Non-verbose output contains Chinese conclusion, cause, impact, and action; verbose output additionally contains raw reason codes and per-ticker manifest details.

---

## File Structure

- Modify `src/screening/offensive/daily_action.py`: own reason-to-operator-copy mapping, summary state classification, empty-section rendering, and the `verbose=False` renderer API.
- Modify `src/cli/dispatcher.py`: pass CLI verbosity into the renderer; no business object receives display state.
- Modify `tests/offensive/test_daily_action_manifest_gate.py`: cover blocking and warning semantics, reason ordering, unknown-code fallback, and verbose diagnostics.
- Modify `tests/offensive/test_daily_action_v2_integration.py`: cover empty sections, healthy no-signal output, plan count, source labels, and shadow wording.
- Modify `tests/test_cli_dispatcher.py`: prove `--verbose` reaches the renderer and default invocation remains non-verbose.

### Task 1: Render the operator summary and explicit empty states

**Files:**
- Modify: `src/screening/offensive/daily_action.py:634-691`
- Test: `tests/offensive/test_daily_action_manifest_gate.py`
- Test: `tests/offensive/test_daily_action_v2_integration.py`

**Interfaces:**
- Consumes: `DailyActionV2Run`, `DailyActionRun.block_reasons`, `DailyActionV2Run.plans`, and existing lifecycle/source collections.
- Produces: `render_daily_action_v2(run: DailyActionV2Run, *, verbose: bool = False) -> str` and private pure helpers `_operator_reason`, `_render_operator_summary`, `_append_section`.

- [ ] **Step 1: Write failing blocking-summary tests**

Add tests that construct the existing `DailyActionV2Run` fixtures and assert the exact operator-facing contract:

```python
def test_missing_manifest_renders_actionable_chinese_summary_and_verbose_code(
    service, candidates
):
    from src.screening.offensive.daily_action import DailyActionV2Run, render_daily_action_v2

    view = service.run(SIGNAL_DATE, candidates, manifest=None)
    text = render_daily_action_v2(
        DailyActionV2Run(view, (), view.open_positions, (), ()), verbose=True
    )

    assert "结论：⛔ 今日未生成新的次日买入计划" in text
    assert "原因：缺少当前交易日的健康数据清单" in text
    assert "影响：不会创建新买入计划；已有持仓仍按既定规则管理" in text
    assert "uv run python src/main.py --auto" in text
    assert "block_reasons=healthy_manifest_missing" in text
    assert "block_reason=" not in text
```

Add a multiple-reason assertion using the existing calendar-plus-manifest fixture. It must preserve first-seen order, render each Chinese explanation once, and contain only the plural raw diagnostic line in verbose mode.

- [ ] **Step 2: Run the blocking tests and verify RED**

Run:

```bash
uv run pytest tests/offensive/test_daily_action_manifest_gate.py \
  -k 'missing_manifest_renders or calendar_and_manifest_warnings' -v
```

Expected: FAIL because the renderer still emits raw `block_reason`/`block_reasons` lines and has no operator summary.

- [ ] **Step 3: Write failing warning, healthy, plan, and empty-section tests**

Add focused tests with these assertions:

```python
assert "结论：✅ 当前有 1 个次日买入计划" in warning_with_plan_text
assert "安全降级：市场状态加仓缺少可验证授权证据" in warning_with_plan_text
assert "今日未生成" not in warning_with_plan_text

assert "结论：ℹ️ 今日无符合条件的次日买入信号（系统运行正常）" in healthy_empty_text
assert "参考价计划:\n  无" in healthy_empty_text
assert "模拟成交（synthetic_open）:\n  无" in healthy_empty_text
assert "确认成交（broker_confirmed）:\n  无" in healthy_empty_text
assert "退出挑战者（SHADOW ONLY，不改变默认退出；不触发交易、仓位或组合上限）:\n  无" in healthy_empty_text

assert "原因：系统安全护栏触发" in unknown_reason_text
assert "block_reasons=future_guard_code" in unknown_verbose_text
```

Also update existing raw-code assertions to call `render_daily_action_v2(..., verbose=True)`. Keep source-label and shadow-only assertions unchanged.

- [ ] **Step 4: Run the new rendering tests and verify RED**

Run:

```bash
uv run pytest tests/offensive/test_daily_action_manifest_gate.py \
  tests/offensive/test_daily_action_v2_integration.py \
  -k 'render or output_distinguishes or surfaces_every' -v
```

Expected: FAIL on missing summary copy, incorrect warning classification, and empty headings.

- [ ] **Step 5: Implement reason metadata and summary classification**

Add immutable module-level metadata near the renderer. Keep it presentation-only:

```python
_OPERATOR_REASON_DETAILS: dict[str, tuple[str, str]] = {
    "healthy_manifest_missing": (
        "缺少当前交易日的健康数据清单",
        "收盘后先运行：uv run python src/main.py --auto；成功后重新运行 daily-action",
    ),
    "manifest_identity_mismatch": (
        "数据清单与当前交易日或运行批次不匹配",
        "重新运行 --auto，不要混用旧报告与新缓存",
    ),
    "manifest_invalid": (
        "数据清单结构不完整或无法验证",
        "重新运行 --auto；若仍出现，检查 auto 输出中的数据质量错误",
    ),
    "calendar_unavailable": (
        "权威交易日历不足，无法确定精确入场日或持有期",
        "更新交易日历或缓存后重跑，禁止猜测自然日",
    ),
    "regime_authorization_evidence_unavailable": (
        "市场状态加仓缺少可验证授权证据",
        "计划仍按单票 10% 安全上限执行，无需手工放大仓位",
    ),
}
_NON_BLOCKING_OPERATOR_REASONS = frozenset(
    {"regime_authorization_evidence_unavailable"}
)


def _operator_reason(code: str) -> tuple[str, str]:
    return _OPERATOR_REASON_DETAILS.get(
        code,
        ("系统安全护栏触发", "保留诊断代码并检查本次 --auto 与交易日数据"),
    )
```

Implement `_render_operator_summary(run)` so it:

1. deduplicates `block_reasons` in first-seen order;
2. classifies reasons outside `_NON_BLOCKING_OPERATOR_REASONS` as blocking;
3. chooses plan-success first, then blocking-without-plan, then healthy-no-signal;
4. deduplicates repeated suggestions;
5. renders warnings separately without invalidating existing plans.

Use `len(run.plans)` for the displayed actionable plan count because `run_daily_action_v2` already combines newly created and same-signal persisted plans.

- [ ] **Step 6: Implement explicit sections and verbose diagnostics**

Change the signature and section construction:

```python
def render_daily_action_v2(
    run: DailyActionV2Run, *, verbose: bool = False
) -> str:
    lines = ["每日动作 v2（模拟台账）", ""]
    lines.extend(_render_operator_summary(run))
    lines.append("")
```

For each always-visible major section, append `  无` when its filtered collection is empty. Preserve the existing details when non-empty. For the shadow section, retain the full `SHADOW ONLY` heading and append `  无` when there are no open positions.

Only when `verbose` is true append:

```python
lines.append("")
lines.append("技术诊断:")
if run.service_run.block_reasons:
    lines.append("  block_reasons=" + ",".join(run.service_run.block_reasons))
else:
    lines.append("  block_reasons=无")
```

Move existing `manifest_blocked_tickers` and `manifest_gate_blocks` output inside that verbose block. Remove the duplicate singular `block_reason=` line entirely.

- [ ] **Step 7: Run focused renderer tests and verify GREEN**

Run:

```bash
uv run pytest tests/offensive/test_daily_action_manifest_gate.py \
  tests/offensive/test_daily_action_v2_integration.py \
  tests/offensive/test_exit_shadow_integration.py -q
```

Expected: all selected tests PASS; no existing source or shadow semantic assertion regresses.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/screening/offensive/daily_action.py \
  tests/offensive/test_daily_action_manifest_gate.py \
  tests/offensive/test_daily_action_v2_integration.py
git commit -m "feat: clarify daily action operator output"
```

### Task 2: Wire CLI verbosity and verify the real command surface

**Files:**
- Modify: `src/cli/dispatcher.py:1049`
- Test: `tests/test_cli_dispatcher.py:240-320`

**Interfaces:**
- Consumes: Task 1 `render_daily_action_v2(run, *, verbose=False)`.
- Produces: `_resolve_daily_action(argv, ...)` passes `verbose="--verbose" in argv` without modifying scan, service, or ledger inputs.

- [ ] **Step 1: Write failing dispatcher propagation tests**

Patch the renderer at its import source and capture the call:

```python
def test_daily_action_passes_verbose_only_to_renderer(self) -> None:
    from datetime import date
    from src.screening.offensive.daily_action import DailyActionScan

    with (
        tempfile.TemporaryDirectory() as tmp,
        patch(
            "src.screening.offensive.daily_action.scan_daily_action_candidates",
            return_value=DailyActionScan(date(2026, 7, 10), (), ()),
        ),
        patch(
            "src.screening.offensive.daily_action.render_daily_action_v2",
            return_value="rendered",
        ) as renderer,
        patch("builtins.print"),
    ):
        dispatcher._resolve_daily_action(
            ["--daily-action", "--verbose"],
            open_sessions=(date(2026, 7, 10), date(2026, 7, 13)),
            ledger_path=Path(tmp) / "v2.sqlite3",
        )

    self.assertTrue(renderer.call_args.kwargs["verbose"])
```

Add the sibling default test and assert `renderer.call_args.kwargs["verbose"] is False`.

- [ ] **Step 2: Run dispatcher tests and verify RED**

Run:

```bash
uv run pytest tests/test_cli_dispatcher.py \
  -k 'daily_action_passes_verbose_only_to_renderer or daily_action_default_renderer' -v
```

Expected: FAIL because `_resolve_daily_action` does not pass `verbose`.

- [ ] **Step 3: Pass verbosity at the presentation boundary**

Replace the final print call with:

```python
        run = run_daily_action_v2(service, scan, manifest)
        print(render_daily_action_v2(run, verbose="--verbose" in argv))
```

Do not pass `argv` or `verbose` into `DailyActionService`, `run_daily_action_v2`, the ledger repository, or manifest loader.

- [ ] **Step 4: Run dispatcher tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_cli_dispatcher.py \
  tests/offensive/test_daily_action_v2_integration.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 5: Run full scoped regression and smoke output**

Run:

```bash
uv run pytest tests/offensive/ tests/test_cli_dispatcher.py \
  tests/test_main_auto_cache_refresh.py -q
uv run python src/main.py --daily-action --verbose
uv run python -m compileall -q src
git diff --check
```

Expected:

- pytest exits 0;
- the real command prints a Chinese conclusion, reason, impact, action, explicit `无` sections, and a verbose raw code;
- compileall and diff-check exit 0;
- the command does not create duplicate plans or mutate legacy v1 paper-trading files.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/cli/dispatcher.py tests/test_cli_dispatcher.py
git commit -m "feat: expose verbose daily action diagnostics"
```
