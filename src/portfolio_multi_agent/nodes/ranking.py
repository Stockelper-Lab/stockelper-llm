import os
import asyncio
from typing import Dict, List, Callable, Any, Tuple
from pydantic import BaseModel, Field
from portfolio_multi_agent.state import RankWeight, Stock

from .rank_func import *


class InputState(BaseModel):
    max_portfolio_size: int = Field(
        default=10, description="Maximum number of stocks in the portfolio"
    )
    rank_weight: RankWeight = Field(default_factory=RankWeight)


class OutputState(BaseModel):
    portfolio_list: list[Stock] = Field(default_factory=list)
    stock_scores: dict[str, float] = Field(
        default_factory=dict, description="각 종목의 순위 점수"
    )
    ranking_details: dict[str, list[Stock]] = Field(
        default_factory=dict, description="각 순위 함수별 상위 종목 리스트"
    )


class Ranking:
    name = "Ranking"

    async def __call__(self, state: InputState) -> OutputState:
        # 1. API 인증 정보 로드
        creds = self._get_api_credentials()

        # 2. 실행할 작업 목록 생성
        active_tasks = self._get_active_tasks(state)

        # 3. 작업 실행 및 점수 계산
        stock_scores, stock_info, ranking_details = await self._execute_ranking_tasks(
            active_tasks, creds
        )

        # 4. 상위 종목 선정
        top_stocks, top_stock_scores = self._select_top_stocks(
            stock_scores, stock_info, state.max_portfolio_size
        )

        return {
            "portfolio_list": top_stocks,
            "stock_scores": top_stock_scores,
            "ranking_details": ranking_details,
        }

    def _get_api_credentials(self) -> Dict[str, str]:
        """API 인증 정보 로드"""
        return {
            "app_key": os.getenv("APP_KEY", ""),
            "app_secret": os.getenv("APP_SECRET", ""),
            "access_token": os.getenv("ACCESS_TOKEN", ""),
        }

    def _get_active_tasks(self, state: InputState) -> List[Tuple[str, Callable, float]]:
        """실행할 순위 함수 목록 생성 (가중치가 0이 아닌 것만)"""
        rank_functions = {
            "operating_profit": get_operating_profit_rank,
            "net_income": get_net_income_rank,
            "total_liabilities": get_total_liabilities_rank,
            "rise_rate": get_rise_rate_rank,
            "fall_rate": get_fall_rate_rank,
            "profitability": get_profitability_rank,
            "stability": get_stability_rank,
            "growth": get_growth_rank,
            "activity": get_activity_rank,
            "volume": get_volume_rank,
            "market_cap": get_market_cap_rank,
        }

        active_tasks = []
        for rank_name, rank_func in rank_functions.items():
            weight = getattr(state.rank_weight, rank_name, 0.0)
            if weight > 0.0:
                active_tasks.append((rank_name, rank_func, weight))

        return active_tasks

    def _calculate_scores(
        self,
        results: List[Any],
        batch_tasks: List[Tuple[str, Callable, float]],
        stock_scores: Dict[str, float],
        stock_info: Dict[str, str],
        ranking_details: Dict[str, List[Stock]],
    ):
        """API 호출 결과를 처리하여 종목별 점수 계산"""
        for i, result in enumerate(results):
            rank_name, _, weight = batch_tasks[i]

            if isinstance(result, Exception):
                continue

            stocks = result

            # 순위 정보 저장
            ranking_details[rank_name] = [
                Stock(code=s["code"], name=s["name"]) for s in stocks
            ]

            # 정규화를 위한 총 개수
            n = len(stocks)
            if n == 0:
                continue

            # 정규화 합계: 1 + 2 + ... + n = n * (n + 1) / 2
            total_sum = n * (n + 1) / 2

            # 각 종목에 정규화된 순위 점수 부여
            for rank, stock in enumerate(stocks, start=1):
                code = stock["code"]
                name = stock["name"]

                # 종목 정보 저장
                if code not in stock_info:
                    stock_info[code] = name

                # 높은 순위일수록 높은 점수
                normalized_score = (n - rank + 1) / total_sum
                weighted_score = normalized_score * weight

                if code in stock_scores:
                    stock_scores[code] += weighted_score
                else:
                    stock_scores[code] = weighted_score

    async def _execute_ranking_tasks(
        self,
        active_tasks: List[Tuple[str, Callable, float]],
        creds: Dict[str, str],
    ) -> Tuple[Dict[str, float], Dict[str, str], Dict[str, List[Stock]]]:
        """순위 함수들을 배치 단위로 비동기 실행"""
        stock_scores: Dict[str, float] = {}
        stock_info: Dict[str, str] = {}  # code -> name 매핑
        ranking_details: Dict[str, List[Stock]] = {}

        # 환경변수에서 초당 최대 요청수 읽기
        max_requests_per_second = int(os.getenv("KIS_MAX_REQUESTS_PER_SECOND", "20"))
        batch_size = max_requests_per_second

        for i in range(0, len(active_tasks), batch_size):
            batch = active_tasks[i : i + batch_size]

            # 배치 내 함수들을 병렬로 호출 (비동기)
            coroutines = [
                rank_func(
                    top_n=30,
                    app_key=creds["app_key"],
                    app_secret=creds["app_secret"],
                    access_token=creds["access_token"],
                )
                for _, rank_func, _ in batch
            ]

            results = await asyncio.gather(*coroutines, return_exceptions=True)

            # 결과 처리 및 점수 계산
            self._calculate_scores(
                results, batch, stock_scores, stock_info, ranking_details
            )

            # 마지막 배치가 아니면 대기 (Rate Limit 준수)
            if i + batch_size < len(active_tasks):
                await asyncio.sleep(1.0)

        return stock_scores, stock_info, ranking_details

    def _select_top_stocks(
        self,
        stock_scores: Dict[str, float],
        stock_info: Dict[str, str],
        max_size: int,
    ) -> Tuple[List[Stock], Dict[str, float]]:
        """점수 기준으로 상위 종목 선정"""
        # 점수 기준으로 정렬 (높을수록 좋음, 내림차순)
        sorted_stocks = sorted(stock_scores.items(), key=lambda x: x[1], reverse=True)

        # 상위 max_portfolio_size 개의 종목 정보 추출
        top_stocks = [
            Stock(code=code, name=stock_info[code])
            for code, _ in sorted_stocks[:max_size]
        ]

        # 상위 종목들의 점수만 추출
        top_stock_scores = {code: score for code, score in sorted_stocks[:max_size]}

        return top_stocks, top_stock_scores
