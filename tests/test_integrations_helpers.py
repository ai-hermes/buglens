from buglens.integrations.arms import extract_trace_id_from_event_url, parse_source_mapped


def test_extract_trace_id_from_event_url() -> None:
    url = "https://arms.console.aliyun.com/path?traceId=abc123&x=1"
    assert extract_trace_id_from_event_url(url) == "abc123"


def test_parse_source_mapped() -> None:
    stack = (
        "TypeError: x\n"
        " at OrderList (webpack:///src/pages/order/ConfirmPage.tsx:42:18)\n"
        " at bootstrap (webpack/bootstrap:1:2)\n"
    )
    parsed = parse_source_mapped(stack)
    assert parsed is not None
    assert parsed["file"] == "ConfirmPage.tsx"
    assert parsed["line"] == 42
