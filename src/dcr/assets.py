"""Pinned models (config/assets.yaml), downloaded over HTTPS and checked by SHA-256 before use."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
from pathlib import Path

import httpx

from . import config


class AssetError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_dir(name: str) -> Path:
    """Where model `name` lives once fetched: a file for single-file models, else the unpacked folder."""
    spec = config.load("assets")["models"][name]
    base = config.MODELS_DIR / name
    if spec["url"].endswith(".tar.bz2"):
        subs = [p for p in base.iterdir() if p.is_dir()] if base.exists() else []
        if not subs:
            raise AssetError(f"model {name} not fetched: run `dcr fetch`")
        return subs[0]
    return base / spec["url"].rsplit("/", 1)[-1]


def have(names: list[str] | None = None) -> bool:
    try:
        for n in names or list(config.load("assets")["models"]):
            p = model_dir(n)
            if not p.exists():
                return False
        return True
    except AssetError:
        return False


def fetch(names: list[str] | None = None, client: httpx.Client | None = None) -> list[str]:
    models = config.load("assets")["models"]
    done = []
    own = client is None
    c = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0))
    try:
        for name in names or list(models):
            spec = models[name]
            if have([name]):
                continue
            url, sha = spec["url"], spec["sha256"]
            if not url.startswith("https://"):
                raise AssetError(f"refusing non-https URL {url}")
            dl = config.MODELS_DIR / "downloads" / url.rsplit("/", 1)[-1]
            dl.parent.mkdir(parents=True, exist_ok=True)
            if not (dl.exists() and _sha(dl) == sha):
                tmp = dl.with_suffix(dl.suffix + ".part")
                for attempt in range(3):
                    try:
                        with c.stream("GET", url) as r:
                            r.raise_for_status()
                            with open(tmp, "wb") as f:
                                for chunk in r.iter_bytes(1 << 20):
                                    f.write(chunk)
                        if _sha(tmp) != sha:
                            raise AssetError(f"{name}: checksum mismatch")
                        tmp.replace(dl)
                        break
                    except (httpx.HTTPError, AssetError):
                        if attempt == 2:
                            raise
            dest = config.MODELS_DIR / name
            shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True)
            if url.endswith(".tar.bz2"):
                with tarfile.open(dl) as tf:
                    tf.extractall(dest, filter="data")
            else:
                shutil.copy(dl, dest / dl.name)
            done.append(name)
    finally:
        if own:
            c.close()
    return done
