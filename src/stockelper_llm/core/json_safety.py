from __future__ import annotations

import base64
import datetime as _dt
from decimal import Decimal
from typing import Any


def to_jsonable(obj: Any) -> Any:
    """재귀적으로 JSON 직렬화 가능한 타입으로 변환합니다."""
    if obj is None:
        return None

    if isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)

    if isinstance(obj, Decimal):
        return str(obj)

    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return to_jsonable(item())
        except Exception:
            pass

    if isinstance(obj, (bytes, bytearray, memoryview)):
        raw = bytes(obj)
        return base64.b64encode(raw).decode("ascii")

    t = type(obj)
    if getattr(t, "__module__", "") == "neo4j.time" and getattr(t, "__name__", "") in {
        "DateTime",
        "Date",
        "Time",
        "Duration",
        "LocalDateTime",
        "LocalTime",
    }:
        return str(obj)

    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]

    return str(obj)
