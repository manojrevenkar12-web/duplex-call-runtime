"""The runtime never looks at the simulator or at what a call is expected to produce."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "dcr"
RUNTIME = ["agent", "turn", "speech", "audio", "serving", "text", "llm/router.py", "llm/brain.py", "server.py", "store.py"]


def _files() -> list[Path]:
    out: list[Path] = []
    for r in RUNTIME:
        p = SRC / r
        out += sorted(p.rglob("*.py")) if p.is_dir() else [p]
    return out


def test_runtime_never_imports_the_simulator() -> None:
    bad = []
    for f in _files():
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ImportFrom):
                mod = ("." * node.level) + (node.module or "")
                if "sim" in mod.split(".") and not mod.endswith("sim_provider"):
                    bad.append(f"{f.relative_to(SRC)}: {mod}")
            if isinstance(node, ast.Import):
                bad += [f"{f.relative_to(SRC)}: {a.name}" for a in node.names if a.name.startswith("dcr.sim")]
    assert not bad, bad


def test_runtime_never_reads_expectations() -> None:
    for f in _files():
        text = f.read_text()
        assert '"expect"' not in text and "'expect'" not in text and ".expect" not in text, f
