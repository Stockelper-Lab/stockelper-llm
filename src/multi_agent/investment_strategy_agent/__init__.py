import os
from .agent import InvestmentStrategyAgent
from .prompt import SYSTEM_TEMPLATE
from .tools import *

agent = InvestmentStrategyAgent(
    model="gpt-4.1-mini",
    tools=[
        GetAccountInfoTool(async_database_url=os.environ["ASYNC_DATABASE_URL"]),
        InvestmentStrategySearchTool(),
    ],
    system=SYSTEM_TEMPLATE,
    name="InvestmentStrategyAgent",
)