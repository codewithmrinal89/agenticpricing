"""Approval Coordination Agent.

Only invoked when the Decision Gate routes a request to pricing leader
review. Drafts a short, formal approval request from the already-computed
pricing analysis -- again, writing only, never recomputing numbers.
"""
import json

from agents.llm_client import chat_completion_with_retry, estimate_cost_usd

SYSTEM_INSTRUCTION = """You are drafting an approval request for a pricing leader at an
aerospace spare parts business. You will receive a JSON pricing analysis for one part
that failed auto-approval.

Write a short, formal approval request (3-5 sentences) that:
1. States the part number, current price, and recommended price
2. Lists the specific reasons this needs review (from the "flags" field)
3. States the recommended action clearly

Respond with ONLY the approval request text -- no JSON, no markdown, no preamble.
"""


def draft_approval_request(pricing_analysis: dict, execution=None) -> str:
    """Draft a human-readable approval request for a flagged pricing decision."""
    response = chat_completion_with_retry(
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": json.dumps(pricing_analysis)},
        ],
    )
    if execution is not None and response.usage is not None:
        execution.set_token_usage(
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            estimate_cost_usd(response.usage.prompt_tokens, response.usage.completion_tokens),
        )
    return response.choices[0].message.content.strip()
