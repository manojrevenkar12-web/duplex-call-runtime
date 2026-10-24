"""When to answer, when to start thinking early, and when the caller is only saying "mhm".

The decisions are pure functions of what the session has measured (how long the caller has
been quiet, what they said, what the agent last asked), so they are tested without audio and
the same code runs in calls and in replays."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..text.numbers import entity_in_progress, words
from . import model as eot

BACKCHANNELS = {
    "mhm", "mm", "hmm", "mmhmm", "mm-hmm", "uh-huh", "m", "h", "uh", "huh", "yeah", "yep", "yes", "okay", "ok", "right", "sure", "alright", "i", "see",
    "ja", "genau", "aha", "achso", "ach", "so", "jaja", "gut", "stimmt", "klar", "richtig", "hm",
}  # fmt: skip

# one of these on its own is an interruption, not a backchannel
STOP_WORDS = {"no", "stop", "wait", "sorry", "hang", "hold", "actually", "nein", "stopp", "moment", "halt", "warten", "entschuldigung"}


@dataclass
class Decision:
    action: str  # wait | speculate | respond
    probability: float
    reason: str
    entity_open: bool


def decide(pause_ms: float, text: str, context: str, cfg: dict[str, Any], mode: str = "model") -> Decision:
    """`mode="silence"` is the baseline every voice stack starts from: answer after a fixed
    silence. `mode="model"` reads the transcript."""
    t = cfg["turn"]
    if mode == "silence":
        if pause_ms >= float(t["silence_only_ms"]):
            return Decision("respond", 1.0, "silence", False)
        return Decision("wait", 0.0, "silence", False)
    early = pause_ms < float(t["evaluate_after_ms"])
    if early and pause_ms < float(t.get("speculate_after_ms", t["evaluate_after_ms"])):
        return Decision("wait", 0.0, "too early", False)
    ent = entity_in_progress(text, context)
    entity_open = not ent.complete
    limit = float(t["entity_max_pause_ms"] if entity_open else t["max_pause_ms"])
    if not words(text):
        # silence with no words yet (a cough, a breath): nothing to answer
        return Decision("wait", 0.0, "no words", False)
    p = eot.load().probability(text, context)
    if ent.kind == "phone" and ent.complete:
        p = max(p, float(t["respond_probability"]))  # a fully dictated number ends the turn
    if early:
        # too soon to answer, not too soon to start thinking
        if not entity_open and p >= float(t["speculate_probability"]):
            return Decision("speculate", p, "likely end", entity_open)
        return Decision("wait", p, "too early", entity_open)
    if pause_ms >= limit:
        return Decision("respond", p, "max pause", entity_open)
    if not entity_open and p >= float(t["respond_probability"]):
        return Decision("respond", p, "end of turn", entity_open)
    if p >= float(t["speculate_probability"]) and not entity_open:
        return Decision("speculate", p, "likely end", entity_open)
    return Decision("wait", p, "number open" if entity_open else "unfinished", entity_open)


def flush_due(pause_ms: float, text: str, context: str, cfg: dict[str, Any]) -> bool:
    """When to push silence through the streaming recogniser so it emits the caller's last word.

    Silence pushed into the middle of an utterance damages what follows it ("zero one seven six
    one" came out as "zero one seven one" with flushes in the gaps between digits), so flush
    early only when the turn looks finished; wait for a real pause while a number is being
    dictated; and give an empty transcript a moment, since a lone "yes" needs the flush to appear."""
    t = cfg["turn"]
    early = float(cfg["stt"].get("flush_after_ms", 60))
    if not words(text):
        return pause_ms >= float(t["evaluate_after_ms"])
    if not entity_in_progress(text, context).complete:
        return pause_ms >= float(cfg["stt"].get("flush_in_number_ms", 600))
    if pause_ms >= float(t["evaluate_after_ms"]):
        return True
    return pause_ms >= early and eot.load().probability(text, context) >= float(t["speculate_probability"])


def is_backchannel(text: str) -> bool:
    ws = words(text)
    return bool(ws) and len(ws) <= 3 and all(w in BACKCHANNELS for w in ws)


def barge_in(speech_ms: float, text: str, cfg: dict[str, Any]) -> str:
    """While the agent talks and the caller makes sound: ignore | hold | interrupt.

    "hold" means yield without giving up the turn: the agent ducks (or pauses) and keeps its
    words ready. If no real words follow (a cough, a door, a "mhm") it carries on.
    A single word that is not a backchannel ("mech": a "mhm" the recogniser misheard) holds
    rather than interrupts, unless it is a stop word ("no", "wait", "nein")."""
    b = cfg["barge_in"]
    if speech_ms < float(b["min_speech_ms"]):
        return "ignore"
    ws = words(text)
    if speech_ms >= float(b["backchannel_max_ms"]) and not is_backchannel(text):
        return "interrupt"  # too long for "mhm", words or not (German has no partial words to read)
    if ws and is_backchannel(text):
        return "ignore"  # a backchannel: the agent keeps talking
    if len(ws) >= 2 or (ws and ws[0] in STOP_WORDS):
        return "interrupt"
    return "hold"
