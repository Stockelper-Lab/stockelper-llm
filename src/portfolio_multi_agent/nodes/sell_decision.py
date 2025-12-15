import os
import json
from typing import Literal
from pydantic import BaseModel, Field
from portfolio_multi_agent.state import HoldingStock, AnalysisResult, SellDecision
from portfolio_multi_agent.utils import JsonOutputParser
from langchain_openai import ChatOpenAI


class SellDecisionResponseSchema(BaseModel):
    """매도 결정 응답 스키마"""

    decision: Literal["SELL", "HOLD"] = Field(
        ..., description="매도 결정 (SELL: 매도, HOLD: 보유)"
    )
    reasoning: str = Field(..., description="결정 사유 (2-3문장으로 간결하게)")


class InputState(BaseModel):
    holding_stocks: list[HoldingStock] = Field(default_factory=list)
    analysis_results: list[AnalysisResult] = Field(default_factory=list)
    loss_threshold: float = Field(default=-0.10)
    profit_threshold: float = Field(default=0.20)


class OutputState(BaseModel):
    sell_decisions: list[SellDecision] = Field(default_factory=list)


class SellDecisionMaker:
    name = "SellDecisionMaker"

    SYSTEM_TEMPLATE = """당신은 전문 투자 분석가입니다. 보유 종목의 정보와 분석 결과를 바탕으로 해당 종목을 매도할지 결정하는 것이 당신의 임무입니다.

**매도 기준:**
1. 손절: 손실률이 {loss_threshold_pct}% 이하인 경우
2. 익절: 수익률이 {profit_threshold_pct}% 이상인 경우
3. 펀더멘털 악화: 재무제표 지표가 크게 악화된 경우
4. 기술적 지표 악화: 기술적 지표가 매도 신호를 보이는 경우
5. 부정적 뉴스: 부정적인 뉴스나 리스크 요인이 있는 경우
6. 산업 전망 악화: 산업 전망이 부정적인 경우

**결정 가이드라인:**
- SELL: 위 기준 중 2개 이상이 충족되거나, 1개 기준이 매우 명확하게 충족되는 경우
- HOLD: 위 기준이 충족되지 않거나, 긍정적 요인이 부정적 요인보다 우세한 경우

**주의사항:**
- 세 가지 분석 결과(웹 검색, 재무제표, 기술적 지표)를 모두 고려하여 종합적으로 판단하세요
- decision은 "SELL" 또는 "HOLD" 중 하나여야 합니다
- reasoning은 간결하게 2-3문장으로 작성하세요

The output should be formatted as a JSON instance that conforms to the JSON schema below.
As an example, for the schema {{"properties": {{"foo": {{"title": "Foo", "description": "a list of strings", "type": "array", "items": {{"type": "string"}}}}}}, "required": ["foo"]}}
the object {{"foo": ["bar", "baz"]}} is a well-formatted instance of the schema. The object {{"properties": {{"foo": ["bar", "baz"]}}}} is not well-formatted.
Here is the output schema:
```json
{response_schema}
```
"""

    USER_TEMPLATE = """**종목 정보:**
- 종목명: {name} ({code})
- 보유 수량: {quantity}주
- 평균 매입가: {avg_buy_price}원
- 현재가: {current_price}원
- 수익률: {return_rate}%
- 평가 금액: {evaluated_amount}원
- 평가 손익: {profit_loss}원

**분석 결과:**

1. **웹 검색 분석 (최근 뉴스 및 시장 동향):**
{web_search}

2. **재무제표 분석:**
{financial_statement}

3. **기술적 지표 분석:**
{technical_indicator}

---

위 정보를 종합하여 이 종목을 매도해야 할지 판단하고, JSON 형식으로 제공해주세요."""

    def __init__(self, model: str = "gpt-4o"):
        """
        매도 결정 생성기

        Args:
            model: 사용할 LLM 모델 (기본값: gpt-4o)
        """
        llm = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            model=model,
            api_key=os.getenv("OPENROUTER_API_KEY"),
            temperature=0.1,  # 일관성 있는 결과를 위해 낮은 temperature
        )
        self.chain = llm | JsonOutputParser(response_schema=SellDecisionResponseSchema)

    async def __call__(self, state: InputState) -> OutputState:
        """
        보유 종목 분석 결과를 기반으로 매도할 종목을 결정

        Args:
            state: 입력 상태 (보유 종목, 분석 결과, 매도 기준)

        Returns:
            매도 결정 리스트
        """
        if not state.holding_stocks:
            print("[SellDecisionMaker] 보유 종목이 없습니다.")
            return {"sell_decisions": []}

        # 종목별로 분석 결과 그룹화
        grouped_analyses = self.group_analysis_by_stock(
            state.holding_stocks, state.analysis_results
        )

        # 각 보유 종목별로 매도 결정
        sell_decisions = []

        for holding in state.holding_stocks:
            analyses = grouped_analyses.get(holding.code, {})

            decision = await self.make_decision_for_stock(
                holding=holding,
                analyses=analyses,
                loss_threshold=state.loss_threshold,
                profit_threshold=state.profit_threshold,
            )

            if decision:
                sell_decisions.append(decision)

        return {"sell_decisions": sell_decisions}

    def group_analysis_by_stock(
        self,
        holding_stocks: list[HoldingStock],
        analysis_results: list[AnalysisResult],
    ) -> dict[str, dict[str, str]]:
        """
        종목별로 분석 결과를 그룹화

        Args:
            holding_stocks: 보유 종목 리스트
            analysis_results: 모든 분석 결과

        Returns:
            {종목코드: {분석타입: 분석결과}} 형태의 딕셔너리
        """
        grouped = {}

        for stock in holding_stocks:
            grouped[stock.code] = {
                "name": stock.name,
                "web_search": "",
                "financial_statement": "",
                "technical_indicator": "",
            }

        # 분석 결과를 종목별로 분류
        for result in analysis_results:
            if result.code in grouped:
                grouped[result.code][result.type] = result.result

        return grouped

    async def make_decision_for_stock(
        self,
        holding: HoldingStock,
        analyses: dict[str, str],
        loss_threshold: float,
        profit_threshold: float,
    ) -> SellDecision | None:
        """
        단일 종목에 대한 매도 결정

        Args:
            holding: 보유 종목 정보
            analyses: 분석 결과 딕셔너리
            loss_threshold: 손실 매도 기준
            profit_threshold: 익절 매도 기준

        Returns:
            SellDecision 객체 또는 None
        """
        # 분석 결과가 하나라도 있는지 확인
        has_analysis = any(
            analyses.get(key)
            for key in ["web_search", "financial_statement", "technical_indicator"]
        )

        if not has_analysis:
            # 분석 결과가 없으면 보유 결정
            return None

        # 메시지 구성
        messages = [
            {
                "role": "system",
                "content": self.SYSTEM_TEMPLATE.format(
                    loss_threshold_pct=loss_threshold * 100,
                    profit_threshold_pct=profit_threshold * 100,
                    response_schema=json.dumps(
                        SellDecisionResponseSchema.model_json_schema(),
                        indent=2,
                        ensure_ascii=False,
                    ),
                ),
            },
            {
                "role": "user",
                "content": self.USER_TEMPLATE.format(
                    **{**holding.model_dump(), **analyses}
                ),
            },
        ]

        # LLM 체인 실행
        response = await self.chain.ainvoke(messages)

        decision = str(response.get("decision", "HOLD"))
        reasoning = str(response.get("reasoning", ""))

        # SELL인 경우에만 SellDecision 반환
        if decision == "SELL":
            return SellDecision(
                code=holding.code, name=holding.name, reasoning=reasoning
            )
        else:
            return None
