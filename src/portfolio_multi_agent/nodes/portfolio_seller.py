import os
import asyncio
import json
import requests
import time
from pydantic import BaseModel, Field
from portfolio_multi_agent.state import (
    HoldingStock,
    SellDecision,
    OrderResult,
    SellResult,
)


class InputState(BaseModel):
    holding_stocks: list[HoldingStock] = Field(default_factory=list)
    sell_decisions: list[SellDecision] = Field(default_factory=list)


class OutputState(BaseModel):
    sell_result: SellResult | None = Field(default=None)


class PortfolioSeller:
    name = "PortfolioSeller"

    def __init__(self):
        """
        포트폴리오 매도 실행 노드
        """
        pass

    def get_hashkey(
        self, app_key: str, app_secret: str, body_data: dict, url_base: str
    ) -> str:
        """
        주문용 해시키 생성

        Args:
            app_key: API 키
            app_secret: API 시크릿
            body_data: 요청 바디 데이터
            url_base: API 베이스 URL

        Returns:
            해시키 문자열
        """
        url = f"{url_base}/uapi/hashkey"
        headers = {
            "content-type": "application/json",
            "appkey": app_key,
            "appsecret": app_secret,
        }
        res = requests.post(url, headers=headers, data=json.dumps(body_data))
        res.raise_for_status()
        return res.json()["HASH"]

    def execute_sell_order(
        self,
        stock_code: str,
        order_quantity: int,
        app_key: str,
        app_secret: str,
        access_token: str,
        account_no: str,
    ) -> dict:
        """
        시장가 매도 주문 실행

        Args:
            stock_code: 종목 코드
            order_quantity: 주문 수량
            app_key: API 키
            app_secret: API 시크릿
            access_token: 액세스 토큰
            account_no: 계좌번호

        Returns:
            주문 결과 딕셔너리
        """
        url = "https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/order-cash"

        body = {
            "CANO": account_no.split("-")[0],
            "ACNT_PRDT_CD": account_no.split("-")[1],
            "PDNO": stock_code,
            "ORD_DVSN": "01",  # 01: 시장가
            "ORD_QTY": str(order_quantity),
            "ORD_UNPR": "0",  # 시장가는 0
        }

        # hashkey 생성
        hashkey = self.get_hashkey(
            app_key,
            app_secret,
            body,
            "https://openapivts.koreainvestment.com:29443",
        )

        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "VTTC0801U",  # 모의투자 매도
            "custtype": "P",
            "hashkey": hashkey,
        }

        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
        res.raise_for_status()
        data = res.json()
        return data

    async def __call__(self, state: InputState) -> OutputState:
        """
        매도 결정에 따라 실제 매도 주문 실행

        Args:
            state: 입력 상태 (보유 종목, 매도 결정)

        Returns:
            매도 실행 결과
        """
        # 매도 결정 검증
        if not state.sell_decisions:
            print("[PortfolioSeller] 매도할 종목이 없습니다.")
            return {"sell_result": None}

        # 환경변수에서 API 인증 정보 읽기
        app_key = os.getenv("APP_KEY")
        app_secret = os.getenv("APP_SECRET")
        access_token = os.getenv("ACCESS_TOKEN")
        account_no = os.getenv("ACCOUNT_NO")

        if not all([app_key, app_secret, access_token, account_no]):
            print(
                "[PortfolioSeller] 환경변수 누락: APP_KEY, APP_SECRET, ACCESS_TOKEN, ACCOUNT_NO가 필요합니다."
            )
            return {"sell_result": None}

        print(f"[PortfolioSeller] 매도 주문 실행 시작")
        print(f"[PortfolioSeller] 매도 대상 종목: {len(state.sell_decisions)}개")

        # 보유 종목 매핑 (종목 코드 -> HoldingStock)
        holdings_map = {h.code: h for h in state.holding_stocks}

        # 매도 주문 실행
        orders = []
        sold_amount = 0.0
        total_evaluated_amount = sum(h.evaluated_amount for h in state.holding_stocks)

        # Rate Limit 적용
        max_requests_per_second = int(os.getenv("KIS_MAX_REQUESTS_PER_SECOND", "20"))
        batch_size = max_requests_per_second

        # 매도할 종목 리스트 준비
        sell_items = []
        for decision in state.sell_decisions:
            # 보유 종목에서 찾기
            holding = holdings_map.get(decision.code)
            if not holding:
                print(
                    f"[PortfolioSeller] 경고: {decision.name}({decision.code})는 보유하지 않은 종목입니다."
                )
                continue

            # 전체 매도 (보유 수량 전량)
            sell_items.append(
                {
                    "code": decision.code,
                    "name": decision.name,
                    "quantity": holding.quantity,
                    "current_price": holding.current_price,
                    "reasoning": decision.reasoning,
                }
            )

        # 배치 단위로 매도 주문 실행
        time.sleep(1)
        for i in range(0, len(sell_items), batch_size):
            batch = sell_items[i : i + batch_size]

            print(
                f"[PortfolioSeller] 매도 주문 배치 {i//batch_size + 1}/{(len(sell_items) + batch_size - 1)//batch_size}"
            )

            for item in batch:
                print(
                    f"[PortfolioSeller] 매도 주문: {item['name']}({item['code']}) "
                    f"{item['quantity']}주 @ {item['current_price']:,.0f}원"
                )
                print(f"  사유: {item['reasoning']}")

                # 주문 실행
                loop = asyncio.get_event_loop()
                order_result = await loop.run_in_executor(
                    None,
                    lambda c=item["code"], q=item["quantity"]: self.execute_sell_order(
                        c,
                        q,
                        app_key,
                        app_secret,
                        access_token,
                        account_no,
                    ),
                )

                # 주문 결과 저장
                rt_cd = order_result.get("rt_cd")
                msg = order_result.get("msg1", "")

                if rt_cd == "0":
                    status = "success"
                    amount = item["quantity"] * item["current_price"]
                    sold_amount += amount
                    print(f"[PortfolioSeller] 매도 성공: {msg}")
                else:
                    status = "failed"
                    print(f"[PortfolioSeller] 매도 실패: {msg}")

                orders.append(
                    OrderResult(
                        code=item["code"],
                        name=item["name"],
                        quantity=item["quantity"],
                        price=item["current_price"],
                        status=status,
                        message=msg,
                    )
                )

            # 마지막 배치가 아니면 1초 대기 (Rate Limit 준수)
            if i + batch_size < len(sell_items):
                print(
                    f"[PortfolioSeller] 배치 {i//batch_size + 1} 완료. Rate Limit을 위해 1초 대기..."
                )
                await asyncio.sleep(1.0)

        # 결과 생성
        sell_result = SellResult(
            orders=orders,
            total_evaluated_amount=total_evaluated_amount,
            sold_amount=sold_amount,
        )

        print(f"[PortfolioSeller] 매도 완료")
        print(f"[PortfolioSeller] 총 주문: {len(orders)}개")
        print(
            f"[PortfolioSeller] 매도 금액: {sold_amount:,.0f}원 / 총 평가 금액: {total_evaluated_amount:,.0f}원"
        )

        return {"sell_result": sell_result}
