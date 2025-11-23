"""
한국투자증권 거래량 순위 API - 거래량 순위
"""

from typing import List, Dict
import os
import aiohttp
import asyncio


async def get_volume_rank(
    top_n: int = 30,
    app_key: str = "",
    app_secret: str = "",
    access_token: str = "",
) -> List[Dict[str, str]]:
    """
    거래량 순위 조회 및 종목 정보 리스트 반환

    Args:
        top_n: 상위 몇 개의 종목을 가져올지 (기본값: 30)
        app_key: 한국투자증권 API App Key
        app_secret: 한국투자증권 API App Secret
        access_token: 한국투자증권 API Access Token

    Returns:
        거래량 순위 상위 N개 종목 정보 리스트 [{"code": "종목코드", "name": "종목명"}, ...]
    """
    _app_key = app_key
    _app_secret = app_secret
    _access_token = access_token

    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/volume-rank"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {_access_token}",
        "appkey": _app_key,
        "appsecret": _app_secret,
        "tr_id": "FHPST01710000",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": "20171",
        "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "0",
        "FID_BLNG_CLS_CODE": "1",
        "FID_TRGT_CLS_CODE": "111111111",
        "FID_TRGT_EXLS_CLS_CODE": "0000001111",
        "FID_INPUT_PRICE_1": "",
        "FID_INPUT_PRICE_2": "",
        "FID_VOL_CNT": "",
        "FID_INPUT_DATE_1": "",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            api_response = await response.json()

    # 응답 코드 확인
    if api_response.get("rt_cd") != "0":
        raise ValueError(f"API 오류: {api_response.get('msg1', '알 수 없는 오류')}")

    # Output: 거래량 순위 리스트
    volume_rank_list = api_response.get("output", [])

    # 상위 N개의 종목 정보 추출 (중복 제거, 순서 유지)
    seen = set()
    stock_list = []
    for stock in volume_rank_list[:top_n]:
        code = stock.get("mksc_shrn_iscd", "")
        name = stock.get("hts_kor_isnm", "")
        if code and code not in seen:
            seen.add(code)
            stock_list.append({"code": code, "name": name})

    return stock_list


# ===== 사용 예시 =====
if __name__ == "__main__":
    # 환경변수에서 인증 정보 로드
    app_key = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    access_token = os.getenv("KIS_ACCESS_TOKEN", "")

    # 거래량 순위 상위 10개 종목 조회
    stock_codes = asyncio.run(
        get_volume_rank(
            top_n=10, app_key=app_key, app_secret=app_secret, access_token=access_token
        )
    )

    print("=" * 80)
    print(f"거래량 순위 Top {len(stock_codes)} 종목 코드")
    print("=" * 80)
    print(stock_codes)
