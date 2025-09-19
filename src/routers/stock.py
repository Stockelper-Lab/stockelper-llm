import os
import json
import logging
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from langfuse.langchain import CallbackHandler

from multi_agent import multi_agent
from .models import ChatRequest, StreamingStatus, FinalResponse

logger = logging.getLogger(__name__)

langfuse_handler = CallbackHandler()

CHECKPOINT_DATABASE_URI = os.getenv("CHECKPOINT_DATABASE_URI")

router = APIRouter(prefix="/stock", tags=["stock"])

async def generate_sse_response(multi_agent, input_state, user_id, thread_id):
    """풀의 생명주기를 스트리밍과 맞춰 관리하는 SSE 응답 생성기"""
    try:
        # 스트리밍 함수 내부에서 풀 생성 및 관리
        async with AsyncConnectionPool(
            conninfo=CHECKPOINT_DATABASE_URI, 
            kwargs={"autocommit": True}
        ) as pool:
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
            
            # 멀티에이전트에 체크포인터 설정
            multi_agent.checkpointer = checkpointer
            
            # config 구성
            config = {
                "callbacks": [langfuse_handler],
                "metadata": {
                    "langfuse_session_id": thread_id,
                    "langfuse_user_id": user_id,
                },
                "configurable": {
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "max_execute_agent_count": 5,
                },
            }
            
            final_response = FinalResponse()
            async for response_type, response in multi_agent.astream(
                input_state, 
                config=config,
                stream_mode=["custom", "values"],
            ):
                if response_type == "custom":
                    streaming_response = StreamingStatus(
                        type="progress",
                        step=response.get("step", "unknown"),
                        status=response.get("status", "unknown")
                    )
                    yield f"data: {json.dumps(streaming_response.model_dump(), ensure_ascii=False)}\n\n"
                    
                elif response_type == "values":
                    final_response = FinalResponse(
                        type="final",
                        message=response.get("messages", [{}])[-1].content,
                        subgraph=response.get("subgraph", {}),
                        trading_action=response.get("trading_action")
                    )
            yield f"data: {json.dumps(final_response.model_dump(), ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        
    except Exception as e:
        # 에러 발생 시 에러 응답 전송
        error_response = FinalResponse(
            message="처리 중 오류가 발생했습니다.",
            error=str(e)
        )
        yield f"data: {json.dumps(error_response.model_dump(), ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"


@router.post("/chat", status_code=status.HTTP_200_OK)
async def stock_chat(request: ChatRequest) -> StreamingResponse:
    try:
        user_id = request.user_id
        thread_id = request.thread_id
        query = request.message
        human_feedback = request.human_feedback

        logger.info(f"Received query: {query}")

        # 입력 상태 구성
        if human_feedback is None:
            input_state = {"messages": [{"role": "user", "content": query}]}
        else:
            input_state = Command(resume=human_feedback)

        return StreamingResponse(
            generate_sse_response(multi_agent, input_state, user_id, thread_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
            }
        )

    except Exception as e:
        import traceback

        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error in stock_chat: {error_msg}")
        
        # 에러 시에도 SSE 응답으로 에러 전송
        async def error_stream():
            error_response = FinalResponse(
                message="처리 중 오류가 발생했습니다.",
                error=error_msg
            )
            yield f"data: {json.dumps(error_response.model_dump(), ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        
        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
            }
        ) 