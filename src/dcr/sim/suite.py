"""The evaluation: every scenario under every configuration, scored from the caller's side.

Configurations switch one thing off at a time, so each piece of the runtime has to earn its
place in numbers:

- **full**: everything on (the shipped settings).
- **silence_endpoint**: answer after 800 ms of silence; no transcript-based end of turn.
- **no_speculation**: the LLM starts only once the turn is over.
- **no_echo_cancel**: no echo cancellation or suppression.
- **no_hedging**: one provider at a time; the second only on an error.
- **pause_on_barge_in**: stop the audio at a possible interruption instead of ducking it.

All configurations meet the same providers. Both have a realistic slow tail: 8% of requests
wait an extra 1.2 s before their first token. Otherwise hedging would have nothing to fix."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..llm.sim_provider import Profile
from . import metrics, run
from .caller import Scenario

CONFIGS: dict[str, dict[str, Any]] = {
    "full": {"options": {}, "settings": {}},
    "silence_endpoint": {"options": {"turn_mode": "silence", "speculate": False}, "settings": {}},
    "no_speculation": {"options": {"speculate": False}, "settings": {}},
    "no_echo_cancel": {"options": {"aec": False}, "settings": {}},
    "no_hedging": {"options": {}, "settings": {"llm": {"hedge_after_ms": 60000}}},
    "pause_on_barge_in": {"options": {}, "settings": {"barge_in": {"hold": "pause"}}},
}


def profiles(seed: int) -> tuple[Profile, Profile]:
    return (
        Profile(ttft_median_ms=380, ttft_sigma=0.3, slow_rate=0.08, slow_ms=1200, seed=seed),
        Profile(ttft_median_ms=430, ttft_sigma=0.3, slow_rate=0.08, slow_ms=1200, seed=seed + 1),
    )


async def _run_config(name: str, scenarios: list[Scenario], seed: int) -> list[dict[str, Any]]:
    spec = CONFIGS[name]
    p1, p2 = profiles(seed)
    out = []
    # calls are kept in the runtime's own database, so the console shows them
    with run.stack(spec["settings"], p1, p2, db=config.DATA_DIR / "calls.sqlite") as st:
        for i, sc in enumerate(scenarios):
            opts = {**sc.options, **spec["options"]}
            t0 = time.monotonic()
            tl, rec, cid = await run.call(st, sc, opts, seed=seed + i)
            res = metrics.score(sc, tl, rec)
            res["config"] = name
            res["call_id"] = cid
            res["seconds"] = round(time.monotonic() - t0, 1)
            out.append(res)
            print(
                f"  {name:17s} {sc.id:28s} task={res['task']} resp={res['response_ms']} takeover={res['pause_takeovers']}/{res['pause_lines']} "
                f"false_stops={res['false_stops']} interrupts={res['interrupts']} bc={res['backchannels']}",
                flush=True,
            )
    return out


def bootstrap_diff(a: list[float], b: list[float], n: int = 4000, seed: int = 0) -> tuple[float, float, float] | None:
    """Median difference b - a with a 95% bootstrap interval (independent samples)."""
    if len(a) < 3 or len(b) < 3:
        return None
    rng = np.random.default_rng(seed)
    aa, bb = np.asarray(a), np.asarray(b)
    diffs = [float(np.median(rng.choice(bb, len(bb))) - np.median(rng.choice(aa, len(aa)))) for _ in range(n)]
    return (
        round(float(np.median(bb) - np.median(aa)), 1),
        round(float(np.percentile(diffs, 2.5)), 1),
        round(float(np.percentile(diffs, 97.5)), 1),
    )


def evaluate(folder: Path, configs: list[str], out: Path | None = None, seed: int = 100, label: str = "dev") -> dict[str, Any]:
    scenarios = run.load_scenarios(folder)
    results: dict[str, list[dict[str, Any]]] = {}
    for name in configs:
        results[name] = asyncio.run(_run_config(name, scenarios, seed))
    summary = {name: metrics.aggregate(rs) for name, rs in results.items()}
    if "full" in results:
        full = [x for r in results["full"] for x in r["response_ms"]]
        for name, rs in results.items():
            if name != "full":
                summary[name]["response_vs_full"] = bootstrap_diff(full, [x for r in rs for x in r["response_ms"]])
    doc = {
        "set": label,
        "scenarios": [s.id for s in scenarios],
        "summary": summary,
        "calls": results,
        "settings": {"turn": config.settings()["turn"], "barge_in": config.settings()["barge_in"]},
    }
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / f"eval_{label}.json").write_text(json.dumps(doc, indent=1, default=str))
        (out / f"EVAL_{label.upper()}.md").write_text(markdown(doc))
    return doc


def first_run(set_name: str, configs: list[str] | None = None, seed: int = 100) -> dict[str, Any]:
    """Run a held-out set for the first time and record it. Refuses if it has run before: a
    first run is never rewritten (AGENTS.md)."""
    folder = config.ROOT / "calls" / "heldout" / set_name
    out = config.ROOT / "reports" / "heldout" / set_name
    if (out / "first_run.json").exists():
        raise FileExistsError(f"{set_name} already has a first run ({out / 'first_run.json'}); it is never rewritten")
    doc = evaluate(folder, configs or ["full"], None, seed=seed, label=set_name)
    doc["first_run"] = True
    doc["recorded_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    doc["commit"] = _commit()
    out.mkdir(parents=True, exist_ok=True)
    (out / "first_run.json").write_text(json.dumps(doc, indent=1, default=str))
    (out / "FIRST_RUN.md").write_text(markdown(doc) + _failures(doc))
    return doc


def _commit() -> str | None:
    """The checked-out commit, read from .git (no subprocess)."""
    git = config.ROOT / ".git"
    try:
        head = (git / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            ref = git / head[5:]
            if ref.exists():
                return ref.read_text().strip()
            packed = (git / "packed-refs").read_text().splitlines() if (git / "packed-refs").exists() else []
            return next((ln.split()[0] for ln in packed if ln.endswith(head[5:])), None)
        return head
    except OSError:
        return None


def _failures(doc: dict[str, Any]) -> str:
    lines = ["", "## Calls that failed their expectation", ""]
    for name, rs in doc["calls"].items():
        for r in rs:
            if r["task"] is False:
                wrong = ", ".join(r.get("task_wrong") or []) or "?"
                lines.append(f"- `{r['scenario']}` ({name}): wrong {wrong}; transcript WER {r['wer'][0]}/{r['wer'][1]} words")
    if len(lines) == 3:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def markdown(doc: dict[str, Any]) -> str:
    s = doc["summary"]
    rows = [
        ("Task success", lambda m: m["task_success"]),
        ("Time to first audio, p50 (ms)", lambda m: m["response_ms"]["p50"]),
        ("Time to first audio, p90 (ms)", lambda m: m["response_ms"]["p90"]),
        ("vs full: median difference, 95% CI (ms)", lambda m: _ci(m.get("response_vs_full"))),
        (
            "Takeovers in mid-sentence pauses",
            lambda m: f"{m['pause_takeover_rate']:.0%} of {m['pause_lines']}" if m["pause_takeover_rate"] is not None else "-",
        ),
        ("Interruptions stopped within 1.5 s", lambda m: m["interrupts_stopped"]),
        ("Interruption stop time, p50 (ms)", lambda m: m["interrupt_stop_ms"]["p50"]),
        ("Backchannels that stopped the agent", lambda m: m["backchannels_disrupted"]),
        ("False stops (echo, noise)", lambda m: m["false_stops"]),
        ("Transcript WER", lambda m: m["wer"]),
        ("Requests hedged to the second provider", lambda m: m["hedged"]),
    ]
    names = list(s)
    lines = [
        f"# Evaluation: {doc['set']} set",
        "",
        f"{len(doc['scenarios'])} simulated calls per configuration, scored from the caller's side of the line.",
        "",
    ]
    lines.append("| | " + " | ".join(names) + " |")
    lines.append("|---|" + "---:|" * len(names))
    for label, fn in rows:
        vals = []
        for n in names:
            try:
                v = fn(s[n])
            except (KeyError, TypeError):
                v = "-"
            vals.append("-" if v is None else str(v))
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    lines += [
        "",
        "## Per call (full configuration)",
        "",
        "| Scenario | Task | Wrong | Replies (ms) | Pause takeovers | Interrupt stop (ms) | False stops |",
        "|---|---|---|---|---|---|---:|",
    ]
    for r in doc["calls"].get("full", []):
        lines.append(
            f"| {r['scenario']} | {r['task']} | {', '.join(r.get('task_wrong') or []) or '-'} | "
            f"{', '.join(str(int(x)) for x in r['response_ms'])} | {r['pause_takeovers']}/{r['pause_lines']} | "
            f"{', '.join(str(i['stop_ms']) for i in r['interrupts']) or '-'} | {r['false_stops']} |"
        )
    return "\n".join(lines) + "\n"


def _ci(v: Any) -> str:
    return f"{v[0]:+} [{v[1]:+}, {v[2]:+}]" if v else "-"
