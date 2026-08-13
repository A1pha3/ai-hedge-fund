# Migration: BTST forward-runner input integrity

**Date:** 2026-08-13 (adversarial closure of the 2026-08-12 review)

**Scope:** paired shadow runner and deterministic replay only

**Authority impact:** none; the path remains shadow-only

The paired runner no longer calls the producer with an unwired `None`
snapshot and no longer invents candidate economics from a signal-envelope id.
The pure construction layer now requires exact verified inputs, but the
official forward entry point is intentionally disabled with
`forward_input_authority_unavailable` before producer, kernel, evidence or
capital side effects.

An exact `VerifiedDailyActionSnapshot` is still only an in-memory value. It
does not prove that the Evidence Store committed that snapshot, that all and
only the producer outputs belong to a complete ordered session batch, or that
governance sealed the exchange decision window. Official RUN/replay therefore
remains unavailable until the following three store-owned facts exist:

- a committed snapshot receipt rooted at the original signal cutoff;
- a session batch manifest binding count plus ordered candidate/record roots;
- a signed exchange decision-window artifact bound by the Trial/Stage.

The pure arm-input builder accepts only strict/frozen
`CommittedBtstCandidate(record, payload)` bindings. Security id, integer price
micros, typed industry and raw target-weight ppm come only from that payload;
there are no exchange, price, industry or sizing fallbacks. The type is a
binding DTO, not authority. The replay implementation can re-read individual
records and blobs, but it now rejects every non-cancelled signal timeline
before creating a replay target because it lacks the authoritative batch root.
This applies to both current-cost and 2×-slippage.

The disabled runner is a zero-capability object. Decision, market advance and
missed-session finalization all reject before reading the request, clock,
bundle, spine, pair store or target path. It cannot create `NO_RUN`, and even
an exact legacy pair plus terminal status cannot resume reserve work: those
rows do not bind the missing session-batch/window authority. Deterministic
construction remains available only as module-level pure builders for tests.

This migration does not implement Stage/calendar binding or independent arm
capital snapshots, and it does not make the standalone trial CLI operational.
