from typing import Dict, List, Optional, Tuple, Type
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
import time
import pandas as pd
import numpy as np
from ...utils import get_user_kis_credentials, get_access_token, Industy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import aiohttp
import logging
import os
import asyncio
import json
import OpenDartReader

logger = logging.getLogger(__name__)
async_engine = create_async_engine(os.environ["ASYNC_DATABASE_URL"], echo=False)
async_engine_ksic = create_async_engine(os.environ["ASYNC_DATABASE_URL_KSIC"], echo=False)


MARKET_MAP = {
    "Y": "유가",
    "K": "코스닥",
    "N": "코넥스",
    "E": "기타"
}


class PortfolioAnalysisInput(BaseModel):
    user_investor_type: str = Field(
        description="The investor type of the user. It indicates the user's investment style or risk profile."
    )

class PortfolioAnalysisTool(BaseTool):
    name: str = "portfolio_analysis"
    description: str = "Analyzes and recommends portfolio based on user's investor type. Evaluates stocks using market value, stability, profitability, and growth metrics, then suggests optimal portfolio composition tailored to the user's investment style."
    url_base: str = "https://openapi.koreainvestment.com:9443"
    args_schema: Type[BaseModel] = PortfolioAnalysisInput

    return_direct: bool = True

    def _ensure_rate_limiter(self):
        if not hasattr(self, "_rate_sem"):
            self._rate_sem = asyncio.Semaphore(2)

    async def _throttle(self):
        self._ensure_rate_limiter()
        await self._rate_sem.acquire()
        asyncio.get_running_loop().call_later(1.0, self._rate_sem.release)
        # pass

    def _make_headers(self, tr_id: str, user_info: dict) -> dict:
        """공통 헤더 생성 함수"""
        logger.debug("Creating headers for transaction ID: %s", tr_id)

        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {user_info['kis_access_token']}",
            "appkey": user_info['kis_app_key'],
            "appsecret": user_info['kis_app_secret'],
            "tr_id": tr_id,
            "tr_cont": "N"
        }
        logger.debug("Headers created: %s", headers)
        return headers


    async def get_top_market_value(self, fid_rank_sort_cls_code, user_info):
        """시가총액 상위 종목을 조회합니다.
        - fid_rank_sort_cls_code: 순위 정렬 구분 코드 (23:PER, 24:PBR, 25:PCR, 26:PSR, 27: EPS, 28:EVA, 29: EBITDA, 30: EV/EBITDA, 31:EBITDA/금융비율)
        """
        logger.info("Fetching top market value stocks with sort code: %s", fid_rank_sort_cls_code)
        path = "/uapi/domestic-stock/v1/ranking/market-value"
        url = self.url_base + path
        headers = self._make_headers("FHPST01790000", user_info)

        params = {
            "fid_trgt_cls_code": "0",
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20179",
            "fid_input_iscd": "0000",
            "fid_div_cls_code": "0",
            "fid_input_price_1": "",
            "fid_input_price_2": "",
            "fid_vol_cnt": "",
            "fid_input_option_1": "2024",
            "fid_input_option_2": "3",
            "fid_rank_sort_cls_code": fid_rank_sort_cls_code,
            "fid_blng_cls_code": "0",
            "fid_trgt_exls_cls_code": "0",
        }

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await self._throttle()
            async with session.get(url, headers=headers, params=params) as response:
                status_code = response.status
                text = await response.text()

                update_access_token_flag = False
                if status_code in (401, 403, 500) and ("기간이 만료된 token" in text or "유효하지 않은 token" in text):
                    user_info['kis_access_token'] = await get_access_token(user_info['kis_app_key'], user_info['kis_app_secret'])
                    update_access_token_flag = True

                    headers["authorization"] = (
                        f"Bearer {user_info['kis_access_token']}"
                    )
                    await self._throttle()
                    async with session.get(
                        url, headers=headers, params=params
                    ) as res_refresh:
                        status_code = res_refresh.status
                        text = await res_refresh.text()

                data = json.loads(text)

                logger.debug("Top market value stocks fetched: %s", data)
                return data.get("output", []), update_access_token_flag, user_info

    async def get_stock_basic_info(self, symbol):
        """OpenDART API를 사용하여 기업 정보를 조회하고, 산업분류명을 추가합니다."""
        dart = OpenDartReader(os.getenv("OPEN_DART_API_KEY"))
        result = dart.company(symbol)

        result["market"] = MARKET_MAP.get(result.get("corp_cls"), result.get("corp_cls"))
        
        # result에서 induty_code 추출
        induty_code = result.get("induty_code")
        
        # async_engine_ksic를 사용하여 industy 테이블에서 induty_name 조회
        if induty_code:
            async with AsyncSession(async_engine_ksic) as session:
                stmt = select(Industy).where(Industy.industy_code == induty_code)
                db_result = await session.execute(stmt)
                industy = db_result.scalar_one_or_none()
                
                if industy:
                    result["induty_name"] = industy.industy_name
                else:
                    result["induty_name"] = "N/A"
        else:
            result["induty_name"] = "N/A"
        
        return result
        

    async def get_stability_ratio(self, symbol: str, div_cd: str = "0", user_info=None):
        """국내주식 안정성 비율 조회"""
        url = f"{self.url_base}/uapi/domestic-stock/v1/finance/stability-ratio"
        headers = self._make_headers("FHKST66430600", user_info)
        params = {
            "fid_input_iscd": symbol,
            "FID_DIV_CLS_CODE": div_cd,
            "fid_cond_mrkt_div_code": 'J'
        }

        async with aiohttp.ClientSession() as session:
            await self._throttle()
            async with session.get(url, headers=headers, params=params) as response:
                status_code = response.status
                text = await response.text()

                update_access_token_flag = False
                if status_code in (401, 403, 500) and ("기간이 만료된 token" in text or "유효하지 않은 token" in text):
                    user_info['kis_access_token'] = await get_access_token(user_info['kis_app_key'], user_info['kis_app_secret'])
                    update_access_token_flag = True

                    headers["authorization"] = (
                        f"Bearer {user_info['kis_access_token']}"
                    )
                    await self._throttle()
                    async with session.get(
                        url, headers=headers, params=params
                    ) as res_refresh:
                        status_code = res_refresh.status
                        text = await res_refresh.text()

                data = json.loads(text)
                api_output = data['output'][:4]
                n = len(api_output)
    
                if n == 0:
                    logger.error("No data returned for stability ratio for symbol: %s", symbol)
                    return 0, []  # 기본값 반환

                df = pd.DataFrame(api_output)
                cols = ["lblt_rate", "bram_depn", "crnt_rate", "quck_rate"]
                
                for c in cols:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                    min_value = df[c].min()
                    max_value = df[c].max() if df[c].max() > min_value else min_value + 1
                    df[c] = (df[c] - min_value) / (max_value - min_value)

                weights = [0.5, 0.3, 0.15, 0.05]
                if n < 4:
                    weights = weights[:n] + [0] * (n - len(weights))  # 부족한 부분은 0으로 채움
                df["StabilityScore"] = df[cols].mean(axis=1)
                df["weight"] = weights
                df["weighted_score"] = df["StabilityScore"] * df["weight"]
                final_score = df["weighted_score"].sum()

                return final_score, api_output, update_access_token_flag, user_info


    async def get_profit_ratio(self, symbol: str, div_cd: str = "1", user_info=None):
        """수익성 비율 조회"""
        url = f"{self.url_base}/uapi/domestic-stock/v1/finance/profit-ratio"
        headers = self._make_headers("FHKST66430400", user_info)
        params = {
            "fid_input_iscd": symbol,
            "FID_DIV_CLS_CODE": div_cd,
            "fid_cond_mrkt_div_code": 'J'
        }

        async with aiohttp.ClientSession() as session:
            await self._throttle()
            async with session.get(url, headers=headers, params=params) as response:
                status_code = response.status
                text = await response.text()

                update_access_token_flag = False
                if status_code in (401, 403, 500) and ("기간이 만료된 token" in text or "유효하지 않은 token" in text):
                    user_info['kis_access_token'] = await get_access_token(user_info['kis_app_key'], user_info['kis_app_secret'])
                    update_access_token_flag = True

                    headers["authorization"] = (
                        f"Bearer {user_info['kis_access_token']}"
                    )
                    await self._throttle()
                    async with session.get(
                        url, headers=headers, params=params
                    ) as res_refresh:
                        status_code = res_refresh.status
                        text = await res_refresh.text()

                data = json.loads(text)
                api_output = data['output'][:4]
                n = len(api_output)

                if n == 0:
                    logger.error("No data returned for stability ratio for symbol: %s", symbol)
                    return 0, []  # 기본값 반환

                df = pd.DataFrame(api_output)
                cols = ["cptl_ntin_rate","self_cptl_ntin_inrt","sale_ntin_rate","sale_totl_rate"]
                
                for c in cols:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                    min_value = df[c].min()
                    max_value = df[c].max() if df[c].max() > min_value else min_value + 1
                    df[c] = (df[c] - min_value) / (max_value - min_value)

                weights = [0.5, 0.3, 0.15, 0.05]
                if n < 4:
                    weights = weights[:n] + [0] * (n - len(weights))  # 부족한 부분은 0으로 채움
                df["StabilityScore"] = df[cols].mean(axis=1)
                df["weight"] = weights
                df["weighted_score"] = df["StabilityScore"] * df["weight"]
                final_score = df["weighted_score"].sum()

                return final_score, api_output, update_access_token_flag, user_info

    async def get_growth_ratio(self, symbol: str, div_cd: str = "1", user_info=None):
        """성장성 비율 조회"""
        url = f"{self.url_base}/uapi/domestic-stock/v1/finance/growth-ratio"
        headers = self._make_headers("FHKST66430800", user_info)
        params = {
            "fid_input_iscd": symbol,
            "FID_DIV_CLS_CODE": div_cd,
            "fid_cond_mrkt_div_code": 'J'
        }

        async with aiohttp.ClientSession() as session:
            await self._throttle()
            async with session.get(url, headers=headers, params=params) as response:
                status_code = response.status
                text = await response.text()

                update_access_token_flag = False
                if status_code in (401, 403, 500) and ("기간이 만료된 token" in text or "유효하지 않은 token" in text):
                    user_info['kis_access_token'] = await get_access_token(user_info['kis_app_key'], user_info['kis_app_secret'])
                    update_access_token_flag = True

                    headers["authorization"] = (
                        f"Bearer {user_info['kis_access_token']}"
                    )
                    await self._throttle()
                    async with session.get(
                        url, headers=headers, params=params
                    ) as res_refresh:
                        status_code = res_refresh.status
                        text = await res_refresh.text()

                data = json.loads(text)

                api_output = data['output'][:4]
                n = len(api_output)

                if n == 0:
                    logger.error("No data returned for stability ratio for symbol: %s", symbol)
                    return 0, []  # 기본값 반환

                df = pd.DataFrame(api_output)
                cols = ["grs","bsop_prfi_inrt","equt_inrt","totl_aset_inrt"] # 매출액 증가율, 영업 이익 증가율, 자기자본 증가율, 총자산 증가율
                
                for c in cols:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                    min_value = df[c].min()
                    max_value = df[c].max() if df[c].max() > min_value else min_value + 1
                    df[c] = (df[c] - min_value) / (max_value - min_value)

                weights = [0.5, 0.3, 0.15, 0.05]
                if n < 4:
                    weights = weights[:n] + [0] * (n - len(weights))  # 부족한 부분은 0으로 채움

                df["StabilityScore"] = df[cols].mean(axis=1)
                df["weight"] = weights
                df["weighted_score"] = df["StabilityScore"] * df["weight"]
                final_score = df["weighted_score"].sum()

                return final_score, api_output, update_access_token_flag, user_info

    async def get_major_ratio(self, symbol: str, div_cd: str = "1", user_info=None):
        """기타 주요 비율 조회"""
        url = f"{self.url_base}/uapi/domestic-stock/v1/finance/other-major-ratios"
        headers = self._make_headers("FHKST66430500", user_info)
        params = {
            "fid_input_iscd": symbol,
            "FID_DIV_CLS_CODE": div_cd,
            "fid_cond_mrkt_div_code": 'J'
        }

        async with aiohttp.ClientSession() as session:
            await self._throttle()
            async with session.get(url, headers=headers, params=params) as response:
                status_code = response.status
                text = await response.text()

                update_access_token_flag = False
                if status_code in (401, 403, 500) and ("기간이 만료된 token" in text or "유효하지 않은 token" in text):
                    user_info['kis_access_token'] = await get_access_token(user_info['kis_app_key'], user_info['kis_app_secret'])
                    update_access_token_flag = True

                    headers["authorization"] = (
                        f"Bearer {user_info['kis_access_token']}"
                    )
                    await self._throttle()
                    async with session.get(
                        url, headers=headers, params=params
                    ) as res_refresh:
                        status_code = res_refresh.status
                        text = await res_refresh.text()

                data = json.loads(text)

                api_output = data['output'][:4]
                n = len(api_output)

                if n == 0:
                    logger.error("No data returned for stability ratio for symbol: %s", symbol)
                    return 0, []  # 기본값 반환

                df = pd.DataFrame(api_output)
                cols = ["payout_rate","eva","ebitda","ev_ebitda"] # 배당 성향, EVA, EBITDA, EV_EBITDA
                
                for c in cols:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                    min_value = df[c].min()
                    max_value = df[c].max() if df[c].max() > min_value else min_value + 1
                    df[c] = (df[c] - min_value) / (max_value - min_value)

                weights = [0.5, 0.3, 0.15, 0.05]
                if n < 4:
                    weights = weights[:n] + [0] * (n - len(weights))  # 부족한 부분은 0으로 채움
                df["StabilityScore"] = df[cols].mean(axis=1)
                df["weight"] = weights
                df["weighted_score"] = df["StabilityScore"] * df["weight"]
                final_score = df["weighted_score"].sum()

                return final_score, api_output, update_access_token_flag, user_info

    async def get_financial_ratio(self, symbol: str, div_cd: str = "1", user_info=None):
        """재무 비율 조회"""
        url = f"{self.url_base}/uapi/domestic-stock/v1/finance/financial-ratio"
        headers = self._make_headers("FHKST66430300", user_info)
        params = {
            "fid_input_iscd": symbol,
            "FID_DIV_CLS_CODE": div_cd,
            "fid_cond_mrkt_div_code": 'J'
        }

        async with aiohttp.ClientSession() as session:
            await self._throttle()
            async with session.get(url, headers=headers, params=params) as response:
                status_code = response.status
                text = await response.text()

                update_access_token_flag = False
                if status_code in (401, 403, 500) and ("기간이 만료된 token" in text or "유효하지 않은 token" in text):
                    user_info['kis_access_token'] = await get_access_token(user_info['kis_app_key'], user_info['kis_app_secret'])
                    update_access_token_flag = True

                    headers["authorization"] = (
                        f"Bearer {user_info['kis_access_token']}"
                    )
                    await self._throttle()
                    async with session.get(
                        url, headers=headers, params=params
                    ) as res_refresh:
                        status_code = res_refresh.status
                        text = await res_refresh.text()

                data = json.loads(text)
                api_output = data['output'][:4]
                n = len(api_output)

                if n == 0:
                    logger.error("No data returned for stability ratio for symbol: %s", symbol)
                    return 0, []  # 기본값 반환

                df = pd.DataFrame(api_output)
                cols = ["grs","bsop_prfi_inrt","ntin_inrt","roe_val", "eps", "sps", "bps", "rsrv_rate", "lblt_rate"] # 매출액 증가율, 영업이익증가율, 순이익증가율, ROE, EPS, 주당매출액, BPS, 유보비율, 부채비율
                
                for c in cols:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                    min_value = df[c].min()
                    max_value = df[c].max() if df[c].max() > min_value else min_value + 1
                    df[c] = (df[c] - min_value) / (max_value - min_value)

                weights = [0.5, 0.3, 0.15, 0.05]
                if n < 4:
                    weights = weights[:n] + [0] * (n - len(weights))  # 부족한 부분은 0으로 채움

                df["StabilityScore"] = df[cols].mean(axis=1)
                df["weight"] = weights
                df["weighted_score"] = df["StabilityScore"] * df["weight"]
                final_score = df["weighted_score"].sum()

                return final_score, api_output, update_access_token_flag, user_info

    async def analyze_stock(self, symbol: str, user_info: dict, risk_level: str):
        should_update_access_token = False

        stock_info = await self.get_stock_basic_info(symbol)

        stability_score, stability_data, update_access_token_flag, user_info = await self.get_stability_ratio(symbol, user_info=user_info)
        should_update_access_token |= update_access_token_flag

        profit_score, profit_data, update_access_token_flag, user_info = await self.get_profit_ratio(symbol, user_info=user_info)
        should_update_access_token |= update_access_token_flag
        
        growth_score, growth_data, update_access_token_flag, user_info = await self.get_growth_ratio(symbol, user_info=user_info)
        should_update_access_token |= update_access_token_flag
        
        major_score, major_data, update_access_token_flag, user_info = await self.get_major_ratio(symbol, user_info=user_info)
        should_update_access_token |= update_access_token_flag
        
        fin_score, fin_data, update_access_token_flag, user_info = await self.get_financial_ratio(symbol, user_info=user_info)
        should_update_access_token |= update_access_token_flag

        total_score = self._calculate_total_score(
            stability_score, profit_score, growth_score,
            major_score, fin_score, risk_level
        )

        analysis_result = {
            "symbol": symbol,
            "name": stock_info.get("corp_name"),
            "market": stock_info.get("market"),
            "sector": stock_info.get("induty_name"),
            "total_score": float(total_score),
            "stability_score": float(stability_score),
            "profit_score": float(profit_score),
            "growth_score": float(growth_score),
            "details": {
                "stability": stability_data,
                "profit": profit_data,
                "growth": growth_data,
                "major": major_data,
                "financial": fin_data
            }
        }

        return analysis_result, should_update_access_token

    async def analyze_portfolio(self, risk_level: str, user_info: dict, top_n: int = 30) -> Dict:
        """
        투자 성향에 따른 포트폴리오 분석 및 추천

        risk_level: "안정형" | "안정추구형" | "위험중립형" | "적극투자형" | "공격투자형"
        """
        logger.info("Analyzing portfolio for risk level: %s with top N: %d", risk_level, top_n)
        # 1. 시가총액 상위 종목 조회
        ranking, update_access_token_flag, user_info = await self.get_top_market_value(fid_rank_sort_cls_code='23', user_info=user_info)
        portfolio_data = []
        should_update_access_token = update_access_token_flag

        tasks = []
        # 2. 각 종목별 지표 분석
        for item in ranking[:top_n]:
            symbol = item.get("mksc_shrn_iscd")
            if not symbol:
                logger.warning("No symbol found for item: %s", item)
                continue
            tasks.append(self.analyze_stock(symbol, user_info, risk_level))

        results = await asyncio.gather(*tasks)
        for analysis_result, flag in results:
            should_update_access_token |= flag
            portfolio_data.append(analysis_result)

        logger.info("Portfolio analysis completed. Total stocks analyzed: %d", len(portfolio_data))
        # 3. 투자 성향에 따른 포트폴리오 구성
        if should_update_access_token:
            from multi_agent.utils import update_user_kis_credentials
            await update_user_kis_credentials(async_engine, user_info['id'], user_info['kis_access_token'])
        return self._build_portfolio_recommendation(portfolio_data, risk_level)

    def _calculate_total_score(self, stability: float, profit: float, 
                             growth: float, major: float, fin: float, 
                             risk_level: str) -> float:
        """투자 성향에 따른 종합 점수 계산"""
        if risk_level == "위험중립형":
            weights = {
                "stability": 0.3,
                "profit": 0.2,
                "growth": 0.2,
                "major": 0.2,
                "financial": 0.1
            }
        elif risk_level == "안정추구형":
            weights = {
                "stability": 0.4,
                "profit": 0.2,
                "growth": 0.1,
                "major": 0.2,
                "financial": 0.1
            }
        elif risk_level == "안정형":
            weights = {
                "stability": 0.3,
                "profit": 0.3,
                "growth": 0.2,
                "major": 0.1,
                "financial": 0.1
            }
        elif risk_level == "적극투자형":
            weights = {
                "stability": 0.2,
                "profit": 0.3,
                "growth": 0.3,
                "major": 0.1,
                "financial": 0.1
            }
        else:  # 공격투자형
            weights = {
                "stability": 0.1,
                "profit": 0.3,
                "growth": 0.4,
                "major": 0.1,
                "financial": 0.1
            }

        return (
            stability * weights["stability"] +
            profit * weights["profit"] +
            growth * weights["growth"] +
            major * weights["major"] +
            fin * weights["financial"]
        )

    def _build_portfolio_recommendation(self, data: List[Dict], 
                                      risk_level: str) -> Dict:
        """투자 성향에 따른 포트폴리오 추천"""
        # 점수 기준 정렬
        sorted_data = sorted(data, key=lambda x: x["total_score"], reverse=True)

        # 투자 성향별 포트폴리오 크기 설정
        if risk_level == "위험중립형":
            portfolio_size = 4
        elif risk_level == "안정추구형":
            portfolio_size = 3
        elif risk_level == "안정형":
            portfolio_size = 3
        elif risk_level == "적극투자형":
            portfolio_size = 5
        else:  # 공격투자형
            portfolio_size = 6

        # 상위 종목 선정
        recommended_portfolio = sorted_data[:portfolio_size]

        # 투자 비중 계산
        total_score = sum(item["total_score"] for item in recommended_portfolio)
        for item in recommended_portfolio:
            item["weight"] = round(item["total_score"] / total_score * 100, 2)

        return {
            "risk_level": risk_level,
            "portfolio_size": portfolio_size,
            "recommendations": recommended_portfolio
        }

    def _format_analysis_result_to_markdown(self, analysis_result: Dict) -> str:
        """분석 결과를 한국어 마크다운 표로 변환"""
        risk_level = analysis_result.get("risk_level", "N/A")
        portfolio_size = analysis_result.get("portfolio_size", 0)
        recommendations = analysis_result.get("recommendations", [])
        
        # 마크다운 시작
        markdown = "# 포트폴리오 분석 결과\n\n"
        
        # 포트폴리오 개요
        markdown += "## 📋 포트폴리오 개요\n"
        markdown += f"- **투자 성향**: {risk_level}\n"
        markdown += f"- **추천 종목 수**: {portfolio_size}개\n\n"
        markdown += "---\n\n"
        
        # 추천 종목 목록 표
        markdown += "## 🎯 추천 종목 목록\n\n"
        markdown += "| 순위 | 종목명 | 종목코드 | 업종 | 시장 | 투자비중 | 종합점수 | 안정성점수 | 수익성점수 | 성장성점수 |\n"
        markdown += "|:---:|:---|:---:|:---|:---|---:|---:|---:|---:|---:|\n"
        
        for idx, stock in enumerate(recommendations, 1):
            name = stock.get("name", "N/A")
            symbol = stock.get("symbol", "N/A")
            sector = stock.get("sector", "N/A")
            market = stock.get("market", "N/A")
            weight = stock.get("weight", 0)
            total_score = stock.get("total_score", 0)
            stability_score = stock.get("stability_score", 0)
            profit_score = stock.get("profit_score", 0)
            growth_score = stock.get("growth_score", 0)
            
            markdown += f"| {idx} | {name} | {symbol} | {sector} | {market} | {weight}% | {total_score:.3f} | {stability_score:.3f} | {profit_score:.3f} | {growth_score:.3f} |\n"
        
        return markdown
    
    def _run(self, user_investor_type: str, config: RunnableConfig = None, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        return asyncio.run(self._arun(config, run_manager))


    async def _arun(
        self, 
        user_investor_type: str,
        config: RunnableConfig = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """
        비동기 포트폴리오 분석 실행 메서드
        risk_profile: 투자자의 위험 성향 (선택적)
        top_n: 분석할 종목 수
        """
        # try:
        # user_info를 가져오는 비동기 호출
        user_info = await get_user_kis_credentials(async_engine=async_engine, user_id=config["configurable"]["user_id"])
        update_access_token_flag = False

        if not user_info['kis_access_token']:
            access_token = await get_access_token(user_info['kis_app_key'], user_info['kis_app_secret'])
            user_info['kis_access_token'] = access_token
            update_access_token_flag = True
        
        # 포트폴리오 분석 실행
        analysis_result = await self.analyze_portfolio(user_investor_type, user_info, top_n=20)

        # 마크다운 형식으로 변환하여 반환
        markdown_result = self._format_analysis_result_to_markdown(analysis_result)
        
        return markdown_result
