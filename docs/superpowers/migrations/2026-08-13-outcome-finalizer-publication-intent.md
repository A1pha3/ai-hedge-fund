# Outcome Finalizer publication-intent proposal withdrawn (2026-08-13)

## Scope

No migration is applied. The proposed local `outcome_publication_intents`
table and its reachable code were removed before release after adversarial
testing proved that independent Finalizer databases cannot provide an
Evidence-namespace single-writer guarantee.

Two writers could prepare different revisions from the same base revision;
after one activation, retries could strand later prepared revisions behind an
activation gap. A local intent also could not establish the missing plan-line
to economic-lot/source binding, calendar completeness or exact correction
reduction.

`finalize_due` and `revise_outcome` now fail with
`outcome_input_authority_unavailable` before observing any dependency or
mutating any database. `register_plan_line` remains local candidate metadata.
`outcome_fact` is also unavailable: pre-gate evidence cannot prove the missing
authoritative inputs, and a local finalized marker is never authority. A future
historical reader requires an approved migration manifest that names the exact
admitted evidence generation and its store-owned input bindings.

## Compatibility and safety

- No publication-intent table, trigger or envelope is created.
- No OutcomeEvidence is published or revised by this component.
- Exact execution mode and signer-capability namespace checks still occur at
  construction, before the local database is created.
- Existing historical markers never constitute authority on their own.
- Re-enablement requires a store-owned exact line binding, cancellation-aware
  calendar, exact capital reducer and mechanically fenced writer/revision CAS.

This remains a disabled offline boundary. It activates no policy, capital
authority, execution permit, broker adapter, evidence promotion or production
trading path.
