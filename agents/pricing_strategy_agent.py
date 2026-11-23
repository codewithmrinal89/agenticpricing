"""Pricing Strategy Agent.

Unlike the three data agents (which give the LLM tools to call), this
agent demonstrates the opposite pattern: we compute everything numeric
ourselves in pricing_engine.py first, then hand the *results* to the LLM
and ask it only to explain them in plain language. The model never does
arithmetic -- it only reasons about what numbers we already trust mean.

It produces a structured, multi-section rationale report (via JSON mode)
rather than a single short narrative -- the "why" behind auto-approve vs.
pending-review needs to be scannable section-by-section (margin, lifecycle,
price-change), not one paragraph.
"""
import json

from agents.llm_client import chat_completion_with_retry, estimate_cost_usd
from agents.pricing_engine import compute_recommendation

SYSTEM_INSTRUCTION = """You are a pricing strategist at an aerospace spare parts business,
writing a decision rationale report for a pricing analyst.

You will be given a JSON object containing a completed, deterministic margin
analysis for one part -- current price, cost, margin, a recommended price,
three pricing scenarios (low/target/high margin), policy thresholds, and any
policy flags that determine whether this part auto-approves or needs pricing
leader review.

Respond with ONLY a single JSON object (no markdown fences, no extra text)
with these exact keys:

- "narrative": a concise 2-3 sentence summary, for quick scanning
- "decision_summary": one sentence naming the single biggest driver of the
  auto-approve or pending-review outcome
- "margin_analysis": 2-3 sentences on the current margin vs. the floor and
  target thresholds, and what that means for this part
- "lifecycle_analysis": 2-3 sentences on what the lifecycle status (Active,
  Obsolete, or Life-Time-Buy) and shipability mean for this pricing decision
- "price_change_analysis": 2-3 sentences on the size of the recommended price
  change vs. the auto-approval threshold
- "recommendation": one clear, specific sentence on what should happen next
  (e.g. "Auto-approve and publish to ERP" or "Route to pricing leader for
  manual sign-off before publishing")

Reference the specific numbers given in each section. Do not invent or
recompute any number that isn't already in the input. If "flags" is empty,
say explicitly that no policy exceptions were found instead of skipping a
section.
"""


def recommend_price(facts: dict, execution=None) -> dict:
    """Run the Pricing Strategy Agent: deterministic math + LLM rationale report."""
    analysis = compute_recommendation(facts)

    response = chat_completion_with_retry(
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": json.dumps(analysis)},
        ],
        response_format={"type": "json_object"},
    )

    if execution is not None and response.usage is not None:
        execution.set_token_usage(
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            estimate_cost_usd(response.usage.prompt_tokens, response.usage.completion_tokens),
        )

    report = json.loads(response.choices[0].message.content)
    return {**analysis, **report}


if __name__ == "__main__":
    import sys
    from agents.supervisor import gather_all_facts

    part_number = sys.argv[1] if len(sys.argv) > 1 else "GE90-FB-7421"
    facts = gather_all_facts(part_number)
    result = recommend_price(facts)
    print(json.dumps(result, indent=2))
