import asyncio
import json
import logging
import os
import re
import traceback

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from stockelper_llm.agents.backtesting_request_agent import request_backtesting_job
from stockelper_llm.agents.portfolio_request_agent import (
    request_portfolio_recommendations,
)
from stockelper_llm.core.db_urls import to_async_sqlalchemy_url, to_postgresql_conninfo
from stockelper_llm.core.langchain_compat import iter_stream_tokens, message_to_text
from stockelper_llm.multi_agent import get_multi_agent
from stockelper_llm.routers.models import ChatRequest, FinalResponse, StreamingStatus

logger = logging.getLogger(__name__)

_BACKTESTING_SERVICE_URL = os.getenv("STOCKELPER_BACKTESTING_URL", "").strip()
_PORTFOLIO_SERVICE_URL = os.getenv("STOCKELPER_PORTFOLIO_URL", "").strip()


CHECKPOINT_DATABASE_URI = to_postgresql_conninfo(
    os.getenv("CHECKPOINT_DATABASE_URI")
    or os.getenv("DATABASE_URL")
    or os.getenv("ASYNC_DATABASE_URL")
)

router = APIRouter(prefix="/stock", tags=["stock"])

_BACKTEST_PAT = re.compile(r"(백테스트|백테스팅|backtest|backtesting)", re.IGNORECASE)
_PORTFOLIO_COUNT_PAT = re.compile(r"(\d{1,3})\s*(?:개|종목)")


def _extract_portfolio_size(text: str) -> int | None:
    t = (text or "").strip()
    if not t:
        return None
    m = _PORTFOLIO_COUNT_PAT.search(t)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _is_portfolio_recommendation_request(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    if "추천" in t and "종목" in t and _extract_portfolio_size(t) is not None:
        return True

    if "리밸런" in t:
        return True
    if "자산" in t and ("배분" in t or "분배" in t):
        return True
    if "포트폴리오" in t and any(
        k in t for k in ("추천", "구성", "배분", "분배", "리밸런")
    ):
        return True
    return False


def _is_backtest_request(text: str) -> bool:
    return bool(_BACKTEST_PAT.search(text or ""))


async def generate_simple_sse(message: str):
    final_response = FinalResponse(
        type="final", message=message, subgraph={}, trading_action=None
    )
    for token in iter_stream_tokens(message):
        yield f'data: {{"type": "delta", "token": {json.dumps(token, ensure_ascii=False)} }}\n\n'
    yield f"data: {json.dumps(final_response.model_dump(), ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


async def _trigger_portfolio_recommendations(user_id: int, user_text: str) -> None:
    try:
        # 에이전트가 user_text를 기반으로 파라미터를 생성한 뒤,
        # portfolio 서버로 `/portfolio/recommendations` 요청을 보냅니다.
        await request_portfolio_recommendations(user_id=user_id, user_text=user_text)
    except Exception:
        logger.exception(
            "Failed to trigger portfolio recommendations: user_id=%s", user_id
        )


async def generate_sse_response(multi_agent, input_state, user_id: int, thread_id: str):
    try:
        if not CHECKPOINT_DATABASE_URI:
            raise RuntimeError(
                "CHECKPOINT_DATABASE_URI 또는 DATABASE_URL/ASYNC_DATABASE_URL 이 설정되어 있지 않습니다."
            )

        def _is_assistant_message(msg: object) -> bool:
            if msg is None:
                return False
            if isinstance(msg, dict):
                role = (msg.get("role") or msg.get("type") or "").lower()
                return role in {"assistant", "ai"}
            msg_type = getattr(msg, "type", None)
            return msg_type == "ai"

        last_emitted_text: str = ""

        async with AsyncConnectionPool(
            conninfo=CHECKPOINT_DATABASE_URI, kwargs={"autocommit": True}
        ) as pool:
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()

            # 그래프에 checkpointer 주입 (레거시와 동일한 패턴)
            multi_agent.checkpointer = checkpointer

            config = {
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
                    # LangGraph custom 스트림은 임의 데이터(문자열 등)도 가능하지만,
                    # 레거시 SSE 스펙은 progress(dict: step/status)만 허용하므로 그 외는 무시합니다.
                    if isinstance(response, dict):
                        streaming_response = StreamingStatus(
                            type="progress",
                            step=response.get("step", "unknown"),
                            status=response.get("status", "unknown"),
                        )
                        yield f"data: {json.dumps(streaming_response.model_dump(), ensure_ascii=False)}\n\n"
                elif response_type == "values":
                    last_msg = (
                        response.get("messages", [])[-1]
                        if response.get("messages")
                        else None
                    )
                    if _is_assistant_message(last_msg):
                        message_text = message_to_text(last_msg)
                        if message_text and message_text != last_emitted_text:
                            for token in iter_stream_tokens(message_text):
                                yield f'data: {{"type": "delta", "token": {json.dumps(token, ensure_ascii=False)} }}\n\n'
                            last_emitted_text = message_text

                        final_response = FinalResponse(
                            type="final",
                            message=message_text,
                            subgraph=response.get("subgraph", {}) or {},
                            trading_action=response.get("trading_action"),
                        )

            yield f"data: {json.dumps(final_response.model_dump(), ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    except Exception as e:
        logger.exception("Error in generate_sse_response")
        debug = os.getenv("DEBUG_ERRORS", "false").lower() in {"1", "true", "yes"}
        err_text = traceback.format_exc() if debug else f"{type(e).__name__}: {e}"
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
    async_db_url = to_async_sqlalchemy_url(
        os.getenv("ASYNC_DATABASE_URL") or os.getenv("DATABASE_URL")
    )
    if not async_db_url:
        raise RuntimeError(
            "ASYNC_DATABASE_URL 또는 DATABASE_URL 이 설정되어 있지 않습니다."
        )

    user_id = request.user_id
    thread_id = request.thread_id
    query = request.message
    human_feedback = request.human_feedback

    logger.info(
        "Received query: user_id=%s thread_id=%s query=%s", user_id, thread_id, query
    )

    if human_feedback is None:
        if _is_portfolio_recommendation_request(query):
            if not _PORTFOLIO_SERVICE_URL:
                guide = (
                    "포트폴리오 추천 기능은 포트폴리오 추천 페이지에서 확인할 수 있습니다.\n"
                    "현재 포트폴리오 추천 서버(STOCKELPER_PORTFOLIO_URL)가 설정되어 있지 않습니다.\n"
                    "관리자에게 문의해주세요."
                )
            else:
                portfolio_size = _extract_portfolio_size(query)
                if portfolio_size is not None and not (1 <= portfolio_size <= 20):
                    msg = (
                        "포트폴리오 추천 종목 개수는 현재 1~20개까지만 지원합니다.\n"
                        f"(요청하신 값: {portfolio_size}개)\n"
                        "예) '10개 종목을 추천해줘'"
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

                asyncio.create_task(
                    _trigger_portfolio_recommendations(user_id, user_text=query)
                )
                guide = "포트폴리오 추천을 생성 중입니다.\n"
                if portfolio_size is not None:
                    guide += f"(요청 개수: {portfolio_size}개)\n"
                guide += (
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

        if _is_backtest_request(query):
            if not _BACKTESTING_SERVICE_URL:
                msg = (
                    "백테스팅 기능은 별도 서비스로 분리되어 있습니다.\n"
                    "백테스팅 서버를 실행한 뒤, 환경변수 STOCKELPER_BACKTESTING_URL을 설정해주세요.\n"
                    "예) STOCKELPER_BACKTESTING_URL=http://localhost:21007"
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
                # 포트폴리오 트리거와 동일 선상: "요청 변환(LLM) + API 호출"을 에이전트로 분리
                # - 내부에서 LLM(structured output)로 parameters를 만들고,
                # - backtesting 서버에 /api/backtesting/execute 요청을 보냅니다.
                data = await request_backtesting_job(user_id=user_id, user_text=query)
                # 플래너가 "추가 정보 필요/거부"를 반환한 경우: job 생성 없이 사용자에게 안내
                if isinstance(data, dict) and data.get("status") in {
                    "needs_clarification",
                    "denied",
                }:
                    msg = (data.get("message") or "").strip() or (
                        "백테스팅을 위해 추가 정보가 필요합니다.\n"
                        "예) '삼성전자(005930) 2023년 백테스트'"
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

                job_id = data.get("job_id") or data.get("jobId")
            except Exception:
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

            msg = f"백테스팅을 시작했습니다. (job_id={job_id})\n약 5~10분 정도 소요될 수 있습니다."
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

        # NOTE: agent_results/execute_agent_count 등은 "요청 1회" 단위로 리셋합니다.
        # 대화 메시지(messages)는 누적되지만, 분석 결과/트레이딩 액션은 이전 턴의 잔재가 남지 않게 합니다.
        input_state = {
            "messages": [{"role": "user", "content": query}],
            "agent_messages": [],
            "agent_results": [],
            "execute_agent_count": 0,
            "trading_action": {},
            "stock_name": "None",
            "stock_code": "None",
            "subgraph": {},
        }
    else:
        # NOTE: 이번 프로젝트에서는 주문 실행/승인(interrupt-resume) 흐름을 사용하지 않습니다.
        msg = (
            "이번 프로젝트에서는 트레이딩 주문 실행(승인/거부) 기능을 지원하지 않습니다.\n"
            "대신 투자전략 '추천'만 제공합니다. 질문을 다시 입력해주세요."
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

    multi_agent = await get_multi_agent(async_db_url)

    return StreamingResponse(
        generate_sse_response(multi_agent, input_state, user_id, thread_id),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream; charset=utf-8",
            "X-Accel-Buffering": "no",
        },
    )
