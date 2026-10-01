#!/usr/bin/env python3
"""Generate the compact calendar snapshot consumed by Relay and Agent."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 이 파일은 공개 저장소의 주간 발행 워크플로에도 그대로 복사된다
# (scripts/sync_market_calendar_publisher.py). 거기에는 node_core 패키지가 없고
# 같은 폴더에 두 모듈이 나란히 있으므로, 사본을 따로 고치지 않도록 여기서 가른다.
try:
    from node_core.domestic_market_sessions import (  # noqa: E402
        with_domestic_venue_calendars,
    )
    from node_core.market_calendar_contract import (  # noqa: E402
        market_calendar_revision,
        validate_market_calendar_snapshot,
    )
except ModuleNotFoundError:  # pragma: no cover - 공개 저장소의 평평한 배치
    from domestic_market_sessions import (  # type: ignore[import-not-found,no-redef]  # noqa: E402
        with_domestic_venue_calendars,
    )
    from market_calendar_contract import (  # type: ignore[import-not-found,no-redef]  # noqa: E402
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
    "NXT": "NXT",
    "SOR": "SOR",
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
    "HASE": "VIETNAM",
    "HNX": "VIETNAM",
    "DHNX": "VIETNAM",
    "VNSE": "VIETNAM",
    "HSX": "VIETNAM",
    "DHSX": "VIETNAM",
}

# Vietnam does not have an exchange_calendars implementation. Keep live-order
# coverage deliberately bounded to the official schedule we have verified;
# later years remain fail-closed until their exchange notice is incorporated.
# HNX's 2026 notice (also confirmed by VSDC) extends National Day closure to
# 31 August, which a generic statutory-holiday package does not include:
# https://hnx.vn/en-gb/chi-tiet-lich-nghi-gd-60021971.html?_page=1
_VIETNAM_VERIFIED_START = date(2026, 1, 1)
_VIETNAM_VERIFIED_END = date(2026, 12, 31)
_VIETNAM_EXCHANGE_CLOSURES = frozenset(
    {
        date(2026, 1, 1),
        *(date(2026, 2, day) for day in range(16, 21)),
        date(2026, 4, 27),
        date(2026, 4, 30),
        date(2026, 5, 1),
        date(2026, 8, 31),
        date(2026, 9, 1),
        date(2026, 9, 2),
    }
)


def _utc_iso(value: Any) -> str:
    converted = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    return converted.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _vietnam_sessions(*, start: str, end: str) -> list[dict[str, Any]]:
    """Build HNX/HOSE cash sessions from Vietnam's statutory holidays.

    ``exchange_calendars`` does not currently ship a Vietnam exchange calendar.
    HNX and HOSE share the same weekday/holiday schedule and regular trading
    hours, so the bundled snapshot derives one explicit, fail-closed calendar
    from the published 2026 HNX/VSDC schedule instead of falling back to
    weekdays or treating a generic statutory-holiday list as authoritative.
    """

    first = max(date.fromisoformat(start), _VIETNAM_VERIFIED_START)
    last = min(date.fromisoformat(end), _VIETNAM_VERIFIED_END)
    if first > last:
        return []
    zone = ZoneInfo("Asia/Ho_Chi_Minh")
    sessions: list[dict[str, Any]] = []
    day = first
    while day <= last:
        if (
            day.weekday() < 5
            and day not in _VIETNAM_EXCHANGE_CLOSURES
        ):
            opened = datetime.combine(day, time(9), tzinfo=zone)
            break_start = datetime.combine(day, time(11, 30), tzinfo=zone)
            break_end = datetime.combine(day, time(13), tzinfo=zone)
            closed_at = datetime.combine(day, time(15), tzinfo=zone)
            sessions.append(
                {
                    "date": day.isoformat(),
                    "open": _utc_iso(opened),
                    "close": _utc_iso(closed_at),
                    "breaks": [[_utc_iso(break_start), _utc_iso(break_end)]],
                }
            )
        day += timedelta(days=1)
    return sessions


def build_snapshot(*, start: str, end: str, generated_at: str) -> dict[str, Any]:
    try:
        import exchange_calendars as xcals
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - actionable CLI failure
        raise SystemExit(
            "Install tools/market_calendar/requirements.txt before generation"
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

    vietnam_start = max(date.fromisoformat(start), _VIETNAM_VERIFIED_START)
    vietnam_end = min(date.fromisoformat(end), _VIETNAM_VERIFIED_END)
    if vietnam_start > vietnam_end:
        raise SystemExit(
            "requested range does not overlap verified Vietnam exchange coverage"
        )
    markets["VIETNAM"] = {
        "calendar": "HNX-VSDC-2026",
        "timezone": "Asia/Ho_Chi_Minh",
        "coverage": {
            "start": vietnam_start.isoformat(),
            "end": vietnam_end.isoformat(),
        },
        "sessions": _vietnam_sessions(start=start, end=end),
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
        "markets": with_domestic_venue_calendars(markets),
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
    parser.add_argument(
        "--frontend-output",
        type=Path,
        default=None,
        help=(
            "identical copy for the web build; defaults to "
            "frontend/public/market_calendar.v1.json when that folder exists"
        ),
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
    frontend_output = args.frontend_output
    default_frontend_dir = REPO_ROOT / "frontend" / "public"
    if frontend_output is None and default_frontend_dir.is_dir():
        frontend_output = default_frontend_dir / "market_calendar.v1.json"
    if frontend_output is None:
        # 공개 저장소에는 웹 빌드가 없다.
        print(f"wrote {args.output} ({snapshot['revision'][:12]})")
        return 0
    frontend_output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.output, frontend_output)
    print(
        f"wrote {args.output} and {frontend_output} "
        f"({snapshot['revision'][:12]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
