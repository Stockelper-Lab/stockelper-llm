from __future__ import annotations

from typing import Any, Iterable


def _content_block_to_text(block: Any) -> str:
    """Best-effort conversion of LangChain v1 content blocks to plain text.

    LangChain v1 / OpenAI Responses API may store message content as list[ContentBlock].
    We only extract textual pieces and ignore non-text blocks (tool calls, images, etc.).
    """
    if block is None:
        return ""

    if isinstance(block, str):
        return block

    if isinstance(block, dict):
        # Common block shapes:
        # - {"type": "text", "text": "..."}
        # - {"type": "...", "content": ...}
        text = block.get("text")
        if isinstance(text, str):
            return text

        inner = block.get("content")
        if inner is not None:
            return _content_to_text(inner)

        return ""

    # Some SDKs may yield objects; try attribute access conservatively.
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
    """Extract user-visible text from a LangChain message object (v0.x or v1.x).

    - v0.x often stores plain string in `message.content`
    - v1.x may store content blocks in `message.content`
    - v1.x also introduces `.text` property (with `.text()` kept for compatibility)
    """
    if message is None:
        return ""

    # v1: `.text` is a property.
    try:
        text_prop = getattr(message, "text", None)
        if isinstance(text_prop, str):
            return text_prop
        if callable(text_prop):
            # v0.x: `.text()` method (deprecated in v1)
            text_val = text_prop()
            if isinstance(text_val, str):
                return text_val
    except Exception:
        pass

    content = getattr(message, "content", None)
    return _content_to_text(content)


def tokenize_korean(text: str) -> list[str]:
    """Tokenize a string into user-friendly chunks for SSE streaming.

    Keeps words and punctuation separated, preserves whitespace tokens only if meaningful.
    """
    import re

    if not text:
        return []
    return re.findall(r"[\w가-힣]+|[^\w가-힣\s]|\s+", text)


def iter_stream_tokens(text: str) -> Iterable[str]:
    for token in tokenize_korean(text):
        if token.strip():
            yield token


