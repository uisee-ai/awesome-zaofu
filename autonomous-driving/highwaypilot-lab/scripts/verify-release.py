#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from highwaypilot_lab.release import ReleaseIntegrityError, verify_release  # noqa: E402


def main() -> int:
    try:
        receipt = verify_release(
            PROJECT_ROOT,
            PROJECT_ROOT / "dist/release-candidates/v1-rc1",
            PROJECT_ROOT / "artifacts/verification/releases/v1-rc1",
        )
    except ReleaseIntegrityError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
