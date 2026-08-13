# Shadow lot-origin integrity cutover

**Date:** 2026-08-13

**Authority impact:** none; the official forward runner remains disabled and
this changes only the authority-free shadow lifecycle primitive.

The prior shadow adapter used `shadow_line_id` as an economic-lot identity and
used the lifecycle state's current `pair_key` when deriving and settling every
open lot. Reusing a line in overlapping signal cycles therefore merged two
positions, allowed a newer decision to postpone an older lot's T+10 mandate,
and let a current NoTrade pair block an existing position's exit.

New shadow entries derive separate collision-resistant position-lineage and
economic-lot ids from the canonical tuple `(trial, arm, decision cycle, line)`.
The adapter persists the origin atomically with its existing immutable
operation row. `shadow_lot_origins` is only an immutable extension containing
fields the parent operation does not already own: position/lot ids, frozen
target exit, exit ordinal, and lot size. Trial, arm, pair, decision, line,
security, entry session, and source binding remain single-sourced from
`shadow_proxy_operations` and are read through a join.

Exit derivation and settlement now resolve each capital lot through that
origin and revalidate the exact committed decision line. Company actions keep
the same lot identity; an exit bust reopens the same origin and forces a new
`REOPENED_BY_CORRECTION` mandate revision even when its economics otherwise
match the prior mandate. A newer NoTrade pair has no entry work and cannot
block old exits or close valuation.

There is deliberately no inferred backfill. A database containing legacy
`shadow_proxy_operations` without matching origin rows fails startup with
`shadow_lot_origin_cutover_required`. Because no official forward Trial has
started, operators must create a new shadow namespace/database. Guessing an
origin from a current pair, line id, or later capital projection is forbidden.
