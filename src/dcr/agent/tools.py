"""The business the agent answers for: a hair salon's calendar, behind the tools the LLM may call.

Each call gets its own calendar, seeded from the call's date, so a test call is reproducible.
In production these tools would call the salon's booking system; the runtime only depends on
the tool schemas below and on `ToolBox.call`."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any

SERVICES = {
    "haircut": {"en": "haircut", "de": "Haarschnitt", "minutes": 30},
    "colour": {"en": "colouring", "de": "Färben", "minutes": 90},
    "beard": {"en": "beard trim", "de": "Bartschnitt", "minutes": 30},
}
OPEN = {0: (9, 18), 1: (9, 18), 2: (9, 18), 3: (9, 20), 4: (9, 18), 5: (9, 14)}  # Mon-Sat; closed Sunday

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Is a slot free? Returns whether it is and the nearest free times that day.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "enum": list(SERVICES)},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:MM, 24-hour"},
                },
                "required": ["service", "date", "time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book a slot that check_availability said is free.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "enum": list(SERVICES)},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "name": {"type": "string"},
                    "phone": {"type": "string", "description": "digits only"},
                },
                "required": ["service", "date", "time", "name", "phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_human",
            "description": "Hand the call to a person at the salon.",
            "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
        },
    },
]


@dataclass
class Booking:
    service: str
    date: str
    time: str
    name: str
    phone: str
    ref: str


class ToolBox:
    """The salon's calendar and the call's side effects. `taken` lists the booked slots
    ("YYYY-MM-DD HH:MM"), as a test sets up a database; without it the week is reproducibly
    about a third booked, like a demo salon."""

    def __init__(self, today: dt.date, seed: str = "salon", taken: list[str] | None = None) -> None:
        self.today = today
        self.seed = seed
        self.taken: set[tuple[str, str]] = set()
        self.bookings: list[Booking] = []
        self.transferred: str | None = None
        if taken is not None:
            for slot in taken:
                day_s, time_s = slot.split()
                self.taken.add((dt.date.fromisoformat(day_s).isoformat(), time_s))
            return
        rng = random.Random(int(hashlib.sha256(f"{self.seed}:{self.today}".encode()).hexdigest()[:8], 16))
        for d in range(8):
            day = self.today + dt.timedelta(days=d)
            for t in self.slots(day):
                if rng.random() < 0.33:
                    self.taken.add((day.isoformat(), t))

    @staticmethod
    def slots(day: dt.date) -> list[str]:
        if day.weekday() not in OPEN:
            return []
        a, b = OPEN[day.weekday()]
        return [f"{h:02d}:{m:02d}" for h in range(a, b) for m in (0, 30)]

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        fn = getattr(self, f"_{name}", None)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        try:
            return dict(fn(**args))
        except (TypeError, ValueError) as e:
            return {"error": str(e)}

    def _check_availability(self, service: str, date: str, time: str) -> dict[str, Any]:
        day = dt.date.fromisoformat(date)
        if service not in SERVICES:
            raise ValueError(f"unknown service {service}")
        slots = self.slots(day)
        if not slots:
            return {"available": False, "closed": True, "alternatives": []}
        free = [s for s in slots if (date, s) not in self.taken]
        if time in free:
            return {"available": True, "date": date, "time": time}
        near = sorted(free, key=lambda s: abs(_minutes(s) - _minutes(time)))[:2]
        return {"available": False, "closed": False, "alternatives": sorted(near)}

    def _book_appointment(self, service: str, date: str, time: str, name: str, phone: str) -> dict[str, Any]:
        if (date, time) in self.taken:
            return {"booked": False, "reason": "slot taken"}
        if len("".join(c for c in phone if c.isdigit())) < 7:
            return {"booked": False, "reason": "phone number incomplete"}
        ref = hashlib.sha256(f"{date}{time}{name}".encode()).hexdigest()[:6].upper()
        self.taken.add((date, time))
        self.bookings.append(Booking(service, date, time, name, phone, ref))
        return {"booked": True, "ref": ref}

    def _transfer_to_human(self, reason: str) -> dict[str, Any]:
        self.transferred = reason
        return {"transferred": True}

    def dump(self) -> str:
        return json.dumps({"bookings": [b.__dict__ for b in self.bookings], "transferred": self.transferred})


def _minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)
