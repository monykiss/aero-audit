"""The fuzz harness itself: every target runs its seed inputs without an unexpected exception (no atheris needed)."""

import subprocess
import sys
from pathlib import Path

import fuzz.fuzz_targets as fz


def test_every_target_survives_its_seeds():
    for name, fn in fz.TARGETS.items():
        for seed in fz.SEEDS[name]:
            fn(seed)
    assert fz.smoke() == 0


def test_harness_cli_smoke_and_usage():
    r = subprocess.run([sys.executable, str(Path("fuzz/fuzz_targets.py")), "--smoke"], capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0 and "no unexpected exception" in r.stdout
    r = subprocess.run([sys.executable, str(Path("fuzz/fuzz_targets.py")), "nope"], capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 2 and "usage" in r.stdout
