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
    get_user_kis_context,
    is_kis_token_expired_message,
    refresh_user_kis_access_token,
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
        user_id = config["configurable"]["user_id"]
        user_info = await get_user_kis_context(self.async_engine, user_id, require=False)
        if not user_info:
            return "There is no account information available."

        account_info = await check_account_balance(
            user_info["kis_app_key"],
            user_info["kis_app_secret"],
            user_info["kis_access_token"],
            user_info["account_no"],
        )

        # 토큰 만료면 재발급 → DB 업데이트 → 1회 재시도
        if isinstance(account_info, str) and is_kis_token_expired_message(account_info):
            new_token = await refresh_user_kis_access_token(self.async_engine, user_id, user_info)
            user_info["kis_access_token"] = new_token
            account_info = await check_account_balance(
                user_info["kis_app_key"],
                user_info["kis_app_secret"],
                user_info["kis_access_token"],
                user_info["account_no"],
            )

        if account_info is None:
            return "There is no account information available."

        return account_info
