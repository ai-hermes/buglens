from __future__ import annotations

import pytest

from buglens.monitoring.schemas.common import (
    MonitoringAdapterError,
    UnifiedErrorCode,
    decode_page_token,
    encode_page_token,
)


def test_page_token_roundtrip() -> None:
    token = encode_page_token({"page": 2, "offset": 10})
    assert decode_page_token(token) == {"page": 2, "offset": 10}


def test_decode_page_token_invalid_raises() -> None:
    with pytest.raises(MonitoringAdapterError) as exc:
        decode_page_token("bad-token-###")
    assert exc.value.code == UnifiedErrorCode.INVALID_PARAM
