from __future__ import annotations

import argparse
import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from db_urls import to_async_sqlalchemy_url
from multi_agent.utils import (
    get_access_token,
    get_user_kis_credentials,
    update_user_kis_credentials,
)


load_dotenv(override=True)


async def _run(user_id: int, force: bool, database_url: str | None) -> str:
    async_db_url = to_async_sqlalchemy_url(
        database_url or os.getenv("ASYNC_DATABASE_URL") or os.getenv("DATABASE_URL")
    )
    if not async_db_url:
        raise RuntimeError("DATABASE_URL(또는 ASYNC_DATABASE_URL)가 설정되어 있지 않습니다.")

    engine = create_async_engine(async_db_url, echo=False)
    try:
        user = await get_user_kis_credentials(engine, user_id)
        if not user:
            raise RuntimeError(f"user_id={user_id} 사용자를 찾지 못했습니다.")

        if user.get("kis_access_token") and not force:
            return str(user["kis_access_token"])

        token = await get_access_token(user["kis_app_key"], user["kis_app_secret"])
        if not token:
            raise RuntimeError("KIS access token 발급 실패")

        await update_user_kis_credentials(engine, user_id, token)
        return token
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="stockelper_web.users에서 user_id의 KIS 토큰을 발급/저장합니다."
    )
    parser.add_argument("--user-id", type=int, default=1, help="users.id")
    parser.add_argument(
        "--force",
        action="store_true",
        help="DB에 토큰이 있어도 강제로 재발급 후 업데이트",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="(선택) DATABASE_URL override (postgresql://... 가능)",
    )
    args = parser.parse_args()

    token = asyncio.run(_run(args.user_id, args.force, args.database_url))
    print(token)


if __name__ == "__main__":
    main()
