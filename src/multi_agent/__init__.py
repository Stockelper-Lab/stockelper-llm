import os
from .market_analysis_agent import agent as market_analysis_agent
from .fundamental_analysis_agent import agent as fundamental_analysis_agent
from .technical_analysis_agent import agent as technical_analysis_agent
from .investment_strategy_agent import agent as investment_strategy_agent
from .portfolio_analysis_agent import agent as portfolio_analysis_agent
from .supervisor_agent import SupervisorAgent

multi_agent = SupervisorAgent(
    model="gpt-4.1-mini",
    agents=[
        market_analysis_agent,
        fundamental_analysis_agent,
        technical_analysis_agent,
        investment_strategy_agent,
        portfolio_analysis_agent,
    ],
    checkpointer=None,
    async_database_url=os.environ["ASYNC_DATABASE_URL"]
)