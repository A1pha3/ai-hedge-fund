from __future__ import annotations

from scripts.run_btst_top3_experiments import _derive_action_semantics


def test_derive_action_semantics_distinguishes_primary_shadow_and_structural_roles():
    primary = _derive_action_semantics({"default_mode": "primary_controlled_follow_through"}, "go")
    shadow = _derive_action_semantics({"default_mode": "secondary_shadow_entry"}, "go")
    structural = _derive_action_semantics({"default_mode": "shadow_structural_candidate"}, "shadow_only")

    assert primary["action_tier"] == "primary_promote"
    assert primary["primary_eligible"] is True
    assert shadow["action_tier"] == "shadow_keep"
    assert shadow["primary_eligible"] is False
    assert structural["action_tier"] == "structural_shadow_hold"
    assert structural["primary_eligible"] is False