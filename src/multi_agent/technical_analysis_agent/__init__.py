import os
from .agent import TechnicalAnalysisAgent
from .prompt import SYSTEM_TEMPLATE
from .tools import *


agent = TechnicalAnalysisAgent(
    model="gpt-4.1-mini",
    tools=[
        AnalysisStockTool(async_database_url=os.environ["ASYNC_DATABASE_URL"]),
        PredictStockTool(),
        StockChartAnalysisTool(async_database_url=os.environ["ASYNC_DATABASE_URL"]),
    ],
    system=SYSTEM_TEMPLATE,
    name="TechnicalAnalysisAgent",
)