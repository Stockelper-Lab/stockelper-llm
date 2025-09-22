import os
import asyncio
from typing import Type, Optional
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables import RunnableConfig
import dotenv


class SearchReportInput(BaseModel):
    company_name: str = Field(
        description='Company name to search for professional investment bank reports (e.g., "삼성전자", "현대차"). '
        "Use this to find expert analysis and recommendations for your target company."
    )


class SearchReportTool(BaseTool):
    name: str = "search_investment_bank_report"
    description: str = (
        "Essential tool for accessing professional investment bank reports and analyses."
        "Use this tool to gather key information for your report including: "
        "1. Expert market analysis and company valuations "
        "2. Price targets and investment recommendations "
        "3. Industry outlook and competitive positioning "
        "4. Financial analysis and forecasts "
        "This information should be integrated throughout your report, especially in the "
        "'Market Analysis', 'Financial Status', and 'Investment Outlook' sections. "
        "The tool provides recent reports sorted by date, offering latest expert opinions and market views."
    )
    args_schema: Type[BaseModel] = SearchReportInput
    return_direct: bool = False

    mongo_collection: object
    three_ago: object = datetime.today() - timedelta(3)

    def __init__(self):
        # 지연 초기화: 실제 사용 시점에 연결 생성
        super().__init__(mongo_collection=None)

    def _run(
        self,
        company_name: str,
        config: RunnableConfig = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ):
        return asyncio.run(self._arun(company_name, config, run_manager))

    async def _arun(
        self,
        company_name: str,
        config: RunnableConfig = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ):
        # 최초 호출 시 Mongo 연결 생성
        if self.mongo_collection is None:
            mongo_uri = os.getenv("MONGO_URI")
            if not mongo_uri:
                return {"error": "MONGO_URI 환경변수가 설정되어 있지 않습니다."}
            mongo_client = AsyncIOMotorClient(mongo_uri)
            mongo_db = mongo_client["stockelper"]
            self.mongo_collection = mongo_db["report"]
        documents = []
        async for doc in self.mongo_collection.find({"company": company_name}).sort("date", -1):
            documents.append(doc)

        observation = []

        for i, doc in enumerate(documents):
            observation.append(
                {
                    "company": doc['company'],
                    "date": doc['date'],
                    'goal_price': doc['goal_price'],
                    'opinion': doc['opinion'],
                    'provider': doc['provider'],
                    'summary': doc['summary'],
                }
            )

        return observation
