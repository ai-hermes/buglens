from __future__ import annotations

import time
from typing import Iterable


def parse_last_duration_ms(value: str) -> int:
    raw = value.strip().lower()
    if len(raw) < 2:
        raise ValueError("last must look like 15m/1h/24h")
    unit = raw[-1]
    number_text = raw[:-1]
    if not number_text.isdigit():
        raise ValueError("last must use an integer value, e.g. 1h")
    number = int(number_text)
    if number <= 0:
        raise ValueError("last must be > 0")
    factors = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    if unit not in factors:
        raise ValueError("last unit must be one of m/h/d")
    return number * factors[unit]


def resolve_time_range(
    *,
    from_ms: int | None,
    to_ms: int | None,
    last: str | None = None,
) -> tuple[int, int]:
    if from_ms is not None and to_ms is not None:
        return int(from_ms), int(to_ms)
    now_ms = int(time.time() * 1000)
    if last:
        return now_ms - parse_last_duration_ms(last), now_ms
    default_from = now_ms - 60 * 60 * 1000
    return int(from_ms or default_from), int(to_ms or now_ms)


def _quote_sls_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_rum_search_query(
    *,
    query: str | None = None,
    event_type: str | None = "exception",
    app_id: str | None = None,
    app_types: str | Iterable[str] | None = None,
    exception_message: str | None = None,
    keyword: str | None = None,
) -> str:
    if query:
        return str(query)

    terms: list[str] = ["*"]
    app_type_list: list[str] = []
    if isinstance(app_types, str):
        app_type_list = [app_types]
    elif app_types is not None:
        app_type_list = [str(item) for item in app_types if str(item).strip()]
    if app_type_list:
        app_type_expr = " or ".join(f"app.type : {item}" for item in app_type_list)
        terms.append(f"({app_type_expr})")

    if event_type:
        terms.append(f"event_type: {event_type}")
    if app_id:
        terms.append(f'app.id : {_quote_sls_value(str(app_id))}')
    if exception_message:
        terms.append(f'exception.message : {_quote_sls_value(str(exception_message))}')
    if keyword:
        terms.append(str(keyword))

    return " and ".join(terms)
