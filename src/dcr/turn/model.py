"""End-of-turn probability from what the caller has said so far.

When the caller pauses, silence alone cannot tell "I'd like to book a ..." (thinking) from
"I'd like to book a haircut" (done). LiveKit's turn detector showed that the transcript carries
most of that signal, so this model reads the words: the last word and the last two, whether
the last word is a function word or a filler, how long the turn is, and whether a phone number
or other digit string is half dictated. A logistic regression over hashed features keeps it at
microseconds per decision, in any language the feature lists cover (English and German here).

It is trained by `dcr train-turn` on every word-boundary prefix of the caller turns in
`corpus/`: the whole line is a finished turn, its prefixes are unfinished ones (unless the
prefix is itself a whole line elsewhere). Lines are split into train and validation by line,
so the reported numbers are on turns the model never saw."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from ..text.numbers import entity_in_progress, number_tokens, words

HERE = Path(__file__).parent
MODEL_PATH = HERE / "eot_model.json"
DIM = 1 << 12

FUNCTION = {
    # English: articles, prepositions, conjunctions, auxiliaries, possessives, and words that announce more
    "a", "an", "the", "to", "for", "on", "at", "in", "of", "with", "and", "or", "but", "because", "so", "my", "your", "our",
    "is", "are", "was", "be", "it's", "its", "i'd", "i'm", "i", "can", "could", "would", "will", "like", "want", "need", "about",
    "around", "after", "before", "than", "if", "that", "this", "some", "any", "me", "also", "just", "maybe", "then", "from",
    # German
    "ein", "eine", "einen", "einem", "der", "die", "das", "den", "dem", "zu", "zum", "zur", "für", "am", "um", "im", "mit", "und", "oder", "aber", "weil", "dass", "mein", "meine", "meinen", "ist", "sind", "war", "ich", "hätte", "möchte",
    "würde", "kann", "könnte", "bräuchte", "gern", "gerne", "gegen", "nach", "vor", "bei", "auf", "wenn", "noch", "auch",
}  # fmt: skip
FILLERS = {"uh", "um", "er", "erm", "hm", "hmm", "äh", "ähm", "öh", "na", "also", "well", "so", "like"}


CONTEXTS = ("service", "day", "time", "name", "phone", "confirm", "open")


def context_of(line: str) -> str:
    """What the agent most plausibly asked before this caller turn (for training lines; at run
    time the session knows what it asked)."""
    ws = set(words(line))
    digits = sum(len(d) for _, d in number_tokens(words(line)))
    if digits >= 7:
        return "phone"
    if ws & {"yes", "no", "yeah", "correct", "ja", "nein", "richtig", "genau", "stimmt"} and len(ws) <= 4:
        return "confirm"
    if ws & {"o'clock", "uhr", "half", "halb", "thirty", "dreißig", "past"} or (digits and len(ws) <= 4):
        return "time"
    if (
        ws
        & {
            "tomorrow",
            "morgen",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "montag",
            "dienstag",
            "mittwoch",
            "donnerstag",
            "freitag",
            "samstag",
            "übermorgen",
        }
        and len(ws) <= 4
    ):
        return "day"
    if ws & {"name", "namen", "heiße", "spricht"} or (len(ws) <= 2 and not digits and not ws & {"okay", "sure", "gern", "thanks", "danke"}):
        return "name"
    return "open"


def features(text: str, context: str = "open") -> list[str]:
    ws = words(text)
    if not ws:
        return ["empty", f"ctx={context}"]
    last = ws[-1]
    nums = number_tokens(ws)
    ends_num = bool(nums) and nums[-1][0] == len(ws) - 1
    cls = "filler" if last in FILLERS else "function" if last in FUNCTION else "number" if ends_num else "content"
    ent = entity_in_progress(text)
    n = len(ws)
    out = [
        f"last={last}",
        f"cls={cls}",
        f"n={min(n, 8)}" if n < 8 else "n=long",
        f"first={ws[0]}",
        "bias",
        f"ctx={context}",
        f"ctx_cls={context}_{cls}",
    ]
    if n >= 2:
        out.append(f"last2={ws[-2]}_{last}")
        out.append(f"cls2={'function' if ws[-2] in FUNCTION else 'other'}_{cls}")
    if ent.kind != "none":
        out.append(f"entity={ent.kind}:{'complete' if ent.complete else 'open'}")
    return out


def _vec(feats: list[str]) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    for f in feats:
        h = int(hashlib.md5(f.encode()).hexdigest()[:8], 16)  # noqa: S324 - feature hashing, not security
        v[h % DIM] += 1.0
    return v


@dataclass
class EOTModel:
    w: np.ndarray
    b: float

    def probability(self, text: str, context: str = "open") -> float:
        z = float(self.w @ _vec(features(text, context))) + self.b
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    def save(self, path: Path, meta: dict[str, Any]) -> None:
        nz = {int(i): round(float(self.w[i]), 5) for i in np.nonzero(self.w)[0]}
        path.write_text(json.dumps({"dim": DIM, "bias": round(self.b, 5), "weights": nz, "meta": meta}, indent=0, sort_keys=True))


@cache
def load(path: Path = MODEL_PATH) -> EOTModel:
    doc = json.loads(path.read_text())
    w = np.zeros(int(doc["dim"]), dtype=np.float32)
    for i, v in doc["weights"].items():
        w[int(i)] = v
    return EOTModel(w, float(doc["bias"]))


def corpus(lang: str) -> list[str]:
    lines = (HERE / "corpus" / f"{lang}.txt").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def examples(lines: list[str], all_lines: set[str]) -> list[tuple[str, str, int]]:
    """(text, context, label) for every prefix; a line is also seen without its context, so the
    model does not lean on context alone."""
    out = []
    for line in lines:
        ws = line.split()
        for ctx in {context_of(line), "open"}:
            for k in range(1, len(ws)):
                prefix = " ".join(ws[:k])
                out.append((prefix, ctx, 1 if prefix in all_lines else 0))
            out.append((line, ctx, 1))
    return out


def train(
    seed: int = 7, l2: float = 1e-3, epochs: int = 400, lr: float = 0.5, valid_share: float = 0.25
) -> tuple[EOTModel, dict[str, Any]]:
    rng = random.Random(seed)
    train_ex: list[tuple[str, str, int]] = []
    valid_ex: list[tuple[str, str, int]] = []
    for lang in ("en", "de"):
        lines = corpus(lang)
        every = set(lines)
        shuffled = lines[:]
        rng.shuffle(shuffled)
        cut = int(len(shuffled) * valid_share)
        valid_ex += examples(shuffled[:cut], every)
        train_ex += examples(shuffled[cut:], every)
    model = _fit(train_ex, l2, epochs, lr)
    meta = {"train": _report(model, train_ex), "valid": _report(model, valid_ex), "seed": seed, "examples": len(train_ex) + len(valid_ex)}
    # the shipped model is refit on everything once the held-out numbers are recorded
    final = _fit(train_ex + valid_ex, l2, epochs, lr)
    return final, meta


def _fit(ex: list[tuple[str, str, int]], l2: float, epochs: int, lr: float) -> EOTModel:
    x = np.stack([_vec(features(t, c)) for t, c, _ in ex])
    y = np.array([lab for _, _, lab in ex], dtype=np.float32)
    # weight the classes equally: there are many more unfinished prefixes than finished turns
    pos = max(1.0, float(y.sum()))
    neg = max(1.0, float(len(y) - y.sum()))
    sw = np.where(y == 1, len(y) / (2 * pos), len(y) / (2 * neg)).astype(np.float32)
    w = np.zeros(DIM, dtype=np.float32)
    b = 0.0
    for _ in range(epochs):
        z = x @ w + b
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        g = (p - y) * sw
        w -= lr * ((x.T @ g) / len(y) + l2 * w)
        b -= lr * float(g.mean())
    return EOTModel(w, b)


def _report(m: EOTModel, ex: list[tuple[str, str, int]]) -> dict[str, Any]:
    ps = np.array([m.probability(t, c) for t, c, _ in ex])
    ys = np.array([lab for _, _, lab in ex])
    pos, neg = ps[ys == 1], ps[ys == 0]
    auc = float(np.mean([(p > n) + 0.5 * (p == n) for p in pos for n in neg])) if len(pos) and len(neg) else float("nan")
    out: dict[str, Any] = {"n": len(ex), "finished": int(ys.sum()), "auc": round(auc, 3)}
    for thr in (0.35, 0.55, 0.75):
        out[f"at_{thr}"] = {
            "cuts_unfinished": round(float(np.mean(neg >= thr)), 3),  # the agent would barge in
            "finished_recognised": round(float(np.mean(pos >= thr)), 3),  # answered without waiting for max pause
        }
    return out
