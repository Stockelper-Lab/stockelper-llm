from .agent import MarketAnalysisAgent
from .prompt import SYSTEM_TEMPLATE
from .tools import *


agent = MarketAnalysisAgent(
    model="gpt-5.1",
    tools=[
        SearchNewsTool(),
        SearchReportTool(),
        YouTubeSearchTool(),
        ReportSentimentAnalysisTool(),
        GraphQATool(),
    ],
    system=SYSTEM_TEMPLATE,
    name="MarketAnalysisAgent",
)