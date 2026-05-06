# BTST Admission Edge Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a clear replay verdict for `btst_admission_edge_recovery` versus the current BTST baseline before any further strategy logic changes.

**Architecture:** Reuse the existing multi-window and weekly validation scripts instead of adding new BTST logic. First compare `btst_admission_edge_recovery` against `btst_precision_v2` across replay windows, then run a week-level follow-up only if the profile is not clearly negative, and finally summarize whether the next cycle should be rollout review, weak-regime retuning, or stop.

**Tech Stack:** Python 3.13 via `uv run`, existing scripts under `scripts/`, replay artifacts under `data/reports/`, pytest for any script regressions if needed

---

## File Structure

- Read: `docs/superpowers/specs/2026-05-06-btst-admission-edge-validation-design.md` — source-of-truth design for this validation cycle.
- Read: `scripts/analyze_btst_multi_window_profile_validation.py` — existing baseline-vs-variant replay comparison entry point.
- Read: `scripts/analyze_btst_weekly_validation.py` — existing weekly outcome summarizer.
- Read: `scripts/optimize_profile.py` — fallback bounded parameter-search entry point if the fixed-profile verdict is mixed.
- Output: `data/reports/btst_admission_edge_recovery_multi_window_validation.json`
- Output: `data/reports/btst_admission_edge_recovery_multi_window_validation.md`
- Output: `data/reports/btst_admission_edge_recovery_weekly_validation.json`
- Output: `data/reports/btst_admission_edge_recovery_weekly_validation.md`

### Task 1: Run the fixed-profile multi-window comparison

**Files:**
- Read: `scripts/analyze_btst_multi_window_profile_validation.py`
- Output: `data/reports/btst_admission_edge_recovery_multi_window_validation.json`
- Output: `data/reports/btst_admission_edge_recovery_multi_window_validation.md`

- [ ] **Step 1: Verify replay windows exist**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
ls -d data/reports/paper_trading_window* | head
```

Expected: At least one `data/reports/paper_trading_window*` directory is listed.

- [ ] **Step 2: Run the multi-window validation command**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
uv run python scripts/analyze_btst_multi_window_profile_validation.py \
  --reports-root data/reports \
  --report-name-contains paper_trading_window \
  --baseline-profile btst_precision_v2 \
  --variant-profile btst_admission_edge_recovery \
  --next-high-hit-threshold 0.02 \
  --output-json data/reports/btst_admission_edge_recovery_multi_window_validation.json \
  --output-md data/reports/btst_admission_edge_recovery_multi_window_validation.md
```

Expected: Command exits successfully and writes the two output artifacts.

- [ ] **Step 3: Confirm the output artifacts were written**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
ls -l \
  data/reports/btst_admission_edge_recovery_multi_window_validation.json \
  data/reports/btst_admission_edge_recovery_multi_window_validation.md
```

Expected: Both files exist and have non-zero size.

- [ ] **Step 4: Read the decision counts and recommendation**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
python - <<'PY'
import json
from pathlib import Path
path = Path("data/reports/btst_admission_edge_recovery_multi_window_validation.json")
payload = json.loads(path.read_text(encoding="utf-8"))
print({
    "keep_baseline_count": payload.get("keep_baseline_count"),
    "variant_supports_t1_count": payload.get("variant_supports_t1_count"),
    "variant_improves_t2_only_count": payload.get("variant_improves_t2_only_count"),
    "mixed_count": payload.get("mixed_count"),
    "recommendation": payload.get("recommendation"),
})
PY
```

Expected: A concise JSON summary prints with a non-empty `recommendation`.

- [ ] **Step 5: Commit the generated validation artifacts**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
git add data/reports/btst_admission_edge_recovery_multi_window_validation.json data/reports/btst_admission_edge_recovery_multi_window_validation.md
git commit -m "chore: add BTST admission edge multi-window validation"
```

### Task 2: Run a weekly follow-up only if the fixed-profile comparison is not clearly negative

**Files:**
- Read: `scripts/analyze_btst_weekly_validation.py`
- Output: `data/reports/btst_admission_edge_recovery_weekly_validation.json`
- Output: `data/reports/btst_admission_edge_recovery_weekly_validation.md`

- [ ] **Step 1: Inspect the multi-window recommendation before proceeding**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("data/reports/btst_admission_edge_recovery_multi_window_validation.json").read_text(encoding="utf-8"))
print(payload.get("recommendation", ""))
PY
```

Expected: If the message clearly says the baseline should remain default with no offsetting T+1 improvement, stop here and skip Task 2. Otherwise continue.

- [ ] **Step 2: Choose the weekly window from the strongest or most relevant adjacent dates**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("data/reports/btst_admission_edge_recovery_multi_window_validation.json").read_text(encoding="utf-8"))
for row in payload.get("rows", [])[:10]:
    print(row["report_label"], row["trade_dates"], row["window_recommendation"])
PY
```

Expected: Pick the most relevant consecutive week represented by the strongest positive or most informative mixed window.

- [ ] **Step 3: Run weekly validation for that week**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
uv run python scripts/analyze_btst_weekly_validation.py \
  --reports-root data/reports \
  --start-date 2026-04-13 \
  --end-date 2026-04-17 \
  --next-high-hit-threshold 0.02 \
  --output-json data/reports/btst_admission_edge_recovery_weekly_validation.json \
  --output-md data/reports/btst_admission_edge_recovery_weekly_validation.md
```

Expected: Command exits successfully and writes weekly JSON/Markdown outputs. If the selected week differs, replace the dates before running.

- [ ] **Step 4: Read the weekly recommendation and surface summary**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("data/reports/btst_admission_edge_recovery_weekly_validation.json").read_text(encoding="utf-8"))
print({
    "trade_dates": payload.get("trade_dates"),
    "missing_trade_dates": payload.get("missing_trade_dates"),
    "selected_report_count": payload.get("selected_report_count"),
    "tradeable_surface": payload.get("weekly_surface_summaries", {}).get("tradeable"),
    "recommendation": payload.get("recommendation"),
})
PY
```

Expected: The summary prints with an explicit weekly `recommendation`.

- [ ] **Step 5: Commit the weekly validation artifacts**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
git add data/reports/btst_admission_edge_recovery_weekly_validation.json data/reports/btst_admission_edge_recovery_weekly_validation.md
git commit -m "chore: add BTST admission edge weekly validation"
```

### Task 3: Escalate to a bounded parameter search only if the fixed-profile verdict is mixed

**Files:**
- Read: `scripts/optimize_profile.py`
- Output: `data/reports/param_search_btst_admission_edge_recovery.json`

- [ ] **Step 1: Confirm the fixed-profile verdict is mixed rather than clearly positive or clearly negative**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("data/reports/btst_admission_edge_recovery_multi_window_validation.json").read_text(encoding="utf-8"))
print({
    "keep_baseline_count": payload.get("keep_baseline_count"),
    "variant_supports_t1_count": payload.get("variant_supports_t1_count"),
    "mixed_count": payload.get("mixed_count"),
})
PY
```

Expected: Only continue if the verdict is mixed enough to justify bounded tuning.

- [ ] **Step 2: Run a narrow parameter search on regime-admission relief only**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
uv run python scripts/optimize_profile.py \
  --profile btst_admission_edge_recovery \
  --objective edge \
  --reports-root data/reports \
  --weekly-start-date 2026-04-13 \
  --weekly-end-date 2026-04-17 \
  --grid-params regime_admission_recovery_normal_trade_relief=0.003,0.005,0.007,0.009 \
  --grid-params regime_admission_recovery_aggressive_trade_relief=0.008,0.010,0.012 \
  --checkpoint-path data/reports/param_search_btst_admission_edge_recovery_checkpoint.json
```

Expected: Search finishes and writes a parameter-search payload/report under `data/reports/`. If the multi-window verdict is clearly positive or clearly negative, skip this task.

- [ ] **Step 3: Read the top-ranked parameter combinations**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
python - <<'PY'
import json
from pathlib import Path
paths = sorted(Path("data/reports").glob("param_search_btst_admission_edge_recovery*.json"))
if not paths:
    raise SystemExit("No parameter search payload found")
payload = json.loads(paths[-1].read_text(encoding="utf-8"))
print(payload.get("best_params"))
print(payload.get("best_metrics"))
PY
```

Expected: A concrete best-parameter summary prints, or the command is skipped because Task 3 was not needed.

- [ ] **Step 4: Commit the bounded search artifacts if Task 3 ran**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery
git add data/reports/param_search_btst_admission_edge_recovery*.json data/reports/param_search_btst_admission_edge_recovery*.md data/reports/param_search_btst_admission_edge_recovery_checkpoint.json
git commit -m "chore: add BTST admission edge bounded search artifacts"
```
