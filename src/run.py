import asyncio
import argparse
from dotenv import load_dotenv
from portfolio_multi_agent.builder import build_buy_workflow, build_sell_workflow


load_dotenv(override=True)


async def run_buy_workflow():
    """매수 워크플로우 실행"""
    print("\n" + "=" * 60)
    print("매수 워크플로우 실행")
    print("=" * 60 + "\n")

    workflow = build_buy_workflow()
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


async def run_sell_workflow():
    """매도 워크플로우 실행"""
    print("\n" + "=" * 60)
    print("매도 워크플로우 실행")
    print("=" * 60 + "\n")

    workflow = build_sell_workflow()
    result = await workflow.ainvoke(
        {
            "loss_threshold": -0.10,  # -10% 손실 시 매도
            "profit_threshold": 0.20,  # 20% 수익 시 익절
        }
    )

    # 결과 출력
    holding_stocks = result.get("holding_stocks", [])
    sell_decisions = result.get("sell_decisions", [])
    sell_result = result.get("sell_result")

    print("\n" + "=" * 60)
    print("매도 분석 결과")
    print("=" * 60)

    # 1. 보유 종목 출력
    print("\n[보유 종목]\n")
    if not holding_stocks:
        print("보유 종목이 없습니다.")
    else:
        for i, stock in enumerate(holding_stocks, 1):
            print(f"{i}. {stock.name} ({stock.code})")
            print(f"   보유 수량: {stock.quantity}주")
            print(f"   평균 매입가: {stock.avg_buy_price:,.0f}원")
            print(f"   현재가: {stock.current_price:,.0f}원")
            print(f"   수익률: {stock.return_rate * 100:.2f}%")
            print(f"   평가 손익: {stock.profit_loss:,.0f}원")
            print()

    # 2. 매도 결정 출력
    print("[매도 결정]\n")
    if not sell_decisions:
        print("매도할 종목이 없습니다.")
    else:
        for i, decision in enumerate(sell_decisions, 1):
            print(f"{i}. {decision.name} ({decision.code})")
            print(f"   사유: {decision.reasoning}")
            print()

    # 3. 매도 실행 결과 출력
    if sell_result:
        print("[매도 실행 결과]\n")
        print(f"총 평가 금액: {sell_result.total_evaluated_amount:,.0f}원")
        print(f"매도 금액: {sell_result.sold_amount:,.0f}원")
        print(f"\n주문 결과:")
        for i, order in enumerate(sell_result.orders, 1):
            status_text = "성공" if order.status == "success" else "실패"
            print(
                f"{i}. {order.name} ({order.code}): {order.quantity}주 @ {order.price:,.0f}원 - {status_text}"
            )
            if order.message:
                print(f"   메시지: {order.message}")

    print("\n" + "=" * 60 + "\n")


async def main():
    parser = argparse.ArgumentParser(description="포트폴리오 매수/매도 워크플로우 실행")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["buy", "sell"],
        default="buy",
        help="워크플로우 모드 선택 (buy: 매수, sell: 매도)",
    )

    args = parser.parse_args()

    if args.mode == "buy":
        await run_buy_workflow()
    elif args.mode == "sell":
        await run_sell_workflow()


if __name__ == "__main__":
    asyncio.run(main())
