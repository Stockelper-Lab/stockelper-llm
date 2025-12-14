import os
import asyncio
import requests
from pydantic import BaseModel, Field
from portfolio_multi_agent.state import HoldingStock, Stock


class InputState(BaseModel):
    pass


class OutputState(BaseModel):
    holding_stocks: list[HoldingStock] = Field(default_factory=list)


class GetPortfolioHoldings:
    name = "GetPortfolioHoldings"

    def __init__(self):
        """
        보유 종목 조회 노드
        """
        pass

    async def fetch_holdings(
        self, app_key: str, app_secret: str, access_token: str, account_no: str
    ) -> list[HoldingStock]:
        """
        계좌 보유 종목 조회

        Args:
            app_key: API 키
            app_secret: API 시크릿
            access_token: 액세스 토큰
            account_no: 계좌번호 (예: "12345678-01")

        Returns:
            보유 종목 리스트
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

            # output1에 보유 종목 정보가 있음
            output1 = res_data.get("output1", [])

            holdings = []
            for item in output1:
                # 보유 수량이 0보다 큰 종목만 추가
                quantity = int(item.get("hldg_qty", "0"))
                if quantity <= 0:
                    continue

                code = item.get("pdno", "")  # 종목 코드
                name = item.get("prdt_name", "")  # 종목명
                avg_buy_price = float(item.get("pchs_avg_pric", "0"))  # 매입 평균가
                current_price = float(item.get("prpr", "0"))  # 현재가
                evaluated_amount = float(item.get("evlu_amt", "0"))  # 평가 금액
                profit_loss = float(item.get("evlu_pfls_amt", "0"))  # 평가 손익

                # 수익률 계산
                if avg_buy_price > 0:
                    return_rate = (current_price - avg_buy_price) / avg_buy_price
                else:
                    return_rate = 0.0

                holdings.append(
                    HoldingStock(
                        code=code,
                        name=name,
                        quantity=quantity,
                        avg_buy_price=avg_buy_price,
                        current_price=current_price,
                        return_rate=return_rate,
                        evaluated_amount=evaluated_amount,
                        profit_loss=profit_loss,
                    )
                )

            return holdings

    async def __call__(self, state: InputState) -> OutputState:
        """
        보유 종목 조회

        Args:
            state: 입력 상태

        Returns:
            보유 종목 리스트
        """
        # 환경변수에서 API 인증 정보 읽기
        app_key = os.getenv("APP_KEY")
        app_secret = os.getenv("APP_SECRET")
        access_token = os.getenv("ACCESS_TOKEN")
        account_no = os.getenv("ACCOUNT_NO")

        if not all([app_key, app_secret, access_token, account_no]):
            print(
                "[GetPortfolioHoldings] 환경변수 누락: APP_KEY, APP_SECRET, ACCESS_TOKEN, ACCOUNT_NO가 필요합니다."
            )
            return {"holding_stocks": []}

        print(f"[GetPortfolioHoldings] 보유 종목 조회 시작")

        # 보유 종목 조회
        holdings = await self.fetch_holdings(
            app_key, app_secret, access_token, account_no
        )

        print(f"[GetPortfolioHoldings] 보유 종목 {len(holdings)}개 조회 완료")
        for holding in holdings:
            print(
                f"  - {holding.name}({holding.code}): {holding.quantity}주, "
                f"수익률 {holding.return_rate*100:.2f}%, "
                f"평가손익 {holding.profit_loss:,.0f}원"
            )

        return {"holding_stocks": holdings}
