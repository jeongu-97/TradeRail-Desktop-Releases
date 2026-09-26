#!/usr/bin/env python3
"""Generate the compact calendar snapshot consumed by Relay and Agent."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from market_calendar_contract import (  # noqa: E402
    market_calendar_revision,
    validate_market_calendar_snapshot,
)


CALENDARS: dict[str, tuple[str, str]] = {
    "KRX": ("XKRX", "Asia/Seoul"),
    "US": ("XNYS", "America/New_York"),
    "HKEX": ("XHKG", "Asia/Hong_Kong"),
    "CHINA": ("XSHG", "Asia/Shanghai"),
    "JPX": ("XTKS", "Asia/Tokyo"),
}
MARKET_ALIASES = {
    "KRX": "KRX",
    "KOSPI": "KRX",
    "KOSDAQ": "KRX",
    "NASD": "US",
    "NASDAQ": "US",
    "NYSE": "US",
    "AMEX": "US",
    "US": "US",
    "SEHK": "HKEX",
    "HKEX": "HKEX",
    "SHAA": "CHINA",
    "SZAA": "CHINA",
    "CHINA": "CHINA",
    "TKSE": "JPX",
    "JPX": "JPX",
}


def _utc_iso(value: Any) -> str:
    return value.to_pydatetime().astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def build_snapshot(*, start: str, end: str, generated_at: str) -> dict[str, Any]:
    try:
        import exchange_calendars as xcals
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - actionable CLI failure
        raise SystemExit(
            "Install calendar/requirements.txt before generation"
        ) from exc

    markets: dict[str, Any] = {}
    for market, (calendar_name, timezone_name) in CALENDARS.items():
        calendar_type = xcals.get_calendar(calendar_name).__class__
        bound_max = calendar_type.bound_max()
        market_end = min(
            datetime.strptime(end, "%Y-%m-%d").date(),
            bound_max.date() if bound_max is not None else datetime.max.date(),
        ).isoformat()
        calendar = xcals.get_calendar(calendar_name, start=start, end=market_end)
        sessions: list[dict[str, Any]] = []
        for session_date, row in calendar.schedule.iterrows():
            breaks: list[list[str]] = []
            break_start = row.get("break_start")
            break_end = row.get("break_end")
            if not pd.isna(break_start) and not pd.isna(break_end):
                breaks.append([_utc_iso(break_start), _utc_iso(break_end)])
            sessions.append(
                {
                    "date": session_date.strftime("%Y-%m-%d"),
                    "open": _utc_iso(row["open"]),
                    "close": _utc_iso(row["close"]),
                    "breaks": breaks,
                }
            )
        markets[market] = {
            "calendar": calendar_name,
            "timezone": timezone_name,
            "coverage": {"start": start, "end": market_end},
            "sessions": sessions,
        }

    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": generated_at,
        "source": {
            "library": "exchange_calendars",
            "version": str(xcals.__version__),
        },
        "coverage": {"start": start, "end": end},
        "market_aliases": MARKET_ALIASES,
        "markets": markets,
    }
    snapshot["revision"] = market_calendar_revision(snapshot)
    return validate_market_calendar_snapshot(snapshot)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2035-12-31")
    parser.add_argument(
        "--generated-at",
        default=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "shared" / "market_calendar.v1.json",
    )
    args = parser.parse_args()
    snapshot = build_snapshot(
        start=args.start,
        end=args.end,
        generated_at=args.generated_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output} ({snapshot['revision'][:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
