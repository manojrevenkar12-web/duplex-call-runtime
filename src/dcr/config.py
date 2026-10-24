"""Settings from config/*.yaml. Code reads thresholds and budgets from here, never from literals."""

from __future__ import annotations

import copy
import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("DCR_HOME", Path(__file__).resolve().parents[2]))
CONFIG_DIR = Path(os.environ.get("DCR_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.environ.get("DCR_DATA_DIR", ROOT / "data"))
MODELS_DIR = DATA_DIR / "models"


@cache
def load(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / f"{name}.yaml") as f:
        return yaml.safe_load(f) or {}


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def settings(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The settings, with DCR_SETTINGS_OVERRIDE (inline YAML) and then `overrides` applied on top."""
    s = load("settings")
    env = os.environ.get("DCR_SETTINGS_OVERRIDE")
    if env:
        s = merge(s, yaml.safe_load(env) or {})
    return merge(s, overrides or {})
