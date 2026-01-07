import os
import json
import asyncio
import difflib
import re
import logging
from pydantic import BaseModel, Field
from typing import Optional, List
from dataclasses import asdict, dataclass, field
from typing import Annotated
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt
from langgraph.graph import StateGraph
from langgraph.config import get_stream_writer
from langchain_openai import ChatOpenAI
from neo4j import GraphDatabase
import functools
from sqlalchemy.ext.asyncio import create_async_engine
from .prompt import SYSTEM_TEMPLATE, TRADING_SYSTEM_TEMPLATE, STOCK_NAME_USER_TEMPLATE, STOCK_CODE_USER_TEMPLATE
from ..utils import (
    custom_add_messages,
    get_user_kis_context,
    is_kis_token_expired_message,
    place_order,
    refresh_user_kis_access_token,
)
from langchain_compat import message_to_text
from json_safety import to_jsonable

logger = logging.getLogger(__name__)

_PRICE_REQUEST_PAT = re.compile(r"(주가|가격|현재가|시세|주식\\s*가격)", re.IGNORECASE)


def _is_price_request(text: str) -> bool:
    return bool(_PRICE_REQUEST_PAT.search(text or ""))



class Router(BaseModel):
    target: str = Field(
        description="The target of the message, either 'User' or 'MarketAnalysisAgent' or 'FundamentalAnalysisAgent' or 'TechnicalAnalysisAgent' or 'InvestmentStrategyAgent'"
    )
    message: str = Field(description="The message in korean to be sent to the target")


class RouterList(BaseModel):
    routers: List[Router] = Field(description="The list of one or more routers")


class StockName(BaseModel):
    stock_name: str = Field(description="The name of the stock or None")


class StockCode(BaseModel):
    stock_code: str = Field(description="The code of the stock or None")


class TradingAction(BaseModel):
    stock_code: str = Field(description="Stock code of the security to be ordered, referring to <Stock_Code>.")
    order_side: str = Field(description="The side of the order to be traded. buy or sell")
    order_type: str = Field(description="The type of the order to be traded. market or limit")
    order_price: Optional[float] = Field(description="The price of the stock to be traded. If the order_type is 'market', then use None.")
    order_quantity: int = Field(description="The quantity of the stock to be traded")


def custom_truncate_agent_results(existing: list, update: list):
    return update[-10:]


@dataclass
class State:
    messages: Annotated[list, custom_add_messages] = field(default_factory=list)
    query: str = field(default="")
    agent_messages: list = field(default_factory=list)
    agent_results: Annotated[list, custom_truncate_agent_results] = field(default_factory=list)
    execute_agent_count: int = field(default=0)
    trading_action: dict = field(default_factory=dict)
    stock_name: str = field(default="")
    stock_code: str = field(default="")
    subgraph: dict = field(default_factory=dict)

@dataclass
class Config:
    user_id: int = field(default=1)
    max_execute_agent_count: int = field(default=3)


class SupervisorAgent:
    def __new__(cls, model, agents, checkpointer, async_database_url: str):
        instance = super().__new__(cls)
        instance.__init__(model, agents, checkpointer, async_database_url)
        return instance.graph

    def __init__(self, model, agents, checkpointer, async_database_url: str):
        self.async_engine = create_async_engine(async_database_url, echo=False)
        self.llm = ChatOpenAI(model=model)
        self.llm_with_router = self.llm.with_structured_output(RouterList)
        self.llm_with_trading = self.llm.with_structured_output(TradingAction)
        self.llm_with_stock_name = self.llm.with_structured_output(StockName)
        self.llm_with_stock_code = self.llm.with_structured_output(StockCode)
        self.agents_by_name = {agent.name: agent for agent in agents}
        # 그래프 구성
        self.workflow = StateGraph(State)
        self.workflow.add_node("supervisor", self.supervisor)
        self.workflow.add_node("execute_agent", self.execute_agent)
        self.workflow.add_node("execute_trading", self.execute_trading)
        # 엣지 추가
        self.workflow.add_edge("__start__", "supervisor")

        # 그래프 컴파일
        self.graph = self.workflow.compile(checkpointer=checkpointer)
        self.graph.name = "stockelper"

    async def supervisor(self, state: State, config: RunnableConfig) -> State:
        stream_writer = get_stream_writer()
        stream_writer({"step": "supervisor", "status": "start"})

        if (
            state.agent_results
            and state.execute_agent_count > 0
            and state.agent_results[-1]["target"] == "InvestmentStrategyAgent"
        ):
            update, goto = await self.trading(state, config)
        else:
            update, goto = await self.routing(state, config)
        
        stream_writer({"step": "supervisor", "status": "end"})
        return Command(update=update, goto=goto)

    async def execute_agent(self, state: State, config: RunnableConfig):
        stream_writer = get_stream_writer()
        
        async def stream_single_agent(router):
            """단일 에이전트 스트리밍 처리"""
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
            agent_config = RunnableConfig(
                configurable={
                    "user_id": config["configurable"]["user_id"], 
                    "max_execute_tool_count": 5
                }
            )
            
            # 스트리밍으로 에이전트 실행
            async for response_type, response in self.agents_by_name[router["target"]].astream(
                input_data, 
                config=agent_config,
                stream_mode=["custom", "values"],
            ):
                if response_type == "custom":
                    stream_writer(response)
                elif response_type == "values":
                    final_response = response
            
            return router, final_response

        # 여러 에이전트를 병렬로 스트리밍 처리
        tasks = [stream_single_agent(router) for router in state.agent_messages]
        results = await asyncio.gather(*tasks)

        agent_results = []
        for router, result in results:
            agent_results.append(
                router | {"result": message_to_text(result["messages"][-1]) if result.get("messages") else ""}
            )

        update = {
            "agent_messages": [],
            "agent_results": state.agent_results + agent_results,
            "execute_agent_count": state.execute_agent_count + 1,
        }
        goto = "supervisor"

        return Command(update=update, goto=goto)
    
    async def execute_trading(self, state: State, config: RunnableConfig):
        human_check = interrupt("interrupt")
        print("human_check", human_check)
        
        if human_check:
            user_id = config["configurable"]["user_id"]
            user_info = await get_user_kis_context(self.async_engine, user_id, require=False)
            if user_info:
                kwargs = state.trading_action | user_info
                trading_result = place_order(**kwargs)

                # 토큰 만료면 재발급 → DB 업데이트 → 1회 재시도
                if isinstance(trading_result, str) and is_kis_token_expired_message(trading_result):
                    user_info["kis_access_token"] = await refresh_user_kis_access_token(
                        self.async_engine, user_id, user_info
                    )
                    kwargs["kis_access_token"] = user_info["kis_access_token"]
                    trading_result = place_order(**kwargs)
            else:
                trading_result = "계좌정보가 없습니다."

            update = State(
                messages=[AIMessage(content=trading_result)],
                agent_results=[],
                stock_name=state.stock_name,
                subgraph=state.subgraph
            )
            goto = "__end__"
        else:
            update = State(
                messages=[AIMessage(content="주문을 취소합니다.")],
                agent_results=state.agent_results,
                stock_name=state.stock_name,
                subgraph=state.subgraph
            )
            goto = "__end__"

        return Command(update=update, goto=goto)
    
    async def get_stock_name_code_by_query_subgraph(self, query, *, include_subgraph: bool = True):
        messages = [HumanMessage(content=STOCK_NAME_USER_TEMPLATE.format(user_request=query))]
        response = await self.llm_with_stock_name.ainvoke(messages)
        stock_name = response.stock_name
        if stock_name != "None":
            # 1) 정확 일치(가장 안정적)
            listing = _get_stock_listing_map()
            exact = listing.get((stock_name or "").strip())
            if exact:
                stock_code = exact
            else:
                # 2) 유사도 기반 후보군 → LLM 선택
                stock_codes = find_similar_companies(company_name=stock_name, top_n=10)
                if stock_codes:
                    messages = [
                        HumanMessage(
                            content=STOCK_CODE_USER_TEMPLATE.format(
                                stock_name=stock_name, stock_codes=stock_codes
                            )
                        )
                    ]
                    response = await self.llm_with_stock_code.ainvoke(messages)
                    stock_code = response.stock_code
                else:
                    # 최후 폴백: 상장목록 로딩 실패 시라도,
                    # LLM이 유명 종목(예: 삼성전자=005930)을 알고 있으면 동작하도록 유도합니다.
                    fallback_prompt = (
                        "Please return the 6-digit KRX stock code for the given Stock Name. "
                        "If unknown, return \"None\".\n\n"
                        "<Stock_Name>\n"
                        f"{stock_name}\n"
                        "</Stock_Name>\n"
                    )
                    response = await self.llm_with_stock_code.ainvoke(
                        [HumanMessage(content=fallback_prompt)]
                    )
                    stock_code = response.stock_code

            # 방어: 6자리 숫자 형식이 아니면 None 처리
            if not (isinstance(stock_code, str) and stock_code.isdigit() and len(stock_code) == 6):
                stock_code = "None"

            # 서브그래프는 일부 요청(투자전략/분석)에서만 의미가 있어,
            # 단순 현재가/가격 문의에서는 Neo4j 경고/오버헤드를 피하기 위해 생략할 수 있습니다.
            if include_subgraph:
                try:
                    subgraph = self.get_subgraph_by_stock_name(stock_name)
                except Exception:
                    subgraph = "None"
            else:
                subgraph = "None"
        else:
            stock_code = "None"
            subgraph = "None"

        return {"stock_name": stock_name, "stock_code": stock_code, "subgraph": subgraph}
    
    def get_subgraph_by_stock_name(self, stock_name):
        driver = GraphDatabase.driver(os.getenv("NEO4J_URI"), auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")))
        
        query = """
        MATCH (c:Company {stock_nm: $stock_name})
        CALL {
            WITH c
            MATCH (c)-[r]->(n)
            WHERE type(r) IN ['HAS_COMPETITOR', 'BELONGS_TO']
            RETURN collect({
                node_type: labels(n)[0],
                properties: properties(n),
                node_name: CASE 
                    WHEN labels(n)[0] = 'Company' THEN n.stock_nm
                    WHEN labels(n)[0] = 'Sector' THEN n.stock_sector_nm
                END
            }) as nodes,
            collect({
                start: {
                    name: c.stock_nm,
                    type: labels(c)[0]
                },
                relationship: type(r),
                end: {
                    name: CASE 
                        WHEN type(r) = 'HAS_COMPETITOR' THEN n.stock_nm
                        WHEN type(r) = 'BELONGS_TO' THEN n.stock_sector_nm
                    END,
                    type: labels(n)[0]
                }
            }) as relations
        }
        WITH nodes, relations, c
        RETURN nodes + [{
            node_type: labels(c)[0],
            properties: properties(c),
            node_name: c.stock_nm
        }] as nodes,
        relations as relations
        """
        
        with driver.session() as session:
            result = session.run(query, stock_name=stock_name)
            record = result.single()
            if record:
                return to_jsonable({
                    "node": record["nodes"],
                    "relation": record["relations"]
                })
            return {}
    
    async def trading(self, state, config):
        result = state.agent_results[-1]["result"]
        trading_messages = [
            SystemMessage(
                content=TRADING_SYSTEM_TEMPLATE.format(stock_code=state.stock_code)
                + "\n"
                + "<Investment_Report>\n"
                + result
                + "\n</Investment_Report>"
            )
        ]
        trading_action = await self.llm_with_trading.ainvoke(trading_messages)
        messages = [AIMessage(content=result + "\n\n아래 주문 정보를 수락하겠습니까?\n" + trading_action.model_dump_json())]

        update = {"messages": messages, "trading_action": trading_action.model_dump(), "subgraph": state.subgraph, "stock_name": state.stock_name}
        goto = "execute_trading"
        return update, goto
    
    async def routing(self, state, config):
        if state.agent_results:
            agent_results_str = json.dumps(
                state.agent_results, indent=2, ensure_ascii=False
            )
        else:
            agent_results_str = "[]"
        human_message = [
            HumanMessage(
                content=(
                    f"<user>\n{message_to_text(state.messages[-1])}\n</user>\n\n"
                    f"<agent_analysis_result>\n{agent_results_str}\n</agent_analysis_result>"
                )
            )
        ]

        messages = [SystemMessage(content=SYSTEM_TEMPLATE)] + state.messages[:-1] + human_message

        stock_info = {"subgraph": "None", "stock_name": "None", "stock_code": "None"}

        user_text = message_to_text(state.messages[-1])

        stock_task = None
        if state.execute_agent_count == 0:
            stock_task = asyncio.create_task(
                self.get_stock_name_code_by_query_subgraph(
                    state.messages[-1].content,
                    include_subgraph=not _is_price_request(user_text),
                )
            )

        try:
            router_info = await self.llm_with_router.ainvoke(messages)
        except Exception as e:
            # 라우팅 실패 시 챗봇이 죽지 않도록 User 응답으로 폴백
            logger.exception("Router LLM call failed")
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
                subgraph=state.subgraph,
                stock_name=state.stock_name,
                stock_code=state.stock_code,
            )
            return update, "__end__"

        if stock_task is not None:
            try:
                stock_info = await stock_task
            except Exception as e:
                logger.exception("Stock name/code extraction failed")
                stock_info = {"subgraph": "None", "stock_name": "None", "stock_code": "None"}

        subgraph = state.subgraph if stock_info["subgraph"] == "None" else stock_info["subgraph"]
        stock_name = state.stock_name if stock_info["stock_name"] == "None" else stock_info["stock_name"]
        stock_code = state.stock_code if stock_info["stock_code"] == "None" else stock_info["stock_code"]

        # 주가/가격/현재가 요청은 TechnicalAnalysisAgent로 강제 라우팅(LLM 라우터 오동작 방지)
        if stock_code != "None" and _is_price_request(user_text):
            router_info = RouterList(
                routers=[
                    Router(
                        target="TechnicalAnalysisAgent",
                        message=user_text,
                    )
                ]
            )
            logger.info(
                "Forced routing to TechnicalAnalysisAgent for price request: stock_name=%s stock_code=%s",
                stock_name,
                stock_code,
            )

        # 안전장치: 존재하지 않는 agent로 라우팅되면 User 응답으로 폴백
        if router_info.routers[0].target not in self.agents_by_name and router_info.routers[0].target != "User":
            update = State(
                messages=[AIMessage(content="요청하신 기능은 챗봇에서 직접 실행할 수 없습니다. 관련 페이지에서 실행해주세요.")],
                agent_results=state.agent_results,
                subgraph=subgraph,
                stock_name=stock_name,
                stock_code=stock_code,
            )
            goto = "__end__"
        elif router_info.routers[0].target == "User":
            update = State(
                messages=[AIMessage(content=router_info.routers[0].message)],
                agent_results=state.agent_results,
                subgraph=subgraph,
                stock_name=stock_name,
                stock_code=stock_code
            )
            goto = "__end__"
        else:
            if (
                state.execute_agent_count
                >= config["configurable"]["max_execute_agent_count"]
            ):
                update = State(
                    messages=[AIMessage(content="더 이상 실행할 수 없습니다.")],
                    agent_results=state.agent_results,
                    subgraph=subgraph,
                    stock_name=stock_name,
                    stock_code=stock_code
                )
                goto = "__end__"
            else:
                update = {
                    "agent_messages": [
                        router.model_dump() for router in router_info.routers
                    ],
                    "execute_agent_count": state.execute_agent_count + 1,
                    "subgraph": subgraph,
                    "stock_name": stock_name,
                    "stock_code": stock_code
                }
                goto = "execute_agent"
        return update, goto
    
    async def routing_user(self, state, config):
        messages = [AIMessage(content=state.agent_results[-1]["result"])]
        update = State(
            messages=messages,
            agent_results=state.agent_results,
            subgraph=state.subgraph,
            stock_name=state.stock_name,
            stock_code=state.stock_code
        )
        goto = "__end__"
        return update, goto
        
_STOCK_LISTING_CACHE = None


def _debug_errors_enabled() -> bool:
    return os.getenv("DEBUG_ERRORS", "false").lower() not in {"0", "false", "no"}


def _parse_kis_mst_text(text: str) -> dict:
    """KIS 종목마스터(.mst) 텍스트를 파싱해 종목명→종목코드 맵으로 변환합니다.

    KIS 샘플코드(kis_kospi_code_mst.py) 기준:
    - row 마지막 228 byte(문자) = part2 고정폭 정보
    - row 앞부분 = part1(단축코드 9, 표준코드 12, 한글명 가변)
    """
    mapping: dict[str, str] = {}
    if not text:
        return mapping

    for raw in text.splitlines():
        row = (raw or "").rstrip("\r\n")
        if not row:
            continue
        # 최소 길이 방어(단축코드/표준코드/한글명 + part2)
        if len(row) < (21 + 1 + 228):
            continue

        part1 = row[:-228]
        if len(part1) < 21:
            continue

        code_raw = part1[0:9].strip()
        name = part1[21:].strip()
        if not code_raw or not name:
            continue

        # 단축코드는 6자리 숫자지만 파일상 9자리 영역이므로 숫자만 추출 후 6자리로 정규화
        code_digits = "".join(ch for ch in code_raw if ch.isdigit())
        if not code_digits:
            continue
        code_digits = code_digits.zfill(6)
        if not (len(code_digits) == 6 and code_digits.isdigit()):
            continue

        # 동일 이름이 여러 시장에 존재하면 최초 값을 유지
        mapping.setdefault(name, code_digits)

    return mapping


def _load_stock_listing_from_kis_master() -> dict:
    """KIS 개발자센터 '종목정보파일'에서 제공하는 mst.zip으로 종목명→종목코드 맵을 로드합니다."""
    import io
    import zipfile
    import requests

    # 기본: 코스피/코스닥(+코넥스) 종목마스터 파일
    default_urls = [
        "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
        "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
        "https://new.real.download.dws.co.kr/common/master/konex_code.mst.zip",
    ]
    raw_urls = (os.getenv("KIS_STOCK_MASTER_URLS") or "").strip()
    urls = [u.strip() for u in raw_urls.split(",") if u.strip()] if raw_urls else default_urls

    headers = {
        "User-Agent": os.getenv(
            "STOCK_LISTING_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        )
    }
    timeout_s = float(os.getenv("KIS_STOCK_MASTER_TIMEOUT", "30") or 30)

    mapping: dict[str, str] = {}
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout_s)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                mst_name = next((n for n in zf.namelist() if n.lower().endswith(".mst")), None)
                if not mst_name:
                    raise ValueError("zip 내부에 .mst 파일이 없습니다.")
                mst_bytes = zf.read(mst_name)

            text = mst_bytes.decode("cp949", errors="replace")
            part = _parse_kis_mst_text(text)
            if part:
                for k, v in part.items():
                    mapping.setdefault(k, v)
            logger.info("Loaded KIS stock master: url=%s rows=%d", url, len(part))
        except Exception as e:
            # 운영에서는 traceback을 숨기고 경고만 남깁니다.
            if _debug_errors_enabled():
                logger.exception("Failed to load KIS stock master: url=%s", url)
            else:
                logger.warning(
                    "Failed to load KIS stock master: url=%s err=%s: %s",
                    url,
                    type(e).__name__,
                    e,
                )

    return mapping


def _get_stock_listing_map():
    global _STOCK_LISTING_CACHE
    if _STOCK_LISTING_CACHE is None:
        _STOCK_LISTING_CACHE = _load_stock_listing_from_kis_master()
        if _STOCK_LISTING_CACHE:
            logger.info("Loaded stock listing via KIS master: %d", len(_STOCK_LISTING_CACHE))
        else:
            logger.warning("Stock listing map is empty (KIS master load failed).")
    return _STOCK_LISTING_CACHE


def find_similar_companies(company_name: str, top_n: int = 10):
    map_stock_code = _get_stock_listing_map()

    similarities = []
    for name in map_stock_code.keys():
        ratio = difflib.SequenceMatcher(None, company_name, name).ratio()
        similarities.append((name, ratio))

    similarities.sort(key=lambda x: x[1], reverse=True)
    top_companies = similarities[:top_n]

    result = {}
    for name, _ in top_companies:
        result[name] = map_stock_code[name]

    return result
