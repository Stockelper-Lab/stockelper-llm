import os
from .market_analysis_agent import agent as market_analysis_agent
from .fundamental_analysis_agent import agent as fundamental_analysis_agent
from .technical_analysis_agent import build_agent as build_technical_agent
from .investment_strategy_agent import build_agent as build_investment_agent
from .portfolio_analysis_agent import build_agent as build_portfolio_agent
from .supervisor_agent import SupervisorAgent

_CACHED_GRAPH = None


def get_multi_agent(async_database_url: str):
    global _CACHED_GRAPH
    if _CACHED_GRAPH is not None:
        return _CACHED_GRAPH

    if not async_database_url:
        raise RuntimeError("ASYNC_DATABASE_URL 이 설정되어 있지 않습니다.")

    technical_analysis_agent = build_technical_agent(async_database_url)
    investment_strategy_agent = build_investment_agent(async_database_url)
    portfolio_analysis_agent = build_portfolio_agent(async_database_url)
    
    graph = SupervisorAgent(
        model="gpt-4.1-mini",
        agents=[
            market_analysis_agent,
            fundamental_analysis_agent,
            technical_analysis_agent,
            investment_strategy_agent,
            portfolio_analysis_agent,
        ],
        checkpointer=None,
        async_database_url=async_database_url,
    )
    _CACHED_GRAPH = graph
    return graph
