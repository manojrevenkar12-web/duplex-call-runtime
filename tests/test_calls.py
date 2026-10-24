"""Whole simulated phone calls through the real protocol, models and providers (real time)."""

import pytest
from conftest import needs_models

from dcr.sim import metrics, run
from dcr.sim.caller import Scenario

pytestmark = [needs_models, pytest.mark.models, pytest.mark.slow]


def test_a_booking_call_end_to_end() -> None:
    sc = Scenario.from_dict(
        {
            "id": "test-booking",
            "lang": "en",
            "today": "2026-10-26",
            "lines": ["i'd like to book a haircut please", "tomorrow at ten o'clock", "my name is anna berger",
                      "my number is zero one seven six three six seven nine five zero two five", "yes that's right"],
            "expect": {"booking": {"service": "haircut", "date": "2026-10-27", "time": "10:00", "name": "Anna Berger", "phone": "017636795025"}},
        }
    )  # fmt: skip
    import asyncio

    with run.stack() as st:
        tl, rec, _ = asyncio.run(run.call(st, sc))
    res = metrics.score(sc, tl, rec)
    assert res["task"] is True, rec["outcome"]
    assert res["false_stops"] == 0
    assert len(res["response_ms"]) >= 5
    assert all(r < 4000 for r in res["response_ms"])  # generous: CI runners are slow and shared
    kinds = {e["kind"] for e in rec["events"]}
    assert {"end_of_turn", "llm_first_token", "agent_audio_start", "tool"} <= kinds


def test_an_interruption_stops_the_agent() -> None:
    sc = Scenario.from_dict(
        {
            "id": "test-interrupt",
            "lang": "en",
            "today": "2026-10-26",
            "lines": ["what are your opening hours", {"interrupt": "no wait i just want to book a haircut", "after_agent_ms": 1500}],
            "expect": {"no_booking": True},
        }
    )
    import asyncio

    with run.stack() as st:
        tl, rec, _ = asyncio.run(run.call(st, sc))
    res = metrics.score(sc, tl, rec)
    stop = res["interrupts"][0]
    assert stop["was_talking"] and stop["stop_ms"] is not None and stop["stop_ms"] < 1500, stop
