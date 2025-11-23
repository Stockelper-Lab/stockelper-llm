import os
import asyncio
from pydantic import BaseModel, Field
from portfolio_multi_agent.state import Stock, AnalysisResult
import OpenDartReader
from datetime import datetime


class InputState(BaseModel):
    portfolio_list: list[Stock] = Field(default_factory=list)


class OutputState(BaseModel):
    analysis_results: list[AnalysisResult] = Field(default_factory=list)


class FinancialStatement:
    name = "FinancialStatement"

    def __init__(self):
        api_key = os.getenv("OPEN_DART_API_KEY")
        if not api_key:
            raise ValueError(
                "오류: OPEN_DART_API_KEY 환경변수가 설정되어 있지 않습니다."
            )
        self.dart = OpenDartReader(api_key)

    async def __call__(self, state: InputState) -> OutputState:
        """
        여러 종목에 대한 재무제표 분석을 병렬로 실행

        Args:
            state: 입력 상태 (종목 리스트)

        Returns:
            분석 결과 리스트
        """
        if not state.portfolio_list:
            return {"analysis_results": []}

        # 모든 종목에 대해 병렬로 재무제표 분석
        # DART API는 동기 함수이므로 asyncio.to_thread 사용
        tasks = [
            asyncio.to_thread(self.analyze_single_stock, stock)
            for stock in state.portfolio_list
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 성공한 결과만 필터링
        analysis_results = []
        for i, result in enumerate(results):
            if isinstance(result, AnalysisResult):
                analysis_results.append(result)
            elif isinstance(result, Exception):
                continue

        return {"analysis_results": analysis_results}

    def calculater(self, financial_statement_all):
        """
        재무제표 데이터로부터 주요 재무 지표를 계산합니다.

        Args:
            financial_statement_all: OpenDartReader로부터 가져온 재무제표 DataFrame

        Returns:
            dict: 계산된 재무 지표들 (한글 키, 포맷팅된 값)
        """
        df_55 = financial_statement_all.iloc[:]

        # 사용할 계정 ID 목록
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
        ordinary_income = 0
        try:
            ordinary_income = (
                financial_dict["dart_OperatingIncomeLoss"]
                + financial_dict["dart_OtherGains"]
                - financial_dict["dart_OtherLosses"]
            )
            results_dict["경상이익"] = f"{ordinary_income:.2f}원"
        except:
            pass

        # 6. 매출액경상이익률 = 경상이익 / 매출액 * 100
        try:
            ordinary_income_ratio = (
                ordinary_income / financial_dict["ifrs-full_Revenue"]
            ) * 100
            results_dict["매출액경상이익률"] = f"{ordinary_income_ratio:.2f}%"
        except:
            pass

        # 7. 이자보상배율 = 영업이익 / 이자비용 * 100
        try:
            interest_coverage_ratio = (
                financial_dict["dart_OperatingIncomeLoss"]
                / financial_dict["ifrs-full_FinanceCosts"]
            ) * 100
            results_dict["이자보상배율"] = f"{interest_coverage_ratio:.2f}%"
        except:
            pass

        # 8. 자기자본이익률 = 당기순이익 / 자본총액 * 100
        try:
            roe = (
                financial_dict["ifrs-full_ProfitLoss"]
                / financial_dict["ifrs-full_Equity"]
            ) * 100
            results_dict["자기자본이익률"] = f"{roe:.2f}%"
        except:
            pass

        return results_dict

    def analyze_single_stock(self, stock: Stock) -> AnalysisResult:
        """
        단일 종목에 대한 재무제표 분석

        Args:
            stock: 종목 정보

        Returns:
            AnalysisResult 객체
        """
        # 최근 5년 내 재무제표 데이터 조회
        current_year = datetime.now().year
        financial_statement_all = None

        for offset in range(5):
            year = current_year - offset
            try:
                df = self.dart.finstate_all(stock.code, year)

                if df is not None and not df.empty:
                    financial_statement_all = df
                    break

            except Exception as e:
                continue

        if financial_statement_all is None or financial_statement_all.empty:
            return AnalysisResult(
                code=stock.code,
                name=stock.name,
                type="financial_statement",
                result=f"오류: 종목코드 {stock.code}({stock.name})의 최근 5년 내 재무제표를 찾지 못했습니다. DART에 등록된 종목인지 확인해주세요.",
            )

        # 재무 지표 계산
        analysis_result = self.calculater(financial_statement_all)

        # 결과를 문자열로 포맷팅
        if not analysis_result:
            result_str = "재무제표 데이터를 분석했으나 계산 가능한 지표가 없습니다."
        else:
            result_lines = [f"{stock.name}({stock.code}) 재무제표 분석 결과:\n"]
            for key, value in analysis_result.items():
                result_lines.append(f"- {key}: {value}")
            result_str = "\n".join(result_lines)

        return AnalysisResult(
            code=stock.code,
            name=stock.name,
            type="financial_statement",
            result=result_str,
        )
