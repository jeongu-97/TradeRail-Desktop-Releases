"""Derive domestic price-series sessions without conflating venues.

KRX supplies trading dates; NXT has its own regular-market ranges and SOR
represents the union of KRX and NXT trades, not their order-entry windows.
Sources: https://www.nextrade.co.kr/menu/transactionSys.do and the exchange's
2026 New Year notice (scNttNo=31). Delayed KRX openings suppress NXT premarket;
the main market starts 30 seconds later and brackets the KRX close by 10 min.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


SEOUL = ZoneInfo("Asia/Seoul")
NXT_FIRST_SESSION = date(2025, 3, 4)
# The exchange_calendars KRX snapshot omits this published CSAT exception.
# Apply it to both KRX and derived venues, including older cached snapshots.
# https://money2.daishin.com/e5/mboard/ptype_basic/basic_001/DW_Basic_Read.aspx?boardseq=114&m=1108&p=1385&page=1&seq=17899&v=2247
_KRX_DAY_OVERRIDES = {
    date(2025, 11, 13): (time(10), time(16, 30)),
}


def domestic_venue_ranges(
    market: str,
    *,
    session_date: date,
    krx_ranges: tuple[tuple[datetime, datetime], ...],
) -> tuple[tuple[datetime, datetime], ...]:
    """Use KRX trading dates while retaining each venue's actual trade hours."""

    if market not in {"NXT", "SOR"}:
        raise ValueError(f"domestic_venue_invalid:{market}")
    if not krx_ranges:
        return ()

    def at(clock: time) -> datetime:
        return datetime.combine(session_date, clock, tzinfo=SEOUL).astimezone(timezone.utc)

    nxt: list[tuple[datetime, datetime]] = []
    if session_date >= NXT_FIRST_SESSION:
        override = _KRX_DAY_OVERRIDES.get(session_date)
        if override is not None:
            krx_ranges = ((at(override[0]), at(override[1])),)
        opened, closed = krx_ranges[0][0], krx_ranges[-1][1]
        if opened.astimezone(SEOUL).time() == time(9):
            nxt.append((at(time(8)), at(time(8, 50))))
        nxt.extend((
            (opened + timedelta(seconds=30), closed - timedelta(minutes=10)),
            (closed + timedelta(minutes=10), at(time(20))),
        ))
    ranges = nxt if market == "NXT" else [*krx_ranges, *nxt]
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(ranges):
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def with_domestic_venue_calendars(markets: dict[str, Any]) -> dict[str, Any]:
    """Correct published KRX exceptions and add missing NXT/SOR calendars.

    The generator and Agent compatibility path share this derivation so an
    older cached/remote snapshot also supplies consistent venue boundaries.
    Explicit NXT/SOR calendars win over derivation. Inputs are not mutated,
    preserving the source snapshot's revision/ETag for cache synchronization.
    """

    krx = markets.get("KRX")
    if not isinstance(krx, dict):
        return dict(markets)
    result = dict(markets)
    corrected_sessions: list[dict[str, Any]] = []
    for raw in krx["sessions"]:
        session_date = date.fromisoformat(raw["date"])
        override = _KRX_DAY_OVERRIDES.get(session_date)
        if override is not None:
            raw = {
                **raw,
                "open": _iso(datetime.combine(session_date, override[0], tzinfo=SEOUL)),
                "close": _iso(datetime.combine(session_date, override[1], tzinfo=SEOUL)),
                "breaks": [],
            }
        corrected_sessions.append(raw)
    krx = {**krx, "sessions": corrected_sessions}
    result["KRX"] = krx
    for market in ("NXT", "SOR"):
        if market in result:
            continue
        sessions: list[dict[str, Any]] = []
        for raw in krx["sessions"]:
            opened, closed = _parse(raw["open"]), _parse(raw["close"])
            krx_ranges: list[tuple[datetime, datetime]] = []
            cursor = opened
            for start, end in raw.get("breaks") or []:
                krx_ranges.append((cursor, _parse(start)))
                cursor = _parse(end)
            krx_ranges.append((cursor, closed))
            ranges = domestic_venue_ranges(
                market, session_date=date.fromisoformat(raw["date"]),
                krx_ranges=tuple(krx_ranges),
            )
            if not ranges:
                continue

            sessions.append({
                "date": raw["date"],
                "open": _iso(ranges[0][0]),
                "close": _iso(ranges[-1][1]),
                "breaks": [[_iso(left[1]), _iso(right[0])] for left, right in zip(ranges, ranges[1:])],
            })
        result[market] = {
            "calendar": f"XKRX+{market}",
            "timezone": "Asia/Seoul",
            "coverage": dict(krx["coverage"]),
            "sessions": sessions,
        }
    return result
