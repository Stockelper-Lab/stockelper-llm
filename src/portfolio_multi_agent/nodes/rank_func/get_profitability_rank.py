"""
한국투자증권 재무비율 순위 API - 수익성 분석 순위
"""

from typing import List, Dict
import os
import aiohttp
import asyncio


async def get_profitability_rank(
    top_n: int = 30,
    app_key: str = "",
    app_secret: str = "",
    access_token: str = "",
) -> List[Dict[str, str]]:
    """
    수익성 분석 순위 조회 및 종목 정보 리스트 반환

    Args:
        top_n: 상위 몇 개의 종목을 가져올지 (기본값: 30)
        app_key: 한국투자증권 API App Key
        app_secret: 한국투자증권 API App Secret
        access_token: 한국투자증권 API Access Token

    Returns:
        수익성 분석 순위 상위 N개 종목 정보 리스트 [{"code": "종목코드", "name": "종목명"}, ...]
    """
    _app_key = app_key
    _app_secret = app_secret
    _access_token = access_token

    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/ranking/finance-ratio"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {_access_token}",
        "appkey": _app_key,
        "appsecret": _app_secret,
        "tr_id": "FHPST01750000",
        "custtype": "P",
    }
    params = {
        "fid_trgt_cls_code": "0",
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20175",
        "fid_input_iscd": "0000",
        "fid_div_cls_code": "0",
        "fid_input_price_1": "",
        "fid_input_price_2": "",
        "fid_vol_cnt": "",
        "fid_input_option_1": "2025",
        "fid_input_option_2": "3",
        "fid_rank_sort_cls_code": "7",  # 수익성 분석
        "fid_blng_cls_code": "0",
        "fid_trgt_exls_cls_code": "0",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            api_response = await response.json()

    # 응답 코드 확인
    if api_response.get("rt_cd") != "0":
        raise ValueError(f"API 오류: {api_response.get('msg1', '알 수 없는 오류')}")

    # Output: 재무비율 순위 리스트
    finance_ratio_rank_list = api_response.get("output", [])

    # 상위 N개의 종목 정보 추출 (중복 제거, 순서 유지)
    seen = set()
    stock_list = []
    for stock in finance_ratio_rank_list[:top_n]:
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

    # 수익성 분석 순위 상위 10개 종목 조회
    stock_codes = asyncio.run(
        get_profitability_rank(
            top_n=10, app_key=app_key, app_secret=app_secret, access_token=access_token
        )
    )

    print("=" * 80)
    print(f"수익성 분석 순위 Top {len(stock_codes)} 종목 코드")
    print("=" * 80)
    print(stock_codes)
