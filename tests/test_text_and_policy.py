"""Spoken numbers and times, the booking policy behind the simulated LLM, and the turn policy."""

import datetime as dt
import json

import pytest

from dcr import config
from dcr.agent.tools import ToolBox
from dcr.llm.brain import next_turn
from dcr.text.numbers import digit_string, entity_in_progress, parse_time
from dcr.turn import model as eot
from dcr.turn import policy


@pytest.mark.parametrize(
    ("text", "digits"),
    [
        ("zero one seven six three six seven nine five zero two five", "017636795025"),
        ("null eins sieben sechs drei sechs sieben neun", "01763679"),
        ("double seven three oh one", "77301"),
        ("seventeen sixty five", "1765"),
        ("einundzwanzig", "21"),
    ],
)
def test_spoken_digits(text, digits):
    assert digit_string(text) == digits


@pytest.mark.parametrize(
    ("text", "hhmm"),
    [
        ("half past two", "14:30"),
        ("two thirty", "14:30"),
        ("at ten o clock", "10:00"),
        ("um vierzehn uhr", "14:00"),
        ("halb drei", "14:30"),
        ("um zehn uhr dreißig", "10:30"),
        ("eleven fifteen please", "11:15"),
    ],
)
def test_spoken_times(text, hhmm):
    assert str(parse_time(text)) == hhmm


def test_a_half_dictated_number_is_open_and_a_whole_one_is_not():
    assert not entity_in_progress("my number is zero one seven six").complete
    assert entity_in_progress("my number is zero one seven six three six seven nine five zero two five").complete
    assert entity_in_progress("i would like a haircut").kind == "none"


def converse(lang, lines, today=dt.date(2026, 10, 26)):
    tb = ToolBox(today)
    msgs = [{"role": "system", "content": f"Today is {today} (Monday). Language: {lang}."}, {"role": "assistant", "content": "Hello"}]
    said = []
    for u in lines:
        msgs.append({"role": "user", "content": u})
        while True:
            r = next_turn(msgs)
            if "tool_call" in r:
                tc = r["tool_call"]
                res = tb.call(tc["name"], tc["arguments"])
                msgs.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {"id": "1", "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                        ],
                    }
                )
                msgs.append({"role": "tool", "tool_call_id": "1", "content": json.dumps(res)})
                continue
            msgs.append({"role": "assistant", "content": r["content"]})
            said.append(r["content"])
            break
    return tb, said


def test_booking_in_english_reads_back_and_books_only_after_a_yes():
    tb, said = converse(
        "en",
        [
            "i'd like to book a haircut",
            "tomorrow at ten o clock",
            "my name is anna berger",
            "zero one seven six three six seven nine five zero two five",
        ],
    )
    assert not tb.bookings and "Is that right?" in said[-1]
    tb, _ = converse(
        "en",
        [
            "i'd like to book a haircut",
            "tomorrow at ten o clock",
            "my name is anna berger",
            "zero one seven six three six seven nine five zero two five",
            "yes",
        ],
    )
    assert [(b.service, b.date, b.time, b.phone) for b in tb.bookings] == [("haircut", "2026-10-27", "10:00", "017636795025")]


def test_booking_in_german_with_a_taken_slot():
    tb, said = converse(
        "de",
        [
            "ich hätte gern einen termin zum haare schneiden",
            "am mittwoch um vierzehn uhr",
            "dann um halb drei",
            "lukas meier",
            "null eins fünf zwei drei vier fünf sechs sieben acht",
            "ja genau",
        ],
    )
    assert "vergeben" in said[1]
    assert [(b.date, b.time, b.name) for b in tb.bookings] == [("2026-10-28", "14:30", "Lukas Meier")]


def test_asking_for_a_person_transfers():
    tb, _ = converse("en", ["can i speak to a real person"])
    assert tb.transferred and not tb.bookings


def test_the_shipped_end_of_turn_model_was_validated_on_unseen_turns():
    doc = json.loads(eot.MODEL_PATH.read_text())
    assert doc["meta"]["valid"]["auc"] >= 0.85
    m = eot.load()
    assert m.probability("i would like to book a", "open") < 0.2 < 0.5 < m.probability("i would like to book a haircut tomorrow", "open")
    assert m.probability("yes", "confirm") > 0.8
    assert m.probability("tomorrow at", "time") < m.probability("tomorrow at ten", "time")


CFG = config.settings()


def test_turn_policy_waits_answers_and_speculates():
    assert policy.decide(100, "i'd like a haircut", "open", CFG).action == "wait"  # too early to tell
    early = policy.decide(150, "i would like to book a haircut tomorrow", "open", CFG)
    assert early.action == "speculate"  # too early to answer, not to start the LLM
    assert policy.decide(150, "i would like to book a", "open", CFG).action == "wait"
    assert policy.decide(250, "i would like to book a haircut tomorrow", "open", CFG).action == "respond"
    assert policy.decide(250, "i would like to book a", "open", CFG).action == "wait"
    assert policy.decide(1500, "i would like to book a", "open", CFG).action == "respond"  # max pause
    d = policy.decide(1500, "my number is zero one seven six", "phone", CFG)
    assert d.action == "wait" and d.entity_open  # mid-number: wait longer than usual
    assert policy.decide(2700, "my number is zero one seven six", "phone", CFG).action == "respond"
    assert policy.decide(900, "anything", "open", CFG, mode="silence").action == "respond"
    assert policy.decide(700, "anything", "open", CFG, mode="silence").action == "wait"


def test_barge_in_ignores_backchannels_holds_on_noise_and_stops_for_words():
    assert policy.barge_in(200, "", CFG) == "ignore"  # too short to be anything
    assert policy.barge_in(400, "mhm", CFG) == "ignore"
    assert policy.barge_in(400, "genau", CFG) == "ignore"
    assert policy.barge_in(400, "", CFG) == "hold"  # sound but no words yet: pause, ready to resume
    assert policy.barge_in(400, "sorry not wednesday", CFG) == "interrupt"
    assert policy.barge_in(1000, "", CFG) == "interrupt"  # too long for a backchannel, words or not


def test_barge_in_one_unknown_word_holds_but_a_stop_word_interrupts():
    assert policy.barge_in(400, "mech", CFG) == "hold"  # a misheard "mhm" must not cut the agent off
    assert policy.barge_in(400, "no", CFG) == "interrupt"
    assert policy.barge_in(400, "nein", CFG) == "interrupt"
    assert policy.barge_in(400, "wait a", CFG) == "interrupt"
    assert policy.barge_in(1200, "yeah okay", CFG) == "ignore"  # a long backchannel is still one


def test_a_number_given_in_answer_to_the_question_needs_no_cue_word():
    from dcr.text.numbers import entity_in_progress

    full = "sure it's zero one five two one two three four five six seven"
    assert not entity_in_progress(full).complete  # without context: a run of digits, maybe more to come
    assert entity_in_progress(full, "phone").complete
    assert not entity_in_progress("zero one five two one", "phone").complete
    assert policy.decide(300, full, "phone", CFG).action == "respond"


def test_flush_waits_for_a_real_pause_inside_a_number():
    assert not policy.flush_due(150, "my number is zero one seven six", "phone", CFG)
    assert policy.flush_due(700, "my number is zero one seven six", "phone", CFG)
    assert policy.flush_due(80, "i would like to book a haircut tomorrow", "open", CFG)
    assert not policy.flush_due(80, "", "open", CFG) and policy.flush_due(220, "", "open", CFG)
