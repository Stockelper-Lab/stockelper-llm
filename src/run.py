import asyncio
from dotenv import load_dotenv
from portfolio_multi_agent.builder import build


load_dotenv(override=True)


async def main():
    workflow = build()
    result = await workflow.ainvoke(
        {
            "rank_weight": {
                "profitability": 0.25,
                "stability": 0.25,
                "growth": 0.25,
                "market_cap": 0.25,
            }
        }
    )
    
    # 결과 출력
    portfolio_result = result.get("portfolio_result")
    
    if not portfolio_result:
        print("포트폴리오 결과를 생성할 수 없습니다.")
        return
    
    print("\n" + "=" * 60)
    print("포트폴리오 분석 결과")
    print("=" * 60)
    
    # 1. 종목 구성 출력 (먼저)
    print("\n[종목 구성]\n")
    
    weights = portfolio_result.weights
    for i, weight in enumerate(weights, 1):
        print(f"{i}. {weight.name} ({weight.code}) - {weight.weight * 100:.1f}%")
        if weight.reasoning:
            # reasoning을 들여쓰기하여 출력
            print(f"   {weight.reasoning}")
        print()
    
    # 2. 성과 지표 출력 (나중에)
    print("[성과 지표]\n")
    metrics = portfolio_result.metrics
    print(f"예상 수익률: {metrics.expected_return * 100:.2f}%")
    print(f"변동성: {metrics.volatility * 100:.2f}%")
    print(f"샤프 비율: {metrics.sharpe_ratio:.2f}")
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
