import os
from typing import Type, Optional, ClassVar
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import json
import dotenv
import asyncio
from langchain_openai import ChatOpenAI


class SearchNewsInput(BaseModel):
    query: str = Field(
        description='query string provided by the user (e.g., "삼성전자 최신 뉴스")'
    )


class SearchNewsTool(BaseTool):
    name: str = "search_news"
    description: str = (
        "search for news related to the user query"
        "use this tool when you need news of companies."
    )
    args_schema: Type[BaseModel] = SearchNewsInput
    return_direct: bool = False

    llm: ClassVar[ChatOpenAI] = ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        model="perplexity/sonar",
        api_key=os.getenv("OPENROUTER_API_KEY")
    )

    def _run(
        self,
        query: str,
        config: RunnableConfig = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ):
        return asyncio.run(self._arun(query, config, run_manager))

    async def _arun(
        self,
        query: str,
        config: RunnableConfig = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ):
        response = await self.llm.ainvoke(query)

        return response.content
