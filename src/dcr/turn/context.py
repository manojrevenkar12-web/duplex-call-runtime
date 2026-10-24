"""What did the agent just ask? The end-of-turn model reads it as context: "at ten" ends a turn
after "what time?", not after "how can I help?"."""

from __future__ import annotations

CUES = {
    "confirm": ["is that right", "shall i book", "stimmt das"],
    "phone": ["phone number", "number we can reach", "telefonnummer"],
    "name": ["what name", "your name", "welchen namen", "ihr name"],
    "time": ["what time", "which time", "um wie viel uhr", "welche uhrzeit", "would suit", "würde passen", "instead", "lieber"],
    "day": ["which day", "what day", "an welchem tag", "welcher tag", "other day", "anderen tag"],
    "service": ["what can we do", "which service", "was dürfen wir", "welche leistung"],
}


def asked(agent_text: str) -> str:
    c = agent_text.lower()
    for key, cues in CUES.items():
        if any(x in c for x in cues):
            return key
    return "open"
