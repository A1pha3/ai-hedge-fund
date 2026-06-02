# BTST Single-Date Input + Next-Trade-Date Output Directory Design

- **Date:** 2026-06-02
- **Topic:** Reduce BTST daily prompting friction by requiring only `signal_date`, while standardizing output directories by `next_trade_date` (execution day) and recording both dates in a manifest.
- **Recommended direction:** **Single required date + SSE trading-calendar inference + explicit directory naming + strict validation**.

## 1. Problem Statement

BTST daily runs conceptually bind two different dates:

- **`signal_date`**: the trading day whose close data is used to generate signals (收盘/信号日)
- **`next_trade_date`**: the next execution trading day for the plan (目标交易日/执行日)

Today, users often have to type both dates and manually maintain a directory path, which causes avoidable errors:

1. Weekend/holiday gaps (Friday close → Monday execution) make the two-date mental model easy to get wrong.
2. Output directories are not self-describing, so artifacts can be misread or misfiled.
3. Follow-up cards (opening watch / premarket execution) must stay aligned with the main bundle’s execution contract, and misfiled dates break that alignment.

## 2. Goals and Non-Goals

### Goals

1. **Single required date input**: user must only provide `signal_date` in the daily prompt.
2. **Correct next-trading-day inference** for A-share (SSE) trading calendar, including weekends/holidays.
3. **Strict validation**: if `signal_date` is not an SSE open day, fail fast (no silent shifting).
4. **Output directory is self-describing**: directory name must encode both `next_trade_date` and `signal_date`.
5. **Durable traceability**: emit `manifest.json` into the output directory to record resolved dates and provenance.

### Non-Goals

1. Do not change selection logic, ranking logic, or execution contract semantics.
2. Do not add US-market calendars or automatic ticker-market detection in this iteration.
3. Do not provide backward-compat directory compatibility or migration tooling.

## 3. Approaches Considered

### Approach A: Keep two dates in prompts

- **Pros**: minimal change.
- **Cons**: doesn’t solve weekend/holiday errors; keeps prompts verbose; still easy to misfile outputs.

### Approach B: Single required `signal_date` + infer `next_trade_date` (**Recommended**)

- **Pros**: simplest daily UX; eliminates the most common error class; system can enforce correctness.
- **Cons**: requires a deterministic trading-calendar resolver.

### Approach C: Only input `next_trade_date` and infer prior trading day as `signal_date`

- **Pros**: aligns with “tomorrow execution” framing.
- **Cons**: harder inference (needs “previous open day”); more risk of wrong inference if the user intended a different signal day.

## 4. Recommended Design

### 4.1 Definitions

- `signal_date` (required): trading day with available close data, in `YYYY-MM-DD` or `YYYYMMDD`.
- `next_trade_date` (derived): next open trading day after `signal_date`.
- `market_calendar`: **SSE open trading days**.
- `scheme_a_active`: resolved boolean (how it is determined is out of scope here). When true, output dir includes `scheme_a`.

### 4.2 Date Inference and Validation Contract

**Input**

- Required: `signal_date`
- Optional: `next_trade_date` only for **strong validation** (if present and doesn’t match inference → error)

**Validation**

1. Normalize `signal_date` into compact `YYYYMMDD`.
2. Load SSE open trading days covering a window around `signal_date`.
3. If `signal_date` is not in the open-day set → **raise error**.
4. Resolve `next_trade_date` as the next open day strictly after `signal_date`.
5. If optional user-supplied `next_trade_date` exists, it must equal inferred `next_trade_date`.

**Calendar source and fallback**

- Primary: `tushare pro.trade_cal(exchange="SSE", is_open="1")`
- Fallback: `akshare.tool_trade_date_hist_sina()`
- The resolver must record which source was used in the manifest (`calendar_source`).

### 4.3 Output Directory Naming (New Default)

Directory is keyed by **signal day** (`signal_date`) to avoid directory/file-date mismatches that confuse audit & replay.

- Non-scheme_a:

```text
outputs/<signal_yyyymm>/<signal_yyyymmdd>/
```

- scheme_a:

```text
outputs/<signal_yyyymm>/<signal_yyyymmdd>_scheme_a/
```

Rationale:

- “Which close data generated this plan?” is answered by the directory name itself.
- `next_trade_date` is still recorded inside docs + `manifest.json` for execution alignment.
- The scheme_a marker is kept for fast visual recognition.

### 4.4 `manifest.json` (Output Provenance)

Each output directory MUST include a `manifest.json` with at least:

```json
{
  "signal_date": "20260601",
  "next_trade_date": "20260602",
  "signal_date_iso": "2026-06-01",
  "next_trade_date_iso": "2026-06-02",
  "market": "CN-SSE",
  "calendar_source": "tushare_trade_cal" ,
  "scheme_a_active": true,
  "output_dir": "outputs/202606/20260601_scheme_a",
  "generated_at": "2026-06-02T08:00:00+08:00",
  "execution_contract_summary": {
    "effective_trade_bias": "confirmation_only",
    "report_mode": "confirmation_review_only",
    "release_authority": "market_gate"
  }
}
```

Notes:

- `execution_contract_summary` is a minimal digest for traceability; it must match the main bundle’s contract.
- The manifest is the canonical place to read the resolved dates programmatically.

### 4.5 Prompt / Skill UX Contract

Daily prompt template becomes single-date by default:

```text
使用 ai-hedge-fund-btst skill，基于 2026-06-01 收盘数据，为下一交易日生成 BTST 全套中文文档，并继续生成 opening watch card 和 premarket execution card。所有 follow-up 文档保持与主文档一致的 execution contract 口径。保存到默认推荐目录；如果方案 A 当前激活，自动输出到 scheme_a 目录。

（可选一致性校验：目标交易日=2026-06-02）
```

Behavior:

- If the optional `目标交易日` is present, it is **only** used for validation.
- The assistant must surface a short “date resolution” block in the response:
  - `signal_date` (ISO + compact)
  - inferred `next_trade_date`
  - resolved output directory
  - scheme_a status

### 4.6 Follow-up Artifacts Placement

Opening watch card and premarket execution card outputs must be written into the **same resolved output directory** as the main doc bundle.

File naming stays unchanged (still includes the appropriate date in the filename), but placement is standardized by this spec.

### 4.7 Documentation Updates

Update these user-facing docs to match the new rule:

- `docs/prompt/often/btst_daily_report.md` (templates and “当前约定” section)
- `docs/plans/2026-05-27-early-runner-scheme-a-operations.md` (directory examples)

### 4.8 Testing Strategy (Acceptance Criteria)

1. **Weekend inference**: if `signal_date` is a Friday open day, inferred `next_trade_date` must be the next Monday open day.
2. **Non-trading-day rejection**: if `signal_date` is Saturday, resolver must error.
3. **Fallback calendar**: if Tushare calendar is empty/unavailable, Akshare calendar provides the open-day list.
4. **Directory naming**: output dir is signal-date anchored: `outputs/<signal_yyyymm>/<signal_yyyymmdd>[_scheme_a]/`.
5. **Manifest correctness**: manifest dates match resolver and include `calendar_source`.

## 5. Rollout Notes

- No backward compatibility is required. The new directory naming becomes the default for new runs.
- Historical outputs remain in their existing locations; no migration is performed.
