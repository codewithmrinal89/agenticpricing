"""Deterministic pricing engine.

All margin math happens here in plain Python -- no LLM involved. This
mirrors the "Deterministic Pricing Engine" + "Margin & Policy Rules" boxes
in the target architecture. The LLM never computes a number; it only
reasons about what these numbers mean.
"""
import json

from agents.policy_store import get_policy as _load_policy


def _resolve_thresholds(category: str, lifecycle_status: str, policy: dict) -> tuple[dict, bool]:
    thresholds = dict(policy["global"])
    thresholds.update(policy["category_overrides"].get(category, {}))

    lifecycle_override = policy["lifecycle_overrides"].get(lifecycle_status, {})
    lifecycle_requires_approval = lifecycle_override.get("requires_approval", False)
    if "min_margin_pct" in lifecycle_override:
        thresholds["min_margin_pct"] = lifecycle_override["min_margin_pct"]

    return thresholds, lifecycle_requires_approval


def _price_for_margin(cost: float, margin_pct: float) -> float:
    return round(cost / (1 - margin_pct / 100), 2)


def compute_recommendation(facts: dict) -> dict:
    """Compute a pricing recommendation for one part's facts packet. Pure math, no LLM."""
    policy = _load_policy()
    category = facts["category"]
    lifecycle_status = facts["lifecycle_status"]
    thresholds, lifecycle_requires_approval = _resolve_thresholds(category, lifecycle_status, policy)

    cost = facts["actual_cost"]
    current_price = facts["current_list_price"]
    current_margin_pct = (current_price - cost) / current_price * 100

    target_margin = thresholds["target_margin_pct"]
    recommended_price = _price_for_margin(cost, target_margin)
    price_change_pct = (recommended_price - current_price) / current_price * 100

    scenarios = {
        "low": _price_for_margin(cost, thresholds["min_margin_pct"]),
        "target": recommended_price,
        "high": _price_for_margin(cost, thresholds["max_margin_pct"]),
    }

    flags = []
    requires_approval = False

    if current_margin_pct < thresholds["min_margin_pct"]:
        flags.append(
            f"Current margin {current_margin_pct:.1f}% is below the "
            f"{thresholds['min_margin_pct']}% floor for this category/lifecycle."
        )
        requires_approval = True

    if lifecycle_requires_approval:
        flags.append(
            f"Lifecycle status '{lifecycle_status}' requires pricing leader approval regardless of margin."
        )
        requires_approval = True

    max_change = policy["global"]["max_price_increase_pct_without_approval"]
    if abs(price_change_pct) > max_change:
        flags.append(
            f"Recommended price change of {price_change_pct:.1f}% exceeds the "
            f"{max_change}% auto-approval threshold."
        )
        requires_approval = True

    if not facts.get("shipable", True):
        flags.append("Part is not currently shippable (zero available inventory).")

    return {
        "part_number": facts["part_number"],
        "description": facts.get("description"),
        "category": category,
        "lifecycle_status": lifecycle_status,
        "actual_cost": cost,
        "current_list_price": current_price,
        "current_margin_pct": round(current_margin_pct, 1),
        "thresholds": thresholds,
        "scenarios": scenarios,
        "recommended_price": recommended_price,
        "price_change_pct": round(price_change_pct, 1),
        "requires_approval": requires_approval,
        "flags": flags,
    }


if __name__ == "__main__":
    import sys
    from agents.supervisor import gather_all_facts

    part_number = sys.argv[1] if len(sys.argv) > 1 else "GE90-FB-7421"
    facts = gather_all_facts(part_number)
    print(json.dumps(compute_recommendation(facts), indent=2))
