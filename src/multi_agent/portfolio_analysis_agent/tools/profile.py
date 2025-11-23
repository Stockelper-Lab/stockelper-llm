import os
from typing import Type, Optional
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.vectorstores import VectorStore
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
import dotenv
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import create_engine
from multi_agent.utils import Base, get_user_kis_credentials


class GetProfileInfoTool(BaseTool):
    name: str = "get_profile_info"
    description: str = "Retrieves user's investor type information. Returns the investor_type which indicates the user's investment style or risk profile."
    return_direct: bool = False

    async_engine: object

    def __init__(self, async_database_url: str):
        super().__init__(
            async_engine=create_async_engine(async_database_url, echo=False)
        )
        # 테이블 존재 확인 및 생성 (동기 방식)
        self._create_table_if_not_exists(async_database_url)
    
    def _create_table_if_not_exists(self, async_database_url: str):
        """users 테이블이 존재하지 않으면 생성 (동기 방식)"""
        # 비동기 URL을 동기 URL로 변환 (psycopg3 사용)
        sync_database_url = async_database_url.replace('+asyncpg', '+psycopg').replace('postgresql+asyncpg', 'postgresql+psycopg')
        
        # 동기 엔진으로 테이블 생성
        sync_engine = create_engine(sync_database_url, echo=False)
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()

    def _run(self, config: RunnableConfig, run_manager: Optional[CallbackManagerForToolRun] = None):
        return asyncio.run(self._arun(config, run_manager))
    
    async def _arun(self, config: RunnableConfig, run_manager: Optional[AsyncCallbackManagerForToolRun] = None):
        user_info = await get_user_kis_credentials(self.async_engine, config["configurable"]["user_id"])
        return {
            "investor_type": user_info.get("investor_type")
        }
