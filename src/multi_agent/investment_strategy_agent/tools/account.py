import asyncio
from typing import Optional

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from sqlalchemy.ext.asyncio import create_async_engine

from multi_agent.utils import (
    check_account_balance,
    get_access_token,
    get_user_kis_credentials,
    update_user_kis_credentials,
)


class GetAccountInfoTool(BaseTool):
    name: str = "get_account_info"
    description: str = "retrieves a user’s account cash balance and the total valuation of the account."
    return_direct: bool = False

    async_engine: object

    def __init__(self, async_database_url: str):
        super().__init__(
            async_engine=create_async_engine(async_database_url, echo=False)
        )

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
