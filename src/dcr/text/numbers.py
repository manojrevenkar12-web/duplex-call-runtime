"""Spoken numbers in English and German, as speech recognition writes them.

Callers dictate phone numbers digit by digit ("zero one seven six", "null eins sieben sechs"),
in groups ("seventeen sixty", "siebzehn sechzig"), or as numerals when the recogniser formats
them. Times come as "half past two", "two thirty", "halb drei", "vierzehn Uhr". This module
turns those into digits and clock times, and tells the turn-taking engine when a number is
still being dictated, which is when a caller pauses mid-sentence most often."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

ONES_EN = {
    "zero": 0, "oh": 0, "o": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}  # fmt: skip
TENS_EN = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
ONES_DE = {
    "null": 0, "eins": 1, "ein": 1, "eine": 1, "zwei": 2, "zwo": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14,
    "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
}  # fmt: skip
TENS_DE = {
    "zwanzig": 20,
    "dreißig": 30,
    "dreissig": 30,
    "vierzig": 40,
    "fünfzig": 50,
    "sechzig": 60,
    "siebzig": 70,
    "achtzig": 80,
    "neunzig": 90,
}
DOUBLE = {"double": 2, "triple": 3, "doppel": 2}

_WORD = re.compile(r"[a-zäöüß0-9']+")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _de_compound(w: str) -> int | None:
    """German writes 21-99 as one word: einundzwanzig, siebenundsechzig."""
    if w in ONES_DE:
        return ONES_DE[w]
    if w in TENS_DE:
        return TENS_DE[w]
    if "und" in w:
        a, _, b = w.partition("und")
        if a in ONES_DE and b in TENS_DE and ONES_DE[a] < 10:
            return TENS_DE[b] + ONES_DE[a]
    return None


def number_tokens(ws: list[str]) -> list[tuple[int, str]]:
    """Each word that is (part of) a number, as (index, digits). "seventeen sixty" gives "17", "60";
    "twenty five" gives "25"; "double seven" gives "77"; numerals pass through."""
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(ws):
        w = ws[i]
        if w.isdigit():
            out.append((i, w))
        elif w in DOUBLE and i + 1 < len(ws):
            nxt = ws[i + 1]
            v = ONES_EN.get(nxt, ONES_DE.get(nxt))
            if v is not None and v < 10:
                out.append((i, str(v) * DOUBLE[w]))
                i += 2
                continue
        elif w in TENS_EN:
            v = TENS_EN[w]
            if i + 1 < len(ws) and ONES_EN.get(ws[i + 1], 99) < 10 and ws[i + 1] not in ("oh", "o"):
                out.append((i, str(v + ONES_EN[ws[i + 1]])))
                i += 2
                continue
            out.append((i, str(v)))
        elif w in ONES_EN and not (w in ("o", "oh") and not _near_digits(ws, i)):
            out.append((i, str(ONES_EN[w])))
        else:
            v = _de_compound(w)
            if v is not None:
                out.append((i, str(v)))
        i += 1
    return out


def _near_digits(ws: list[str], i: int) -> bool:
    """'oh' is a zero only between other numbers ("oh one seven")."""
    return any(0 <= j < len(ws) and (ws[j].isdigit() or ws[j] in ONES_EN or ws[j] in TENS_EN) for j in (i - 1, i + 1))


def digit_string(text: str) -> str:
    """All digits a caller has said, in order (phone numbers, IBANs)."""
    return "".join(d for _, d in number_tokens(words(text)))


PHONE_CUES = {"number", "phone", "mobile", "nummer", "telefonnummer", "handynummer", "rufnummer", "erreichbar", "reach"}
DATE_CUES = {"on", "the", "am", "den", "dem"}


@dataclass
class Entity:
    kind: str  # phone | time | none
    digits: int
    complete: bool


def entity_in_progress(text: str, context: str = "") -> Entity:
    """Is the caller in the middle of dictating something? A phone number after a cue word with
    fewer digits than a German or English number has (10-12 for mobiles, 7+ for landlines), or
    a trailing run of number words, means a pause is a breath, not the end of the turn.
    `context="phone"` (the agent just asked for a number) makes the whole answer the number."""
    ws = words(text)
    if not ws:
        return Entity("none", 0, True)
    nums = number_tokens(ws)
    cue = max((i for i, w in enumerate(ws) if w in PHONE_CUES), default=-1)
    if cue < 0 and context == "phone" and nums:
        cue = nums[0][0] - 1  # "zero one five ...", "sure it's zero one ...": the answer is the number
    if cue >= 0 or (context == "phone" and nums):
        after = [d for i, d in nums if i > cue]
        n = sum(len(d) for d in after)
        if n > 0 or cue >= len(ws) - 3:
            ends_on_number = bool(nums) and nums[-1][0] >= len(ws) - 1
            return Entity("phone", n, n >= 10 and not (ends_on_number and n < 11))
    # a trailing run of numbers without a cue (e.g. "my postcode is one oh three one")
    if nums and nums[-1][0] == len(ws) - 1:
        run = 0
        for i, _ in reversed(nums):
            if i == len(ws) - 1 - run:
                run += 1
            else:
                break
        if run >= 3:
            return Entity("digits", run, False)
    return Entity("none", 0, True)


@dataclass
class ClockTime:
    hour: int
    minute: int

    def __str__(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


_DE_HALF = re.compile(r"\bhalb\s+(\w+)")
_EN_PAST = re.compile(r"\b(half|quarter|ten|twenty|five)\s+(past|to)\s+(\w+)")


def parse_time(text: str) -> ClockTime | None:
    """'two thirty', 'half past two', '14:30', '14 Uhr 30', 'halb drei' (= 2:30), 'at ten'.
    Hours 1-7 are read as afternoon, as a salon books them."""
    t = text.lower()
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", t)
    if m:
        return _fix(int(m.group(1)), int(m.group(2)))
    m = _DE_HALF.search(t)
    if m:
        h = _val(m.group(1))
        if h is not None:
            return _fix(h - 1, 30)
    m = _EN_PAST.search(t)
    if m:
        h = _val(m.group(3))
        if h is not None:
            mins = {"half": 30, "quarter": 15, "ten": 10, "twenty": 20, "five": 5}[m.group(1)]
            return _fix(h, mins) if m.group(2) == "past" else _fix(h - 1, 60 - mins)
    t = t.replace("o clock", "oclock").replace("o'clock", "oclock")
    ws = words(t)
    nums = number_tokens(ws)
    # "two thirty", "eleven fifteen": an hour word right before a minute word
    for (i, a), (j, b) in itertools.pairwise(nums):
        if j == i + 1 and 1 <= int(a) <= 12 and int(b) in (5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55):
            return _fix(int(a), int(b))
    for i, w in enumerate(ws):
        if w in ("uhr", "oclock", "at", "um", "pm", "am"):
            seq = ws[i + 1 : i + 4] if w in ("at", "um") else ws[max(0, i - 1) : i] + ws[i + 1 : i + 2]
            vals = [d for _, d in number_tokens(seq)]
            if vals and int(vals[0]) <= 23:
                h = int(vals[0])
                minute = int(vals[1]) if len(vals) > 1 and int(vals[1]) < 60 else 0
                return _fix(h, minute)
    return None


def _val(w: str) -> int | None:
    if w.isdigit():
        return int(w)
    return ONES_EN.get(w, _de_compound(w))


def _fix(h: int, m: int) -> ClockTime:
    if 1 <= h <= 7:
        h += 12
    return ClockTime(h % 24, m % 60)
