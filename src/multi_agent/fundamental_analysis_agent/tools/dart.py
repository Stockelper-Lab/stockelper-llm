from typing import Type, Optional
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
import OpenDartReader
import dotenv
import os
import json
from datetime import datetime


class AnalysisFinancialStatementInput(BaseModel):
    stock_code: str = Field(
        description="The stock code of the company you want to analyze."
    )


class AnalysisFinancialStatementTool(BaseTool):
    name: str = "analize_financial_statements"
    description: str = (
        "Analyzes company financial statements to calculate critical financial health metrics including current ratio, debt ratio, retained earnings ratio, capital impairment ratio, ordinary income, ordinary income margin, interest coverage ratio, and ROE."
    )
    args_schema: Type[BaseModel] = AnalysisFinancialStatementInput
    return_direct: bool = False

    dart: object

    def __init__(self):
        super().__init__(dart=OpenDartReader(os.environ["OPEN_DART_API_KEY"]))

    def calculater(self, financial_statement_all):

        # # 55기 데이터 필터링 (제 55 기)
        # df_55 = financial_statement_all[
        #     financial_statement_all["thstrm_nm"] == "제 55 기"
        # ]
        df_55 = financial_statement_all.iloc[:]

        # 사용할 계정 ID 목록 업데이트
        financial_data = df_55[
            df_55["account_id"].isin(
                [
                    "ifrs-full_CurrentAssets",
                    "ifrs-full_CurrentLiabilities",
                    "ifrs-full_Liabilities",
                    "ifrs-full_Equity",
                    "ifrs-full_SharePremium",
                    "ifrs-full_RetainedEarnings",
                    "ifrs-full_IssuedCapital",
                    "dart_OperatingIncomeLoss",
                    "dart_OtherGains",
                    "dart_OtherLosses",
                    "ifrs-full_ProfitLoss",
                    "ifrs-full_Revenue",
                    "ifrs-full_FinanceCosts",
                ]
            )
        ]

        # 계산을 위한 재무 데이터 딕셔너리 생성
        financial_dict = financial_data.set_index("account_id")[
            "thstrm_amount"
        ].to_dict()

        # 계산을 위해 모든 값을 float로 변환
        for key in financial_dict:
            financial_dict[key] = float(financial_dict[key])

        results_dict = {}

        # 계산 수행
        # 1. 유동비율 = (유동자산 / 유동부채) * 100
        try:
            current_ratio = (
                financial_dict["ifrs-full_CurrentAssets"]
                / financial_dict["ifrs-full_CurrentLiabilities"]
            ) * 100
            results_dict["유동비율"] = f"{current_ratio:.2f}%"
        except:
            pass

        # 2. 부채비율 = (부채총계 / 자본총계) * 100
        try:
            debt_ratio = (
                financial_dict["ifrs-full_Liabilities"]
                / financial_dict["ifrs-full_Equity"]
            ) * 100
            results_dict["부채비율"] = f"{debt_ratio:.2f}%"
        except:
            pass

        # 3. 유보율 = (자본잉여금 + 이익잉여금) / 납입자본금 * 100
        try:
            reserve_ratio = (
                (
                    financial_dict["ifrs-full_SharePremium"]
                    + financial_dict["ifrs-full_RetainedEarnings"]
                )
                / financial_dict["ifrs-full_IssuedCapital"]
            ) * 100
            results_dict["유보율"] = f"{reserve_ratio:.2f}%"
        except:
            pass

        # 4. 자본잠식률 = {(자본금 - 자본총계) / 자본금} * 100
        try:
            capital_impairment_ratio = (
                (
                    financial_dict["ifrs-full_IssuedCapital"]
                    - financial_dict["ifrs-full_Equity"]
                )
                / financial_dict["ifrs-full_IssuedCapital"]
            ) * 100
            results_dict["자본잠식률"] = f"{capital_impairment_ratio:.2f}%"
        except:
            pass

        # 5. 경상이익 = 영업이익 + 영업외수익 - 영업외비용
        try:
            ordinary_income = (
                financial_dict["dart_OperatingIncomeLoss"]
                + financial_dict["dart_OtherGains"]
                - financial_dict["dart_OtherLosses"]
            )
            results_dict["경상이익"] = f"{ordinary_income:.2f}원"
        except:
            pass

        # 8. 매출액경상이익률 = 경상이익 / 매출액 * 100
        try:
            ordinary_income_ratio = (
                ordinary_income / financial_dict["ifrs-full_Revenue"]
            ) * 100
            results_dict["매출액경상이익률"] = f"{ordinary_income_ratio:.2f}%"
        except:
            pass

        # 9. 이자보상배율 = 영업이익 / 이자비용 * 100
        try:
            interest_coverage_ratio = (
                financial_dict["dart_OperatingIncomeLoss"]
                / financial_dict["ifrs-full_FinanceCosts"]
            ) * 100
            results_dict["이자보상배율"] = f"{interest_coverage_ratio:.2f}%"
        except:
            pass

        # 10. 자기자본이익률 = 당기순이익 / 자본총액 * 100
        try:
            roe = (
                financial_dict["ifrs-full_ProfitLoss"]
                / financial_dict["ifrs-full_Equity"]
            ) * 100
            results_dict["자기자본이익률"] = f"{roe:.2f}%"
        except:
            pass

        return results_dict

    def _run(
        self, stock_code: str, config: RunnableConfig, run_manager: Optional[CallbackManagerForToolRun] = None
    ):
        current_year = datetime.now().year
        financial_statement_all = None

        # 종목코드 형식 확인 및 변환
        if len(stock_code) != 6 or not stock_code.isdigit():
            return {"error": f"잘못된 종목코드 형식입니다: {stock_code}. 6자리 숫자여야 합니다."}

        for offset in range(5):
            year = current_year - offset
            try:
                print(f"DART API 조회 시도: 종목코드={stock_code}, 연도={year}")
                df = self.dart.finstate_all(stock_code, year)
                
                if df is not None and not df.empty:
                    print(f"재무제표 데이터 발견: {year}년, 행수={len(df)}")
                    financial_statement_all = df
                    break
                else:
                    print(f"{year}년 데이터 없음")
                    
            except Exception as e:
                print(f"DART API 오류 ({year}년): {str(e)}")
                continue

        if financial_statement_all is None or financial_statement_all.empty:
            return {"error": f"종목코드 {stock_code}의 최근 5년 내 재무제표를 찾지 못했습니다. DART에 등록된 종목인지 확인해주세요."}

        try:
            analysis_result = self.calculater(financial_statement_all)
            return analysis_result
        except Exception as e:
            return {"error": f"재무제표 분석 중 오류 발생: {str(e)}"}

    async def _arun(
        self,
        stock_code: str,
        config: RunnableConfig,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ):
        result = self._run(stock_code, config, run_manager)

        return result
