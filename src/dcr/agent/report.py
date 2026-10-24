"""A call's event log turned into per-turn numbers: where each millisecond of a reply went."""

from __future__ import annotations

from typing import Any


def summarise(events: list[dict[str, Any]]) -> dict[str, Any]:
    turns: list[dict[str, Any]] = []
    by_turn: dict[int, dict[str, Any]] = {}
    counts = {
        k: 0
        for k in (
            "interrupt",
            "hold",
            "resume",
            "backchannel",
            "speculate",
            "speculation_used",
            "speculation_cancelled",
            "taken_back",
            "llm_stream_broken",
            "llm_unavailable",
        )
    }
    hedged = 0
    providers: dict[str, int] = {}
    for ev in events:
        k = ev["kind"]
        if k in counts:
            counts[k] += 1
        if k == "end_of_turn":
            t = {
                "turn": ev["turn"],
                "text": ev["text"],
                "speech_end": ev["speech_end"],
                "decided": ev["t"],
                "endpoint_ms": round(ev["t"] - ev["speech_end"], 1),
                "reason": ev["reason"],
                "p": ev["p"],
            }
            by_turn[ev["turn"]] = t
            turns.append(t)
        elif k == "llm_first_token" and ev["turn"] in by_turn and "llm_first_token" not in by_turn[ev["turn"]]:
            by_turn[ev["turn"]]["llm_first_token"] = ev["t"]
        elif k == "tts" and ev["turn"] in by_turn and "tts_first" not in by_turn[ev["turn"]]:
            by_turn[ev["turn"]]["tts_first"] = ev["t"]
            by_turn[ev["turn"]]["tts_ms"] = ev["ms"]
        elif k == "agent_audio_start" and ev["turn"] in by_turn:
            t = by_turn[ev["turn"]]
            t["audio_start"] = ev["t"]
            t["response_ms"] = round(ev["t"] - t["speech_end"], 1)
            t["after_decision_ms"] = round(ev["t"] - t["decided"], 1)
        elif k == "llm_done":
            providers[ev["provider"]] = providers.get(ev["provider"], 0) + 1
            hedged += bool(ev["hedged"])
        elif k == "tool" and ev["turn"] in by_turn:
            by_turn[ev["turn"]].setdefault("tools", []).append(ev["name"])
    answered = [t["response_ms"] for t in turns if "response_ms" in t]
    return {
        "turns": turns,
        "response_ms": answered,
        "counts": counts,
        "providers": providers,
        "hedged": hedged,
    }
