from __future__ import annotations

import base64
import datetime as _dt
from decimal import Decimal
from typing import Any


def to_jsonable(obj: Any) -> Any:
    """재귀적으로 JSON/MsgPack 직렬화 가능한 타입으로 변환합니다.

    목적:
    - LangGraph(Postgres checkpointer)가 상태를 저장할 때, neo4j temporal 타입(neo4j.time.DateTime 등)
      또는 기타 비직렬화 타입 때문에 실패하는 것을 방지합니다.

    NOTE:
    - LangChain/LangGraph 메시지 객체(BaseMessage 등)는 JsonPlusSerializer가 직접 처리할 수 있으므로,
      이 함수는 주로 "서브그래프/툴 결과" 같은 임의 dict 구조에만 적용하세요.
    """
    if obj is None:
        return None

    if isinstance(obj, (str, int, float, bool)):
        return obj

    # datetime/date/time → ISO 문자열
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)

    # Decimal → 문자열(정밀도 보존)
    if isinstance(obj, Decimal):
        return str(obj)

    # numpy scalar 지원 (numpy가 없을 수 있어 안전하게 처리)
    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return to_jsonable(item())
        except Exception:
            pass

    # bytes → base64 문자열
    if isinstance(obj, (bytes, bytearray, memoryview)):
        raw = bytes(obj)
        return base64.b64encode(raw).decode("ascii")

    # neo4j temporal 타입(DateTime/Date/Time/Duration/LocalDateTime/LocalTime 등) → 문자열
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

    # dict / list / tuple / set 재귀 처리
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]

    # 기타 타입은 안전하게 문자열로 강등
    return str(obj)


