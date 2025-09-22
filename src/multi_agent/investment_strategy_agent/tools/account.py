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
from multi_agent.utils import get_user_kis_credentials, get_access_token, check_account_balance, update_user_kis_credentials, Base


class GetAccountInfoTool(BaseTool):
    name: str = "get_account_info"
    description: str = "retrieves a user’s account cash balance and the total valuation of the account."
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
        update_access_token_flag = False
        if not user_info:
            return "There is no account information available."
        
        if not user_info['kis_access_token']:
            access_token = await get_access_token(user_info['kis_app_key'], user_info['kis_app_secret'])
            user_info['kis_access_token'] = access_token
            update_access_token_flag = True
        
        account_info = await check_account_balance(user_info['kis_app_key'], user_info['kis_app_secret'], user_info['kis_access_token'], user_info['account_no'])
        if account_info is None:
            return "There is no account information available."
        
        if isinstance(account_info, str) and ("유효하지 않은 token" in account_info or "기간이 만료된 token" in account_info):
            user_info['kis_access_token'] = await get_access_token(user_info['kis_app_key'], user_info['kis_app_secret'])
            account_info = await check_account_balance(user_info['kis_app_key'], user_info['kis_app_secret'], user_info['kis_access_token'], user_info['account_no'])
            update_access_token_flag = True
            
        if update_access_token_flag:
            await update_user_kis_credentials(self.async_engine, config["configurable"]["user_id"], user_info['kis_access_token'])
        
        return account_info
