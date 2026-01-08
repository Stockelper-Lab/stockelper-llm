from typing import Type, Optional
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
import os
import logging
import aiohttp
import json
import asyncio
from prophet import Prophet
import pandas as pd
import FinanceDataReader as fdr
from statsmodels.tsa.arima.model import ARIMA
import numpy as np
from sqlalchemy.ext.asyncio import create_async_engine

from multi_agent.utils import (
    KIS_BASE_URL,
    get_user_kis_context,
    is_kis_token_expired_message,
    refresh_user_kis_access_token,
)


URL_BASE = KIS_BASE_URL

logger = logging.getLogger(__name__)


def _debug_errors_enabled() -> bool:
    return os.getenv("DEBUG_ERRORS", "false").lower() in {"1", "true", "yes"}



# KIS Auth
class AnalysisStockInput(BaseModel):
    stock_code: str = Field(
        description="The stock code of the company you want to analyze."
    )


class AnalysisStockTool(BaseTool):
    name: str = "analysis_stock"
    description: str = (
        "A comprehensive stock analysis tool that provides key market information, price trends, trading status, investment indicators (PER, PBR, EPS, BPS), foreign ownership ratio, and market warning signals for listed companies."
    )
    args_schema: Type[BaseModel] = AnalysisStockInput
    return_direct: bool = False
    
    async_engine: object

    def __init__(self, async_database_url: str):
        super().__init__(
            async_engine=create_async_engine(async_database_url, echo=False)
        )
    
    # 주식현재가 시세
    async def get_current_price(self, stock_no, user_id):
        try:
            user_info = await get_user_kis_context(self.async_engine, user_id, require=False)
            if not user_info:
                logger.warning("KIS current price: no user KIS context (user_id=%s)", user_id)
                return {
                    "error": "KIS 자격증명/계좌정보가 없어 현재가를 조회할 수 없습니다.",
                    "user_id": user_id,
                }

            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {user_info['kis_access_token']}",
                "appkey": user_info['kis_app_key'],
                "appsecret": user_info['kis_app_secret'],
                "tr_id": "FHKST01010100",
            }
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": stock_no,
            }
            PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
            URL = f"{URL_BASE}/{PATH}"

            # print(f"Price request URL: {URL}")
            # print(f"Price request headers: {headers}")
            # print(f"Price request params: {params}")

            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(URL, headers=headers, params=params) as res:
                    status_code = res.status
                    try:
                        res_body = await res.json()
                    except Exception:
                        text = await res.text()
                        res_body = {"msg1": text}

                    msg = (
                        res_body.get("msg1", "") if isinstance(res_body, dict) else str(res_body)
                    )
                    # 일부 엔드포인트는 200으로 내려오더라도 msg1에 토큰 만료가 담길 수 있어
                    # 상태코드와 무관하게 메시지 기반으로 만료를 감지합니다(1회 재시도).
                    if is_kis_token_expired_message(msg):
                        # 토큰 재발급 → DB 업데이트 → 1회 재시도
                        try:
                            user_info["kis_access_token"] = await refresh_user_kis_access_token(
                                self.async_engine, user_id, user_info
                            )
                            headers["authorization"] = f"Bearer {user_info['kis_access_token']}"
                        except Exception as e:
                            logger.exception(
                                "KIS current price: token refresh failed (user_id=%s)", user_id
                            )
                            return {"error": f"KIS 토큰 재발급 실패: {type(e).__name__}: {e}"}
                        async with session.get(URL, headers=headers, params=params) as res_refresh:
                            status_code = res_refresh.status
                            try:
                                res_body = await res_refresh.json()
                            except Exception:
                                text = await res_refresh.text()
                                res_body = {"msg1": text}

                    if status_code != 200:
                        err_msg = (
                            res_body.get("msg1")
                            if isinstance(res_body, dict)
                            else str(res_body)
                        )
                        logger.warning(
                            "KIS current price HTTP error: user_id=%s stock_no=%s status=%s msg=%s",
                            user_id,
                            stock_no,
                            status_code,
                            (err_msg or "")[:200],
                        )
                        return {"error": f"KIS 현재가 조회 실패(HTTP {status_code}): {err_msg}"}

                    try:
                        if res_body.get("rt_cd") != "0":
                            msg1 = res_body.get("msg1", "")
                            logger.warning(
                                "KIS current price API error: user_id=%s stock_no=%s rt_cd=%s msg1=%s",
                                user_id,
                                stock_no,
                                res_body.get("rt_cd"),
                                (msg1 or "")[:200],
                            )
                            return {"error": f"KIS 현재가 조회 실패: {msg1}"}

                        output = res_body.get("output", {})
                        if not output:
                            logger.warning(
                                "KIS current price: empty output (user_id=%s stock_no=%s)",
                                user_id,
                                stock_no,
                            )
                            return {"error": "KIS 현재가 응답에 output이 없습니다."}

                        # 필요한 정보만 추출하여 반환
                        return {
                            "대표 시장 한글 명": output.get("rprs_mrkt_kor_name", ""),
                            "업종": output.get("bstp_kor_isnm", ""),
                            "종목 코드": stock_no,
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
                            "전일 대비 거래량 비율": output.get(
                                "prdy_vrss_vol_rate", ""
                            ),
                            "최고가 대비 현재가": f"{output.get('stck_hgpr', '')} - {output.get('stck_prpr', '')}",
                            "최저가 대비 현재가": f"{output.get('stck_prpr', '')} - {output.get('stck_lwpr', '')}",
                            "250일 최고가": output.get("d250_hgpr", ""),
                            "250일 최저가": output.get("d250_lwpr", ""),
                            "신용 가능 여부": output.get("crdt_able_yn", ""),
                            "ELW 발행 여부": output.get("elw_pblc_yn", ""),
                            "외국인 보유율": output.get("hts_frgn_ehrt", ""),
                            "단기과열 여부": output.get("ovtm_vi_cls_code", ""),
                            "저유동성 종목 여부": output.get("sltr_yn", ""),
                            "시장 경고 코드": output.get("mrkt_warn_cls_code", ""),
                        }
                    except (KeyError, json.JSONDecodeError) as e:
                        logger.exception(
                            "KIS current price parse error: user_id=%s stock_no=%s",
                            user_id,
                            stock_no,
                        )
                        return {"error": f"KIS 응답 파싱 실패: {type(e).__name__}: {e}"}
        except Exception as e:
            if _debug_errors_enabled():
                logger.exception(
                    "KIS current price unexpected error: user_id=%s stock_no=%s",
                    user_id,
                    stock_no,
                )
            else:
                logger.warning(
                    "KIS current price unexpected error: user_id=%s stock_no=%s err=%s: %s",
                    user_id,
                    stock_no,
                    type(e).__name__,
                    e,
                )
            return {"error": f"KIS 현재가 조회 중 오류: {type(e).__name__}: {e}"}

    def _run(
        self,
        stock_code: str,
        config: RunnableConfig,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        # 동기 버전에서는 비동기 함수를 asyncio.run으로 실행
        return asyncio.run(self._arun(stock_code, config, run_manager))

    async def _arun(
        self,
        stock_code: str,
        config: RunnableConfig,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ):
        # 비동기 버전에서는 직접 비동기 함수 호출
        res = await self.get_current_price(stock_code, config["configurable"]["user_id"])
        if res is None:
            res = {"error": "주가 정보를 가져오는데 실패했습니다."}

        return res


class PredictStockTool(BaseTool):
    name: str = "predict_stock"
    description: str = (
        "This tool predicts stock price trends and analyzes future market movements based on stock price fluctuations. "
        "It identifies key trends, turning points, and factors that could influence future market performance. "
        "Use this tool to gain insights into market dynamics and formulate data-driven investment strategies."
    )
    args_schema: Type[BaseModel] = AnalysisStockInput
    return_direct: bool = False

    def predict_with_prophet(self, df: pd.DataFrame, periods: int = 365):
        """Prophet을 사용한 주가 예측"""

        prophet_df = pd.DataFrame({"ds": df["Date"], "y": df["Change"]})

        model = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05,
        )
        model.fit(prophet_df)

        future = model.make_future_dataframe(periods=periods)
        forecast = model.predict(future)
        changes = forecast["yhat"].iloc[-periods:].values

        return changes

    def predict_with_arima(self, df: pd.DataFrame, periods: int = 365):
        """ARIMA를 사용한 주가 예측"""

        model = ARIMA(df["Change"], order=(5, 1, 0))
        results = model.fit()
        forecast = results.forecast(steps=periods).values

        return forecast

    def ensemble_prediction(self, stock_code: str, periods: int = 365):
        """Prophet과 ARIMA의 앙상블 예측"""

        # 전체 시계열 불러오기 (OHLCV)
        df_all = fdr.DataReader(f"KRX:{stock_code}", "2023")
        # Change 컬럼이 없는 경우 Close 기준으로 생성
        if "Change" not in df_all.columns:
            base_col = "Close" if "Close" in df_all.columns else ("Adj Close" if "Adj Close" in df_all.columns else None)
            if base_col is None:
                raise ValueError("시계열 데이터에 Close/Adj Close 컬럼이 없어 Change 계산이 불가합니다.")
            df_all["Change"] = df_all[base_col].pct_change().fillna(0)

        # Prophet/ARIMA에 필요한 컬럼만 사용하고 인덱스를 컬럼으로
        df = df_all[["Change"]].reset_index()  # reset_index 후 날짜 컬럼은 'Date'

        prophet_changes = self.predict_with_prophet(df, periods)
        arima_changes = self.predict_with_arima(df, periods)

        ensemble_changes = (prophet_changes + arima_changes) / 2

        return ensemble_changes

    def _run(
        self,
        stock_code: str,
        config: Optional[RunnableConfig] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        try:

            # 앙상블 예측 실행
            predicted_changes = self.ensemble_prediction(stock_code)
            # print(predicted_changes)

            avg_change = np.mean(predicted_changes)
            max_change = np.max(predicted_changes)
            min_change = np.min(predicted_changes)
            volatility = np.std(predicted_changes)

            observation = {
                "평균 변동률": avg_change,
                "최대 상승률": max_change,
                "최대 하락률": min_change,
                "변동성": volatility
            }

            return observation

        except Exception as e:
            return f"예측 중 오류가 발생했습니다: {str(e)}"

    async def _arun(
        self,
        stock_code: str,
        config: Optional[RunnableConfig] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        result = self._run(stock_code, config, run_manager)

        return result
