"""Run unit tests for each service in separate subprocess.

All three services share the 'app' package name, so they can't coexist
in a single Python process. This script runs each service's tests in
isolation and aggregates results.
"""
import subprocess
import sys

SERVICES = [
    ("api", "tests/unit/api/"),
    ("publisher", "tests/unit/publisher/"),
    ("worker", "tests/unit/worker/"),
]


def main():
    failed = []
    extra_args = sys.argv[1:]

    for name, path in SERVICES:
        print(f"\n{'='*60}")
        print(f"  Running {name} unit tests")
        print(f"{'='*60}")
        cmd = [sys.executable, "-m", "pytest", path, "-v", "--tb=short"] + extra_args
        result = subprocess.run(cmd)
        if result.returncode != 0:
            failed.append(name)

    print(f"\n{'='*60}")
    if failed:
        print(f"  FAILED services: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("  All unit tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
