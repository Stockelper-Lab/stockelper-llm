from __future__ import annotations

from typing import Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Command


class ProgressMiddleware(AgentMiddleware):
    """레거시 SSE 스펙(progress: step/status start|end)으로 custom 스트림 이벤트를 방출합니다.

    NOTE: create_agent를 async(.astream/.ainvoke)로 실행할 때는 `awrap_tool_call`이 필요합니다.
    데코레이터 기반(@wrap_tool_call) 훅은 sync만 등록되는 경우가 있어, 클래스로 명시 구현합니다.
    """

    def __init__(self, agent_step_name: str):
        self.agent_step_name = agent_step_name

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        try:
            runtime.stream_writer({"step": self.agent_step_name, "status": "start"})
        except Exception:
            try:
                get_stream_writer()({"step": self.agent_step_name, "status": "start"})
            except Exception:
                pass
        return None

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        try:
            runtime.stream_writer({"step": self.agent_step_name, "status": "end"})
        except Exception:
            try:
                get_stream_writer()({"step": self.agent_step_name, "status": "end"})
            except Exception:
                pass
        return None

    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self.before_agent(state, runtime)

    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self.after_agent(state, runtime)

    @staticmethod
    def _tool_name(request: ToolCallRequest) -> str:
        tool_call = getattr(request, "tool_call", None)
        if isinstance(tool_call, dict):
            return tool_call.get("name") or "tool"
        name = getattr(tool_call, "name", None)
        if isinstance(name, str) and name:
            return name
        if tool_call is not None:
            try:
                return tool_call["name"]  # type: ignore[index]
            except Exception:
                pass
        return "tool"

    @staticmethod
    def _writer_from_request(request: ToolCallRequest):
        writer = getattr(getattr(request, "runtime", None), "stream_writer", None)
        if writer is not None:
            return writer
        try:
            return get_stream_writer()
        except Exception:
            return None

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        tool_name = self._tool_name(request)
        writer = self._writer_from_request(request)
        if writer is not None:
            try:
                writer({"step": tool_name, "status": "start"})
            except Exception:
                pass
        try:
            return handler(request)
        finally:
            if writer is not None:
                try:
                    writer({"step": tool_name, "status": "end"})
                except Exception:
                    pass

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        tool_name = self._tool_name(request)
        writer = self._writer_from_request(request)
        if writer is not None:
            try:
                writer({"step": tool_name, "status": "start"})
            except Exception:
                pass
        try:
            return await handler(request)
        finally:
            if writer is not None:
                try:
                    writer({"step": tool_name, "status": "end"})
                except Exception:
                    pass


def make_progress_middleware(agent_step_name: str):
    """progress 이벤트를 LangGraph custom stream으로 방출하는 미들웨어 팩토리."""
    return [ProgressMiddleware(agent_step_name)]

