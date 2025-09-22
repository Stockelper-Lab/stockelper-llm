import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from multi_agent.utils import Base, User

load_dotenv(override=True)


def upload_sample_user():
    engine = create_engine(os.environ["DATABASE_URL"])
    # 테이블 스키마 보장
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # id=1인 기존 사용자 확인 및 삭제
        existing_user = session.query(User).filter(User.id == 1).first()
        if existing_user:
            session.delete(existing_user)
            session.commit()
            print("기존 사용자 데이터(id=1)가 삭제되었습니다.")
        
        # 새로운 샘플 데이터 생성
        user = User(
            id=1,
            kis_app_key=os.getenv("KIS_APP_KEY"),
            kis_app_secret=os.getenv("KIS_APP_SECRET"),
            kis_access_token=os.getenv("KIS_ACCESS_TOKEN"),
            account_no=os.getenv("KIS_ACCOUNT_NO"),
            investor_type="beginner"
        )
        session.add(user)
        session.commit()
        print("새로운 샘플 사용자 데이터가 업로드되었습니다.")
        
    except Exception as e:
        session.rollback()
        print(f"데이터 업로드 중 오류가 발생했습니다: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    upload_sample_user()
