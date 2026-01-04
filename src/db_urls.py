from __future__ import annotations

from typing import Optional


def to_async_sqlalchemy_url(url: Optional[str]) -> Optional[str]:
    """SQLAlchemy async(engine=asyncpg) URL로 정규화합니다.

    지원 입력 예:
    - postgresql://user:pass@host:5432/db
    - postgres://user:pass@host:5432/db
    - postgresql+psycopg://user:pass@host:5432/db
    - postgresql+asyncpg://user:pass@host:5432/db
    """
    if not url:
        return None

    # Heroku/일부 툴이 쓰는 postgres:// 스킴을 표준으로 정규화
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    if url.startswith("postgresql+asyncpg://"):
        return url

    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # 알 수 없는 스킴은 그대로 반환(상위에서 검증/에러 처리)
    return url


def to_psycopg_sqlalchemy_url(url: Optional[str]) -> Optional[str]:
    """SQLAlchemy sync(engine=psycopg3) URL로 정규화합니다."""
    if not url:
        return None

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    if url.startswith("postgresql+psycopg://"):
        return url

    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)

    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)

    return url


def to_postgresql_conninfo(url: Optional[str]) -> Optional[str]:
    """psycopg/psycopg_pool(=libpq)에서 인식 가능한 conninfo로 정규화합니다.

    - SQLAlchemy dialect 접두사(+asyncpg/+psycopg)를 제거합니다.
    """
    if not url:
        return None

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)

    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)

    return url


