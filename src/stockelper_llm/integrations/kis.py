from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import aiohttp
import requests
from sqlalchemy import TIMESTAMP, Column, Integer, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


KIS_BASE_URL = os.getenv(
    "KIS_BASE_URL", "https://openapivts.koreainvestment.com:29443"
).rstrip("/")

KIS_TR_ID_BALANCE = os.getenv("KIS_TR_ID_BALANCE", "VTTC8434R")
KIS_TR_ID_ORDER_BUY = os.getenv("KIS_TR_ID_ORDER_BUY", "VTTC0802U")
KIS_TR_ID_ORDER_SELL = os.getenv("KIS_TR_ID_ORDER_SELL", "VTTC0011U")
KIS_TR_ID_PRICE = os.getenv("KIS_TR_ID_PRICE", "FHKST01010100")

_KIS_TOKEN_EXPIRED_SUBSTRINGS = (
    "기간이 만료된 token",
    "유효하지 않은 token",
)


def is_kis_token_expired_message(message: str | None) -> bool:
    if not message:
        return False
    return any(s in message for s in _KIS_TOKEN_EXPIRED_SUBSTRINGS)


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": os.getenv("STOCKELPER_WEB_SCHEMA", "public")}

    id = Column(Integer, primary_key=True)
    kis_app_key = Column(Text, nullable=False)
    kis_app_secret = Column(Text, nullable=False)
    kis_access_token = Column(Text, nullable=True)
    account_no = Column(Text, nullable=False)  # ex) "50132452-01"
    investor_type = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


async def get_user_kis_credentials(async_engine: Any, user_id: int):
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
                "investor_type": user.investor_type,
            }
        return None


async def update_user_kis_credentials(
    async_engine: Any, user_id: int, access_token: str
):
    async with AsyncSession(async_engine) as session:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            return False
        user.kis_access_token = access_token
        await session.commit()
        return True


async def get_access_token(app_key: str, app_secret: str) -> str | None:
    url = f"{KIS_BASE_URL}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=body) as res:
            if res.status == 200:
                token_data = await res.json()
                return token_data.get("access_token")
            return None


async def get_user_kis_context(
    async_engine: Any, user_id: int, *, require: bool = True
) -> dict | None:
    """users 테이블에서 KIS 자격증명/계좌/토큰을 로드하고 토큰이 없으면 발급 후 DB에 저장."""
    user_info = await get_user_kis_credentials(async_engine, user_id)
    if not user_info:
        if require:
            raise ValueError(f"user_id={user_id} 사용자를 DB에서 찾지 못했습니다.")
        return None

    if not user_info.get("account_no"):
        if require:
            raise ValueError("users.account_no가 비어있습니다.")
        return None

    access_token = user_info.get("kis_access_token")
    if not access_token:
        access_token = await get_access_token(
            user_info["kis_app_key"], user_info["kis_app_secret"]
        )
        if not access_token:
            if require:
                raise ValueError(
                    "KIS access token 발급 실패 (app_key/app_secret 확인 필요)"
                )
            return None

        await update_user_kis_credentials(async_engine, user_id, access_token)
        user_info["kis_access_token"] = access_token

    return user_info


async def refresh_user_kis_access_token(
    async_engine: Any, user_id: int, user_info: dict | None = None
) -> str:
    if user_info is None:
        user_info = await get_user_kis_credentials(async_engine, user_id)
    if not user_info:
        raise ValueError(f"user_id={user_id} 사용자를 DB에서 찾지 못했습니다.")

    access_token = await get_access_token(
        user_info["kis_app_key"], user_info["kis_app_secret"]
    )
    if not access_token:
        raise ValueError("KIS access token 재발급 실패")

    await update_user_kis_credentials(async_engine, user_id, access_token)
    return access_token


async def check_account_balance(
    app_key: str, app_secret: str, access_token: str, account_no: str
):
    url = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": app_key,
        "appSecret": app_secret,
        "tr_id": KIS_TR_ID_BALANCE,
        "custtype": "P",
    }
    params = {
        "CANO": account_no.split("-")[0],
        "ACNT_PRDT_CD": account_no.split("-")[1],
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "01",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(
                url, headers=headers, params=params, timeout=30
            ) as res:
                if res.status == 200:
                    res_data = await res.json()
                    if res_data.get("rt_cd") == "0":
                        output = (res_data.get("output2") or [{}])[0]
                        cash = output.get("dnca_tot_amt")
                        total_eval = output.get("tot_evlu_amt")
                        return {"cash": cash, "total_eval": total_eval}
                    msg1 = res_data.get("msg1") if isinstance(res_data, dict) else None
                    return msg1 or None
                text = await res.text()
                try:
                    res_data = await res.json()
                    return res_data.get("msg1")
                except Exception:
                    return f"오류: {text}"
        except asyncio.TimeoutError:
            return None


async def get_current_price(async_engine: Any, user_id: int, stock_code: str) -> dict:
    """KIS '주식현재가 시세' 조회.

    - users 테이블의 kis_app_key/kis_app_secret/kis_access_token을 사용합니다.
    - 토큰 만료 메시지 감지 시 1회 재발급 후 재시도합니다.
    """
    stock_code = (stock_code or "").strip()
    if not stock_code or stock_code == "None":
        return {
            "error": "6자리 종목코드(stock_code)가 필요합니다.",
            "stock_code": stock_code,
        }

    user_info = await get_user_kis_context(async_engine, user_id, require=False)
    if not user_info:
        # 서비스 계정 기반(환경변수) fallback: DB에 user가 없는 경우에도 조회 가능하도록
        app_key = (os.getenv("KIS_APP_KEY") or os.getenv("KIS_APPKEY") or "").strip()
        app_secret = (
            os.getenv("KIS_APP_SECRET") or os.getenv("KIS_APPSECRET") or ""
        ).strip()
        if not app_key or not app_secret:
            return {
                "error": "KIS 자격증명/계좌정보가 없어 현재가를 조회할 수 없습니다. (users 테이블 또는 KIS_APP_KEY/KIS_APP_SECRET 필요)",
                "user_id": user_id,
                "stock_code": stock_code,
            }
        access_token = await get_access_token(app_key, app_secret)
        if not access_token:
            return {
                "error": "KIS access token 발급 실패 (KIS_APP_KEY/KIS_APP_SECRET 확인 필요)",
                "user_id": user_id,
                "stock_code": stock_code,
            }
        user_info = {
            "kis_app_key": app_key,
            "kis_app_secret": app_secret,
            "kis_access_token": access_token,
        }

    url = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {user_info['kis_access_token']}",
        "appkey": user_info["kis_app_key"],
        "appsecret": user_info["kis_app_secret"],
        "tr_id": KIS_TR_ID_PRICE,
        "custtype": "P",
    }
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": stock_code}

    async def _request(session: aiohttp.ClientSession) -> tuple[int, dict]:
        async with session.get(url, headers=headers, params=params) as res:
            status_code = res.status
            try:
                body = await res.json()
            except Exception:
                text = await res.text()
                body = {"msg1": text}
            return status_code, body if isinstance(body, dict) else {"msg1": str(body)}

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        status_code, res_body = await _request(session)

        msg = res_body.get("msg1", "")
        # 일부 응답은 HTTP 200이어도 msg1에 토큰 만료가 포함될 수 있어 메시지 기반으로 감지합니다.
        if is_kis_token_expired_message(msg):
            try:
                # DB 기반 user이면 refresh 로직을 사용 (DB 업데이트 포함)
                if user_info.get("id"):
                    user_info["kis_access_token"] = await refresh_user_kis_access_token(
                        async_engine, user_id, user_info
                    )
                else:
                    user_info["kis_access_token"] = await get_access_token(
                        user_info["kis_app_key"], user_info["kis_app_secret"]
                    )
                headers["authorization"] = f"Bearer {user_info['kis_access_token']}"
            except Exception as e:
                return {
                    "error": f"KIS 토큰 재발급 실패: {type(e).__name__}: {e}",
                    "user_id": user_id,
                    "stock_code": stock_code,
                }
            status_code, res_body = await _request(session)

        if status_code != 200:
            return {
                "error": f"KIS 현재가 조회 실패(HTTP {status_code}): {res_body.get('msg1','')}",
                "user_id": user_id,
                "stock_code": stock_code,
            }
        if res_body.get("rt_cd") != "0":
            return {
                "error": f"KIS 현재가 조회 실패: {res_body.get('msg1','')}",
                "user_id": user_id,
                "stock_code": stock_code,
            }

        output = res_body.get("output") or {}
        if not isinstance(output, dict) or not output:
            return {
                "error": "KIS 현재가 응답에 output이 없습니다.",
                "user_id": user_id,
                "stock_code": stock_code,
            }

        return {
            "대표 시장 한글 명": output.get("rprs_mrkt_kor_name", ""),
            "업종": output.get("bstp_kor_isnm", ""),
            "종목 코드": stock_code,
            "주식 현재가": output.get("stck_prpr", ""),
            "주식 전일 종가": output.get("stck_sdpr", ""),
            "상한가": output.get("stck_mxpr", ""),
            "하한가": output.get("stck_llam", ""),
            "최고가": output.get("stck_hgpr", ""),
            "최저가": output.get("stck_lwpr", ""),
            "거래량": output.get("acml_vol", ""),
            "누적 거래 대금": output.get("acml_tr_pbmn", ""),
            "PER (주가수익비율)": output.get("per", ""),
            "PBR (주가순자산비율)": output.get("pbr", ""),
            "EPS (주당순이익)": output.get("eps", ""),
            "BPS (주당순자산)": output.get("bps", ""),
            "배당수익률": output.get("vol_tnrt", ""),
            "전일 대비": output.get("prdy_vrss", ""),
            "전일 대비 거래량 비율": output.get("prdy_vrss_vol_rate", ""),
            "250일 최고가": output.get("d250_hgpr", ""),
            "250일 최저가": output.get("d250_lwpr", ""),
            "신용 가능 여부": output.get("crdt_able_yn", ""),
            "ELW 발행 여부": output.get("elw_pblc_yn", ""),
            "외국인 보유율": output.get("hts_frgn_ehrt", ""),
            "단기과열 여부": output.get("ovtm_vi_cls_code", ""),
            "저유동성 종목 여부": output.get("sltr_yn", ""),
            "시장 경고 코드": output.get("mrkt_warn_cls_code", ""),
        }


def get_hashkey(
    app_key: str, app_secret: str, body_data: dict, url_base: str | None = None
):
    url_base = (url_base or KIS_BASE_URL).rstrip("/")
    url = f"{url_base}/uapi/hashkey"
    headers = {
        "content-type": "application/json",
        "appkey": app_key,
        "appsecret": app_secret,
    }
    res = requests.post(url, headers=headers, data=json.dumps(body_data))
    if res.status_code == 200:
        return res.json().get("HASH")
    return None


def place_order(
    *,
    stock_code: str,
    order_side: str,
    order_type: str,
    order_price: float | None,
    order_quantity: int,
    account_no: str,
    kis_app_key: str,
    kis_app_secret: str,
    kis_access_token: str,
    **kwargs: Any,
) -> str | dict:
    url = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"

    if order_side == "buy":
        tr_id = KIS_TR_ID_ORDER_BUY
    elif order_side == "sell":
        tr_id = KIS_TR_ID_ORDER_SELL
    else:
        return "주문 유형이 잘못되었습니다. 'buy' 또는 'sell'을 선택하세요."

    if order_type == "market":
        order_dvsn = "01"
    elif order_type == "limit":
        order_dvsn = "00"
    else:
        return "주문 유형이 잘못되었습니다. 'market' 또는 'limit'을 선택하세요."

    body = {
        "CANO": account_no.split("-")[0],
        "ACNT_PRDT_CD": account_no.split("-")[1],
        "PDNO": stock_code,
        "ORD_DVSN": order_dvsn,
        "ORD_QTY": str(order_quantity),
        "ORD_UNPR": "0" if order_dvsn == "01" else str(order_price or 0),
    }

    try:
        hashkey = get_hashkey(kis_app_key, kis_app_secret, body, KIS_BASE_URL)
    except Exception as e:
        return f"hashkey 생성 실패: {str(e)}"

    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {kis_access_token}",
        "appkey": kis_app_key,
        "appsecret": kis_app_secret,
        "tr_id": tr_id,
        "custtype": "P",
        "hashkey": hashkey,
    }
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
        res.raise_for_status()
        data = res.json()
        return data.get("msg1", data)
    except Exception as e:
        try:
            data = res.json()
            return data.get("msg1", str(e))
        except Exception:
            return f"주문 요청 실패: {str(e)}"
