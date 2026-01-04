from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db_urls import to_psycopg_sqlalchemy_url
from multi_agent.utils import User


load_dotenv(override=True)


def upload_sample_user(
    *,
    user_id: int,
    kis_app_key: str,
    kis_app_secret: str,
    account_no: str,
    investor_type: str,
    kis_access_token: str | None,
    database_url: str | None,
    allow_ddl: bool,
) -> None:
    db_url = to_psycopg_sqlalchemy_url(database_url or os.getenv("DATABASE_URL"))
    if not db_url:
        raise RuntimeError("DATABASE_URL 이 설정되어 있지 않습니다.")

    engine = create_engine(db_url)
    if allow_ddl:
        # 로컬 개발/테스트에서만 사용하세요. 운영(stockelper_web)에서는 권장하지 않습니다.
        User.__table__.create(engine, checkfirst=True)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        existing_user = session.query(User).filter(User.id == user_id).first()
        if existing_user:
            existing_user.kis_app_key = kis_app_key
            existing_user.kis_app_secret = kis_app_secret
            existing_user.account_no = account_no
            existing_user.investor_type = investor_type
            existing_user.kis_access_token = kis_access_token
            print(f"기존 사용자(id={user_id})를 업데이트합니다.")
        else:
            user = User(
                id=user_id,
                kis_app_key=kis_app_key,
                kis_app_secret=kis_app_secret,
                kis_access_token=kis_access_token,
                account_no=account_no,
                investor_type=investor_type,
            )
            session.add(user)
            print(f"새 사용자(id={user_id})를 생성합니다.")

        session.commit()
        print("✅ 사용자 데이터 업로드 완료")

    except Exception as e:
        session.rollback()
        raise RuntimeError(f"데이터 업로드 중 오류: {e}") from e
    finally:
        session.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="로컬 개발용: stockelper_web.users에 샘플 사용자(KIS 자격증명)를 삽입/갱신합니다."
    )
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--kis-app-key", type=str, default=os.getenv("KIS_APP_KEY", ""))
    parser.add_argument(
        "--kis-app-secret", type=str, default=os.getenv("KIS_APP_SECRET", "")
    )
    parser.add_argument("--account-no", type=str, default=os.getenv("KIS_ACCOUNT_NO", ""))
    parser.add_argument("--investor-type", type=str, default="안정추구형")
    parser.add_argument(
        "--kis-access-token",
        type=str,
        default=os.getenv("KIS_ACCESS_TOKEN"),
        help="(선택) 이미 발급된 토큰을 넣을 때 사용",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="(선택) DATABASE_URL override (postgresql://... 가능)",
    )
    parser.add_argument(
        "--allow-ddl",
        action="store_true",
        help="(주의) users 테이블이 없으면 생성합니다. 로컬 개발에서만 사용 권장.",
    )
    args = parser.parse_args()

    if not args.kis_app_key or not args.kis_app_secret or not args.account_no:
        raise SystemExit(
            "kis-app-key/kis-app-secret/account-no 가 비어있습니다. "
            "옵션으로 넘기거나 환경변수(KIS_APP_KEY/KIS_APP_SECRET/KIS_ACCOUNT_NO)를 설정하세요."
        )

    upload_sample_user(
        user_id=args.user_id,
        kis_app_key=args.kis_app_key,
        kis_app_secret=args.kis_app_secret,
        account_no=args.account_no,
        investor_type=args.investor_type,
        kis_access_token=args.kis_access_token,
        database_url=args.database_url,
        allow_ddl=args.allow_ddl,
    )


if __name__ == "__main__":
    main()
