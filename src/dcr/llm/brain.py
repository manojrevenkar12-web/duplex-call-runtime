"""A deterministic receptionist that stands in for the LLM in tests and benchmarks.

It reads an OpenAI-style message history (system, user, assistant, tool calls and results) and
returns the next assistant turn: text, or a tool call. It is stateless, as an LLM is: everything
it knows comes from the history it is sent, including the transcripts speech recognition
produced, errors and all. That makes calls reproducible and free, so the runtime's latency and
turn-taking can be measured without a model's variance on top. The production client talks to
any OpenAI-compatible endpoint (vLLM, OpenAI, an Anthropic-compatible gateway) instead.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..agent.tools import SERVICES
from ..text.numbers import ClockTime, digit_string, parse_time, words

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4, "samstag": 5, "sonnabend": 5, "sonntag": 6,
}  # fmt: skip
SERVICE_WORDS = {
    "haircut": ["haircut", "hair cut", "cut", "trim my hair", "haarschnitt", "schneiden", "haare schneiden"],
    "colour": ["colour", "color", "colouring", "coloring", "dye", "färben", "farbe", "faerben", "tönen"],
    "beard": ["beard", "bart", "bartschnitt", "rasur"],
}
YES = {
    "yes",
    "yeah",
    "yep",
    "correct",
    "right",
    "exactly",
    "sure",
    "ja",
    "genau",
    "richtig",
    "stimmt",
    "passt",
    "korrekt",
    "perfect",
    "perfekt",
}
NO = {"no", "nope", "wrong", "nein", "falsch", "nicht"}
HUMAN = ["human", "person", "real person", "someone", "staff", "mitarbeiter", "mensch", "jemanden"]
HOURS = ["opening hours", "open", "when are you", "öffnungszeiten", "geöffnet", "offen", "wann haben sie"]

NAME_PATTERNS = [
    r"\bmy name is ([a-zäöüß]+(?: [a-zäöüß]+)?)",
    r"\bthis is ([a-zäöüß]+(?: [a-zäöüß]+)?)",
    r"\bit'?s ([a-zäöüß]+(?: [a-zäöüß]+)?) speaking",
    r"\bich heiße ([a-zäöüß]+(?: [a-zäöüß]+)?)",
    r"\bich heisse ([a-zäöüß]+(?: [a-zäöüß]+)?)",
    r"\bmein name ist ([a-zäöüß]+(?: [a-zäöüß]+)?)",
    r"\bhier (?:ist|spricht) ([a-zäöüß]+(?: [a-zäöüß]+)?)",
    r"\bname(?: is|:)? ([a-zäöüß]+(?: [a-zäöüß]+)?)",
    r"\bauf den namen ([a-zäöüß]+(?: [a-zäöüß]+)?)",
    r"\bunder ([a-zäöüß]+(?: [a-zäöüß]+)?)",
]
NOT_NAMES = {"calling", "here", "looking", "interested", "free", "the", "a", "an", "ich", "and", "und", "i", "booking", "to"}
TIME_CUES = ["uhr", "o'clock", "o clock", "oclock", "past", "half", "halb", "am", "pm", "um", "at"]
FILLERS = {"and", "uh", "um", "er", "please", "bitte", "und", "also", "äh", "ähm"}


@dataclass
class State:
    lang: str = "en"
    today: dt.date = field(default_factory=dt.date.today)
    service: str | None = None
    date: dt.date | None = None
    time: ClockTime | None = None
    name: str | None = None
    phone: str = ""
    checked: dict[str, Any] | None = None  # last check_availability result (with its arguments)
    booked: dict[str, Any] | None = None
    transferred: bool = False
    summary_given: bool = False
    last_user: str = ""
    asked: str | None = None  # what the last assistant turn asked for


def _contains(text: str, phrases: list[str]) -> bool:
    t = f" {text.lower()} "
    return any(f" {p} " in t or (len(p) > 5 and p in t) for p in phrases)


ORDINALS_EN = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
    "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
    "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}  # fmt: skip
ORDINALS_DE = {
    "ersten": 1, "zweiten": 2, "dritten": 3, "vierten": 4, "fünften": 5, "sechsten": 6, "siebten": 7, "achten": 8,
    "neunten": 9, "zehnten": 10, "elften": 11, "zwölften": 12, "dreizehnten": 13, "vierzehnten": 14, "fünfzehnten": 15,
    "sechzehnten": 16, "siebzehnten": 17, "achtzehnten": 18, "neunzehnten": 19, "zwanzigsten": 20, "dreißigsten": 30,
}  # fmt: skip


def _day_of_month(ws: list[str]) -> int | None:
    """ "the fourth", "the 4th", "twenty first", "am vierten", "einundzwanzigsten"."""
    for i, w in enumerate(ws):
        m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th|\.)", w)
        if m:
            return int(m.group(1))
        if w in ORDINALS_EN:
            prev = ws[i - 1] if i else ""
            tens = {"twenty": 20, "thirty": 30}.get(prev, 0)
            return tens + ORDINALS_EN[w] if ORDINALS_EN[w] < 10 or not tens else ORDINALS_EN[w]
        if w in ORDINALS_DE:
            return ORDINALS_DE[w]
        if w.endswith("ten") and "und" in w:  # einundzwanzigsten
            ones, _, tens_w = w.removesuffix("sten").removesuffix("ten").partition("und")
            from ..text.numbers import ONES_DE

            tens_de = {"zwanzig": 20, "dreißig": 30}.get(tens_w)
            if tens_de and ones in ONES_DE:
                return tens_de + ONES_DE[ones]
    return None


def _date_from(text: str, today: dt.date) -> dt.date | None:
    ws = words(text)
    dom = _day_of_month(ws)
    if dom is not None and 1 <= dom <= 31:
        # the next date with that day of the month; if a weekday is named too, the next one that matches both
        wd = next((WEEKDAYS[w] for w in ws if w in WEEKDAYS), None)
        d = today
        for _ in range(400):
            if d.day == dom and (wd is None or d.weekday() == wd):
                return d
            d += dt.timedelta(days=1)
    if "today" in ws or "heute" in ws:
        return today
    if "übermorgen" in ws or ("day" in ws and "after" in ws and "tomorrow" in ws):
        return today + dt.timedelta(days=2)
    if "tomorrow" in ws or "morgen" in ws:
        return today + dt.timedelta(days=1)
    for w in ws:
        if w in WEEKDAYS:
            ahead = (WEEKDAYS[w] - today.weekday()) % 7 or 7
            return today + dt.timedelta(days=ahead)
    return None


def _service_from(text: str) -> str | None:
    for key, ws in SERVICE_WORDS.items():
        if _contains(text, ws):
            return key
    # recognisers misspell: "ferben", "bart-schnitt", "colouring" as "coloring"
    for w in words(text.replace("-", "")):
        for key, ws in SERVICE_WORDS.items():
            if len(w) >= 6 and any(len(p) >= 6 and " " not in p and _edits(w, p) <= 1 for p in ws):
                return key
    if _contains(text, ["hair", "haare"]):
        return "haircut"  # "a hair could please": speech recognition splits "haircut" more often than not
    return None


def _edits(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 1:
        return 2
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, d[0] = d[:], i
        for j, y in enumerate(b, 1):
            d[j] = min(prev[j] + 1, d[j - 1] + 1, prev[j - 1] + (x != y))
    return d[-1]


def _name_from(text: str) -> str | None:
    t = text.lower()
    for p in NAME_PATTERNS:
        m = re.search(p, t)
        if m:
            parts = [w for w in m.group(1).split() if w not in NOT_NAMES and w not in FILLERS and not w.isdigit()]
            if parts:
                return " ".join(w.capitalize() for w in parts[:2])
    return None


def _yes_no(text: str) -> bool | None:
    ws = set(words(text))
    if ws & NO and not (ws & YES and len(ws) <= 2):
        return False
    if ws & YES:
        return True
    return None


def read_state(messages: list[dict[str, Any]]) -> State:
    st = State()
    sys = next((m["content"] for m in messages if m["role"] == "system"), "")
    m = re.search(r"Today is (\d{4}-\d{2}-\d{2})", sys)
    if m:
        st.today = dt.date.fromisoformat(m.group(1))
    m = re.search(r"Language: (en|de)", sys)
    if m:
        st.lang = m.group(1)
    for msg in messages:
        role = msg["role"]
        if role == "user":
            text = msg.get("content") or ""
            st.last_user = text
            if st.asked == "name":
                # the answer to "what name?" is usually just the name
                n = _name_from(text) or _bare_name(text)
                if n:
                    st.name = n
            st.service = _service_from(text) or st.service
            d = _date_from(text, st.today)
            if d:
                st.date = d
                st.checked = None
            dictating = st.asked == "phone" or (len(digit_string(text)) >= 5 and not _contains(text, TIME_CUES))
            t = None if dictating else parse_time(text)
            if t is None and st.asked == "time" and not dictating:
                ds = [int(x) for x in _numbers(text)]
                if ds and ds[0] <= 23:
                    t = ClockTime(ds[0] + 12 if 1 <= ds[0] <= 7 else ds[0], ds[1] if len(ds) > 1 and ds[1] < 60 else 0)
            if t:
                st.time = t
                st.checked = None
            if st.asked != "name":
                st.name = _name_from(text) or st.name
            digits = digit_string(text)
            if (st.asked == "phone" or any(c in text.lower() for c in ("number", "nummer"))) and len(digits) >= 3:
                st.phone = digits if len(digits) >= 7 else st.phone + digits
            if st.asked == "confirm":
                yn = _yes_no(text)
                if yn is False:
                    st.summary_given = False
        elif role == "assistant":
            content = msg.get("content") or ""
            st.asked = _asked(content)
            if st.asked == "confirm":
                st.summary_given = True
            for tc in msg.get("tool_calls") or []:
                st.asked = None
                _ = tc
        elif role == "tool":
            res = json.loads(msg.get("content") or "{}")
            if "available" in res:
                st.checked = res
            if res.get("booked"):
                st.booked = res
            if res.get("transferred"):
                st.transferred = True
    return st


def _numbers(text: str) -> list[str]:
    from ..text.numbers import number_tokens

    return [d for _, d in number_tokens(words(text))]


def _bare_name(text: str) -> str | None:
    ws = [w for w in words(text) if w not in FILLERS and w not in NOT_NAMES and not w.isdigit() and w not in YES and w not in NO]
    ws = [
        w
        for w in ws
        if w not in {"my", "name", "is", "its", "it's", "it", "this", "that", "mein", "ist", "ich", "bin", "hier", "heiße", "heisse"}
        and w not in {"sure", "yes", "okay", "ok", "please", "bitte", "of", "course", "natürlich"}
    ]
    if 1 <= len(ws) <= 2:
        return " ".join(w.capitalize() for w in ws)
    return None


def _asked(content: str) -> str | None:
    c = content.lower()
    for key, cues in {
        "confirm": ["is that right", "shall i book", "stimmt das"],
        "phone": ["phone number", "number we can reach", "telefonnummer", "nummer"],
        "name": ["what name", "your name", "welchen namen", "ihr name", "auf welchen namen"],
        "time": [
            "what time",
            "which time",
            "um wie viel uhr",
            "welche uhrzeit",
            "would suit",
            "würde passen",
            "would you like instead",
            "lieber",
        ],
        "day": ["which day", "what day", "an welchem tag", "welcher tag"],
        "service": ["what can we do", "which service", "was dürfen wir", "welche leistung"],
    }.items():
        if any(x in c for x in cues):
            return key
    return None


T = {
    "ask_service": {
        "en": "Of course. What can we do for you: a haircut, colouring or a beard trim?",
        "de": "Gern. Was dürfen wir für Sie tun: Haarschnitt, Färben oder Bartschnitt?",
    },
    "ask_day": {"en": "Which day would you like?", "de": "An welchem Tag hätten Sie gern einen Termin?"},
    "ask_time": {"en": "And what time would suit you?", "de": "Und um wie viel Uhr würde es Ihnen passen?"},
    "ask_name": {
        "en": "That time is free. What name should I put the booking under?",
        "de": "Der Termin ist frei. Auf welchen Namen darf ich buchen?",
    },
    "ask_phone": {
        "en": "Thanks. And a phone number we can reach you on?",
        "de": "Danke. Und unter welcher Telefonnummer erreichen wir Sie?",
    },
    "closed": {
        "en": "Sorry, we're closed that day. Which other day would you like?",
        "de": "An dem Tag haben wir leider geschlossen. An welchem anderen Tag würde es passen?",
    },
    "taken": {
        "en": "Sorry, {time} is taken. I can offer {alts}. Which would you like instead?",
        "de": "{time} ist leider schon vergeben. Ich kann Ihnen {alts} anbieten. Was wäre Ihnen lieber?",
    },
    "none_free": {
        "en": "Sorry, that day is fully booked. Which other day would you like?",
        "de": "Der Tag ist leider ausgebucht. An welchem anderen Tag würde es passen?",
    },
    "confirm": {
        "en": "So that's a {service} on {day} at {time} for {name}, number {phone}. Is that right?",
        "de": "Also {service} am {day} um {time} für {name}, Telefonnummer {phone}. Stimmt das so?",
    },
    "change": {"en": "No problem. What should I change?", "de": "Kein Problem. Was soll ich ändern?"},
    "booked": {
        "en": "Done, you're booked. Your reference is {ref}. See you then, goodbye!",
        "de": "Erledigt, Ihr Termin ist gebucht. Ihre Buchungsnummer ist {ref}. Bis dann, auf Wiederhören!",
    },
    "hours": {
        "en": "We're open Monday to Friday from nine to six, Thursdays until eight, and Saturdays from nine to two. Would you like to book?",
        "de": "Wir haben Montag bis Freitag von neun bis achtzehn Uhr geöffnet, donnerstags bis zwanzig Uhr und samstags von neun bis vierzehn Uhr. Möchten Sie einen Termin?",
    },
    "transfer": {"en": "I'll put you through to a colleague now.", "de": "Ich verbinde Sie jetzt mit einer Kollegin."},
    "repeat": {"en": "Sorry, could you say that again?", "de": "Entschuldigung, könnten Sie das wiederholen?"},
}
DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _say(key: str, lang: str, **kw: Any) -> str:
    return T[key][lang].format(**kw)


def _spoken_time(t: str, lang: str) -> str:
    h, m = (int(x) for x in t.split(":"))
    if lang == "de":
        return f"{h} Uhr" + (f" {m}" if m else "")
    hh = h - 12 if h > 12 else h
    suffix = "pm" if h >= 12 else "am"
    return f"{hh}{':' + f'{m:02d}' if m else ''} {suffix}"


def _spoken_phone(p: str) -> str:
    return " ".join(p[i : i + 3] for i in range(0, len(p), 3))


def next_turn(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """{"content": str} or {"tool_call": {"name": ..., "arguments": {...}}}."""
    st = read_state(messages)
    lang = st.lang
    last = st.last_user
    if st.booked:
        return {"content": _say("booked", lang, ref=st.booked.get("ref", ""))}
    if st.transferred:
        return {"content": _say("transfer", lang)}
    if last and _contains(last, HUMAN):
        return {"tool_call": {"name": "transfer_to_human", "arguments": {"reason": "caller asked for a person"}}}
    if last and _contains(last, HOURS) and not (st.service or st.date or st.time):
        return {"content": _say("hours", lang)}
    if st.summary_given and _yes_no(last) is True and st.service and st.date and st.time and st.name and st.phone:
        return {
            "tool_call": {
                "name": "book_appointment",
                "arguments": {"service": st.service, "date": st.date.isoformat(), "time": str(st.time), "name": st.name, "phone": st.phone},
            }
        }
    if st.summary_given is False and st.asked == "confirm" and _yes_no(last) is False:
        return {"content": _say("change", lang)}
    if not st.service:
        if st.date or st.time or _contains(last, ["appointment", "book", "termin", "buchen"]) or not last:
            return {"content": _say("ask_service", lang)}
        return {"content": _say("repeat", lang) if last else _say("ask_service", lang)}
    if not st.date:
        return {"content": _say("ask_day", lang)}
    if not st.time:
        return {"content": _say("ask_time", lang)}
    want = {"service": st.service, "date": st.date.isoformat(), "time": str(st.time)}
    if not st.checked or (st.checked.get("available") and (st.checked.get("date"), st.checked.get("time")) != (want["date"], want["time"])):
        return {"tool_call": {"name": "check_availability", "arguments": want}}
    if not st.checked.get("available"):
        if st.checked.get("closed"):
            return {"content": _say("closed", lang)}
        alts = st.checked.get("alternatives") or []
        if not alts:
            return {"content": _say("none_free", lang)}
        joiner = " or " if lang == "en" else " oder "
        return {
            "content": _say("taken", lang, time=_spoken_time(str(st.time), lang), alts=joiner.join(_spoken_time(a, lang) for a in alts))
        }
    if not st.name:
        return {"content": _say("ask_name", lang)}
    if len(st.phone) < 7:
        return {"content": _say("ask_phone", lang)}
    day = (DAYS_DE if lang == "de" else DAYS_EN)[st.date.weekday()]
    return {
        "content": _say(
            "confirm",
            lang,
            service=SERVICES[st.service][lang],
            day=day,
            time=_spoken_time(str(st.time), lang),
            name=st.name,
            phone=_spoken_phone(st.phone),
        )
    }
