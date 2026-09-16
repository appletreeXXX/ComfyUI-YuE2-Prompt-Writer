"""Run every offline check in sequence.

These are deliberately dependency-free plain scripts rather than pytest suites,
so they run inside ComfyUI's own interpreter with no test framework installed.

    python tests/run_all.py

Run this with **ComfyUI's own interpreter** (the ``python_embeded`` that ships
with the portable build). ``backend/models/_http.py`` imports ``aiohttp``, which
ComfyUI provides but a plain system Python does not, so starting this script with
the wrong interpreter reports three spurious failures. The pre-flight below says
so explicitly instead of letting you chase a phantom bug.

``check_frontend.mjs`` needs Node and is skipped when it is absent.
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (label, script, needs_node)
CHECKS = [
    ("lyric engine", "run_tests.py", False),
    ("bundled guides", "check_guides.py", False),
    ("provider assembly", "check_assembly.py", False),
    ("extension load", "check_extension_load.py", False),
    ("GGUF backend", "check_gguf.py", False),
    ("HTTP routes", "run_api_tests.py", False),
    ("frontend syntax", "check_frontend.mjs", True),
]

REQUIRED = ["aiohttp"]


def preflight() -> bool:
    """ComfyUI's interpreter supplies aiohttp; a bare system Python does not."""
    missing = [
        name for name in REQUIRED if importlib.util.find_spec(name) is None
    ]
    if not missing:
        return True
    print("=" * 68)
    print("wrong interpreter")
    print("=" * 68)
    print(f"  {sys.executable}")
    print(f"  missing: {', '.join(missing)}")
    print()
    print("  This extension imports aiohttp, which ships with ComfyUI.")
    print("  Re-run with ComfyUI's bundled interpreter, e.g. on Windows:")
    print("    E:\\ComfyUI\\python_embeded\\python.exe tests/run_all.py")
    print()
    return False


def main() -> int:
    if not preflight():
        return 1

    node = shutil.which("node")
    results = []
    for label, script, needs_node in CHECKS:
        if needs_node and not node:
            print("=" * 68)
            print(f"== {label}  ({script}) -- SKIPPED, node not on PATH")
            print("=" * 68)
            results.append((label, 0, True))
            continue

        path = HERE / script
        print("=" * 68)
        print(f"== {label}  ({script})")
        print("=" * 68)
        if needs_node:
            command = [node, "--experimental-vm-modules", str(path)]
        else:
            command = [sys.executable, str(path)]
        completed = subprocess.run(command)
        results.append((label, completed.returncode, False))
        print()

    print("=" * 68)
    print("summary")
    print("=" * 68)
    failed = 0
    for label, code, skipped in results:
        status = "SKIP" if skipped else ("PASS" if code == 0 else "FAIL")
        if code != 0:
            failed += 1
        print(f"  {status}  {label}")
    print()
    if failed:
        print(f"{failed} of {len(results)} check script(s) failed")
        return 1
    print(f"all {len(results)} check scripts passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
