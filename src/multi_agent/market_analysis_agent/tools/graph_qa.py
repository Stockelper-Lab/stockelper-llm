import dotenv
import os
import asyncio
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
from langchain_community.graphs import Neo4jGraph
from langchain.chains import GraphCypherQAChain
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables import RunnableConfig
from typing import Optional
import dotenv

class GraphQAToolInput(BaseModel):
    query: str = Field(
        description="query string provided by the user in Korean"
    )

class GraphQATool(BaseTool):
    name: str = "financial_knowledge_graph_analysis"
    description: str = (
        "Analyze the relationships between entities in a financial knowledge graph."
        "The entity types in a financial knowledge graph include company, competitors, financial statements, indicators, stock prices, news, date, and sector."
    )
    graph: Optional[Neo4jGraph] = None
    llm: Optional[ChatOpenAI] = None
    args_schema: Type[BaseModel] = GraphQAToolInput
    return_direct: bool = False
    chain: Optional[GraphCypherQAChain] = None

    def __init__(self):
        # 지연 초기화: 연결 실패 시 서버 기동을 막지 않도록 함
        super().__init__(graph=None, llm=None, chain=None)

    def _ensure_initialized(self):
        if self.chain is not None:
            return
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USER")
        pwd = os.getenv("NEO4J_PASSWORD")
        if not uri or not user or not pwd:
            raise RuntimeError("Neo4j 설정(NEO4J_URI/USER/PASSWORD)이 없습니다.")
        # Neo4j 그래프 및 체인 초기화 (연결 시도는 여기서 수행)
        graph = Neo4jGraph(url=uri, username=user, password=pwd)
        llm = ChatOpenAI(openai_api_key=os.getenv("OPENAI_API_KEY"), temperature=0, model="gpt-4.1")
        chain = GraphCypherQAChain.from_llm(
            llm,
            graph=graph,
            verbose=True,
            return_intermediate_steps=True,
            allow_dangerous_requests=True,
            schema=custom_schema,
        )
        self.graph = graph
        self.llm = llm
        self.chain = chain

    # 답변과 cypher 쿼리를 반환
    def kgqa_chain(self, query: str):
        self._ensure_initialized()
        output = self.chain.invoke({"query": query}) # 출력
        answer = output.get('result', '') # 답변

        cypher = ''
        if 'intermediate_steps' in output and output['intermediate_steps']:
            cypher = output['intermediate_steps'][0].get('query', '')

        result = {
            'answer': answer,
            'cypher': cypher
        }
        return result

    def _run(self, 
             query: str,
             config: RunnableConfig,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """동기 메서드는 비동기 메서드를 실행"""
        return asyncio.run(self._arun(query, config, run_manager))
    
    async def _arun(self, 
                    query: str,
                    config: RunnableConfig,
                    run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        """메인 비동기 실행 메서드"""

        try:
            result = self.kgqa_chain(query)
        except Exception as e:
            return {"error": f"Neo4j 연결 불가: {str(e)}"}
        
        return result

    

custom_schema = """
Node types:
- Company
    - stock_name: 회사의 이름 (예: SK하이닉스)
    - stock_code: 회사의 종목코드 (예: 000660)
    - product: 회사의 제품 (예: 반도체)
    - listing_date: 회사의 상장일 (예: 2021-03-01)
    - settlement_month: 회사의 정산월 (예: 2021-03)
    - leader_name: 회사의 리더 (예: 이영표)
    - homepage: 회사의 홈페이지 (예: https://www.skhynix.com)
    - region: 회사의 지역 (예: 미국)
    - marcap: 회사의 시가총액 (예: 100000000000)
    - stock_cnt: 회사의 주식 수 (예: 100000000000)
    - market: 회사의 시장 (예: 코스피)
- Sector
    - sector: 회사의 업종 (예: 반도체)
- StockPrice
    - date: 날짜 (예: 2021-03-01)
    - open: 시가 (예: 100000000000)
    - high: 최고가 (예: 100000000000)
    - low: 최저가 (예: 100000000000)
    - close: 종가 (예: 100000000000)
    - volume: 거래량 (예: 100000000000)
    - changes_price: 변동가 (예: 100000000000)
- FinancialStatements
    - revenue: 매출액 (예: 100000000000)
    - operating_income: 영업이익 (예: 100000000000)
    - net_income: 순이익 (예: 100000000000)
    - total_assets: 총자산 (예: 100000000000)
    - total_liabilities: 총부채 (예: 100000000000)
    - total_capital: 총자본 (예: 100000000000)
    - capital_stock: 자본금 (예: 100000000000)
- Indicator
    - eps: 주당순이익 (예: 100000000000)
    - bps: 주당자본 (예: 100000000000)
    - per: 주가수익비율 (예: 100000000000)
    - pbr: 주가자산비율 (예: 100000000000)
- Date
    - date: 날짜 (예: 2021-03-01)
- News
    - id: 뉴스의 고유 ID (예: 1)
    - date: 뉴스의 날짜 (예: 2021-03-01)
    - title: 뉴스의 제목 (예: "SK하이닉스, 영업이익 증가")
    - body: 뉴스의 본문 (예: "SK하이닉스는 영업이익을 증가시켰습니다.")
    - stock_name: 뉴스의 종목명 (예: "SK하이닉스")

Relationships:
- (Company)-[:HAS_STOCK_PRICE]->(StockPrice)
- (Company)-[:HAS_FINANCIAL_STATEMENTS]->(FinancialStatements)
- (Company)-[:HAS_INDICATOR]->(Indicator)
- (StockPrice)-[:RECORDED_ON]->(Date)
- (Company)-[:BELONGS_TO]->(Sector)
- (Company)-[:HAS_COMPETITOR]->(Company)
- (News)-[:PUBLISHED_ON]->(Date)
- (News)-[:MENTIONS_STOCKS]->(Company)
"""
