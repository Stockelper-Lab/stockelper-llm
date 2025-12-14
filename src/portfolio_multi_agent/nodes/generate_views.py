import os
import json
from pydantic import BaseModel, Field
from portfolio_multi_agent.state import Stock, AnalysisResult, InvestorView
from portfolio_multi_agent.utils import JsonOutputParser
from langchain_openai import ChatOpenAI


class ViewResponseSchema(BaseModel):
    """투자자 뷰 응답 스키마"""

    expected_return: float = Field(
        ...,
        description="향후 1년간 예상되는 초과 수익률 (소수점 형식, 예: 0.10은 10%). 범위: -0.20 ~ 0.20",
    )
    confidence: float = Field(
        ...,
        description="예측에 대한 신뢰도 (0.0 ~ 1.0). 0.8~1.0: 모든 분석 일치, 0.6~0.8: 대부분 일치, 0.4~0.6: 혼재, 0.2~0.4: 상충, 0.0~0.2: 정보 부족",
    )
    reasoning: str = Field(..., description="판단 근거 (2-3문장으로 간결하게)")


class InputState(BaseModel):
    portfolio_list: list[Stock] = Field(default_factory=list)
    analysis_results: list[AnalysisResult] = Field(default_factory=list)


class OutputState(BaseModel):
    investor_views: list[InvestorView] = Field(default_factory=list)


class ViewGenerator:
    name = "ViewGenerator"

    SYSTEM_TEMPLATE = """당신은 전문 투자 분석가입니다. 제공된 세 가지 분석 결과(웹 검색, 재무제표, 기술적 지표)를 종합하여 투자 의견을 제시하는 것이 당신의 임무입니다.

**수익률 가이드라인:**
- 매우 강세: 0.10 ~ 0.15 (10~15%)
- 강세: 0.05 ~ 0.10 (5~10%)
- 약한 강세: 0.02 ~ 0.05 (2~5%)
- 중립: -0.02 ~ 0.02 (-2~2%)
- 약한 약세: -0.05 ~ -0.02 (-5~-2%)
- 약세: -0.10 ~ -0.05 (-10~-5%)
- 매우 약세: -0.15 ~ -0.10 (-15~-10%)

**신뢰도 가이드라인:**
- 0.8 ~ 1.0: 세 가지 분석이 모두 일치하고 명확한 신호
- 0.6 ~ 0.8: 대부분의 분석이 일치
- 0.4 ~ 0.6: 분석 결과가 혼재되어 있음
- 0.2 ~ 0.4: 분석 결과가 상충하거나 불확실
- 0.0 ~ 0.2: 정보 부족 또는 매우 불확실

**주의사항:**
- 세 가지 분석 결과를 모두 고려하여 종합적으로 판단하세요
- expected_return은 -0.20에서 0.20 사이의 값이어야 합니다
- confidence는 0.0에서 1.0 사이의 값이어야 합니다
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
- 종목명: {stock_name}
- 종목코드: {stock_code}

**분석 결과:**

1. **웹 검색 분석 (최근 뉴스 및 시장 동향):**
{web_search}

2. **재무제표 분석:**
{financial_statement}

3. **기술적 지표 분석:**
{technical_indicator}

---

위 세 가지 분석 결과를 종합하여 투자 의견을 JSON 형식으로 제공해주세요."""

    def __init__(self, model: str = "gpt-4o"):
        """
        투자자 뷰 생성기

        Args:
            model: 사용할 LLM 모델 (기본값: gpt-4o)
        """
        llm = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            model=model,
            api_key=os.getenv("OPENROUTER_API_KEY"),
            temperature=0.3,  # 일관성 있는 결과를 위해 낮은 temperature
        )
        self.chain = llm | JsonOutputParser(response_schema=ViewResponseSchema)

    async def __call__(self, state: InputState) -> OutputState:
        """
        모든 종목에 대한 투자자 뷰 생성

        Args:
            state: 입력 상태 (종목 리스트, 분석 결과)

        Returns:
            투자자 뷰 리스트
        """
        if not state.portfolio_list:
            return {"investor_views": []}

        # 종목별로 분석 결과 그룹화
        grouped_analyses = self.group_analysis_by_stock(
            state.portfolio_list, state.analysis_results
        )

        # 각 종목에 대한 뷰 생성
        investor_views = []

        for index, stock in enumerate(state.portfolio_list):
            analyses = grouped_analyses.get(stock.code, {})

            view = await self.generate_view_for_stock(
                stock_index=index,
                stock_name=stock.name,
                stock_code=stock.code,
                analyses=analyses,
            )

            if view:
                investor_views.append(view)

        return {"investor_views": investor_views}

    def group_analysis_by_stock(
        self, portfolio_list: list[Stock], analysis_results: list[AnalysisResult]
    ) -> dict[str, dict[str, str]]:
        """
        종목별로 분석 결과를 그룹화

        Args:
            portfolio_list: 종목 리스트
            analysis_results: 모든 분석 결과

        Returns:
            {종목코드: {분석타입: 분석결과}} 형태의 딕셔너리
        """
        grouped = {}

        for stock in portfolio_list:
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

    async def generate_view_for_stock(
        self,
        stock_index: int,
        stock_name: str,
        stock_code: str,
        analyses: dict[str, str],
    ) -> InvestorView | None:
        """
        단일 종목에 대한 투자자 뷰 생성

        Args:
            stock_index: 종목 인덱스 (portfolio_list에서의 위치)
            stock_name: 종목명
            stock_code: 종목 코드
            analyses: 분석 결과 딕셔너리

        Returns:
            InvestorView 객체 또는 None
        """
        # 분석 결과가 하나라도 있는지 확인
        has_analysis = any(
            analyses.get(key)
            for key in ["web_search", "financial_statement", "technical_indicator"]
        )

        if not has_analysis:
            # 분석 결과가 없으면 중립적인 뷰 반환
            return InvestorView(
                stock_indices=[stock_index],
                expected_return=0.0,
                confidence=0.3,
                reasoning="분석 데이터가 부족하여 중립적 입장을 유지합니다.",
            )

        messages = [
            {
                "role": "system",
                "content": self.SYSTEM_TEMPLATE.format(
                    response_schema=json.dumps(
                        ViewResponseSchema.model_json_schema(),
                        indent=2,
                        ensure_ascii=False,
                    )
                ),
            },
            {
                "role": "user",
                "content": self.USER_TEMPLATE.format(
                    stock_name=stock_name,
                    stock_code=stock_code,
                    **analyses,
                ),
            },
        ]

        # LLM 체인 실행
        response = await self.chain.ainvoke(messages)

        expected_return = float(response.get("expected_return", 0.0))
        confidence = float(response.get("confidence", 0.5))
        reasoning = str(response.get("reasoning", ""))

        # 값 검증 및 제한
        expected_return = max(-0.20, min(0.20, expected_return))  # -20% ~ 20%
        confidence = max(0.0, min(1.0, confidence))  # 0.0 ~ 1.0

        return InvestorView(
            stock_indices=[stock_index],
            expected_return=expected_return,
            confidence=confidence,
            reasoning=reasoning,
        )
