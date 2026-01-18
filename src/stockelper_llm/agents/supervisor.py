from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Annotated, List, Optional

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph
from langgraph.types import Command, RunnableConfig, interrupt
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import create_async_engine

from stockelper_llm.core.langchain_compat import message_to_text
from stockelper_llm.integrations.kis import (
    get_user_kis_context,
    is_kis_token_expired_message,
    place_order,
    refresh_user_kis_access_token,
)
from stockelper_llm.integrations.neo4j_subgraph import (
    get_subgraph_by_company_name,
    get_subgraph_by_stock_code,
)
from stockelper_llm.integrations.stock_listing import (
    find_similar_companies,
    lookup_stock_code,
)

logger = logging.getLogger(__name__)


_PRICE_REQUEST_PAT = re.compile(r"(주가|가격|현재가|시세|주식\s*가격)", re.IGNORECASE)
_NEWS_REQUEST_PAT = re.compile(
    r"(뉴스|최신|최근\s*소식|소식|이슈|기사|호재|악재)", re.IGNORECASE
)


def _is_price_request(text: str) -> bool:
    return bool(_PRICE_REQUEST_PAT.search(text or ""))


def _is_news_request(text: str) -> bool:
    return bool(_NEWS_REQUEST_PAT.search(text or ""))


def _latest_agent_result(state: "State", target: str) -> str | None:
    for r in reversed(state.agent_results or []):
        if isinstance(r, dict) and r.get("target") == target and r.get("result"):
            return str(r["result"])
    return None


SYSTEM_TEMPLATE = """As the Supervisor Agent, you must decide whether to respond directly to the user or delegate the request to one or more of the following agents: MarketAnalysisAgent, FundamentalAnalysisAgent, TechnicalAnalysisAgent, or InvestmentStrategyAgent.
You may also delegate to GraphRAGAgent when graph-based evidence (events/documents/relationships) is needed.

Refer to each agent’s “when to make the request” condition, and if the current situation matches, send the appropriate request to those agents.

However, if the information inside the <agent_analysis_result> tag is sufficient to answer the user’s request, respond to the user based on that information.

If the user's request is for the company’s investment strategy recommendation, **you must first check whether all of the following agents have provided analysis results in the <agent_analysis_result> tag: MarketAnalysisAgent, FundamentalAnalysisAgent, and TechnicalAnalysisAgent.**
- If any of these agents’ analysis results are missing, first send requests to the missing agents before calling the InvestmentStrategyAgent.
- Only call the InvestmentStrategyAgent when all three analysis results are present in the <agent_analysis_result> tag.

IMPORTANT: Portfolio recommendations MUST NOT be executed in the chat interface. If the user asks for portfolio recommendations, respond to the user that this feature is available on the dedicated portfolio recommendation page, and do not call any portfolio agent/tools here.

If none of the conditions match the current situation, respond to the user directly.

<Agent_Descriptions>
[
  {
    "name": "MarketAnalysisAgent",
    "description": "Corporate market analysis expert",
    "when to make the request": [
      "When the user’s request is about company market analysis."
    ]
  },
  {
    "name": "FundamentalAnalysisAgent",
    "description": "Corporate fundamental analysis expert",
    "when to make the request": [
      "When the user’s request is about company fundamental analysis."
    ]
  },
  {
    "name": "TechnicalAnalysisAgent",
    "description": "Corporate technical analysis expert",
    "when to make the request": [
      "When the user’s request is about company technical analysis or price request."
    ]
  },
  {
    "name": "InvestmentStrategyAgent",
    "description": "Creates a comprehensive investment strategy report based on analysis data.",
    "when to make the request": [
      "When the user’s request is for investment strategy recommendation AND prerequisite agent results exist."
    ]
  },
  {
    "name": "GraphRAGAgent",
    "description": "GraphRAG expert that uses the Neo4j financial knowledge graph for evidence-backed answers (events, documents, relationships, timelines).",
    "when to make the request": [
      "When the user asks for reasons/causes, timelines, disclosure/event summaries, evidence URLs, or relationship/graph-based explanations."
    ]
  }
]
</Agent_Descriptions>
"""


TRADING_SYSTEM_TEMPLATE = """Please extract only the trading strategy from section 6. Trade Execution Recommendation of the given investment report.

<Stock_Code>
{stock_code}
</Stock_Code>
"""


STOCK_NAME_USER_TEMPLATE = """Please extract the stock name from the user's request. if the user's request is not related to a stock, return "None".

<User_Request>
{user_request}
</User_Request>
"""


STOCK_CODE_USER_TEMPLATE = """Please select the Stock Code corresponding to the given Stock Name from the list of Stock_Codes. If it does not exist, return “None”.

<Stock_Name>
{stock_name}
</Stock_Name>

<Stock_Codes>
{stock_codes}
</Stock_Codes>
"""


class Router(BaseModel):
    target: str = Field(
        description="Target: 'User' or MarketAnalysisAgent/FundamentalAnalysisAgent/TechnicalAnalysisAgent/InvestmentStrategyAgent/GraphRAGAgent"
    )
    message: str = Field(description="Message in korean to be sent to the target")


class RouterList(BaseModel):
    routers: List[Router] = Field(description="List of one or more routers")


class StockName(BaseModel):
    stock_name: str = Field(description="The name of the stock or None")


class StockCode(BaseModel):
    stock_code: str = Field(description="The code of the stock or None")


class TradingAction(BaseModel):
    stock_code: str = Field(description="6-digit stock code")
    order_side: str = Field(description="buy or sell")
    order_type: str = Field(description="market or limit")
    order_price: Optional[float] = Field(description="limit price, else None")
    order_quantity: int = Field(description="quantity")


def _truncate_agent_results(existing: list, update: list):
    return update[-10:]


def _add_messages(existing: list, update: list):
    for message in update:
        # LangChain 메시지 객체(내부 구현체와 무관하게 duck-typing으로 처리)
        msg_type = getattr(message, "type", None)
        msg_content = getattr(message, "content", None)
        if isinstance(msg_type, str) and msg_content is not None:
            existing.append(message)
            continue

        if isinstance(message, dict):
            role = (message.get("role") or message.get("type") or "").lower()
            content = message.get("content") or ""
            if role in {"user", "human"}:
                existing.append(HumanMessage(content=content))
            elif role in {"assistant", "ai"}:
                existing.append(AIMessage(content=content))
            else:
                # 알 수 없는 role은 무시
                continue
            continue

        # 그 외 타입은 문자열로 강등
        existing.append(HumanMessage(content=str(message)))

    return existing[-10:]


@dataclass
class State:
    messages: Annotated[list, _add_messages] = field(default_factory=list)
    agent_messages: list = field(default_factory=list)
    agent_results: Annotated[list, _truncate_agent_results] = field(
        default_factory=list
    )
    execute_agent_count: int = field(default=0)
    trading_action: dict = field(default_factory=dict)
    stock_name: str = field(default="None")
    stock_code: str = field(default="None")
    subgraph: dict = field(default_factory=dict)


@dataclass
class Config:
    user_id: int = field(default=1)
    max_execute_agent_count: int = field(default=3)


class SupervisorAgent:
    """레거시 SupervisorGraph를 유지하되, 하위 전문 에이전트는 LangChain v1 create_agent로 교체."""

    def __new__(cls, model: str, agents: list, checkpointer, async_database_url: str):
        instance = super().__new__(cls)
        instance.__init__(model, agents, checkpointer, async_database_url)
        return instance.graph

    def __init__(self, model: str, agents: list, checkpointer, async_database_url: str):
        self.async_engine = create_async_engine(async_database_url, echo=False)
        self.llm = ChatOpenAI(model=model)
        self.llm_with_router = self.llm.with_structured_output(RouterList)
        self.llm_with_trading = self.llm.with_structured_output(TradingAction)
        self.llm_with_stock_name = self.llm.with_structured_output(StockName)
        self.llm_with_stock_code = self.llm.with_structured_output(StockCode)

        self.agents_by_name = {
            getattr(agent, "name", None) or getattr(agent, "graph", agent).name: agent
            for agent in agents
        }

        wf = StateGraph(State)
        wf.add_node("supervisor", self.supervisor)
        wf.add_node("execute_agent", self.execute_agent)
        wf.add_node("execute_trading", self.execute_trading)
        wf.add_edge("__start__", "supervisor")

        self.graph = wf.compile(checkpointer=checkpointer)
        self.graph.name = "stockelper"

    async def supervisor(self, state: State, config: RunnableConfig):
        writer = get_stream_writer()
        writer({"step": "supervisor", "status": "start"})

        if (
            state.agent_results
            and state.execute_agent_count > 0
            and state.agent_results[-1].get("target") == "InvestmentStrategyAgent"
        ):
            update, goto = await self.trading(state, config)
        else:
            update, goto = await self.routing(state, config)

        writer({"step": "supervisor", "status": "end"})
        return Command(update=update, goto=goto)

    async def execute_agent(self, state: State, config: RunnableConfig):
        writer = get_stream_writer()

        user_id = config.get("configurable", {}).get("user_id", 1)
        thread_id = config.get("configurable", {}).get("thread_id", "thread")

        # lazy import to avoid circular
        from stockelper_llm.agents.specialists import AgentContext

        ctx = AgentContext(user_id=user_id, thread_id=thread_id)

        async def stream_single_agent(router: dict):
            target = router["target"]
            content = f"<user>\n{router['message']}\n</user>\n"
            if state.stock_name != "None":
                content += f"\n<stock_name>\n{state.stock_name}\n</stock_name>\n"
            if state.stock_code != "None":
                content += f"\n<stock_code>\n{state.stock_code}\n</stock_code>\n"
            if state.agent_results:
                agent_results_str = json.dumps(
                    state.agent_results, indent=2, ensure_ascii=False
                )
                content += f"\n<agent_analysis_result>\n{agent_results_str}\n</agent_analysis_result>\n"

            input_data = {"messages": [HumanMessage(content=content)]}

            final_state = None
            agent = self.agents_by_name[target]
            async for response_type, response in agent.astream(
                input_data,
                stream_mode=["custom", "values"],
                context=ctx,
            ):
                if response_type == "custom":
                    # 하위 에이전트의 custom(progress) 이벤트를 상위로 전달
                    writer(response)
                elif response_type == "values":
                    final_state = response

            return router, final_state or {}

        tasks = [stream_single_agent(router) for router in state.agent_messages]
        results = await asyncio.gather(*tasks)

        agent_results: list[dict] = []
        extracted_subgraph: dict = {}

        for router, result in results:
            last_msg = (
                result.get("messages", [])[-1] if result.get("messages") else None
            )
            result_text = message_to_text(last_msg)
            agent_results.append(router | {"result": result_text})

            # GraphRAGAgent 결과에서 subgraph 추출
            if router.get("target") == "GraphRAGAgent" and result_text:
                extracted = self._extract_subgraph_from_agent_result(
                    result, result_text
                )
                if extracted:
                    extracted_subgraph = extracted

        # 기존 subgraph와 병합 (새로 추출된 것이 더 풍부하면 대체)
        new_subgraph = state.subgraph if isinstance(state.subgraph, dict) else {}
        if extracted_subgraph:
            existing_nodes = len((new_subgraph or {}).get("node", []))
            new_nodes = len(extracted_subgraph.get("node", []))
            if new_nodes > existing_nodes:
                new_subgraph = extracted_subgraph

        update = {
            "agent_messages": [],
            "agent_results": state.agent_results + agent_results,
            "execute_agent_count": state.execute_agent_count + 1,
            "subgraph": new_subgraph,
        }
        return Command(update=update, goto="supervisor")

    def _extract_subgraph_from_agent_result(
        self, result: dict, result_text: str
    ) -> dict | None:
        """GraphRAGAgent 결과에서 subgraph를 추출합니다.

        1. 메시지에서 <subgraph>...</subgraph> 태그 파싱
        2. tool_calls 결과에서 subgraph 추출
        """
        # 방법 1: 메시지에서 subgraph JSON 태그 파싱
        subgraph_match = re.search(r"<subgraph>([\s\S]*?)</subgraph>", result_text)
        if subgraph_match:
            try:
                return json.loads(subgraph_match.group(1))
            except Exception:
                pass

        # 방법 2: 도구 호출 결과에서 subgraph 추출 (메시지 히스토리 탐색)
        messages = result.get("messages", [])
        for msg in reversed(messages):
            # ToolMessage의 content에서 subgraph 추출 시도
            content = getattr(msg, "content", None)
            if not content:
                continue

            if isinstance(content, str):
                # JSON 형식의 도구 결과
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and "subgraph" in parsed:
                        return parsed["subgraph"]
                except Exception:
                    pass

            elif isinstance(content, dict) and "subgraph" in content:
                return content["subgraph"]

        return None

    async def execute_trading(self, state: State, config: RunnableConfig):
        human_check = interrupt("interrupt")

        if human_check:
            user_id = config.get("configurable", {}).get("user_id", 1)
            user_info = await get_user_kis_context(
                self.async_engine, user_id, require=False
            )
            if user_info:
                kwargs = state.trading_action | user_info
                trading_result = place_order(**kwargs)

                if isinstance(trading_result, str) and is_kis_token_expired_message(
                    trading_result
                ):
                    user_info["kis_access_token"] = await refresh_user_kis_access_token(
                        self.async_engine, user_id, user_info
                    )
                    kwargs["kis_access_token"] = user_info["kis_access_token"]
                    trading_result = place_order(**kwargs)
            else:
                trading_result = "계좌정보가 없습니다."

            update = State(
                messages=[AIMessage(content=str(trading_result))],
                agent_results=[],
                stock_name=state.stock_name,
                stock_code=state.stock_code,
                subgraph=state.subgraph,
            )
            goto = "__end__"
        else:
            update = State(
                messages=[AIMessage(content="주문을 취소합니다.")],
                agent_results=state.agent_results,
                stock_name=state.stock_name,
                stock_code=state.stock_code,
                subgraph=state.subgraph,
            )
            goto = "__end__"

        return Command(update=update, goto=goto)

    async def get_stock_name_code_by_query_subgraph(
        self,
        query: str,
        *,
        include_subgraph: bool = True,
    ):
        resp = await self.llm_with_stock_name.ainvoke(
            [HumanMessage(content=STOCK_NAME_USER_TEMPLATE.format(user_request=query))],
        )
        stock_name = resp.stock_name
        stock_code = "None"
        subgraph: dict | str = "None"

        if stock_name != "None":
            exact = lookup_stock_code((stock_name or "").strip())
            if exact:
                stock_code = exact
            else:
                candidates = find_similar_companies(company_name=stock_name, top_n=10)
                if candidates:
                    resp2 = await self.llm_with_stock_code.ainvoke(
                        [
                            HumanMessage(
                                content=STOCK_CODE_USER_TEMPLATE.format(
                                    stock_name=stock_name, stock_codes=candidates
                                )
                            )
                        ],
                    )
                    stock_code = resp2.stock_code
                else:
                    fallback_prompt = (
                        "Please return the 6-digit KRX stock code for the given Stock Name. "
                        'If unknown, return "None".\n\n'
                        "<Stock_Name>\n"
                        f"{stock_name}\n"
                        "</Stock_Name>\n"
                    )
                    resp2 = await self.llm_with_stock_code.ainvoke(
                        [HumanMessage(content=fallback_prompt)],
                    )
                    stock_code = resp2.stock_code

            if not (
                isinstance(stock_code, str)
                and stock_code.isdigit()
                and len(stock_code) == 6
            ):
                stock_code = "None"

            if include_subgraph:
                try:
                    # NOTE: Neo4j 드라이버는 sync이므로 event-loop 블로킹을 피하기 위해 thread로 실행합니다.
                    if (
                        isinstance(stock_code, str)
                        and stock_code.isdigit()
                        and len(stock_code) == 6
                    ):
                        subgraph = await asyncio.to_thread(
                            get_subgraph_by_stock_code,
                            stock_code,
                            max_events=10,
                            max_prices=20,
                        )
                        # 코드 매칭이 실패하면 이름(corp_name)으로 1회 더 시도
                        if not subgraph:
                            subgraph = await asyncio.to_thread(
                                get_subgraph_by_company_name,
                                stock_name,
                                max_events=10,
                                max_prices=20,
                            )
                    else:
                        subgraph = await asyncio.to_thread(
                            get_subgraph_by_company_name,
                            stock_name,
                            max_events=10,
                            max_prices=20,
                        )
                except Exception:
                    subgraph = "None"

        return {
            "stock_name": stock_name,
            "stock_code": stock_code,
            "subgraph": subgraph,
        }

    async def trading(self, state: State, config: RunnableConfig):
        result = state.agent_results[-1].get("result", "")
        trading_messages = [
            SystemMessage(
                content=TRADING_SYSTEM_TEMPLATE.format(stock_code=state.stock_code)
                + "\n"
                + "<Investment_Report>\n"
                + result
                + "\n</Investment_Report>"
            )
        ]
        trading_action = await self.llm_with_trading.ainvoke(
            trading_messages,
        )
        # NOTE: 이번 프로젝트에서는 실거래/주문 실행을 하지 않습니다.
        # trading_action은 "추천" 정보로만 반환하고, 사용자 승인(interrupt)/주문(place_order)은 수행하지 않습니다.
        messages = [
            AIMessage(
                content=(
                    result
                    + "\n\n(참고) 아래 '추천 주문'은 실제로 실행되지 않습니다.\n"
                    + trading_action.model_dump_json()
                )
            )
        ]

        update = {
            "messages": messages,
            "trading_action": trading_action.model_dump(),
            "subgraph": state.subgraph,
            "stock_name": state.stock_name,
            "stock_code": state.stock_code,
        }
        return update, "__end__"

    async def routing(self, state: State, config: RunnableConfig):
        agent_results_str = (
            json.dumps(state.agent_results, indent=2, ensure_ascii=False)
            if state.agent_results
            else "[]"
        )

        user_text = message_to_text(state.messages[-1]) if state.messages else ""

        # 가격/시세 요청은 TechnicalAnalysisAgent 결과가 1회 확보되면 추가 실행 없이 사용자에게 응답합니다.
        if _is_price_request(user_text):
            tech = _latest_agent_result(state, "TechnicalAnalysisAgent")
            if tech:
                update = State(
                    messages=[AIMessage(content=tech)],
                    agent_results=state.agent_results,
                    subgraph=state.subgraph if isinstance(state.subgraph, dict) else {},
                    stock_name=state.stock_name,
                    stock_code=state.stock_code,
                )
                return update, "__end__"

        # 뉴스/최신 소식 요청은 MarketAnalysisAgent 결과가 1회 확보되면 추가 실행 없이 사용자에게 응답합니다.
        if _is_news_request(user_text):
            market = _latest_agent_result(state, "MarketAnalysisAgent")
            if market:
                update = State(
                    messages=[AIMessage(content=market)],
                    agent_results=state.agent_results,
                    subgraph=state.subgraph if isinstance(state.subgraph, dict) else {},
                    stock_name=state.stock_name,
                    stock_code=state.stock_code,
                )
                return update, "__end__"

        human_message = HumanMessage(
            content=(
                f"<user>\n{user_text}\n</user>\n\n"
                f"<agent_analysis_result>\n{agent_results_str}\n</agent_analysis_result>"
            )
        )

        messages = (
            [SystemMessage(content=SYSTEM_TEMPLATE)]
            + state.messages[:-1]
            + [human_message]
        )

        stock_info = {"subgraph": "None", "stock_name": "None", "stock_code": "None"}
        stock_task = None
        if state.execute_agent_count == 0 and user_text:
            stock_task = asyncio.create_task(
                # 요구사항: 종목이 식별되면(간단 답변/그래프 미사용 답변 포함) 항상 subgraph를 반환
                self.get_stock_name_code_by_query_subgraph(
                    user_text, include_subgraph=True
                )
            )

        try:
            router_info = await self.llm_with_router.ainvoke(
                messages,
            )
        except Exception as e:
            logger.exception("Router LLM call failed")
            if stock_task is not None:
                try:
                    stock_info = await stock_task
                except Exception:
                    stock_info = {
                        "subgraph": "None",
                        "stock_name": "None",
                        "stock_code": "None",
                    }
            subgraph = (
                state.subgraph
                if stock_info["subgraph"] == "None"
                else stock_info["subgraph"]
            )
            stock_name = (
                state.stock_name
                if stock_info["stock_name"] == "None"
                else stock_info["stock_name"]
            )
            stock_code = (
                state.stock_code
                if stock_info["stock_code"] == "None"
                else stock_info["stock_code"]
            )
            update = State(
                messages=[
                    AIMessage(
                        content=(
                            "라우팅 단계에서 오류가 발생했습니다.\n"
                            "OPENAI_API_KEY/네트워크/모델 설정을 확인해주세요.\n\n"
                            f"에러: {type(e).__name__}: {e}"
                        )
                    )
                ],
                agent_results=state.agent_results,
                subgraph=subgraph if isinstance(subgraph, dict) else {},
                stock_name=stock_name,
                stock_code=stock_code,
            )
            return update, "__end__"

        if stock_task is not None:
            try:
                stock_info = await stock_task
            except Exception:
                stock_info = {
                    "subgraph": "None",
                    "stock_name": "None",
                    "stock_code": "None",
                }

        subgraph = (
            state.subgraph
            if stock_info["subgraph"] == "None"
            else stock_info["subgraph"]
        )
        stock_name = (
            state.stock_name
            if stock_info["stock_name"] == "None"
            else stock_info["stock_name"]
        )
        stock_code = (
            state.stock_code
            if stock_info["stock_code"] == "None"
            else stock_info["stock_code"]
        )

        if stock_code != "None" and _is_price_request(user_text):
            router_info = RouterList(
                routers=[Router(target="TechnicalAnalysisAgent", message=user_text)]
            )
        elif _is_news_request(user_text):
            router_info = RouterList(
                routers=[Router(target="MarketAnalysisAgent", message=user_text)]
            )

        target0 = router_info.routers[0].target
        if target0 not in self.agents_by_name and target0 != "User":
            update = State(
                messages=[
                    AIMessage(
                        content="요청하신 기능은 챗봇에서 직접 실행할 수 없습니다. 관련 페이지에서 실행해주세요."
                    )
                ],
                agent_results=state.agent_results,
                subgraph=subgraph if isinstance(subgraph, dict) else {},
                stock_name=stock_name,
                stock_code=stock_code,
            )
            return update, "__end__"

        if target0 == "User":
            update = State(
                messages=[AIMessage(content=router_info.routers[0].message)],
                agent_results=state.agent_results,
                subgraph=subgraph if isinstance(subgraph, dict) else {},
                stock_name=stock_name,
                stock_code=stock_code,
            )
            return update, "__end__"

        if state.execute_agent_count >= config.get("configurable", {}).get(
            "max_execute_agent_count", 3
        ):
            update = State(
                messages=[AIMessage(content="더 이상 실행할 수 없습니다.")],
                agent_results=state.agent_results,
                subgraph=subgraph if isinstance(subgraph, dict) else {},
                stock_name=stock_name,
                stock_code=stock_code,
            )
            return update, "__end__"

        update = {
            "agent_messages": [r.model_dump() for r in router_info.routers],
            "subgraph": subgraph if isinstance(subgraph, dict) else {},
            "stock_name": stock_name,
            "stock_code": stock_code,
        }
        return update, "execute_agent"
