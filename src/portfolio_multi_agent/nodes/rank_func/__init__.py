"""
한국투자증권 순위 API 함수 모음

이 패키지는 한국투자증권 API를 사용하여 다양한 지표별 주식 순위를 조회하는 함수들을 제공합니다.
모든 함수는 상위 N개 종목의 코드를 리스트로 반환합니다.

사용 예시:
    from rank_func import get_volume_rank, get_market_cap_rank

    # 거래량 상위 10개 종목
    volume_top = get_volume_rank(top_n=10)

    # 시가총액 상위 20개 종목
    market_cap_top = get_market_cap_rank(top_n=20)
"""

# 수익자산지표 관련
from .get_operating_profit_rank import get_operating_profit_rank
from .get_net_income_rank import get_net_income_rank
from .get_total_liabilities_rank import get_total_liabilities_rank

# 등락률 관련
from .get_rise_rate_rank import get_rise_rate_rank
from .get_fall_rate_rank import get_fall_rate_rank

# 재무비율 관련
from .get_profitability_rank import get_profitability_rank
from .get_stability_rank import get_stability_rank
from .get_growth_rank import get_growth_rank
from .get_activity_rank import get_activity_rank

# 기타
from .get_volume_rank import get_volume_rank
from .get_market_cap_rank import get_market_cap_rank

__all__ = [
    # 수익자산지표 관련
    "get_operating_profit_rank",  # 영업이익 순위
    "get_net_income_rank",  # 당기순이익 순위
    "get_total_liabilities_rank",  # 부채총계 순위
    # 등락률 관련
    "get_rise_rate_rank",  # 상승률 순위
    "get_fall_rate_rank",  # 하락률 순위
    # 재무비율 관련
    "get_profitability_rank",  # 수익성 분석 순위
    "get_stability_rank",  # 안정성 분석 순위
    "get_growth_rank",  # 성장성 분석 순위
    "get_activity_rank",  # 활동성 분석 순위
    # 기타
    "get_volume_rank",  # 거래량 순위
    "get_market_cap_rank",  # 시가총액 순위
]

__version__ = "1.0.0"
