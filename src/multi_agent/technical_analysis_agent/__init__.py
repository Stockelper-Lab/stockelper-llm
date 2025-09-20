import os
from .agent import TechnicalAnalysisAgent
from .prompt import SYSTEM_TEMPLATE
from .tools import *


async_db_url = os.getenv("ASYNC_DATABASE_URL")
if not async_db_url:
    raise RuntimeError("환경변수 ASYNC_DATABASE_URL 이 설정되어 있지 않습니다.")

agent = TechnicalAnalysisAgent(
    model="gpt-4.1-mini",
    tools=[
        AnalysisStockTool(async_database_url=async_db_url),
        PredictStockTool(),
        StockChartAnalysisTool(async_database_url=async_db_url),
    ],
    system=SYSTEM_TEMPLATE,
    name="TechnicalAnalysisAgent",
)
