"""Tests for agents/policy_store.py: the admin-editable pricing policy
(global thresholds + per-category/per-lifecycle overrides) that backs the
Admin dashboard's "Pricing policy" panel.
"""
import agents.policy_store as policy_store


def test_get_policy_returns_seeded_global(temp_catalog_db):
    policy = policy_store.get_policy()
    assert policy["global"]["min_margin_pct"] == 25.0
    assert policy["global"]["target_margin_pct"] == 40.0
    assert policy["category_overrides"] == {}
    assert policy["lifecycle_overrides"] == {}


def test_update_global_policy_partial(temp_catalog_db):
    updated = policy_store.update_global_policy({"min_margin_pct": 30.0})
    assert updated["min_margin_pct"] == 30.0
    assert updated["target_margin_pct"] == 40.0  # untouched


def test_set_and_clear_category_override(temp_catalog_db):
    policy_store.set_category_override("Avionics", target_margin_pct=45.0, min_margin_pct=28.0)
    policy = policy_store.get_policy()
    assert policy["category_overrides"]["Avionics"] == {"target_margin_pct": 45.0, "min_margin_pct": 28.0}

    policy_store.clear_category_override("Avionics")
    assert "Avionics" not in policy_store.get_policy()["category_overrides"]


def test_set_category_override_unknown_category_raises(temp_catalog_db):
    import pytest

    with pytest.raises(ValueError):
        policy_store.set_category_override("Nonexistent", 1, 2)


def test_set_and_clear_lifecycle_override(temp_catalog_db):
    policy_store.set_lifecycle_override("Obsolete", min_margin_pct=None, requires_approval=True, note="always review")
    policy = policy_store.get_policy()
    assert policy["lifecycle_overrides"]["Obsolete"]["requires_approval"] is True
    assert policy["lifecycle_overrides"]["Obsolete"]["note"] == "always review"

    policy_store.clear_lifecycle_override("Obsolete")
    assert "Obsolete" not in policy_store.get_policy()["lifecycle_overrides"]


def test_list_lifecycle_statuses(temp_catalog_db):
    assert policy_store.list_lifecycle_statuses() == ["Active", "Obsolete"]
