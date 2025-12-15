from typing import Literal, Optional, Annotated
from pydantic import BaseModel, Field


def add_value(existing: list, update: list):
    return existing + update


class Stock(BaseModel):
    code: str = Field(description="종목 코드")
    name: str = Field(description="종목명")


class RankWeight(BaseModel):
    operating_profit: float = Field(default=0.0, description="영업이익 순위 가중치")
    net_income: float = Field(default=0.0, description="당기순이익 순위 가중치")
    total_liabilities: float = Field(default=0.0, description="부채총계 순위 가중치")
    rise_rate: float = Field(default=0.0, description="상승률 순위 가중치")
    fall_rate: float = Field(default=0.0, description="하락률 순위 가중치")
    profitability: float = Field(default=0.0, description="수익성 분석 순위 가중치")
    stability: float = Field(default=0.0, description="안정성 분석 순위 가중치")
    growth: float = Field(default=0.0, description="성장성 분석 순위 가중치")
    activity: float = Field(default=0.0, description="활동성 분석 순위 가중치")
    volume: float = Field(default=0.0, description="거래량 순위 가중치")
    market_cap: float = Field(default=0.0, description="시가총액 순위 가중치")


class AnalysisResult(Stock):
    type: Literal["web_search", "financial_statement", "technical_indicator"] = Field(
        description="분석 타입"
    )
    result: str = Field(description="분석 결과")


class MarketData(Stock):
    """시장 데이터"""

    returns: list[float] = Field(description="일별 수익률 리스트")


class InvestorView(BaseModel):
    """투자자 View (Black-Litterman 모델용)"""

    stock_indices: list[int] = Field(
        description="뷰가 적용되는 종목의 인덱스 (P 행렬 구성용)"
    )
    expected_return: float = Field(description="예상 초과 수익률 (Q 벡터)")
    confidence: float = Field(
        ge=0.0, le=1.0, description="뷰에 대한 신뢰도 (0~1, Omega 행렬 구성용)"
    )
    reasoning: str = Field(default="", description="투자 판단 근거")


class PortfolioWeight(Stock):
    """포트폴리오 비중"""

    weight: float = Field(ge=0.0, le=1.0, description="포트폴리오 내 비중 (0~1)")
    reasoning: str = Field(default="", description="투자 판단 근거")


class PortfolioMetrics(BaseModel):
    """포트폴리오 성과 지표"""

    expected_return: float = Field(description="연간 예상 수익률")
    volatility: float = Field(description="연간 변동성 (표준편차)")
    sharpe_ratio: float = Field(description="샤프 비율")


class PortfolioResult(BaseModel):
    """포트폴리오 최적화 결과"""

    weights: list[PortfolioWeight] = Field(description="종목별 최적 비중")
    metrics: PortfolioMetrics = Field(description="포트폴리오 성과 지표")


class OrderResult(BaseModel):
    """주문 결과"""

    code: str = Field(description="종목 코드")
    name: str = Field(description="종목명")
    quantity: int = Field(description="주문 수량")
    price: float = Field(description="주문 가격")
    status: str = Field(description="주문 상태 (success, failed)")
    message: str = Field(default="", description="주문 결과 메시지")


class TradingResult(BaseModel):
    """트레이딩 결과"""

    orders: list[OrderResult] = Field(description="주문 결과 리스트")
    total_cash: float = Field(description="사용 가능한 총 현금")
    used_cash: float = Field(description="실제 사용한 현금")


# ==================== 매수 워크플로우 State ====================


class BuyInputState(BaseModel):
    max_portfolio_size: int = Field(
        default=10, description="Maximum number of stocks in the portfolio"
    )
    rank_weight: RankWeight = Field(default_factory=RankWeight)
    portfolio_list: list[Stock] = Field(default_factory=list)
    risk_free_rate: float = Field(
        default=0.03, description="무위험 이자율 (연율, 기본값 3%)"
    )


class BuyPrivateState(BaseModel):
    analysis_results: Annotated[list[AnalysisResult], add_value] = Field(
        default_factory=list
    )
    market_data_list: list[MarketData] = Field(default_factory=list)
    investor_views: list[InvestorView] = Field(default_factory=list)
    stock_scores: dict[str, float] = Field(
        default_factory=dict, description="각 종목의 순위 점수 (종목코드 -> 점수)"
    )
    ranking_details: dict[str, list[Stock]] = Field(
        default_factory=dict, description="각 순위 함수별 상위 종목 리스트 (함수명 -> 종목 리스트)"
    )


class BuyOutputState(BaseModel):
    analysis_results: list[AnalysisResult] = Field(default_factory=list)
    portfolio_result: Optional[PortfolioResult] = Field(
        default=None, description="포트폴리오 최적화 결과"
    )
    trading_result: Optional[TradingResult] = Field(
        default=None, description="트레이딩 실행 결과"
    )


class BuyOverallState(BuyInputState, BuyPrivateState, BuyOutputState):
    pass


# ==================== 매도 워크플로우 State ====================


class HoldingStock(BaseModel):
    """보유 종목 정보"""

    code: str = Field(description="종목 코드")
    name: str = Field(description="종목명")
    quantity: int = Field(description="보유 수량")
    avg_buy_price: float = Field(description="평균 매입가")
    current_price: float = Field(description="현재가")
    return_rate: float = Field(description="수익률 (소수, 예: 0.15 = 15%)")
    evaluated_amount: float = Field(description="평가 금액")
    profit_loss: float = Field(description="평가 손익")


class SellDecision(BaseModel):
    """매도 결정 (전체 매도만 가능)"""

    code: str = Field(description="종목 코드")
    name: str = Field(description="종목명")
    reasoning: str = Field(description="매도 사유")


class SellResult(BaseModel):
    """매도 실행 결과"""

    orders: list[OrderResult] = Field(description="매도 주문 결과 리스트")
    total_evaluated_amount: float = Field(description="총 평가 금액")
    sold_amount: float = Field(description="매도한 금액")


class SellInputState(BaseModel):
    """매도 워크플로우 입력 상태"""

    loss_threshold: float = Field(
        default=-0.10, description="손실 매도 기준 (소수, 예: -0.10 = -10%)"
    )
    profit_threshold: float = Field(
        default=0.20, description="익절 매도 기준 (소수, 예: 0.20 = 20%)"
    )


class SellPrivateState(BaseModel):
    """매도 워크플로우 내부 상태"""

    holding_stocks: list[HoldingStock] = Field(
        default_factory=list, description="보유 종목 리스트"
    )
    analysis_results: Annotated[list[AnalysisResult], add_value] = Field(
        default_factory=list, description="종목별 분석 결과"
    )
    sell_decisions: list[SellDecision] = Field(
        default_factory=list, description="매도 결정 리스트"
    )


class SellOutputState(BaseModel):
    """매도 워크플로우 출력 상태"""

    holding_stocks: list[HoldingStock] = Field(
        default_factory=list, description="보유 종목 리스트"
    )
    analysis_results: list[AnalysisResult] = Field(
        default_factory=list, description="종목별 분석 결과"
    )
    sell_decisions: list[SellDecision] = Field(
        default_factory=list, description="매도 결정 리스트"
    )
    sell_result: Optional[SellResult] = Field(
        default=None, description="매도 실행 결과"
    )


class SellOverallState(SellInputState, SellPrivateState, SellOutputState):
    pass
