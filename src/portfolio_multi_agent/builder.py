from langgraph.graph import StateGraph
from langgraph.types import Send
from .nodes import *
from .state import InputState, OutputState, OverallState, Stock


def map_analysis(state: OverallState):
    send_list = []
    for node in [WebSearch.name, FinancialStatement.name, TechnicalIndicator.name]:
        send_list.append(
            Send(
                node=node,
                arg=AnalysisInputState(portfolio_list=state.portfolio_list),
            ),
        )
    return send_list


def build():
    workflow = StateGraph(
        state_schema=OverallState, input_schema=InputState, output_schema=OutputState
    )

    workflow.add_node(Ranking.name, Ranking())
    workflow.add_node(WebSearch.name, WebSearch())
    workflow.add_node(FinancialStatement.name, FinancialStatement())
    workflow.add_node(TechnicalIndicator.name, TechnicalIndicator())
    workflow.add_node(ViewGenerator.name, ViewGenerator(model="gpt-4.1-mini"))
    workflow.add_node(PortfolioBuilder.name, PortfolioBuilder())
    workflow.add_node(PortfolioTrader.name, PortfolioTrader())

    workflow.add_edge("__start__", Ranking.name)
    workflow.add_conditional_edges(Ranking.name, map_analysis)
    workflow.add_edge(WebSearch.name, ViewGenerator.name)
    workflow.add_edge(FinancialStatement.name, ViewGenerator.name)
    workflow.add_edge(TechnicalIndicator.name, ViewGenerator.name)
    workflow.add_edge(ViewGenerator.name, PortfolioBuilder.name)
    # workflow.add_edge(PortfolioBuilder.name, PortfolioTrader.name)
    # workflow.add_edge(PortfolioTrader.name, "__end__")
    workflow.add_edge(PortfolioBuilder.name, "__end__")

    return workflow.compile(name="portfolio_multi_agent")
