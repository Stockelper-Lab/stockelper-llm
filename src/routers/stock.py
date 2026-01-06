import asyncio
import os
import json
import logging
import re
import traceback
import httpx
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from db_urls import to_async_sqlalchemy_url, to_postgresql_conninfo
from multi_agent import get_multi_agent
from langchain_compat import iter_stream_tokens, message_to_text
from .models import ChatRequest, StreamingStatus, FinalResponse

logger = logging.getLogger(__name__)

_LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() not in {"0", "false", "no"}
_BACKTESTING_SERVICE_URL = os.getenv("STOCKELPER_BACKTESTING_URL", "").strip()
_PORTFOLIO_SERVICE_URL = os.getenv("STOCKELPER_PORTFOLIO_URL", "").strip()

# LangChain v1에서 langfuse.langchain 통합이 깨질 수 있어(legacy import 의존),
# Langfuse는 옵션으로만 활성화한다.
_langfuse_handler = None
if _LANGFUSE_ENABLED:
    try:
        from langfuse.langchain import CallbackHandler  # type: ignore

        _langfuse_handler = CallbackHandler()
    except Exception:
        _langfuse_handler = None

CHECKPOINT_DATABASE_URI = to_postgresql_conninfo(
    os.getenv("CHECKPOINT_DATABASE_URI")
    or os.getenv("DATABASE_URL")
    or os.getenv("ASYNC_DATABASE_URL")
)

router = APIRouter(prefix="/stock", tags=["stock"])

_BACKTEST_PAT = re.compile(r"(백테스트|백테스팅|backtest|backtesting)", re.IGNORECASE)


def _is_portfolio_recommendation_request(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    # 케이스: "포트폴리오 추천해줘", "포트폴리오 구성", "리밸런싱", "자산 배분" 등
    if "리밸런" in t:
        return True
    if "자산" in t and ("배분" in t or "분배" in t):
        return True
    if "포트폴리오" in t and any(k in t for k in ("추천", "구성", "배분", "분배", "리밸런")):
        return True
    return False


def _is_backtest_request(text: str) -> bool:
    return bool(_BACKTEST_PAT.search(text or ""))


async def generate_simple_sse(message: str):
    """멀티에이전트를 실행하지 않는 단순 SSE 응답(차단/가이드/즉시응답)."""
    final_response = FinalResponse(type="final", message=message, subgraph={}, trading_action=None)
    for token in iter_stream_tokens(message):
        yield f"data: {{\"type\": \"delta\", \"token\": {json.dumps(token, ensure_ascii=False)} }}\n\n"
    yield f"data: {json.dumps(final_response.model_dump(), ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


async def _trigger_portfolio_recommendations(user_id: int) -> None:
    """포트폴리오 추천 API를 호출해 추천 서버 실행 및 DB 적재를 트리거합니다.

    NOTE: 채팅창에는 결과를 보여주지 않습니다(페이지에서 확인 유도).
    """
    base = _PORTFOLIO_SERVICE_URL.rstrip("/")
    if not base:
        logger.warning("STOCKELPER_PORTFOLIO_URL is not set; skip portfolio trigger")
        return

    timeout_s = float(os.getenv("PORTFOLIO_REQUESTS_TIMEOUT", "") or os.getenv("REQUESTS_TIMEOUT", "300") or 300)
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                f"{base}/portfolio/recommendations",
                json={"user_id": user_id},
            )
            # portfolio 서버는 내부에서 DB 적재를 수행할 예정이므로, 여기선 성공/실패만 로깅합니다.
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("detail")
                except Exception:
                    detail = resp.text
                raise RuntimeError(f"portfolio API error ({resp.status_code}): {detail}")

        logger.info("Triggered portfolio recommendations: user_id=%s", user_id)
    except Exception:
        logger.exception("Failed to trigger portfolio recommendations: user_id=%s", user_id)


async def generate_sse_response(multi_agent, input_state, user_id, thread_id):
    """풀의 생명주기를 스트리밍과 맞춰 관리하는 SSE 응답 생성기"""
    try:
        if not CHECKPOINT_DATABASE_URI:
            raise RuntimeError(
                "CHECKPOINT_DATABASE_URI 또는 DATABASE_URL/ASYNC_DATABASE_URL 이 설정되어 있지 않습니다."
            )

        def _is_assistant_message(msg: object) -> bool:
            if msg is None:
                return False
            # dict 형태(compat)
            if isinstance(msg, dict):
                role = (msg.get("role") or msg.get("type") or "").lower()
                return role in {"assistant", "ai"}
            # LangChain BaseMessage 계열
            msg_type = getattr(msg, "type", None)
            return msg_type == "ai"

        last_emitted_text: str = ""

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
                    # assistant 메시지만 토큰 단위(delta)로 스트리밍 후 마지막에 final 전송
                    last_msg = response.get("messages", [])[-1] if response.get("messages") else None
                    if _is_assistant_message(last_msg):
                        message_text = message_to_text(last_msg)
                        if message_text and message_text != last_emitted_text:
                            for token in iter_stream_tokens(message_text):
                                yield f"data: {{\"type\": \"delta\", \"token\": {json.dumps(token, ensure_ascii=False)} }}\n\n"
                            last_emitted_text = message_text

                        final_response = FinalResponse(
                            type="final",
                            message=message_text,
                            subgraph=response.get("subgraph", {}) or {},
                            trading_action=response.get("trading_action"),
                        )
            # 최종 응답과 종료 신호 전송
            yield f"data: {json.dumps(final_response.model_dump(), ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.exception("Error in generate_sse_response")
        debug = os.getenv("DEBUG_ERRORS", "false").lower() in {"1", "true", "yes"}
        err_text = traceback.format_exc() if debug else f"{type(e).__name__}: {e}"
        # 에러 발생 시 에러 응답 전송
        error_response = FinalResponse(
            message="처리 중 오류가 발생했습니다.",
            error=err_text,
            subgraph={},
            trading_action=None,
        )
        yield f"data: {json.dumps(error_response.model_dump(), ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"


@router.post("/chat", status_code=status.HTTP_200_OK)
async def stock_chat(request: ChatRequest) -> StreamingResponse:
    try:
        # 멀티에이전트 인스턴스 확보 (캐시)
        async_db_url = to_async_sqlalchemy_url(
            os.getenv("ASYNC_DATABASE_URL") or os.getenv("DATABASE_URL")
        )
        if not async_db_url:
            raise RuntimeError("ASYNC_DATABASE_URL 또는 DATABASE_URL 이 설정되어 있지 않습니다.")

        multi_agent = get_multi_agent(async_db_url)
        user_id = request.user_id
        thread_id = request.thread_id
        query = request.message
        human_feedback = request.human_feedback

        logger.info(f"Received query: {query}")

        # 입력 상태 구성
        if human_feedback is None:
            # 포트폴리오 추천: 백엔드에서는 추천 API를 호출(=추천 서버 실행/DB 적재),
            # 채팅창에서는 전용 페이지로 이동 안내만 반환
            if _is_portfolio_recommendation_request(query):
                if not _PORTFOLIO_SERVICE_URL:
                    guide = (
                        "포트폴리오 추천 기능은 포트폴리오 추천 페이지에서 확인할 수 있습니다.\n"
                        "현재 포트폴리오 추천 서버(STOCKELPER_PORTFOLIO_URL)가 설정되어 있지 않습니다.\n"
                        "관리자에게 문의해주세요."
                    )
                else:
                    # 추천 서버를 백그라운드로 트리거하고(출력은 추천 서버가 DB에 저장),
                    # 챗봇은 안내만 합니다.
                    asyncio.create_task(_trigger_portfolio_recommendations(user_id))
                    guide = (
                        "포트폴리오 추천을 생성 중입니다.\n"
                        "포트폴리오 추천 페이지로 이동해서 결과를 확인해주세요.\n"
                        "(생성에는 몇 분 정도 걸릴 수 있습니다.)"
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
