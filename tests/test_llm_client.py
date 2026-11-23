"""Tests for agents/llm_client.py: retry/backoff behavior and tool-calling
loop instrumentation. Mocks the OpenAI client -- no real network calls.
"""
import httpx
import openai
import pytest

import agents.llm_client as llm_client
from agents.tracing import AgentExecutionRecorder


def _fake_rate_limit_error():
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError("rate limited", response=response, body=None)


class _FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_unset=True):
        return {"role": "assistant", "content": self.content}


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, content, usage=None):
        self.choices = [_FakeChoice(_FakeMessage(content=content))]
        self.usage = usage


def test_retries_on_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm_client, "BASE_DELAY_SECONDS", 0)  # don't actually sleep in tests
    calls = {"count": 0}

    class FakeCompletions:
        def create(self, model, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise _fake_rate_limit_error()
            return _FakeResponse('{"ok": true}', usage=_FakeUsage(10, 5))

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(llm_client, "get_client", lambda: FakeClient())

    response = llm_client.chat_completion_with_retry(messages=[])
    assert calls["count"] == 2  # failed once, retried, succeeded
    assert response.usage.prompt_tokens == 10


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(llm_client, "BASE_DELAY_SECONDS", 0)
    monkeypatch.setattr(llm_client, "MAX_RETRIES", 2)

    class FakeCompletions:
        def create(self, model, **kwargs):
            raise _fake_rate_limit_error()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(llm_client, "get_client", lambda: FakeClient())

    with pytest.raises(openai.RateLimitError):
        llm_client.chat_completion_with_retry(messages=[])


def test_tool_calling_loop_accumulates_tokens_and_records_tools(temp_db, monkeypatch):
    from agents.tracing import PipelineRunRecorder

    class FakeToolCallFunction:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class FakeToolCall:
        def __init__(self, id, name, arguments):
            self.id = id
            self.function = FakeToolCallFunction(name, arguments)

    responses = [
        _FakeResponse(
            None,
            usage=_FakeUsage(20, 3),
        ),
        _FakeResponse('{"part_number": "PN-1"}', usage=_FakeUsage(15, 8)),
    ]
    responses[0].choices[0].message.tool_calls = [FakeToolCall("call_1", "get_part_master", '{"part_number": "PN-1"}')]

    call_log = {"n": 0}

    def fake_create(**kwargs):
        resp = responses[call_log["n"]]
        call_log["n"] += 1
        return resp

    monkeypatch.setattr(llm_client, "chat_completion_with_retry", fake_create)
    monkeypatch.setattr(
        "agents.tools.TOOL_FUNCTIONS",
        {"get_part_master": lambda part_number: {"part_number": part_number, "found": True}},
        raising=False,
    )

    run_id = "run-1"
    with PipelineRunRecorder(run_id, "PN-1", "gpt-4o-mini") as run:
        with run.agent("Enterprise Data Retrieval Agent") as execution:
            result = llm_client.run_tool_calling_agent("sys", "user", [], execution=execution)

    assert result == {"part_number": "PN-1"}
    assert execution.prompt_tokens == 35  # 20 + 15 across both API calls
    assert execution.completion_tokens == 11  # 3 + 8

    from agents.tracing import list_tool_executions

    tools = list_tool_executions(execution.id)
    assert len(tools) == 1
    assert tools[0]["tool_name"] == "get_part_master"
