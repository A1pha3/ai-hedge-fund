"""v3 broker gateway: optional broker adapter, reconciliation, and DR.

This package holds the broker-neutral protocol boundary (Plan 07 Task 1),
the capability certification gate (Task 2), the SEND_CLAIMED dispatcher
(Task 3), execution-revision normalization (Task 4), paginated
reconciliation (Task 5), lifecycle scheduling (Task 6), credential/session
fencing and writer handoff (Task 7), and disaster recovery (Task 8).

Until every gate in this package is satisfied the production adapter stays
disabled (``BROKER_ADAPTER_NOT_CERTIFIED``); no real broker round trip
occurs.
"""
