# Auto Quality and Daily Action Readiness Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish trustworthy, independent Auto and Daily Action artifacts so optional data or expected suspensions cannot create false degradation, while unexplained evidence gaps still fail closed at the correct scope.

**Architecture:** Auto quality is decided from actual scoring evidence through a centralized feature-policy registry. Daily Action receives a separate full-universe readiness manifest built from immutable per-ticker refresh outcomes, then scans only a verified in-memory PIT snapshot. The ledger lifecycle runs independently of new-entry readiness, and both commands render separate Chinese operator results.

**Tech Stack:** Python 3.13, dataclasses, enums, pandas, SHA-256 canonical JSON fingerprints, SQLite ledger, pytest, existing atomic-file and trading-calendar utilities.

## Global Constraints

- Do not change BTST thresholds, Kelly sizing, exit policy, portfolio caps, or OversoldBounce default-disabled state.
- A degraded setup may be scanned and displayed, but must remain `plan_eligible=False` and must never create `BUY_PLAN`.
- Auto and Daily Action are independent publication domains; neither reader may require the other domain to be healthy.
- Required scoring evidence blocks Auto; optional evidence only warns and disables its enhancement.
- Expected suspension and explicitly unsupported data are per-ticker states, not global failures.
- All price and fund-flow outcome categories must conserve the frozen Daily Action universe exactly.
- Signal-session policy is Asia/Shanghai 17:00, versioned, and uses explicit open sessions without weekday inference.
- PIT fingerprints cover normalized rows with `date <= signal_date`; future appends do not change historical fingerprints.
- Daily Action production code must scan the same in-memory snapshot that was verified; it must not reopen cache files.
- Missing new-entry readiness must not skip ledger lifecycle processing. Missing execution evidence produces deferred state, never a fabricated fill.
- Existing backtest and v1 paper-trading artifacts are immutable.
- Every task uses RED → minimal GREEN → scoped regression → two-stage review → commit.
- This plan supersedes `docs/superpowers/plans/2026-07-14-daily-action-operator-summary.md`; Task 9 carries that rendering work after the corrected readiness boundary exists.

---

## File Structure

### New focused modules

- `src/screening/scoring_feature_quality.py`: feature policies, evidence validation, ticker-set fingerprints, and pure Auto quality decisions.
- `src/screening/offensive/cache_readiness.py`: suspension evidence, `DailyActionCacheRefreshStats`, mutually exclusive per-ticker refresh outcomes, derived stats, and universe conservation.
- `src/screening/offensive/setup_data_contracts.py`: versioned setup dependencies and capability evaluation.
- `src/screening/offensive/daily_action_readiness.py`: Daily Action manifest model, serialization, validation, and independent atomic publication.
- `src/utils/secure_files.py`: bounded no-follow regular-file reads shared by manifest and cache loaders.
- `src/screening/offensive/daily_action_snapshot.py`: canonical PIT normalization and `VerifiedDailyActionSnapshot` loading.

### Existing modules with bounded changes

- `src/utils/date_utils.py`, `src/cli/input.py`: one authoritative 17:00 signal-session resolver for Auto defaults.
- `src/screening/scoring_feature_refresh.py`, `src/screening/scoring_feature_store.py`, `src/screening/optional_feature_store.py`: truthful producer and consumer evidence.
- `src/screening/auto_pipeline.py`, `src/main.py`: structured Auto quality plus independent Daily readiness orchestration and output.
- `src/screening/offensive/cache_refresh.py`: one daily batch, one suspension snapshot, one frozen universe, per-ticker results.
- `src/screening/offensive/daily_action.py`, `src/screening/offensive/daily_action_service.py`, `src/cli/dispatcher.py`: verified-snapshot scanning, lifecycle-first control flow, and operator rendering.

---

### Task 1: Freeze the shared authoritative signal-session policy

**Files:**
- Modify: `src/utils/date_utils.py`
- Modify: `src/cli/input.py`
- Modify: `src/screening/offensive/daily_action.py`
- Test: `tests/utils/test_date_utils.py`
- Test: `tests/cli/test_input_dates.py`
- Test: `tests/offensive/test_trade_session_semantics.py`

**Interfaces:**
- Consumes: explicit sorted open-session dates and an Asia/Shanghai wall clock.
- Produces: `SIGNAL_SESSION_POLICY_VERSION`, `SignalSessionUnavailable`, and `resolve_signal_session(*, now_cn, open_sessions, override=None) -> date`.

- [ ] **Step 1: Write failing exact-session tests**

Add tests that prohibit the existing weekday fallback on the trading command path:

```python
def test_resolve_signal_session_uses_same_1700_policy_for_weekday_and_weekend():
    sessions = (date(2026, 7, 10), date(2026, 7, 13), date(2026, 7, 14))
    assert resolve_signal_session(
        now_cn=datetime(2026, 7, 13, 16, 59), open_sessions=sessions
    ) == date(2026, 7, 10)
    assert resolve_signal_session(
        now_cn=datetime(2026, 7, 13, 17, 0), open_sessions=sessions
    ) == date(2026, 7, 13)
    assert resolve_signal_session(
        now_cn=datetime(2026, 7, 12, 18, 0), open_sessions=sessions
    ) == date(2026, 7, 10)


def test_resolve_signal_session_fails_without_explicit_calendar():
    with pytest.raises(SignalSessionUnavailable):
        resolve_signal_session(
            now_cn=datetime(2026, 7, 13, 18, 0), open_sessions=()
        )


def test_override_must_be_an_open_session():
    with pytest.raises(SignalSessionUnavailable):
        resolve_signal_session(
            now_cn=datetime(2026, 7, 13, 18, 0),
            open_sessions=(date(2026, 7, 10),),
            override="20260711",
        )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run pytest tests/utils/test_date_utils.py tests/cli/test_input_dates.py \
  tests/offensive/test_trade_session_semantics.py -k 'signal_session or default_end_date' -v
```

Expected: FAIL because no strict shared resolver exists and Auto defaults still allow weekday inference.

- [ ] **Step 3: Implement the strict resolver and migrate both callers**

Add this public boundary in `src/utils/date_utils.py`:

```python
SIGNAL_SESSION_POLICY_VERSION = "ashare-cn-1700-v1"
_SIGNAL_READY_CUTOFF = time(17, 0)


class SignalSessionUnavailable(ValueError):
    pass


def resolve_signal_session(
    *,
    now_cn: datetime,
    open_sessions: Sequence[date],
    override: str | date | None = None,
) -> date:
    sessions = tuple(sorted(set(open_sessions)))
    if not sessions:
        raise SignalSessionUnavailable("authoritative open sessions unavailable")
    if override is not None:
        selected = (
            override
            if isinstance(override, date) and not isinstance(override, datetime)
            else datetime.strptime(str(override).replace("-", ""), "%Y%m%d").date()
        )
        if selected not in sessions:
            raise SignalSessionUnavailable("override is not an authoritative open session")
        return selected
    cutoff_date = now_cn.date() if now_cn.time() >= _SIGNAL_READY_CUTOFF else now_cn.date() - timedelta(days=1)
    eligible = tuple(session for session in sessions if session <= cutoff_date)
    if not eligible:
        raise SignalSessionUnavailable("calendar has no session at or before cutoff")
    return eligible[-1]
```

Move the local-calendar loader to a shared helper in the same module, keeping `DAILY_ACTION_CALENDAR_PATH` as a backward-compatible alias. Make `_resolve_default_end_date()` and Daily Action call `resolve_signal_session`; leave legacy non-trading research helpers unchanged.

- [ ] **Step 4: Run scoped tests and verify GREEN**

```bash
uv run pytest tests/utils/test_date_utils.py tests/cli/test_input_dates.py \
  tests/offensive/test_trade_session_semantics.py tests/test_cli_dispatcher.py -q
```

Expected: PASS; Friday resolves to Friday, Monday before 17:00 resolves to Friday, and missing authoritative sessions fail closed.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/utils/date_utils.py src/cli/input.py \
  src/screening/offensive/daily_action.py tests/utils/test_date_utils.py \
  tests/cli/test_input_dates.py tests/offensive/test_trade_session_semantics.py
git commit -m "fix: unify authoritative signal session resolution"
```

---

### Task 2: Add centralized scoring feature policies and pure Auto quality decisions

**Files:**
- Create: `src/screening/scoring_feature_quality.py`
- Create: `tests/screening/test_scoring_feature_quality.py`

**Interfaces:**
- Consumes: `payload["data_quality"]["scoring_features"]`.
- Produces: `ObservationStatus`, `FeaturePolicy`, `FeatureEvidence`, `QualityIssue`, `QualityDecision`, `FEATURE_POLICIES`, `ticker_set_fingerprint()`, and `assess_auto_quality()`.

- [ ] **Step 1: Write failing model and decision tests**

Cover required/optional separation, strict conservation, identity fingerprints, and refresh-versus-consumption failure:

```python
def test_complete_required_and_missing_optional_is_healthy():
    payload = quality_payload(required="success", optional="unavailable")
    decision = assess_auto_quality(payload)
    assert decision.healthy is True
    assert decision.blockers == ()
    assert {issue.family for issue in decision.warnings} == {
        "industry_pe_medians", "dragon_tiger_bonus",
        "intraday_short_trade_metrics", "daily_fund_flow_metrics",
    }


def test_refresh_failure_with_current_consumption_is_warning_only():
    payload = quality_payload(required="success")
    evidence = payload["data_quality"]["scoring_features"]["financial_metrics"]
    evidence["refresh_failed_count"] = 2
    decision = assess_auto_quality(payload)
    assert decision.healthy is True
    assert any(issue.code == "provider_refresh_failed" for issue in decision.warnings)


def test_equal_counts_with_wrong_ticker_identity_is_blocked():
    payload = quality_payload(required="success")
    payload["data_quality"]["scoring_features"]["price_history"][
        "usable_tickers_fingerprint"
    ] = "sha256:wrong"
    assert assess_auto_quality(payload).healthy is False
```

Also assert that `daily_action_cache_refresh` and compatibility `optional_features` cannot change the verdict.

- [ ] **Step 2: Run the new test file and verify RED**

```bash
uv run pytest tests/screening/test_scoring_feature_quality.py -v
```

Expected: collection FAIL because the module does not exist.

- [ ] **Step 3: Implement immutable policies, evidence validation, and decision logic**

Use exact fields from the approved spec:

```python
class ObservationStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class QualityDecision:
    healthy: bool
    blockers: tuple[QualityIssue, ...]
    warnings: tuple[QualityIssue, ...]


REQUIRED_SCORING_FEATURES = frozenset(
    {"price_history", "financial_metrics", "event_inputs"}
)
OPTIONAL_SCORING_FEATURES = frozenset(
    {"industry_pe_medians", "dragon_tiger_bonus",
     "intraday_short_trade_metrics", "daily_fund_flow_metrics"}
)
```

`FeatureEvidence.from_mapping()` must reject booleans masquerading as integers, negative counts, invalid status conservation, missing fingerprints, and unequal requested/observed/usable identities for required success. `assess_auto_quality()` reads only `scoring_features`; required `partial/failed/unavailable` block, optional failures warn.

- [ ] **Step 4: Run tests and verify GREEN**

```bash
uv run pytest tests/screening/test_scoring_feature_quality.py -q
```

- [ ] **Step 5: Commit Task 2**

```bash
git add src/screening/scoring_feature_quality.py \
  tests/screening/test_scoring_feature_quality.py
git commit -m "feat: model scoring evidence quality"
```

---

### Task 3: Produce truthful provider and consumed scoring evidence

**Files:**
- Modify: `src/screening/scoring_feature_refresh.py`
- Modify: `src/screening/scoring_feature_store.py`
- Modify: `src/screening/optional_feature_store.py`
- Create: `tests/screening/test_scoring_feature_refresh.py`
- Modify: `tests/screening/test_scoring_feature_store.py`
- Modify: `tests/screening/test_optional_feature_store.py`

**Interfaces:**
- Consumes: Task 2 `ObservationStatus`, `FeatureEvidence`, and `ticker_set_fingerprint()`.
- Produces: `TickerFeatureObservation`; per-family, per-ticker refresh evidence; truthful `ScoringFeatureStore.build_quality_summary()`.

- [ ] **Step 1: Write failing producer tests**

```python
def test_successful_empty_events_are_observed_empty(monkeypatch):
    monkeypatch.setattr(api, "get_company_news", lambda *_a, **_k: [])
    monkeypatch.setattr(api, "get_insider_trades", lambda *_a, **_k: [])
    observations = _fetch_ticker_data("000001", "20260713")
    event = next(item for item in observations if item.family == "event_inputs")
    assert event.status is ObservationStatus.SUCCESS
    assert event.nonempty_count == 0


def test_event_is_partial_when_one_source_fails(monkeypatch):
    monkeypatch.setattr(api, "get_company_news", lambda *_a, **_k: [])
    monkeypatch.setattr(api, "get_insider_trades", Mock(side_effect=RuntimeError("down")))
    event = next(
        item for item in _fetch_ticker_data("000001", "20260713")
        if item.family == "event_inputs"
    )
    assert event.status is ObservationStatus.PARTIAL
```

Add timeout conservation and per-family independence tests.

- [ ] **Step 2: Write failing consumer-evidence tests**

Assert exact-date price, stale financial fallback, authoritative empty events, missing events, optional exact-empty龙虎榜, and ticker-set identity:

```python
assert summary["scoring_features"]["financial_metrics"]["stale_count"] == 1
assert summary["scoring_features"]["event_inputs"]["observed_count"] == 1
assert summary["scoring_features"]["event_inputs"]["nonempty_count"] == 0
assert summary["optional_features"][family] == summary["scoring_features"][family]
```

- [ ] **Step 3: Run focused tests and verify RED**

```bash
uv run pytest tests/screening/test_scoring_feature_refresh.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_optional_feature_store.py -k 'evidence or stale or empty or timeout' -v
```

Expected: FAIL because refresh exceptions are swallowed, stale is hardcoded false, and empty observations are not tracked.

- [ ] **Step 4: Implement per-ticker refresh observations**

Replace the count-only worker result with:

```python
@dataclass(frozen=True)
class TickerFeatureObservation:
    ticker: str
    family: str
    status: ObservationStatus
    nonempty_count: int
    source_parts_succeeded: int
    source_parts_total: int
    failure_code: str | None = None
```

The refresh manifest stores every requested ticker outcome. Pending futures at timeout become failed observations. Aggregate `refresh_failed_count` is derived per family, and manifest JSON uses `atomic_write_json()`.

- [ ] **Step 5: Implement the consumption collector**

Expand `_QualityTracker` with `note_observed`, `note_usable`, `note_nonempty`, `note_stale`, and `note_consumption_failure`. Make snapshot resolution return `(path, snapshot_date, stale)`. Change `build_quality_summary(trade_date, tickers, score_outputs)` so required score-component outputs are checked for presence and finite values. Emit Task 2 evidence fields, including all three ticker-set fingerprints and separate row targets. Derive compatibility `optional_features` directly from `scoring_features`.

- [ ] **Step 6: Run scoped regression and verify GREEN**

```bash
uv run pytest tests/screening/test_scoring_feature_refresh.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_optional_feature_store.py \
  tests/screening/test_strategy_scorer.py -q
```

- [ ] **Step 7: Commit Task 3**

```bash
git add src/screening/scoring_feature_refresh.py \
  src/screening/scoring_feature_store.py \
  src/screening/optional_feature_store.py \
  tests/screening/test_scoring_feature_refresh.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_optional_feature_store.py
git commit -m "fix: record truthful scoring evidence"
```

---

### Task 4: Decouple Auto canonical health from Daily Action cache statistics

**Files:**
- Modify: `src/screening/auto_pipeline.py`
- Modify: `src/main.py`
- Modify: `tests/screening/test_auto_pipeline_publication.py`
- Modify: `tests/test_main_auto_feature_quality.py`
- Modify: `tests/test_main_auto_cache_refresh.py`

**Interfaces:**
- Consumes: Task 2 `assess_auto_quality()` and Task 3 quality payload.
- Produces: serialized `quality_decision`; compatibility `_quality_is_healthy()` wrapper.

- [ ] **Step 1: Replace tests that encode the incorrect global coupling**

Delete assertions requiring `price_missing == 0` or optional coverage `1.0`, then add:

```python
def test_auto_health_ignores_daily_action_single_ticker_outcomes():
    payload = strict_required_quality_payload()
    payload["daily_action_cache_refresh"] = {
        "status": "success", "price_missing": 2,
        "fund_flow_suspended": 3, "fund_flow_bse_unsupported": 7,
    }
    assert _quality_is_healthy(payload) is True


def test_auto_optional_missing_publishes_healthy_canonical(tmp_path):
    result = run_pipeline_with_required_success_optional_unavailable(tmp_path)
    assert result.status is AutoRunStatus.HEALTHY
    assert result.payload["quality_decision"]["warnings"]
    assert result.artifact_path.name == "auto_screening_20260713.json"
```

Add a fixed 2026-07-13-shaped fixture rather than reading mutable runtime artifacts.

- [ ] **Step 2: Run Auto tests and verify RED**

```bash
uv run pytest tests/screening/test_auto_pipeline_publication.py \
  tests/test_main_auto_feature_quality.py tests/test_main_auto_cache_refresh.py \
  -k 'quality or optional or cache_refresh or 20260713' -v
```

- [ ] **Step 3: Integrate one structured decision**

```python
def _quality_is_healthy(payload: Mapping[str, Any]) -> bool:
    return assess_auto_quality(payload).healthy
```

Pass the actual per-ticker strategy score outputs into Task 3 `build_quality_summary()`. Compute `decision = assess_auto_quality(payload)` once after scoring evidence is complete. Serialize blockers and warnings into `payload["quality_decision"]`; use `decision.healthy` for Auto manifest status and canonical-versus-attempt publication. Remove `daily_action_cache_refresh` and compatibility `optional_features` from Auto gate logic.

- [ ] **Step 4: Run Auto regression and verify GREEN**

```bash
uv run pytest tests/screening/test_auto_pipeline_publication.py \
  tests/test_main_auto_feature_quality.py tests/test_main_auto_cache_refresh.py -q
```

- [ ] **Step 5: Commit Task 4**

```bash
git add src/screening/auto_pipeline.py src/main.py \
  tests/screening/test_auto_pipeline_publication.py \
  tests/test_main_auto_feature_quality.py tests/test_main_auto_cache_refresh.py
git commit -m "fix: scope auto health to consumed scoring evidence"
```

---

### Task 5: Freeze one refresh universe and derive mutually exclusive per-ticker outcomes

**Files:**
- Create: `src/screening/offensive/cache_readiness.py`
- Modify: `src/screening/offensive/cache_refresh.py`
- Modify: `tests/offensive/test_daily_action_cache_refresh.py`

**Interfaces:**
- Consumes: one daily batch, one `SuspensionEvidence`, existing caches, explicit targets, and limit-up injection.
- Produces: `DailyActionRefreshResult` with immutable universe, outcomes, fingerprints, and derived `DailyActionCacheRefreshStats`.

- [ ] **Step 1: Write failing outcome and conservation tests**

```python
def test_20260713_suspensions_are_expected_not_missing(tmp_path):
    result = refresh_daily_action_caches(
        "20260713",
        target_tickers=["000001", "002677", "300567"],
        daily_prices_df=prices_for("000001"),
        suspension_loader=lambda _d: SuspensionEvidence.available(
            date(2026, 7, 13), {"002677", "300567"}
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )
    assert result.outcomes["000001"].price_status is PriceStatus.CURRENT
    assert result.outcomes["002677"].price_status is PriceStatus.SUSPENDED
    assert result.stats.price_missing == 0
    assert sum(result.stats.price_status_counts.values()) == 3


def test_unavailable_suspension_source_never_means_empty():
    evidence = load_suspension_evidence("20260713", fetch=lambda _d: None)
    assert evidence.status is SuspensionEvidenceStatus.UNAVAILABLE
```

Also cover one batch call, limit-up before universe freeze, BSE unsupported, quota `not_attempted`, runtime directory mutation, and price/fund-flow conservation.

- [ ] **Step 2: Run cache tests and verify RED**

```bash
uv run pytest tests/offensive/test_daily_action_cache_refresh.py \
  -k 'outcome or conserve or suspension or universe or one_daily_batch' -v
```

- [ ] **Step 3: Implement immutable result models**

```python
class PriceStatus(StrEnum):
    CURRENT = "current"
    SUSPENDED = "suspended"
    MISSING_UNEXPLAINED = "missing_unexplained"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


class FundFlowStatus(StrEnum):
    CURRENT = "current"
    SUSPENDED = "suspended"
    UNSUPPORTED = "unsupported"
    MISSING_UNEXPLAINED = "missing_unexplained"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


@dataclass(frozen=True)
class DailyActionCacheRefreshStats:
    price_status_counts: Mapping[str, int]
    fund_flow_status_counts: Mapping[str, int]
    industry_index_total: int
    industry_index_failed: int
    limit_up_injected: int


@dataclass(frozen=True)
class DailyActionRefreshResult:
    trade_date: date
    universe_tickers: tuple[str, ...]
    universe_fingerprint: str
    daily_batch_fingerprint: str | None
    suspension_evidence: SuspensionEvidence
    outcomes: Mapping[str, TickerRefreshOutcome]
    stats: DailyActionCacheRefreshStats
```

Validate ticker uniqueness and category conservation in `__post_init__`; freeze mappings with `MappingProxyType`.

- [ ] **Step 4: Refactor refresh orchestration around one frozen batch**

Order must be: fetch batch and suspension evidence once → extract limit-ups → merge existing/explicit/injected tickers → normalize/sort/freeze → refresh each source → derive outcomes → derive stats. Apply `max_tickers` only after fresh-cache checks and record remaining stale tickers as `NOT_ATTEMPTED`.

Keep `DailyActionRefreshResult.to_dict()` as the compatibility surface used by current logging.

- [ ] **Step 5: Run all cache tests and verify GREEN**

```bash
uv run pytest tests/offensive/test_daily_action_cache_refresh.py \
  tests/test_main_auto_cache_refresh.py -q
```

- [ ] **Step 6: Commit Task 5**

```bash
git add src/screening/offensive/cache_readiness.py \
  src/screening/offensive/cache_refresh.py \
  tests/offensive/test_daily_action_cache_refresh.py \
  tests/test_main_auto_cache_refresh.py
git commit -m "fix: classify daily cache outcomes per ticker"
```

---

### Task 6: Build and independently publish the full-universe Daily Action readiness manifest

**Files:**
- Create: `src/screening/offensive/setup_data_contracts.py`
- Create: `src/screening/offensive/daily_action_readiness.py`
- Create: `tests/offensive/test_daily_action_readiness.py`
- Modify: `src/main.py`
- Modify: `tests/test_main_auto_cache_refresh.py`

**Interfaces:**
- Consumes: Task 5 `DailyActionRefreshResult`, exact-date shared evidence, policy versions.
- Produces: `SharedReadinessEvidence`, `SetupCapability`, `DailyActionTickerReadiness`, `DailyActionReadinessManifest`, `DailyActionReadinessPublication`, `build_daily_action_readiness()`, `publish_daily_action_readiness()`.

- [ ] **Step 1: Write failing contract and manifest tests**

```python
def test_shallow_btst_is_scannable_but_not_plan_eligible():
    capability = evaluate_btst_capability(
        evidence(full_price_days=6, fund_flow_days=4, industry_current=True)
    )
    assert capability.scannable is True
    assert capability.degraded is True
    assert capability.plan_eligible is False


def test_readiness_universe_is_refresh_universe_not_auto_300():
    manifest = build_daily_action_readiness(refresh_652(), shared_evidence())
    assert len(manifest.universe_tickers) == 652
    assert manifest.domain == "daily_action"
    assert manifest.status == "healthy"


def test_all_tickers_blocked_can_still_be_structurally_healthy():
    manifest = build_daily_action_readiness(all_suspended_refresh(), shared_evidence())
    assert manifest.is_healthy is True
    assert not any(
        cap.plan_eligible
        for ticker in manifest.tickers.values()
        for cap in ticker.capabilities.values()
    )
```

Add unknown policy version, Auto manifest rejection, atomic failure, and old-canonical preservation tests.

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/offensive/test_daily_action_readiness.py -v
```

- [ ] **Step 3: Implement versioned setup contracts and manifest types**

```python
@dataclass(frozen=True)
class SetupCapability:
    enabled: bool
    scannable: bool
    plan_eligible: bool
    degraded: bool
    block_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    consumed_fingerprint: str | None


@dataclass(frozen=True)
class SharedReadinessEvidence:
    regime_row: Mapping[str, object]
    regime_fingerprint: str | None
    industry_mapping_fingerprint: str | None
    security_status_fingerprint: str | None
    board_rule_version: str
    normalization_version: str
    signal_session_policy_version: str


DAILY_ACTION_READINESS_SCHEMA_VERSION = 1
SETUP_REQUIREMENTS_VERSION = "daily-action-setups-v1"


@dataclass(frozen=True)
class DailyActionReadinessPublication:
    status: str
    artifact_path: Path
    manifest: DailyActionReadinessManifest | None
    summary: Mapping[str, Mapping[str, int]]
```

BTST requires exact-day price, at least five prior sessions, exact-day fund flow, listed/non-ST security, and known board rule. Flow history under 20 or missing industry may be scanned as degraded but is never plan eligible. OversoldBounce records `enabled=False` unless its existing environment control explicitly enables it.

- [ ] **Step 4: Implement independent publication**

Canonical path is `daily_action_readiness_YYYYMMDD.json`; degraded/fatal attempt path includes `run_id`. Serialize sorted universe, setup capabilities, shared evidence, policy versions, and canonical content fingerprint. Use `atomic_write_json()` and never read or mutate Auto canonical.

Change `_refresh_daily_action_caches_for_auto()` to return the refresh result, build readiness, publish it, attach a diagnostic summary, and keep Auto publication independent if readiness fails.

- [ ] **Step 5: Run readiness and orchestration tests**

```bash
uv run pytest tests/offensive/test_daily_action_readiness.py \
  tests/test_main_auto_cache_refresh.py \
  tests/screening/test_auto_pipeline_publication.py -q
```

- [ ] **Step 6: Commit Task 6**

```bash
git add src/screening/offensive/setup_data_contracts.py \
  src/screening/offensive/daily_action_readiness.py src/main.py \
  tests/offensive/test_daily_action_readiness.py \
  tests/test_main_auto_cache_refresh.py
git commit -m "feat: publish daily action readiness independently"
```

---

### Task 7: Load one immutable, security-hardened PIT snapshot

**Files:**
- Create: `src/utils/secure_files.py`
- Create: `src/screening/offensive/daily_action_snapshot.py`
- Create: `tests/utils/test_secure_files.py`
- Create: `tests/offensive/test_daily_action_verified_snapshot.py`
- Modify: `src/screening/offensive/daily_action_service.py`

**Interfaces:**
- Consumes: Task 6 exact-date Daily readiness canonical and Task 5 cache files.
- Produces: `read_regular_bytes()`, normalized immutable row types, `VerifiedDailyActionSnapshot`, `VerifiedSnapshotResult`, and `load_verified_daily_action_snapshot()`.

- [ ] **Step 1: Write failing hardened-read tests**

Test regular file success and rejection of symlink, ancestor symlink, FIFO, directory, oversize content, inode replacement, and invalid UTF-8/JSON.

```python
with pytest.raises(SecureReadError):
    read_regular_bytes(symlink_path, max_bytes=1024)
with pytest.raises(SecureReadError):
    read_regular_bytes(fifo_path, max_bytes=1024)
```

- [ ] **Step 2: Write failing PIT and immutability tests**

```python
def test_future_append_does_not_change_pit_projection(tmp_path):
    reports_dir, data_dir = install_verified_fixture(tmp_path, signal_date=date(2026, 7, 13))
    first = load_verified_daily_action_snapshot(
        date(2026, 7, 13), reports_dir=reports_dir, data_dir=data_dir
    )
    append_price_row(tmp_path, "000001", "2026-07-14", 99)
    second = load_verified_daily_action_snapshot(
        date(2026, 7, 13), reports_dir=reports_dir, data_dir=data_dir
    )
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id


def test_historical_mutation_blocks_only_affected_ticker(tmp_path):
    reports_dir, data_dir = install_verified_fixture(tmp_path, signal_date=date(2026, 7, 13))
    mutate_price_row(tmp_path, "000001", "2026-07-12")
    result = load_verified_daily_action_snapshot(
        date(2026, 7, 13), reports_dir=reports_dir, data_dir=data_dir
    )
    assert result.ticker_blocks["000001"] == ("price_fingerprint_mismatch",)
    assert "000002" not in result.ticker_blocks
```

Also cover shared industry scope, policy mismatch, NaN/Inf, normalization stability, and legacy Auto manifest rejection.

- [ ] **Step 3: Run new tests and verify RED**

```bash
uv run pytest tests/utils/test_secure_files.py \
  tests/offensive/test_daily_action_verified_snapshot.py -v
```

- [ ] **Step 4: Extract the secure read primitive**

Move `_read_exact_regular_json` mechanics into:

```python
def read_regular_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read one bounded stable regular file without following indirection."""
```

Retain `O_NOFOLLOW`, held inode/device checks before and after read, `O_NONBLOCK`, size enforcement, and guaranteed fd closure.

- [ ] **Step 5: Implement canonical PIT projection and snapshot loader**

Read every file once, filter `date <= signal_date`, normalize selected columns, encode numeric fields as stable decimal strings, map optional missing to `null`, reject required nonfinite values, sort by ticker/date, and SHA-256 stable JSON. Store tuples/mapping proxies; `price_frame(ticker)` returns a defensive DataFrame copy.

`VerifiedDailyActionSnapshot` binds price, fund flow, industry, security/ST, regime, board-rule, normalization, setup-contract and signal-session policy evidence. It exposes `scannable_tickers: tuple[str, ...]` and `setup_context(ticker: str) -> VerifiedSetupContext`; the context contains the matching capability and consumed fingerprint. Scanner and service receive no cache path.

- [ ] **Step 6: Run snapshot tests and verify GREEN**

```bash
uv run pytest tests/utils/test_secure_files.py \
  tests/offensive/test_daily_action_verified_snapshot.py \
  tests/offensive/test_daily_action_manifest_gate.py -q
```

- [ ] **Step 7: Commit Task 7**

```bash
git add src/utils/secure_files.py \
  src/screening/offensive/daily_action_snapshot.py \
  src/screening/offensive/daily_action_service.py \
  tests/utils/test_secure_files.py \
  tests/offensive/test_daily_action_verified_snapshot.py
git commit -m "feat: verify immutable daily action snapshots"
```

---

### Task 8: Make scanner, service, and dispatcher consume only the verified snapshot

**Files:**
- Modify: `src/screening/offensive/daily_action.py`
- Modify: `src/screening/offensive/daily_action_service.py`
- Modify: `src/cli/dispatcher.py`
- Modify: `tests/offensive/test_daily_action.py`
- Modify: `tests/offensive/test_daily_action_manifest_gate.py`
- Modify: `tests/offensive/test_daily_action_v2_integration.py`
- Modify: `tests/test_cli_dispatcher.py`

**Interfaces:**
- Consumes: Task 7 `VerifiedDailyActionSnapshot` and `VerifiedSnapshotResult`.
- Produces: `scan_daily_action_candidates(snapshot)`, candidate snapshot provenance, `DailyActionService.advance_lifecycle()`, and `DailyActionService.complete_run()`.

- [ ] **Step 1: Write failing scanner provenance and universe tests**

```python
def test_candidate_outside_auto_300_can_be_planned(verified_snapshot_652):
    scan = scan_daily_action_candidates(verified_snapshot_652)
    assert "000004" in {candidate.ticker for candidate in scan.candidates}


def test_degraded_capability_is_display_only(verified_degraded_snapshot):
    scan = scan_daily_action_candidates(verified_degraded_snapshot)
    assert scan.candidates == ()
    assert scan.blocked_candidates[0].reason == "incomplete_setup_data"


def test_v2_scanner_never_reopens_cache(monkeypatch, verified_snapshot):
    monkeypatch.setattr(Path, "open", Mock(side_effect=AssertionError("reopened")))
    scan_daily_action_candidates(verified_snapshot)
```

- [ ] **Step 2: Write failing lifecycle-first and provenance-gate tests**

```python
def test_missing_readiness_still_advances_existing_exit(service_with_due_exit):
    context = service_with_due_exit.advance_lifecycle(SIGNAL_DATE)
    run = service_with_due_exit.complete_run(context, snapshot_result=None, scan=None)
    assert run.exit_plans or run.deferred_exits or run.completed_exits
    assert run.block_reason == "daily_action_readiness_missing"


def test_candidate_snapshot_identity_mismatch_is_blocked(service, snapshot, scan):
    bad = replace(scan.candidates[0], snapshot_id="sha256:other")
    run = service.run_from_snapshot(snapshot, replace(scan, candidates=(bad,)))
    assert run.new_plans == ()
    assert run.ticker_gate_blocks[0].reasons == ("candidate_snapshot_mismatch",)
```

Add Friday-to-Monday and repeated-run ledger idempotency.

- [ ] **Step 3: Run integration tests and verify RED**

```bash
uv run pytest tests/offensive/test_daily_action.py \
  tests/offensive/test_daily_action_manifest_gate.py \
  tests/offensive/test_daily_action_v2_integration.py \
  tests/test_cli_dispatcher.py -k 'snapshot or readiness or lifecycle or monday or auto_pool' -v
```

- [ ] **Step 4: Refactor the v2 scanner boundary**

Change the production signature to:

```python
def scan_daily_action_candidates(
    snapshot: VerifiedDailyActionSnapshot,
) -> DailyActionScan:
    contexts = tuple(snapshot.setup_context(ticker) for ticker in snapshot.scannable_tickers)
    return _scan_verified_contexts(
        signal_date=snapshot.signal_date,
        snapshot_id=snapshot.snapshot_id,
        contexts=contexts,
    )
```

Add `snapshot_id` and `setup_consumed_fingerprint` to `DailyActionScan` and `PlanCandidate`. Introduce the private pure helper `_scan_verified_contexts(*, signal_date, snapshot_id, contexts) -> DailyActionScan`; it runs the existing setup detectors against the supplied contexts, filters `plan_eligible=False` before ranking, and builds candidates with the context fingerprint. Keep legacy file adapters only for legacy research callers; v2 must not call `_load_prices_for_ticker`, `_load_st_tickers`, `_regime_from_history`, or `_load_industry_day_pct_by_ticker`.

- [ ] **Step 5: Split lifecycle from new-entry completion**

```python
context = service.advance_lifecycle(signal_date)
if verified.snapshot is None:
    run = service.complete_run(context, candidates=(), admission_block=verified.global_reason)
else:
    scan = scan_daily_action_candidates(verified.snapshot)
    run = service.complete_run(context, candidates=scan.candidates, snapshot=verified.snapshot)
```

Service validates per-setup `plan_eligible`, `snapshot_id`, and consumed fingerprint. Remove `RunManifest`, `cache_fingerprints`, Auto candidate membership, and `load_daily_action_manifest_gate()` from the production path.

- [ ] **Step 6: Wire dispatcher in the mandatory order**

Resolve session → open ledger → advance lifecycle → load verified snapshot → scan if available → complete run → render. Loader failure must remain a new-entry block rather than an early return.

- [ ] **Step 7: Run scoped and full offensive regression**

```bash
uv run pytest tests/offensive/test_daily_action.py \
  tests/offensive/test_daily_action_manifest_gate.py \
  tests/offensive/test_daily_action_v2_integration.py \
  tests/offensive/test_exit_shadow_integration.py tests/test_cli_dispatcher.py -q
uv run pytest tests/offensive/ -q
```

- [ ] **Step 8: Commit Task 8**

```bash
git add src/screening/offensive/daily_action.py \
  src/screening/offensive/daily_action_service.py src/cli/dispatcher.py \
  tests/offensive/test_daily_action.py \
  tests/offensive/test_daily_action_manifest_gate.py \
  tests/offensive/test_daily_action_v2_integration.py tests/test_cli_dispatcher.py
git commit -m "fix: gate daily actions on verified snapshots"
```

---

### Task 9: Render independent Auto results and the Chinese Daily Action operator summary

**Files:**
- Modify: `src/main.py`
- Modify: `src/screening/offensive/daily_action.py`
- Modify: `src/cli/dispatcher.py`
- Modify: `tests/test_main_auto_cache_refresh.py`
- Modify: `tests/offensive/test_daily_action_manifest_gate.py`
- Modify: `tests/offensive/test_daily_action_v2_integration.py`
- Modify: `tests/test_cli_dispatcher.py`

**Interfaces:**
- Consumes: structured Auto decision, Daily readiness publication summary, Task 8 run results.
- Produces: `render_daily_action_v2(run, *, verbose=False)` and explicit Auto domain summaries.

- [ ] **Step 1: Write failing operator-output tests**

Assert separate Auto and readiness lines, exact no-signal versus blocked semantics, scannable-but-ineligible state, explicit empty sections, and verbose-only raw diagnostics:

```python
assert "Auto 评分：✅" in auto_text
assert "Daily Action 就绪度：✅" in auto_text
assert "价格：正常 650 · 停牌 2 · 异常 0" in auto_text

assert "结论：⛔ 今日未生成新的次日买入计划" in blocked_text
assert "结论：ℹ️ 今日无符合条件的次日买入信号（系统运行正常）" in healthy_empty_text
assert "存在仅供诊断的残缺 setup，无可交易候选" in diagnostic_only_text
assert "参考价计划:\n  无" in healthy_empty_text
assert "block_reasons=" not in non_verbose_text
assert "block_reasons=daily_action_readiness_missing" in verbose_text
```

- [ ] **Step 2: Run output tests and verify RED**

```bash
uv run pytest tests/test_main_auto_cache_refresh.py \
  tests/offensive/test_daily_action_manifest_gate.py \
  tests/offensive/test_daily_action_v2_integration.py \
  tests/test_cli_dispatcher.py -k 'render or output or verbose or readiness' -v
```

- [ ] **Step 3: Implement presentation-only reason metadata and summaries**

Reason mapping must include `daily_action_readiness_missing`, `readiness_manifest_invalid`, `readiness_identity_mismatch`, `snapshot_fingerprint_mismatch`, `calendar_unavailable`, and warning-only `regime_authorization_evidence_unavailable`. Unknown codes use a fail-closed Chinese fallback and remain visible under `--verbose`.

Always render `无` for empty reference plans, synthetic fills, broker-confirmed fills, and shadow exits. Keep `SHADOW ONLY` wording unchanged. Remove duplicate singular/plural raw reason lines.

- [ ] **Step 4: Pass verbosity only at the rendering boundary**

```python
print(render_daily_action_v2(run, verbose="--verbose" in argv))
```

Do not add verbosity to scanner, service, manifest, or ledger interfaces.

- [ ] **Step 5: Run output and command-surface regression**

```bash
uv run pytest tests/test_main_auto_cache_refresh.py \
  tests/offensive/test_daily_action_manifest_gate.py \
  tests/offensive/test_daily_action_v2_integration.py \
  tests/test_cli_dispatcher.py -q
```

- [ ] **Step 6: Commit Task 9**

```bash
git add src/main.py src/screening/offensive/daily_action.py \
  src/cli/dispatcher.py tests/test_main_auto_cache_refresh.py \
  tests/offensive/test_daily_action_manifest_gate.py \
  tests/offensive/test_daily_action_v2_integration.py tests/test_cli_dispatcher.py
git commit -m "feat: clarify auto and daily action operator results"
```

---

### Task 10: Prove the 2026-07-13 regression, security boundaries, and real command behavior

**Files:**
- Create: `tests/offensive/fixtures/daily_readiness_20260713.json`
- Modify: `tests/test_e2e_pipeline_smoke.py`
- Modify: `tests/offensive/test_daily_action_v2_integration.py`
- Modify: `docs/superpowers/specs/2026-07-14-auto-daily-readiness-separation-design.md` only if verified implementation names differ without changing semantics.

**Interfaces:**
- Consumes: Tasks 1–9.
- Produces: deterministic end-to-end evidence and operator smoke output.

- [ ] **Step 1: Add the fixed regression fixture and end-to-end test**

The compact fixture stores the observed category counts plus the known suspended/unsupported identities. A test factory deterministically expands it to 652 six-digit synthetic ticker identities, avoiding a 652-row hand-written artifact. It matches the observed run: 650 current prices, 2 confirmed suspensions, 642 current fund-flow outcomes, 3 suspended and 7 unsupported. The test must assert:

```python
assert auto_result.status is AutoRunStatus.HEALTHY
assert daily_publication.status == "healthy"
assert len(daily_publication.manifest.universe_tickers) == 652
assert daily_publication.summary.price == {
    "current": 650, "suspended": 2, "abnormal": 0
}
assert load_verified_daily_action_snapshot(
    SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
).snapshot is not None
```

Do not read `data/reports/auto_attempt_20260713_*.json`; the fixture must be immutable and minimal.

- [ ] **Step 2: Run the focused end-to-end test**

```bash
uv run pytest tests/test_e2e_pipeline_smoke.py \
  tests/offensive/test_daily_action_v2_integration.py \
  -k '20260713 or outside_auto_pool or lifecycle_without_readiness' -v
```

Expected: PASS.

- [ ] **Step 3: Run the complete scoped verification matrix**

```bash
uv run pytest tests/screening/test_scoring_feature_quality.py \
  tests/screening/test_scoring_feature_refresh.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_auto_pipeline_publication.py -q
uv run pytest tests/offensive/ -q
uv run pytest tests/test_main_auto_cache_refresh.py \
  tests/test_main_auto_feature_quality.py tests/test_cli_dispatcher.py \
  tests/test_e2e_pipeline_smoke.py -q
uv run python -m compileall -q src
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 4: Run real command smoke checks without rewriting history**

```bash
uv run python src/main.py --daily-action --verbose
uv run python src/main.py --auto --strict-quality
uv run python src/main.py --daily-action --verbose
```

Expected after the fresh Auto run:

- Auto and Daily readiness results are printed independently;
- confirmed suspensions are expected states, not global failures;
- optional enhancements appear as warnings;
- Daily Action no longer prints `healthy_manifest_missing` from the legacy Auto manifest path;
- existing positions and exits remain visible even if new-entry readiness is blocked;
- no duplicate plan or ledger event is created on a repeat Daily Action run.

The real `--auto` command performs network-backed cache refresh and writes new dated artifacts. Run it only after all deterministic tests pass; never mutate the old degraded attempt.

- [ ] **Step 5: Final two-stage review**

First reviewer checks every completed task against the approved design and confirms no strategy semantics changed. Second reviewer checks code quality, security boundaries, error handling, and test maintainability. Resolve all blocking findings and rerun Step 3.

- [ ] **Step 6: Commit final regression evidence**

```bash
git add tests/offensive/fixtures/daily_readiness_20260713.json \
  tests/test_e2e_pipeline_smoke.py \
  tests/offensive/test_daily_action_v2_integration.py
git commit -m "test: prove independent auto and daily readiness"
```

---

## Final Acceptance Checklist

- [ ] Auto required evidence is complete and optional evidence is warning-only.
- [ ] Provider refresh failures do not invalidate current verified local consumption evidence.
- [ ] Two confirmed suspensions do not degrade Auto or the whole Daily readiness batch.
- [ ] Auto 300 and Daily Action 652 coexist without membership coupling.
- [ ] A valid BTST ticker outside Auto 300 can reach Daily Action admission.
- [ ] Degraded setup detections remain display-only.
- [ ] Every scanner input comes from the verified in-memory PIT snapshot.
- [ ] Missing readiness blocks new entries but does not bypass lifecycle checks.
- [ ] Canonical/attempt publication, security checks, PIT, TOCTOU, Friday-to-Monday, and idempotency tests pass.
- [ ] Default output is clear Chinese; verbose output retains raw audit details.
- [ ] No strategy parameter, historical artifact, or legacy backtest result changed.
