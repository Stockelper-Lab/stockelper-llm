from .agent import FundamentalAnalysisAgent
from .prompt import SYSTEM_TEMPLATE
from .tools import *


agent = FundamentalAnalysisAgent(
    model="gpt-4.1-mini",
    tools=[
        AnalysisFinancialStatementTool(),
    ],
    system=SYSTEM_TEMPLATE,
    name="FundamentalAnalysisAgent",
)