"""The LLM router against two simulated providers on real sockets: hedging, failover, stalls, breakers."""

import time

import pytest

from dcr import config
from dcr.llm.router import Done, LLMUnavailable, Router, StreamBroken, Text, ToolCall
from dcr.llm.sim_provider import Profile, make_app
from dcr.serve_util import Background

MSGS = [
    {"role": "system", "content": "Today is 2026-10-26 (Monday). Language: en."},
    {"role": "assistant", "content": "Hello"},
    {"role": "user", "content": "I would like a haircut tomorrow"},
]


@pytest.fixture
def providers():
    a, b = Profile(ttft_median_ms=120, ttft_sigma=0.01, seed=1), Profile(ttft_median_ms=150, ttft_sigma=0.01, seed=2)
    with Background(make_app(a, "primary")) as pa, Background(make_app(b, "secondary")) as pb:
        yield a, b, pa, pb


def router(pa, pb, **llm):
    s = config.settings(
        {"llm": {"providers": [{"name": "primary", "base_url": pa.url + "/v1"}, {"name": "secondary", "base_url": pb.url + "/v1"}], **llm}}
    )
    return Router(s)


async def collect(r, msgs=MSGS):
    out, t0 = [], time.monotonic()
    async for ev in r.stream(msgs):
        out.append(ev)
    return out, (time.monotonic() - t0) * 1000


async def test_the_primary_answers_when_it_is_healthy(providers):
    *_, pa, pb = providers
    r = router(pa, pb)
    out, _ = await collect(r)
    done = out[-1]
    assert isinstance(done, Done) and done.provider == "primary" and not done.hedged
    assert "".join(e.text for e in out if isinstance(e, Text)) == "And what time would suit you?"
    await r.aclose()


async def test_a_slow_first_token_is_hedged_to_the_next_provider(providers):
    a, _, pa, pb = providers
    a.ttft_median_ms = 3000
    r = router(pa, pb, hedge_after_ms=300)
    out, ms = await collect(r)
    done = out[-1]
    assert done.provider == "secondary" and done.hedged and done.attempts == ["primary", "secondary"]
    assert 400 < done.ttft_ms < 900 and ms < 1500  # hedge delay + the secondary's own time, not 3 s
    await r.aclose()


async def test_an_error_fails_over_at_once_without_waiting_for_the_hedge(providers):
    a, _, pa, pb = providers
    a.error_rate = 1.0
    r = router(pa, pb, hedge_after_ms=1000)
    out, _ = await collect(r)
    assert out[-1].provider == "secondary" and out[-1].ttft_ms < 600
    await r.aclose()


async def test_a_stream_that_stalls_after_speaking_is_reported(providers):
    a, _, pa, pb = providers
    a.stall_rate = 1.0
    r = router(pa, pb, stall_timeout_ms=300)
    with pytest.raises(StreamBroken) as e:
        await collect(r)
    assert e.value.provider == "primary" and e.value.emitted.startswith("And")
    await r.aclose()


async def test_a_failing_provider_is_skipped_once_its_circuit_opens(providers):
    a, _, pa, pb = providers
    a.error_rate = 1.0
    r = router(pa, pb, circuit={"failures": 2, "window_s": 30, "open_s": 60})
    for _ in range(2):
        out, _ = await collect(r)
        assert out[-1].attempts == ["primary", "secondary"]
    out, _ = await collect(r)
    assert out[-1].attempts == ["secondary"]  # primary's circuit is open: not even tried
    await r.aclose()


async def test_tool_calls_arrive_whole(providers):
    *_, pa, pb = providers
    r = router(pa, pb)
    msgs = [*MSGS[:-1], {"role": "user", "content": "a haircut tomorrow at ten please"}]
    out, _ = await collect(r, msgs)
    calls = [e for e in out if isinstance(e, ToolCall)]
    assert calls and calls[0].name == "check_availability" and calls[0].arguments["time"] == "10:00"
    await r.aclose()


async def test_no_provider_at_all_is_reported(providers):
    a, b, pa, pb = providers
    a.error_rate = b.error_rate = 1.0
    r = router(pa, pb)
    with pytest.raises(LLMUnavailable):
        await collect(r)
    await r.aclose()
