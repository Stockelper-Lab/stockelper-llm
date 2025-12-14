from langgraph.graph import StateGraph
from langgraph.types import Send
from .nodes import *
from .state import (
    Stock,
    BuyInputState,
    BuyOutputState,
    BuyOverallState,
    SellInputState,
    SellOutputState,
    SellOverallState,
)


def map_buy_analysis(state: BuyOverallState):
    """매수를 위한 종목 분석 매핑"""
    send_list = []
    for node in [WebSearch.name, FinancialStatement.name, TechnicalIndicator.name]:
        send_list.append(
            Send(
                node=node,
                arg=AnalysisInputState(portfolio_list=state.portfolio_list),
            ),
        )
    return send_list


def build_buy_workflow():
    """매수 워크플로우 빌더"""
    workflow = StateGraph(
        state_schema=BuyOverallState,
        input_schema=BuyInputState,
        output_schema=BuyOutputState,
    )

    workflow.add_node(Ranking.name, Ranking())
    workflow.add_node(WebSearch.name, WebSearch())
    workflow.add_node(FinancialStatement.name, FinancialStatement())
    workflow.add_node(TechnicalIndicator.name, TechnicalIndicator())
    workflow.add_node(ViewGenerator.name, ViewGenerator(model="gpt-4.1-mini"))
    workflow.add_node(PortfolioBuilder.name, PortfolioBuilder())
    workflow.add_node(PortfolioTrader.name, PortfolioTrader())

    workflow.add_edge("__start__", Ranking.name)
    workflow.add_conditional_edges(Ranking.name, map_buy_analysis)
    workflow.add_edge(WebSearch.name, ViewGenerator.name)
    workflow.add_edge(FinancialStatement.name, ViewGenerator.name)
    workflow.add_edge(TechnicalIndicator.name, ViewGenerator.name)
    workflow.add_edge(ViewGenerator.name, PortfolioBuilder.name)
    workflow.add_edge(PortfolioBuilder.name, PortfolioTrader.name)
    workflow.add_edge(PortfolioTrader.name, "__end__")

    return workflow.compile(name="portfolio_buy_agent")


def map_sell_analysis(state: SellOverallState):
    """매도를 위한 보유 종목 분석 매핑"""
    send_list = []

    # 보유 종목을 Stock 리스트로 변환
    portfolio_list = [Stock(code=h.code, name=h.name) for h in state.holding_stocks]

    for node in [WebSearch.name, FinancialStatement.name, TechnicalIndicator.name]:
        send_list.append(
            Send(
                node=node,
                arg=AnalysisInputState(portfolio_list=portfolio_list),
            ),
        )
    return send_list


def build_sell_workflow():
    """매도 워크플로우 빌더"""
    workflow = StateGraph(
        state_schema=SellOverallState,
        input_schema=SellInputState,
        output_schema=SellOutputState,
    )

    workflow.add_node(GetPortfolioHoldings.name, GetPortfolioHoldings())
    workflow.add_node(WebSearch.name, WebSearch())
    workflow.add_node(FinancialStatement.name, FinancialStatement())
    workflow.add_node(TechnicalIndicator.name, TechnicalIndicator())
    workflow.add_node(SellDecisionMaker.name, SellDecisionMaker(model="gpt-4.1-mini"))
    workflow.add_node(PortfolioSeller.name, PortfolioSeller())

    workflow.add_edge("__start__", GetPortfolioHoldings.name)
    workflow.add_conditional_edges(GetPortfolioHoldings.name, map_sell_analysis)
    workflow.add_edge(WebSearch.name, SellDecisionMaker.name)
    workflow.add_edge(FinancialStatement.name, SellDecisionMaker.name)
    workflow.add_edge(TechnicalIndicator.name, SellDecisionMaker.name)
    workflow.add_edge(SellDecisionMaker.name, PortfolioSeller.name)
    workflow.add_edge(PortfolioSeller.name, "__end__")

    return workflow.compile(name="portfolio_sell_agent")
