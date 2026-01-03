from .agent import InvestmentStrategyAgent
from .prompt import SYSTEM_TEMPLATE
from .tools import *


def build_agent(async_database_url: str):
    if not async_database_url:
        raise ValueError("async_database_url 가 필요합니다.")
    return InvestmentStrategyAgent(
        model="gpt-5.1",
        tools=[
            GetAccountInfoTool(async_database_url=async_database_url),
            InvestmentStrategySearchTool(),
        ],
        system=SYSTEM_TEMPLATE,
        name="InvestmentStrategyAgent",
    )
