import json
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
import os
import requests
import json
from dotenv import load_dotenv
import aiohttp
import asyncio
from sqlalchemy import create_engine, Column, Integer, Text, TIMESTAMP, select
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

load_dotenv(override=True)

Base = declarative_base()

# 사용자 테이블 모델 정의
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    kis_app_key = Column(Text, nullable=False)
    kis_app_secret = Column(Text, nullable=False)
    kis_access_token = Column(Text, nullable=True)
    account_no = Column(Text, nullable=False) # ex) "50132452-01"
    investor_type = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

# 산업분류 테이블 모델 정의
class Industy(Base):
    __tablename__ = "industy"

    industy_code = Column(Text, primary_key=True)  # 5자리 패딩된 산업분류코드
    industy_name = Column(Text, nullable=False)  # 산업분류명

# 사용자 정보 조회 함수
async def get_user_kis_credentials(async_engine: object, user_id: int):
    async with AsyncSession(async_engine) as session:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            return {
                "id": user.id,
                "kis_app_key": user.kis_app_key,
                "kis_app_secret": user.kis_app_secret,
                "kis_access_token": user.kis_access_token,
                "account_no": user.account_no,
                "investor_type": user.investor_type
            }
        else:
            return None


async def update_user_kis_credentials(async_engine: object, user_id: int, access_token: str):
    async with AsyncSession(async_engine) as session:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            # 사용자 없음: 업데이트 불가
            return False
        user.kis_access_token = access_token
        await session.commit()
        return True


async def get_access_token(app_key, app_secret):
    """접근 토큰(access token) 발급"""
    url = "https://openapivts.koreainvestment.com:29443/oauth2/tokenP"
    headers = {
        "content-type": "application/json"
    }
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=body) as res:
            if res.status == 200:
                token_data = await res.json()
                return token_data["access_token"]
            else:
                text = await res.text()
                print(f"토큰 발급 실패: {res.status} - {text}")
                return None
    

async def check_account_balance(app_key, app_secret, access_token, account_no):
    """계좌 잔고 조회"""
    url = "https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": app_key,
        "appSecret": app_secret,
        "tr_id": "VTTC8434R",  # 모의투자 계좌 잔고 조회 / 실전투자 : TTTC8434R 
        "custtype": "P"  # 고객타입 - P: 개인 
    }
    params = {
        "CANO": account_no.split('-')[0],  # 계좌번호
        "ACNT_PRDT_CD": account_no.split('-')[1],
        "AFHR_FLPR_YN": "N",  # 시간외 단일가 포함 여부 
        "OFL_YN": "",  # 오프라인 여부 
        "INQR_DVSN": "01",  # 조회 구분 - 01:대출일별 / 02 : 종목별
        "UNPR_DVSN": "01",  # 단가 구분 - 01:현재가
        "FUND_STTL_ICLD_YN": "N",  # 펀드 결제 포함 여부 
        "FNCG_AMT_AUTO_RDPT_YN": "N",  # 금융금액 자동 상환 여부 
        "PRCS_DVSN": "01",  # 처리 구분 - 	00 : 전일매매포함 / 01 : 전일매매미포함
        "CTX_AREA_FK100": "",  # 연속조회검색조건100
        "CTX_AREA_NK100": ""  # 연속조회검색키100
    }
    
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url, headers=headers, params=params, timeout=30) as res:
                if res.status == 200:
                    res_data = await res.json()
                    if res_data.get('rt_cd') == '0':  # 응답 성공
                        output = res_data.get('output2', {})[0]
                        cash = output.get('dnca_tot_amt')  # 예수금
                        total_eval = output.get('tot_evlu_amt')  # 총 평가금액
                        return {'cash': cash, 'total_eval': total_eval}
                    else:
                        print(f"잔고 조회 실패: {res_data.get('msg1')}")
                        return None
                else:
                    text = await res.text()
                    print(f"잔고 조회 요청 실패: {res.status} - {text}")
                    try:
                        res_data = await res.json()
                        return res_data['msg1']
                    except:
                        return f"오류: {text}"
        except asyncio.TimeoutError:
            print("잔고 조회 요청 시간 초과 (timeout)")
            return None


def get_hashkey(app_key, app_secret, body_data, url_base):
    url = f"{url_base}/uapi/hashkey"
    headers = {
        'content-type': 'application/json',
        'appkey': app_key,
        'appsecret': app_secret
    }
    res = requests.post(url, headers=headers, data=json.dumps(body_data))
    if res.status_code == 200:
        return res.json()['HASH']
    else:
        print(f"Hashkey 요청 실패: {res.status_code} - {res.text}")
        return None
        

def place_order(stock_code:str, order_side:str, order_type:str, order_price:float, order_quantity:int, account_no:str = None, kis_app_key:str = None, kis_app_secret:str = None, kis_access_token:str = None, **kwargs) -> dict:
    """
    국내주식 모의투자 매수 또는 매도 주문을 실행.

    Parameters:
    - token (str): API 접근 토큰
    - stock_code (str): 주문할 주식의 종목 코드 (예: "005930" - 삼성전자)
    - order_qty (int): 주문 수량 (예: 1주)
    - order_price (float): 주문 단가 (예: 60000원)
    - ord_type (str, 기본값: "buy"): 주문 유형 ("buy" 또는 "sell")

    Returns:
    - dict: 주문 결과를 포함하는 JSON 응답 데이터
    """

    url = "https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/order-cash"

    # 주문 유형에 따라 SLL_BUY_DVSN_CD와 tr_id 설정
    if order_side == "buy":
        tr_id = "VTTC0802U"  # 매수 tr_id
    elif order_side == "sell":
        tr_id = "VTTC0011U"  # 매도 tr_id
    else:
        print("주문 유형이 잘못되었습니다. 'buy' 또는 'sell'을 선택하세요.")
        return "주문 요청 실패"
    
    if order_type == "market":
        order_dvsn = "01"
    elif order_type == "limit":
        order_dvsn = "00"
    else:
        print("주문 유형이 잘못되었습니다. 'market' 또는 'limit'을 선택하세요.")
        return "주문 요청 실패"

    body = {
        "CANO": account_no.split('-')[0],
        "ACNT_PRDT_CD": account_no.split('-')[1],
        "PDNO": stock_code,
        "ORD_DVSN": order_dvsn,  # 00: 지정가 / 01: 시장가
        "ORD_QTY": str(order_quantity),  # 주문수량
        # 시장가 주문은 0, 지정가는 전달된 가격을 문자열로
        "ORD_UNPR": "0" if order_dvsn == "01" else str(order_price),
    }

    # hashkey 생성 (주문 엔드포인트 필수)
    try:
        hashkey = get_hashkey(kis_app_key, kis_app_secret, body, "https://openapivts.koreainvestment.com:29443")
    except Exception as e:
        return f"hashkey 생성 실패: {str(e)}"

    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {kis_access_token}",
        "appkey": kis_app_key,
        "appsecret": kis_app_secret,
        "tr_id": tr_id,  # 모의투자 매수 - VTTC0802U / 모의투자 매도 - VTTC0011U
        "custtype": "P",
        "hashkey": hashkey,
    }
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
        res.raise_for_status()
        data = res.json()
        # 표준 메시지 우선 반환하되, 없으면 전체 응답 반환
        return data.get('msg1', data)
    except Exception as e:
        try:
            # 가능한 경우 서버 메시지 노출
            data = res.json()
            return data.get('msg1', str(e))
        except Exception:
            return f"주문 요청 실패: {str(e)}"
    

def custom_add_messages(existing: list, update: list):
    for message in update:
        if not isinstance(message, BaseMessage):
            if message["role"] == "user":
                existing.append(HumanMessage(content=message["content"]))
            elif message["role"] == "assistant":
                existing.append(AIMessage(content=message["content"]))
            else:
                raise ValueError(f"Invalid message type: {type(message)}")
        else:
            existing.append(message)
    return existing[-10:]
