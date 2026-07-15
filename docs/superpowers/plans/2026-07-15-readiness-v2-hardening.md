# Auto / Daily Action Readiness v2 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Replace the incomplete readiness separation with one fail-closed, reproducible evidence chain from signal-session resolution through Auto quality, cache refresh, readiness v2, PIT snapshot, candidate admission, and ledger provenance.

**Architecture:** Auto quality is decided solely from validated consumed scoring evidence. Daily Action receives one frozen refresh result, publishes a strict schema-v2 readiness manifest, reloads and fingerprint-verifies one immutable PIT snapshot, then admits only candidates carrying matching structured provenance. Ledger lifecycle runs before any new-entry readiness work.

**Tech Stack:** Python 3.12+, dataclasses, pandas at detector adapters only, SHA-256 canonical JSON, SQLite ledger, pytest, existing atomic file helpers and authoritative trading calendar.

## Global Constraints

- Do not change BTST, Kelly, stop, ranking, holding-horizon, or setup thresholds.
- OversoldBounce remains disabled by default and follows the existing explicit environment control.
- The repository-enforced single-stock cap remains 10%; no caller-derived regime label may restore 12%.
- Never modify data/paper_trading_backtest, historical backtest results, old reports, or legacy ledgers.
- Auto 300 and the Daily Action full-market universe remain independent.
- Preserve the current Beijing Stock Exchange exclusion; this hardening does not change the supported trading-market scope.
- Schema v1, test-generated manifests, empty fingerprints, unknown policy versions, and unverifiable evidence have no new-entry authority.
- Degraded detections may be rendered but must never create BUY_PLAN.
- Every test that writes reports, cache files, or ledgers must use tmp_path or an injected path.
- Production code must not infer readiness by re-globbing mutable cache directories after the refresh result is frozen.
- Use test-driven development: observe each new regression test fail before implementing its fix.

## File Responsibility Map

- src/utils/date_utils.py: strict authoritative signal-session policy.
- src/cli/input.py: Auto default date adapter with no weekday/cache fallback.
- src/screening/scoring_feature_quality.py: scoring feature policy and evidence invariants.
- src/screening/scoring_feature_refresh.py: provider outcomes, timeout conservation, atomic producer manifest.
- src/screening/scoring_feature_store.py: actual consumed evidence and final score-output validation.
- src/screening/optional_feature_store.py: distinguish unavailable snapshots from authoritative empty observations.
- src/screening/auto_pipeline.py: one Auto quality decision and canonical publication gate.
- src/screening/offensive/pit_evidence.py: canonical PIT records and fingerprints shared by refresh and loader.
- src/screening/offensive/cache_readiness.py: frozen universe, tri-state suspension, mutually exclusive outcomes.
- src/screening/offensive/cache_refresh.py: one daily batch and one frozen DailyActionRefreshResult.
- src/screening/offensive/daily_action_readiness.py: schema-v2 manifest, strict validation, canonical/attempt publication.
- src/utils/secure_files.py: symlink- and replacement-resistant reads.
- src/screening/offensive/daily_action_snapshot.py: immutable verified in-memory snapshot.
- src/screening/offensive/daily_action.py: snapshot-only scanning and diagnostic rendering.
- src/screening/offensive/daily_action_service.py: lifecycle split and provenance admission.
- src/screening/offensive/ledger_repository.py: verified snapshot provenance persistence.
- src/cli/dispatcher.py: lifecycle-first production orchestration.
- src/main.py: consume FrozenRefreshResult directly and render independent domain results.

---

### Task 1: Make the authoritative signal session the only production date source

**Files:**
- Modify: src/utils/date_utils.py
- Modify: src/cli/input.py
- Modify: src/screening/offensive/daily_action.py
- Modify: src/cli/dispatcher.py
- Test: tests/utils/test_date_utils.py
- Test: tests/cli/test_input_dates.py
- Test: tests/offensive/test_trade_session_semantics.py
- Test: tests/test_cli_dispatcher.py

**Interfaces:**
- Consumes: authoritative tuple[date, ...] from _load_authoritative_session_dates().
- Produces: resolve_signal_session(*, now_cn: datetime, open_sessions: Sequence[date], override: str | date | None = None) -> date.
- Produces: resolve_daily_action_signal(*, end_date: str | None, now_cn: datetime, open_sessions: Sequence[date]) -> tuple[date, str].

- [ ] **Step 1: Add production-path regression tests**

~~~python
def test_daily_action_uses_previous_session_before_1700(monkeypatch):
    sessions = (date(2026, 7, 10), date(2026, 7, 13))
    signal_date, _ = resolve_daily_action_signal(
        now_cn=datetime(2026, 7, 13, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        open_sessions=sessions,
    )
    assert signal_date == date(2026, 7, 10)


def test_daily_action_rejects_weekend_override():
    with pytest.raises(SignalSessionUnavailable):
        resolve_daily_action_signal(
            end_date="2026-07-12",
            now_cn=datetime(2026, 7, 13, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            open_sessions=(date(2026, 7, 10), date(2026, 7, 13)),
        )


def test_auto_and_daily_action_share_the_same_cutoff(monkeypatch):
    now = datetime(2026, 7, 13, 16, 59, tzinfo=ZoneInfo("Asia/Shanghai"))
    sessions = (date(2026, 7, 10), date(2026, 7, 13))
    assert resolve_signal_session(now_cn=now, open_sessions=sessions) == date(2026, 7, 10)
~~~

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

~~~bash
uv run pytest tests/utils/test_date_utils.py tests/cli/test_input_dates.py \
  tests/offensive/test_trade_session_semantics.py tests/test_cli_dispatcher.py \
  -k "signal_session or weekend_override or shared_cutoff" -v
~~~

Expected: production Daily Action still chooses the latest cache date or accepts the weekend override.

- [ ] **Step 3: Route both commands through the strict resolver**

Implement this production adapter in src/screening/offensive/daily_action.py:

~~~python
def resolve_daily_action_signal(
    *,
    end_date: str | None = None,
    now_cn: datetime | None = None,
    open_sessions: Sequence[date] | None = None,
) -> tuple[date, str]:
    sessions = tuple(open_sessions or _load_authoritative_session_dates())
    selected = resolve_signal_session(
        now_cn=now_cn or _current_cn_datetime(),
        open_sessions=sessions,
        override=end_date,
    )
    compact = selected.strftime("%Y%m%d")
    return selected, _regime_from_history(compact)
~~~

Change _resolve_default_end_date() to return the formatted result of resolve_signal_session() and propagate SignalSessionUnavailable. Remove the market-ready weekday fallback from the Auto production path. In dispatcher, pass the already loaded open_sessions into resolve_daily_action_signal().

- [ ] **Step 4: Run date and dispatcher tests**

Run:

~~~bash
uv run pytest tests/utils/test_date_utils.py tests/cli/test_input_dates.py \
  tests/offensive/test_trade_session_semantics.py tests/test_cli_dispatcher.py -q
~~~

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/utils/date_utils.py src/cli/input.py \
  src/screening/offensive/daily_action.py src/cli/dispatcher.py \
  tests/utils/test_date_utils.py tests/cli/test_input_dates.py \
  tests/offensive/test_trade_session_semantics.py tests/test_cli_dispatcher.py
git commit -m "fix: enforce authoritative signal sessions"
~~~

---

### Task 2: Enforce Auto evidence conservation and one canonical quality gate

**Files:**
- Modify: src/screening/scoring_feature_quality.py
- Modify: src/screening/scoring_feature_store.py
- Modify: src/main.py
- Modify: src/screening/auto_pipeline.py
- Test: tests/screening/test_scoring_feature_quality.py
- Test: tests/screening/test_scoring_feature_store.py
- Test: tests/screening/test_auto_pipeline_publication.py
- Test: tests/test_main_auto_feature_quality.py

**Interfaces:**
- Consumes: score_outputs: Mapping[str, object] keyed by the exact requested ticker set.
- Produces: FeatureEvidence.from_mapping(family, raw, *, trade_date) -> FeatureEvidence.
- Produces: ScoringFeatureStore.build_quality_summary(trade_date, tickers, score_outputs, requested=None) -> dict[str, Any].
- Produces: one QualityDecision from assess_auto_quality(payload).

- [ ] **Step 1: Add failing conservation and score-output tests**

~~~python
def test_required_success_rejects_inconsistent_counts():
    evidence = required_success_evidence()
    evidence.update(eligible_count=300, requested_count=1, observed_count=1, usable_count=1)
    with pytest.raises(ValueError, match="count conservation"):
        FeatureEvidence.from_mapping("price_history", evidence, trade_date="20260713")


def test_required_success_rejects_missing_input_fingerprint():
    evidence = required_success_evidence()
    evidence["input_fingerprint"] = None
    with pytest.raises(ValueError, match="input_fingerprint"):
        FeatureEvidence.from_mapping("financial_metrics", evidence, trade_date="20260713")


def test_quality_summary_rejects_missing_or_nonfinite_score_output(tmp_path):
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=tmp_path / "snapshots",
        lhb_cache_dir=tmp_path / "lhb_cache",
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
    )
    with pytest.raises(ValueError, match="score output"):
        store.build_quality_summary(
            "20260713",
            ["000001"],
            {"000001": {"trend": float("nan")}},
        )
~~~

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

~~~bash
uv run pytest tests/screening/test_scoring_feature_quality.py \
  tests/screening/test_scoring_feature_store.py \
  -k "inconsistent_counts or input_fingerprint or score_output" -v
~~~

Expected: the inconsistent evidence is currently accepted or the new score_outputs parameter is missing.

- [ ] **Step 3: Add strict policy and evidence validation**

Extend FeaturePolicy with min_usable_rows and required_score_components. Enforce this invariant in FeatureEvidence.from_mapping():

~~~python
if not (0 <= nonempty <= usable <= observed <= requested <= eligible):
    raise ValueError(f"evidence for {family!r}: count conservation failed")
if status is ObservationStatus.SUCCESS:
    if not (requested == observed == usable):
        raise ValueError(f"evidence for {family!r}: success requires full coverage")
    if stale or consumption_failed:
        raise ValueError(f"evidence for {family!r}: success cannot consume stale or failed rows")
if policy.required:
    if not input_fingerprint:
        raise ValueError(f"evidence for {family!r}: input_fingerprint is required")
    if _compact_date(as_of_max) != _compact_date(trade_date):
        raise ValueError(f"evidence for {family!r}: as_of_max must equal trade_date")
    if not requested_fp or requested_fp != observed_fp or observed_fp != usable_fp:
        raise ValueError(f"evidence for {family!r}: ticker identity mismatch")
~~~

Pass scored into build_quality_summary() from src/main.py. Validate every requested ticker has finite required score components before producing success evidence.

- [ ] **Step 4: Remove the second Auto readiness gate**

In src/screening/auto_pipeline.py, derive publication status only from QualityDecision:

~~~python
decision = assess_auto_quality(payload)
manifest_status = AutoRunStatus.HEALTHY if decision.healthy else AutoRunStatus.DEGRADED
~~~

Keep legacy ticker readiness only as a diagnostic projection. It must not change manifest_status or canonical-versus-attempt selection.

- [ ] **Step 5: Run Auto quality and publication tests**

Run:

~~~bash
uv run pytest tests/screening/test_scoring_feature_quality.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_auto_pipeline_publication.py \
  tests/test_main_auto_feature_quality.py -q
~~~

Expected: PASS.

- [ ] **Step 6: Commit**

~~~bash
git add src/screening/scoring_feature_quality.py \
  src/screening/scoring_feature_store.py src/main.py \
  src/screening/auto_pipeline.py \
  tests/screening/test_scoring_feature_quality.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_auto_pipeline_publication.py \
  tests/test_main_auto_feature_quality.py
git commit -m "fix: enforce auto evidence conservation"
~~~

---

### Task 3: Preserve truthful provider outcomes through consumption

**Files:**
- Modify: src/screening/scoring_feature_refresh.py
- Modify: src/screening/scoring_feature_store.py
- Modify: src/screening/optional_feature_store.py
- Test: tests/screening/test_scoring_feature_refresh.py
- Test: tests/screening/test_scoring_feature_store.py
- Test: tests/screening/test_optional_feature_store.py

**Interfaces:**
- Consumes: requested ticker sequence and per-source provider results.
- Produces: atomic producer manifest with ticker_outcomes and family observation status.
- Produces: explicit OptionalObservation(status, values, source_fingerprint).

- [ ] **Step 1: Add failing partial, timeout, and optional-empty tests**

~~~python
def test_one_failed_event_source_remains_partial_through_quality_summary(tmp_path):
    producer = event_outcome(news="success_empty", insider="failed")
    write_producer_manifest(tmp_path, producer)
    quality = ScoringFeatureStore(root=tmp_path).build_quality_summary(
        "20260713",
        ["000001"],
        finite_score_outputs(["000001"]),
    )
    assert quality["scoring_features"]["event_inputs"]["observation_status"] == "partial"


def test_timeout_conserves_every_requested_ticker(monkeypatch, tmp_path):
    result = refresh_scoring_features(
        "20260713",
        ["000001", "000002"],
        timeout_seconds=0.01,
        reports_dir=tmp_path,
    )
    assert set(result["ticker_outcomes"]) == {"000001", "000002"}
    assert result["failure_count"] == 1


def test_missing_optional_snapshot_is_unavailable_not_observed_empty(tmp_path):
    quality = OptionalFeatureStore(base_dir=tmp_path).build_quality_summary(
        "20260713", ["000001"]
    )
    assert quality["intraday_short_trade_metrics"]["observation_status"] == "unavailable"
~~~

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

~~~bash
uv run pytest tests/screening/test_scoring_feature_refresh.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_optional_feature_store.py \
  -k "partial_through or timeout_conserves or unavailable_not_observed" -v
~~~

Expected: producer partial is promoted, timeout outcomes disappear, or a missing optional file is reported success.

- [ ] **Step 3: Preserve per-ticker producer status**

Serialize a ticker_outcomes mapping and aggregate status from all required sub-sources:

~~~python
def _event_status(news: SourceObservation, insider: SourceObservation) -> ObservationStatus:
    statuses = {news.status, insider.status}
    if statuses == {ObservationStatus.SUCCESS}:
        return ObservationStatus.SUCCESS
    if ObservationStatus.SUCCESS in statuses or ObservationStatus.PARTIAL in statuses:
        return ObservationStatus.PARTIAL
    if ObservationStatus.FAILED in statuses:
        return ObservationStatus.FAILED
    return ObservationStatus.UNAVAILABLE
~~~

On timeout, mark every unfinished ticker failed before returning and shut down the executor without waiting:

~~~python
for future in pending:
    future.cancel()
    ticker = futures[future]
    outcomes[ticker] = failed_ticker_outcome(ticker, "provider_timeout")
executor.shutdown(wait=False, cancel_futures=True)
~~~

Write the producer manifest with src.utils.atomic_files.atomic_write_json().

- [ ] **Step 4: Separate optional unavailable from authoritative empty**

Return an explicit observation object from OptionalFeatureStore loaders:

~~~python
@dataclass(frozen=True)
class OptionalObservation:
    status: ObservationStatus
    values: Mapping[str, object]
    source_fingerprint: str | None
~~~

Only ObservationStatus.SUCCESS may call note_observed(); missing or malformed files call note_consumption_failure() and remain unavailable or failed.

- [ ] **Step 5: Run producer/store tests**

Run:

~~~bash
uv run pytest tests/screening/test_scoring_feature_refresh.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_optional_feature_store.py -q
~~~

Expected: PASS.

- [ ] **Step 6: Commit**

~~~bash
git add src/screening/scoring_feature_refresh.py \
  src/screening/scoring_feature_store.py \
  src/screening/optional_feature_store.py \
  tests/screening/test_scoring_feature_refresh.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_optional_feature_store.py
git commit -m "fix: preserve scoring provider outcomes"
~~~

---

### Task 4: Produce one immutable Daily Action refresh result

**Files:**
- Create: src/screening/offensive/pit_evidence.py
- Modify: src/screening/offensive/cache_readiness.py
- Modify: src/screening/offensive/cache_refresh.py
- Modify: src/main.py
- Create: tests/offensive/test_pit_evidence.py
- Test: tests/offensive/test_cache_readiness.py
- Test: tests/offensive/test_daily_action_cache_refresh.py
- Test: tests/test_main_auto_cache_refresh.py

**Interfaces:**
- Produces: canonical_price_fingerprint(frame, ticker, signal_date) -> str.
- Produces: canonical_flow_fingerprint(records, ticker, signal_date) -> str.
- Produces: refresh_daily_action_caches(...) -> DailyActionRefreshResult.
- DailyActionRefreshResult.outcomes is a MappingProxyType with exactly the frozen universe keys.

- [ ] **Step 1: Add failing one-batch, tri-state, immutability, and conservation tests**

~~~python
def test_refresh_fetches_daily_batch_once_when_there_are_no_limit_ups(tmp_path):
    fetch = Mock(return_value=daily_batch([("000001", 1.0)]))
    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=tmp_path / "price",
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        fetch_daily_prices_batch=fetch,
        target_tickers=["000001"],
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )
    assert fetch.call_count == 1
    assert result.universe_tickers == ("000001",)


def test_suspension_failure_is_unavailable_not_empty():
    evidence = load_suspension_evidence("20260713", fetch_fn=Mock(side_effect=RuntimeError("down")))
    assert evidence.status is SuspensionEvidenceStatus.UNAVAILABLE


def test_refresh_result_freezes_nested_mappings(refresh_result):
    with pytest.raises(TypeError):
        refresh_result.outcomes["000002"] = refresh_result.outcomes["000001"]
    with pytest.raises(TypeError):
        refresh_result.outcomes["000001"].evidence_fingerprints["price"] = "forged"
~~~

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

~~~bash
uv run pytest tests/offensive/test_pit_evidence.py \
  tests/offensive/test_cache_readiness.py \
  tests/offensive/test_daily_action_cache_refresh.py \
  -k "once_when or unavailable_not_empty or freezes_nested" -v
~~~

Expected: legacy stats are returned, the batch may be fetched twice, or nested mappings remain mutable.

- [ ] **Step 3: Implement canonical PIT fingerprints**

Use canonical JSON with normalized decimal strings and sorted rows:

~~~python
def canonical_fingerprint(kind: str, ticker: str, rows: Sequence[Mapping[str, object]]) -> str:
    payload = {
        "kind": kind,
        "ticker": ticker,
        "rows": [dict(sorted(row.items())) for row in rows],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
~~~

Price and flow adapters must filter date <= signal_date before calling canonical_fingerprint().

- [ ] **Step 4: Freeze refresh models**

In DailyActionRefreshResult.__post_init__ require exact key equality and freeze nested mappings:

~~~python
if set(self.outcomes) != set(self.universe_tickers):
    raise ValueError("outcomes must exactly cover the frozen universe")
frozen_outcomes = {
    ticker: replace(
        outcome,
        evidence_fingerprints=MappingProxyType(dict(outcome.evidence_fingerprints)),
    )
    for ticker, outcome in self.outcomes.items()
}
object.__setattr__(self, "outcomes", MappingProxyType(frozen_outcomes))
~~~

- [ ] **Step 5: Return DailyActionRefreshResult directly**

Resolve the daily batch before limit-up extraction and retain it regardless of whether any limit-up exists. Freeze universe before writes. Create explicit NOT_ATTEMPTED outcomes for quota-omitted tickers. Return:

~~~python
return DailyActionRefreshResult(
    trade_date=trade_date_value,
    universe_tickers=frozen_universe,
    universe_fingerprint=universe_fingerprint(frozen_universe),
    daily_batch_fingerprint=daily_batch_fingerprint,
    suspension_evidence=suspension_evidence,
    outcomes=outcomes,
    stats=derive_stats_from_outcomes(
        outcomes,
        industry_index_total=industry_stats.industry_index_total,
        industry_index_failed=industry_stats.industry_index_failed,
        limit_up_injected=len(injected),
    ),
)
~~~

Change main refresh orchestration to retain this result; do not convert it to flat counters before readiness publication.

- [ ] **Step 6: Run cache and main tests**

Run:

~~~bash
uv run pytest tests/offensive/test_pit_evidence.py \
  tests/offensive/test_cache_readiness.py \
  tests/offensive/test_daily_action_cache_refresh.py \
  tests/test_main_auto_cache_refresh.py -q
~~~

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add src/screening/offensive/pit_evidence.py \
  src/screening/offensive/cache_readiness.py \
  src/screening/offensive/cache_refresh.py src/main.py \
  tests/offensive/test_pit_evidence.py \
  tests/offensive/test_cache_readiness.py \
  tests/offensive/test_daily_action_cache_refresh.py \
  tests/test_main_auto_cache_refresh.py
git commit -m "fix: freeze daily action refresh evidence"
~~~

---

### Task 5: Publish and validate strict readiness manifest v2

**Files:**
- Modify: src/screening/offensive/setup_data_contracts.py
- Rewrite: src/screening/offensive/daily_action_readiness.py
- Modify: src/main.py
- Test: tests/offensive/test_setup_data_contracts.py
- Test: tests/offensive/test_daily_action_readiness.py
- Create: tests/offensive/test_daily_readiness_v2_security.py
- Test: tests/test_main_auto_cache_refresh.py

**Interfaces:**
- Produces: DAILY_ACTION_READINESS_SCHEMA_VERSION = 2.
- Produces: DailyActionReadinessManifest.content_fingerprint.
- Produces: parse_manifest_v2(raw: Mapping[str, object]) -> DailyActionReadinessManifest.
- Produces: publish_daily_action_readiness(manifest, reports_dir, *, attempt_reason=None) -> DailyActionReadinessPublication.

- [ ] **Step 1: Add failing schema and authorization tests**

~~~python
def test_v2_rejects_string_booleans(valid_manifest_dict):
    valid_manifest_dict["ticker_readiness"]["000001"]["capabilities"]["btst_breakout"][
        "plan_eligible"
    ] = "false"
    with pytest.raises(ManifestValidationError, match="plan_eligible"):
        parse_manifest_v2(valid_manifest_dict)


def test_v2_rejects_unknown_policy_and_forged_universe(valid_manifest_dict):
    valid_manifest_dict["policy_versions"]["setup_requirements"] = "unknown"
    valid_manifest_dict["universe_fingerprint"] = "sha256:forged"
    with pytest.raises(ManifestValidationError):
        parse_manifest_v2(valid_manifest_dict)


def test_refresh_failure_writes_attempt_and_preserves_canonical(tmp_path, valid_manifest):
    canonical = tmp_path / "daily_action_readiness_20260713.json"
    canonical.write_bytes(b'{"existing":true}')
    publication = publish_daily_action_attempt(
        trade_date=date(2026, 7, 13),
        run_id="failed-run",
        reports_dir=tmp_path,
        reasons=("refresh_failed",),
    )
    assert canonical.read_bytes() == b'{"existing":true}'
    assert publication.artifact_path.name == (
        "daily_action_readiness_attempt_20260713_failed-run.json"
    )
~~~

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

~~~bash
uv run pytest tests/offensive/test_daily_action_readiness.py \
  tests/offensive/test_daily_readiness_v2_security.py \
  -k "string_booleans or unknown_policy or writes_attempt" -v
~~~

Expected: schema v1 accepts the forged values or no attempt artifact is produced.

- [ ] **Step 3: Define complete shared evidence and capability identity**

SharedReadinessEvidence must serialize the actual verified values, not only claimed fingerprints:

~~~python
@dataclass(frozen=True)
class SharedReadinessEvidence:
    regime_row: Mapping[str, object]
    industry_by_ticker: Mapping[str, str]
    industry_day_pct: Mapping[str, float]
    security_status_by_ticker: Mapping[str, str]
    regime_fingerprint: str
    industry_fingerprint: str
    security_fingerprint: str
    board_rule_version: str
    normalization_version: str
    signal_session_policy_version: str
~~~

SetupCapability.consumed_fingerprint is required whenever plan_eligible is true.

- [ ] **Step 4: Implement strict v2 parsing and canonical identity**

Use exact type helpers, validate key equality and recompute fingerprints:

~~~python
def require_bool(raw: Mapping[str, object], key: str) -> bool:
    value = raw.get(key)
    if type(value) is not bool:
        raise ManifestValidationError(f"{key} must be bool")
    return value


if tuple(sorted(universe_tickers)) != universe_tickers:
    raise ManifestValidationError("universe_tickers must be sorted")
if set(ticker_readiness) != set(universe_tickers):
    raise ManifestValidationError("ticker_readiness must exactly cover universe")
if universe_fingerprint(universe_tickers) != claimed_universe_fingerprint:
    raise ManifestValidationError("universe_fingerprint mismatch")
if capability.plan_eligible and (
    not capability.enabled
    or not capability.scannable
    or capability.degraded
    or not capability.consumed_fingerprint
):
    raise ManifestValidationError("plan_eligible capability invariant failed")
~~~

Compute content_fingerprint from the manifest dictionary with content_fingerprint omitted, then require exact equality during parse.

- [ ] **Step 5: Make main publish from FrozenRefreshResult only**

Replace _publish_daily_action_readiness_for_auto(trade_date, cache_summary) with:

~~~python
def _publish_daily_action_readiness_for_auto(
    refresh_result: DailyActionRefreshResult,
    *,
    reports_dir: Path,
    shared_evidence: SharedReadinessEvidence,
) -> DailyActionReadinessPublication:
    manifest = build_daily_action_readiness(
        refresh_result,
        shared_evidence,
        run_id=new_readiness_run_id(refresh_result),
        oversold_bounce_enabled=oversold_bounce_enabled_from_env(),
    )
    return publish_daily_action_readiness(manifest, reports_dir)
~~~

If refresh fails or shared evidence cannot be built, call publish_daily_action_attempt() and leave canonical unchanged.

- [ ] **Step 6: Run readiness and main tests**

Run:

~~~bash
uv run pytest tests/offensive/test_setup_data_contracts.py \
  tests/offensive/test_daily_action_readiness.py \
  tests/offensive/test_daily_readiness_v2_security.py \
  tests/test_main_auto_cache_refresh.py -q
~~~

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add src/screening/offensive/setup_data_contracts.py \
  src/screening/offensive/daily_action_readiness.py src/main.py \
  tests/offensive/test_setup_data_contracts.py \
  tests/offensive/test_daily_action_readiness.py \
  tests/offensive/test_daily_readiness_v2_security.py \
  tests/test_main_auto_cache_refresh.py
git commit -m "fix: publish strict daily readiness v2"
~~~

---

### Task 6: Load a security-hardened immutable PIT snapshot

**Files:**
- Modify: src/utils/secure_files.py
- Rewrite: src/screening/offensive/daily_action_snapshot.py
- Test: tests/utils/test_secure_files.py
- Test: tests/offensive/test_daily_action_verified_snapshot.py
- Create: tests/offensive/test_daily_action_snapshot_security.py

**Interfaces:**
- Consumes: a validated DailyActionReadinessManifest v2.
- Produces: FrozenPriceRow and FrozenFlowRow tuples.
- Produces: VerifiedSetupContext with consumed_fingerprint.
- Produces: load_verified_daily_action_snapshot(...) -> VerifiedSnapshotResult.
- Produces: VerifiedDailyActionSnapshot.reference_price(ticker: str) -> float.

- [ ] **Step 1: Add historical mutation and immutable-record tests**

~~~python
def test_historical_price_mutation_blocks_ticker(v2_snapshot_fixture):
    first = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
    mutate_price_close(v2_snapshot_fixture.price_path, date(2026, 7, 10), 999.0)
    second = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
    assert first.snapshot is not None
    assert second.ticker_blocks["000001"] == ("price_fingerprint_mismatch",)


def test_future_append_does_not_change_verified_snapshot(v2_snapshot_fixture):
    first = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
    append_future_price(v2_snapshot_fixture.price_path, date(2026, 7, 14), 20.0)
    second = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
    assert first.snapshot is not None
    assert second.snapshot is not None
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id


def test_snapshot_does_not_expose_mutable_dataframes(v2_snapshot_fixture):
    snapshot = load_verified_daily_action_snapshot(
        **v2_snapshot_fixture.loader_args
    ).snapshot
    assert snapshot is not None
    assert isinstance(snapshot.prices_by_ticker["000001"], tuple)
~~~

- [ ] **Step 2: Add secure-read failure tests**

~~~python
def test_read_regular_bytes_rejects_ancestor_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "manifest.json").write_text("{}", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(SecureReadError):
        read_regular_bytes(linked / "manifest.json", max_bytes=1024)


def test_loader_rejects_invalid_utf8_manifest(tmp_path):
    path = tmp_path / "daily_action_readiness_20260713.json"
    path.write_bytes(b"\xff\xfe")
    result = load_verified_daily_action_snapshot(
        date(2026, 7, 13), reports_dir=tmp_path, data_dir=tmp_path
    )
    assert result.global_reason == "readiness_manifest_invalid"
~~~

- [ ] **Step 3: Run focused tests and confirm RED**

Run:

~~~bash
uv run pytest tests/utils/test_secure_files.py \
  tests/offensive/test_daily_action_verified_snapshot.py \
  tests/offensive/test_daily_action_snapshot_security.py \
  -k "historical_price_mutation or future_append or mutable_dataframes or ancestor_symlink or invalid_utf8" -v
~~~

Expected: historical mutation is accepted, DataFrames are exposed, or malformed inputs escape fail-closed handling.

- [ ] **Step 4: Harden secure reads**

Open each path component relative to a trusted directory descriptor using O_DIRECTORY and O_NOFOLLOW. After reading, compare the opened file identity with a fresh lstat of the path:

~~~python
opened = os.fstat(fd)
current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
    current.st_dev,
    current.st_ino,
    current.st_size,
    current.st_mtime_ns,
):
    raise SecureReadError("path changed while reading")
~~~

- [ ] **Step 5: Build immutable verified records**

Represent normalized inputs as frozen records:

~~~python
@dataclass(frozen=True)
class FrozenPriceRow:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    pct_change: Decimal | None


@dataclass(frozen=True)
class FrozenFlowRow:
    trade_date: date
    close: Decimal | None
    pct_change: Decimal | None
    main_net_inflow: Decimal


@dataclass(frozen=True)
class VerifiedSetupContext:
    ticker: str
    setup_name: str
    capability: SetupCapability
    prices: tuple[FrozenPriceRow, ...]
    fund_flow_records: tuple[FrozenFlowRow, ...]
    industry_day_pct: float | None
    regime: str
    consumed_fingerprint: str
~~~

Read each price/flow file once, filter PIT rows, recompute fingerprints, and compare them with the manifest. Use the manifest-bound industry, security, regime, and policy evidence; do not call legacy cache helpers after validation. Compute snapshot_id from manifest.content_fingerprint plus the sorted consumed fingerprints.

Implement reference_price() by returning the final verified close as float and raising KeyError when the ticker has no verified price rows.

- [ ] **Step 6: Run snapshot and security tests**

Run:

~~~bash
uv run pytest tests/utils/test_secure_files.py \
  tests/offensive/test_daily_action_verified_snapshot.py \
  tests/offensive/test_daily_action_snapshot_security.py -q
~~~

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add src/utils/secure_files.py \
  src/screening/offensive/daily_action_snapshot.py \
  tests/utils/test_secure_files.py \
  tests/offensive/test_daily_action_verified_snapshot.py \
  tests/offensive/test_daily_action_snapshot_security.py
git commit -m "fix: verify immutable pit snapshots"
~~~

---

### Task 7: Carry and revalidate candidate provenance

**Files:**
- Modify: src/screening/offensive/daily_action.py
- Modify: src/screening/offensive/daily_action_service.py
- Modify: src/screening/offensive/ledger_repository.py
- Modify: src/cli/dispatcher.py
- Test: tests/offensive/test_daily_action_snapshot_scan.py
- Create: tests/offensive/test_daily_action_service_snapshot_gate.py
- Test: tests/offensive/test_ledger_repository.py
- Test: tests/offensive/test_daily_action_v2_integration.py

**Interfaces:**
- Produces: DailyActionScan.snapshot_id and setup_consumed_fingerprint per candidate.
- Produces: PlanCandidate with signal_date, snapshot_id, setup_consumed_fingerprint, detector_degraded.
- Produces: verified PlanProvenance for every snapshot-authorized plan.

- [ ] **Step 1: Add detector-degraded and provenance mismatch tests**

~~~python
def test_detector_degraded_hit_is_display_only(verified_snapshot, monkeypatch):
    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: degraded_hit_result(),
    )
    scan = scan_from_verified_snapshot(verified_snapshot)
    assert scan.candidates == ()
    assert scan.blocked_candidates[0].reason == "detector_degraded"


def test_candidate_snapshot_mismatch_is_blocked(service, snapshot, valid_candidate):
    forged = replace(valid_candidate, snapshot_id="sha256:forged")
    run = service.run_from_snapshot(snapshot, (forged,))
    assert run.new_plans == ()
    assert run.ticker_gate_blocks[0].reasons == ("candidate_snapshot_mismatch",)


def test_snapshot_plan_persists_verified_provenance(service, repository, snapshot, valid_candidate):
    run = service.run_from_snapshot(snapshot, (valid_candidate,))
    trade = repository.get_trade(run.new_plans[0].trade_id)
    assert trade.provenance.verification_status == "verified"
    assert trade.provenance.snapshot_id == snapshot.snapshot_id
~~~

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

~~~bash
uv run pytest tests/offensive/test_daily_action_snapshot_scan.py \
  tests/offensive/test_daily_action_service_snapshot_gate.py \
  tests/offensive/test_ledger_repository.py \
  -k "detector_degraded or snapshot_mismatch or persists_verified" -v
~~~

Expected: degraded detector output is actionable, PlanCandidate lacks fields, or provenance is legacy_unverified.

- [ ] **Step 3: Add structured candidate identity**

Use these fields:

~~~python
@dataclass(frozen=True)
class PlanCandidate:
    ticker: str
    setup: str
    setup_version: str
    signal_date: date
    target_weight: float
    priority: int
    snapshot_id: str
    setup_consumed_fingerprint: str
    detector_degraded: bool = False
    authorization: RegimeAuthorization = RegimeAuthorization.NORMAL
~~~

DailyActionScan carries snapshot_id and candidates. Scanner must convert FrozenPriceRow tuples to a private detector DataFrame, then filter both capability.plan_eligible=false and result.degraded=true before ranking.

- [ ] **Step 4: Revalidate every field in service**

For each candidate, require:

~~~python
if candidate.signal_date != snapshot.signal_date:
    reasons.append("candidate_date_mismatch")
if candidate.snapshot_id != snapshot.snapshot_id:
    reasons.append("candidate_snapshot_mismatch")
if candidate.setup != context.setup_name:
    reasons.append("candidate_setup_mismatch")
if candidate.setup_consumed_fingerprint != context.consumed_fingerprint:
    reasons.append("candidate_consumed_fingerprint_mismatch")
if candidate.detector_degraded or not context.capability.plan_eligible:
    reasons.append("candidate_not_plan_eligible")
~~~

Do not accept a candidate merely because another setup on the ticker is scannable.

- [ ] **Step 5: Persist verified snapshot provenance**

Extend PlanProvenance with snapshot_id and setup_consumed_fingerprint. In the snapshot path, construct:

~~~python
return PlanProvenance(
    verification_status="verified",
    source_run_id=snapshot.manifest.run_id,
    manifest_fingerprint=snapshot.manifest.content_fingerprint,
    input_fingerprint=snapshot.manifest.input_fingerprint,
    ticker_cache_fingerprint=candidate.setup_consumed_fingerprint,
    snapshot_id=snapshot.snapshot_id,
    setup_consumed_fingerprint=candidate.setup_consumed_fingerprint,
    reference_price=snapshot.reference_price(candidate.ticker),
    order_type="next_session_open_proxy",
    board_rule_version=snapshot.board_rule_version,
    valid_on=entry_date,
    execution_cost_version=self.costs.version,
    authorization=RegimeAuthorization.NORMAL.value,
)
~~~

- [ ] **Step 6: Run scanner, service, and ledger tests**

Run:

~~~bash
uv run pytest tests/offensive/test_daily_action_snapshot_scan.py \
  tests/offensive/test_daily_action_service_snapshot_gate.py \
  tests/offensive/test_ledger_repository.py \
  tests/offensive/test_daily_action_v2_integration.py -q
~~~

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add src/screening/offensive/daily_action.py \
  src/screening/offensive/daily_action_service.py \
  src/screening/offensive/ledger_repository.py src/cli/dispatcher.py \
  tests/offensive/test_daily_action_snapshot_scan.py \
  tests/offensive/test_daily_action_service_snapshot_gate.py \
  tests/offensive/test_ledger_repository.py \
  tests/offensive/test_daily_action_v2_integration.py
git commit -m "fix: verify daily action candidate provenance"
~~~

---

### Task 8: Make Daily Action lifecycle-first and operator output truthful

**Files:**
- Modify: src/screening/offensive/daily_action_service.py
- Modify: src/screening/offensive/daily_action.py
- Modify: src/cli/dispatcher.py
- Modify: src/main.py
- Modify: tests/offensive/test_daily_action_v2_integration.py
- Modify: tests/test_cli_dispatcher.py
- Create: tests/offensive/test_daily_action_lifecycle_first.py
- Create: tests/test_operator_output_domains.py

**Interfaces:**
- Produces: DailyActionService.advance_lifecycle(as_of) -> LifecycleContext.
- Produces: DailyActionService.complete_run(context, *, snapshot, candidates, new_entry_block) -> DailyActionRun.
- Produces: independent Auto and Daily readiness operator summaries.

- [ ] **Step 1: Add lifecycle-first and output tests**

~~~python
def test_due_exit_runs_when_manifest_is_invalid(service, invalid_manifest_path):
    context = service.advance_lifecycle(date(2026, 7, 13))
    run = service.complete_run(
        context,
        snapshot=None,
        candidates=(),
        new_entry_block="readiness_manifest_invalid",
    )
    assert run.completed_exits[0].reason == "exit_filled"
    assert run.block_reasons == ("readiness_manifest_invalid",)


def test_cli_test_fixture_never_writes_workspace_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    run_daily_action_cli_fixture(reports_dir=reports_dir)
    assert not Path("data/reports").exists()


def test_default_output_distinguishes_three_no_plan_states():
    assert "系统健康，今日无信号" in render_no_signal()
    assert "仅供诊断的残缺 setup" in render_degraded_only()
    assert "数据护栏阻断新计划" in render_readiness_block()
~~~

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

~~~bash
uv run pytest tests/offensive/test_daily_action_lifecycle_first.py \
  tests/offensive/test_daily_action_v2_integration.py \
  tests/test_cli_dispatcher.py tests/test_operator_output_domains.py \
  -k "invalid or never_writes or three_no_plan" -v
~~~

Expected: ledger opens after snapshot work, tests write workspace reports, or output states are conflated.

- [ ] **Step 3: Split lifecycle from new-entry completion**

Move settlement, valuation, and open-position evaluation into advance_lifecycle(). complete_run() may only gate candidates, create plans, and build the view from the existing LifecycleContext.

Dispatcher order must be:

~~~python
with LedgerRepository(resolved_ledger_path, "daily-action-v2", 100_000.0, execution_costs=execution_costs) as repository:
    service = DailyActionService(
        repository,
        TradingSessionCalendar(open_sessions),
        cached_prices,
        execution_costs,
        shadow_history=cached_shadow_history,
    )
    context = service.advance_lifecycle(signal_date)
    verified = load_verified_daily_action_snapshot(
        signal_date,
        reports_dir=reports_dir,
        data_dir=data_dir,
    )
    if verified.snapshot is None:
        run = service.complete_run(
            context,
            snapshot=None,
            candidates=(),
            new_entry_block=verified.global_reason,
        )
    else:
        scan = scan_from_verified_snapshot(verified.snapshot)
        run = service.complete_run(
            context,
            snapshot=verified.snapshot,
            candidates=scan.candidates,
            new_entry_block=None,
        )
~~~

Catch loader and scanner exceptions after advance_lifecycle() and convert them into fail-closed new-entry blockers.

- [ ] **Step 4: Isolate all integration test paths**

Change _install_readiness_manifest() and CLI test helpers to require reports_dir and data_dir arguments rooted under tmp_path. Add an autouse guard that fails any test opening the repository root data/reports for writing.

- [ ] **Step 5: Render independent domain summaries**

Default Auto output must contain an Auto scoring status and a separate Daily Action readiness status with dynamic category counts. Map known codes to Chinese; raw codes and fingerprints appear only with --verbose. Treat regime_authorization_evidence_unavailable as a 10% sizing disclosure, not a fatal block.

- [ ] **Step 6: Run lifecycle, CLI, and output tests**

Run:

~~~bash
uv run pytest tests/offensive/test_daily_action_lifecycle_first.py \
  tests/offensive/test_daily_action_v2_integration.py \
  tests/test_cli_dispatcher.py tests/test_operator_output_domains.py -q
~~~

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add src/screening/offensive/daily_action_service.py \
  src/screening/offensive/daily_action.py src/cli/dispatcher.py src/main.py \
  tests/offensive/test_daily_action_v2_integration.py \
  tests/offensive/test_daily_action_lifecycle_first.py \
  tests/test_cli_dispatcher.py tests/test_operator_output_domains.py
git commit -m "fix: run daily action lifecycle before readiness"
~~~

---

### Task 9: Prove schema migration and the complete production path

**Files:**
- Replace: tests/offensive/fixtures/daily_readiness_20260713.json
- Create: tests/offensive/readiness_v2_testkit.py
- Modify: tests/test_e2e_pipeline_smoke.py
- Modify: tests/offensive/test_daily_action_v2_integration.py
- Create: tests/offensive/test_readiness_v2_migration.py
- Modify: AGENTS.md

**Interfaces:**
- Consumes: production Auto refresh orchestration with injected providers and temporary paths.
- Proves: Auto → FrozenRefreshResult → manifest v2 → verified snapshot → scanner → service → verified ledger.
- Produces: run_injected_auto_refresh_for_20260713(), run_full_injected_pipeline(), and run_pipeline_without_readiness_with_due_exit() test helpers with every path rooted below tmp_path.

- [ ] **Step 1: Build an isolated production-path test kit**

Create tests/offensive/readiness_v2_testkit.py with explicit path ownership:

~~~python
@dataclass(frozen=True)
class PipelineTestResult:
    publication: DailyActionReadinessPublication | None
    snapshot: VerifiedDailyActionSnapshot | None
    new_plans: tuple[ActionItem, ...]
    completed_exits: tuple[ActionItem, ...]
    ledger_trade: LedgerTrade | None


def run_injected_auto_refresh_for_20260713(root: Path) -> DailyActionReadinessPublication:
    data_dir = root / "data"
    reports_dir = data_dir / "reports"
    refresh_result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=data_dir / "price_cache",
        fund_flow_cache_dir=data_dir / "fund_flow_cache",
        snapshot_dir=data_dir / "snapshots",
        daily_prices_df=fixture_daily_batch_20260713(),
        target_tickers=fixture_universe_20260713(),
        backfill_price_history_fn=fixture_price_history,
        fund_flow_fetch_fn=fixture_fund_flow,
        industry_index_backfill_fn=fixture_industry_backfill,
        fund_flow_rate_limit_sec=0.0,
    )
    shared = fixture_shared_evidence(refresh_result)
    manifest = build_daily_action_readiness(
        refresh_result,
        shared,
        run_id="fixture-20260713-v2",
        oversold_bounce_enabled=False,
    )
    return publish_daily_action_readiness(manifest, reports_dir)
~~~

In the same module, fixture_universe_20260713(), fixture_daily_batch_20260713(), fixture_price_history(), fixture_fund_flow(), fixture_industry_backfill(), and fixture_shared_evidence() must return deterministic rows and must not read repository data.

- [ ] **Step 2: Replace the synthetic v1 fixture with a self-consistent v2 fixture**

Generate the fixture through run_injected_auto_refresh_for_20260713() in a temporary directory, then commit the resulting deterministic JSON. Its sorted universe must exactly match the current production resolver, including the current Beijing Stock Exchange exclusion. It must contain exact mutually exclusive outcome counts, shared evidence, per-setup consumed fingerprints, and a valid content fingerprint. Do not hand-edit claimed hashes.

- [ ] **Step 3: Add named end-to-end tests that the plan command selects**

~~~python
def test_20260713_production_readiness_v2_round_trip(tmp_path):
    publication = run_injected_auto_refresh_for_20260713(tmp_path)
    loaded = load_verified_daily_action_snapshot(
        date(2026, 7, 13),
        reports_dir=publication.artifact_path.parent,
        data_dir=tmp_path / "data",
    )
    assert loaded.snapshot is not None
    expected = tuple(read_fixture_manifest()["universe_tickers"])
    assert loaded.snapshot.universe_tickers == expected


def test_outside_auto_pool_ticker_reaches_verified_plan(tmp_path):
    result = run_full_injected_pipeline(
        tmp_path,
        auto_tickers={"000001"},
        daily_tickers={"000001", "002999"},
        btst_hit="002999",
    )
    assert [plan.ticker for plan in result.new_plans] == ["002999"]
    assert result.ledger_trade.provenance.verification_status == "verified"


def test_lifecycle_without_readiness_still_completes_exit(tmp_path):
    result = run_pipeline_without_readiness_with_due_exit(tmp_path)
    assert len(result.completed_exits) == 1
    assert result.new_plans == ()
~~~

- [ ] **Step 4: Add migration and idempotency tests**

~~~python
def test_schema_v1_is_read_only_and_has_no_new_entry_authority(tmp_path):
    write_v1_manifest(tmp_path)
    result = load_verified_daily_action_snapshot(
        date(2026, 7, 13), reports_dir=tmp_path, data_dir=tmp_path
    )
    assert result.snapshot is None
    assert result.global_reason == "readiness_schema_unsupported"


def test_repeat_verified_run_creates_one_plan_event(full_pipeline_fixture):
    first = full_pipeline_fixture.run()
    second = full_pipeline_fixture.run()
    assert first.plans[0].trade_id == second.plans[0].trade_id
    assert full_pipeline_fixture.repository.count_events(
        first.plans[0].trade_id, "PLAN_CREATED"
    ) == 1
~~~

- [ ] **Step 5: Run the required named E2E command**

Run:

~~~bash
uv run pytest tests/test_e2e_pipeline_smoke.py \
  tests/offensive/test_daily_action_v2_integration.py \
  -k "20260713 or outside_auto_pool or lifecycle_without_readiness" -v
~~~

Expected: at least three selected tests and all PASS. Zero selected tests is failure.

- [ ] **Step 6: Run the complete scoped matrix**

Run:

~~~bash
uv run pytest tests/screening/test_scoring_feature_quality.py \
  tests/screening/test_scoring_feature_refresh.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_auto_pipeline_publication.py -q
uv run pytest tests/offensive/ -q
uv run pytest tests/test_main_auto_cache_refresh.py \
  tests/test_main_auto_feature_quality.py tests/test_cli_dispatcher.py \
  tests/test_e2e_pipeline_smoke.py tests/test_operator_output_domains.py -q
uv run python -m compileall -q src
git diff --check
~~~

Expected: every command exits 0.

- [ ] **Step 7: Run adversarial counterexamples**

Run the dedicated tests for inconsistent Auto evidence, forged string booleans, historical mutation, detector degraded, candidate provenance mismatch, and lifecycle without readiness:

~~~bash
uv run pytest \
  tests/screening/test_scoring_feature_quality.py \
  tests/offensive/test_daily_readiness_v2_security.py \
  tests/offensive/test_daily_action_snapshot_security.py \
  tests/offensive/test_daily_action_service_snapshot_gate.py \
  tests/offensive/test_daily_action_lifecycle_first.py -v
~~~

Expected: PASS.

- [ ] **Step 8: Update operator documentation and commit**

Update AGENTS.md with schema v2 migration behavior, the one trusted evidence path, test isolation rule, and the requirement to rerun --auto after deployment. Do not change strategy-performance claims.

~~~bash
git add tests/offensive/fixtures/daily_readiness_20260713.json \
  tests/offensive/readiness_v2_testkit.py \
  tests/test_e2e_pipeline_smoke.py \
  tests/offensive/test_daily_action_v2_integration.py \
  tests/offensive/test_readiness_v2_migration.py AGENTS.md
git commit -m "test: prove readiness v2 production path"
~~~

---

## Final Acceptance Checklist

- [ ] Auto required success has conserved counts, exact ticker identity, exact trade date, input fingerprint, row sufficiency, and finite score outputs.
- [ ] Required event partial remains partial from provider through Auto publication.
- [ ] Optional unavailable is warning-only and cannot masquerade as authoritative empty success.
- [ ] Auto canonical status is decided once and is independent of Daily Action cache/readiness statistics.
- [ ] Daily Action uses one daily batch, one suspension snapshot, one frozen universe, and explicit not-attempted outcomes.
- [ ] Refresh or shared-evidence failure preserves the previous canonical and writes only an attempt.
- [ ] Readiness v2 rejects schema v1, forged identity, unknown policy, string booleans, empty fingerprints, and invalid capability invariants.
- [ ] Historical PIT mutation blocks the affected ticker; future append leaves the historical snapshot unchanged.
- [ ] Snapshot exposes immutable records and never reopens legacy cache helpers after verification.
- [ ] Detector-degraded and manifest-degraded hits are diagnostic-only.
- [ ] Every candidate and ledger plan has matching structured snapshot/setup provenance.
- [ ] Existing lifecycle advances before readiness/scanner work and survives every new-entry failure.
- [ ] Auto and Daily Action use the same authoritative 17:00 session resolver; weekend overrides fail closed.
- [ ] Default Chinese output distinguishes healthy no-signal, diagnostic-only degraded, and readiness-blocked states.
- [ ] Tests never write the workspace runtime data/reports or production ledger.
- [ ] The named E2E selector runs real tests rather than selecting zero.
- [ ] No strategy parameter, backtest artifact, or historical result changed.
