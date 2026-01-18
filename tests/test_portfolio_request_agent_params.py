from __future__ import annotations

import pytest

from stockelper_llm.agents.portfolio_request_agent import (
    build_portfolio_parameters_from_user_text,
)


@pytest.mark.asyncio
async def test_build_portfolio_parameters_fallback_all(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    q = "10개 종목 추천해줘. 웹검색 포함하고 무위험이자율 2%로 해줘"
    params = await build_portfolio_parameters_from_user_text(q)
    assert params.get("portfolio_size") == 10
    assert params.get("include_web_search") is True
    assert params.get("risk_free_rate") == pytest.approx(0.02, rel=0, abs=1e-12)


@pytest.mark.asyncio
async def test_build_portfolio_parameters_fallback_only_size(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    params = await build_portfolio_parameters_from_user_text("10개 종목 추천해줘")
    assert params == {"portfolio_size": 10}


@pytest.mark.asyncio
async def test_build_portfolio_parameters_fallback_websearch_false(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    params = await build_portfolio_parameters_from_user_text(
        "포트폴리오 추천해줘. 웹검색 제외"
    )
    assert params == {"include_web_search": False}


@pytest.mark.asyncio
async def test_build_portfolio_parameters_fallback_risk_free_rate_decimal(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    params = await build_portfolio_parameters_from_user_text(
        "포트폴리오 추천해줘. 무위험이자율 0.025로"
    )
    assert params == {"risk_free_rate": pytest.approx(0.025, rel=0, abs=1e-12)}


@pytest.mark.asyncio
async def test_build_portfolio_parameters_fallback_ignores_unrealistic_rf(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    params = await build_portfolio_parameters_from_user_text(
        "포트폴리오 추천해줘. 무위험이자율 50%로"
    )
    assert params == {}
