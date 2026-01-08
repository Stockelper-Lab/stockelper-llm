import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from multi_agent.utils import Base, Industy

load_dotenv(override=True)


def upload_ksic_data():
    """KSIC 10차 개정 데이터를 다운로드하고 industy 테이블에 업로드"""
    
    # KSIC 데이터베이스 연결 (llm_users 대신 ksic 데이터베이스 사용)
    database_url = os.environ.get("DATABASE_URL_KSIC", "")
    engine = create_engine(database_url)
    
    # industy 테이블만 생성
    Industy.__table__.create(engine, checkfirst=True)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # KSIC 10차 개정 데이터 다운로드 및 로드
        url = 'https://github.com/FinanceData/KSIC/raw/master/KSIC_10.csv.gz'
        print(f"KSIC 데이터 다운로드 중: {url}")
        
        df_ksic = pd.read_csv(url, dtype='str')
        print(df_ksic.head())
        print(f"다운로드 완료: {len(df_ksic)}개의 행")
        
        # 기존 데이터 삭제
        deleted_count = session.query(Industy).delete()
        print(f"기존 데이터 {deleted_count}개 삭제 완료")
        
        # 새로운 데이터 삽입
        inserted_count = 0
        for _, row in df_ksic.iterrows():
            industy = Industy(
                industy_code=row['Industy_code'],
                industy_name=row['Industy_name']
            )
            session.add(industy)
            inserted_count += 1
            
            # 100개씩 커밋
            if inserted_count % 100 == 0:
                session.commit()
                print(f"{inserted_count}개 업로드 중...")
        
        # 나머지 커밋
        session.commit()
        print(f"✅ KSIC 데이터 업로드 완료: 총 {inserted_count}개")
        
        # 확인: 몇 가지 샘플 데이터 출력
        print("\n샘플 데이터 (상위 5개):")
        samples = session.query(Industy).limit(5).all()
        for sample in samples:
            print(f"  - {sample.industy_code}: {sample.industy_name}")
        
    except Exception as e:
        session.rollback()
        print(f"❌ 데이터 업로드 중 오류가 발생했습니다: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    upload_ksic_data()

