#!/usr/bin/env python3
"""Run named unittest modules and reject empty or skipped validation gates."""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("modules", nargs="+", help="unittest module names")
    args = parser.parse_args()

    sys.path.insert(0, str(TESTS_DIR))
    suite = unittest.defaultTestLoader.loadTestsFromNames(args.modules)
    test_count = suite.countTestCases()
    if test_count == 0:
        print("Validation gate discovered zero tests", file=sys.stderr)
        return 2

    print(f"Running {test_count} tests from: {', '.join(args.modules)}")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        skipped = ", ".join(f"{test}: {reason}" for test, reason in result.skipped)
        print(f"Unexpected skipped tests: {skipped}", file=sys.stderr)
        return 2
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
