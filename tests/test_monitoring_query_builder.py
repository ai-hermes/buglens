from __future__ import annotations

from buglens.monitoring.query_builder import (
    build_rum_search_query,
    parse_last_duration_ms,
    resolve_time_range,
)


def test_parse_last_duration_ms() -> None:
    assert parse_last_duration_ms("15m") == 15 * 60_000
    assert parse_last_duration_ms("2h") == 2 * 3_600_000
    assert parse_last_duration_ms("1d") == 86_400_000


def test_build_rum_search_query_structured() -> None:
    query = build_rum_search_query(
        event_type="exception",
        app_id="a@b",
        app_types=["browser", "miniapp"],
        exception_message='RUM_UNHANDLED_REJECTION: "boom"',
        keyword="TypeError",
    )
    assert "(app.type : browser or app.type : miniapp)" in query
    assert 'app.id : "a@b"' in query
    assert 'exception.message : "RUM_UNHANDLED_REJECTION: \\"boom\\""' in query
    assert "event_type: exception" in query
    assert "TypeError" in query


def test_build_rum_search_query_raw_override() -> None:
    query = build_rum_search_query(query='event_type: exception and app.id : "x"')
    assert query == 'event_type: exception and app.id : "x"'


def test_resolve_time_range_with_last() -> None:
    from_ms, to_ms = resolve_time_range(from_ms=None, to_ms=None, last="1h")
    assert to_ms >= from_ms
    assert to_ms - from_ms == 3_600_000
