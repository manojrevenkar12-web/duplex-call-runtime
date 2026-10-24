"""Run simulated calls against a real runtime: the server, two simulated LLM providers and the
callers, each on its own port, speaking the production protocols."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .. import config
from ..llm.sim_provider import Profile, make_app
from ..serve_util import Background
from ..store import Store
from .caller import Caller, Scenario, Timeline


def load_scenarios(folder: Path) -> list[Scenario]:
    return [Scenario.from_dict(yaml.safe_load(p.read_text())) for p in sorted(folder.glob("*.yaml"))]


@dataclass
class Stack:
    url: str
    store: Store
    primary: Profile
    secondary: Profile
    provider_urls: tuple[str, str]


@contextlib.contextmanager
def stack(
    settings_over: dict[str, Any] | None = None, primary: Profile | None = None, secondary: Profile | None = None, db: Path | None = None
) -> Iterator[Stack]:
    from ..server import create_app

    p1 = primary or Profile(ttft_median_ms=380, seed=11)
    p2 = secondary or Profile(ttft_median_ms=420, seed=12)
    with Background(make_app(p1, "primary")) as a, Background(make_app(p2, "secondary")) as b:
        over = {"llm": {"providers": [{"name": "primary", "base_url": a.url + "/v1"}, {"name": "secondary", "base_url": b.url + "/v1"}]}}
        cfg = config.settings(config.merge(over, settings_over or {}))
        tmp = tempfile.mkdtemp(prefix="dcr-")
        store = Store(db or Path(tmp) / "calls.sqlite")
        with Background(create_app(cfg, store)) as srv:
            yield Stack(f"ws://127.0.0.1:{srv.port}/media", store, p1, p2, (a.url, b.url))


async def call(st: Stack, sc: Scenario, options: dict[str, Any] | None = None, seed: int = 0) -> tuple[Timeline, dict[str, Any], str]:
    cid = f"{sc.id}-{uuid.uuid4().hex[:6]}"
    tl = await Caller(sc, st.url, cid, options=options, seed=seed).run()
    for _ in range(100):  # the server saves the call when its socket closes
        rec = st.store.get(cid)
        if rec:
            return tl, rec, cid
        await asyncio.sleep(0.05)
    raise RuntimeError(f"call {cid} was not recorded")
