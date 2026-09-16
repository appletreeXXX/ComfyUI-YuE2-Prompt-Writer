"""Run every offline check in sequence.

These are deliberately dependency-free plain scripts rather than pytest suites,
so they run inside ComfyUI's own interpreter with no test framework installed.

    python tests/run_all.py

``check_frontend.mjs`` needs Node and is skipped when it is absent.
"""

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


def main() -> int:
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
