from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain.tools import ToolRuntime, tool
from langchain_openai import ChatOpenAI
from langchain.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import create_async_engine

from stockelper_llm.agents.progress_middleware import make_progress_middleware
from stockelper_llm.agents.tool_error_middleware import ToolErrorMiddleware
from stockelper_llm.integrations.kis import (
    check_account_balance,
    get_current_price,
    get_user_kis_context,
    is_kis_token_expired_message,
    refresh_user_kis_access_token,
)
from stockelper_llm.integrations.neo4j_subgraph import (
    get_subgraph_by_company_name,
    get_subgraph_by_stock_code,
)


@dataclass(frozen=True)
class AgentContext:
    user_id: int
    thread_id: str


def _model_name(default: str = "gpt-5.1") -> str:
    return (os.getenv("STOCKELPER_LLM_MODEL") or os.getenv("STOCKELPER_MODEL") or default).strip()


async def _financial_knowledge_graph_analysis_impl(
    *,
    question: str,
    stock_code: str,
    stock_name: str | None,
    max_events: int,
    max_prices: int,
) -> dict | str:
    """GraphRAG(Neo4j) 조회 구현부(공유).

    - 현재 온톨로지(Company/Event/Document/StockPrice/Date)에 맞춰 조회
    - FE가 기대하는 subgraph 포맷({node, relation}) 포함
    """
    if not (os.getenv("NEO4J_URI") and os.getenv("NEO4J_USER") and os.getenv("NEO4J_PASSWORD")):
        return (
            "Neo4j 설정(NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD)이 없어 지식그래프를 조회할 수 없습니다.\n"
            "관리자에게 문의해주세요."
        )

    sc = (stock_code or "").strip()
    if sc.lower() == "none":
        sc = ""
    name = (stock_name or "").strip()
    if name.lower() == "none":
        name = ""

    subgraph: dict = {}
    if sc and sc.isdigit() and len(sc) == 6:
        subgraph = await asyncio.to_thread(
            get_subgraph_by_stock_code,
            sc,
            max_events=max_events,
            max_prices=max_prices,
        )
        if not subgraph and name:
            subgraph = await asyncio.to_thread(
                get_subgraph_by_company_name,
                name,
                max_events=max_events,
                max_prices=max_prices,
            )
    elif name:
        subgraph = await asyncio.to_thread(
            get_subgraph_by_company_name,
            name,
            max_events=max_events,
            max_prices=max_prices,
        )
    else:
        return "stock_code/stock_name 정보가 없어 지식그래프를 조회할 수 없습니다."

    if not subgraph:
        return "지식그래프에서 해당 종목 데이터를 찾지 못했습니다."

    nodes = list(subgraph.get("node") or [])
    relations = list(subgraph.get("relation") or [])

    node_by_name: dict[str, dict] = {
        str(n.get("node_name")): n
        for n in nodes
        if isinstance(n, dict) and n.get("node_name") is not None
    }

    company = next((n for n in nodes if isinstance(n, dict) and n.get("node_type") == "Company"), None)

    # Event -> Document 연결 매핑
    ev_to_docs: dict[str, list[dict]] = {}
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        if rel.get("relationship") != "REPORTED_BY":
            continue
        start = (rel.get("start") or {}).get("name")
        end = (rel.get("end") or {}).get("name")
        if not (start and end):
            continue
        doc_node = node_by_name.get(str(end))
        if not doc_node:
            continue
        ev_to_docs.setdefault(str(start), []).append(doc_node)

    events: list[dict] = []
    for n in nodes:
        if not (isinstance(n, dict) and n.get("node_type") == "Event"):
            continue
        props = n.get("properties") or {}
        docs = ev_to_docs.get(str(n.get("node_name")), [])
        events.append(
            {
                "event_id": props.get("event_id"),
                "disclosure_name": props.get("disclosure_name"),
                "disclosure_category": props.get("disclosure_category"),
                "report_type": props.get("report_type"),
                "disclosure_type_code": props.get("disclosure_type_code"),
                "source": props.get("source"),
                "updated_at": props.get("updated_at"),
                "documents": [
                    {
                        "rcept_no": (d.get("properties") or {}).get("rcept_no"),
                        "report_nm": (d.get("properties") or {}).get("report_nm"),
                        "rcept_dt": (d.get("properties") or {}).get("rcept_dt"),
                        "url": (d.get("properties") or {}).get("url"),
                    }
                    for d in docs
                    if isinstance(d, dict)
                ],
            }
        )

    # 최신순 정렬(ISO string 기대)
    def _sort_key(ev: dict) -> str:
        v = ev.get("updated_at")
        return str(v or "")

    events.sort(key=_sort_key, reverse=True)

    prices: list[dict] = []
    for n in nodes:
        if not (isinstance(n, dict) and n.get("node_type") == "StockPrice"):
            continue
        props = n.get("properties") or {}
        prices.append(
            {
                "traded_at": props.get("traded_at"),
                "stck_prpr": props.get("stck_prpr"),
                "stck_oprc": props.get("stck_oprc"),
                "stck_hgpr": props.get("stck_hgpr"),
                "stck_lwpr": props.get("stck_lwpr"),
                "volume": props.get("volume"),
            }
        )

    # traded_at 최신순(문자열 정렬)
    prices.sort(key=lambda p: str(p.get("traded_at") or ""), reverse=True)

    return {
        "question": question,
        "company": (company.get("properties") if isinstance(company, dict) else None),
        "events": events[: max(0, int(max_events))],
        "prices": prices[: max(0, int(max_prices))],
        "subgraph": subgraph,
    }


def build_market_analysis_agent(*, extra_tools: list[Any] | None = None):
    """시장 분석 에이전트 (create_agent 기반)."""
    extra_tools = list(extra_tools or [])

    @tool
    async def search_news(query: str, runtime: ToolRuntime[AgentContext]) -> str:
        """OpenAI Web Search Tool로 최신 뉴스/소식을 검색해 요약합니다.

        참고(개념): https://docs.langchain.com/oss/javascript/integrations/tools/openai#web-search-tool
        """
        if not os.getenv("OPENAI_API_KEY"):
            return "OPENAI_API_KEY가 설정되어 있지 않아 Web Search를 사용할 수 없습니다."

        # OpenAI Responses API의 built-in web search tool을 바인딩해 최신 정보를 가져옵니다.
        # (LangChain.js에서는 tools.webSearch()로 제공되며, Python에서는 dict tool 정의를 bind_tools로 전달합니다.)
        llm = ChatOpenAI(
            model=_model_name(),
            temperature=0,
            max_completion_tokens=900,
            use_responses_api=True,
        ).bind_tools([{"type": "web_search_preview"}])

        system = SystemMessage(
            content=(
                "당신은 주식/기업 뉴스 리서처입니다.\n"
                "반드시 Web Search tool을 사용해 최신 정보를 찾고, 그 결과만 근거로 답하세요.\n"
                "출력 형식:\n"
                "- 핵심 요약(3~6줄)\n"
                "- 주요 기사/소식 3~7개: 제목 + (가능하면 날짜/매체) + URL\n"
                "- '투자 판단'이 아니라 '사실 요약' 중심\n"
                "응답 언어: 한국어"
            )
        )
        user = HumanMessage(
            content=(
                f"'{query}' 관련 최신 뉴스/소식을 웹에서 찾아 요약해줘.\n"
                "가능하면 한국/국내 기사도 포함해줘."
            )
        )

        resp = await llm.ainvoke([system, user])
        return str(getattr(resp, "content", "") or "")

    tools = [search_news] + extra_tools

    agent = create_agent(
        model=_model_name(),
        tools=tools,
        system_prompt=(
            "You are a professional market analyst specializing in analyzing company market conditions.\n"
            "Your role is to respond to user requests strictly based on the results from available tools.\n"
            "If tools are unavailable, clearly explain what configuration is missing.\n"
            "If the user asks for news/latest updates, you MUST call search_news first.\n"
            "응답 언어: 한국어"
        ),
        middleware=[
            *make_progress_middleware("MarketAnalysisAgent"),
            ToolCallLimitMiddleware(thread_limit=20, run_limit=10),
            ToolErrorMiddleware(),
            ToolRetryMiddleware(max_retries=2, tools=[t.name for t in tools]),
            # NOTE: LangChain v1 SummarizationMiddleware의 trigger는 (kind, value) 튜플 형태를 사용합니다.
            SummarizationMiddleware(
                model=_model_name(default="gpt-5.1"),
                trigger=("tokens", 8000),
                keep=("messages", 20),
            ),
        ],
        context_schema=AgentContext,
    )
    agent.name = "MarketAnalysisAgent"
    return agent


def build_fundamental_analysis_agent(*, extra_tools: list[Any] | None = None):
    """기본적 분석 에이전트."""
    extra_tools = list(extra_tools or [])

    @tool
    def analyze_financial_statement(stock_name: str, runtime: ToolRuntime[AgentContext]) -> str:
        """재무제표/공시 기반 기본적 분석을 수행합니다. (예시 구현)"""
        return (
            "재무제표 분석 도구는 현재 예시 구현입니다.\n"
            "OPEN_DART_API_KEY 및 DART/재무제표 분석 로직을 연결해 확장하세요."
        )

    tools = [analyze_financial_statement] + extra_tools

    agent = create_agent(
        model=_model_name(),
        tools=tools,
        system_prompt=(
            "You are a professional fundamental analysis expert specializing in evaluating the intrinsic value of companies.\n"
            "Respond strictly based on tool outputs.\n"
            "응답 언어: 한국어"
        ),
        middleware=[
            *make_progress_middleware("FundamentalAnalysisAgent"),
            ToolCallLimitMiddleware(thread_limit=20, run_limit=10),
            ToolErrorMiddleware(),
            ToolRetryMiddleware(max_retries=2, tools=[t.name for t in tools]),
        ],
        context_schema=AgentContext,
    )
    agent.name = "FundamentalAnalysisAgent"
    return agent


def build_technical_analysis_agent(async_database_url: str, *, extra_tools: list[Any] | None = None):
    """기술적 분석 에이전트."""
    extra_tools = list(extra_tools or [])
    async_engine = create_async_engine(async_database_url, echo=False)

    @tool
    async def analysis_stock(stock_code: str, runtime: ToolRuntime[AgentContext]) -> dict:
        """주가/시세/현재가 등을 조회합니다. (KIS 현재가 조회)"""
        user_id = runtime.context.user_id
        return await get_current_price(async_engine, user_id, stock_code)

    tools = [analysis_stock] + extra_tools

    agent = create_agent(
        model=_model_name(),
        tools=tools,
        system_prompt=(
            "당신은 주식 기술적 분석 전문가입니다.\n"
            "중요: 답변은 반드시 도구 결과 기반으로만 작성하세요.\n"
            "가격/현재가/시세 요청이면 analysis_stock 도구를 반드시 1회 호출해 현재가를 확인한 뒤 답하세요.\n"
            "응답 언어: 한국어"
        ),
        middleware=[
            *make_progress_middleware("TechnicalAnalysisAgent"),
            ToolCallLimitMiddleware(thread_limit=20, run_limit=10),
            ToolErrorMiddleware(),
            ToolRetryMiddleware(max_retries=2, tools=[t.name for t in tools]),
        ],
        context_schema=AgentContext,
    )
    agent.name = "TechnicalAnalysisAgent"
    return agent


def build_investment_strategy_agent(async_database_url: str, *, extra_tools: list[Any] | None = None):
    """투자전략 에이전트.

    - 이번 프로젝트에서는 **실거래 주문을 실행하지 않습니다.**
    - 대신, 전문가 관점의 '규칙 기반/검증/리스크 통제' 투자전략을 제시합니다.
    - 필요 시 다른 에이전트급 도구(현재가/뉴스/지식그래프)를 직접 호출해 근거를 확보합니다.
    """
    extra_tools = list(extra_tools or [])
    async_engine = create_async_engine(async_database_url, echo=False)

    @tool
    async def get_account_info(runtime: ToolRuntime[AgentContext]) -> dict | str:
        """사용자 계좌의 예수금(cash)과 총평가(total_eval)를 조회합니다."""
        user_id = runtime.context.user_id
        user_info = await get_user_kis_context(async_engine, user_id, require=False)
        if not user_info:
            return "There is no account information available."

        account_info = await check_account_balance(
            user_info["kis_app_key"],
            user_info["kis_app_secret"],
            user_info["kis_access_token"],
            user_info["account_no"],
        )

        if isinstance(account_info, str) and is_kis_token_expired_message(account_info):
            new_token = await refresh_user_kis_access_token(async_engine, user_id, user_info)
            user_info["kis_access_token"] = new_token
            account_info = await check_account_balance(
                user_info["kis_app_key"],
                user_info["kis_app_secret"],
                user_info["kis_access_token"],
                user_info["account_no"],
            )

        return account_info or "There is no account information available."

    @tool
    async def analysis_stock(stock_code: str, runtime: ToolRuntime[AgentContext]) -> dict:
        """(재사용) 현재가/시세/가격 조회 (KIS)."""
        user_id = runtime.context.user_id
        return await get_current_price(async_engine, user_id, stock_code)

    @tool
    async def search_news(query: str, runtime: ToolRuntime[AgentContext]) -> str:
        """(재사용) OpenAI Web Search Tool로 최신 뉴스/소식을 검색해 요약합니다.

        참고(개념): https://docs.langchain.com/oss/javascript/integrations/tools/openai#web-search-tool
        """
        if not os.getenv("OPENAI_API_KEY"):
            return "OPENAI_API_KEY가 설정되어 있지 않아 Web Search를 사용할 수 없습니다."

        llm = ChatOpenAI(
            model=_model_name(),
            temperature=0,
            max_completion_tokens=900,
            use_responses_api=True,
        ).bind_tools([{"type": "web_search_preview"}])

        system = SystemMessage(
            content=(
                "당신은 주식/기업 뉴스 리서처입니다.\n"
                "반드시 Web Search tool을 사용해 최신 정보를 찾고, 그 결과만 근거로 답하세요.\n"
                "출력 형식:\n"
                "- 핵심 요약(3~6줄)\n"
                "- 주요 기사/소식 3~7개: 제목 + (가능하면 날짜/매체) + URL\n"
                "- '투자 판단'이 아니라 '사실 요약' 중심\n"
                "응답 언어: 한국어"
            )
        )
        user = HumanMessage(
            content=(
                f"'{query}' 관련 최신 뉴스/소식을 웹에서 찾아 요약해줘.\n"
                "가능하면 한국/국내 기사도 포함해줘."
            )
        )

        resp = await llm.ainvoke([system, user])
        return str(getattr(resp, "content", "") or "")

    @tool
    async def financial_knowledge_graph_analysis(
        question: str,
        stock_code: str,
        runtime: ToolRuntime[AgentContext],
        stock_name: str | None = None,
        max_events: int = 10,
        max_prices: int = 20,
    ) -> dict | str:
        """(재사용) 금융 지식그래프(Neo4j)에서 종목 관련 서브그래프/근거를 조회합니다."""
        return await _financial_knowledge_graph_analysis_impl(
            question=question,
            stock_code=stock_code,
            stock_name=stock_name,
            max_events=max_events,
            max_prices=max_prices,
        )

    tools = [get_account_info, analysis_stock, search_news, financial_knowledge_graph_analysis] + extra_tools

    agent = create_agent(
        model=_model_name(),
        tools=tools,
        system_prompt=(
            "당신은 항상 (+) 수익률을 '보장'한다고 말하지 않는, 실적 좋은 주식투자 전문가입니다.\n"
            "중요: “항상 +수익률”은 현실적으로 보장할 수 없습니다. 다만 장기적으로 일관된 "
            "‘플러스 기대수익(positive expected value)’과 ‘리스크 조정 수익률’의 극대화를 목표로 합니다.\n\n"
            "따라서 답변은 감(感)이 아니라 **규칙·검증·리스크 통제** 중심으로 구성해야 합니다.\n"
            "가능하면 아래 도구로 근거를 확보하세요:\n"
            "- analysis_stock: 현재가/시세(가능하면 1회)\n"
            "- search_news: 최신 뉴스/이슈(필요 시)\n"
            "- financial_knowledge_graph_analysis: 공시 이벤트/문서/근거 URL 및 타임라인(필요 시)\n"
            "- get_account_info: 사용자 예수금/총평가(요청/필요 시에만)\n\n"
            "출력 형식(항상 이 순서를 지키세요):\n"
            "0) 전제/면책(“항상 +수익률 불가” 문장을 반드시 포함)\n"
            "1) 목표를 숫자로 고정: 수익률보다 손실 한도(MDD/Vol/손실확률)\n"
            "2) 엣지(Edge) 1개 정의(팩터/이벤트/구조/행동 중 택1~2, 과최적화 경계)\n"
            "3) 매매 규칙을 재현 가능 문장으로(Entry/Exit/Manage/Guardrails)\n"
            "4) 리스크 관리 핵심: 포지션 사이징(단일/섹터 상한, 변동성 기반, 상관관리, 포트폴리오 손실 제한)\n"
            "5) 포트폴리오 구성: 코어-새틀라이트 + 리밸런싱 규칙\n"
            "6) 검증: 워크포워드/스트레스/비용 포함/파라미터 최소화\n"
            "7) 실행 규율: 주문/유동성/회전율/데이터 품질\n"
            "8) 운영: 전략 포트폴리오(상관 낮은 2~4개, 위험예산 재배분)\n"
            "9) 금지 규칙(레버리지 몰빵/복수매매/근거없는 확신/즉흥 룰변경 금지)\n\n"
            "추가로, 사용자가 특정 종목/기간을 언급하면 마지막에:\n"
            "10) (해당 종목 적용) 위 1~9를 그 종목에 적용한 구체안(가능하면 도구 근거 + URL 포함)\n\n"
            "주의: 이번 프로젝트에서는 주문 실행/자동매매를 하지 않습니다. "
            "구체 주문(매수/매도/수량/가격)은 '추천'으로만 표현하고 실행을 전제로 말하지 마세요.\n"
            "응답 언어: 한국어"
        ),
        middleware=[
            *make_progress_middleware("InvestmentStrategyAgent"),
            ToolCallLimitMiddleware(thread_limit=20, run_limit=10),
            ToolErrorMiddleware(),
            ToolRetryMiddleware(max_retries=2, tools=[t.name for t in tools]),
            SummarizationMiddleware(
                model=_model_name(default="gpt-5.1"),
                trigger=("tokens", 8000),
                keep=("messages", 20),
            ),
        ],
        context_schema=AgentContext,
    )
    agent.name = "InvestmentStrategyAgent"
    return agent


def build_graph_rag_agent(*, extra_tools: list[Any] | None = None):
    """지식그래프(Neo4j) 기반 GraphRAG 에이전트.

    - 현재 온톨로지(Company/Event/Document/StockPrice/Date)에 맞춰 조회
    - 답변은 반드시 그래프에서 가져온 근거(URL 포함) 기반으로 작성
    """
    extra_tools = list(extra_tools or [])

    @tool
    async def financial_knowledge_graph_analysis(
        question: str,
        stock_code: str,
        runtime: ToolRuntime[AgentContext],
        stock_name: str | None = None,
        max_events: int = 10,
        max_prices: int = 20,
    ) -> dict | str:
        """금융 지식그래프(Neo4j)에서 종목 관련 서브그래프/근거를 조회합니다."""
        return await _financial_knowledge_graph_analysis_impl(
            question=question,
            stock_code=stock_code,
            stock_name=stock_name,
            max_events=max_events,
            max_prices=max_prices,
        )

    tools = [financial_knowledge_graph_analysis] + extra_tools

    agent = create_agent(
        model=_model_name(),
        tools=tools,
        system_prompt=(
            "당신은 금융 지식그래프(Neo4j) 기반 GraphRAG 분석가입니다.\n"
            "원칙:\n"
            "- 입력에 <stock_code>/<stock_name> 태그가 포함되어 있으면 그 값을 그대로 tool 인자로 사용하세요.\n"
            "- 답변 전에 반드시 financial_knowledge_graph_analysis 도구를 1회 이상 호출해 근거를 수집하세요.\n"
            "- 답변은 도구 결과에 포함된 facts/events/prices/documents만 근거로 작성하세요.\n"
            "- Document.url이 있으면 답변에 반드시 URL을 포함하세요.\n"
            "응답 언어: 한국어"
        ),
        middleware=[
            *make_progress_middleware("GraphRAGAgent"),
            ToolCallLimitMiddleware(thread_limit=20, run_limit=10),
            ToolErrorMiddleware(),
            ToolRetryMiddleware(max_retries=2, tools=[t.name for t in tools]),
            SummarizationMiddleware(
                model=_model_name(default="gpt-5.1"),
                trigger=("tokens", 8000),
                keep=("messages", 20),
            ),
        ],
        context_schema=AgentContext,
    )
    agent.name = "GraphRAGAgent"
    return agent

