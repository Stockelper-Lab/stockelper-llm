from __future__ import annotations

from routers.stock import (  # type: ignore[import-not-found]
    _extract_portfolio_size,
    _is_portfolio_recommendation_request,
)


def test_extract_portfolio_size_basic():
    assert _extract_portfolio_size("10개 종목 추천해줘") == 10
    assert _extract_portfolio_size("10종목 추천") == 10
    assert _extract_portfolio_size("  3 개  종목  추천  ") == 3


def test_extract_portfolio_size_none_when_missing():
    assert _extract_portfolio_size("") is None
    assert _extract_portfolio_size("포트폴리오 추천해줘") is None
    assert _extract_portfolio_size("뉴스 5개 추천해줘") == 5  # 숫자 자체는 추출됨


def test_is_portfolio_recommendation_request_with_count():
    q = "지금 내가 갖고 있는 종목을 기준으로 10개 종목을 추천해줘"
    assert _extract_portfolio_size(q) == 10
    assert _is_portfolio_recommendation_request(q) is True


