import os
import asyncio
import json
import requests
import time
from datetime import datetime
from pydantic import BaseModel, Field
from portfolio_multi_agent.state import (
    PortfolioResult,
    OrderResult,
    TradingResult,
)


class InputState(BaseModel):
    portfolio_result: PortfolioResult | None = Field(default=None)


class OutputState(BaseModel):
    trading_result: TradingResult | None = Field(default=None)


class PortfolioTrader:
    name = "PortfolioTrader"

    def __init__(self):
        """
        포트폴리오 트레이더 (실제 주문 실행)
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

    async def fetch_account_balance(
        self, app_key: str, app_secret: str, access_token: str, account_no: str
    ) -> float:
        """
        계좌 잔고 조회 (사용 가능한 현금)

        Args:
            app_key: API 키
            app_secret: API 시크릿
            access_token: 액세스 토큰
            account_no: 계좌번호 (예: "12345678-01")

        Returns:
            사용 가능한 현금
        """
        url = "https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appKey": app_key,
            "appSecret": app_secret,
            "tr_id": "VTTC8434R",  # 모의투자 계좌 잔고 조회
            "custtype": "P",  # 고객타입 - P: 개인
        }
        params = {
            "CANO": account_no.split("-")[0],  # 계좌번호
            "ACNT_PRDT_CD": account_no.split("-")[1],
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        async with asyncio.timeout(30):
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: requests.get(url, headers=headers, params=params)
            )
            response.raise_for_status()
            res_data = response.json()

            # 응답 코드 확인
            if res_data.get("rt_cd") != "0":
                raise ValueError(f"API 오류: {res_data.get('msg1', '알 수 없는 오류')}")

            output = res_data.get("output2", [{}])[0]
            cash = float(output.get("dnca_tot_amt", 0))  # 예수금총금액
            return cash

    async def fetch_current_price(
        self, stock_code: str, app_key: str, app_secret: str, access_token: str
    ) -> float:
        """
        종목 현재가 조회

        Args:
            stock_code: 종목 코드
            app_key: API 키
            app_secret: API 시크릿
            access_token: 액세스 토큰

        Returns:
            현재가
        """
        url_base = "https://openapivts.koreainvestment.com:29443"
        path = "uapi/domestic-stock/v1/quotations/inquire-price"
        url = f"{url_base}/{path}"

        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST01010100",
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
        }

        async with asyncio.timeout(30):
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: requests.get(url, headers=headers, params=params)
            )
            response.raise_for_status()
            res_body = response.json()

            # 응답 코드 확인
            if res_body.get("rt_cd") != "0":
                raise ValueError(
                    f"현재가 조회 실패: {res_body.get('msg1', '알 수 없는 오류')}"
                )

            output = res_body.get("output", {})
            price = float(output.get("stck_prpr", 0))
            return price

    def execute_order(
        self,
        stock_code: str,
        order_quantity: int,
        app_key: str,
        app_secret: str,
        access_token: str,
        account_no: str,
    ) -> dict:
        """
        시장가 매수 주문 실행

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
            "tr_id": "VTTC0802U",  # 모의투자 매수
            "custtype": "P",
            "hashkey": hashkey,
        }

        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
        res.raise_for_status()
        data = res.json()
        return data

    async def __call__(self, state: InputState) -> OutputState:
        """
        포트폴리오 비중에 따라 실제 주문 실행

        Args:
            state: 입력 상태 (포트폴리오 결과)

        Returns:
            트레이딩 결과
        """
        # 포트폴리오 결과 검증
        if not state.portfolio_result or not state.portfolio_result.weights:
            return {"trading_result": None}

        # 환경변수에서 API 인증 정보 읽기
        app_key = os.getenv("APP_KEY")
        app_secret = os.getenv("APP_SECRET")
        access_token = os.getenv("ACCESS_TOKEN")
        account_no = os.getenv("ACCOUNT_NO")

        print(f"[PortfolioTrader] Starting trading execution")
        print(f"[PortfolioTrader] Portfolio has {len(state.portfolio_result.weights)} stocks")

        # 1. 계좌 잔고 조회
        total_cash = await self.fetch_account_balance(
            app_key, app_secret, access_token, account_no
        )
        print(f"[PortfolioTrader] Available cash: {total_cash:,.0f}원")

        # 2. 각 종목의 현재가 조회 (Rate Limit 적용한 병렬 처리)
        time.sleep(1)
        max_requests_per_second = int(os.getenv("KIS_MAX_REQUESTS_PER_SECOND", "20"))
        batch_size = max_requests_per_second
        all_prices = []

        for i in range(0, len(state.portfolio_result.weights), batch_size):
            batch = state.portfolio_result.weights[i : i + batch_size]

            # 배치 내 종목들을 병렬로 처리
            price_tasks = [
                self.fetch_current_price(weight.code, app_key, app_secret, access_token)
                for weight in batch
            ]
            batch_prices = await asyncio.gather(*price_tasks)
            all_prices.extend(batch_prices)

            # 마지막 배치가 아니면 1초 대기 (Rate Limit 준수)
            if i + batch_size < len(state.portfolio_result.weights):
                print(
                    f"[PortfolioTrader] Batch {i//batch_size + 1} completed. Waiting 1 second for rate limit..."
                )
                await asyncio.sleep(1.0)

        prices = all_prices

        # 3. 종목별 현재가 매핑
        stock_prices = {
            weight.code: price
            for weight, price in zip(state.portfolio_result.weights, prices)
        }

        print(f"[PortfolioTrader] Fetched prices for {len(stock_prices)} stocks")

        # 4. 각 종목별 주문 실행 (Rate Limit 적용)
        orders = []
        used_cash = 0.0

        # 주문할 종목 리스트 준비
        order_items = []
        for weight in state.portfolio_result.weights:
            stock_code = weight.code
            stock_name = weight.name
            target_weight = weight.weight
            current_price = stock_prices[stock_code]

            # 매수 금액 계산
            target_amount = total_cash * target_weight

            # 매수 수량 계산 (정수로 내림)
            quantity = int(target_amount / current_price)

            if quantity == 0:
                print(
                    f"[PortfolioTrader] Skipping {stock_name}({stock_code}): quantity is 0"
                )
                continue

            # 실제 사용 금액
            actual_amount = quantity * current_price
            used_cash += actual_amount

            order_items.append(
                {
                    "code": stock_code,
                    "name": stock_name,
                    "quantity": quantity,
                    "price": current_price,
                    "amount": actual_amount,
                }
            )

        # 배치 단위로 주문 실행
        time.sleep(1)
        for i in range(0, len(order_items), batch_size):
            batch = order_items[i : i + batch_size]

            print(
                f"[PortfolioTrader] Processing order batch {i//batch_size + 1}/{(len(order_items) + batch_size - 1)//batch_size}"
            )

            for item in batch:
                print(
                    f"[PortfolioTrader] Ordering {item['name']}({item['code']}): {item['quantity']}주 @ {item['price']:,.0f}원 = {item['amount']:,.0f}원"
                )

                # 주문 실행
                loop = asyncio.get_event_loop()
                order_result = await loop.run_in_executor(
                    None,
                    lambda c=item["code"], q=item["quantity"]: self.execute_order(
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
                    print(f"[PortfolioTrader] Order success: {msg}")
                else:
                    status = "failed"
                    print(f"[PortfolioTrader] Order failed: {msg}")

                orders.append(
                    OrderResult(
                        code=item["code"],
                        name=item["name"],
                        quantity=item["quantity"],
                        price=item["price"],
                        status=status,
                        message=msg,
                    )
                )

            # 마지막 배치가 아니면 1초 대기 (Rate Limit 준수)
            if i + batch_size < len(order_items):
                print(
                    f"[PortfolioTrader] Order batch {i//batch_size + 1} completed. Waiting 1 second for rate limit..."
                )
                await asyncio.sleep(1.0)

        # 5. 결과 생성
        trading_result = TradingResult(
            orders=orders, total_cash=total_cash, used_cash=used_cash
        )

        print(f"[PortfolioTrader] Trading completed")
        print(f"[PortfolioTrader] Total orders: {len(orders)}")
        print(f"[PortfolioTrader] Used cash: {used_cash:,.0f}원 / {total_cash:,.0f}원")

        return {"trading_result": trading_result}
