#!/usr/bin/env python3
"""Validate a generated market calendar before atomically publishing it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from market_calendar_contract import (  # noqa: E402
    assert_market_calendar_non_regressing,
    validate_market_calendar_snapshot,
)


MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


def _load(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("market_calendar_snapshot_too_large")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_update(
    candidate_path: Path, current_path: Path | None
) -> dict[str, object]:
    candidate = validate_market_calendar_snapshot(_load(candidate_path))
    if current_path is not None and current_path.is_file():
        candidate = assert_market_calendar_non_regressing(
            _load(current_path), candidate
        )
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--current", type=Path)
    args = parser.parse_args()
    snapshot = validate_update(args.candidate, args.current)
    print(
        json.dumps(
            {
                "revision": snapshot["revision"],
                "generated_at": snapshot["generated_at"],
                "source": snapshot["source"],
                "coverage": snapshot["coverage"],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
