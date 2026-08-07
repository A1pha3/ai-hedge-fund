"""Plan 05: producer pure-function layers (auto / btst).

Each producer is a pure function consuming a ``VerifiedDailyActionSnapshot``
and returning immutable ``SignalEvidence`` envelopes; services in
``services/auto_producer_api`` / ``services/btst_producer_api`` sign and
publish them through one EvidenceRepository per issuer namespace.
"""
