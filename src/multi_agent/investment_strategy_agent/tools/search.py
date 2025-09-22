import os
import json
import requests
import httpx
import asyncio
from dotenv import load_dotenv
from typing import Type, Optional, ClassVar
from langchain_openai import ChatOpenAI
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

load_dotenv(override=True)

class InvestmentStrategySearchInput(BaseModel):
    query: str = Field(
        description="Mandatory search query you want to use to search the internet"
    )

class InvestmentStrategySearchTool(BaseTool):
    name: str = "investment_strategy_search"
    description: str = "A tool for searching investment strategies on the web"
    args_schema: Type[BaseModel] = InvestmentStrategySearchInput
    return_direct: bool = False

    llm: ClassVar[ChatOpenAI] = ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        model="perplexity/sonar",
        api_key=os.getenv("OPENROUTER_API_KEY")
    )

    def _run(self, query: str, config: RunnableConfig, run_manager: Optional[CallbackManagerForToolRun] = None):
        return asyncio.run(self._arun(query, config, run_manager))

    async def _arun(
        self,
        query: str,
        config: RunnableConfig,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ):
        if not os.getenv("OPENROUTER_API_KEY"):
            return {"error": "OPENROUTER_API_KEY 환경변수가 설정되어 있지 않습니다."}
        response = await self.llm.ainvoke(query)

        return response.content
