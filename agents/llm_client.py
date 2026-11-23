"""Shared OpenAI client with retry/backoff for rate limits and transient errors."""
import json
import os
import time

import openai
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = "gpt-4o-mini"
MAX_RETRIES = 5
BASE_DELAY_SECONDS = 5

# Approximate published OpenAI pricing for gpt-4o-mini (USD per 1K tokens).
# Advisory only -- update if MODEL changes. Used solely to populate
# estimated_cost_usd on persisted agent-execution traces.
PRICE_PER_1K_PROMPT_TOKENS = 0.00015
PRICE_PER_1K_COMPLETION_TOKENS = 0.0006


def estimate_cost_usd(prompt_tokens, completion_tokens) -> float:
    return round(
        prompt_tokens / 1000 * PRICE_PER_1K_PROMPT_TOKENS
        + completion_tokens / 1000 * PRICE_PER_1K_COMPLETION_TOKENS,
        6,
    )

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def chat_completion_with_retry(**kwargs):
    """Call client.chat.completions.create, retrying on rate-limit/server errors."""
    client = get_client()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return client.chat.completions.create(model=MODEL, **kwargs)
        except (openai.RateLimitError, openai.InternalServerError) as e:
            if attempt == MAX_RETRIES:
                raise
            delay = BASE_DELAY_SECONDS * attempt
            print(f"  [{type(e).__name__}] retrying in {delay}s (attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(delay)


def run_tool_calling_agent(
    system_instruction: str,
    user_message: str,
    tool_schemas: list[dict],
    execution=None,
) -> dict:
    """Shared manual tool-calling loop: send the request, execute any tool calls
    the model asks for, feed results back, repeat until it returns final JSON.

    Every specialist data agent (Enterprise Data Retrieval, Inventory &
    Shipability, Cost & Margin) uses this same loop -- only the system
    instruction and which tools it's handed differ.

    `execution` is an optional agents.tracing.AgentExecutionRecorder for the
    caller's current step. When provided, token usage is accumulated across
    every API call in this loop (a single agent execution can involve
    several round trips -- that's deliberately not conflated with "one
    execution = one API call"), and each tool call is persisted individually.
    """
    from agents.tools import TOOL_FUNCTIONS

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": user_message},
    ]
    total_prompt_tokens = 0
    total_completion_tokens = 0
    usage_seen = False

    while True:
        response = chat_completion_with_retry(messages=messages, tools=tool_schemas)
        if response.usage is not None:
            usage_seen = True
            total_prompt_tokens += response.usage.prompt_tokens
            total_completion_tokens += response.usage.completion_tokens
        message = response.choices[0].message

        if not message.tool_calls:
            if execution is not None and usage_seen:
                execution.set_token_usage(
                    total_prompt_tokens,
                    total_completion_tokens,
                    estimate_cost_usd(total_prompt_tokens, total_completion_tokens),
                )
            raw_text = message.content.strip()
            raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(raw_text)

        messages.append(message.model_dump(exclude_unset=True))

        for tool_call in message.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)
            print(f"  called {fn_name}({fn_args})")

            tool_started = time.monotonic()
            try:
                result = TOOL_FUNCTIONS[fn_name](**fn_args)
            except Exception as e:
                tool_duration_ms = int((time.monotonic() - tool_started) * 1000)
                if execution is not None:
                    execution.record_tool_execution(fn_name, fn_args, None, tool_duration_ms, str(e))
                raise
            tool_duration_ms = int((time.monotonic() - tool_started) * 1000)
            print(f"  -> result: {result}")

            if execution is not None:
                execution.record_tool_execution(fn_name, fn_args, result, tool_duration_ms)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result),
            })
