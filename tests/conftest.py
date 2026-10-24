import pytest

from dcr import assets
from dcr.cli import SETS

HAVE_MODELS = assets.have(SETS["runtime"] + SETS["sim"])
needs_models = pytest.mark.skipif(not HAVE_MODELS, reason="pinned models missing: run `dcr fetch`")
