from .agent import PortfolioAnalysisAgent
from .prompt import SYSTEM_TEMPLATE
from .tools import *


def build_agent(async_database_url: str):
    return PortfolioAnalysisAgent(
        model="gpt-4.1-mini",
        tools=[
            PortfolioAnalysisTool(),
            GetProfileInfoTool(async_database_url=async_database_url),
        ],
        system=SYSTEM_TEMPLATE,
        name="PortfolioAnalysisAgent",
    )
