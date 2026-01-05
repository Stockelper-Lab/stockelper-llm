from __future__ import annotations

from langchain_compat import iter_stream_tokens


def test_iter_stream_tokens_preserves_spaces_when_joined() -> None:
    text = "실시간 주가 데이터에는 직접 접근할 수 없습니다."
    tokens = list(iter_stream_tokens(text))
    assert "".join(tokens) == text


def test_iter_stream_tokens_preserves_newlines_when_joined() -> None:
    text = "첫 줄\n\n둘째 줄"
    tokens = list(iter_stream_tokens(text))
    assert "".join(tokens) == text


