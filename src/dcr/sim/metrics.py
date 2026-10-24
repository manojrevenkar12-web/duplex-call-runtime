"""Scoring a simulated call from what the line carried, the way a recording would be scored.

The caller knows exactly when it spoke, where its scripted pauses were, and what it played
back; the agent's speech is found by energy in the audio the carrier played. The server's own
event log is used only for what audio cannot show (the transcript it acted on and the booking
it made). The metrics follow Full-Duplex-Bench's turn-taking dimensions (pause handling,
backchannels, smooth turn-taking, user interruption) plus time to first audio:

- **response_ms**: caller stops speaking -> agent audio starts (TTFA, measured from audio).
- **pause takeover**: the agent starts talking inside a caller's mid-sentence pause.
- **interrupt stop_ms**: caller starts talking over the agent -> agent audio stops.
- **backchannel disrupted**: a "mhm" made the agent stop or pause.
- **false stops**: the agent stopped or paused while the caller was silent (echo, noise).
- **task**: the booking (or transfer) the script expects was made, exactly.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .caller import Scenario, Timeline

AUDIBLE = 0.01
MERGE_GAP_MS = 300.0


def agent_segments(tl: Timeline) -> list[tuple[float, float]]:
    segs: list[list[float]] = []
    for t, rms in tl.agent_frames:
        if rms <= AUDIBLE:
            continue
        start = t - 20
        if segs and start - segs[-1][1] <= MERGE_GAP_MS:
            segs[-1][1] = t
        else:
            segs.append([start, t])
    return [(a, b) for a, b in segs]


def _first_after(segs: list[tuple[float, float]], t: float, within: float = 8000) -> float | None:
    for a, _ in segs:
        if t <= a <= t + within:
            return a
    return None


def _playing_at(segs: list[tuple[float, float]], t: float) -> tuple[float, float] | None:
    for a, b in segs:
        if a <= t <= b:
            return (a, b)
    return None


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r = ref.lower().replace("'", " ").replace(",", " ").split()
    h = hyp.lower().replace("'", " ").replace(",", " ").split()
    d = list(range(len(h) + 1))
    for i, a in enumerate(r, 1):
        prev = d[:]
        d[0] = i
        for j, b in enumerate(h, 1):
            d[j] = min(prev[j] + 1, d[j - 1] + 1, prev[j - 1] + (a != b))
    return d[-1], len(r)


def task_ok(sc: Scenario, outcome: dict[str, Any]) -> bool | None:
    exp = sc.expect
    if not exp:
        return None
    bookings = outcome.get("bookings") or []
    if "booking" in exp:
        if len(bookings) != 1:
            return False
        b, e = bookings[0], exp["booking"]
        digits = "".join(c for c in str(b.get("phone", "")) if c.isdigit())
        return (
            b["service"] == e["service"]
            and str(b["date"]) == str(e["date"])
            and b["time"] == str(e["time"])
            and digits == str(e["phone"])
            and _name_close(b["name"], str(e["name"]))
        )
    if exp.get("transfer"):
        return bool(outcome.get("transferred")) and not bookings
    if exp.get("no_booking"):
        return not bookings
    return None


def task_diff(sc: Scenario, outcome: dict[str, Any]) -> list[str]:
    """What a failed call got wrong: the booking fields that differ, or what happened instead."""
    exp = sc.expect
    bookings = outcome.get("bookings") or []
    if "booking" in exp:
        if not bookings:
            return ["no booking"]
        if len(bookings) > 1:
            return [f"{len(bookings)} bookings"]
        b, e = bookings[0], exp["booking"]
        digits = "".join(c for c in str(b.get("phone", "")) if c.isdigit())
        wrong = [k for k in ("service", "time") if str(b[k]) != str(e[k])]
        if str(b["date"]) != str(e["date"]):
            wrong.append("date")
        if not _name_close(b["name"], str(e["name"])):
            wrong.append("name")
        if digits != str(e["phone"]):
            wrong.append("phone")
        return wrong
    if exp.get("transfer"):
        return [] if outcome.get("transferred") and not bookings else ["not transferred"]
    return ["booked"] if bookings else []


def _name_close(got: str, want: str) -> bool:
    """Names are spelled by the recogniser ("Burger" for "Berger"): accept one edit per word."""
    g, w = got.lower().split(), want.lower().split()
    if len(g) != len(w):
        return False
    for a, b in zip(g, w, strict=True):
        e, _ = wer(" ".join(a), " ".join(b))
        if e > 1:
            return False
    return True


def score(sc: Scenario, tl: Timeline, rec: dict[str, Any]) -> dict[str, Any]:
    segs = agent_segments(tl)
    lines = tl.caller
    out: dict[str, Any] = {"scenario": sc.id, "lang": sc.lang, "response_ms": [], "pause_lines": 0, "pause_takeovers": 0}
    out["interrupts"] = []
    out["backchannels"] = []
    for ln in lines:
        if ln["kind"] == "backchannel":
            disrupted = any(ln["start"] - 100 <= c <= ln["start"] + 1500 for c in tl.clears)
            out["backchannels"].append({"text": ln["text"], "disrupted": disrupted})
            continue
        if ln["kind"] == "interrupt":
            seg = _playing_at(segs, ln["start"] + 40)
            stop = (seg[1] - ln["start"]) if seg else None
            out["interrupts"].append(
                {"text": ln["text"], "stop_ms": round(stop, 1) if stop is not None else None, "was_talking": seg is not None}
            )
        if ln["pauses"]:
            out["pause_lines"] += 1
            if any(_first_after(segs, a, within=b - a + 60) is not None for a, b in ln["pauses"]):
                out["pause_takeovers"] += 1
        r = _first_after(segs, ln["end"])
        if r is not None:
            out["response_ms"].append(round(r - ln["end"], 1))
    # stops (clears) not explained by the caller speaking: echo, noise, a cough
    spoken = [(ln["start"] - 200, ln["end"] + 1500) for ln in lines]
    out["false_stops"] = sum(1 for c in tl.clears if not any(a <= c <= b for a, b in spoken))
    out["task"] = task_ok(sc, rec.get("outcome") or {})
    out["task_wrong"] = task_diff(sc, rec.get("outcome") or {}) if out["task"] is False else []
    said = " ".join(ln["text"] for ln in lines if ln["kind"] != "backchannel")
    heard = " ".join(ev["text"] for ev in rec["events"] if ev["kind"] == "end_of_turn" and not _taken_back_after(rec["events"], ev))
    errs, n = wer(said, heard)
    out["wer"] = (errs, n)
    out["server"] = rec["summary"]["counts"] | {"hedged": rec["summary"]["hedged"]}
    lag = next((ev.get("inbound_lag_ms") for ev in rec["events"] if ev["kind"] == "call_end"), None)
    out["inbound_lag_ms"] = lag
    return out


def _taken_back_after(events: list[dict[str, Any]], eot: dict[str, Any]) -> bool:
    """A committed turn that was later taken back reappears, longer, in a later commit."""
    seen = False
    for ev in events:
        if ev is eot:
            seen = True
            continue
        if seen and ev["kind"] == "taken_back" and ev.get("turn") == eot["turn"]:
            return True
        if seen and ev["kind"] == "end_of_turn":
            return False
    return False


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    resp = [x for r in results for x in r["response_ms"]]
    stops = [i["stop_ms"] for r in results for i in r["interrupts"] if i["stop_ms"] is not None]
    inter = [i for r in results for i in r["interrupts"]]
    bcs = [b for r in results for b in r["backchannels"]]
    tasks = [r["task"] for r in results if r["task"] is not None]
    errs = sum(r["wer"][0] for r in results)
    words = sum(r["wer"][1] for r in results)
    pl = sum(r["pause_lines"] for r in results)

    def pct(xs: list[float], q: float) -> float | None:
        return round(float(np.percentile(xs, q)), 1) if xs else None

    return {
        "calls": len(results),
        "response_ms": {
            "n": len(resp),
            "p50": pct(resp, 50),
            "p90": pct(resp, 90),
            "mean": round(float(np.mean(resp)), 1) if resp else None,
        },
        "pause_takeover_rate": round(sum(r["pause_takeovers"] for r in results) / pl, 3) if pl else None,
        "pause_lines": pl,
        "interrupt_stop_ms": {"n": len(stops), "p50": pct(stops, 50), "p90": pct(stops, 90)},
        "interrupts_stopped": f"{sum(1 for i in inter if i['stop_ms'] is not None and i['stop_ms'] < 1500)}/{sum(1 for i in inter if i['was_talking'])}",
        "backchannels_disrupted": f"{sum(b['disrupted'] for b in bcs)}/{len(bcs)}",
        "false_stops": sum(r["false_stops"] for r in results),
        "task_success": f"{sum(tasks)}/{len(tasks)}",
        "wer": round(errs / words, 3) if words else None,
        "hedged": sum(r["server"].get("hedged", 0) for r in results),
        "taken_back": sum(r["server"].get("taken_back", 0) for r in results),
    }
