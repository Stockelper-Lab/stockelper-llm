from typing import Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    user_id: int = Field(
        description="실행 ID",
        default=1
    )
    thread_id: str = Field(
        description="스레드 ID",
        default="test_thread_id"
    )
    message: str = Field(
        description="채팅 메시지",
        default="삼성전자에 대한 투자전략을 추천해줘"
    )
    human_feedback: Optional[bool] = Field(
        description="사용자 피드백",
        default=None
    )

class StreamingStatus(BaseModel):
    type: str = Field(description="메시지 타입: 'progress'", default="progress")
    step: str = Field(description="현재 실행 단계 (agent명, tool명 등)")
    status: str = Field(description="상태: 'start' | 'end'")

class FinalResponse(BaseModel):
    type: str = Field(description="메시지 타입: 'final'", default="final")
    message: str = Field(
        description="채팅 메시지",
        default=""
    )
    subgraph: dict = Field(
        description="종목에 대한 서브그래프. 만약 서브그래프가 없는경우 빈 딕셔너리를 반환",
        default_factory=dict
    )
    trading_action: Optional[dict] = Field(
        description="투자전략 추천시 구체적인 트레이딩 액션. 트레이딩 액션이 없는 경우 None. order_side는 buy, sell 중 하나. order_type는 market, limit 중 하나. order_price는 주문 가격으로 order_type이 limit인 경우에만 주문 가격이 존재하고 market인 경우 null. order_quantity는 주문 수량.",
        default=None
    )
    error: Optional[str] = Field(
        description="에러 메시지",
        default=None
    )