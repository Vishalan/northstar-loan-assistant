"""The LLM agent loop, driven by a scripted fake with the SDK's streaming shape.

This checks our loop (tool rounds, parallel tool calls, events, grounding, voice gating), not model quality.
"""

from types import SimpleNamespace as NS

import pytest

from conftest import answer, login, turn


class FakeStream:
    def __init__(self, message):
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for block in self.message.content:
                if block.type == "text":
                    for i in range(0, len(block.text), 12):
                        yield NS(type="text", text=block.text[i:i + 12])
        return gen()

    async def get_final_message(self):
        return self.message


def msg(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop,
              usage=NS(input_tokens=1000, output_tokens=50, cache_read_input_tokens=900))


def text(t):
    return NS(type="text", text=t)


def tool(name, args, id_="tu_1"):
    return NS(type="tool_use", id=id_, name=name, input=args)


class FakeLLM:
    model = "fake"
    failover_model = None

    def __init__(self, script, rewrite=""):
        self.script = list(script)
        self.calls = []
        self.rewrite = rewrite

    def stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot: the loop appends later
        return FakeStream(self.script.pop(0))

    async def complete(self, **kwargs):
        return self.rewrite

    def disable_server_fallbacks_if(self, error):
        return False


async def run_with(api, fake, customer, question, channel="text"):
    auth = await login(api, customer)  # first request creates the services
    api._transport.app.state.services.llm = fake
    return await turn(api, auth, question, channel)


async def test_tool_round_then_grounded_answer(api):
    fake = FakeLLM([
        msg(tool("loans_explain_emi_change", {}), stop="tool_use"),
        msg(text("Your EMI went up from ₹17,195 to ₹17,416 because your rate was reset to 11.25% on 1 Oct 2026.")),
    ])
    events = await run_with(api, fake, "C1001", "Why did my EMI go up?")
    names = [e for e, _ in events]
    assert names.index("tool.started") < names.index("card") < names.index("answer.delta")
    assert ("answer.verified", True) in [(e, d.get("ok")) for e, d in events]
    assert next(d for e, d in events if e == "turn.completed")["mode"] == "llm"
    # tools are offered with eager streaming, system prompt cached, customer id never a parameter
    call = fake.calls[0]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert all(t["eager_input_streaming"] for t in call["tools"])
    assert "<session_context>" in call["messages"][-1]["content"]
    # second call carries the tool result back
    assert fake.calls[1]["messages"][-1]["content"][0]["type"] == "tool_result"


async def test_parallel_tool_calls_in_one_round(api):
    fake = FakeLLM([
        msg(tool("loans_explain_emi_change", {}, "tu_1"), tool("loans_prepayment_options", {"amount": 50000}, "tu_2"),
            stop="tool_use"),
        msg(text("Your EMI is now ₹17,416. Prepaying ₹50,000 saves ₹22,883 if you shorten the tenure.")),
    ])
    events = await run_with(api, fake, "C1001", "Why did my EMI change and what if I prepay 50,000?")
    started = [d["tool"] for e, d in events if e == "tool.started"]
    assert set(started) == {"loans_explain_emi_change", "loans_prepayment_options"}
    results = fake.calls[1]["messages"][-1]["content"]
    assert {r["tool_use_id"] for r in results} == {"tu_1", "tu_2"}  # all results in one user message
    assert "₹22,883" in answer(events)


async def test_invented_number_is_replaced(api):
    fake = FakeLLM([
        msg(tool("loans_prepayment_options", {"amount": 50000}), stop="tool_use"),
        msg(text("Prepaying ₹50,000 would save you about ₹41,950 in interest.")),
    ], rewrite="Prepaying saves ₹99,999.")  # the rewrite also fails, so the template is used
    events = await run_with(api, fake, "C1001", "What if I prepay 50,000?")
    verified = next(d for e, d in events if e == "answer.verified")
    assert verified["ok"] is False
    assert "₹41,950" not in verified["replaced_text"] and "₹22,883" in verified["replaced_text"]


async def test_voice_blocks_ungrounded_sentence_before_speaking(api):
    fake = FakeLLM([
        msg(tool("loans_loan_overview", {}), stop="tool_use"),
        msg(text("Your next EMI is ₹17,416. It is due on 5 Nov 2026. You also owe a late fee of ₹1,250. Anything else?")),
    ])
    events = await run_with(api, fake, "C1001", "What's my next EMI?", channel="voice")
    spoken = "".join(d["text"] for e, d in events if e == "answer.delta")
    assert "₹17,416" in spoken and "₹1,250" not in spoken


async def test_llm_error_falls_back_to_deterministic_planner(api):
    import anthropic
    import httpx

    class Broken(FakeLLM):
        def stream(self, **kwargs):
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    events = await run_with(api, Broken([]), "C1001", "What's my next EMI?")
    assert next(d for e, d in events if e == "turn.completed")["mode"] == "fallback"
    assert "₹17,416" in answer(events)


async def test_failover_model_takes_over_when_primary_errors(api):
    import anthropic
    import httpx

    class Flaky(FakeLLM):
        model, failover_model = "claude-haiku-5-5", "claude-opus-5-5"

        def stream(self, **kwargs):
            self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
            if kwargs["model"] == "claude-haiku-5-5":
                raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
            return FakeStream(self.script.pop(0))

    fake = Flaky([msg(tool("loans_loan_overview", {}), stop="tool_use"),
                  msg(text("Your next EMI is ₹17,416, due on 5 Nov 2026."))])
    events = await run_with(api, fake, "C1001", "What's my next EMI?")
    done = next(d for e, d in events if e == "turn.completed")
    assert done["mode"] == "llm" and done["model"] == "claude-opus-5-5"
    assert [c["model"] for c in fake.calls] == ["claude-haiku-5-5", "claude-opus-5-5", "claude-opus-5-5"]
    assert "₹17,416" in answer(events)


def test_swap_cost_and_server_fallback_gating():
    from types import SimpleNamespace as U

    from orchestrator.llm import LLM, PROVIDERS, cost_usd
    llm = LLM(PROVIDERS["native"], "test-key", "claude-haiku-5-5", "low", "claude-opus-5-5")
    llm.swap("claude-sonnet-5-5")
    assert llm.model == "claude-sonnet-5-5" and llm.failover_model == "claude-opus-5-5"
    llm.swap("claude-opus-5-5")
    assert llm.failover_model is None  # never fail over to itself
    with pytest.raises(ValueError):
        llm.swap("gpt-4")
    usage = U(input_tokens=1000, output_tokens=200, cache_read_input_tokens=5000, cache_creation_input_tokens=0)
    assert cost_usd("claude-haiku-5-5", usage) < cost_usd("claude-opus-5-5", usage) / 30
    # Haiku has no server-side refusal fallback: the beta must not be sent to it
    llm.swap("claude-haiku-5-5")
    stream = llm.stream(model="claude-haiku-5-5", system=[], tools=[], messages=[{"role": "user", "content": "hi"}])
    assert "beta" not in type(stream).__module__


async def test_admin_model_swap_endpoint(api):
    from orchestrator.llm import LLM, PROVIDERS
    await api.get("/healthz")
    await login(api, "C1001")
    api._transport.app.state.services.llm = LLM(PROVIDERS["native"], "test-key", "claude-haiku-5-5", "low", "claude-opus-5-5")
    assert (await api.put("/v1/admin/model", json={"model": "claude-sonnet-5-5"})).status_code == 401
    r = await api.put("/v1/admin/model", json={"model": "claude-sonnet-5-5"}, headers={"x-admin-token": "dev-admin-token"})
    assert r.status_code == 200 and r.json()["model"] == "claude-sonnet-5-5"
    r = await api.put("/v1/admin/model", json={"model": "nope"}, headers={"x-admin-token": "dev-admin-token"})
    assert r.status_code == 400


def test_dotenv_does_not_override_real_env(tmp_path, monkeypatch):
    from orchestrator import config
    monkeypatch.setattr(config, "BACKEND_DIR", tmp_path / "backend")
    (tmp_path / "backend").mkdir()
    (tmp_path / ".env").write_text("NS_TEST_A=from_file  # comment\nNS_TEST_B='quoted'\n# NS_TEST_C=x\n")
    monkeypatch.setenv("NS_TEST_A", "from_env")
    monkeypatch.delenv("NS_TEST_B", raising=False)
    config.load_dotenv()
    import os
    assert os.environ["NS_TEST_A"] == "from_env" and os.environ["NS_TEST_B"] == "quoted"
    assert "NS_TEST_C" not in os.environ


def test_proxy_provider_only_allows_models_it_really_serves():
    from orchestrator.llm import LLM, PROVIDERS, same_model
    llm = LLM(PROVIDERS["abhi"], "test-key", "claude-haiku-5-5", "low")
    # the proxy answered claude-haiku-5-5 with claude-opus-4-8, so it is not allowed there
    assert llm.model == "claude-haiku-4-5" and llm.failover_model == "claude-opus-5-5"
    assert llm.warnings and "claude-haiku-5-5" in llm.warnings[0]
    assert str(llm.client.base_url).startswith("https://opus.abhibots.com")
    assert llm.use_server_fallbacks is False
    assert llm._kwargs("claude-haiku-4-5") == {}  # no effort on Haiku 4.5
    assert llm._kwargs("claude-opus-5-5") == {"output_config": {"effort": "low"}}
    with pytest.raises(ValueError):
        llm.swap("claude-haiku-5-5")
    assert same_model("claude-haiku-4-5", "claude-haiku-4-5-20251001")
    assert not same_model("claude-haiku-5-5", "claude-opus-4-8")


def test_self_hosted_provider_takes_any_model_and_ignores_claude_settings(monkeypatch):
    from orchestrator.config import Settings
    from orchestrator.llm import LLM, load_providers
    monkeypatch.setenv("SELFHOSTED_LLM_URL", "http://gpu-box:11434")
    monkeypatch.setenv("MODEL_PLANNER", "claude-haiku-5-5")
    monkeypatch.setenv("MODEL_FAILOVER", "claude-opus-5-5")
    monkeypatch.delenv("SELFHOSTED_MODEL", raising=False)
    monkeypatch.delenv("SELFHOSTED_FAILOVER", raising=False)
    provider = load_providers()["selfhosted"]
    assert provider.has_credentials()  # a URL is enough; no key needed
    model, failover = Settings().models_for(provider)
    assert (model, failover) == ("qwen3:14b", None)  # MODEL_PLANNER names a Claude id, not sent to Ollama
    llm = LLM(provider, None, model, "low", failover)
    assert str(llm.client.base_url).startswith("http://gpu-box:11434")
    assert llm._kwargs(model) == {"thinking": {"type": "disabled"}} and llm.use_server_fallbacks is False
    llm.swap("qwen2.5-coder:14b")
    assert llm.model == "qwen2.5-coder:14b"
    monkeypatch.setenv("SELFHOSTED_MODEL", "llama3.3:70b")
    assert Settings().models_for(provider)[0] == "llama3.3:70b"


def test_providers_are_data(tmp_path, monkeypatch):
    from orchestrator.llm import load_providers
    path = tmp_path / "providers.yaml"
    path.write_text("gateway:\n  kind: anthropic\n  key_env: GATEWAY_KEY\n  base_url: https://llm.internal\n"
                    "  models: [claude-haiku-5-5]\n  default_model: claude-haiku-5-5\n  default_failover: ''\n")
    monkeypatch.delenv("GATEWAY_KEY", raising=False)
    gateway = load_providers(path)["gateway"]
    assert not gateway.has_credentials()
    monkeypatch.setenv("GATEWAY_KEY", "k")
    assert gateway.has_credentials() and gateway.base_url == "https://llm.internal"


async def test_promise_without_tool_is_nudged_into_a_tool_call(api):
    fake = FakeLLM([
        msg(text("I'll check your foreclosure options now.")),           # announces, calls nothing
        msg(tool("loans_foreclosure_options", {}), stop="tool_use"),      # after the nudge
        msg(text("No. Your loan is in its lock-in until 20 Feb 2027.")),
    ])
    events = await run_with(api, fake, "C1003", "Can I foreclose my loan without a penalty?", channel="voice")
    assert [d["tool"] for e, d in events if e == "tool.started"] == ["loans_foreclosure_options"]
    assert "did not call" in fake.calls[1]["messages"][-1]["content"]
    assert "20 Feb 2027" in answer(events)


async def test_repeated_promise_falls_back_to_the_planner(api):
    fake = FakeLLM([msg(text("Let me check that for you.")), msg(text("I will look into your foreclosure options."))])
    events = await run_with(api, fake, "C1003", "Can I foreclose my loan without a penalty?")
    assert "loans_foreclosure_options" in [d["tool"] for e, d in events if e == "tool.started"]
    assert "20 Feb 2027" in answer(events)


def test_invented_years_are_caught():
    from orchestrator.grounding import collect_allowed, unsupported
    allowed = collect_allowed({"next_due_date": "2026-11-05", "last_emi_date": "2030-04-05"})
    assert unsupported("Your loan ends in April 2030.", allowed) == []
    assert unsupported("Your loan ends around October 2031.", allowed) == ["2031"]
