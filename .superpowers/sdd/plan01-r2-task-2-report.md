# Plan 01 Revision 2 — Task 2 report

## Preflight

Read the task brief, AGENTS.md, Plan 01 Task 2, and the specified governance,
authorization, trial, canary, broker, migration, and DR specification sections.

## TDD

Added the replacement portfolio-envelope tests and governance adversarial tests.
The first focused run collected eight tests and failed because the Revision 2
envelope and governance module did not yet exist.  Expanded the tests for
typed authorization status/fences, exact issuer capabilities, broker binding,
integer budgets, caps, recovery inheritance, activation candidates, and
sensitive manifests.

## Verification

`UV_CACHE_DIR=/private/tmp/ai_hedge_uv_cache uv run pytest tests/offensive/v3/contracts/test_authorization.py tests/offensive/v3/contracts/test_governance.py -v`
passes: 13 tests.

The full contracts suite currently has three expected legacy-interface failures
in `test_contract_hardening.py` and `test_ports.py`: those tests instantiate the
Revision 1 `CapitalAuthorization` RootModel / `EdgeAuthorization` payload,
which Task 2 replaces.  Task 3 is explicitly scheduled to remove those generic
stable port return types.

## Self-review / concerns

The contracts are storage-free candidates only; they do not sign, activate,
persist, send, or broker-submit anything.  Actual monotonicity across candidate
documents remains the future authority-store responsibility.  The temporary
legacy compatibility aliases in `authorization.py` must be removed when Task 3
updates the decision and port contracts.
