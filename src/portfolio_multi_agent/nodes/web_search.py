import os
import asyncio
from pydantic import BaseModel, Field
from portfolio_multi_agent.state import Stock, AnalysisResult
from langchain_openai import ChatOpenAI

from .rank_func import *


class InputState(BaseModel):
    portfolio_list: list[Stock] = Field(default_factory=list)


class OutputState(BaseModel):
    analysis_results: list[AnalysisResult] = Field(default_factory=list)


class WebSearch:
    name = "WebSearch"

    def __init__(self, model: str = "perplexity/sonar"):
        self.llm = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            model=model,
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

    async def search_single_stock(self, stock: Stock) -> AnalysisResult:
        """
        단일 종목에 대한 웹 검색 분석

        Args:
            stock: 종목 정보

        Returns:
            AnalysisResult 객체
        """
        query = f"{stock.name}({stock.code}) 주식의 최근 뉴스, 재무 실적, 투자 전망, 주요 리스크 요인, 그리고 산업 동향을 종합적으로 분석하여 투자 의사결정에 도움이 될 수 있는 정보를 제공해주세요."
        response = await self.llm.ainvoke(query)

        return AnalysisResult(
            code=stock.code,
            name=stock.name,
            type="web_search",
            result=response.content,
        )

    async def __call__(self, state: InputState) -> OutputState:
        """
        여러 종목에 대한 웹 검색 분석을 병렬로 실행

        Args:
            state: 입력 상태 (종목 리스트)

        Returns:
            분석 결과 리스트
        """
        if not state.portfolio_list:
            return {"analysis_results": []}

        # 모든 종목에 대해 병렬로 웹 검색 분석
        tasks = [self.search_single_stock(stock) for stock in state.portfolio_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 성공한 결과만 필터링
        analysis_results = []
        for i, result in enumerate(results):
            if isinstance(result, AnalysisResult):
                analysis_results.append(result)
            elif isinstance(result, Exception):
                continue

        return {"analysis_results": analysis_results}
