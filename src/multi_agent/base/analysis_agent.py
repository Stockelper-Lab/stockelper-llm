import json
import asyncio
from dataclasses import asdict, dataclass, field
from typing import Annotated
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.types import Command
from langgraph.graph import StateGraph
from langgraph.config import get_stream_writer
from ..utils import custom_add_messages


@dataclass
class SubState:
    messages: Annotated[list, custom_add_messages] = field(default_factory=list)
    execute_tool_count: int = field(default=0)


@dataclass
class SubConfig:
    max_execute_tool_count: int = field(default=5)


class BaseAnalysisAgent:
    def __new__(cls, model, tools, system, name):
        instance = super().__new__(cls)
        instance.__init__(model, tools, system, name)
        return instance.graph

    def __init__(self, model, tools, system, name):
        llm = ChatOpenAI(model=model)
        self.llm_with_tools = llm.bind_tools(tools)
        self.tools_by_name = {tool.name: tool for tool in tools}
        self.name = name
        self.system_message = SystemMessage(content=system)
        
        workflow = StateGraph(SubState)
        workflow.add_node("agent", self.agent)
        workflow.add_node("execute_tool", self.execute_tool)

        workflow.add_edge("__start__", "agent")
        self.graph = workflow.compile()
        self.graph.name = name

    async def agent(self, state: SubState, config: RunnableConfig):
        stream_writer = get_stream_writer()
        stream_writer({"step": self.name, "status": "start"})
        
        messages = [self.system_message] + state.messages

        result = await self.llm_with_tools.ainvoke(messages)

        if result.tool_calls and state.execute_tool_count < config["configurable"]["max_execute_tool_count"]:  # 툴 실행
            update = {"messages": [result]}
            goto = "execute_tool"
        elif result.tool_calls and state.execute_tool_count >= config["configurable"]["max_execute_tool_count"]: # 툴 실행 횟수 초과
            update = {"messages": [AIMessage(content="더 이상 실행할 수 없습니다.")]}
            goto = "__end__"
        else: # 답변 완료   
            update = {"messages": [AIMessage(content=result.content)]}
            goto = "__end__"

        stream_writer({"step": self.name, "status": "end"})
        return Command(update=update, goto=goto)

    async def execute_tool(self, state: SubState, config: RunnableConfig):
        stream_writer = get_stream_writer()
        
        outputs = []

        async def execute_single_tool(tool_call):
            """단일 tool 실행을 래핑하여 시작/끝 스트리밍 추가"""
            tool_name = tool_call["name"]
            tool = self.tools_by_name[tool_name]
            stream_writer({"step": tool_name, "status": "start"})

            try:
                result = await tool.ainvoke(
                    tool_call["args"], 
                    config={"configurable": {"user_id": config["configurable"]["user_id"]}}
                )
            except Exception as e:
                result = {
                    "error": str(e)
                }
            stream_writer({"step": tool_name, "status": "end"})
            return_direct = tool.return_direct
            return tool_call, result, return_direct

        # 모든 tool_call을 병렬로 처리하기 위한 태스크 리스트 생성
        tasks = [execute_single_tool(tool_call) for tool_call in state.messages[-1].tool_calls]

        results = await asyncio.gather(*tasks)

        # 모든 태스크 비동기적으로 실행
        return_direct = False
        for tool_call, result, tool_return_direct in results:
            outputs.append(
                ToolMessage(
                    name=tool_call["name"],
                    content=json.dumps(result, indent=2, ensure_ascii=False) if not isinstance(result, str) else result,
                    tool_call_id=tool_call["id"],
                )
            )
            return_direct |= tool_return_direct

        update = {
            "messages": outputs,
            "execute_tool_count": state.execute_tool_count + 1,
        }
        if return_direct:
            goto = "__end__"
        else:
            goto = "agent"

        return Command(update=update, goto=goto) 
