"""Framework-independent market-calendar snapshot contract.

The generated snapshot is shared by Relay, the frozen Agent, and the
frontend.  Keeping validation here lets Relay reject a malformed upstream
update before any trading process can cache it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MARKET_CALENDAR_SCHEMA_VERSION = 1
MARKET_CALENDAR_MAX_MARKETS = 16
MARKET_CALENDAR_MAX_SESSIONS_PER_MARKET = 20_000


class MarketCalendarContractError(ValueError):
    """Raised when a calendar snapshot violates the shared contract."""


def _iso_datetime(value: object, *, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise MarketCalendarContractError(f"{field}_required")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MarketCalendarContractError(f"{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise MarketCalendarContractError(f"{field}_timezone_required")
    return parsed


def _calendar_content(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if key != "revision"}


def market_calendar_revision(snapshot: dict[str, Any]) -> str:
    """Return the content hash used as the snapshot revision and HTTP ETag."""

    encoded = json.dumps(
        _calendar_content(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_market_calendar_snapshot(payload: object) -> dict[str, Any]:
    """Validate and normalize one generated or remotely supplied snapshot."""

    if not isinstance(payload, dict):
        raise MarketCalendarContractError("market_calendar_snapshot_object_required")
    snapshot = dict(payload)
    if snapshot.get("schema_version") != MARKET_CALENDAR_SCHEMA_VERSION:
        raise MarketCalendarContractError("market_calendar_schema_version_invalid")
    generated_at = _iso_datetime(
        snapshot.get("generated_at"), field="market_calendar_generated_at"
    )
    source = snapshot.get("source")
    if not isinstance(source, dict):
        raise MarketCalendarContractError("market_calendar_source_required")
    library = str(source.get("library") or "").strip()
    version = str(source.get("version") or "").strip()
    if library != "exchange_calendars" or not version:
        raise MarketCalendarContractError("market_calendar_source_invalid")

    coverage = snapshot.get("coverage")
    if not isinstance(coverage, dict):
        raise MarketCalendarContractError("market_calendar_coverage_required")
    coverage_start = str(coverage.get("start") or "").strip()
    coverage_end = str(coverage.get("end") or "").strip()
    try:
        start_day = datetime.strptime(coverage_start, "%Y-%m-%d").date()
        end_day = datetime.strptime(coverage_end, "%Y-%m-%d").date()
    except ValueError as exc:
        raise MarketCalendarContractError("market_calendar_coverage_invalid") from exc
    if start_day > end_day:
        raise MarketCalendarContractError("market_calendar_coverage_reversed")

    aliases = snapshot.get("market_aliases")
    if not isinstance(aliases, dict) or not aliases:
        raise MarketCalendarContractError("market_calendar_aliases_required")
    normalized_aliases: dict[str, str] = {}
    for raw_alias, raw_target in aliases.items():
        alias = str(raw_alias or "").strip().upper()
        target = str(raw_target or "").strip().upper()
        if not alias or not target:
            raise MarketCalendarContractError("market_calendar_alias_invalid")
        normalized_aliases[alias] = target

    markets = snapshot.get("markets")
    if not isinstance(markets, dict) or not markets:
        raise MarketCalendarContractError("market_calendar_markets_required")
    if len(markets) > MARKET_CALENDAR_MAX_MARKETS:
        raise MarketCalendarContractError("market_calendar_market_limit_exceeded")

    normalized_markets: dict[str, dict[str, Any]] = {}
    for raw_market, raw_spec in markets.items():
        market = str(raw_market or "").strip().upper()
        if not market or not isinstance(raw_spec, dict):
            raise MarketCalendarContractError("market_calendar_market_invalid")
        timezone_name = str(raw_spec.get("timezone") or "").strip()
        calendar_name = str(raw_spec.get("calendar") or "").strip()
        market_coverage = raw_spec.get("coverage")
        sessions = raw_spec.get("sessions")
        if (
            not timezone_name
            or not calendar_name
            or not isinstance(market_coverage, dict)
            or not isinstance(sessions, list)
        ):
            raise MarketCalendarContractError(
                f"market_calendar_market_spec_invalid:{market}"
            )
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise MarketCalendarContractError(
                f"market_calendar_timezone_invalid:{market}"
            ) from exc
        market_start_raw = str(market_coverage.get("start") or "").strip()
        market_end_raw = str(market_coverage.get("end") or "").strip()
        try:
            market_start = datetime.strptime(market_start_raw, "%Y-%m-%d").date()
            market_end = datetime.strptime(market_end_raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise MarketCalendarContractError(
                f"market_calendar_market_coverage_invalid:{market}"
            ) from exc
        if not (
            start_day <= market_start <= market_end <= end_day
        ):
            raise MarketCalendarContractError(
                f"market_calendar_market_coverage_bounds_invalid:{market}"
            )
        if len(sessions) > MARKET_CALENDAR_MAX_SESSIONS_PER_MARKET:
            raise MarketCalendarContractError(
                f"market_calendar_session_limit_exceeded:{market}"
            )
        normalized_sessions: list[dict[str, Any]] = []
        previous_date = ""
        for raw_session in sessions:
            if not isinstance(raw_session, dict):
                raise MarketCalendarContractError(
                    f"market_calendar_session_invalid:{market}"
                )
            session_date = str(raw_session.get("date") or "").strip()
            try:
                day = datetime.strptime(session_date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise MarketCalendarContractError(
                    f"market_calendar_session_date_invalid:{market}"
                ) from exc
            if not (market_start <= day <= market_end) or session_date <= previous_date:
                raise MarketCalendarContractError(
                    f"market_calendar_session_order_invalid:{market}"
                )
            previous_date = session_date
            opened_at = _iso_datetime(
                raw_session.get("open"),
                field=f"market_calendar_session_open:{market}:{session_date}",
            )
            closed_at = _iso_datetime(
                raw_session.get("close"),
                field=f"market_calendar_session_close:{market}:{session_date}",
            )
            if opened_at >= closed_at:
                raise MarketCalendarContractError(
                    f"market_calendar_session_bounds_invalid:{market}:{session_date}"
                )
            raw_breaks = raw_session.get("breaks") or []
            if not isinstance(raw_breaks, list) or len(raw_breaks) > 4:
                raise MarketCalendarContractError(
                    f"market_calendar_breaks_invalid:{market}:{session_date}"
                )
            normalized_breaks: list[list[str]] = []
            previous_break_end = opened_at
            for raw_break in raw_breaks:
                if not isinstance(raw_break, list) or len(raw_break) != 2:
                    raise MarketCalendarContractError(
                        f"market_calendar_break_invalid:{market}:{session_date}"
                    )
                break_start = _iso_datetime(
                    raw_break[0],
                    field=f"market_calendar_break_start:{market}:{session_date}",
                )
                break_end = _iso_datetime(
                    raw_break[1],
                    field=f"market_calendar_break_end:{market}:{session_date}",
                )
                if not (
                    previous_break_end <= break_start < break_end <= closed_at
                ):
                    raise MarketCalendarContractError(
                        f"market_calendar_break_bounds_invalid:{market}:{session_date}"
                    )
                normalized_breaks.append([str(raw_break[0]), str(raw_break[1])])
                previous_break_end = break_end
            normalized_sessions.append(
                {
                    "date": session_date,
                    "open": str(raw_session.get("open")),
                    "close": str(raw_session.get("close")),
                    "breaks": normalized_breaks,
                }
            )
        normalized_markets[market] = {
            "calendar": calendar_name,
            "timezone": timezone_name,
            "coverage": {"start": market_start_raw, "end": market_end_raw},
            "sessions": normalized_sessions,
        }

    for alias, target in normalized_aliases.items():
        if target not in normalized_markets:
            raise MarketCalendarContractError(
                f"market_calendar_alias_target_unknown:{alias}"
            )

    normalized: dict[str, Any] = {
        "schema_version": MARKET_CALENDAR_SCHEMA_VERSION,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "source": {"library": library, "version": version},
        "coverage": {"start": coverage_start, "end": coverage_end},
        "market_aliases": normalized_aliases,
        "markets": normalized_markets,
    }
    expected_revision = market_calendar_revision(normalized)
    supplied_revision = str(snapshot.get("revision") or "").strip().lower()
    if supplied_revision and not hmac.compare_digest(
        supplied_revision, expected_revision
    ):
        raise MarketCalendarContractError("market_calendar_revision_mismatch")
    normalized["revision"] = expected_revision
    return normalized


def assert_market_calendar_non_regressing(
    current: object,
    candidate: object,
) -> dict[str, Any]:
    """Return a validated candidate only when it preserves published coverage."""

    normalized_current = validate_market_calendar_snapshot(current)
    normalized_candidate = validate_market_calendar_snapshot(candidate)
    current_generated_at = _iso_datetime(
        normalized_current["generated_at"], field="market_calendar_generated_at"
    )
    candidate_generated_at = _iso_datetime(
        normalized_candidate["generated_at"], field="market_calendar_generated_at"
    )
    if candidate_generated_at < current_generated_at:
        raise MarketCalendarContractError("market_calendar_generated_at_regressed")
    for market, current_spec in normalized_current["markets"].items():
        candidate_spec = normalized_candidate["markets"].get(market)
        if candidate_spec is None:
            raise MarketCalendarContractError(
                f"market_calendar_market_removed:{market}"
            )
        current_coverage = current_spec["coverage"]
        candidate_coverage = candidate_spec["coverage"]
        if (
            candidate_coverage["start"] > current_coverage["start"]
            or candidate_coverage["end"] < current_coverage["end"]
        ):
            raise MarketCalendarContractError(
                f"market_calendar_coverage_regressed:{market}"
            )
    return normalized_candidate


__all__ = [
    "MARKET_CALENDAR_SCHEMA_VERSION",
    "MarketCalendarContractError",
    "assert_market_calendar_non_regressing",
    "market_calendar_revision",
    "validate_market_calendar_snapshot",
]
