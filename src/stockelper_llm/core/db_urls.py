from __future__ import annotations

from typing import Optional


def to_async_sqlalchemy_url(url: Optional[str]) -> Optional[str]:
    """SQLAlchemy async(engine=asyncpg) URL로 정규화합니다."""
    if not url:
        return None

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    if url.startswith("postgresql+asyncpg://"):
        return url

    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return url


def to_postgresql_conninfo(url: Optional[str]) -> Optional[str]:
    """psycopg/psycopg_pool에서 인식 가능한 conninfo로 정규화합니다."""
    if not url:
        return None

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)

    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)

    return url

