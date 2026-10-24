"""dcr: fetch models, serve calls, train the end-of-turn model, run the evaluation and benchmarks."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from . import config

app = typer.Typer(add_completion=False, help=__doc__)


SETS = {
    "runtime": ["silero_vad", "stt_en_nemo", "stt_whisper_base", "tts_en_lessac", "tts_de_thorsten"],
    "sim": ["tts_en_amy", "tts_en_ryan", "tts_en_gb_alan"],
    "compare": ["stt_en_streaming", "stt_whisper_tiny"],
}


@app.command()
def fetch(only: str = typer.Option("runtime,sim", help="model sets: runtime, sim (caller voices), compare, all")) -> None:
    """Download the pinned models (checked by SHA-256)."""
    from . import assets

    sets = list(SETS) if only == "all" else only.split(",")
    names = [n for s in sets for n in SETS[s]]
    typer.echo(json.dumps({"fetched": assets.fetch(names)}))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """The runtime: Twilio Media Streams at /media, TwiML at /twilio/voice, the inspector API."""
    import uvicorn

    uvicorn.run("dcr.server:app_from_env", host=host, port=port, factory=True, ws="websockets-sansio")


@app.command("sim-provider")
def sim_provider(
    port: int = 8781,
    name: str = "primary",
    ttft_ms: float = 380.0,
    slow_rate: float = 0.0,
    error_rate: float = 0.0,
    host: str = "127.0.0.1",
) -> None:
    """A simulated OpenAI-compatible LLM provider (for local runs without an API key)."""
    import uvicorn

    from .llm.sim_provider import Profile, make_app

    uvicorn.run(make_app(Profile(ttft_median_ms=ttft_ms, slow_rate=slow_rate, error_rate=error_rate), name), host=host, port=port)


@app.command("train-turn")
def train_turn() -> None:
    """Train the end-of-turn model on turn/corpus and write it, with its held-out numbers."""
    from .turn import model

    m, meta = model.train()
    m.save(model.MODEL_PATH, meta)
    typer.echo(json.dumps(meta["valid"], indent=1))


@app.command("eval")
def evaluate(
    folder: Path = Path("calls/dev"),
    configs: str = "full,silence_endpoint,no_speculation,no_echo_cancel,no_hedging",
    label: str = "dev",
) -> None:
    """Run every scenario under each configuration and write reports/EVAL_<label>.md."""
    from .sim import suite

    doc = suite.evaluate(folder, configs.split(","), config.ROOT / "reports", label=label)
    typer.echo(json.dumps(doc["summary"], indent=1, default=str))


@app.command()
def call(scenario: Path) -> None:
    """Place one simulated call and print its timeline."""
    import asyncio

    import yaml

    from .sim import metrics, run
    from .sim.caller import Scenario

    sc = Scenario.from_dict(yaml.safe_load(scenario.read_text()))
    with run.stack() as st:
        tl, rec, _ = asyncio.run(run.call(st, sc))
    for ev in rec["events"]:
        if ev["kind"] not in ("mark", "tts", "llm_request"):
            typer.echo(f"{ev['t']:>9.1f}  {ev['kind']:<22} {json.dumps({k: v for k, v in ev.items() if k not in ('t', 'kind')})[:160]}")
    typer.echo(json.dumps(metrics.score(sc, tl, rec), default=str, indent=1))


@app.command()
def heldout(set_name: str, configs: str = "full") -> None:
    """Run a held-out call set for the first (and only) recorded time: reports/heldout/<set>/."""
    from .sim import suite

    doc = suite.first_run(set_name, configs.split(","))
    typer.echo(json.dumps(doc["summary"], indent=1, default=str))


@app.command()
def bench(seconds: float = 20.0) -> None:
    """Serving benchmark: STT throughput and latency vs batch size, TTS time to first audio."""
    from .serving import bench as b

    typer.echo(json.dumps(b.run(seconds), indent=1))


if __name__ == "__main__":  # pragma: no cover
    app()
