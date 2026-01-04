from __future__ import annotations

from db_urls import to_async_sqlalchemy_url, to_postgresql_conninfo, to_psycopg_sqlalchemy_url


def test_to_async_sqlalchemy_url_from_postgresql() -> None:
    assert (
        to_async_sqlalchemy_url("postgresql://u:p@h:5432/db")
        == "postgresql+asyncpg://u:p@h:5432/db"
    )


def test_to_async_sqlalchemy_url_from_postgres_alias() -> None:
    assert (
        to_async_sqlalchemy_url("postgres://u:p@h:5432/db")
        == "postgresql+asyncpg://u:p@h:5432/db"
    )


def test_to_async_sqlalchemy_url_from_psycopg_dialect() -> None:
    assert (
        to_async_sqlalchemy_url("postgresql+psycopg://u:p@h:5432/db")
        == "postgresql+asyncpg://u:p@h:5432/db"
    )


def test_to_psycopg_sqlalchemy_url_from_postgresql() -> None:
    assert (
        to_psycopg_sqlalchemy_url("postgresql://u:p@h:5432/db")
        == "postgresql+psycopg://u:p@h:5432/db"
    )


def test_to_psycopg_sqlalchemy_url_from_asyncpg_dialect() -> None:
    assert (
        to_psycopg_sqlalchemy_url("postgresql+asyncpg://u:p@h:5432/db")
        == "postgresql+psycopg://u:p@h:5432/db"
    )


def test_to_postgresql_conninfo_strips_sqlalchemy_dialect() -> None:
    assert (
        to_postgresql_conninfo("postgresql+psycopg://u:p@h:5432/db")
        == "postgresql://u:p@h:5432/db"
    )
    assert (
        to_postgresql_conninfo("postgresql+asyncpg://u:p@h:5432/db")
        == "postgresql://u:p@h:5432/db"
    )


def test_to_postgresql_conninfo_normalizes_postgres_scheme() -> None:
    assert (
        to_postgresql_conninfo("postgres://u:p@h:5432/db")
        == "postgresql://u:p@h:5432/db"
    )


