from __future__ import annotations

import asyncio
import os
from typing import Any

from stockelper_llm.agents.specialists import (
    build_fundamental_analysis_agent,
    build_graph_rag_agent,
    build_investment_strategy_agent,
    build_market_analysis_agent,
    build_technical_analysis_agent,
)
from stockelper_llm.agents.supervisor import SupervisorAgent

_CACHED_GRAPH: Any | None = None
_CACHE_LOCK = asyncio.Lock()


async def get_multi_agent(async_database_url: str):
    """멀티 에이전트 그래프를 생성/캐시합니다.

    - 하위 전문 에이전트: LangChain v1 create_agent 기반
    - 상위 Supervisor: LangGraph(StateGraph) 기반(레거시 I/O 및 interrupt/resume 유지)
    """
    global _CACHED_GRAPH
    if _CACHED_GRAPH is not None:
        return _CACHED_GRAPH

    if not async_database_url:
        raise RuntimeError("ASYNC_DATABASE_URL 이 설정되어 있지 않습니다.")

    async with _CACHE_LOCK:
        if _CACHED_GRAPH is not None:
            return _CACHED_GRAPH

        market_analysis_agent = build_market_analysis_agent()
        fundamental_analysis_agent = build_fundamental_analysis_agent()
        technical_analysis_agent = build_technical_analysis_agent(async_database_url)
        investment_strategy_agent = build_investment_strategy_agent(async_database_url)
        graph_rag_agent = build_graph_rag_agent()

        model = (
            os.getenv("STOCKELPER_LLM_MODEL")
            or os.getenv("STOCKELPER_MODEL")
            or "gpt-5.1"
        ).strip()

        graph = SupervisorAgent(
            model=model,
            agents=[
                market_analysis_agent,
                fundamental_analysis_agent,
                technical_analysis_agent,
                investment_strategy_agent,
                graph_rag_agent,
            ],
            checkpointer=None,
            async_database_url=async_database_url,
        )
        _CACHED_GRAPH = graph
        return graph
