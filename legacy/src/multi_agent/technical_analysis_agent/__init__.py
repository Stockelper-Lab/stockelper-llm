from .agent import TechnicalAnalysisAgent
from .prompt import SYSTEM_TEMPLATE
from .tools import *


def build_agent(async_database_url: str):
    if not async_database_url:
        raise ValueError("async_database_url 가 필요합니다.")
    return TechnicalAnalysisAgent(
        model="gpt-5.1",
        tools=[
            AnalysisStockTool(async_database_url=async_database_url),
            PredictStockTool(),
            StockChartAnalysisTool(async_database_url=async_database_url),
        ],
        system=SYSTEM_TEMPLATE,
        name="TechnicalAnalysisAgent",
    )
