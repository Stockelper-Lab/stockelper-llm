from __future__ import annotations

from json_safety import to_jsonable


class _FakeNeo4jDateTime:
    __module__ = "neo4j.time"

    def __str__(self) -> str:
        return "2026-01-01T00:00:00+00:00"


def test_to_jsonable_converts_neo4j_datetime_like_object() -> None:
    # class name must be "DateTime" to match converter
    Fake = type("DateTime", (_FakeNeo4jDateTime,), {})
    obj = {"t": Fake()}
    out = to_jsonable(obj)
    assert out == {"t": "2026-01-01T00:00:00+00:00"}


def test_to_jsonable_recursive_lists_dicts() -> None:
    Fake = type("DateTime", (_FakeNeo4jDateTime,), {})
    obj = {"a": [1, {"b": Fake()}]}
    out = to_jsonable(obj)
    assert out == {"a": [1, {"b": "2026-01-01T00:00:00+00:00"}]}


