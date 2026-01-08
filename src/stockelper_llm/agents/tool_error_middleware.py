from __future__ import annotations

import os
import traceback
from typing import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command


class ToolErrorMiddleware(AgentMiddleware):
    """도구 실행 예외를 ToolMessage로 변환해 에이전트 런을 중단시키지 않게 합니다.

    Docs by LangChain 권장 패턴:
    - tool 실행 중 예외 발생 시 wrap_tool_call/awrap_tool_call에서 ToolMessage를 반환
    - async 실행(.astream/.ainvoke)에서도 동작하도록 awrap_tool_call을 구현
    """

    def __init__(self, *, debug_env: str = "DEBUG_ERRORS"):
        self._debug_env = debug_env

    def _debug_enabled(self) -> bool:
        return (os.getenv(self._debug_env) or "").lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _tool_call_id(request: ToolCallRequest) -> str:
        runtime = getattr(request, "runtime", None)
        tool_call_id = getattr(runtime, "tool_call_id", None)
        if isinstance(tool_call_id, str) and tool_call_id:
            return tool_call_id
        return "unknown"

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        try:
            return handler(request)
        except Exception as e:
            if self._debug_enabled():
                detail = traceback.format_exc()
            else:
                detail = f"{type(e).__name__}: {e}"
            return ToolMessage(
                content=(
                    "도구 실행 중 오류가 발생했습니다. 입력값/환경설정(API 키/DB 등)을 확인해주세요.\n"
                    f"에러: {detail}"
                ),
                tool_call_id=self._tool_call_id(request),
            )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            return await handler(request)
        except Exception as e:
            if self._debug_enabled():
                detail = traceback.format_exc()
            else:
                detail = f"{type(e).__name__}: {e}"
            return ToolMessage(
                content=(
                    "도구 실행 중 오류가 발생했습니다. 입력값/환경설정(API 키/DB 등)을 확인해주세요.\n"
                    f"에러: {detail}"
                ),
                tool_call_id=self._tool_call_id(request),
            )

