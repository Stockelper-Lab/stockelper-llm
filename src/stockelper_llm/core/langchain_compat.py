from __future__ import annotations

from typing import Any, Iterable


def _content_block_to_text(block: Any) -> str:
    """LangChain v1 content blocks → plain text (best-effort)."""
    if block is None:
        return ""

    if isinstance(block, str):
        return block

    if isinstance(block, dict):
        text = block.get("text")
        if isinstance(text, str):
            return text

        inner = block.get("content")
        if inner is not None:
            return _content_to_text(inner)
        return ""

    text_attr = getattr(block, "text", None)
    if isinstance(text_attr, str):
        return text_attr

    return ""


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_block_to_text(b) for b in content)
    if isinstance(content, dict):
        return _content_block_to_text(content)
    return ""


def message_to_text(message: Any) -> str:
    """LangChain message(v0/v1)에서 사용자에게 보여줄 텍스트만 추출."""
    if message is None:
        return ""

    try:
        text_prop = getattr(message, "text", None)
        if isinstance(text_prop, str):
            return text_prop
        if callable(text_prop):
            text_val = text_prop()
            if isinstance(text_val, str):
                return text_val
    except Exception:
        pass

    content = getattr(message, "content", None)
    return _content_to_text(content)


def tokenize_korean(text: str) -> list[str]:
    """SSE delta 스트리밍을 위한 한국어 친화 토크나이즈(간단 규칙)."""
    import re

    if not text:
        return []
    return re.findall(r"[\w가-힣]+|[^\w가-힣\s]|\s+", text)


def iter_stream_tokens(text: str) -> Iterable[str]:
    """공백을 유지하면서 사용자 친화 chunk 단위로 yield."""
    if not text:
        return

    buf = ""
    for token in tokenize_korean(text):
        if not buf:
            buf = token
            continue

        if token.isspace():
            buf += token
            continue

        yield buf
        buf = token

    if buf:
        yield buf
