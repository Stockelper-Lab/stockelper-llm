import os
import json
import logging
import re
import httpx
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from multi_agent import get_multi_agent
from langchain_compat import iter_stream_tokens, message_to_text
from .models import ChatRequest, StreamingStatus, FinalResponse

logger = logging.getLogger(__name__)

_LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() not in {"0", "false", "no"}
_BACKTESTING_SERVICE_URL = os.getenv("STOCKELPER_BACKTESTING_URL", "").strip()

# LangChain v1에서 langfuse.langchain 통합이 깨질 수 있어(legacy import 의존),
# Langfuse는 옵션으로만 활성화한다.
_langfuse_handler = None
if _LANGFUSE_ENABLED:
    try:
        from langfuse.langchain import CallbackHandler  # type: ignore

        _langfuse_handler = CallbackHandler()
    except Exception:
        _langfuse_handler = None

CHECKPOINT_DATABASE_URI = os.getenv("CHECKPOINT_DATABASE_URI")

router = APIRouter(prefix="/stock", tags=["stock"])

_PORTFOLIO_BLOCK_PAT = re.compile(r"(포트폴리오\s*추천|자산\s*배분|리밸런싱)", re.IGNORECASE)
_BACKTEST_PAT = re.compile(r"(백테스트|백테스팅|backtest|backtesting)", re.IGNORECASE)


def _is_portfolio_recommendation_request(text: str) -> bool:
    return bool(_PORTFOLIO_BLOCK_PAT.search(text or ""))


def _is_backtest_request(text: str) -> bool:
    return bool(_BACKTEST_PAT.search(text or ""))


async def generate_simple_sse(message: str):
    """멀티에이전트를 실행하지 않는 단순 SSE 응답(차단/가이드/즉시응답)."""
    final_response = FinalResponse(type="final", message=message, subgraph={}, trading_action=None)
    for token in iter_stream_tokens(message):
        yield f"data: {{\"type\": \"delta\", \"token\": {json.dumps(token, ensure_ascii=False)} }}\n\n"
    yield f"data: {json.dumps(final_response.model_dump(), ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


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
                "callbacks": ([_langfuse_handler] if _langfuse_handler is not None else []),
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
                    # 최종 메시지를 토큰 단위(delta)로 스트리밍 후 마지막에 final 전송
                    last_msg = response.get("messages", [])[-1] if response.get("messages") else None
                    message_text = message_to_text(last_msg)
                    for token in iter_stream_tokens(message_text):
                        yield f"data: {{\"type\": \"delta\", \"token\": {json.dumps(token, ensure_ascii=False)} }}\n\n"

                    final_response = FinalResponse(
                        type="final",
                        message=message_text,
                        subgraph=response.get("subgraph", {}),
                        trading_action=response.get("trading_action")
                    )
            # 최종 응답과 종료 신호 전송
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
        # 멀티에이전트 인스턴스 확보 (캐시)
        async_db_url = os.getenv("ASYNC_DATABASE_URL")
        multi_agent = get_multi_agent(async_db_url)
        user_id = request.user_id
        thread_id = request.thread_id
        query = request.message
        human_feedback = request.human_feedback

        logger.info(f"Received query: {query}")

        # 입력 상태 구성
        if human_feedback is None:
            # 요구사항: 포트폴리오 추천은 챗봇에서 실행하지 않음(전용 페이지로 유도)
            if _is_portfolio_recommendation_request(query):
                guide = (
                    "포트폴리오 추천 기능은 챗봇에서 실행하지 않습니다.\n"
                    "포트폴리오 추천 페이지에서 버튼을 눌러 실행해주세요."
                )
                return StreamingResponse(
                    generate_simple_sse(guide),
                    media_type="text/event-stream; charset=utf-8",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "Content-Type": "text/event-stream; charset=utf-8",
                        "X-Accel-Buffering": "no",
                    },
                )

            # 요구사항: 백테스팅은 챗봇에서 '실행중' 안내 후, 완료 알림으로 별도 전달
            if _is_backtest_request(query):
                if not _BACKTESTING_SERVICE_URL:
                    msg = (
                        "백테스팅 기능은 별도 서비스로 분리되어 있습니다.\n"
                        "백테스팅 서버를 실행한 뒤, 환경변수 STOCKELPER_BACKTESTING_URL을 설정해주세요.\n"
                        "예) STOCKELPER_BACKTESTING_URL=http://localhost:21011"
                    )
                    return StreamingResponse(
                        generate_simple_sse(msg),
                        media_type="text/event-stream; charset=utf-8",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                            "Content-Type": "text/event-stream; charset=utf-8",
                            "X-Accel-Buffering": "no",
                        },
                    )

                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            f"{_BACKTESTING_SERVICE_URL.rstrip('/')}/api/backtesting/execute",
                            json={
                                "user_id": user_id,
                                "stock_symbol": None,
                                "strategy_type": None,
                                "query": query,
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        job_id = data.get("job_id") or data.get("jobId")
                except Exception as e:
                    logger.warning(
                        "Failed to enqueue backtest via STOCKELPER_BACKTESTING_URL=%s: %s",
                        _BACKTESTING_SERVICE_URL,
                        e,
                    )
                    msg = (
                        "백테스팅 요청에 실패했습니다.\n"
                        "백테스팅 서버 상태를 확인한 뒤 다시 시도해주세요."
                    )
                    return StreamingResponse(
                        generate_simple_sse(msg),
                        media_type="text/event-stream; charset=utf-8",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                            "Content-Type": "text/event-stream; charset=utf-8",
                            "X-Accel-Buffering": "no",
                        },
                    )

                msg = (
                    f"백테스팅을 시작했습니다. (job_id={job_id})\n"
                    "약 5~10분 정도 소요될 수 있으며, 완료되면 알림으로 알려드릴게요."
                )
                return StreamingResponse(
                    generate_simple_sse(msg),
                    media_type="text/event-stream; charset=utf-8",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "Content-Type": "text/event-stream; charset=utf-8",
                        "X-Accel-Buffering": "no",
                    },
                )

            input_state = {"messages": [{"role": "user", "content": query}]}
        else:
            input_state = Command(resume=human_feedback)

        return StreamingResponse(
            generate_sse_response(multi_agent, input_state, user_id, thread_id),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream; charset=utf-8",
                "X-Accel-Buffering": "no",
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
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream; charset=utf-8",
                "X-Accel-Buffering": "no",
            }
        ) 
